"""Модель плана полёта, импортированного из FMC Zibo / .fms / config."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

ICAO_RE = re.compile(r"^[A-Z]{4}$")
RWY_RE = re.compile(r"^(?:RW)?(\d{2}[LRC]?)$")
PROC_RE = re.compile(r"^[A-Z]{2,5}\d[A-Z]?$")         # LAKI1G, AKERI2A, TOPL1
AIRWAY_RE = re.compile(r"^[A-Z]{1,2}\d{1,4}[A-Z]?$")    # R22, UL999, B102, T123
FLTNO_RE = re.compile(r"^[A-Z0-9]{2,3}\d{1,5}[A-Z]?$")

FIELDS = ("origin", "dest", "dep_rwy", "sid", "sid_trans", "star", "star_trans",
          "approach", "app_trans", "arr_rwy", "cruise_fl", "flight_no")


def norm_icao(v) -> str:
    v = str(v or "").strip().upper()
    return v if ICAO_RE.match(v) else ""


def norm_rwy(v) -> str:
    """'RW24C' / '24C' / 'RWY 24C' -> '24C'; мусор -> ''."""
    v = str(v or "").strip().upper().replace("RWY", "RW").replace(" ", "")
    m = RWY_RE.match(v)
    return m.group(1) if m else ""


def norm_proc(v) -> str:
    v = str(v or "").strip().upper()
    v = v.replace("<SEL>", "").replace("<ACT>", "").strip()
    if not v or set(v) <= set("-.*_ ") or v in ("NONE", "DIRECT", "VECTORS", "VECTOR"):
        return ""
    return v if re.match(r"^[A-Z0-9\-\.]{2,8}$", v) else ""


def parse_cruise_fl(v) -> Optional[int]:
    """'FL330' / '33000' / '330' / '---/FL330' / 'TRIP/FL350' -> 330."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        n = int(v)
        return n // 100 if n >= 1000 else (n if 10 <= n <= 510 else None)
    s = str(v).upper()
    if "/" in s:
        s = s.split("/")[-1]
    s = s.strip()
    m = re.search(r"FL\s?(\d{2,3})", s)
    if m:
        n = int(m.group(1))
        return n if 10 <= n <= 510 else None
    m = re.search(r"(\d{4,5})", s)
    if m:
        n = int(m.group(1)) // 100
        return n if 10 <= n <= 510 else None
    return None


def approach_runway(app: str) -> str:
    """'ILS28R' -> '28R', 'I06C' -> '06C', 'R35-Y' -> '35', 'RNV24' -> '24'."""
    m = re.search(r"(\d{2}[LRC]?)(?:[-\s]?[A-Z])?$", str(app or "").upper())
    return m.group(1) if m else ""


@dataclass
class Waypoint:
    ident: str
    via: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_ft: float = 0.0
    kind: int = 0

    @property
    def has_pos(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass
class FlightPlan:
    origin: str = ""
    dest: str = ""
    dep_rwy: str = ""
    sid: str = ""
    sid_trans: str = ""
    star: str = ""
    star_trans: str = ""
    approach: str = ""
    app_trans: str = ""
    arr_rwy: str = ""
    cruise_fl: Optional[int] = None
    flight_no: str = ""
    waypoints: List[Waypoint] = field(default_factory=list)
    origin_pos: Optional[Tuple[float, ...]] = None     # (lat, lon, превышение ft) аэродромов из .fms
    dest_pos: Optional[Tuple[float, ...]] = None
    sources: Dict[str, str] = field(default_factory=dict)   # поле -> откуда взято

    def set(self, name: str, value, source: str, overwrite: bool = False) -> bool:
        if value in (None, "", []):
            return False
        cur = getattr(self, name)
        if cur not in (None, "", []) and not overwrite:
            return False
        setattr(self, name, value)
        self.sources[name] = source
        return True

    def fill_from(self, other: "FlightPlan", source: Optional[str] = None) -> None:
        """Заполнить пустые поля значениями из other (other менее приоритетен)."""
        for f in FIELDS:
            self.set(f, getattr(other, f), source or other.sources.get(f, "?"))
        if self.origin_pos is None and other.origin_pos and (not self.origin or self.origin == other.origin):
            self.origin_pos = other.origin_pos
        if self.dest_pos is None and other.dest_pos and (not self.dest or self.dest == other.dest):
            self.dest_pos = other.dest_pos
        if not self.waypoints and other.waypoints:
            self.waypoints = list(other.waypoints)
            self.sources["waypoints"] = source or other.sources.get("waypoints", "?")

    def finalize(self) -> "FlightPlan":
        if not self.arr_rwy and self.approach:
            self.set("arr_rwy", approach_runway(self.approach), self.sources.get("approach", "?") + "(из захода)")
        return self

    def is_empty(self) -> bool:
        return not any(getattr(self, f) for f in FIELDS) and not self.waypoints

    def key(self) -> Tuple:
        return tuple(getattr(self, f) for f in FIELDS) + (tuple(w.ident for w in self.waypoints),)

    def route_idents(self) -> List[str]:
        return [w.ident for w in self.waypoints]

    def summary(self) -> str:
        if self.is_empty():
            return "нет данных"
        dep = " ".join(x for x in (self.origin or "????", self.dep_rwy and f"ВПП {self.dep_rwy}",
                                   self.sid and (self.sid + (f".{self.sid_trans}" if self.sid_trans else ""))) if x)
        arr = " ".join(x for x in (self.dest or "????",
                                   self.star and (self.star + (f".{self.star_trans}" if self.star_trans else "")),
                                   self.approach, self.arr_rwy and f"ВПП {self.arr_rwy}") if x)
        extra = []
        if self.cruise_fl:
            extra.append(f"FL{self.cruise_fl:03d}")
        if self.waypoints:
            extra.append(f"{len(self.waypoints)} тчк")
        if self.flight_no:
            extra.append(f"рейс {self.flight_no}")
        return f"{dep} → {arr}" + (", " + ", ".join(extra) if extra else "")

    def to_dict(self) -> Dict:
        d = {f: getattr(self, f) for f in FIELDS}
        d["waypoints"] = [w.ident for w in self.waypoints]
        d["sources"] = dict(self.sources)
        return d
