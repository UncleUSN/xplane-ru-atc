"""Общий интерфейс источника данных и перевод сырых значений datarefs в SimState."""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from ..model import SimState, M_TO_FT, MS_TO_KT, INHG_TO_HPA, normalize_com_khz


def apply_raw(state: SimState, raw: Dict[str, float]) -> SimState:
    """Применить словарь {key: value} (ключи из datarefs.py) к SimState."""
    g = raw.get
    if "lat" in raw: state.lat = float(raw["lat"])
    if "lon" in raw: state.lon = float(raw["lon"])
    if "elev_m" in raw: state.alt_msl_ft = float(raw["elev_m"]) * M_TO_FT
    if "alt_ind_ft" in raw: state.alt_ind_ft = float(raw["alt_ind_ft"])
    if "agl_m" in raw: state.agl_ft = float(raw["agl_m"]) * M_TO_FT
    if "ias_kt" in raw: state.ias_kt = float(raw["ias_kt"])
    if "gs_ms" in raw: state.gs_kt = float(raw["gs_ms"]) * MS_TO_KT
    if "vs_fpm" in raw: state.vs_fpm = float(raw["vs_fpm"])
    if "hdg_mag" in raw: state.hdg_mag = float(raw["hdg_mag"]) % 360
    if "on_ground" in raw: state.on_ground = bool(round(float(raw["on_ground"])))
    if "zibo_air_ground" in raw and "on_ground" not in raw:
        state.on_ground = bool(round(float(raw["zibo_air_ground"])))
    if "parking_brake" in raw: state.parking_brake = float(raw["parking_brake"])
    if "gear_down" in raw: state.gear_down = bool(round(float(raw["gear_down"])))
    if "flaps" in raw: state.flaps = float(raw["flaps"])
    if "xpdr_code" in raw: state.xpdr_code = int(round(float(raw["xpdr_code"])))
    if "xpdr_mode" in raw: state.xpdr_mode = int(round(float(raw["xpdr_mode"])))
    if "com1_raw" in raw: state.com1_khz = normalize_com_khz(raw["com1_raw"])
    if "com1_stby_raw" in raw: state.com1_stby_khz = normalize_com_khz(raw["com1_stby_raw"])
    for k in ("beacon", "strobe", "landing_lights", "taxi_light", "nav_lights"):
        if k in raw:
            setattr(state, k, bool(round(float(raw[k]))))
    for i in (0, 1):
        if f"n1_{i}" in raw: state.n1[i] = float(raw[f"n1_{i}"])
        if f"n2_{i}" in raw: state.n2[i] = float(raw[f"n2_{i}"])
    if "baro_set_inhg" in raw: state.baro_set_hpa = float(raw["baro_set_inhg"]) * INHG_TO_HPA
    if g("qnh_pas"): state.qnh_hpa = float(raw["qnh_pas"]) / 100.0
    if "wind_dir" in raw: state.wind_dir = float(raw["wind_dir"])
    if "wind_ms" in raw: state.wind_kt = float(raw["wind_ms"]) * MS_TO_KT
    if "zibo_xpdr_pos" in raw: state.zibo_xpdr_pos = int(round(float(raw["zibo_xpdr_pos"])))
    if "zibo_baro_std" in raw and float(raw["zibo_baro_std"]) >= 0.5 and "baro_set_inhg" not in raw:
        state.baro_set_hpa = 1013.25
    if "zibo_mcp_alt" in raw: state.mcp_alt_ft = float(raw["zibo_mcp_alt"])
    elif "mcp_alt_ft" in raw: state.mcp_alt_ft = float(raw["mcp_alt_ft"])
    if "local_time_sec" in raw:
        sec = float(raw["local_time_sec"])
        if sec == sec and sec >= 0:
            state.local_time_sec = sec % 86400.0
    return state


class DataSource:
    """Базовый класс: потокобезопасно хранит последнее состояние."""

    name = "base"

    def __init__(self) -> None:
        self._state = SimState()
        self._lock = threading.Lock()
        self._raw: Dict[str, float] = {}
        self.last_update: float = 0.0
        self.error: Optional[str] = None

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def _update_raw(self, raw: Dict[str, float]) -> None:
        with self._lock:
            self._raw.update(raw)
            apply_raw(self._state, raw)
            self._state.t = time.monotonic()
            self._state.connected = True
            self.last_update = time.monotonic()

    def snapshot(self) -> SimState:
        with self._lock:
            s = SimState(**{k: getattr(self._state, k) for k in self._state.__dataclass_fields__})
            s.n1 = list(self._state.n1)
            s.n2 = list(self._state.n2)
            s.t = self.clock()
            s.connected = self.is_connected()
            return s

    def clock(self) -> float:
        """Время для автомата фаз/таймеров: идёт всегда, даже если данные не меняются."""
        return time.monotonic()

    def is_connected(self) -> bool:
        return self.last_update > 0 and time.monotonic() - self.last_update <= 5.0

    def tune_com1(self, khz: int) -> tuple:
        """Поставить частоту на COM1. (успех, короткая строка для журнала)."""
        from ..radio import idle_tune
        return idle_tune(khz)

    def raw(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._raw)
