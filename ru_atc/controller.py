"""Логика диспетчера: разрешения, передачи между органами, контроль readback и процедур."""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from .airspace import Airport, Airspace, Runway, Unit, angle_diff
from .events import Hint, PilotMessage, Transmission
from .model import SimState
from .phases import Phase, PhaseTracker
from .phraseology.parser import ParsedMessage, parse
from .phraseology.render import Renderer

log = logging.getLogger(__name__)

Event = Union[Transmission, Hint, PilotMessage]

# Цепочки подмены отсутствующих органов (региональные аэродромы)
FALLBACK = {
    "delivery": ["delivery", "ground", "tower", "radar", "approach"],
    "ground": ["ground", "tower", "radar", "approach"],
    "tower": ["tower", "radar", "approach"],
    "radar": ["radar", "approach"],
    "approach": ["approach", "radar"],
}

GROUND_DEP_PHASES = {Phase.PARKED, Phase.PUSHBACK, Phase.STARTUP, Phase.TAXI_OUT, Phase.LINEUP}
GROUND_ARR_PHASES = {Phase.LANDING, Phase.TAXI_IN, Phase.ARRIVED}
AIRBORNE_PHASES = {Phase.TAKEOFF, Phase.CLIMB, Phase.CRUISE, Phase.DESCENT, Phase.APPROACH}

FT_PER_HPA = 27.3


def pressure_alt(s: SimState) -> float:
    return s.alt_ind_ft - (s.baro_set_hpa - 1013.25) * FT_PER_HPA


def qnh_alt(s: SimState) -> float:
    return pressure_alt(s) + (s.qnh_hpa - 1013.25) * FT_PER_HPA


@dataclass
class Clearance:
    kind: str            # "alt" | "fl"
    value: int

    def as_feet(self, qnh: float) -> float:
        return self.value * 100.0 if self.kind == "fl" else float(self.value)


@dataclass
class PendingReadback:
    items: Dict[str, object]
    t: float
    unit: Unit
    after: Optional[str] = None             # шаблон, добавляемый к "Правильно"
    after_unit: Optional[Unit] = None       # орган, на который после readback передаём
    attempts: int = 0
    reminded: bool = False
    seq: int = 0


class Controller:
    def __init__(self, cfg: Dict, airspace: Airspace, rng: Optional[random.Random] = None):
        self.cfg = cfg
        self.airspace = airspace
        self.rng = rng or random.Random()
        cs = cfg["callsign"]
        self.r = Renderer(cs["spoken"], str(cs["number"]), cfg["atc"].get("levels_digit_by_digit", False))
        fp = cfg["flight_plan"]
        self.dep: Airport = airspace.airports[fp["departure"]]
        self.arr: Airport = airspace.airports[fp["arrival"]]
        self.cruise_fl = int(fp.get("cruise_fl", 330))
        self.strict_freq = bool(cfg["atc"].get("strict_frequency", True))
        self.dep_rwy: Optional[Runway] = None
        self.arr_rwy: Optional[Runway] = None
        self.squawk: Optional[str] = None
        self.cleared: Optional[Clearance] = None
        self.flags: Dict[str, bool] = {k: False for k in (
            "clearance", "pushback", "startup", "taxi", "lineup", "takeoff", "dep_handoff",
            "acc_handoff", "descent", "arr_approach_init", "approach", "landing",
            "tower_handoff_arr", "ground_handoff_arr", "taxi_in", "squawk_ok")}
        self.controlling: Optional[Unit] = None      # орган, с которым пилот сейчас работает
        self.handoff_to: Optional[Unit] = None       # орган, куда передали
        self.pending: Optional[PendingReadback] = None
        self.last_tx: Optional[Transmission] = None
        self.last_proactive_t = -1e9
        self.warn_cooldown: Dict[str, float] = {}
        self.timers: Dict[str, float] = {}
        self.events_log: List[Event] = []
        self.tracker = PhaseTracker(
            dep_runway_hdg=lambda: self.dep_rwy.hdg if self.dep_rwy else None,
            dist_to_arrival_km=lambda s: self.arr.distance_km(s.lat, s.lon),
            cruise_ft=lambda: self.cruise_fl * 100.0,
            field_elev_ft=lambda: self.arr.elevation_ft,
        )
        self.tracker.listeners.append(self._on_phase)
        self._phase_events: List[Event] = []
        self.sim: SimState = SimState()

    # ------------------------------------------------------------------ helpers
    @property
    def phase(self) -> Phase:
        return self.tracker.phase

    def unit_of(self, ap: Airport, t: str, s: Optional[SimState] = None) -> Unit:
        for tt in FALLBACK.get(t, [t]):
            u = ap.unit(tt)
            if u:
                return u
        sec = self.airspace.sector_at(ap.lat, ap.lon)
        if sec:
            return sec.unit()
        raise RuntimeError(f"Нет ни одного органа ОВД для {ap.icao}")

    def sector_unit(self, s: SimState) -> Optional[Unit]:
        sec = self.airspace.sector_at(s.lat, s.lon)
        return sec.unit() if sec else None

    def dep_terminal_unit(self) -> Optional[Unit]:
        return self.dep.unit("radar") or self.dep.unit("approach")

    def arr_terminal_units(self) -> List[Unit]:
        return [u for u in (self.arr.unit("approach"), self.arr.unit("radar")) if u]

    def terminal_fl(self, ap: Airport) -> int:
        return 150 if ap.transition_altitude_ft >= 10000 else 100

    def initial_clearance(self) -> Clearance:
        ic = self.dep.initial_climb or {}
        if "fl" in ic:
            return Clearance("fl", int(ic["fl"]))
        return Clearance("alt", int(ic.get("alt_ft", 5000)))

    def wind_tag(self, s: SimState) -> str:
        ms = int(round(s.wind_kt / 1.943844))
        d = int(round(s.wind_dir / 10.0) * 10) % 360 or 360
        return f"{{wind:{d}/{ms}}}"

    def qnh(self, s: SimState) -> int:
        return int(round(s.qnh_hpa))

    def same_unit(self, a: Optional[Unit], b: Optional[Unit]) -> bool:
        return bool(a and b and a.khz == b.khz and a.callsign == b.callsign)

    def tx(self, unit: Unit, template: str, s: SimState, kind: str = "atc",
           readback: Optional[Dict[str, object]] = None, after: Optional[str] = None,
           after_unit: Optional[Unit] = None) -> Transmission:
        # Позывной борта — первым, затем позывной органа (стандартный порядок ФАП)
        disp, speech = self.r.render(template)
        t = Transmission(unit=unit, display=disp, speech=speech, t=s.t, kind=kind)
        if readback:
            self._seq = getattr(self, "_seq", 0) + 1
            self.pending = PendingReadback(items=readback, t=s.t, unit=unit, after=after,
                                           after_unit=after_unit, seq=self._seq)
        self.last_tx = t
        self.events_log.append(t)
        return t

    def hint(self, key: str, text: str, s: SimState, cooldown: float = 90.0) -> Optional[Hint]:
        last = self.warn_cooldown.get(key, -1e9)
        if s.t - last < cooldown:
            return None
        self.warn_cooldown[key] = s.t
        h = Hint(text=text, t=s.t, key=key)
        self.events_log.append(h)
        return h

    def cooldown_ok(self, key: str, s: SimState, cooldown: float) -> bool:
        last = self.warn_cooldown.get(key, -1e9)
        if s.t - last < cooldown:
            return False
        self.warn_cooldown[key] = s.t
        return True

    def handoff_template(self, unit: Unit) -> str:
        return f"работайте с {unit.callsign} {{freq:{unit.freq}}}"

    def set_cleared(self, c: Clearance) -> None:
        self.cleared = c

    def clr_tag(self, c: Clearance, verb: str = "набирайте") -> str:
        if c.kind == "fl":
            if verb == "снижайтесь":
                return f"снижайтесь до {{fla:{c.value}}}"
            return f"{verb} {{fl:{c.value}}}"
        return f"{verb} {{alt:{c.value}}}"

    def clr_items(self, c: Clearance) -> Dict[str, object]:
        return {"level": c.value} if c.kind == "fl" else {"alt_ft": c.value}

    # ------------------------------------------------------------------ фазы
    def _on_phase(self, old: Phase, new: Phase, s: SimState) -> None:
        self._phase_events.append(Hint(text=f"Фаза: {old.value} → {new.value}", t=s.t, key="phase"))
        if new == Phase.TAKEOFF and old in (Phase.TAXI_OUT, Phase.LINEUP):
            self.timers["takeoff_t"] = s.t
        if new == Phase.CLIMB and old == Phase.APPROACH:
            # уход на второй круг
            self.flags["landing"] = False
            self.flags["approach"] = False
            self.flags["tower_handoff_arr"] = False

    # ------------------------------------------------------------------ основной цикл
    def update(self, s: SimState) -> List[Event]:
        self.sim = s
        out: List[Event] = []
        self.tracker.update(s)
        out += self._phase_events
        self._phase_events = []
        if not s.connected:
            return out
        out += [e for e in self._proactive(s) if e]
        out += [e for e in self._monitor(s) if e]
        return out

    # ------------------------------------------------------------------ сообщения пилота
    def responding_unit(self, s: SimState, needed: Optional[Unit]) -> Optional[Unit]:
        if not self.strict_freq:
            return needed or self.controlling
        cands = self.airspace.units_on_freq(s.com1_khz)
        if not cands:
            return None
        # приоритет: нужный орган, текущий/передающий, аэродромы плана, сектор, ближайший
        for pref in (needed, self.handoff_to, self.controlling):
            for c in cands:
                if self.same_unit(c, pref):
                    return c
        sec = self.airspace.sector_at(s.lat, s.lon)
        relevant_ap = self.dep.icao if self.phase in GROUND_DEP_PHASES or self.phase in (Phase.TAKEOFF, Phase.CLIMB) else self.arr.icao
        for c in cands:
            if c.airport == relevant_ap:
                return c
        for c in cands:
            if c.airport in (self.dep.icao, self.arr.icao):
                return c
        for c in cands:
            if sec and c.sector_id == sec.id:
                return c

        def dist(u: Unit) -> float:
            if u.airport:
                return self.airspace.airports[u.airport].distance_km(s.lat, s.lon)
            return 0.0 if (sec and u.sector_id == sec.id) else 500.0
        return min(cands, key=dist)

    def needed_unit(self, msg: ParsedMessage, s: SimState) -> Optional[Unit]:
        it = msg.intent
        ap = self.dep if self.phase in GROUND_DEP_PHASES else self.arr
        if it == "request_clearance":
            return self.unit_of(self.dep, "delivery")
        if it == "request_taxi" and self.phase in GROUND_ARR_PHASES:
            return self.unit_of(self.arr, "ground")
        if it in ("request_pushback", "request_startup", "request_push_start", "request_taxi"):
            return self.unit_of(self.dep, "ground")
        if it in ("request_lineup", "ready_departure"):
            return self.unit_of(self.dep, "tower")
        if it in ("request_landing",):
            return self.unit_of(self.arr, "tower")
        if it in ("request_taxi_in",):
            return self.unit_of(self.arr, "ground")
        if it == "runway_vacated":
            return None
        return None

    def on_pilot(self, text: str, s: Optional[SimState] = None) -> List[Event]:
        s = s or self.sim
        msg = parse(text)
        out: List[Event] = []
        needed = self.needed_unit(msg, s)
        unit = self.responding_unit(s, needed)
        pm = PilotMessage(text=text, norm=msg.norm, intent=msg.intent, t=s.t, unit=unit)
        out.append(pm)
        self.events_log.append(pm)
        if unit is None:
            out.append(Hint(text=f"На частоте {s.com1_khz / 1000:.3f} никто не отвечает "
                                 f"(нет органа ОВД в data/airports.yaml / airspace.yaml)", t=s.t, key="nofreq"))
            return out
        # Пилот вышел на связь с органом, куда его передали
        if self.handoff_to and self.same_unit(unit, self.handoff_to):
            self.controlling = unit
            self.handoff_to = None
        elif self.controlling is None:
            self.controlling = unit

        # 1) readback
        rel_keys = {"level": ("level", "target_level"), "alt_ft": ("alt_ft", "target_alt_ft"),
                    "squawk": ("squawk",), "freq": ("freq",), "runway": ("runway",), "qnh": ("qnh",)}
        has_rel = bool(self.pending) and any(
            k in msg.slots for pk in self.pending.items for k in rel_keys.get(pk, ()))
        if self.pending and self.same_unit(self.pending.unit, unit) and (
                msg.intent in ("readback", "wilco", "unknown")
                or (has_rel and not msg.intent.startswith("request_"))):
            res = self._check_readback(msg, s)
            if res is not None:
                out.append(res)
                return out
        # 2) направить к нужному органу
        if needed and self.strict_freq and not self.same_unit(unit, needed) and unit.type != needed.type:
            out.append(self.tx(unit, f"{{cs}}, {unit.callsign}, {self.handoff_template(needed)}", s))
            self.handoff_to = needed
            return out
        handler = getattr(self, f"_h_{msg.intent}", None)
        if handler is None:
            handler = self._h_unknown
        res = handler(msg, s, unit)
        if res:
            out.append(res)
        return out

    # ------------------------------------------------------------------ readback
    def _check_readback(self, msg: ParsedMessage, s: SimState) -> Optional[Transmission]:
        p = self.pending
        sl = msg.slots
        wrong, missing = [], []
        for k, v in p.items.items():
            got = None
            if k == "level":
                got = sl.get("level") if sl.get("level") == v else sl.get("target_level", sl.get("level"))
            elif k == "alt_ft":
                got = sl.get("alt_ft") if sl.get("alt_ft") == v else sl.get("target_alt_ft", sl.get("alt_ft"))
            elif k == "squawk":
                got = sl.get("squawk")
                if got is None and str(v) in msg.norm.replace(" ", ""):
                    got = v
            elif k == "freq":
                got = sl.get("freq")
                if got is None:
                    a, b = f"{float(v):.3f}".rstrip("0").split(".")
                    if f"{a} {b}" in msg.norm or f"{a}.{b}" in msg.norm:
                        got = v
                if got is not None and abs(float(got) - float(v)) < 0.006:
                    got = v
            elif k == "runway":
                got = sl.get("runway")
                if got and len(got) == 2 and str(v)[:2] == got:
                    got = v      # сторону (левая/правая) не назвали — не придираемся
            elif k == "qnh":
                got = sl.get("qnh")
                if got is not None and abs(int(got) - int(v)) <= 1:
                    got = v
            if got is None:
                missing.append(k)
            elif str(got) != str(v):
                wrong.append(k)
        unit = p.unit
        if not wrong and not missing:
            after, after_unit = p.after, p.after_unit
            self.pending = None
            parts = []
            only_freq = set(p.items) == {"freq"}
            if self.cfg["atc"].get("confirm_correct_readback", True) and not only_freq:
                parts.append("правильно")
            if after:
                parts.append(after)
            if after_unit:
                self.handoff_to = after_unit
            if not parts:
                return None
            return self.tx(unit, "{cs}, " + ", ".join(parts), s)
        p.attempts += 1
        if p.attempts > 2:
            self.pending = None
        bad = wrong + missing
        word = "неправильно" if wrong else "подтвердите"
        items = ", ".join(self._item_tag(k, p.items[k]) for k in bad)
        tx = self.tx(unit, f"{{cs}}, {word}, {items}", s)
        return tx

    def _item_tag(self, k: str, v) -> str:
        return {"level": f"{{fl:{v}}}", "alt_ft": f"{{alt:{v}}}", "squawk": f"ответчик {{sq:{v}}}",
                "freq": f"частота {{freq:{v}}}", "runway": f"ВПП {{rwy:{v}}}",
                "qnh": f"{{qnh:{v}}}"}.get(k, str(v))

    # ------------------------------------------------------------------ обработчики намерений
    def _h_unknown(self, msg, s, unit):
        return self.tx(unit, "{cs}, повторите", s)

    def _h_say_again(self, msg, s, unit):
        if self.last_tx:
            t = Transmission(self.last_tx.unit, self.last_tx.display, self.last_tx.speech, s.t)
            return t
        return None

    def _h_radio_check(self, msg, s, unit):
        return self.tx(unit, f"{{cs}}, {unit.callsign}, слышу вас отлично", s)

    def _h_wilco(self, msg, s, unit):
        return None

    def _h_readback(self, msg, s, unit):
        # повторение без ожидающего readback — например, доклад частоты при переходе
        if any(k in msg.slots for k in ("level", "alt_ft")) and unit.type in ("control", "radar", "approach"):
            return self._h_check_in(msg, s, unit)
        return None

    def _clearance_text(self, s: SimState) -> Tuple[str, Dict]:
        if not self.dep_rwy:
            self.dep_rwy = self.dep.select_runway(s.wind_dir, s.wind_kt, False,
                                                  self.cfg["flight_plan"].get("departure_runway", ""))
        if not self.squawk:
            self.squawk = self.dep.assign_squawk(self.rng)
        ic = self.initial_clearance()
        self.set_cleared(ic)
        sid = self.cfg["flight_plan"].get("sid") or ""
        route = self.cfg["flight_plan"].get("route") or ""
        sid_txt = f"выход по схеме {sid}" if sid else "выход по схеме согласно плану"
        route_txt = f" по маршруту {route}" if route and route != "по плану" else " по плану"
        clr = "набор " + ("{fl:%d}" % ic.value if ic.kind == "fl" else "{alt:%d}" % ic.value)
        tpl = (f"{{cs}}, {self.unit_of(self.dep, 'delivery').callsign}, разрешено до {self.arr.name_gen}{route_txt}, "
               f"взлёт ВПП {{rwy:{self.dep_rwy.id}}}, {sid_txt}, {clr}, ответчик {{sq:{self.squawk}}}")
        items = {"squawk": self.squawk}
        items.update(self.clr_items(ic))
        return tpl, items

    def _h_request_clearance(self, msg, s, unit):
        tpl, items = self._clearance_text(s)
        self.flags["clearance"] = True
        ground = self.unit_of(self.dep, "ground")
        after, after_unit = None, None
        if not self.same_unit(ground, unit):
            after = f"по готовности к буксировке и запуску {self.handoff_template(ground)}"
            after_unit = ground
        return self.tx(unit, tpl, s, readback=items, after=after, after_unit=after_unit)

    def _need_clearance(self, s, unit):
        if self.flags["clearance"]:
            return None
        d = self.unit_of(self.dep, "delivery")
        if self.same_unit(d, unit):
            return None
        return self.tx(unit, f"{{cs}}, разрешение на вылет не получено, {self.handoff_template(d)}", s)

    def _h_request_push_start(self, msg, s, unit):
        r = self._need_clearance(s, unit)
        if r:
            return r
        self.flags["pushback"] = self.flags["startup"] = True
        self.tracker.pushback_cleared = True
        return self.tx(unit, f"{{cs}}, {unit.callsign}, буксировку и запуск разрешаю, {{qnh:{self.qnh(s)}}}", s)

    def _h_request_pushback(self, msg, s, unit):
        r = self._need_clearance(s, unit)
        if r:
            return r
        self.flags["pushback"] = True
        self.tracker.pushback_cleared = True
        return self.tx(unit, f"{{cs}}, {unit.callsign}, буксировку разрешаю", s)

    def _h_request_startup(self, msg, s, unit):
        r = self._need_clearance(s, unit)
        if r:
            return r
        self.flags["startup"] = True
        return self.tx(unit, f"{{cs}}, запуск разрешаю, {{qnh:{self.qnh(s)}}}", s)

    def _h_request_taxi(self, msg, s, unit):
        if self.phase in GROUND_ARR_PHASES:
            return self._h_request_taxi_in(msg, s, unit)
        r = self._need_clearance(s, unit)
        if r:
            return r
        if not self.dep_rwy:
            self.dep_rwy = self.dep.select_runway(s.wind_dir, s.wind_kt)
        self.flags["taxi"] = True
        tower = self.unit_of(self.dep, "tower")
        tpl = (f"{{cs}}, рулите к предварительному старту ВПП {{rwy:{self.dep_rwy.id}}}, "
               f"{{qnh:{self.qnh(s)}}}")
        if not self.same_unit(tower, unit):
            tpl += f", на предварительном {self.handoff_template(tower)}"
            self.handoff_to = tower
        return self.tx(unit, tpl, s, readback={"runway": self.dep_rwy.id, "qnh": self.qnh(s)})

    def _h_request_lineup(self, msg, s, unit):
        if not self.dep_rwy:
            self.dep_rwy = self.dep.select_runway(s.wind_dir, s.wind_kt)
        self.flags["lineup"] = True
        self.tracker.lineup_cleared = True
        return self.tx(unit, f"{{cs}}, {unit.callsign}, занимайте исполнительный старт ВПП {{rwy:{self.dep_rwy.id}}}", s,
                       readback={"runway": self.dep_rwy.id})

    def _h_ready_departure(self, msg, s, unit):
        if not self.dep_rwy:
            self.dep_rwy = self.dep.select_runway(s.wind_dir, s.wind_kt)
        if not self.flags["clearance"]:
            tpl, _ = self._clearance_text(s)
            self.flags["clearance"] = True
        self.flags["lineup"] = self.flags["takeoff"] = True
        self.tracker.lineup_cleared = True
        return self.tx(unit, f"{{cs}}, {unit.callsign}, ВПП {{rwy:{self.dep_rwy.id}}}, {self.wind_tag(s)}, взлёт разрешаю", s,
                       readback={"runway": self.dep_rwy.id})

    def _h_report_airborne(self, msg, s, unit):
        return self._h_check_in(msg, s, unit)

    def _h_check_in(self, msg, s, unit):
        ph = self.phase
        self.controlling = unit
        if unit.type in ("delivery",) and not self.flags["clearance"]:
            return self._h_request_clearance(msg, s, unit)
        if unit.type == "ground" and ph in GROUND_ARR_PHASES:
            return self._h_request_taxi_in(msg, s, unit)
        if unit.type == "ground" and ph in GROUND_DEP_PHASES:
            if not self.flags["clearance"]:
                return self._need_clearance(s, unit) or self.tx(unit, f"{{cs}}, {unit.callsign}, ожидайте", s)
            return self.tx(unit, f"{{cs}}, {unit.callsign}, доложите готовность к буксировке и запуску", s)
        if unit.type == "tower" and ph in (Phase.DESCENT, Phase.APPROACH):
            return self._h_request_landing(msg, s, unit)
        if unit.type == "tower" and ph in GROUND_DEP_PHASES:
            return self.tx(unit, f"{{cs}}, {unit.callsign}, доложите готовность к взлёту", s)
        if s.on_ground:
            return self.tx(unit, f"{{cs}}, {unit.callsign}, понял", s)
        # --- в воздухе: радар/подход/РЦ ---
        if unit.type == "control":
            if self.phase in (Phase.DESCENT, Phase.APPROACH) or self.flags["descent"]:
                c = self.cleared or Clearance("fl", self.terminal_fl(self.arr))
                return self.tx(unit, f"{{cs}}, {unit.callsign}, наблюдаю, {self.clr_tag(c, 'продолжайте снижение до' if c.kind=='alt' else 'снижайтесь')}", s,
                               readback=self.clr_items(c))
            if self.cleared and self.cleared.kind == "fl" and self.cleared.value >= self.cruise_fl:
                return self.tx(unit, f"{{cs}}, {unit.callsign}, наблюдаю, сохраняйте {{fl:{self.cleared.value}}}", s)
            c = Clearance("fl", self.cruise_fl)
            self.set_cleared(c)
            return self.tx(unit, f"{{cs}}, {unit.callsign}, наблюдаю, набирайте {{fl:{c.value}}}", s,
                           readback={"level": c.value})
        # radar/approach
        if ph in (Phase.TAKEOFF, Phase.CLIMB) and not self.flags["descent"]:
            c = Clearance("fl", self.terminal_fl(self.dep))
            self.set_cleared(c)
            return self.tx(unit, f"{{cs}}, {unit.callsign}, наблюдаю, набирайте {{fl:{c.value}}}", s,
                           readback={"level": c.value})
        # прибытие
        return self._arrival_terminal_checkin(s, unit)

    def _arrival_terminal_checkin(self, s, unit):
        if not self.arr_rwy:
            self.arr_rwy = self.arr.select_runway(s.wind_dir, s.wind_kt, True,
                                                  self.cfg["flight_plan"].get("arrival_runway", ""))
        units = self.arr_terminal_units()
        last_terminal = (not units) or self.same_unit(unit, units[-1])
        d = self.arr.distance_km(s.lat, s.lon)
        if last_terminal and d < self.arr.radar_radius_km + 10:
            return self._approach_clearance(s, unit, greet=True)
        alt = min(self.arr.transition_altitude_ft,
                  int(math.ceil((self.arr.elevation_ft + 4000) / 500.0) * 500))
        c = Clearance("alt", alt)
        self.set_cleared(c)
        self.flags["arr_approach_init"] = True
        return self.tx(unit, f"{{cs}}, {unit.callsign}, наблюдаю, снижайтесь до высоты {{alt:{alt}}}, "
                             f"{{qnh:{self.qnh(s)}}}, ожидайте заход ILS ВПП {{rwy:{self.arr_rwy.id}}}", s,
                       readback={"alt_ft": alt, "qnh": self.qnh(s)})

    def _approach_clearance(self, s, unit, greet=False):
        if not self.arr_rwy:
            self.arr_rwy = self.arr.select_runway(s.wind_dir, s.wind_kt, True,
                                                  self.cfg["flight_plan"].get("arrival_runway", ""))
        alt = int(math.ceil((self.arr.elevation_ft + 2000) / 100.0) * 100)
        c = Clearance("alt", alt)
        self.set_cleared(c)
        self.flags["approach"] = True
        self.flags["arr_approach_init"] = True
        g = f"{unit.callsign}, наблюдаю, " if greet else ""
        appr = "ILS" if self.arr_rwy.ils else "по RNAV"
        return self.tx(unit, f"{{cs}}, {g}снижайтесь до высоты {{alt:{alt}}}, {{qnh:{self.qnh(s)}}}, "
                             f"заход {appr} ВПП {{rwy:{self.arr_rwy.id}}} разрешаю, доложите на посадочном", s,
                       readback={"alt_ft": alt, "qnh": self.qnh(s), "runway": self.arr_rwy.id})

    def _h_report_level(self, msg, s, unit):
        lvl = msg.slots.get("level")
        alt = msg.slots.get("alt_ft")
        if unit.type == "control" and not self.same_unit(unit, self.controlling):
            return self._h_check_in(msg, s, unit)
        if self.cleared and ((lvl and self.cleared.kind == "fl" and lvl != self.cleared.value) or
                             (alt and self.cleared.kind == "alt" and alt != self.cleared.value)):
            return self.tx(unit, f"{{cs}}, проверьте, вам разрешено {self._item_tag(self.clr_items(self.cleared).popitem()[0], self.cleared.value)}", s)
        return self.tx(unit, "{cs}, понял", s)

    def _h_request_climb(self, msg, s, unit):
        lvl = msg.slots.get("level") or msg.slots.get("target_level") or self.cruise_fl
        c = Clearance("fl", int(lvl))
        self.set_cleared(c)
        return self.tx(unit, f"{{cs}}, набирайте {{fl:{c.value}}}", s, readback={"level": c.value})

    def tod_km(self, s: SimState) -> float:
        above = max(0.0, s.alt_ind_ft - self.arr.elevation_ft)
        return above / 1000.0 * 3.0 * 1.852 + 20.0

    def _h_request_descent(self, msg, s, unit):
        d = self.arr.distance_km(s.lat, s.lon)
        if unit.type == "control":
            if d > self.tod_km(s) + 60:
                return self.tx(unit, f"{{cs}}, ожидайте снижение через {{km:{int((d - self.tod_km(s)) // 10 * 10)}}}", s)
            return self._issue_descent(s, unit)
        return self._arrival_terminal_checkin(s, unit)

    def _issue_descent(self, s, unit):
        c = Clearance("fl", self.terminal_fl(self.arr))
        self.set_cleared(c)
        self.flags["descent"] = True
        return self.tx(unit, f"{{cs}}, снижайтесь до {{fla:{c.value}}}", s, readback={"level": c.value})

    def _h_request_approach(self, msg, s, unit):
        if unit.type == "control":
            return self._h_request_descent(msg, s, unit)
        return self._approach_clearance(s, unit)

    def _h_report_established(self, msg, s, unit):
        tower = self.unit_of(self.arr, "tower")
        if not self.same_unit(tower, unit):
            self.flags["tower_handoff_arr"] = True
            self.handoff_to = tower
            return self.tx(unit, f"{{cs}}, {self.handoff_template(tower)}", s, readback={"freq": tower.freq})
        return self._h_request_landing(msg, s, unit)

    def _h_request_landing(self, msg, s, unit):
        if not self.arr_rwy:
            self.arr_rwy = self.arr.select_runway(s.wind_dir, s.wind_kt, True)
        self.flags["landing"] = True
        self.controlling = unit
        return self.tx(unit, f"{{cs}}, {unit.callsign}, {self.wind_tag(s)}, ВПП {{rwy:{self.arr_rwy.id}}}, посадку разрешаю", s,
                       readback={"runway": self.arr_rwy.id})

    def _h_going_around(self, msg, s, unit):
        self.flags["landing"] = self.flags["approach"] = self.flags["tower_handoff_arr"] = False
        alt = int(math.ceil((self.arr.elevation_ft + 3000) / 500.0) * 500)
        alt = min(alt, self.arr.transition_altitude_ft)
        self.set_cleared(Clearance("alt", alt))
        nxt = (self.arr_terminal_units() or [self.sector_unit(s) or unit])[-1]
        tpl = f"{{cs}}, понял, по схеме ухода набирайте {{alt:{alt}}}"
        if not self.same_unit(nxt, unit):
            tpl += f", {self.handoff_template(nxt)}"
            self.handoff_to = nxt
        return self.tx(unit, tpl, s, readback={"alt_ft": alt})

    def _h_runway_vacated(self, msg, s, unit):
        ground = self.unit_of(self.arr, "ground")
        if self.same_unit(ground, unit):
            return self._h_request_taxi_in(msg, s, unit)
        self.flags["ground_handoff_arr"] = True
        self.handoff_to = ground
        return self.tx(unit, f"{{cs}}, {self.handoff_template(ground)}", s, readback={"freq": ground.freq})

    def _h_request_taxi_in(self, msg, s, unit):
        stand = self.cfg["flight_plan"].get("arrival_stand") or msg.slots.get("stand") or ""
        self.flags["taxi_in"] = True
        where = f"на стоянку {stand}" if stand else "на стоянку по указанию сигнальщика"
        return self.tx(unit, f"{{cs}}, {unit.callsign}, рулите {where}", s)

    # ------------------------------------------------------------------ проактивные передачи
    def _can_speak(self, s: SimState, gap: float = 8.0) -> bool:
        if self.pending and s.t - self.pending.t < 10:
            return False
        return s.t - self.last_proactive_t >= gap

    def _pro(self, unit: Unit, tpl: str, s: SimState, **kw) -> Transmission:
        self.last_proactive_t = s.t
        return self.tx(unit, tpl, s, **kw)

    def _on_freq(self, s: SimState, unit: Optional[Unit]) -> bool:
        if unit is None:
            return False
        return (not self.strict_freq) or abs(s.com1_khz - unit.khz) <= 3

    def _proactive(self, s: SimState) -> List[Optional[Event]]:
        out: List[Optional[Event]] = []
        ph = self.phase
        ctrl = self.controlling
        # напоминание о readback
        if self.pending and not self.pending.reminded and \
                s.t - self.pending.t > float(self.cfg["atc"].get("readback_timeout_s", 20)):
            self.pending.reminded = True
            if self._on_freq(s, self.pending.unit):
                out.append(self.tx(self.pending.unit, "{cs}, подтвердите приём", s))
            else:
                self.pending = None
        if not self._can_speak(s) or ctrl is None:
            return out
        if not self._on_freq(s, ctrl):
            return out    # пилот не на частоте текущего органа — говорить бесполезно

        # Вышка -> радар/подход/РЦ после взлёта
        if ph == Phase.CLIMB and ctrl.type == "tower" and not self.flags["dep_handoff"] and s.agl_ft > 1000:
            nxt = self.dep_terminal_unit() or self.sector_unit(s)
            if nxt and not self.same_unit(nxt, ctrl):
                self.flags["dep_handoff"] = True
                self.handoff_to = nxt
                out.append(self._pro(ctrl, f"{{cs}}, {self.handoff_template(nxt)}", s, readback={"freq": nxt.freq}))
                return out
        # Радар/подход вылета -> РЦ
        if ctrl.type in ("radar", "approach") and ctrl.airport == self.dep.icao and ph in (Phase.CLIMB, Phase.CRUISE) \
                and not self.flags["acc_handoff"]:
            if s.alt_ind_ft > self.terminal_fl(self.dep) * 100 - 2500 or \
                    self.dep.distance_km(s.lat, s.lon) > self.dep.approach_radius_km:
                nxt = self.sector_unit(s)
                if nxt:
                    self.flags["acc_handoff"] = True
                    self.handoff_to = nxt
                    out.append(self._pro(ctrl, f"{{cs}}, {self.handoff_template(nxt)}", s, readback={"freq": nxt.freq}))
                    return out
        if ctrl.type == "control" and not s.on_ground:
            d_arr = self.arr.distance_km(s.lat, s.lon)
            # смена сектора РЦ (Москва -> Санкт-Петербург и т.п.)
            sec = self.airspace.sector_at(s.lat, s.lon)
            if sec and sec.id != ctrl.sector_id and abs(sec.unit().khz - ctrl.khz) > 3:
                nxt = sec.unit()
                if not self.same_unit(self.handoff_to, nxt):
                    self.handoff_to = nxt
                    out.append(self._pro(ctrl, f"{{cs}}, {self.handoff_template(nxt)}", s, readback={"freq": nxt.freq}))
                    return out
            # снижение
            if self.cfg["atc"].get("auto_descent", True) and not self.flags["descent"] and \
                    ph in (Phase.CRUISE, Phase.CLIMB, Phase.DESCENT) and d_arr <= self.tod_km(s):
                out.append(self._issue_descent(s, ctrl))
                self.last_proactive_t = s.t
                return out
            # передача на подход прибытия
            terms = self.arr_terminal_units()
            if self.flags["descent"] and d_arr < self.arr.approach_radius_km:
                nxt = terms[0] if terms else self.arr.unit("tower")
                if nxt and not self.same_unit(self.handoff_to, nxt):
                    self.handoff_to = nxt
                    out.append(self._pro(ctrl, f"{{cs}}, {self.handoff_template(nxt)}", s, readback={"freq": nxt.freq}))
                    return out
                if nxt is None and not self.flags["approach"] and d_arr < 40:
                    out.append(self._approach_clearance(s, ctrl))
                    self.last_proactive_t = s.t
                    return out
        # Подход -> Круг (если на аэродроме оба)
        terms = self.arr_terminal_units()
        if ctrl.airport == self.arr.icao and ctrl.type in ("approach", "radar") and not s.on_ground:
            d_arr = self.arr.distance_km(s.lat, s.lon)
            if len(terms) == 2 and self.same_unit(ctrl, terms[0]) and d_arr < self.arr.radar_radius_km:
                nxt = terms[1]
                if not self.same_unit(self.handoff_to, nxt):
                    self.handoff_to = nxt
                    out.append(self._pro(ctrl, f"{{cs}}, {self.handoff_template(nxt)}", s, readback={"freq": nxt.freq}))
                    return out
            last = self.same_unit(ctrl, terms[-1]) if terms else False
            if last and not self.flags["approach"] and d_arr < self.arr.radar_radius_km:
                out.append(self._approach_clearance(s, ctrl))
                self.last_proactive_t = s.t
                return out
            # автоматическое обнаружение выхода на посадочный курс
            if self.flags["approach"] and self.arr_rwy and not self.flags["tower_handoff_arr"]:
                aligned = angle_diff(s.hdg_mag, self.arr_rwy.hdg) < 15
                if aligned and d_arr < 22 and (s.alt_ind_ft - self.arr.elevation_ft) < 4000:
                    if self._held("estab", True, s.t, 20):
                        tower = self.arr.unit("tower")
                        if tower:
                            self.flags["tower_handoff_arr"] = True
                            self.handoff_to = tower
                            out.append(self._pro(ctrl, f"{{cs}}, {self.handoff_template(tower)}", s,
                                                 readback={"freq": tower.freq}))
                            return out
                else:
                    self._held("estab", False, s.t, 0)
        # Вышка -> Руление после посадки
        if ph in (Phase.TAXI_IN,) and ctrl.type == "tower" and not self.flags["ground_handoff_arr"]:
            if s.t - self.tracker.since > 5:
                ground = self.arr.unit("ground")
                if ground:
                    self.flags["ground_handoff_arr"] = True
                    self.handoff_to = ground
                    out.append(self._pro(ctrl, f"{{cs}}, после освобождения ВПП {self.handoff_template(ground)}", s,
                                         readback={"freq": ground.freq}))
                    return out
        return out

    def _held(self, name: str, cond: bool, t: float, dur: float) -> bool:
        if not cond:
            self.timers.pop(name, None)
            return False
        st = self.timers.setdefault(name, t)
        return t - st >= dur

    # ------------------------------------------------------------------ мониторинг процедур
    def _monitor(self, s: SimState) -> List[Optional[Event]]:
        out: List[Optional[Event]] = []
        ph = self.phase
        voice = self.cfg["atc"].get("voice_warnings", True)
        ctrl = self.controlling
        speak_ok = voice and ctrl is not None and self._on_freq(s, ctrl)

        # --- огни ---
        if (s.engines_running or ph == Phase.PUSHBACK) and not s.beacon:
            out.append(self.hint("beacon", "Проблесковый маяк (BEACON / ANTI-COLLISION) выключен при запуске/буксировке", s))
        if ph == Phase.TAKEOFF and not s.landing_lights:
            out.append(self.hint("ldg_to", "Посадочные фары выключены на взлёте", s))
        if ph in (Phase.TAKEOFF, Phase.LINEUP) and not s.strobe:
            out.append(self.hint("strobe", "Стробы (STROBE) выключены на ВПП", s))
        if ph == Phase.APPROACH and not s.landing_lights and s.agl_ft < 5000:
            out.append(self.hint("ldg_app", "Посадочные фары выключены на заходе", s))
        if ph == Phase.APPROACH and not s.gear_down and 0 < s.agl_ft < 1500:
            out.append(self.hint("gear", "ШАССИ НЕ ВЫПУЩЕНО ниже 1500 ft AGL!", s, cooldown=30))

        # --- ответчик ---
        airborne = not s.on_ground and ph in AIRBORNE_PHASES
        alt_rep = s.xpdr_alt_reporting
        if self._held("xpdr_mode", airborne and not alt_rep, s.t, 30):
            if speak_ok and self.cooldown_ok("xpdr_mode_v", s, 120):
                out.append(self.tx(ctrl, "{cs}, ответчик не наблюдаю, проверьте режим ответчика", s, kind="warning"))
            else:
                out.append(self.hint("xpdr_mode", "Ответчик не в режиме ALT/TA/RA", s))
        if self.squawk and self.pending is None and (airborne or ph in (Phase.TAXI_OUT, Phase.LINEUP)):
            if self._held("xpdr_code", f"{s.xpdr_code:04d}" != self.squawk, s.t, 25):
                if speak_ok and airborne and self.cooldown_ok("xpdr_code_v", s, 120):
                    out.append(self.tx(ctrl, f"{{cs}}, проверьте код ответчика, установите {{sq:{self.squawk}}}", s, kind="warning"))
                else:
                    out.append(self.hint("xpdr_code", f"Код ответчика {s.xpdr_code:04d}, назначен {self.squawk}", s))

        # --- движение без разрешений ---
        if ph == Phase.PUSHBACK and not self.flags["pushback"]:
            out.append(self.hint("push_noclr", "Буксировка без разрешения диспетчера", s))
        if ph == Phase.TAXI_OUT and not self.flags["taxi"] and self._held("taxi_noclr", s.gs_kt > 5, s.t, 5):
            if speak_ok and self.cooldown_ok("taxi_noclr_v", s, 120):
                out.append(self.tx(ctrl, "{cs}, остановитесь, руление не разрешено", s, kind="warning"))
            else:
                out.append(self.hint("taxi_noclr", "Руление без разрешения", s))
        if ph == Phase.TAKEOFF and not self.flags["takeoff"] and s.on_ground:
            tower = self.unit_of(self.dep, "tower")
            if s.gs_kt < 90 and voice and self._on_freq(s, tower) and self.cooldown_ok("to_noclr_v", s, 60):
                out.append(self.tx(tower, "{cs}, взлёт не разрешён, прекратите взлёт", s, kind="warning"))
            else:
                out.append(self.hint("to_noclr", "Взлёт без разрешения!", s))
        if ph == Phase.APPROACH and not self.flags["landing"] and 0 < s.agl_ft < 300 and not s.on_ground:
            if speak_ok and self.cooldown_ok("ldg_noclr_v", s, 60):
                out.append(self.tx(ctrl, "{cs}, посадка не разрешена, уходите на второй круг", s, kind="warning"))
            else:
                out.append(self.hint("ldg_noclr", "Нет разрешения на посадку!", s, cooldown=30))

        # --- высота ---
        if airborne and self.cleared and ph not in (Phase.TAKEOFF,) and not self.flags["approach"]:
            cur = pressure_alt(s) if self.cleared.kind == "fl" else qnh_alt(s)
            tgt = self.cleared.as_feet(s.qnh_hpa)
            dev = cur - tgt
            climbing_to = s.vs_fpm > 300 and dev > 300   # проскочили вверх
            descending_to = s.vs_fpm < -300 and dev < -300   # проскочили вниз
            level_off = abs(s.vs_fpm) < 300 and abs(dev) > 300
            started_above = getattr(self, "_clr_dir", None)
            if (climbing_to or descending_to) and self._held("alt_bust", True, s.t, 4):
                if speak_ok and self.cooldown_ok("alt_bust_v", s, 60):
                    tag = self._item_tag("level" if self.cleared.kind == "fl" else "alt_ft", self.cleared.value)
                    out.append(self.tx(ctrl, f"{{cs}}, проверьте высоту, вам разрешено {tag}", s, kind="warning"))
                else:
                    out.append(self.hint("alt_bust", f"Отклонение от разрешённой высоты: {dev:+.0f} ft", s, cooldown=45))
            elif not (climbing_to or descending_to):
                self._held("alt_bust", False, s.t, 0)
            if self._held("alt_lvl", level_off, s.t, 90):
                out.append(self.hint("alt_lvl", f"Горизонтальный полёт не на разрешённой высоте ({dev:+.0f} ft)", s))

        # --- давление: стандарт выше ЭП / QNH ниже ВП ---
        if airborne:
            ap = self.dep if ph in (Phase.CLIMB, Phase.TAKEOFF) else self.arr
            tl_ft = ap.transition_level(s.qnh_hpa) * 100
            ta_ft = ap.transition_altitude_ft
            std = abs(s.baro_set_hpa - 1013.25) < 0.7
            pa = pressure_alt(s)
            if self._held("baro_std", pa > tl_ft + 1000 and not std, s.t, 30):
                out.append(self.hint("baro_std", f"Выше эшелона перехода (FL{tl_ft // 100:03.0f}) — установите стандартное давление 1013", s))
            if self._held("baro_qnh", qnh_alt(s) < ta_ft - 1000 and std and abs(s.qnh_hpa - 1013.25) > 1.5 and s.vs_fpm < 0,
                          s.t, 30):
                out.append(self.hint("baro_qnh", f"Ниже высоты перехода ({ta_ft} ft) — установите QNH {self.qnh(s)}", s))

        # --- скорость ---
        lim = float(self.cfg["atc"].get("speed_limit_kt", 250) or 0)
        if lim and airborne and self._held("spd", qnh_alt(s) < 10000 and s.ias_kt > lim + 10, s.t, 15):
            out.append(self.hint("spd", f"Скорость {s.ias_kt:.0f} kt ниже 10000 ft (учебное ограничение {lim:.0f} kt)", s))
        return out

    # ------------------------------------------------------------------ сводка для UI
    def status(self) -> Dict[str, str]:
        c = self.cleared
        clr = "-" if not c else (f"FL{c.value:03d}" if c.kind == "fl" else f"{c.value} ft QNH")
        return {
            "phase": self.phase.value,
            "controlling": f"{self.controlling.callsign} {self.controlling.freq:.3f}" if self.controlling else "-",
            "handoff": f"{self.handoff_to.callsign} {self.handoff_to.freq:.3f}" if self.handoff_to else "-",
            "cleared": clr,
            "squawk": self.squawk or "-",
            "dep_rwy": self.dep_rwy.id if self.dep_rwy else "-",
            "arr_rwy": self.arr_rwy.id if self.arr_rwy else "-",
            "pending": ", ".join(f"{k}={v}" for k, v in self.pending.items.items()) if self.pending else "-",
        }
