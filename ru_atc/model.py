"""Снимок состояния самолёта, общий для всех источников данных."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional

M_TO_FT = 3.28084
MS_TO_KT = 1.943844
PA_PER_HPA = 100.0
INHG_TO_HPA = 33.8639


@dataclass
class SimState:
    t: float = 0.0                 # монотонное время, с
    lat: float = 0.0
    lon: float = 0.0
    alt_msl_ft: float = 0.0        # геометрическая высота MSL (из elevation)
    alt_ind_ft: float = 0.0        # высота по высотомеру КВС (с учётом установленного давления)
    agl_ft: float = 0.0
    ias_kt: float = 0.0
    gs_kt: float = 0.0
    vs_fpm: float = 0.0
    hdg_mag: float = 0.0
    on_ground: bool = True
    parking_brake: float = 1.0     # 0..1
    gear_down: bool = True
    flaps: float = 0.0             # 0..1
    xpdr_code: int = 2000
    xpdr_mode: int = 1             # 0 off,1 stby,2 on(A),3 alt(C),4 test,5 GND,6 TA,7 TA/RA
    com1_khz: int = 0              # активная частота COM1, кГц (напр. 118700)
    com1_stby_khz: int = 0
    beacon: bool = False
    strobe: bool = False
    landing_lights: bool = False
    taxi_light: bool = False
    nav_lights: bool = False
    n1: List[float] = field(default_factory=lambda: [0.0, 0.0])
    n2: List[float] = field(default_factory=lambda: [0.0, 0.0])
    qnh_hpa: float = 1013.25       # фактическое QNH в точке (погода симулятора)
    baro_set_hpa: float = 1013.25  # что установлено на высотомере КВС
    wind_dir: float = 0.0
    wind_kt: float = 0.0
    mcp_alt_ft: float = 0.0        # выставленная на MCP высота (если доступна)
    zibo_xpdr_pos: int = -1        # Zibo: 0 TEST? 1 STBY 2 ALT RPTG OFF 3 XPNDR 4 TA 5 TA/RA (-1 = нет данных)
    connected: bool = False
    local_time_sec: Optional[float] = None  # секунды от местной полуночи в симе; None — нет данных

    # ---- производные ----
    @property
    def engines_running(self) -> bool:
        return any(v > 18.0 for v in self.n2)

    @property
    def any_engine_running(self) -> bool:
        return self.engines_running

    @property
    def all_engines_running(self) -> bool:
        return bool(self.n2) and all(v > 50.0 for v in self.n2)

    @property
    def max_n1(self) -> float:
        return max(self.n1) if self.n1 else 0.0

    @property
    def com1_mhz(self) -> float:
        return round(self.com1_khz / 1000.0, 3)

    @property
    def xpdr_alt_reporting(self) -> bool:
        if self.zibo_xpdr_pos >= 0 and self.zibo_xpdr_pos in (3, 4, 5):
            return True
        return self.xpdr_mode in (3, 5, 6, 7)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["engines_running"] = self.engines_running
        return d


def normalize_com_khz(raw: float) -> int:
    """X-Plane отдаёт com1_frequency_hz_833 как 118700 (кГц), хотя в описании 'hertz'.
    На всякий случай поддерживаем и Гц, и 10-кГц формат старого dataref (11870)."""
    v = float(raw)
    if v > 1e7:          # Гц
        return int(round(v / 1000.0))
    if v > 1e5:          # кГц
        return int(round(v))
    if v > 1e4:          # старый формат 11870 -> 118700
        return int(round(v * 10))
    return int(round(v))
