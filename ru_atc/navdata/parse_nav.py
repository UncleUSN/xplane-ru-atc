"""earth_nav.dat (XP NAV1200), earth_fix.dat (XP FIX1200), earth_awy.dat (XP AWY1101).

Спецификации Laminar: XP-NAV1200, XP-FIX1200, XP-AWY1101.
В файле airway версия в заголовке по-прежнему строка «1100 Version».
Координат у участка трассы нет: только идентификатор и код региона,
координаты подставляются из fix/nav при сборке кэша.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, TextIO

_HEADER = re.compile(r"\b\d{3,4}\s+Version\b", re.I)
_RUNWAY = re.compile(r"^\d{2}[LRCWST]?$", re.I)


@dataclass
class Navaid:
    code: int
    lat: float
    lon: float
    elev_ft: float
    freq_mhz: Optional[float]
    freq_khz: Optional[int]
    range_nm: float
    bearing_true: float
    ident: str
    airport: str
    region: str
    runway: str
    name: str


@dataclass
class Fix:
    lat: float
    lon: float
    ident: str
    airport: str
    region: str
    name: str


@dataclass
class AirwaySeg:
    fix1: str
    region1: str
    kind1: int
    fix2: str
    region2: str
    kind2: int
    direction: str
    level: str
    base_fl: int
    top_fl: int
    names: List[str]


def header_lines(path, limit: int = 4) -> str:
    lines = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            text = raw.strip()
            if text:
                lines.append(text[:300])
            if len(lines) >= limit:
                break
    return " | ".join(lines)


def cycle_of(header: str) -> str:
    match = re.search(r"data cycle\s+(\d{4})", header or "", re.I)
    return match.group(1) if match else ""


def iter_data_lines(handle: TextIO) -> Iterator[str]:
    for raw in handle:
        text = raw.strip()
        if not text or text in ("I", "A", "99"):
            continue
        if text.startswith("#"):
            continue
        if _HEADER.search(text) and "cycle" in text.lower():
            continue
        yield text


def true_bearing(encoded: float) -> float:
    """Курс ЛК: магнитный курс × 360 прибавлен к истинному. ``% 360`` достаёт истинный."""
    return float(encoded) % 360.0


def _float(token: str) -> Optional[float]:
    try:
        return float(token)
    except ValueError:
        return None


def parse_nav_line(line: str) -> Optional[Navaid]:
    parts = line.split()
    if len(parts) < 11 or not parts[0].isdigit():
        return None
    code = int(parts[0])
    if code not in (2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16):
        return None
    lat, lon = _float(parts[1]), _float(parts[2])
    if lat is None or lon is None:
        return None
    elev = _float(parts[3]) or 0.0
    try:
        freq_raw = int(float(parts[4]))
    except ValueError:
        return None
    range_nm = _float(parts[5]) or 0.0
    bearing = _float(parts[6]) or 0.0
    ident = parts[7].upper()
    airport = parts[8].upper()
    region = parts[9].upper()
    rest = parts[10:]
    runway = ""
    if code in (4, 5, 6, 7, 8, 9, 12, 13, 14, 16) and rest and _RUNWAY.match(rest[0]):
        runway = rest[0].upper()
        rest = rest[1:]
    name = " ".join(rest)
    freq_mhz: Optional[float] = None
    freq_khz: Optional[int] = None
    if code == 2:
        freq_khz = freq_raw
    elif code in (14, 15, 16):
        freq_khz = freq_raw
    else:
        freq_mhz = freq_raw / 100.0
    course = true_bearing(bearing) if code in (4, 5, 7, 8, 9) else bearing
    return Navaid(code, lat, lon, elev, freq_mhz, freq_khz, range_nm, course,
                  ident, airport, region, runway, name)


def parse_nav_text(text: str) -> List[Navaid]:
    return [row for row in (parse_nav_line(line) for line in text.splitlines()) if row]


def parse_fix_line(line: str) -> Optional[Fix]:
    parts = line.split()
    if len(parts) < 5:
        return None
    lat, lon = _float(parts[0]), _float(parts[1])
    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
        return None
    ident = parts[2].upper()
    if not re.fullmatch(r"[A-Z0-9]{2,6}", ident):
        return None
    airport = parts[3].upper()
    region = parts[4].upper()
    name = " ".join(parts[5:]) or ident
    return Fix(lat, lon, ident, airport, region, name)


def parse_fix_text(text: str) -> List[Fix]:
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped in ("I", "A", "99") or _HEADER.search(stripped):
            continue
        row = parse_fix_line(stripped)
        if row:
            rows.append(row)
    return rows


def parse_awy_line(line: str) -> Optional[AirwaySeg]:
    parts = line.split()
    if len(parts) < 11:
        return None
    if parts[6].upper() not in ("N", "F", "B"):
        return None
    if parts[7] not in ("1", "2"):
        return None
    try:
        kind1, kind2 = int(parts[2]), int(parts[5])
        base, top = int(float(parts[8])), int(float(parts[9]))
    except ValueError:
        return None
    names = [n for n in parts[10].upper().split("-") if n]
    if not names:
        return None
    return AirwaySeg(parts[0].upper(), parts[1].upper(), kind1,
                     parts[3].upper(), parts[4].upper(), kind2,
                     parts[6].upper(), "high" if parts[7] == "2" else "low",
                     base, top, names)


def parse_awy_text(text: str) -> List[AirwaySeg]:
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped in ("I", "A", "99") or _HEADER.search(stripped):
            continue
        row = parse_awy_line(stripped)
        if row:
            rows.append(row)
    return rows


def parse_nav_file(path) -> Iterable[Navaid]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in iter_data_lines(handle):
            row = parse_nav_line(line)
            if row:
                yield row


def parse_fix_file(path) -> Iterable[Fix]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in iter_data_lines(handle):
            row = parse_fix_line(line)
            if row:
                yield row


def parse_awy_file(path) -> Iterable[AirwaySeg]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in iter_data_lines(handle):
            row = parse_awy_line(line)
            if row:
                yield row
