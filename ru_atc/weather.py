"""Погода для АТИС и для ответа диспетчера.

Два источника, в таком порядке для аэродрома, где самолёта нет:

1. Файл реального погоды X-Plane ``Output/real weather/METAR.rwx``
   (и запасной ``METAR.rwx`` в корне установки). Строка вида
   ``UUEE 231200Z 24005MPS 9999 BKN020 05/02 Q1013``.
2. Если файла нет или станции в нём нет — погода в точке самолёта
   из dataref ``sim/weather/aircraft/...`` (ветер, QNH, видимость,
   температура, точка росы, три слоя облачности). Эти dataref
   необязательные: нет имени в симе — поле остаётся пустым.

Рядом с аэродромом (ближе 30 км или на его земле) берётся погода сима:
она как раз про то место, где стоит самолёт. QFE считается из QNH и
превышения: 27.3 фута на гектопаскаль, затем перевод в миллиметры
ртутного столба — так QFE звучит в российской сводке.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from .model import SimState

FT_PER_HPA = 27.3
MMHG_PER_HPA = 0.75006168
KT_TO_MS = 0.514444
NEAR_KM = 30.0

_WIND = re.compile(r"\b(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)\b")
_CLOUD = re.compile(r"\b(FEW|SCT|BKN|OVC|VV)(\d{3})\b")
_TEMP = re.compile(r"\b(M?\d{2})/(M?\d{2})\b")
_QNH = re.compile(r"\bQ(\d{4})\b")
_ALTIM = re.compile(r"\bA(\d{4})\b")
_STATION = re.compile(r"^([A-Z]{4})\s+\d{6}Z\b")
_VIS_M = re.compile(r"\b(\d{4})\b")
_VIS_SM = re.compile(r"\b(\d{1,2})SM\b")


@dataclass
class CloudLayer:
    coverage: str
    base_ft: Optional[int] = None


@dataclass
class Weather:
    wind_dir: Optional[int] = None
    wind_ms: Optional[int] = None
    wind_gust_ms: Optional[int] = None
    visibility_m: Optional[int] = None
    clouds: List[CloudLayer] = field(default_factory=list)
    temp_c: Optional[int] = None
    dew_c: Optional[int] = None
    qnh_hpa: Optional[int] = None
    cavok: bool = False
    source: str = ""
    raw: str = ""

    def usable(self) -> bool:
        return any(v is not None for v in (self.qnh_hpa, self.wind_dir, self.visibility_m, self.temp_c)) or bool(self.clouds)

    def signature(self) -> tuple:
        """Грубый отпечаток: буква АТИС меняется, когда меняется он, и раз в час."""
        wind = None
        if self.wind_dir is not None or self.wind_ms is not None:
            wind = (None if self.wind_dir is None else int(self.wind_dir) // 10, self.wind_ms, self.wind_gust_ms)
        vis = None if self.visibility_m is None else int(self.visibility_m) // 1000
        clouds = tuple((c.coverage, None if c.base_ft is None else int(c.base_ft) // 500) for c in self.clouds)
        return (wind, vis, clouds, self.temp_c, self.dew_c, self.qnh_hpa, self.cavok)


def qfe_hpa(qnh_hpa: float, elevation_ft: float) -> float:
    return float(qnh_hpa) - float(elevation_ft or 0) / FT_PER_HPA


def qfe_mmhg(qnh_hpa: Optional[float], elevation_ft: float) -> Optional[int]:
    if qnh_hpa is None:
        return None
    return int(round(qfe_hpa(qnh_hpa, elevation_ft) * MMHG_PER_HPA))


def _signed(token: str) -> int:
    if token.startswith(("M", "m")):
        return -int(token[1:])
    return int(token)


def _to_ms(speed: int, unit: str) -> int:
    if unit == "MPS":
        return int(round(speed))
    if unit == "KMH":
        return int(round(speed / 3.6))
    return int(round(speed * KT_TO_MS))


def parse_metar(line: str) -> Weather:
    """Одна сводка METAR. Незнакомые группы пропускаются."""
    text = " ".join((line or "").upper().split())
    wx = Weather(raw=text, source="METAR")
    if "CAVOK" in text.split():
        wx.cavok = True
        wx.visibility_m = 10000
    wind = _WIND.search(text)
    if wind:
        if wind.group(1) != "VRB":
            wx.wind_dir = int(wind.group(1))
        wx.wind_ms = _to_ms(int(wind.group(2)), wind.group(4))
        if wind.group(3):
            wx.wind_gust_ms = _to_ms(int(wind.group(3)), wind.group(4))
    if not wx.cavok:
        sm = _VIS_SM.search(text)
        if sm:
            wx.visibility_m = int(round(int(sm.group(1)) * 1609))
        else:
            # Первое четырёхзначное, которое не время (время уже в шапке ddhhmmZ) и не группа облаков.
            body = _STATION.sub("", text, count=1)
            body = _CLOUD.sub(" ", body)
            vis = _VIS_M.search(body)
            if vis:
                wx.visibility_m = int(vis.group(1))
        for match in _CLOUD.finditer(text):
            kind, hundreds = match.group(1), int(match.group(2))
            base = None if kind == "VV" and hundreds == 0 else hundreds * 100
            wx.clouds.append(CloudLayer(kind, base))
    temp = _TEMP.search(text)
    if temp:
        wx.temp_c = _signed(temp.group(1))
        wx.dew_c = _signed(temp.group(2))
    qnh = _QNH.search(text)
    if qnh:
        wx.qnh_hpa = int(qnh.group(1))
    else:
        alt = _ALTIM.search(text)
        if alt:
            wx.qnh_hpa = int(round(int(alt.group(1)) / 100.0 * 33.8639))
    return wx


def metar_index(text: str) -> dict:
    found = {}
    for line in (text or "").splitlines():
        line = " ".join(line.strip().split())
        match = _STATION.match(line.upper())
        if match:
            found[match.group(1)] = line
    return found


def metar_paths(xplane_path: str | Path) -> List[Path]:
    root = Path(xplane_path)
    return [
        root / "Output" / "real weather" / "METAR.rwx",
        root / "Output" / "real weather" / "metar.rwx",
        root / "METAR.rwx",
    ]


def load_metar(xplane_path: str | Path | None, icao: str) -> Optional[Weather]:
    if not xplane_path or not icao:
        return None
    code = icao.strip().upper()
    for path in metar_paths(xplane_path):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        line = metar_index(text).get(code)
        if not line:
            continue
        wx = parse_metar(line)
        wx.source = f"METAR {path.name}"
        return wx
    return None


def _coverage_word(percent: float) -> str:
    # И доля 0..1, и проценты 0..100.
    value = percent * 100.0 if percent <= 1.5 else percent
    if value < 12:
        return ""
    if value < 25:
        return "FEW"
    if value < 50:
        return "SCT"
    if value < 88:
        return "BKN"
    return "OVC"


def weather_from_sim(state: SimState) -> Weather:
    """Погода в точке самолёта. Ветер и QNH в SimState уже есть, остальное — если dataref пришёл."""
    wx = Weather(source="sim")
    if state.wind_kt or state.wind_dir:
        wx.wind_dir = int(round(state.wind_dir)) % 360
        wx.wind_ms = int(round(state.wind_kt * KT_TO_MS))
    if state.qnh_hpa:
        wx.qnh_hpa = int(round(state.qnh_hpa))
    if state.vis_m is not None and state.vis_m > 0:
        wx.visibility_m = int(round(state.vis_m))
    if state.temp_c is not None:
        wx.temp_c = int(round(state.temp_c))
    if state.dew_c is not None:
        wx.dew_c = int(round(state.dew_c))
    for cov, base in zip(state.cloud_cov, state.cloud_base_m):
        kind = _coverage_word(float(cov or 0))
        if not kind:
            continue
        base_ft = int(round(float(base) * 3.28084)) if base else None
        wx.clouds.append(CloudLayer(kind, base_ft))
    return wx


def weather_for(state: SimState, icao: str, distance_km: float, xplane_path: str | Path | None) -> Weather:
    """У аэродрома — сим, иначе METAR, иначе снова сим, если больше не из чего."""
    sim = weather_from_sim(state)
    if distance_km <= NEAR_KM and sim.usable():
        return sim
    metar = load_metar(xplane_path, icao)
    if metar and metar.usable():
        return metar
    return sim
