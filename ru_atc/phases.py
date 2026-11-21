"""Конечный автомат фаз полёта по данным симулятора."""
from __future__ import annotations

import logging
from enum import Enum
from typing import Callable, List, Optional

from .model import SimState

log = logging.getLogger(__name__)


class Phase(str, Enum):
    PARKED = "PARKED"
    PUSHBACK = "PUSHBACK"
    STARTUP = "STARTUP"
    TAXI_OUT = "TAXI_OUT"
    LINEUP = "LINEUP"
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    DESCENT = "DESCENT"
    APPROACH = "APPROACH"
    LANDING = "LANDING"
    TAXI_IN = "TAXI_IN"
    ARRIVED = "ARRIVED"


PHASE_RU = {
    Phase.PARKED: "Стоянка / получение разрешения",
    Phase.PUSHBACK: "Буксировка",
    Phase.STARTUP: "Запуск двигателей",
    Phase.TAXI_OUT: "Руление на старт",
    Phase.LINEUP: "Исполнительный старт",
    Phase.TAKEOFF: "Взлёт",
    Phase.CLIMB: "Набор высоты",
    Phase.CRUISE: "Крейсерский полёт",
    Phase.DESCENT: "Снижение",
    Phase.APPROACH: "Заход на посадку",
    Phase.LANDING: "Посадка / пробег",
    Phase.TAXI_IN: "Руление на стоянку",
    Phase.ARRIVED: "На стоянке (прибытие)",
}


class PhaseTracker:
    """Определяет фазу по SimState. Контекст (разрешения, аэродромы) передаётся через ctx-функции,
    чтобы автомат можно было тестировать без контроллера."""

    def __init__(self, dep_runway_hdg: Callable[[], Optional[float]] = lambda: None,
                 dist_to_arrival_km: Callable[[SimState], Optional[float]] = lambda s: None,
                 cruise_ft: Callable[[], float] = lambda: 33000,
                 field_elev_ft: Callable[[], float] = lambda: 0.0) -> None:
        self.phase = Phase.PARKED
        self.dep_runway_hdg = dep_runway_hdg
        self.dist_to_arrival_km = dist_to_arrival_km
        self.cruise_ft = cruise_ft
        self.field_elev_ft = field_elev_ft
        self.lineup_cleared = False
        self.pushback_cleared = False
        self.since = 0.0
        self._timers: dict = {}
        self._initialized = False
        self.listeners: List[Callable[[Phase, Phase, SimState], None]] = []
        self.history: List[tuple] = []
        self.max_gs_on_roll = 0.0
        self.go_around = False

    # --- таймеры условий: условие должно держаться dt секунд ---
    def _held(self, name: str, cond: bool, t: float, dur: float) -> bool:
        if not cond:
            self._timers.pop(name, None)
            return False
        start = self._timers.setdefault(name, t)
        return t - start >= dur

    def _set(self, new: Phase, s: SimState) -> None:
        if new == self.phase:
            return
        old = self.phase
        self.phase = new
        self.since = s.t
        self._timers.clear()
        self.history.append((s.t, old.value, new.value))
        log.info("Фаза: %s -> %s", old.value, new.value)
        for cb in self.listeners:
            cb(old, new, s)

    def _initial(self, s: SimState) -> Phase:
        if s.on_ground:
            if s.gs_kt > 40:
                return Phase.TAKEOFF
            if s.engines_running and s.gs_kt > 3:
                return Phase.TAXI_OUT
            return Phase.STARTUP if s.engines_running else Phase.PARKED
        if s.vs_fpm > 500:
            return Phase.CLIMB
        if s.vs_fpm < -500:
            return Phase.DESCENT
        return Phase.CRUISE

    def update(self, s: SimState) -> Phase:
        if not s.connected:
            return self.phase
        if not self._initialized:
            self._initialized = True
            ph = self._initial(s)
            if ph != self.phase:
                self._set(ph, s)
            self.since = s.t
            return self.phase
        p, t = self.phase, s.t
        agl = s.agl_ft

        if p == Phase.PARKED:
            if s.gs_kt > 0.5 and (self.pushback_cleared or (s.max_n1 < 30 and s.gs_kt < 6)) and not s.engines_running:
                self._set(Phase.PUSHBACK, s)
            elif s.gs_kt > 0.5 and self.pushback_cleared:
                self._set(Phase.PUSHBACK, s)
            elif s.engines_running and s.gs_kt > 3:
                self._set(Phase.TAXI_OUT, s)
            elif s.engines_running:
                self._set(Phase.STARTUP, s)
        elif p == Phase.PUSHBACK:
            if s.gs_kt > 6 and s.engines_running:
                self._set(Phase.TAXI_OUT, s)
            elif self._held("push_stop", s.gs_kt < 0.3, t, 5):
                self._set(Phase.STARTUP, s)
        elif p == Phase.STARTUP:
            if s.gs_kt > 3 and s.engines_running:
                self._set(Phase.TAXI_OUT, s)
            elif s.gs_kt > 0.5 and self.pushback_cleared and not s.engines_running:
                self._set(Phase.PUSHBACK, s)
            elif self._held("eng_off", not s.engines_running and s.parking_brake > 0.5, t, 30):
                self._set(Phase.PARKED, s)
        elif p == Phase.TAXI_OUT:
            hdg = self.dep_runway_hdg()
            aligned = hdg is not None and abs((s.hdg_mag - hdg + 180) % 360 - 180) < 10
            if s.gs_kt > 40:
                self._set(Phase.TAKEOFF, s)
            elif aligned and self.lineup_cleared and s.gs_kt < 20:
                self._set(Phase.LINEUP, s)
        elif p == Phase.LINEUP:
            if s.gs_kt > 40:
                self._set(Phase.TAKEOFF, s)
        elif p == Phase.TAKEOFF:
            self.max_gs_on_roll = max(self.max_gs_on_roll, s.gs_kt)
            if not s.on_ground and agl > 50:
                self._set(Phase.CLIMB, s)
            elif s.on_ground and s.gs_kt < 25 and self.max_gs_on_roll > 40:
                log.info("Прерванный взлёт")
                self._set(Phase.TAXI_OUT, s)
        elif p == Phase.CLIMB:
            near_cruise = abs(s.alt_ind_ft - self.cruise_ft()) < 1000 or (
                s.alt_ind_ft > self.cruise_ft() - 1000)
            if self._held("lvl", abs(s.vs_fpm) < 300 and near_cruise, t, 30):
                self._set(Phase.CRUISE, s)
            elif self._held("desc", s.vs_fpm < -500, t, 30):
                self._set(Phase.DESCENT, s)
            elif s.on_ground:
                self._set(Phase.LANDING, s)
        elif p == Phase.CRUISE:
            if self._held("desc", s.vs_fpm < -500, t, 20):
                self._set(Phase.DESCENT, s)
            elif self._held("clb", s.vs_fpm > 500, t, 20) and s.alt_ind_ft < self.cruise_ft() - 1000:
                self._set(Phase.CLIMB, s)
        elif p == Phase.DESCENT:
            d = self.dist_to_arrival_km(s)
            if d is not None and d < 45 and (s.alt_ind_ft - self.field_elev_ft()) < 7000:
                self._set(Phase.APPROACH, s)
            elif s.on_ground:
                self._set(Phase.LANDING, s)
            elif self._held("clb", s.vs_fpm > 500, t, 30) and (d is None or d > 60):
                self._set(Phase.CLIMB, s)
        elif p == Phase.APPROACH:
            if s.on_ground:
                self._set(Phase.LANDING, s)
            elif self._held("ga", s.vs_fpm > 1000 and agl > 200, t, 5):
                self.go_around = True
                log.info("Уход на второй круг")
                self._set(Phase.CLIMB, s)
        elif p == Phase.LANDING:
            if s.on_ground and s.gs_kt < 40:
                self._set(Phase.TAXI_IN, s)
            elif not s.on_ground and agl > 100:
                self._set(Phase.CLIMB, s)   # тач-энд-гоу / уход
        elif p == Phase.TAXI_IN:
            if self._held("park", s.gs_kt < 1 and s.parking_brake > 0.5, t, 3):
                self._set(Phase.ARRIVED, s)
        elif p == Phase.ARRIVED:
            if s.gs_kt > 3 and s.engines_running:
                self._set(Phase.TAXI_IN, s)
        return self.phase
