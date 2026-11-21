"""Режим без X-Plane: кинематическая модель полёта + (по желанию) автоматический «пилот».

MockFlight подчиняется разрешениям контроллера (набор/снижение до разрешённой высоты,
руление после разрешения и т.д.) и сам перестраивает COM1 при передаче на другой орган.
ScriptedPilot ведёт радиообмен текстом — для демонстрации и сквозных тестов.
"""
from __future__ import annotations

import math
import threading
import time
from typing import List, Optional

from ..airspace import Airport, angle_diff, bearing_deg, destination
from ..model import SimState, M_TO_FT
from ..phases import Phase
from .base import DataSource

RWY_SIDE = {"L": "левая", "R": "правая", "C": "центральная"}


class MockFlight:
    def __init__(self, dep: Airport, arr: Airport, controller=None, faults: Optional[set] = None):
        self.dep, self.arr = dep, arr
        self.ctl = controller
        self.faults = faults or set()
        s = SimState()
        s.connected = True
        # стоянка в 600 м от КТА
        s.lat, s.lon = destination(dep.lat, dep.lon, 200, 0.6)
        s.alt_msl_ft = dep.elevation_ft + 10
        s.alt_ind_ft = s.alt_msl_ft
        s.qnh_hpa = 1003.0
        s.baro_set_hpa = 1003.0
        s.wind_dir, s.wind_kt = 250.0, 9.7     # ~5 м/с
        s.hdg_mag = 20.0
        s.xpdr_code, s.xpdr_mode = 2000, 1
        s.parking_brake = 1.0
        s.nav_lights = True
        u = dep.unit("delivery") or dep.unit("ground") or dep.unit("tower")
        s.com1_khz = u.khz if u else 122800
        self.s = s
        self.mode = "parked"
        self.t_mode = 0.0
        self.t = 0.0
        self.tuned_handoff_at: Optional[float] = None
        self.done = False

    # ---------- helpers ----------
    def _set_mode(self, m: str) -> None:
        self.mode = m
        self.t_mode = self.t

    def _flag(self, k: str) -> bool:
        return bool(self.ctl and self.ctl.flags.get(k))

    def _move(self, dt: float) -> None:
        s = self.s
        dist_km = s.gs_kt * 1.852 / 3600.0 * dt
        if dist_km > 0:
            brg = s.hdg_mag if self.mode != "push" else (s.hdg_mag + 180) % 360
            s.lat, s.lon = destination(s.lat, s.lon, brg, dist_km)

    def _target_alt(self) -> float:
        c = self.ctl.cleared if self.ctl else None
        if not c:
            return self.dep.elevation_ft + 3000
        if c.kind == "fl":   # эшелон — по стандартному давлению; переводим в MSL
            return c.value * 100.0 + (self.s.qnh_hpa - 1013.25) * 27.3
        return float(c.value)

    def _update_baro(self) -> None:
        s = self.s
        ap = self.dep if self.mode in ("climb",) else self.arr
        tl = ap.transition_level(s.qnh_hpa) * 100
        if "no_std" in self.faults:
            return
        if self.mode == "climb" and s.alt_msl_ft > ap.transition_altitude_ft:
            s.baro_set_hpa = 1013.25
        elif self.mode in ("cruise", "descent", "approach") and s.alt_msl_ft < tl - 300 and s.vs_fpm < 0:
            s.baro_set_hpa = s.qnh_hpa
        elif self.mode == "cruise":
            s.baro_set_hpa = 1013.25

    def _indicated(self) -> None:
        s = self.s
        s.alt_ind_ft = s.alt_msl_ft + (s.baro_set_hpa - s.qnh_hpa) * 27.3

    # ---------- шаг модели ----------
    def step(self, dt: float = 1.0) -> SimState:
        self.t += dt
        s = self.s
        s.t = self.t
        ctl = self.ctl
        # Пилот переключает COM1 на орган, куда передали (через 3 с)
        conditional_wait = bool(ctl and ctl.handoff_to and ctl.handoff_to.type == "tower" and s.on_ground
                                and self.mode not in ("holding", "lineup", "roll"))   # "на предварительном работайте с..."
        if ctl and ctl.handoff_to and abs(s.com1_khz - ctl.handoff_to.khz) > 3 and "no_tune" not in self.faults \
                and not ("no_tune_air" in self.faults and not s.on_ground) and not conditional_wait \
                and not (ctl.pending and ctl.pending.seq and s.t - ctl.pending.t < 6):
            if self.tuned_handoff_at is None:
                self.tuned_handoff_at = self.t
            elif self.t - self.tuned_handoff_at >= 3:
                s.com1_stby_khz = s.com1_khz
                s.com1_khz = ctl.handoff_to.khz
                self.tuned_handoff_at = None
        if ctl and ctl.squawk and "no_squawk" not in self.faults and self.mode != "parked":
            s.xpdr_code = int(ctl.squawk)
        m = self.mode
        el = self.t - self.t_mode
        if m == "parked":
            if self._flag("pushback") or (self._flag("startup") and el > 5):
                s.beacon = True
                s.parking_brake = 0.0
                self._set_mode("push" if self._flag("pushback") else "start")
        elif m == "push":
            s.gs_kt = 2.0 if el < 40 else 0.0
            if el > 48:
                self._set_mode("start")
        elif m == "start":
            k = min(1.0, el / 30.0)
            s.n2 = [60.0 * k, 60.0 * k]
            s.n1 = [21.0 * k, 21.0 * k]
            if el > 35:
                self._set_mode("ready_taxi")
        elif m == "ready_taxi":
            if self._flag("taxi") or ("taxi_noclr" in self.faults and el > 5):
                s.taxi_light = True
                self._set_mode("taxi")
        elif m == "taxi":
            s.n1 = [28.0, 28.0]
            s.gs_kt = 15.0
            if el > 90:
                s.hdg_mag = ctl.dep_rwy.hdg - 90 if ctl and ctl.dep_rwy else s.hdg_mag
                s.gs_kt = 0.0
                self._set_mode("holding")
        elif m == "holding":
            s.gs_kt = 0.0
            if self._flag("takeoff") or self._flag("lineup"):
                s.hdg_mag = (ctl.dep_rwy.hdg if ctl and ctl.dep_rwy else s.hdg_mag) % 360
                if "no_xpdr" not in self.faults:
                    s.xpdr_mode = 3
                s.strobe = s.landing_lights = True
                self._set_mode("lineup")
        elif m == "lineup":
            s.gs_kt = 5.0 if el < 8 else 0.0
            if self._flag("takeoff") and el > 10:
                self._set_mode("roll")
        elif m == "roll":
            s.n1 = [92.0, 92.0]
            s.gs_kt = min(160.0, s.gs_kt + 4.0 * dt)
            s.ias_kt = s.gs_kt
            if s.gs_kt >= 150:
                s.on_ground = False
                self._set_mode("climb")
        elif m == "climb":
            s.gear_down = s.agl_ft < 300
            s.flaps = 0.0 if s.agl_ft > 3000 else 0.25
            tgt = self._target_alt()
            s.ias_kt = 250.0 if s.alt_msl_ft < 10000 else 290.0
            if "overspeed" in self.faults and s.alt_msl_ft < 10000:
                s.ias_kt = 290
            diff = tgt - s.alt_msl_ft
            if "bust" in self.faults and s.alt_msl_ft < 8000:
                diff = 1000
            s.vs_fpm = max(-2000, min(2500, diff * 2.0)) if abs(diff) > 30 else 0.0
            if s.agl_ft > 1500:
                s.hdg_mag = bearing_deg(s.lat, s.lon, self.arr.lat, self.arr.lon)
            if ctl and ctl.cruise_fl and abs(s.alt_msl_ft - tgt) < 50 and tgt > ctl.cruise_fl * 100 - 1000:
                self._set_mode("cruise")
        elif m in ("cruise", "descent"):
            tgt = self._target_alt()
            diff = tgt - s.alt_msl_ft
            s.vs_fpm = max(-2200, min(2000, diff * 2.0)) if abs(diff) > 30 else 0.0
            s.ias_kt = 290.0 if s.alt_msl_ft > 10500 else 250.0
            s.hdg_mag = bearing_deg(s.lat, s.lon, self.arr.lat, self.arr.lon)
            if diff < -100:
                self.mode = "descent"
            if self._flag("approach") and self.arr.distance_km(s.lat, s.lon) < 40:
                self._set_mode("approach")
        elif m == "approach":
            d = self.arr.distance_km(s.lat, s.lon)
            rwy = ctl.arr_rwy if ctl else None
            s.ias_kt = 180.0 if d > 12 else 145.0
            s.landing_lights = True
            if d < 25 and rwy:
                s.hdg_mag = rwy.hdg
            # движемся к КТА, по 3° глиссаде
            self._brg_override = bearing_deg(s.lat, s.lon, self.arr.lat, self.arr.lon)
            gp = self.arr.elevation_ft + d * 1000 * math.tan(math.radians(3)) * M_TO_FT
            tgt = min(self._target_alt(), gp) if self._flag("approach") else self._target_alt()
            diff = tgt - s.alt_msl_ft
            s.vs_fpm = max(-1800, min(1500, diff * 2.0)) if abs(diff) > 20 else 0.0
            s.gear_down = d < 18 and "gear_up" not in self.faults
            s.flaps = 1.0 if d < 15 else 0.5
            if d < 0.8 or s.alt_msl_ft <= self.arr.elevation_ft + 5:
                s.on_ground = True
                s.vs_fpm = 0.0
                s.alt_msl_ft = self.arr.elevation_ft + 5
                self._set_mode("rollout")
        elif m == "rollout":
            s.ias_kt = s.gs_kt = max(15.0, s.gs_kt - 4.0 * dt)
            s.n1 = [25.0, 25.0]
            if s.gs_kt <= 15:
                s.landing_lights = s.strobe = False
                self._set_mode("taxi_in")
        elif m == "taxi_in":
            s.gs_kt = 15.0 if el < 60 else 0.0
            s.ias_kt = 0.0
            if el > 62:
                s.parking_brake = 1.0
                s.n1, s.n2 = [0.0, 0.0], [0.0, 0.0]
                s.beacon = False
                self._set_mode("done")
                self.done = True
        # кинематика
        if m == "approach" and hasattr(self, "_brg_override"):
            dist_km = s.gs_kt * 1.852 / 3600.0 * dt
            s.lat, s.lon = destination(s.lat, s.lon, self._brg_override, dist_km)
        else:
            self._move(dt)
        if not s.on_ground:
            s.alt_msl_ft += s.vs_fpm / 60.0 * dt
            s.gs_kt = s.ias_kt * (1 + s.alt_msl_ft / 1000.0 * 0.02)
        s.agl_ft = max(0.0, s.alt_msl_ft - (self.dep.elevation_ft if m in ("climb", "roll") else self.arr.elevation_ft)) \
            if not s.on_ground else 0.0
        self._update_baro()
        self._indicated()
        return s


class ScriptedPilot:
    """Автоматический пилот-радиообмен (текстом) — для демо и сквозных тестов."""

    def __init__(self, controller, flight: MockFlight, delay: float = 4.0):
        self.ctl = controller
        self.f = flight
        self.delay = delay
        self.last_tx_id = None
        self.next_t = 0.0
        self.done: set = set()
        self.last_com = flight.s.com1_khz
        self.checked_in_khz = None

    @staticmethod
    def rwy_words(rid: str) -> str:
        side = rid[2:] if len(rid) > 2 else ""
        return f"{rid[:2]} {RWY_SIDE.get(side, '')}".strip()

    def readback_text(self, items: dict) -> str:
        cs = self.ctl.r.callsign
        parts = []
        for k, v in items.items():
            if k == "squawk":
                parts.append(f"ответчик {v}")
            elif k == "level":
                parts.append(f"эшелон {v}")
            elif k == "alt_ft":
                parts.append(f"{v} футов")
            elif k == "freq":
                parts.append(f"частота {v}")
            elif k == "runway":
                parts.append(f"ВПП {self.rwy_words(v)}")
            elif k == "qnh":
                parts.append(f"давление {v}")
        return ", ".join(parts) + f", {cs}"

    def step(self, s: SimState) -> List[str]:
        ctl, f = self.ctl, self.f
        if s.t < self.next_t:
            return []
        out: List[str] = []
        cs = ctl.r.callsign
        lt = ctl.last_tx
        # 1) readback последней передачи
        if ctl.pending and ctl.pending.seq != self.last_tx_id and lt is not None:
            self.last_tx_id = ctl.pending.seq
            out.append(self.readback_text(ctl.pending.items))
        # 2) первый выход на связь на новой частоте
        elif s.com1_khz != self.checked_in_khz and ctl.controlling is not None and \
                abs(s.com1_khz - (ctl.controlling.khz)) > 3 and ctl.handoff_to and \
                abs(s.com1_khz - ctl.handoff_to.khz) <= 3:
            self.checked_in_khz = s.com1_khz
            u = ctl.handoff_to
            if u.type in ("radar", "approach", "control") and not s.on_ground:
                if ctl.cleared and ctl.cleared.kind == "fl":
                    rep = f"эшелон {int(round(s.alt_ind_ft / 100.0))} {'в наборе' if s.vs_fpm > 300 else ''} {'эшелона' if s.vs_fpm > 300 else ''} {ctl.cleared.value if s.vs_fpm > 300 else ''}"
                    if s.vs_fpm < -300:
                        rep = f"эшелон {int(round(s.alt_ind_ft / 100.0))} снижаюсь до эшелона {ctl.cleared.value}"
                else:
                    rep = f"{int(round(s.alt_ind_ft / 100.0) * 100)} футов"
                out.append(f"{u.callsign}, {cs}, добрый день, {rep}")
            elif u.type == "tower" and not s.on_ground:
                out.append(f"{u.callsign}, {cs}, на посадочном")
            elif u.type == "tower":
                out.append(f"{u.callsign}, {cs}, на предварительном, к взлёту готов")
            elif u.type == "ground" and ctl.phase in (Phase.TAXI_IN, Phase.LANDING):
                out.append(f"{u.callsign}, {cs}, полосу освободил, разрешите рулить на стоянку")
            elif u.type == "ground":
                out.append(f"{u.callsign}, {cs}, стоянка 20, разрешите буксировку и запуск")
        # 3) сценарий наземных запросов
        elif "clr" not in self.done and s.t > 3:
            self.done.add("clr")
            out.append(f"{cs}, стоянка 20, информация Альфа, прошу разрешение до {ctl.arr.name_gen}")
        elif "taxi" not in self.done and f.mode == "ready_taxi" and ctl.flags["startup"]:
            self.done.add("taxi")
            out.append(f"{cs}, разрешите руление")
        elif "ready" not in self.done and f.mode == "holding" and ctl.controlling and ctl.controlling.type == "tower" \
                and not ctl.flags["takeoff"]:
            self.done.add("ready")
            out.append(f"{cs}, на предварительном, к взлёту готов")
        if out:
            self.next_t = s.t + self.delay
        return out


class MockSource(DataSource):
    """Источник данных для приложения: MockFlight в реальном (ускоренном) времени."""
    name = "mock"

    def __init__(self, flight: MockFlight, time_scale: float = 4.0, hz: float = 5.0):
        super().__init__()
        self.flight = flight
        self.scale = time_scale
        self.hz = hz
        self._stop = threading.Event()
        self.on_step = None   # callback(sim) — для ScriptedPilot в демо

    def clock(self) -> float:
        return self.flight.t          # модельное (ускоренное) время

    def start(self) -> None:
        threading.Thread(target=self._run, name="mock", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        dt_real = 1.0 / self.hz
        while not self._stop.is_set():
            st = self.flight.step(dt_real * self.scale)
            with self._lock:
                self._state = SimState(**{k: getattr(st, k) for k in st.__dataclass_fields__})
                self._state.n1, self._state.n2 = list(st.n1), list(st.n2)
                self._state.connected = True
                self.last_update = time.monotonic()
            if self.on_step:
                try:
                    self.on_step(self._state)
                except Exception:  # pragma: no cover
                    pass
            time.sleep(dt_real)
