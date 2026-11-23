"""Разбор файлов X-Plane, кэш, коридор UUEE→ULLI и выбор сектора."""
import os
from pathlib import Path

import pytest

from ru_atc.airspace import Airspace, Sector, pick_sector
from ru_atc.controller import Controller
from ru_atc.navdata.cache import ensure_cache
from ru_atc.navdata.overlay import apply_navdata
from ru_atc.navdata.parse_apt import parse_apt_text
from ru_atc.navdata.parse_atc import parse_atc_text, parse_openair_text
from ru_atc.navdata.parse_cifp import parse_cifp_text
from ru_atc.navdata.parse_nav import parse_awy_text, parse_fix_text, parse_nav_text
from ru_atc.navdata.provider import NavigraphProvider, make_provider
from ru_atc.navdata.sources import collect_sources
from ru_atc.xplane_install import (
    classify_root,
    decode_text_bytes,
    fms_configured_path,
    is_xplane_root,
    nav_configured_path,
    read_install_paths,
)
from tests.conftest import make_ctl

NAV_HEADER = "1200 Version - data cycle 2413, build 20241123, metadata NavXP1200."
FIX_HEADER = "1200 Version - data cycle 2413, build 20241123, metadata FixXP1200."
AWY_HEADER = "1100 Version - data cycle 2413, build 20241123, metadata AwyXP1100."


def cifp_line(airport, proc, kind, transition, seq, fix, path="TF", route_type="1"):
    line = [" "] * 132
    sub = {"sid": "D", "star": "E", "approach": "F"}[kind]
    line[0] = "S"
    line[4] = "P"
    line[5] = sub

    def put(start, text):
        for offset, char in enumerate(text):
            line[start + offset] = char

    put(6, f"{airport:<4}"[:4])
    put(10, "UU")
    put(13, f"{proc:<6}"[:6])
    line[19] = route_type
    put(20, f"{transition:<5}"[:5])
    put(26, f"{seq:03d}")
    put(29, f"{fix:<5}"[:5])
    put(47, path)
    return "".join(line)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_mini_xplane(root: Path) -> None:
    _write(root / "X-Plane.exe", "")
    _write(root / "Resources" / "default data" / "earth_nav.dat", f"""I
{NAV_HEADER}

 3  55.97000000  37.50000000  600  11370  130  10.000  SVO   ENRT UU SHEREMETYEVO VOR
 4  55.96000000  37.43000000  630  11030   25  244.000 ISVO  UUEE UU 24C ILS-cat-I
99
""")
    _write(root / "Resources" / "default data" / "earth_fix.dat", f"""I
{FIX_HEADER}

 57.90000000   34.00000000  KUSIP ENRT UU KUSIP
 58.80000000   32.00000000  SPFIX ENRT UU SPFIX
 40.00000000   50.00000000  FARAW ENRT UU FARAW
99
""")
    _write(root / "Resources" / "default data" / "earth_awy.dat", f"""I
{AWY_HEADER}

KUSIP UU 11 SPFIX UU 11 N 2 180 450 T173
99
""")
    _write(root / "Resources" / "default data" / "CIFP" / "UUEE.dat",
           cifp_line("UUEE", "TOKN3H", "sid", "RW24C", 10, "KUSIP") + "\n")
    _write(root / "Resources" / "default data" / "CIFP" / "ULLI.dat",
           cifp_line("ULLI", "BEMA2E", "star", "RIMET", 10, "BEMAN", route_type="3") + "\n")
    _write(root / "Resources" / "default data" / "airspaces" / "airspace.txt", """
AC CTR
AN TEST CTR
AF 133.000
AG Тест-Контроль
AL GND
AH FL200
DP 47:00:00 N 036:00:00 E
DP 47:00:00 N 038:00:00 E
DP 49:00:00 N 038:00:00 E
DP 49:00:00 N 036:00:00 E

AC D
AN NOT A CENTER
AF 121.500
AL GND
AH 3000 MSL
DP 10:00:00 N 010:00:00 E
DP 10:00:00 N 012:00:00 E
DP 12:00:00 N 012:00:00 E
DP 12:00:00 N 010:00:00 E
""")
    _write(root / "Resources" / "default scenery" / "1200 atc data" / "Earth nav data" / "atc.dat", """A
1000
ATCFILE

CONTROLLER
NAME MOSCOW
FACILITY_ID UUWV-LO
ROLE ctr
FREQ 12500
AIRSPACE_POLYGON_BEGIN 0 15000
POINT 54.000000 35.000000
POINT 54.000000 40.500000
POINT 57.200000 40.500000
POINT 57.200000 35.000000
AIRSPACE_POLYGON_END
CONTROLLER_END

CONTROLLER
NAME MOSCOW
FACILITY_ID UUWV-HI
ROLE ctr
FREQ 12650
AIRSPACE_POLYGON_BEGIN 15000 66000
POINT 54.000000 35.000000
POINT 54.000000 40.500000
POINT 57.200000 40.500000
POINT 57.200000 35.000000
AIRSPACE_POLYGON_END
CONTROLLER_END

CONTROLLER
NAME SAINT PETERSBURG
FACILITY_ID ULLL
ROLE ctr
FREQ 13410
CHAN 134105
AIRSPACE_POLYGON_BEGIN 0 66000
POINT 58.500000 28.000000
POINT 58.500000 34.000000
POINT 61.000000 34.000000
POINT 61.000000 28.000000
AIRSPACE_POLYGON_END
CONTROLLER_END

CONTROLLER
NAME SHEREMETYEVO
FACILITY_ID UUEE
ROLE twr
ICAO UUEE
FREQ 13190
CONTROLLER_END

CONTROLLER
NAME SHEREMETYEVO APP
FACILITY_ID UUEE-APP
ROLE tracon
ICAO UUEE
FREQ 11950
AIRSPACE_POLYGON_BEGIN 0 18000
POINT 55.500000 36.800000
POINT 55.500000 38.200000
POINT 56.400000 38.200000
POINT 56.400000 36.800000
AIRSPACE_POLYGON_END
CONTROLLER_END
""")
    _write(root / "Resources" / "default scenery" / "1200 atc data" / "Earth nav data" / "atc_regions.dat", """A
1000
ATCFILE

CONTROLLER
NAME TopLevel
FACILITY_ID ZZZZ
ROLE ctr
SPOKEN_NAME Generic
FREQ 13595
AIRSPACE_POLYGON_BEGIN 0 99999
POINT -10.000000 -10.000000
POINT -10.000000 60.000000
POINT 70.000000 60.000000
POINT 70.000000 -10.000000
AIRSPACE_POLYGON_END
CONTROLLER_END
""")
    _write(root / "Global Scenery" / "Global Airports" / "Earth nav data" / "apt.dat", """I
1200 Version - data cycle 2413, build 20241123, metadata AptXP1200.

1 630 0 0 UUEE Sheremetyevo
1302 icao_id UUEE
100 60.00 2 0 0.25 1 2 1 06C 55.99000000 37.40000000 0.00 0.00 3 0 1 1 24C 55.96000000 37.43000000 0.00 0.00 3 0 1 1
1052 120050 DEL
1053 121800 GND
1054 118100 TWR
1055 122700 APP
1056 126000 DEP

1 79 0 0 ULLI Pulkovo
1302 icao_id ULLI
100 60.00 2 0 0.25 1 2 1 10L 59.80000000 30.20000000 0.00 0.00 3 0 1 1 28R 59.80000000 30.32000000 0.00 0.00 3 0 1 1
1054 118700 TWR
99
""")
    _write(root / "Custom Scenery" / "Override UUEE" / "Earth nav data" / "apt.dat", """I
1200 Version - data cycle 2413, build 20241123, metadata AptXP1200.

1 630 0 0 UUEE Sheremetyevo
1302 icao_id UUEE
100 60.00 2 0 0.25 1 2 1 06C 55.99000000 37.40000000 0.00 0.00 3 0 1 1 24C 55.96000000 37.43000000 0.00 0.00 3 0 1 1
1052 120900 DEL
1054 131500 TWR
1056 125125 DEP
99
""")
    _write(root / "Custom Scenery" / "Disabled Pack" / "Earth nav data" / "apt.dat", """I
1200 Version - data cycle 2413, build 20241123, metadata AptXP1200.

1 630 0 0 UUEE Sheremetyevo
1302 icao_id UUEE
1054 119000 TWR
99
""")
    _write(root / "Custom Scenery" / "scenery_packs.ini", """I
1000 Version
SCENERY_PACK Custom Scenery/Override UUEE/
SCENERY_PACK_DISABLED Custom Scenery/Disabled Pack/
SCENERY_PACK Global Scenery/Global Airports/
""")


def test_nav_fix_awy_and_localizer_bearing():
    nav = parse_nav_text("""
 2  55.10000000  37.10000000  0  375  25  0.000  SW   ENRT UU SHEREMETYEVO NDB
 4  47.428408333 -122.308063889 425 11030 25 59220.343 ISNQ KSEA K1 16L ILS-cat-III
99
""")
    ndb = next(row for row in nav if row.code == 2)
    loc = next(row for row in nav if row.code == 4)
    assert ndb.freq_khz == 375 and ndb.freq_mhz is None and ndb.ident == "SW"
    assert loc.runway == "16L" and loc.freq_mhz == pytest.approx(110.30)
    assert loc.bearing_true == pytest.approx(180.343, abs=0.01)
    fixes = parse_fix_text(" 55.10000000  37.20000000  ABAGO ENRT UU ABAGO\n")
    assert fixes[0].airport == "ENRT" and fixes[0].region == "UU"
    awy = parse_awy_text("ABCDE K1 11 ABC K1 3 N 2 180 450 J13-J14\n")
    assert awy[0].names == ["J13", "J14"] and awy[0].direction == "N"
    assert awy[0].level == "high" and awy[0].base_fl == 180 and awy[0].top_fl == 450


def test_apt_frequencies_runway_and_legacy_ignored_when_833_present():
    airports = parse_apt_text("""
1 630 0 0 UUEE Sheremetyevo
1302 icao_id UUEE
100 60.00 2 0 0.25 1 2 1 06C 55.99000000 37.40000000 0 0 3 0 1 1 24C 55.96000000 37.43000000 0 0 3 0 1 1
54 11870 TWR OLD
1054 131500 TWR NEW
1052 120900 DEL
""")
    apt = airports[0]
    assert apt.icao == "UUEE"
    kinds = {item.kind: item.mhz for item in apt.comms}
    assert kinds["tower"] == pytest.approx(131.5)
    assert "delivery" in kinds and abs(kinds["delivery"] - 120.9) < 1e-6
    assert len(apt.runways) == 2
    assert {rwy.ident for rwy in apt.runways} == {"06C", "24C"}


def test_atc_and_openair_parse():
    controllers = parse_atc_text("""
CONTROLLER
NAME MOSCOW
FACILITY_ID UUWV
ROLE ctr
FREQ 12650
CHAN 126505
AIRSPACE_POLYGON_BEGIN 0 60000
POINT 54.0 35.0
POINT 54.0 40.0
POINT 57.0 40.0
AIRSPACE_POLYGON_END
CONTROLLER_END
""")
    assert controllers[0].freqs == [126.5, 126.505]
    assert len(controllers[0].polygons[0].points) == 3
    zones = parse_openair_text("AC CTR\nAF 133.0\nAY CTR\nDP 47:30:00 N 037:00:00 E\nDP 48:00:00 N 037:00:00 E\nDP 48:00:00 N 038:00:00 E\n")
    assert zones[0].is_center()
    assert zones[0].polygon[0][0] == pytest.approx(47.5)


def test_cifp_procedure_columns():
    legs = parse_cifp_text(cifp_line("UUEE", "TOKN3H", "sid", "RW24C", 10, "KUSIP") + "\nSHORT\n")
    assert len(legs) == 1
    leg = legs[0]
    assert (leg.airport, leg.kind, leg.ident, leg.runway, leg.fix, leg.path_term) == (
        "UUEE", "sid", "TOKN3H", "24C", "KUSIP", "TF")


def test_install_list_utf16_and_root_markers(tmp_path):
    listing = tmp_path / "x-plane_install_12.txt"
    listing.write_bytes("D:\\X-Plane 12\n".encode("utf-16"))
    assert "X-Plane 12" in decode_text_bytes(listing.read_bytes())
    paths = read_install_paths(listing)
    assert len(paths) == 1 and "X-Plane 12" in str(paths[0])
    root = tmp_path / "XP"
    (root / "Resources" / "default data").mkdir(parents=True)
    (root / "Resources" / "default data" / "earth_nav.dat").write_text("I\n", encoding="utf-8")
    assert is_xplane_root(root)
    assert "earth_nav.dat" in classify_root(root)
    assert "Output/FMS plans" in classify_root(root)


def test_configured_path_falls_back_between_keys():
    cfg = {"navdata": {"xplane_path": ""}, "flight_plan_import": {"xplane_path": "D:/X-Plane 12"}}
    assert nav_configured_path(cfg) == "D:/X-Plane 12"
    assert fms_configured_path(cfg) == "D:/X-Plane 12"
    cfg["navdata"]["xplane_path"] = "E:/X-Plane 12"
    assert nav_configured_path(cfg) == "E:/X-Plane 12"
    assert fms_configured_path(cfg) == "D:/X-Plane 12"


def test_navigraph_is_a_stub():
    provider = make_provider({"navdata": {"provider": "navigraph"}})
    assert isinstance(provider, NavigraphProvider)
    assert provider.available() is False
    assert "заглушка" in provider.explain()


def test_custom_data_must_be_complete_and_same_cycle(tmp_path):
    write_mini_xplane(tmp_path)
    partial = tmp_path / "Custom Data"
    partial.mkdir()
    (partial / "earth_nav.dat").write_text(f"I\n{NAV_HEADER}\n99\n", encoding="utf-8")
    notes = "\n".join(collect_sources(tmp_path).notes)
    assert "неполный" in notes
    for name, header in (("earth_fix.dat", FIX_HEADER), ("earth_awy.dat", AWY_HEADER.replace("2413", "2412"))):
        text = f"I\n{header}\n99\n" if "FIX" in header or name.startswith("earth_f") else f"I\n{header}\n99\n"
        (partial / name).write_text(f"I\n{header}\n99\n", encoding="utf-8")
    (partial / "earth_nav.dat").write_text(f"I\n{NAV_HEADER}\n99\n", encoding="utf-8")
    (partial / "earth_fix.dat").write_text(f"I\n{FIX_HEADER}\n99\n", encoding="utf-8")
    notes = "\n".join(collect_sources(tmp_path).notes)
    assert "разные циклы" in notes


def test_yaml_sector_order_and_altitude():
    poly = [[0, 0], [0, 10], [10, 10], [10, 0]]
    first = Sector("A", "первый", 1, poly, priority=2, source="yaml")
    second = Sector("B", "второй", 2, poly, priority=2, source="yaml")
    assert pick_sector([first, second], 5, 5).id == "A"
    data = Sector("C", "данные", 3, poly, priority=0, source="atc.dat")
    assert pick_sector([first, data], 5, 5).id == "C"
    low = Sector("L", "низ", 125.0, poly, floor_ft=0, ceiling_ft=15000, priority=0)
    high = Sector("H", "верх", 126.5, poly, floor_ft=15000, ceiling_ft=66000, priority=0)
    assert pick_sector([low, high], 5, 5, 5000).id == "L"
    assert pick_sector([low, high], 5, 5, 30000).id == "H"


def test_cache_corridor_sectors_and_invalidation(tmp_path, cfg):
    write_mini_xplane(tmp_path)
    cache_file = tmp_path / "cache" / "nav.sqlite"
    progress = []
    cache, rebuilt, _sources = ensure_cache(tmp_path, cache_file, progress=lambda m, f: progress.append((m, f)))
    assert rebuilt and progress[-1][1] == 1.0
    again, rebuilt2, _ = ensure_cache(tmp_path, cache_file)
    assert rebuilt2 is False
    again.close()

    uuee = (55.9728, 37.4146)
    ulli = (59.8003, 30.2625)
    low = cache.select_sector(*uuee, 5000)
    high = cache.select_sector(*uuee, 30000)
    spb = cache.select_sector(*ulli, 30000)
    assert low is not None and high is not None and spb is not None
    assert low.callsign == "Москва-Контроль" and low.freq == pytest.approx(125.0)
    assert high.callsign == "Москва-Контроль" and high.freq == pytest.approx(126.5)
    assert high.source == "atc.dat"
    assert spb.callsign == "Санкт-Петербург Контроль" and spb.freq == pytest.approx(134.1)
    assert spb.extra_freqs[0] == pytest.approx(134.105)
    # TopLevel накрывает всё, но не побеждает настоящий центр.
    assert cache.select_sector(10, 10, 10000).source == "atc_regions.dat"
    assert cache.select_sector(48, 37, 5000).callsign == "Тест-Контроль"
    assert cache.select_sector(11, 11, 1000).source == "atc_regions.dat"

    near = cache.corridor([uuee, (57.9, 34.0), ulli], 80, ["UUEE", "ULLI"])
    fixes = {item.ident for item in near.fixes}
    assert "KUSIP" in fixes and "SPFIX" in fixes and "FARAW" not in fixes
    assert any(item.ident == "SVO" and item.freq_mhz == pytest.approx(113.7) for item in near.navaids)
    assert any(item.name == "T173" for item in near.airways)
    procs = {(item.airport, item.ident) for item in near.procedures}
    assert ("UUEE", "TOKN3H") in procs and ("ULLI", "BEMA2E") in procs
    cache.close()

    nav_path = tmp_path / "Resources" / "default data" / "earth_nav.dat"
    stamp = nav_path.stat().st_mtime
    text = nav_path.read_text(encoding="utf-8").replace("2413", "2414")
    nav_path.write_text(text, encoding="utf-8")
    os.utime(nav_path, (stamp, stamp))
    rebuilt_cache, rebuilt3, _ = ensure_cache(tmp_path, cache_file)
    assert rebuilt3 is True
    rebuilt_cache.close()


def test_overlay_replaces_frequencies_and_keeps_russian_callsigns(tmp_path, cfg):
    write_mini_xplane(tmp_path)
    cache, _, _ = ensure_cache(tmp_path, tmp_path / "nav.sqlite")
    airspace = Airspace.load(cfg["airports_file"], cfg["airspace_file"])
    notes = apply_navdata(airspace, cache)
    joined = "\n".join(notes)
    uuee = airspace.airports["UUEE"]
    assert uuee.unit("tower").callsign == "Шереметьево-Старт"
    assert uuee.unit("tower").freq == pytest.approx(131.9)
    assert uuee.unit("delivery").freq == pytest.approx(120.9)
    assert uuee.unit("ground").freq == pytest.approx(121.8)  # в выигравшем apt.dat земли нет
    assert uuee.unit("approach").callsign == "Шереметьево-Подход"
    assert uuee.unit("approach").freq == pytest.approx(119.5)
    assert uuee.unit("departure").callsign == "Шереметьево-Выход"
    assert uuee.unit("departure").freq == pytest.approx(125.125)
    assert uuee.runway("24C").ils == pytest.approx(110.3)
    ulli = airspace.airports["ULLI"]
    assert ulli.unit("tower").callsign == "Пулково-Вышка"
    assert ulli.unit("tower").freq == pytest.approx(118.7)
    voronezh = airspace.airports["UUOO"]
    south = airspace.sector_at(voronezh.lat, voronezh.lon, 30000)
    assert south.source == "yaml" and south.freq == pytest.approx(128.3)
    assert "UUOO" in joined and "data/airspace.yaml" in joined
    assert "atc.dat" in joined
    ctl = make_ctl(cfg, airspace)
    assert ctl.dep_terminal_unit().callsign == "Шереметьево-Выход"
    assert ctl.sector_unit(_state(uuee, 30000)).freq == pytest.approx(126.5)
    assert ctl.sector_unit(_state(ulli, 30000)).callsign == "Санкт-Петербург Контроль"
    cache.close()


def _state(airport, alt):
    from ru_atc.model import SimState
    return SimState(lat=airport.lat, lon=airport.lon, alt_msl_ft=alt, connected=True)


def test_controller_uses_cache_for_unknown_airport(tmp_path, cfg):
    write_mini_xplane(tmp_path)
    cache, _, _ = ensure_cache(tmp_path, tmp_path / "nav.sqlite")
    airspace = Airspace.load(cfg["airports_file"], cfg["airspace_file"])
    ctl = Controller(cfg, airspace)
    ctl.nav = cache
    built = ctl._make_airport("ULLI", None, "")
    assert built is None or built.icao == "ULLI"
    # ULLI уже в yaml, поэтому проверяем аэродром только из apt.dat через кэш напрямую.
    from ru_atc.navdata.overlay import airport_from_cache
    fresh = airport_from_cache(cache, "ULLI")
    assert fresh is not None and fresh.unit("tower").freq == pytest.approx(118.7)
    assert fresh.name == "Пулково"
    cache.close()
