"""Собственные datarefs FMS Zibo (laminar/B738/fms/...).

Что известно (форум x-plane.org, фрагменты B738.a_fms.lua):
  ИМЕНА ВСТРЕЧАЛИСЬ: laminar/B738/fms/legs (строка), legs_ext, num_of_wpts, legs_lat, legs_lon,
     legs_type, legs_alt_rest1/2, legs_alt_rest_type, legs_alt_calc, fms_legs_rte_type, fpln_nav_id,
     dest_runway_alt, des_icao_alt (форум 2019), laminar/B738/FMS/takeoff_flaps.
  НЕ ПРОВЕРЕНО: отдельные datarefs для ORIGIN/DEST/SID/STAR/ВПП/крейсерского эшелона.
     Автор Zibo на форуме (2018) говорил, что таких нет — только строки экрана CDU.
Поэтому: при подключении забираем ВЕСЬ список datarefs с префиксом laminar/B738/fms/ и сопоставляем
имена по шаблонам. Если в вашей версии Zibo такие datarefs есть — они подхватятся сами;
tools/fmcdump.py покажет всё найденное, чтобы закрепить точные имена.
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
    ("approach", re.compile(r"(^|_)(app|appr|approach)(_name)?$", re.I), norm_proc),
    ("cruise_fl", re.compile(r"(^|_)(crz|cruise)_?(alt|altitude|fl|level)$", re.I), parse_cruise_fl),
    ("flight_no", re.compile(r"(^|_)(flt|flight)_?(no|num|number|id)$", re.I),
     lambda v: str(v or "").strip().upper()),
]

INTERESTING_RE = re.compile(r"icao|rwy|runway|sid|star|app|crz|cruise|flt|flight|legs|wpt|orig|dest|"
                            r"des_|ref_|route|rte|fpln|num_of", re.I)


def is_interesting(name: str) -> bool:
    tail = name.split("/")[-1]
    return any(p.search(tail) for _, p, _ in FIELD_PATTERNS) or bool(INTERESTING_RE.search(tail))


def plan_from_values(values: Dict[str, object]) -> FlightPlan:
    """values: имя dataref -> значение (строки уже декодированы из base64)."""
    fp = FlightPlan()
    for name, val in sorted(values.items()):
        tail = name.split("/")[-1]
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
    legs = values.get("laminar/B738/fms/legs")
    if isinstance(legs, str) and legs.strip():
        fp.waypoints = legs_to_waypoints(legs, values)
        if fp.waypoints:
            fp.sources["waypoints"] = f"{SRC} legs (формат не проверен)"
    return fp.finalize()


def legs_to_waypoints(legs: str, values: Dict[str, object]) -> List[Waypoint]:
    """ПРЕДПОЛОЖЕНИЕ о формате: идентификаторы точек, разделённые пробелами.
    Если есть массивы legs_lat/legs_lon той же длины — добавляем координаты."""
    ids = re.findall(r"[A-Z0-9]{2,7}", legs.upper())
    n = values.get("laminar/B738/fms/num_of_wpts")
    try:
        n = int(n[0] if isinstance(n, list) else n)
    except (TypeError, ValueError):
        n = 0
    if 0 < n < len(ids):
        ids = ids[:n]
    lats = values.get("laminar/B738/fms/legs_lat")
    lons = values.get("laminar/B738/fms/legs_lon")
    out = []
    for i, ident in enumerate(ids):
        w = Waypoint(ident)
        if isinstance(lats, list) and isinstance(lons, list) and len(lats) > i and len(lons) > i:
            try:
                la, lo = float(lats[i]), float(lons[i])
                if abs(la) > 0.01 or abs(lo) > 0.01:
                    w.lat, w.lon = la, lo
            except (TypeError, ValueError):
                pass
        out.append(w)
    return out
