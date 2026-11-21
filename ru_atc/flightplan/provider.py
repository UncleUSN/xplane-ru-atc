"""Источник плана полёта: FMC Zibo (экран CDU + datarefs laminar/B738/fms/*) через Web API,
последний .fms из <X-Plane>/Output/FMS plans и config.yaml как запасной вариант.

Приоритет полей: CDU (страницы DEP/ARR, RTE, PERF INIT) > datarefs Zibo > .fms (только если
ADEP/ADES совпадают с FMC или FMC пуст) > config.yaml (решает контроллер).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .cdu import CduCollector, Screen, cdu_dataref_names, page_kind
from .fms_file import fms_dir, latest_fms, list_fms, load_fms
from .model import FlightPlan
from . import zibo_refs

log = logging.getLogger(__name__)

RELEVANT_PAGES = ("rte", "dep", "arr", "perf", "legs")
KNOWN_FMS_REFS = ["laminar/B738/fms/legs", "laminar/B738/fms/num_of_wpts", "laminar/B738/fms/legs_lat",
                  "laminar/B738/fms/legs_lon"]
MAX_ZIBO_REFS = 80


def import_settings(cfg: Dict) -> Dict:
    imp = dict(cfg.get("flight_plan_import") or {})
    imp.setdefault("source", "auto")
    imp.setdefault("fmc_side", 1)
    imp.setdefault("poll_s", 2.0)
    imp.setdefault("xplane_path", "")
    imp.setdefault("fms_max_age_h", 12)
    imp.setdefault("callsign_from_fmc", True)
    return imp


class FlightPlanProvider:
    def __init__(self, cfg: Dict, rest=None, on_change: Optional[Callable[[FlightPlan], None]] = None) -> None:
        imp = import_settings(cfg)
        self.mode = str(imp["source"]).lower()
        self.side = int(imp["fmc_side"] or 1)
        self.poll_s = float(imp["poll_s"])
        self.xplane_path = str(imp.get("xplane_path") or "")
        self.max_age_h = float(imp["fms_max_age_h"] or 0)
        sim = cfg.get("sim", {})
        self.use_webapi = self.mode in ("auto", "fmc") and sim.get("source") == "webapi"
        self.use_fms = self.mode in ("auto", "fms")
        if rest is None and self.use_webapi:
            from ..sources.webapi import WebApiRest
            rest = WebApiRest(sim.get("host", "localhost"), int(sim.get("webapi_port", 8086)),
                              sim.get("webapi_version", "auto"))
        self.rest = rest if self.use_webapi else None
        self.on_change = on_change
        self.collector = CduCollector()
        self.cdu_names: List[str] = []
        self.zibo_names: List[str] = []
        self.zibo_values: Dict[str, object] = {}
        self.cdu_values: Dict[str, str] = {}
        self.connected = False
        self.next_connect = 0.0
        self.next_zibo = 0.0
        self.next_fms = 0.0
        self.fail_count = 0
        self.errors: List[str] = []
        self.fms_path: Optional[Path] = None
        self.fms_cache: Dict[Tuple[str, float], FlightPlan] = {}
        self.fms_plan: Optional[FlightPlan] = None
        self.plan = FlightPlan()
        self._last_key = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------ Web API
    def _err(self, msg: str) -> None:
        if self.errors and self.errors[-1] == msg:
            return            # не засоряем лог одинаковыми сообщениями при переподключении
        log.info("План полёта: %s", msg)
        self.errors = (self.errors + [msg])[-10:]

    def connect(self) -> bool:
        self.connected = False
        try:
            self.rest.connect()
        except Exception as e:
            self._err(f"Web API недоступен: {e}")
            return False
        pfx_cdu = f"laminar/B738/fmc{self.side}/"
        found = {}
        try:
            found = self.rest.discover((pfx_cdu,) + zibo_refs.PREFIXES)
        except Exception as e:
            self._err(f"полный список datarefs не получен ({e}) — ищу по именам")
            try:
                found = self.rest.resolve(cdu_dataref_names(self.side) + KNOWN_FMS_REFS)
            except Exception as e2:
                self._err(f"поиск datarefs не удался: {e2}")
        wanted = set(cdu_dataref_names(self.side))
        self.cdu_names = [n for n in cdu_dataref_names(self.side) if n in found]
        zib = [n for n in found if n.lower().startswith(tuple(p.lower() for p in zibo_refs.PREFIXES))
               and n not in wanted and zibo_refs.is_interesting(n)]
        # строки (data) и известные имена — в первую очередь
        zib.sort(key=lambda n: (0 if n in KNOWN_FMS_REFS else 1 if found[n][1] == "data" else 2, n))
        self.zibo_names = zib[:MAX_ZIBO_REFS]
        if not self.cdu_names and not self.zibo_names:
            self._err("datarefs FMC Zibo не найдены (самолёт не Zibo или полёт ещё не загружен)")
            return False
        self.connected = True
        self.fail_count = 0
        log.info("План полёта: найдено %d строк CDU, %d datarefs FMS Zibo", len(self.cdu_names), len(self.zibo_names))
        return True

    def read_cdu(self) -> Optional[Screen]:
        if not self.cdu_names:
            return None
        title_names = [n for n in self.cdu_names if "/Line00_" in n]
        vals: Dict[str, str] = {}
        for n in title_names:
            vals[n] = self.rest.value(n)
        title = Screen.from_values(vals, self.side).title
        if page_kind(title) in RELEVANT_PAGES:
            for n in self.cdu_names:
                if n not in vals:
                    vals[n] = self.rest.value(n)
        self.cdu_values = vals
        return Screen.from_values(vals, self.side)

    def read_zibo(self) -> None:
        vals = {}
        for n in self.zibo_names:
            try:
                vals[n] = self.rest.value(n)
            except Exception as e:
                vals[n] = None
                log.debug("dataref %s: %s", n, e)
        self.zibo_values = vals

    # ------------------------------------------------------------ .fms
    def read_fms(self, live: FlightPlan) -> None:
        d = fms_dir(self.xplane_path)
        if d is None:
            if self.xplane_path:
                self._err(f"папка 'Output/FMS plans' не найдена в {self.xplane_path}")
            self.fms_plan, self.fms_path = None, None
            return
        f = latest_fms(d, live.origin, live.dest, self.max_age_h)
        if f is None:
            self.fms_plan, self.fms_path = None, None
            return
        try:
            k = (str(f), f.stat().st_mtime)
            if k not in self.fms_cache:
                self.fms_cache[k] = load_fms(f)
            self.fms_plan, self.fms_path = self.fms_cache[k], f
        except (OSError, ValueError) as e:
            self._err(f"не удалось прочитать {f.name}: {e}")
            self.fms_plan = None

    # ------------------------------------------------------------ слияние
    def merge(self) -> FlightPlan:
        live = self.collector.plan()
        zp = zibo_refs.plan_from_values(self.zibo_values) if self.zibo_values else FlightPlan()
        # datarefs Zibo не должны противоречить экрану: берём, только если аэропорты не конфликтуют
        if not ((live.origin and zp.origin and live.origin != zp.origin) or
                (live.dest and zp.dest and live.dest != zp.dest)):
            live.fill_from(zp)
        fp = live
        f = self.fms_plan
        if f is not None and (not fp.origin or fp.origin == f.origin) and (not fp.dest or fp.dest == f.dest):
            route_ok = any(w.has_pos for w in f.waypoints)
            if route_ok:     # точки с координатами лучше идентификаторов с экрана
                fp.waypoints = list(f.waypoints)
                fp.sources["waypoints"] = f.sources.get("waypoints", "fms")
            fp.fill_from(f)
        return fp.finalize()

    def poll_once(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        if self.rest is not None:
            if not self.connected and now >= self.next_connect:
                if not self.connect():
                    self.next_connect = now + 15.0
            if self.connected:
                try:
                    sc = self.read_cdu()
                    if sc is not None:
                        self.collector.feed(sc)
                    if now >= self.next_zibo:
                        self.read_zibo()
                        self.next_zibo = now + 5.0
                    self.fail_count = 0
                except Exception as e:
                    self.fail_count += 1
                    if self.fail_count >= 3:   # X-Plane перезапущен/самолёт перезагружен — id устарели
                        self._err(f"чтение FMC прервано ({e}) — переподключение")
                        self.connected = False
                        self.next_connect = now + 5.0
        if self.use_fms and now >= self.next_fms:
            live = self.collector.plan()
            self.read_fms(live)
            self.next_fms = now + 10.0
        self.plan = self.merge()
        key = self.plan.key()
        if key != self._last_key:
            self._last_key = key
            if self.on_change and not self.plan.is_empty():
                try:
                    self.on_change(self.plan)
                except Exception:
                    log.exception("on_change")
            return True
        return False

    # ------------------------------------------------------------ поток
    def start(self) -> None:
        if self.mode in ("config", "off", "none"):
            return
        self._thread = threading.Thread(target=self._run, name="flightplan", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("Ошибка опроса плана полёта")
            self._stop.wait(self.poll_s)

    def status_line(self) -> str:
        src = "FMC" if self.connected else ("FMS-файл" if self.fms_plan else "нет")
        return f"{self.plan.summary()} [{src}]"
