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

import base64
import binascii
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

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


def normalize_host(host: str) -> str:
    # "localhost" на Windows может уйти в IPv6 (::1) — X-Plane слушает IPv4
    return "127.0.0.1" if str(host).strip().lower() == "localhost" else str(host).strip()


def rest_send(host: str, port: int, method: str, path: str, payload: Optional[dict] = None,
              timeout: float = 3.0):
    """HTTP к Web API без системного прокси. Пустой ответ (PATCH 200) — это {}."""
    url = f"http://{host}:{port}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = opener.open(req, timeout=timeout)
    except OSError as e:
        raise OSError(f"REST {method} {url}: {e}") from e
    with r:
        raw = r.read()
    if not raw or not raw.strip():
        return {}
    return json.loads(raw.decode("utf-8"))


def rest_get(host: str, port: int, path: str, timeout: float = 3.0):
    """GET к Web API X-Plane, без системного прокси/VPN (urllib на Windows берёт прокси из реестра)."""
    return rest_send(host, port, "GET", path, timeout=timeout)


def _printable_ratio(s: str) -> float:
    if not s:
        return 1.0
    good = sum(1 for c in s if 32 <= ord(c) < 127 or c in "\r\n\t")
    return good / len(s)


def decode_data_value(val) -> str:
    """Значение dataref типа data -> обычная строка.

    Ранний Web API отдавал data как base64. В v3 (дамп CDU Zibo, ноябрь 2026) это уже
    обычный текст: «ACT PERF INIT», legs_pth «TFTFDF…». Строгий base64 принимаем только
    если декод сам похож на текст; иначе оставляем исходную строку (она случайно
    состоит из алфавита base64).
    """
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        raw = bytes(val)
        return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
    if isinstance(val, list):   # на всякий случай: массив байтов
        try:
            raw = bytes(int(x) & 0xFF for x in val)
        except (TypeError, ValueError):
            return ""
        return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
    if not isinstance(val, str):
        return str(val)
    try:
        raw = base64.b64decode(val, validate=True)
    except (binascii.Error, ValueError):
        return val
    dec = raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
    if val.strip() and not dec:
        return val
    if _printable_ratio(val) >= 0.9 and _printable_ratio(dec) < 0.9:
        return val
    return dec


class WebApiRest:
    """Минимальный REST-клиент Web API: поиск id, полный список, чтение значений (в т.ч. строк)."""

    def __init__(self, host: str = "localhost", port: int = 8086, api_version: str = "auto") -> None:
        self.host, self.port = normalize_host(host), int(port)
        self.api_version = api_version
        self.ver = ""
        self.info: Dict[str, Tuple[int, str]] = {}   # name -> (id, value_type)

    def get(self, path: str, timeout: float = 3.0):
        return rest_get(self.host, self.port, path, timeout)

    def connect(self) -> str:
        if self.api_version != "auto":
            self.ver = self.api_version
        else:
            try:
                caps = self.get("/api/capabilities")
                versions = caps.get("api", {}).get("versions", [])
                self.ver = sorted(versions, key=lambda v: int(v.lstrip("v")))[-1] if versions else "v1"
            except Exception as e:
                # capabilities нет в 12.1.1–12.1.3 (сервер ответит 404) — тогда v1;
                # если сервер не отвечает вовсе — ошибка подключения
                if not isinstance(e.__cause__, urllib.error.HTTPError):
                    raise
                self.ver = "v1"
        return self.ver

    def resolve(self, names: List[str]) -> Dict[str, Tuple[int, str]]:
        found: Dict[str, Tuple[int, str]] = {}
        for n in names:
            for with_fields in (True, False):
                try:
                    res = self.get(f"/api/{self.ver}/datarefs?" + build_name_query([n], with_fields))
                    for d in res.get("data", []):
                        found[d["name"]] = (int(d["id"]), str(d.get("value_type", "")))
                    break
                except Exception:
                    continue
        self.info.update(found)
        return found

    def list_all(self, timeout: float = 30.0) -> List[Dict]:
        res = self.get(f"/api/{self.ver}/datarefs", timeout=timeout)
        return list(res.get("data", []))

    def discover(self, prefixes: Tuple[str, ...]) -> Dict[str, Tuple[int, str]]:
        """Все datarefs, чьё имя начинается с одного из префиксов (через полный список)."""
        out: Dict[str, Tuple[int, str]] = {}
        low = tuple(p.lower() for p in prefixes)
        for d in self.list_all():
            name = str(d.get("name", ""))
            if name.lower().startswith(low):
                out[name] = (int(d["id"]), str(d.get("value_type", "")))
        self.info.update(out)
        return out

    def value(self, name: str, timeout: float = 2.0):
        """Текущее значение dataref по имени (id должен быть найден resolve/discover).
        Строки (тип data) возвращаются уже декодированными."""
        did, vtype = self.info[name]
        res = self.get(f"/api/{self.ver}/datarefs/{did}/value", timeout=timeout)
        val = res.get("data") if isinstance(res, dict) else res
        if vtype == "data" or (isinstance(val, str) and vtype in ("", "data")):
            return decode_data_value(val)
        return val


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
        self.api_ver = ""

    def is_connected(self) -> bool:
        # Web API присылает только ИЗМЕНИВШИЕСЯ значения: на стоянке сообщений может не быть долго,
        # поэтому «на связи» = WebSocket открыт и хотя бы одно обновление уже пришло.
        return self.ws_alive and self.last_update > 0

    # ---------- REST ----------
    def _get(self, path: str, timeout: float = 3.0):
        return rest_get(self.host, self.port, path, timeout)

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
                self.api_ver = ver
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

    def tune_com1(self, khz: int) -> Tuple[bool, str]:
        """Резерв COM1, обмен с активной, иначе запись активной частоты.

        Dataref ``com1_*_frequency_hz_833`` — целое в кГц (121800 = 121.800).
        Команда ``sim/radios/com1_standy_flip`` есть с Web API v2. Zibo читает
        эти же штатные dataref, отдельный dataref кабины не требуется.
        """
        from ..radio import COM1_ACTIVE, COM1_FLIP, COM1_STANDBY, describe_tune, khz_value
        ver = self.api_ver
        if not ver:
            return False, "Web API ещё не подключен, COM1 не перестроен"
        try:
            value = khz_value(khz)
        except ValueError as e:
            return False, str(e)
        try:
            standby = self.resolve_ids(ver, [COM1_STANDBY]).get(COM1_STANDBY)
            active = self.resolve_ids(ver, [COM1_ACTIVE]).get(COM1_ACTIVE)
        except Exception as e:
            return False, f"COM1: не удалось найти dataref ({e})"
        if not standby and not active:
            return False, "COM1: X-Plane не отдал dataref частоты"
        flipped = False
        wrote_active = False
        try:
            if standby:
                rest_send(self.host, self.port, "PATCH", f"/api/{ver}/datarefs/{standby}/value",
                          {"data": value})
            cmd = self._flip_command_id(ver) if _version_at_least(ver, 2) else None
            if cmd:
                rest_send(self.host, self.port, "POST", f"/api/{ver}/command/{cmd}/activate",
                          {"duration": 0})
                flipped = True
            if active:
                rest_send(self.host, self.port, "PATCH", f"/api/{ver}/datarefs/{active}/value",
                          {"data": value})
                wrote_active = True
        except Exception as e:
            return False, f"COM1 не перестроен: {e}"
        if not standby and not wrote_active:
            return False, "COM1: нет доступного dataref"
        return True, describe_tune(value, flipped=flipped, wrote_active=wrote_active)

    def _flip_command_id(self, ver: str) -> Optional[int]:
        from ..radio import COM1_FLIP
        try:
            res = self._get(f"/api/{ver}/commands?" + build_name_query([COM1_FLIP], with_fields=False))
        except Exception as e:
            log.info("Команда %s недоступна: %s", COM1_FLIP, e)
            return None
        for item in res.get("data", []):
            if item.get("name") == COM1_FLIP and int(item.get("id") or 0) > 0:
                return int(item["id"])
        return None


def _version_at_least(ver: str, number: int) -> bool:
    digits = "".join(ch for ch in str(ver) if ch.isdigit())
    try:
        return int(digits or "0") >= number
    except ValueError:
        return False
