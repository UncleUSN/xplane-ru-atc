"""apt.dat 1200 (и старые 1050–1130): заголовок аэродрома, ВПП, частоты 50–56 и 1050–1056.

Ряд 100: после семи общих полей два конца ВПП. Лишние колонки более новых
редакций не сбивают разбор: концы ищутся по идентификатору ``06L`` / ``24C``.
Если в записи есть ряды 1050–1056, ряды 50–56 того же аэродрома игнорируются,
как это делает X-Plane.
Идентификатор: ``1302 icao_id``, если он есть, иначе код в заголовке ряда 1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional

from ..airspace import bearing_deg, haversine_km
from .parse_nav import iter_data_lines

_RUNWAY = re.compile(r"^\d{2}[LRCWST]?$", re.I)
_ICAO = re.compile(r"^[A-Z0-9]{3,7}$")

APT_KIND = {
    1050: "atis", 1051: "unicom", 1052: "delivery", 1053: "ground",
    1054: "tower", 1055: "approach", 1056: "departure",
    50: "atis", 51: "unicom", 52: "delivery", 53: "ground",
    54: "tower", 55: "approach", 56: "departure",
}

_HEADERS = {1, 16, 17}


@dataclass
class AptRunway:
    ident: str
    lat: float
    lon: float
    opposite: str
    opposite_lat: float
    opposite_lon: float
    heading_true: float
    length_m: float


@dataclass
class AptComm:
    code: int
    kind: str
    mhz: float
    name: str


@dataclass
class AptAirport:
    icao: str
    name: str
    elev_ft: float
    lat: Optional[float]
    lon: Optional[float]
    runways: List[AptRunway] = field(default_factory=list)
    comms: List[AptComm] = field(default_factory=list)
    transition_alt_ft: Optional[int] = None
    source: str = ""


def comm_mhz(code: int, raw: str) -> Optional[float]:
    try:
        value = int(float(raw))
    except ValueError:
        return None
    if 1050 <= code <= 1056:
        if not 100000 <= value <= 999999:
            return None
        return value / 1000.0
    if 50 <= code <= 56:
        if not 10000 <= value <= 99999:
            return None
        return value / 100.0
    return None


def _heading(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Курс конца — направление от противоположного порога к этому.
    return bearing_deg(lat2, lon2, lat1, lon1)


def _length_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_km(lat1, lon1, lat2, lon2) * 1000.0


def _runway_ends(tokens: List[str]) -> Optional[tuple]:
    indexes = [i for i, token in enumerate(tokens) if _RUNWAY.match(token)]
    if len(indexes) < 2:
        return None
    i1, i2 = indexes[0], indexes[1]

    def end(index: int):
        if index + 2 >= len(tokens):
            return None
        try:
            return tokens[index].upper(), float(tokens[index + 1]), float(tokens[index + 2])
        except ValueError:
            return None

    a, b = end(i1), end(i2)
    if not a or not b:
        return None
    return a, b


def _flush(current: Optional[dict]) -> Optional[AptAirport]:
    if not current:
        return None
    icao = (current.get("icao_id") or current.get("header_id") or "").upper()
    if not _ICAO.match(icao):
        return None
    comms: List[AptComm] = current["comms"]
    if any(item.code >= 1050 for item in comms):
        comms = [item for item in comms if item.code >= 1050]
    lat, lon = current.get("view_lat"), current.get("view_lon")
    if lat is None and current["thresholds"]:
        lats = [p[0] for p in current["thresholds"]]
        lons = [p[1] for p in current["thresholds"]]
        lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
    return AptAirport(
        icao=icao, name=current.get("name") or icao, elev_ft=float(current.get("elev") or 0),
        lat=lat, lon=lon, runways=list(current["runways"]), comms=comms,
        transition_alt_ft=current.get("transition_alt"), source=current.get("source") or "",
    )


def parse_apt_lines(lines: Iterable[str], source: str = "") -> Iterator[AptAirport]:
    current: Optional[dict] = None
    for line in lines:
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        code = int(parts[0])
        if code in _HEADERS:
            done = _flush(current)
            if done:
                yield done
            header_id = parts[4].upper() if len(parts) > 4 else ""
            try:
                elev = float(parts[1])
            except (ValueError, IndexError):
                elev = 0.0
            current = {
                "header_id": header_id, "elev": elev, "name": " ".join(parts[5:]) or header_id,
                "comms": [], "runways": [], "thresholds": [], "source": source,
            }
            continue
        if current is None:
            continue
        if code == 100 and len(parts) >= 18:
            ends = _runway_ends(parts[8:])
            if not ends:
                continue
            (id1, lat1, lon1), (id2, lat2, lon2) = ends
            length = _length_m(lat1, lon1, lat2, lon2)
            current["runways"].append(AptRunway(
                id1, lat1, lon1, id2, lat2, lon2, _heading(lat1, lon1, lat2, lon2), length))
            current["runways"].append(AptRunway(
                id2, lat2, lon2, id1, lat1, lon1, _heading(lat2, lon2, lat1, lon1), length))
            current["thresholds"].extend([(lat1, lon1), (lat2, lon2)])
        elif code == 14 and len(parts) >= 3:
            try:
                current["view_lat"] = float(parts[1])
                current["view_lon"] = float(parts[2])
            except ValueError:
                pass
        elif code == 1302 and len(parts) >= 3:
            key = parts[1].lower()
            value = " ".join(parts[2:])
            if key in ("icao_id", "icao"):
                current["icao_id"] = value.strip().upper()
            elif key.startswith("transition_alt"):
                try:
                    feet = int(float(value.split()[0]))
                except ValueError:
                    feet = 0
                if 1000 <= feet <= 18000:
                    current["transition_alt"] = feet
        elif code in APT_KIND and len(parts) >= 2:
            mhz = comm_mhz(code, parts[1])
            if mhz is None or not 108.0 <= mhz <= 137.0:
                continue
            current["comms"].append(AptComm(code, APT_KIND[code], mhz, " ".join(parts[2:])))
    done = _flush(current)
    if done:
        yield done


def parse_apt_text(text: str, source: str = "") -> List[AptAirport]:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped in ("I", "A", "99"):
            continue
        lines.append(stripped)
    return list(parse_apt_lines(lines, source))


def parse_apt_file(path, source: str = "") -> Iterator[AptAirport]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield from parse_apt_lines(iter_data_lines(handle), source or str(path))
