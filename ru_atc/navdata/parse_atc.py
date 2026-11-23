"""``atc.dat`` (формат ATCFILE 1000) и OpenAir ``airspace.txt``.

``atc.dat`` — документ Laminar «atc.dat», обновлён 10 мая 2024.
Файл X-Plane 12: ``Resources/default scenery/1200 atc data/Earth nav data/atc.dat``.
Подписка кладёт замену в ``Custom Data/1200 atc data/Earth nav data/atc.dat``:
этот файл целиком заменяет штатный.

Контроллер: NAME, FACILITY_ID, ROLE (del/gnd/twr/tracon/ctr), ICAO,
FREQ (МГц × 100, шаг 25 кГц) и/или CHAN (кГц, 8.33),
полигоны ``AIRSPACE_POLYGON_BEGIN <низ_ft> <верх_ft>`` / ``POINT широта долгота``.
Первая частота в файле — та, которую симулятор берёт основной.
Секторы внутри одного органа X-Plane не моделирует: несколько FREQ принадлежат
одному контроллеру, без привязки к кускам полигона.

``atc_regions.dat`` рядом — фиктивные контроллеры TopLevel на весь мир.
Их имя всегда TopLevel. Это запасной слой, не замена РЦ.

``airspace.txt`` — OpenAir (не формат Laminar). С 12-й версии лежит в
``Resources/default data/airspaces/airspace.txt``. Частота — строка AF, позывной — AG.
Дуги DA/DB и круги DC в выбор сектора не идут: для границы нужен полигон DP.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

_DMS = re.compile(
    r"(\d+):(\d+):(\d+(?:\.\d+)?)\s*([NSns])\s+(\d+):(\d+):(\d+(?:\.\d+)?)\s*([EWew])"
)
_DDM = re.compile(
    r"(\d+):(\d+(?:\.\d+)?)\s*([NSns])\s+(\d+):(\d+(?:\.\d+)?)\s*([EWew])"
)
_ALT = re.compile(r"(FL\s*)?(\d+(?:\.\d+)?)")


@dataclass
class AtcPolygon:
    floor_ft: float
    ceiling_ft: float
    points: List[List[float]] = field(default_factory=list)


@dataclass
class AtcController:
    name: str = ""
    spoken_name: str = ""
    facility_id: str = ""
    role: str = ""
    icao: str = ""
    freqs: List[float] = field(default_factory=list)
    polygons: List[AtcPolygon] = field(default_factory=list)
    transition_alt_ft: Optional[int] = None
    toplevel: bool = False
    source: str = ""


@dataclass
class OpenAirspace:
    name: str = ""
    klass: str = ""
    ay: str = ""
    freq_mhz: Optional[float] = None
    station: str = ""
    floor_ft: float = 0
    ceiling_ft: float = 99999
    polygon: List[List[float]] = field(default_factory=list)
    geom: str = "none"
    source: str = ""

    def is_center(self) -> bool:
        token = (self.ay or self.klass or "").upper()
        return token in ("CTR", "ACC", "FIR", "UIR", "ACCSEC") and self.freq_mhz is not None and len(self.polygon) >= 3


def _freq_token(kind: str, raw: str) -> Optional[float]:
    try:
        value = int(float(raw))
    except ValueError:
        return None
    mhz = value / 1000.0 if kind == "CHAN" else value / 100.0
    if 108.0 <= mhz <= 137.0:
        return round(mhz, 3)
    return None


def parse_atc_text(text: str, source: str = "", toplevel: bool = False) -> List[AtcController]:
    controllers: List[AtcController] = []
    current: Optional[AtcController] = None
    poly: Optional[AtcPolygon] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line in ("I", "A", "ATCFILE"):
            continue
        if line == "CONTROLLER":
            current = AtcController(source=source, toplevel=toplevel)
            poly = None
            continue
        if line == "CONTROLLER_END":
            if current and (current.freqs or current.polygons):
                if current.name.strip().upper() == "TOPLEVEL":
                    current.toplevel = True
                controllers.append(current)
            current = None
            poly = None
            continue
        if current is None:
            continue
        if line.startswith("AIRSPACE_POLYGON_BEGIN"):
            parts = line.split()
            try:
                a = float(parts[1])
                b = float(parts[2]) if len(parts) > 2 else 99999.0
            except (ValueError, IndexError):
                a, b = 0.0, 99999.0
            poly = AtcPolygon(min(a, b), max(a, b))
            continue
        if line == "AIRSPACE_POLYGON_END":
            if poly and len(poly.points) >= 3:
                current.polygons.append(poly)
            poly = None
            continue
        if line.startswith("POINT") and poly is not None:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    poly.points.append([float(parts[1]), float(parts[2])])
                except ValueError:
                    pass
            continue
        if " " not in line:
            continue
        key, value = line.split(None, 1)
        key = key.upper()
        value = value.strip()
        if key == "NAME":
            current.name = value
        elif key == "SPOKEN_NAME":
            current.spoken_name = value
        elif key == "FACILITY_ID":
            current.facility_id = value.upper()
        elif key == "ROLE":
            current.role = value.lower()
        elif key == "ICAO":
            current.icao = value.upper()
        elif key in ("FREQ", "CHAN"):
            mhz = _freq_token(key, value.split()[0])
            if mhz is not None:
                current.freqs.append(mhz)
        elif key == "TRANSITION_ALT":
            try:
                feet = int(float(value.split()[0]))
            except ValueError:
                feet = 0
            if 1000 <= feet <= 18000:
                current.transition_alt_ft = feet
    return controllers


def _dms_to_deg(deg: str, minutes: str, seconds: str, hemi: str) -> float:
    sign = -1 if hemi.upper() in ("S", "W") else 1
    return sign * (int(deg) + int(minutes) / 60.0 + float(seconds) / 3600.0)


def _ddm_to_deg(deg: str, minutes: str, hemi: str) -> float:
    sign = -1 if hemi.upper() in ("S", "W") else 1
    return sign * (int(deg) + float(minutes) / 60.0)


def parse_openair_point(text: str) -> Optional[List[float]]:
    match = _DMS.search(text)
    if match:
        lat = _dms_to_deg(match.group(1), match.group(2), match.group(3), match.group(4))
        lon = _dms_to_deg(match.group(5), match.group(6), match.group(7), match.group(8))
        return [lat, lon]
    match = _DDM.search(text)
    if match:
        lat = _ddm_to_deg(match.group(1), match.group(2), match.group(3))
        lon = _ddm_to_deg(match.group(4), match.group(5), match.group(6))
        return [lat, lon]
    return None


def parse_openair_alt(text: str, default: float) -> float:
    raw = (text or "").strip().upper()
    if not raw:
        return default
    if raw in ("GND", "SFC", "GROUND", "MSL"):
        return 0.0
    if raw in ("UNL", "UNLIM", "UNLIMITED"):
        return 99999.0
    match = _ALT.search(raw)
    if not match:
        return default
    value = float(match.group(2))
    if match.group(1) or raw.startswith("FL"):
        return value * 100.0
    if re.search(r"\bM\b", raw) and "MSL" not in raw and "FT" not in raw:
        return value * 3.28084
    return value


def parse_openair_text(text: str, source: str = "") -> List[OpenAirspace]:
    blocks: List[OpenAirspace] = []
    current: Optional[OpenAirspace] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("#"):
            continue
        code = line[:2].upper()
        rest = line[2:].strip()
        if code == "AC":
            if current and (current.polygon or current.freq_mhz):
                blocks.append(current)
            current = OpenAirspace(klass=rest.upper(), source=source)
            continue
        if current is None:
            continue
        if code == "AN":
            current.name = rest
        elif code == "AY":
            current.ay = rest.upper()
        elif code == "AF":
            try:
                current.freq_mhz = float(rest.split()[0])
            except ValueError:
                current.freq_mhz = None
        elif code == "AG":
            current.station = rest
        elif code == "AH":
            current.ceiling_ft = parse_openair_alt(rest, 99999.0)
        elif code == "AL":
            current.floor_ft = parse_openair_alt(rest, 0.0)
        elif code == "DP":
            point = parse_openair_point(rest)
            if point:
                current.polygon.append(point)
                current.geom = "polygon"
        elif code in ("DA", "DB"):
            current.geom = "arc"
        elif code == "DC":
            current.geom = "circle"
    if current and (current.polygon or current.freq_mhz):
        blocks.append(current)
    return blocks


def parse_atc_file(path, toplevel: bool = False) -> List[AtcController]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_atc_text(text, source=str(path), toplevel=toplevel)


def parse_openair_file(path) -> List[OpenAirspace]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_openair_text(text, source=str(path))
