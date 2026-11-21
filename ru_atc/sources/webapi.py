"""Источник данных через встроенный Web API X-Plane 12 (12.1.1+).

Документация: https://developer.x-plane.com/article/x-plane-web-api/
  REST:      GET http://localhost:8086/api/v{N}/datarefs?filter[name]=...&fields=id,name,value_type
  WebSocket: ws://localhost:8086/api/v{N}
             -> {"req_id":1,"type":"dataref_subscribe_values","params":{"datarefs":[{"id":..,"index":[0,1]}]}}
             <- {"type":"dataref_update_values","data":{"<id>": value}}   (10 Гц, только изменения)
ID datarefs действительны только в текущей сессии X-Plane — ищем их заново при каждом подключении.
Пока не загружен полёт, список datarefs пуст.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Dict, List, Tuple

from .base import DataSource
from ..datarefs import all_specs

log = logging.getLogger(__name__)


def build_name_query(names: List[str], with_fields: bool = True) -> str:
    # Квадратные скобки оставляем как есть: не все версии X-Plane декодируют filter%5Bname%5D
    parts = [("filter[name]", n) for n in names]
    if with_fields:
        parts.append(("fields", "id,name,value_type"))
    return urllib.parse.urlencode(parts, safe="[]/")


def group_specs(specs) -> "OrderedDict[str, List]":
    """Сгруппировать спецификации по имени dataref (N1[0], N1[1] -> одна подписка с index [0,1])."""
    groups: "OrderedDict[str, List]" = OrderedDict()
    for s in specs:
        groups.setdefault(s.name, []).append(s)
    return groups


def decode_update(data: Dict[str, object], id_map: Dict[int, List]) -> Dict[str, float]:
    """Разобрать data из dataref_update_values в {key: value}."""
    out: Dict[str, float] = {}
    for sid, val in data.items():
        try:
            did = int(str(sid).strip())
        except ValueError:
            continue
        specs = id_map.get(did)
        if not specs:
            continue
        indexed = [s for s in specs if s.index is not None]
        if indexed:
            vals = val if isinstance(val, list) else [val]
            # Сервер отдаёт элементы в порядке возрастания запрошенных индексов, без разрежения
            for pos, s in enumerate(sorted(indexed, key=lambda x: x.index)):
                if pos < len(vals):
                    out[s.key] = vals[pos]
        else:
            if isinstance(val, list):
                val = val[0] if val else 0
            if isinstance(val, str):   # тип data (base64) — нам не нужен
                continue
            out[specs[0].key] = val
    return out


class WebApiSource(DataSource):
    name = "webapi"

    def __init__(self, host: str = "localhost", port: int = 8086, use_zibo: bool = True,
                 api_version: str = "auto") -> None:
        super().__init__()
        # "localhost" на Windows может уйти в IPv6 (::1) — X-Plane слушает IPv4
        if str(host).strip().lower() == "localhost":
            host = "127.0.0.1"
        self.host, self.port = host, port
        self.use_zibo = use_zibo
        self.api_version = api_version
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self.missing: List[str] = []
        self.ws_alive = False

    def is_connected(self) -> bool:
        # Web API присылает только ИЗМЕНИВШИЕСЯ значения: на стоянке сообщений может не быть долго,
        # поэтому «на связи» = WebSocket открыт и хотя бы одно обновление уже пришло.
        return self.ws_alive and self.last_update > 0

    # ---------- REST ----------
    def _get(self, path: str, timeout: float = 3.0):
        url = f"http://{self.host}:{self.port}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        # Локальный X-Plane: никаких системных прокси/VPN (на Windows urllib берёт прокси из реестра)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            r = opener.open(req, timeout=timeout)
        except OSError as e:
            raise OSError(f"REST {url}: {e}") from e
        with r:
            return json.loads(r.read().decode("utf-8"))

    def detect_version(self) -> str:
        if self.api_version != "auto":
            return self.api_version
        try:
            caps = self._get("/api/capabilities")
            versions = caps.get("api", {}).get("versions", [])
            # Для datarefs достаточно v1; берём максимальную доступную
            return sorted(versions, key=lambda v: int(v.lstrip("v")))[-1] if versions else "v1"
        except Exception:
            return "v1"  # 12.1.1–12.1.3: эндпоинта capabilities нет

    def resolve_ids(self, ver: str, names: List[str]) -> Dict[str, int]:
        ids: Dict[str, int] = {}
        errors: List[str] = []
        # По одному запросу на имя: если хоть одно имя неизвестно, пакетный запрос вернёт 404
        for n in names:
            for with_fields in (True, False):
                try:
                    res = self._get(f"/api/{ver}/datarefs?" + build_name_query([n], with_fields))
                    for d in res.get("data", []):
                        ids[d["name"]] = int(d["id"])
                    break
                except Exception as e:  # 404 invalid_dataref_name, 400 и т.п.
                    errors.append(f"{n}: {e}")
                    log.debug("dataref %s не найден: %s", n, e)
        if not ids:
            # Запасной путь: забираем весь список datarefs и ищем имена у себя
            try:
                res = self._get(f"/api/{ver}/datarefs", timeout=30.0)
                wanted = set(names)
                for d in res.get("data", []):
                    if d.get("name") in wanted:
                        ids[d["name"]] = int(d["id"])
                log.info("Web API: datarefs найдены через полный список (%d из %d)", len(ids), len(names))
            except Exception as e:
                errors.append(f"полный список: {e}")
        if not ids and errors:
            log.warning("Web API %s: ни один dataref не найден. Первые ошибки: %s", ver, "; ".join(errors[:3]))
        return ids

    # ---------- поток ----------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="xp-webapi", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def _run(self) -> None:
        try:
            import websocket  # websocket-client
        except ImportError:
            self.error = "Не установлен пакет websocket-client (pip install websocket-client)"
            log.error(self.error)
            return
        while not self._stop.is_set():
            try:
                ver = self.detect_version()
                groups = group_specs(all_specs(self.use_zibo))
                ids = self.resolve_ids(ver, list(groups))
                if not ids:
                    raise RuntimeError("X-Plane не вернул datarefs (полёт ещё не загружен?)")
                self.missing = [n for n in groups if n not in ids]
                for n in self.missing:
                    level = logging.DEBUG if groups[n][0].optional else logging.WARNING
                    log.log(level, "dataref недоступен: %s", n)
                id_map: Dict[int, List] = {ids[n]: groups[n] for n in ids}
                sub = []
                for n, did in ids.items():
                    idx = sorted(s.index for s in groups[n] if s.index is not None)
                    sub.append({"id": did, "index": idx} if idx else {"id": did})
                ws_url = f"ws://{self.host}:{self.port}/api/{ver}"
                try:
                    # http_no_proxy/proxy_type=None: не идём через системный прокси
                    self._ws = websocket.create_connection(ws_url, timeout=5, http_proxy_host=None,
                                                           http_no_proxy=["localhost", "127.0.0.1", self.host])
                except OSError as e:
                    raise OSError(f"WebSocket {ws_url}: {e}") from e
                self._ws.send(json.dumps({"req_id": 1, "type": "dataref_subscribe_values",
                                          "params": {"datarefs": sub}}))
                log.info("Web API %s: подписка на %d datarefs", ver, len(sub))
                self.error = None
                self.ws_alive = True
                while not self._stop.is_set():
                    try:
                        msg = json.loads(self._ws.recv())
                    except websocket.WebSocketTimeoutException:
                        continue      # данных нет — значения не менялись, соединение живо
                    if msg.get("type") == "dataref_update_values":
                        self._update_raw(decode_update(msg.get("data", {}), id_map))
                    elif msg.get("type") == "result" and not msg.get("success", True):
                        log.warning("Web API ошибка: %s", msg)
            except Exception as e:
                self.ws_alive = False
                self.error = f"Web API: {e}"
                log.warning("%s — повтор через 3 с", self.error)
                time.sleep(3)
