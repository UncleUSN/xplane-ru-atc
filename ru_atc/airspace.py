"""Аэродромы, органы ОВД, секторы РЦ, геометрия."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml

from .config import resolve_path

EARTH_R_KM = 6371.0
UNIT_TYPES = ("delivery", "ground", "tower", "radar", "approach", "control")
# Каналы 8.33 кГц стоят через 8.33, каналы 25 кГц — через 25.
# 8 кГц закрывает округление подписи канала и dataref, но не соседний канал.
COM_MATCH_KHZ = 8


def com_match(mhz: float, khz: int, tolerance: int = COM_MATCH_KHZ) -> bool:
    """Совпадает ли частота органа (МГц) с COM1 (кГц) с допуском округления."""
    try:
        mine = int(round(float(mhz) * 1000))
    except (TypeError, ValueError):
        return False
    return abs(mine - int(khz)) <= int(tolerance)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(lat, lon, brg, dist_km) -> Tuple[float, float]:
    d = dist_km / EARTH_R_KM
    b = math.radians(brg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _ring_area(poly: List[List[float]]) -> float:
    if len(poly) < 3:
        return 1e18
    acc = 0.0
    for i in range(len(poly)):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % len(poly)]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


def point_in_polygon(lat: float, lon: float, poly: List[List[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            xint = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < xint:
                inside = not inside
    return inside


@dataclass
class Unit:
    type: str
    callsign: str
    freq: float
    voice: Optional[str] = None
    airport: Optional[str] = None
    sector_id: Optional[str] = None
    source: str = ""
    # Прежние частоты: yaml до apt.dat и apt.dat до atc.dat. Пилот может быть на любой из них.
    aliases: List[float] = field(default_factory=list)

    @property
    def khz(self) -> int:
        return int(round(self.freq * 1000))

    def matches_khz(self, khz: int, tolerance: int = COM_MATCH_KHZ) -> bool:
        return any(com_match(mhz, khz, tolerance) for mhz in (self.freq, *self.aliases))

    @property
    def key(self) -> str:
        return f"{self.airport or self.sector_id}:{self.type}:{self.khz}"


@dataclass
class Runway:
    id: str
    hdg: float
    ils: Optional[float] = None


@dataclass
class Airport:
    icao: str
    name: str
    name_gen: str
    lat: float
    lon: float
    elevation_ft: float
    transition_altitude_ft: int
    transition_levels: List[Dict]
    squawk_range: Tuple[str, str]
    initial_climb: Dict
    runways: List[Runway]
    units: Dict[str, Unit]
    preferred_departure: List[str] = field(default_factory=list)
    preferred_arrival: List[str] = field(default_factory=list)
    approach_radius_km: float = 70
    radar_radius_km: float = 40
    atis_mhz: Optional[float] = None   # ряд 1050 apt.dat или atis_freq в yaml; не орган для ответа

    def unit(self, t: str) -> Optional[Unit]:
        return self.units.get(t)

    def transition_level(self, qnh_hpa: float) -> int:
        for row in self.transition_levels:
            if qnh_hpa >= row["qnh_min"]:
                return int(row["fl"])
        return int(self.transition_levels[-1]["fl"]) if self.transition_levels else 110

    def runway(self, rid: str) -> Optional[Runway]:
        for r in self.runways:
            if r.id.upper() == str(rid).upper():
                return r
        return None

    def select_runway(self, wind_dir: float, wind_kt: float, arrival: bool = False,
                      forced: str = "") -> Runway:
        if forced and self.runway(forced):
            return self.runway(forced)
        pref = [self.runway(r) for r in (self.preferred_arrival if arrival else self.preferred_departure)]
        pref = [r for r in pref if r] or list(self.runways)
        if wind_kt < 6:   # штиль (< 3 м/с) — предпочтительная ВПП
            return pref[0]
        return min(pref, key=lambda r: angle_diff(r.hdg, wind_dir))

    def assign_squawk(self, rng: random.Random | None = None) -> str:
        rng = rng or random.Random()
        lo, hi = int(self.squawk_range[0], 8), int(self.squawk_range[1], 8)
        return format(rng.randint(lo, hi), "04o")

    def distance_km(self, lat: float, lon: float) -> float:
        return haversine_km(self.lat, self.lon, lat, lon)


@dataclass
class Sector:
    id: str
    callsign: str
    freq: float
    polygon: List[List[float]]
    floor_ft: float = 0
    ceiling_ft: float = 99999
    # 0 — центр из atc.dat, 1 — CTR/FIR из airspace.txt, 2 — yaml, 3 — TopLevel.
    # Среди yaml и TopLevel побеждает первый в списке (как раньше). Среди данных — меньший полигон.
    priority: int = 2
    source: str = "yaml"
    role: str = "ctr"
    facility_id: str = ""
    extra_freqs: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.area = _ring_area(self.polygon)
        if len(self.polygon) >= 3:
            lats = [p[0] for p in self.polygon]
            lons = [p[1] for p in self.polygon]
            self._min_lat, self._max_lat = min(lats), max(lats)
            self._min_lon, self._max_lon = min(lons), max(lons)
            self._bbox_ok = (self._max_lon - self._min_lon) <= 180
        else:
            self._bbox_ok = False

    def unit(self) -> Unit:
        return Unit("control", self.callsign, self.freq, sector_id=self.id, source=self.source)

    def contains(self, lat: float, lon: float) -> bool:
        return point_in_polygon(lat, lon, self.polygon)

    def bbox_hits(self, lat: float, lon: float) -> bool:
        if not self._bbox_ok:
            return True
        return self._min_lat <= lat <= self._max_lat and self._min_lon <= lon <= self._max_lon

    def covers_alt(self, alt_ft: Optional[float]) -> bool:
        if alt_ft is None:
            return True
        return self.floor_ft <= alt_ft <= self.ceiling_ft


def pick_sector(sectors: List[Sector], lat: float, lon: float,
                alt_ft: Optional[float] = None) -> Optional[Sector]:
    """Сектор под точкой.

    Меньший ``priority`` побеждает. На одном уровне у данных X-Plane берётся меньший
    полигон (затем более высокий нижний край). У yaml и TopLevel остаётся первый
    подходящий в списке — порядок в ``airspace.yaml`` по-прежнему важен.
    ``alt_ft is None`` не фильтрует по высоте.
    """
    best: Optional[Sector] = None
    for s in sectors:
        if not s.covers_alt(alt_ft) or not s.bbox_hits(lat, lon) or not s.contains(lat, lon):
            continue
        if best is None or s.priority < best.priority:
            best = s
            continue
        if s.priority != best.priority or s.priority >= 2:
            continue
        if (s.area, -s.floor_ft) < (best.area, -best.floor_ft):
            best = s
    return best


class Airspace:
    def __init__(self, airports: Dict[str, Airport], sectors: List[Sector]):
        self.airports = airports
        self.sectors = sectors

    @classmethod
    def load(cls, airports_file: str, airspace_file: str) -> "Airspace":
        with open(resolve_path(airports_file), encoding="utf-8") as f:
            ad = yaml.safe_load(f)
        with open(resolve_path(airspace_file), encoding="utf-8") as f:
            sd = yaml.safe_load(f)
        return cls.from_dicts(ad, sd)

    @classmethod
    def from_dicts(cls, ad: Dict, sd: Dict) -> "Airspace":
        airports: Dict[str, Airport] = {}
        for icao, a in (ad.get("airports") or {}).items():
            units = {}
            for t, u in (a.get("units") or {}).items():
                if u and u.get("freq"):
                    units[t] = Unit(t, u["callsign"], float(u["freq"]), u.get("voice"), airport=icao)
            airports[icao] = Airport(
                icao=icao, name=a.get("name", icao), name_gen=a.get("name_gen", a.get("name", icao)),
                lat=float(a["lat"]), lon=float(a["lon"]), elevation_ft=float(a.get("elevation_ft", 0)),
                transition_altitude_ft=int(a.get("transition_altitude_ft", 10000)),
                transition_levels=a.get("transition_levels") or [{"qnh_min": 0, "fl": 110}],
                squawk_range=tuple(str(x).zfill(4) for x in a.get("squawk_range", ["2000", "2077"])),
                initial_climb=a.get("initial_climb") or {"alt_ft": 5000},
                runways=[Runway(str(r["id"]), float(r["hdg"]), r.get("ils")) for r in a.get("runways", [])],
                units=units,
                preferred_departure=[str(x) for x in a.get("preferred_departure", [])],
                preferred_arrival=[str(x) for x in a.get("preferred_arrival", [])],
                approach_radius_km=float(a.get("approach_radius_km", 70)),
                radar_radius_km=float(a.get("radar_radius_km", 40)),
                atis_mhz=float(a["atis_freq"]) if a.get("atis_freq") else None,
            )
        sectors = [Sector(s["id"], s["callsign"], float(s["freq"]), s["polygon"], float(s.get("floor_ft", 0)))
                   for s in (sd.get("sectors") or [])]
        return cls(airports, sectors)

    def nearest_airport(self, lat: float, lon: float) -> Tuple[Optional[Airport], float]:
        best, bd = None, 1e9
        for a in self.airports.values():
            d = a.distance_km(lat, lon)
            if d < bd:
                best, bd = a, d
        return best, bd

    def sector_at(self, lat: float, lon: float, alt_ft: Optional[float] = None) -> Optional[Sector]:
        return pick_sector(self.sectors, lat, lon, alt_ft)

    def all_units(self) -> List[Unit]:
        out = [u for a in self.airports.values() for u in a.units.values()]
        out += [s.unit() for s in self.sectors]
        return out

    def units_on_freq(self, khz: int) -> List[Unit]:
        return [u for u in self.all_units() if u.matches_khz(khz)]
