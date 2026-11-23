"""Подмешать кэш X-Plane в учебное воздушное пространство.

Позывной органа, который уже описан в ``data/airports.yaml``, не меняется.
Меняется частота, если она есть в выигравшем ``apt.dat``. Вышка, руление,
деливери и подход из ``atc.dat`` важнее ``apt.dat`` — так делает сам X-Plane
для вышки. Нет частоты в данных — остаётся yaml.

Секторы РЦ из ``atc.dat`` (приоритет 0) и CTR/FIR из OpenAir (приоритет 1)
добавляются к секторам yaml (приоритет 2). TopLevel из ``atc_regions.dat``
остаётся запасным (приоритет 3) и не перебивает ни yaml, ни настоящий центр.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from ..airspace import Airport, Airspace, Runway, Unit
from .cache import NavCache
from .names import unit_callsign

log = logging.getLogger("ru_atc.navdata")

# apt.dat → тип органа в программе. ATIS и unicom в эфир разрешений не входят.
KIND_UNIT = {
    "delivery": "delivery",
    "ground": "ground",
    "tower": "tower",
    "approach": "approach",
    "departure": "departure",
}

HOME = ("UUEE", "UUDD", "UUWW", "ULLI")
_RWY = re.compile(r"0?(\d{1,2})([LRC])?", re.I)


def norm_rwy(value: str) -> str:
    match = _RWY.fullmatch(str(value or "").upper())
    if not match:
        return str(value or "").upper()
    return f"{int(match.group(1)):02d}{match.group(2) or ''}"


def _set_freq(airport: Airport, kind: str, mhz: float, source: str, notes: List[str],
              quiet: bool) -> None:
    unit_type = KIND_UNIT.get(kind)
    if not unit_type:
        return
    existing = airport.units.get(unit_type)
    if existing:
        if abs(existing.freq - mhz) < 0.0005:
            existing.source = source
            return
        old = existing.freq
        existing.freq = mhz
        existing.source = source
        if not quiet:
            notes.append(f"{airport.icao} {existing.callsign}: {old:.3f} → {mhz:.3f} ({source})")
        return
    callsign = unit_callsign(airport.name, unit_type)
    airport.units[unit_type] = Unit(unit_type, callsign, mhz, airport=airport.icao, source=source)
    if not quiet:
        notes.append(f"{airport.icao}: добавлен {callsign} {mhz:.3f} ({source})")


def update_airport(airport: Airport, cache: NavCache, quiet: bool = False) -> List[str]:
    notes: List[str] = []
    comms = cache.comms(airport.icao)
    atis = comms.get("atis")
    if atis:
        airport.atis_mhz = float(atis[0])
        if airport.icao in HOME and not quiet:
            notes.append(f"{airport.icao} АТИС {atis[0]:.3f} ({atis[2] or 'apt.dat'})")
    for kind, (mhz, _name, source) in comms.items():
        if kind == "atis":
            continue
        _set_freq(airport, kind, mhz, source or "apt.dat", notes, quiet)
    for role, kind in (("twr", "tower"), ("del", "delivery"), ("gnd", "ground")):
        override = cache.role_override(airport.icao, role, kind)
        if override:
            mhz, source = override
            apt = comms.get(kind)
            if apt and abs(apt[0] - mhz) >= 0.0005 and not quiet:
                notes.append(f"{airport.icao} {kind}: apt.dat {apt[0]:.3f}, atc.dat {mhz:.3f} — в эфире atc.dat")
            _set_freq(airport, kind, mhz, source, notes, quiet=True)
    tracon = cache.tracon_override(airport.icao, airport.lat, airport.lon)
    if tracon:
        _set_freq(airport, "approach", tracon[0], tracon[1], notes, quiet)
    for runway in list(airport.runways):
        ils = cache.localizer_mhz(airport.icao, runway.id)
        if ils:
            runway.ils = ils
    known = {norm_rwy(runway.id) for runway in airport.runways}
    for row in cache.runways(airport.icao):
        ident = norm_rwy(row["ident"])
        if ident in known:
            continue
        airport.runways.append(Runway(ident, float(row["heading_true"] or 0),
                                       cache.localizer_mhz(airport.icao, ident)))
        known.add(ident)
    return notes


def apply_navdata(airspace: Airspace, cache: NavCache) -> List[str]:
    """Частоты и секторы. Возвращает короткие строки для окна и журнала."""
    notes: List[str] = []
    changed = 0
    for airport in airspace.airports.values():
        airport_notes = update_airport(airport, cache, quiet=airport.icao not in HOME)
        changed += len(airport_notes)
        if airport.icao in HOME:
            notes.extend(airport_notes[:6])
    if changed and len(notes) < changed:
        notes.append(f"Частоты обновлены у органов: {changed} (в окне — основные аэродромы).")
    airspace.sectors = [sector for sector in airspace.sectors if sector.source == "yaml"]
    data_sectors = cache.sectors()
    airspace.sectors.extend(data_sectors)
    centers = sum(1 for sector in data_sectors if sector.priority == 0)
    toplevel = sum(1 for sector in data_sectors if sector.priority == 3)
    if centers:
        notes.append(f"Центров в atc.dat: {centers}. TopLevel (запасной слой, не для эфира, "
                     f"пока есть другой сектор): {toplevel}.")
    else:
        notes.append("В atc.dat нет центра с полигоном и частотой. "
                     "Секторы РЦ остаются из data/airspace.yaml — это заглушки, не AIP.")
    for icao in HOME:
        airport = airspace.airports.get(icao)
        if not airport:
            continue
        high = airspace.sector_at(airport.lat, airport.lon, 30000)
        low = airspace.sector_at(airport.lat, airport.lon, 5000)
        notes.append(_sector_line(icao, high, "FL300"))
        if low and high and (low.facility_id != high.facility_id or abs(low.freq - high.freq) > 0.001):
            notes.append(_sector_line(icao, low, "5000 ft"))
    fallback = []
    for icao, airport in airspace.airports.items():
        sector = airspace.sector_at(airport.lat, airport.lon, 30000)
        if sector is not None and sector.source == "yaml":
            fallback.append(icao)
    if fallback:
        notes.append("Без своего центра в данных X-Plane, остаётся data/airspace.yaml: " + ", ".join(fallback))
    log.info("Навигация X-Plane применена:\n%s", "\n".join(notes))
    return notes


def _sector_line(icao: str, sector, level: str) -> str:
    if sector is None:
        return f"{icao} на {level}: сектор не найден"
    extras = ""
    if sector.extra_freqs:
        extras = " (ещё частоты " + ", ".join(f"{mhz:.3f}" for mhz in sector.extra_freqs) + \
                 " — X-Plane не делит их по секторам, в эфире первая)"
    origin = {
        "yaml": "data/airspace.yaml (в данных X-Plane свой центр эту точку не накрыл)",
        "atc.dat": "atc.dat",
        "atc_regions.dat": "atc_regions.dat (TopLevel)",
        "airspace.txt": "airspace.txt",
    }.get(sector.source, sector.source)
    return (f"{icao} на {level}: {sector.callsign} {sector.freq:.3f} — {origin}{extras}")


def airport_from_cache(cache: NavCache, icao: str) -> Optional[Airport]:
    """Аэродром, которого нет в yaml, но он есть в apt.dat."""
    row = cache.airport(icao)
    if row is None or row["lat"] is None or row["lon"] is None:
        return None
    from .names import airport_display_name
    name = airport_display_name(row["name"] or icao)
    runways = []
    for item in cache.runways(icao):
        ident = norm_rwy(item["ident"])
        runways.append(Runway(ident, float(item["heading_true"] or 0),
                              cache.localizer_mhz(icao, ident)))
    if not runways:
        return None
    airport = Airport(
        icao=icao.upper(), name=name, name_gen=name, lat=float(row["lat"]), lon=float(row["lon"]),
        elevation_ft=float(row["elev_ft"] or 0),
        transition_altitude_ft=int(row["transition_alt_ft"] or cache.transition_alt(icao) or 10000),
        transition_levels=[{"qnh_min": 1012, "fl": 110}, {"qnh_min": 977, "fl": 120}, {"qnh_min": 0, "fl": 130}],
        squawk_range=("2000", "2077"),
        initial_climb={"alt_ft": 5000},
        runways=runways,
        units={},
        preferred_departure=[runways[0].id],
        preferred_arrival=[runways[0].id],
    )
    update_airport(airport, cache, quiet=True)
    return airport
