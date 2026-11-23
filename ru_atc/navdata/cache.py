"""SQLite-кэш навигации X-Plane и запросы коридора / сектора."""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..airspace import Sector, bearing_deg, destination, haversine_km, pick_sector, point_in_polygon
from ..airspace import _ring_area
from .names import control_callsign
from .parse_apt import parse_apt_file
from .parse_atc import parse_atc_file, parse_openair_file
from .parse_cifp import parse_cifp_file
from .parse_nav import parse_awy_file, parse_fix_file, parse_nav_file
from .sources import SCHEMA, SourceSet

log = logging.getLogger("ru_atc.navdata")

Progress = Callable[[str, float], None]
Point = Tuple[float, float]

SCHEMA_SQL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE navaids (
  ident TEXT, name TEXT, code INTEGER, lat REAL, lon REAL, elev_ft REAL,
  freq_mhz REAL, freq_khz INTEGER, range_nm REAL, bearing REAL,
  airport TEXT, region TEXT, runway TEXT, source TEXT
);
CREATE TABLE fixes (
  ident TEXT, name TEXT, lat REAL, lon REAL, airport TEXT, region TEXT, source TEXT
);
CREATE TABLE airways (
  name TEXT, level TEXT, direction TEXT,
  fix1 TEXT, region1 TEXT, lat1 REAL, lon1 REAL,
  fix2 TEXT, region2 TEXT, lat2 REAL, lon2 REAL,
  base_fl INTEGER, top_fl INTEGER, source TEXT
);
CREATE TABLE procedures (
  airport TEXT, kind TEXT, ident TEXT, route_type TEXT, transition TEXT,
  runway TEXT, seq INTEGER, fix TEXT, path_term TEXT, source TEXT
);
CREATE TABLE airports (
  icao TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, elev_ft REAL,
  transition_alt_ft INTEGER, source TEXT
);
CREATE TABLE runways (
  airport TEXT, ident TEXT, lat REAL, lon REAL, heading_true REAL,
  length_m REAL, opposite TEXT
);
CREATE TABLE frequencies (
  airport TEXT, kind TEXT, mhz REAL, name TEXT, source TEXT
);
CREATE TABLE controllers (
  facility_id TEXT, name TEXT, spoken TEXT, role TEXT, icao TEXT,
  freq REAL, extra TEXT, floor_ft REAL, ceiling_ft REAL, polygon TEXT,
  transition_alt INTEGER, toplevel INTEGER, source TEXT
);
CREATE TABLE airspaces (
  name TEXT, klass TEXT, ay TEXT, freq REAL, station TEXT,
  floor_ft REAL, ceiling_ft REAL, polygon TEXT, geom TEXT, center INTEGER, source TEXT
);
"""


class NavDataError(RuntimeError):
    pass


def _noop(_message: str, _fraction: float) -> None:
    return None


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=OFF")
    return db


def _meta(db: sqlite3.Connection, key: str) -> str:
    try:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return ""
    return row["value"] if row else ""


@dataclass
class NavFix:
    ident: str
    lat: float
    lon: float
    airport: str = ""
    region: str = ""
    name: str = ""


@dataclass
class NavAid:
    ident: str
    lat: float
    lon: float
    code: int
    freq_mhz: Optional[float]
    name: str
    airport: str
    runway: str
    region: str


@dataclass
class NavAirway:
    name: str
    level: str
    direction: str
    fix1: str
    fix2: str
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    base_fl: int
    top_fl: int


@dataclass
class NavProc:
    airport: str
    kind: str
    ident: str
    runway: str
    transition: str


@dataclass
class NavZone:
    name: str
    freq_mhz: Optional[float]
    station: str
    kind: str


@dataclass
class Corridor:
    navaids: List[NavAid] = field(default_factory=list)
    fixes: List[NavFix] = field(default_factory=list)
    airways: List[NavAirway] = field(default_factory=list)
    procedures: List[NavProc] = field(default_factory=list)
    zones: List[NavZone] = field(default_factory=list)

    def summary(self) -> str:
        bits: List[str] = []
        vors = [n for n in self.navaids if n.code == 3 and n.freq_mhz][:3]
        if vors:
            bits.append(", ".join(f"{n.ident} {n.freq_mhz:.2f}" for n in vors))
        procs = []
        seen = set()
        for proc in self.procedures:
            key = (proc.airport, proc.ident)
            if key in seen:
                continue
            seen.add(key)
            procs.append(f"{proc.airport} {proc.ident}")
            if len(procs) >= 4:
                break
        if procs:
            bits.append(", ".join(procs))
        if not bits:
            return ""
        return "Рядом: " + " | ".join(bits)


class NavCache:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self._lock = threading.Lock()
        self._sectors: Optional[List[Sector]] = None
        self._controllers: Optional[List[dict]] = None

    def close(self) -> None:
        try:
            self.db.close()
        except sqlite3.Error:
            pass

    def _controllers_rows(self) -> List[dict]:
        if self._controllers is None:
            rows = []
            for row in self.db.execute("SELECT * FROM controllers"):
                item = dict(row)
                try:
                    item["polygon"] = json.loads(item["polygon"] or "[]")
                except json.JSONDecodeError:
                    item["polygon"] = []
                extra = item.get("extra") or ""
                item["extra_freqs"] = [float(x) for x in extra.split(",") if x]
                rows.append(item)
            self._controllers = rows
        return self._controllers

    def sectors(self) -> List[Sector]:
        if self._sectors is not None:
            return self._sectors
        built: List[Sector] = []
        for row in self._controllers_rows():
            if row["role"] != "ctr" or not row["freq"] or len(row["polygon"]) < 3:
                continue
            toplevel = bool(row["toplevel"])
            built.append(Sector(
                id=row["facility_id"] or row["name"] or "ctr",
                callsign=control_callsign(row["name"], row["spoken"] or ""),
                freq=float(row["freq"]),
                polygon=row["polygon"],
                floor_ft=float(row["floor_ft"] or 0),
                ceiling_ft=float(row["ceiling_ft"] or 99999),
                priority=3 if toplevel else 0,
                source="atc_regions.dat" if toplevel else "atc.dat",
                role="ctr",
                facility_id=row["facility_id"] or "",
                extra_freqs=list(row["extra_freqs"]),
            ))
        for row in self.db.execute(
                "SELECT * FROM airspaces WHERE center=1 AND freq IS NOT NULL"):
            try:
                poly = json.loads(row["polygon"] or "[]")
            except json.JSONDecodeError:
                continue
            if len(poly) < 3:
                continue
            built.append(Sector(
                id="oa:" + (row["name"] or row["station"] or "ctr"),
                callsign=control_callsign(row["station"] or row["name"] or ""),
                freq=float(row["freq"]),
                polygon=poly,
                floor_ft=float(row["floor_ft"] or 0),
                ceiling_ft=float(row["ceiling_ft"] or 99999),
                priority=1,
                source="airspace.txt",
                role="ctr",
            ))
        self._sectors = built
        return built

    def select_sector(self, lat: float, lon: float, alt_ft: Optional[float] = None) -> Optional[Sector]:
        with self._lock:
            return pick_sector(self.sectors(), lat, lon, alt_ft)

    def counts(self) -> Dict[str, int]:
        out = {}
        for table in ("navaids", "fixes", "airways", "procedures", "airports", "frequencies", "controllers"):
            out[table] = self.db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        out["centers"] = sum(1 for s in self.sectors() if s.priority == 0)
        out["toplevel"] = sum(1 for s in self.sectors() if s.priority == 3)
        return out

    def comms(self, icao: str) -> Dict[str, Tuple[float, str, str]]:
        found: Dict[str, Tuple[float, str, str]] = {}
        for row in self.db.execute(
                "SELECT kind, mhz, name, source FROM frequencies WHERE airport=? ORDER BY rowid",
                (icao.upper(),)):
            found.setdefault(row["kind"], (float(row["mhz"]), row["name"] or "", row["source"] or ""))
        return found

    def localizer_mhz(self, icao: str, runway: str) -> Optional[float]:
        want = _norm_rwy(runway)
        for row in self.db.execute(
                "SELECT runway, freq_mhz FROM navaids WHERE airport=? AND code IN (4, 5) AND freq_mhz IS NOT NULL",
                (icao.upper(),)):
            if _norm_rwy(row["runway"] or "") == want and row["freq_mhz"]:
                return float(row["freq_mhz"])
        return None

    def tower_override(self, icao: str) -> Optional[Tuple[float, str]]:
        for row in self._controllers_rows():
            if row["role"] == "twr" and (row["icao"] or "").upper() == icao.upper() and row["freq"]:
                return float(row["freq"]), "atc.dat"
        return None

    def role_override(self, icao: str, role: str, kind: str) -> Optional[Tuple[float, str]]:
        for row in self._controllers_rows():
            if row["role"] == role and (row["icao"] or "").upper() == icao.upper() and row["freq"]:
                return float(row["freq"]), "atc.dat"
        return None

    def tracon_override(self, icao: str, lat: Optional[float], lon: Optional[float]) -> Optional[Tuple[float, str]]:
        explicit = None
        best = None
        best_area = 1e18
        for row in self._controllers_rows():
            if row["role"] != "tracon" or not row["freq"]:
                continue
            if (row["icao"] or "").upper() == icao.upper() and row["icao"]:
                explicit = (float(row["freq"]), "atc.dat")
                break
            poly = row["polygon"]
            if lat is None or lon is None or len(poly) < 3:
                continue
            if point_in_polygon(lat, lon, poly):
                area = _ring_area(poly)
                if area < best_area:
                    best_area = area
                    best = (float(row["freq"]), "atc.dat")
        return explicit or best

    def transition_alt(self, icao: str) -> Optional[int]:
        row = self.db.execute(
            "SELECT transition_alt_ft FROM airports WHERE icao=?", (icao.upper(),)).fetchone()
        if row and row["transition_alt_ft"]:
            return int(row["transition_alt_ft"])
        for item in self._controllers_rows():
            if (item["icao"] or "").upper() == icao.upper() and item.get("transition_alt"):
                return int(item["transition_alt"])
        return None

    def airport(self, icao: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM airports WHERE icao=?", (icao.upper(),)).fetchone()

    def runways(self, icao: str) -> List[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM runways WHERE airport=?", (icao.upper(),)))

    def corridor(self, points: Sequence[Point], radius_km: float, icaos: Sequence[str],
                 step_km: float = 25.0) -> Corridor:
        samples = sample_route(list(points), step_km)
        if not samples and not icaos:
            return Corridor()
        result = Corridor()
        explicit = [i.strip().upper() for i in icaos if i and i.strip()]
        with self._lock:
            if samples:
                lat0, lat1, lon0, lon1 = _bbox(samples, radius_km)
                result.navaids = self._near_navaids(lat0, lat1, lon0, lon1, samples, radius_km)
                result.fixes = self._near_fixes(lat0, lat1, lon0, lon1, samples, radius_km)
                result.airways = self._near_airways(lat0, lat1, lon0, lon1, samples, radius_km)
                result.zones = self._near_zones(samples, radius_km)
                for row in self.db.execute(
                        "SELECT icao, lat, lon FROM airports WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                        (lat0, lat1, lon0, lon1)):
                    if row["lat"] is None:
                        continue
                    if _near(row["lat"], row["lon"], samples, radius_km):
                        explicit.append(row["icao"])
            result.procedures = self._procedures(sorted(set(explicit)))
        return result

    def _near_navaids(self, lat0, lat1, lon0, lon1, samples, radius) -> List[NavAid]:
        hits = []
        for row in self.db.execute(
                "SELECT * FROM navaids WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (lat0, lat1, lon0, lon1)):
            if not _near(row["lat"], row["lon"], samples, radius):
                continue
            hits.append((haversine_km(row["lat"], row["lon"], samples[0][0], samples[0][1]), NavAid(
                row["ident"], row["lat"], row["lon"], int(row["code"]), row["freq_mhz"],
                row["name"] or "", row["airport"] or "", row["runway"] or "", row["region"] or "")))
        hits.sort(key=lambda item: item[0])
        return [item[1] for item in hits[:120]]

    def _near_fixes(self, lat0, lat1, lon0, lon1, samples, radius) -> List[NavFix]:
        hits = []
        for row in self.db.execute(
                "SELECT * FROM fixes WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (lat0, lat1, lon0, lon1)):
            if not _near(row["lat"], row["lon"], samples, radius):
                continue
            dist = min(haversine_km(row["lat"], row["lon"], s[0], s[1]) for s in samples)
            hits.append((dist, NavFix(row["ident"], row["lat"], row["lon"],
                                      row["airport"] or "", row["region"] or "", row["name"] or "")))
        hits.sort(key=lambda item: item[0])
        return [item[1] for item in hits[:250]]

    def _near_airways(self, lat0, lat1, lon0, lon1, samples, radius) -> List[NavAirway]:
        hits = []
        for row in self.db.execute(
                """SELECT * FROM airways
                   WHERE lat1 IS NOT NULL AND lat1 BETWEEN ? AND ? AND lon1 BETWEEN ? AND ?""",
                (lat0, lat1, lon0, lon1)):
            if not (_near(row["lat1"], row["lon1"], samples, radius) or
                    _near(row["lat2"], row["lon2"], samples, radius)):
                continue
            hits.append(NavAirway(
                row["name"], row["level"], row["direction"], row["fix1"], row["fix2"],
                row["lat1"], row["lon1"], row["lat2"], row["lon2"],
                int(row["base_fl"] or 0), int(row["top_fl"] or 0)))
            if len(hits) >= 150:
                break
        return hits

    def _near_zones(self, samples, radius) -> List[NavZone]:
        found = []
        for row in self.db.execute("SELECT * FROM airspaces WHERE freq IS NOT NULL"):
            try:
                poly = json.loads(row["polygon"] or "[]")
            except json.JSONDecodeError:
                continue
            if len(poly) < 3:
                continue
            if any(point_in_polygon(lat, lon, poly) for lat, lon in samples):
                found.append(NavZone(row["name"] or "", row["freq"], row["station"] or "",
                                     row["ay"] or row["klass"] or ""))
            if len(found) >= 20:
                break
        return found

    def _procedures(self, icaos: Sequence[str]) -> List[NavProc]:
        if not icaos:
            return []
        marks = ",".join("?" for _ in icaos)
        rows = self.db.execute(
            f"""SELECT airport, kind, ident, runway, transition FROM procedures
                WHERE airport IN ({marks}) ORDER BY airport, kind, ident, seq""",
            tuple(icaos)).fetchall()
        out: List[NavProc] = []
        seen = set()
        for row in rows:
            key = (row["airport"], row["kind"], row["ident"], row["runway"] or "", row["transition"] or "")
            if key in seen:
                continue
            seen.add(key)
            out.append(NavProc(row["airport"], row["kind"], row["ident"],
                               row["runway"] or "", row["transition"] or ""))
            if len(out) >= 400:
                break
        return out


def _norm_rwy(value: str) -> str:
    import re
    match = re.fullmatch(r"0?(\d{1,2})([LRC])?", (value or "").upper())
    if not match:
        return (value or "").upper()
    return f"{int(match.group(1)):02d}{match.group(2) or ''}"


def _near(lat: float, lon: float, samples: Sequence[Point], radius_km: float) -> bool:
    # Грубая отсечка по градусам, затем точная.
    pad = radius_km / 100.0
    for sla, slo in samples:
        if abs(lat - sla) <= pad and abs(lon - slo) <= pad / max(0.2, math.cos(math.radians(lat))):
            if haversine_km(lat, lon, sla, slo) <= radius_km:
                return True
    return False


def _bbox(samples: Sequence[Point], radius_km: float) -> Tuple[float, float, float, float]:
    lats = [p[0] for p in samples]
    lons = [p[1] for p in samples]
    mid = sum(lats) / len(lats)
    pad_lat = radius_km / 110.574 + 0.02
    pad_lon = radius_km / (111.320 * max(0.2, math.cos(math.radians(mid)))) + 0.02
    return min(lats) - pad_lat, max(lats) + pad_lat, min(lons) - pad_lon, max(lons) + pad_lon


def sample_route(points: List[Point], step_km: float) -> List[Point]:
    clean = [(p[0], p[1]) for p in points if p and p[0] is not None and p[1] is not None]
    if not clean:
        return []
    out = [clean[0]]
    for start, end in zip(clean, clean[1:]):
        dist = haversine_km(start[0], start[1], end[0], end[1])
        if dist < 1:
            continue
        steps = max(1, int(dist // step_km))
        bearing = bearing_deg(start[0], start[1], end[0], end[1])
        for index in range(1, steps):
            out.append(destination(start[0], start[1], bearing, step_km * index))
        out.append(end)
    return out


def _executemany(db: sqlite3.Connection, sql: str, rows: Iterable[tuple], chunk: int = 2000) -> int:
    batch: List[tuple] = []
    total = 0
    for row in rows:
        batch.append(row)
        if len(batch) >= chunk:
            db.executemany(sql, batch)
            total += len(batch)
            batch.clear()
    if batch:
        db.executemany(sql, batch)
        total += len(batch)
    return total


def build_cache(db: sqlite3.Connection, sources: SourceSet, progress: Progress = _noop) -> None:
    db.executescript(SCHEMA_SQL)
    coords: Dict[Tuple[str, str], Point] = {}
    progress("Читаю маяки и точки", 0.02)

    def remember(ident: str, region: str, lat: float, lon: float) -> None:
        if ident and region:
            coords[(ident, region)] = (lat, lon)

    nav_sql = """INSERT INTO navaids (ident, name, code, lat, lon, elev_ft, freq_mhz, freq_khz,
                 range_nm, bearing, airport, region, runway, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    fix_sql = "INSERT INTO fixes (ident, name, lat, lon, airport, region, source) VALUES (?,?,?,?,?,?,?)"
    files = [item for item in sources.files if item.role in ("earth_nav", "user_nav", "earth_fix", "user_fix")]
    # Сначала база, потом user_*: одинаковый ключ в словаре координат перезаписывается.
    order = {"earth_nav": 0, "earth_fix": 1, "user_nav": 2, "user_fix": 3}
    files.sort(key=lambda item: order.get(item.role, 9))
    done = 0
    for item in files:
        layer = item.layer
        if item.role in ("earth_nav", "user_nav"):
            rows = []
            for nav in parse_nav_file(item.path):
                if layer == "user":
                    db.execute("DELETE FROM navaids WHERE ident=? AND region=? AND code=?",
                               (nav.ident, nav.region, nav.code))
                rows.append((nav.ident, nav.name, nav.code, nav.lat, nav.lon, nav.elev_ft,
                             nav.freq_mhz, nav.freq_khz, nav.range_nm, nav.bearing_true,
                             nav.airport, nav.region, nav.runway, layer))
                remember(nav.ident, nav.region, nav.lat, nav.lon)
                done += 1
                if done % 50000 == 0:
                    progress(f"{item.path.name}: {done}", 0.05 + min(0.2, done / 500000))
            _executemany(db, nav_sql, rows)
        else:
            rows = []
            for fix in parse_fix_file(item.path):
                if layer == "user":
                    db.execute(
                        "DELETE FROM fixes WHERE ident=? AND region=? AND airport=?",
                        (fix.ident, fix.region, fix.airport))
                rows.append((fix.ident, fix.name, fix.lat, fix.lon, fix.airport, fix.region, layer))
                remember(fix.ident, fix.region, fix.lat, fix.lon)
                done += 1
                if done % 50000 == 0:
                    progress(f"{item.path.name}: {done}", 0.25 + min(0.2, done / 800000))
            _executemany(db, fix_sql, rows)
        log.info("прочитан %s (%s)", item.path, item.role)
    progress("Читаю трассы", 0.5)
    awy_sql = """INSERT INTO airways (name, level, direction, fix1, region1, lat1, lon1,
                 fix2, region2, lat2, lon2, base_fl, top_fl, source)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    for item in sources.files:
        if item.role != "earth_awy":
            continue
        rows = []
        for seg in parse_awy_file(item.path):
            c1 = coords.get((seg.fix1, seg.region1))
            c2 = coords.get((seg.fix2, seg.region2))
            for name in seg.names:
                rows.append((name, seg.level, seg.direction, seg.fix1, seg.region1,
                             c1[0] if c1 else None, c1[1] if c1 else None,
                             seg.fix2, seg.region2,
                             c2[0] if c2 else None, c2[1] if c2 else None,
                             seg.base_fl, seg.top_fl, item.layer))
        _executemany(db, awy_sql, rows)
    progress("Читаю схемы CIFP", 0.62)
    proc_sql = """INSERT INTO procedures (airport, kind, ident, route_type, transition, runway,
                  seq, fix, path_term, source) VALUES (?,?,?,?,?,?,?,?,?,?)"""
    cifp_files = []
    for folder in sources.cifp_dirs:
        if folder.is_dir():
            cifp_files.extend(sorted(p for p in folder.iterdir() if p.suffix.lower() == ".dat" and p.is_file()))
    total = max(1, len(cifp_files))
    for index, path in enumerate(cifp_files, 1):
        rows = [(leg.airport, leg.kind, leg.ident, leg.route_type, leg.transition, leg.runway,
                 leg.seq, leg.fix, leg.path_term, "cifp") for leg in parse_cifp_file(path)]
        if rows:
            _executemany(db, proc_sql, rows)
        if index % 40 == 0 or index == total:
            progress(f"CIFP {index}/{total}", 0.62 + 0.15 * index / total)
    if sources.faa_cifp and sources.faa_cifp.is_file():
        progress("FAACIFP18", 0.78)
        legs = list(parse_cifp_file(sources.faa_cifp))
        airports = sorted({leg.airport for leg in legs})
        if airports:
            marks = ",".join("?" for _ in airports)
            db.execute(f"DELETE FROM procedures WHERE airport IN ({marks})", airports)
            _executemany(db, proc_sql, (
                (leg.airport, leg.kind, leg.ident, leg.route_type, leg.transition, leg.runway,
                 leg.seq, leg.fix, leg.path_term, "faa") for leg in legs))
    progress("Читаю аэродромы apt.dat", 0.8)
    apt_total = max(1, len(sources.apt_files))
    for index, item in enumerate(sources.apt_files, 1):
        for apt in parse_apt_file(item.path, source=item.role):
            db.execute("DELETE FROM runways WHERE airport=?", (apt.icao,))
            db.execute("DELETE FROM frequencies WHERE airport=?", (apt.icao,))
            db.execute(
                """INSERT OR REPLACE INTO airports (icao, name, lat, lon, elev_ft, transition_alt_ft, source)
                   VALUES (?,?,?,?,?,?,?)""",
                (apt.icao, apt.name, apt.lat, apt.lon, apt.elev_ft, apt.transition_alt_ft, apt.source))
            db.executemany(
                """INSERT INTO runways (airport, ident, lat, lon, heading_true, length_m, opposite)
                   VALUES (?,?,?,?,?,?,?)""",
                [(apt.icao, rwy.ident, rwy.lat, rwy.lon, rwy.heading_true, rwy.length_m, rwy.opposite)
                 for rwy in apt.runways])
            db.executemany(
                "INSERT INTO frequencies (airport, kind, mhz, name, source) VALUES (?,?,?,?,?)",
                [(apt.icao, comm.kind, comm.mhz, comm.name, apt.source) for comm in apt.comms])
        progress(f"apt.dat {index}/{apt_total}", 0.8 + 0.1 * index / apt_total)
    progress("Читаю atc.dat", 0.92)
    _load_controllers(db, sources)
    progress("Читаю зоны airspace.txt", 0.96)
    for item in sources.files:
        if item.role != "airspace":
            continue
        for zone in parse_openair_file(item.path):
            db.execute(
                """INSERT INTO airspaces (name, klass, ay, freq, station, floor_ft, ceiling_ft,
                   polygon, geom, center, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (zone.name, zone.klass, zone.ay, zone.freq_mhz, zone.station, zone.floor_ft,
                 zone.ceiling_ft, json.dumps(zone.polygon), zone.geom, 1 if zone.is_center() else 0,
                 item.layer))
    db.executescript("""
        CREATE INDEX ix_fix_lat ON fixes(lat);
        CREATE INDEX ix_nav_lat ON navaids(lat);
        CREATE INDEX ix_nav_ap ON navaids(airport);
        CREATE INDEX ix_awy_lat ON airways(lat1);
        CREATE INDEX ix_ap ON airports(icao);
        CREATE INDEX ix_proc ON procedures(airport);
        CREATE INDEX ix_freq ON frequencies(airport);
        CREATE INDEX ix_rwy ON runways(airport);
    """)
    db.execute("INSERT INTO meta (key, value) VALUES ('schema', ?)", (SCHEMA,))
    db.commit()
    progress("Кэш собран", 1.0)


def _load_controllers(db: sqlite3.Connection, sources: SourceSet) -> None:
    ordered = []
    for item in sources.files:
        if item.role == "atc":
            ordered.append((item, False))
    for item in sources.files:
        if item.role.startswith("atc_pack:"):
            ordered.append((item, False))
    for item in sources.files:
        if item.role == "atc_regions":
            ordered.append((item, True))
    for item, toplevel in ordered:
        for ctrl in parse_atc_file(item.path, toplevel=toplevel):
            if not ctrl.freqs:
                continue
            if ctrl.facility_id:
                db.execute("DELETE FROM controllers WHERE facility_id=? AND role=?",
                           (ctrl.facility_id, ctrl.role))
            polys = ctrl.polygons or [type("P", (), {"floor_ft": 0, "ceiling_ft": 99999, "points": []})()]
            # Контроллер без полигона (вышка) всё равно нужен: частота перекрывает apt.dat.
            if not ctrl.polygons:
                polys = [type("P", (), {"floor_ft": 0.0, "ceiling_ft": 99999.0, "points": []})()]
            extra = ",".join(f"{mhz:.3f}" for mhz in ctrl.freqs[1:])
            for poly in polys:
                db.execute(
                    """INSERT INTO controllers (facility_id, name, spoken, role, icao, freq, extra,
                       floor_ft, ceiling_ft, polygon, transition_alt, toplevel, source)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ctrl.facility_id, ctrl.name, ctrl.spoken_name, ctrl.role, ctrl.icao,
                     ctrl.freqs[0], extra, poly.floor_ft, poly.ceiling_ft, json.dumps(poly.points),
                     ctrl.transition_alt_ft, 1 if ctrl.toplevel or toplevel else 0, item.layer))


def ensure_cache(root: Path, cache_path: Path, rebuild: bool = False,
                 progress: Progress = _noop) -> Tuple["NavCache", bool, SourceSet]:
    from .sources import collect_sources
    sources = collect_sources(root)
    if not any(item.role == "earth_nav" for item in sources.files):
        raise NavDataError("earth_nav.dat не найден в " + str(root))
    fingerprint = sources.fingerprint()
    if not rebuild and cache_path.exists():
        try:
            db = connect(cache_path)
            if _meta(db, "fingerprint") == fingerprint and _meta(db, "schema") == SCHEMA:
                progress("Кэш навигационных данных актуален", 1.0)
                return NavCache(db), False, sources
            db.close()
        except sqlite3.Error:
            log.info("кэш %s повреждён — соберу заново", cache_path)
    for suffix in ("", "-wal", "-shm"):
        extra = Path(str(cache_path) + suffix) if suffix else cache_path
        try:
            extra.unlink()
        except OSError:
            pass
    db = connect(cache_path)
    try:
        build_cache(db, sources, progress)
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fingerprint', ?)", (fingerprint,))
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', ?)", (str(time.time()),))
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('xplane_root', ?)", (str(root),))
        cycles = sorted({item.cycle for item in sources.files if item.cycle})
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('cycle', ?)",
                   (",".join(cycles),))
        db.commit()
    except Exception:
        db.close()
        try:
            cache_path.unlink()
        except OSError:
            pass
        raise
    return NavCache(db), True, sources
