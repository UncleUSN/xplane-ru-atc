"""Собственные datarefs FMS Zibo (laminar/B738/fms/...).

Проверено дампом CDU/FMS (UUEE 24C → ULLI 28L, FL330, ноябрь 2026):
  laminar/B738/fms/ref_icao, ref_runway, dest_icao, dest_runway — аэродромы и ВПП;
  flight09 — «UUEE - ULLI» (запасной вариант, если отдельных ICAO нет);
  legs — идентификаторы через пробел, включая аэропорты, RWxx, (INTC) и уход на второй круг;
  legs_pth — по 2 символа на участок (TF, DF, IF, CF, CI, HM…), длина = 2 × число участков;
  legs_lat / legs_lon — float[256], координата i относится к участку i (хвост — нули);
  num_of_wpts — число участков в строке legs (включая аэропорты и (INTC));
  laminar/B738/FMS/fpln_dist — длина маршрута, м. мили; dist_dest — остаток до назначения;
  laminar/B738/FMS/fmc_gw_app — НЕ имя захода (число, похоже на вес), не использовать.
Имени SID/STAR в datarefs нет: схема есть только на CDU и только с маркером <SEL>/<ACT>.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .model import FlightPlan, Waypoint, norm_icao, norm_proc, norm_rwy, parse_cruise_fl

PREFIXES = ("laminar/B738/fms/", "laminar/B738/FMS/")
SRC = "Zibo dataref"

# (поле, regex по хвосту имени, нормализатор). Порядок важен: первое совпадение побеждает.
FIELD_PATTERNS: List[Tuple[str, re.Pattern, object]] = [
    ("origin", re.compile(r"(^|_)(ref|orig|origin|dep|departure)_?(icao|apt|airport)$", re.I), norm_icao),
    ("dest", re.compile(r"(^|_)(dest|des|destination|arr)_?(icao|apt|airport)$", re.I), norm_icao),
    ("dep_rwy", re.compile(r"(^|_)(ref|dep|orig|departure)_?(rwy|runway)$", re.I), norm_rwy),
    ("arr_rwy", re.compile(r"(^|_)(dest|des|arr|destination)_?(rwy|runway)$", re.I), norm_rwy),
    ("sid_trans", re.compile(r"(^|_)sid_?(tns|trans|transition)(_name)?$", re.I), norm_proc),
    ("sid", re.compile(r"(^|_)sid(_name)?$", re.I), norm_proc),
    ("star_trans", re.compile(r"(^|_)star_?(tns|trans|transition)(_name)?$", re.I), norm_proc),
    ("star", re.compile(r"(^|_)star(_name)?$", re.I), norm_proc),
    ("app_trans", re.compile(r"(^|_)(app|appr|approach)_?(tns|trans|transition)(_name)?$", re.I), norm_proc),
    # Именно имя захода. Голый суффикс _app цепляет fmc_gw_app (число, не схема).
    ("approach", re.compile(r"(^|_)(?:approach|appr)(?:_name)?$", re.I), norm_proc),
    ("cruise_fl", re.compile(r"(^|_)(crz|cruise)_?(alt|altitude|fl|level)$", re.I), parse_cruise_fl),
    ("flight_no", re.compile(r"(^|_)(flt|flight)_?(no|num|number|id)$", re.I),
     lambda v: str(v or "").strip().upper()),
]

INTERESTING_RE = re.compile(r"icao|rwy|runway|sid|star|app|crz|cruise|flt|flight|legs|wpt|orig|dest|"
                            r"des_|ref_|route|rte|fpln|num_of", re.I)


def is_interesting(name: str) -> bool:
    tail = name.split("/")[-1]
    return any(p.search(tail) for _, p, _ in FIELD_PATTERNS) or bool(INTERESTING_RE.search(tail))


_PAIR_RE = re.compile(r"^([A-Z]{4})\s*-\s*([A-Z]{4})$")
_TOKEN_RE = re.compile(r"\([^)]+\)|[A-Z0-9]+")
_RWY_LEG_RE = re.compile(r"^RW(\d{2}[LRC]?)$")
_FF_LEG_RE = re.compile(r"^FF(\d{2}[LRC]?)$")
_INTC_RE = re.compile(r"^\(?INTC\)?$")
# Имя захода как отдельный участок (ILS28L). FF28L — конечная точка, не тип захода.
_APP_NAME_RE = re.compile(r"^(?:ILS|LOC|RNV|RNAV|RNP|VOR|NDB|GLS)\d{2}[LRC]?$")


def plan_from_values(values: Dict[str, object]) -> FlightPlan:
    """values: имя dataref -> значение (строки уже обычный текст)."""
    fp = FlightPlan()
    for name, val in sorted(values.items()):
        tail = name.split("/")[-1]
        low = tail.lower()
        if low == "dist_dest":
            fp.dist_dest_nm = _positive_nm(val)
            continue
        if low == "fpln_dist":
            fp.route_nm = _positive_nm(val)
            continue
        for f, pat, norm in FIELD_PATTERNS:
            if pat.search(tail):
                v = val[0] if isinstance(val, list) and val and f == "cruise_fl" else val
                if isinstance(v, list):
                    break
                nv = norm(v)
                if f == "flight_no" and not re.match(r"^[A-Z0-9]{3,8}$", nv or ""):
                    nv = ""
                if f == "cruise_fl" and isinstance(v, (int, float)) and not v:
                    nv = None
                fp.set(f, nv, f"{SRC} {tail}")
                break
    # «UUEE - ULLI» в flight09 — только если отдельных ref_icao/dest_icao нет.
    for name, val in values.items():
        tail = name.split("/")[-1]
        if re.fullmatch(r"flight\d+", tail, re.I) and isinstance(val, str):
            m = _PAIR_RE.match(val.strip().upper())
            if m:
                fp.set("origin", norm_icao(m.group(1)), f"{SRC} {tail}")
                fp.set("dest", norm_icao(m.group(2)), f"{SRC} {tail}")
    apply_legs(fp, values)
    return fp.finalize()


def _positive_nm(val) -> Optional[float]:
    if isinstance(val, list):
        val = val[0] if val else None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if x <= 0 or x > 20000:
        return None
    return x


def _as_int(val) -> int:
    if isinstance(val, list):
        val = val[0] if val else 0
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0


def tokenize_legs(legs: str) -> List[str]:
    """Участки строки legs: идентификаторы и целые токены в скобках, например (INTC)."""
    return _TOKEN_RE.findall((legs or "").upper())


def legs_to_waypoints(legs: str, values: Dict[str, object], origin: str = "", dest: str = "") -> List[Waypoint]:
    """Маршрут по legs: без аэропортов, ВПП, (INTC), точек захода FF28L и ухода на второй круг.

    Уход на второй круг — всё, что после ВПП назначения (последняя RWxx). Координаты берутся
    по исходному индексу участка, до фильтрации.
    """
    tokens = tokenize_legs(legs)
    n = _as_int(values.get("laminar/B738/fms/num_of_wpts"))
    if 0 < n < len(tokens):
        tokens = tokens[:n]
    _dep, _arr, arr_index = classify_runways(tokens, dest)
    end = arr_index if arr_index is not None else len(tokens)
    lats = values.get("laminar/B738/fms/legs_lat")
    lons = values.get("laminar/B738/fms/legs_lon")
    out: List[Waypoint] = []
    for i, ident in enumerate(tokens[:end]):
        if _skip_enroute(ident, origin, dest):
            continue
        w = Waypoint(ident)
        if isinstance(lats, list) and isinstance(lons, list) and len(lats) > i and len(lons) > i:
            try:
                la, lo = float(lats[i]), float(lons[i])
                if abs(la) > 0.01 or abs(lo) > 0.01:
                    w.lat, w.lon = la, lo
            except (TypeError, ValueError):
                pass
        if out and out[-1].ident == w.ident:
            continue
        out.append(w)
    return out


def classify_runways(tokens: List[str], dest: str = "") -> Tuple[str, str, Optional[int]]:
    """(ВПП вылета, ВПП посадки, индекс ВПП посадки в tokens).

    В списке Zibo первая RWxx в начале — вылет (UUEE RW24C …), последняя другая RWxx — посадка,
    после неё уход на второй круг. Единственная ВПП в начале вылетом и остаётся.
    """
    positions: List[Tuple[int, str]] = []
    for i, tok in enumerate(tokens):
        m = _RWY_LEG_RE.match(tok)
        if m:
            positions.append((i, m.group(1)))
    dep = arr = ""
    arr_index: Optional[int] = None
    if positions:
        i0, r0 = positions[0]
        if i0 <= 1:
            dep = r0
        il, rl = positions[-1]
        if il != i0:
            arr, arr_index = rl, il
        else:
            tail = tokens[il + 1:]
            missed = (dest and dest in tail) or any(_INTC_RE.match(t) for t in tail)
            if missed or i0 > 1:
                arr, arr_index = rl, il
    if not arr:
        for i, tok in enumerate(tokens):
            m = _FF_LEG_RE.match(tok)
            if m:
                arr = m.group(1)
                arr_index = i          # FF28L тоже не маршрутная точка; дальше — заход и уход
    return dep, arr, arr_index


def _skip_enroute(ident: str, origin: str, dest: str) -> bool:
    if ident and ident in (origin, dest):
        return True
    if _RWY_LEG_RE.match(ident) or _INTC_RE.match(ident) or _FF_LEG_RE.match(ident):
        return True
    if _APP_NAME_RE.match(ident):
        return True
    return False


def apply_legs(fp: FlightPlan, values: Dict[str, object]) -> None:
    legs = values.get("laminar/B738/fms/legs")
    if not isinstance(legs, str) or not legs.strip():
        return
    tokens = tokenize_legs(legs)
    n = _as_int(values.get("laminar/B738/fms/num_of_wpts"))
    if 0 < n < len(tokens):
        tokens = tokens[:n]
    dep, arr, _ = classify_runways(tokens, fp.dest)
    fp.set("dep_rwy", dep, f"{SRC} legs")
    fp.set("arr_rwy", arr, f"{SRC} legs")
    for tok in tokens:
        if _APP_NAME_RE.match(tok):
            fp.set("approach", norm_proc(tok), f"{SRC} legs")
            break
    wpts = legs_to_waypoints(legs, values, fp.origin, fp.dest)
    if wpts:
        fp.waypoints = wpts
        fp.sources["waypoints"] = f"{SRC} legs"
