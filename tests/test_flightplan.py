"""Импорт плана из FMC Zibo: разбор CDU, .fms, datarefs, слияние источников, интеграция с контроллером."""
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fmc_fixtures import (ARR, DEP, FMS_1100, FMS_UNKNOWN_DEST, FMS_V3, OTHER, PERF, RTE1, RTE2, RTE3, b64, ln,
                          screen_values)
from ru_atc.flightplan.cdu import CduCollector, Screen, overlay, page_kind, split_lr
from ru_atc.flightplan.fms_file import fms_dir, latest_fms, parse_fms
from ru_atc.flightplan.model import FlightPlan, approach_runway, norm_rwy, parse_cruise_fl
from ru_atc.flightplan.provider import FlightPlanProvider
from ru_atc.flightplan import zibo_refs
from ru_atc.events import Transmission
from ru_atc.model import SimState
from ru_atc.phases import Phase

from conftest import make_ctl


# ---------------------------------------------------------------- модель
def test_normalizers():
    assert norm_rwy("RW24C") == "24C" and norm_rwy("06") == "06" and norm_rwy("RWY 28R") == "28R"
    assert norm_rwy("-----") == ""
    assert parse_cruise_fl("FL330") == 330 and parse_cruise_fl("35000") == 350
    assert parse_cruise_fl("--- /FL350") == 350 and parse_cruise_fl(37000) == 370 and parse_cruise_fl("") is None
    assert approach_runway("ILS28R") == "28R" and approach_runway("I06C") == "06C" and approach_runway("R35-Y") == "35"


# ---------------------------------------------------------------- CDU
def test_overlay_and_split():
    assert overlay(["AB    ", "  CD  ", "XXXXXXX"]) == "ABCDXXX"
    assert split_lr(ln("UUEE", "ULLI")) == ("UUEE", "ULLI")
    assert split_lr(ln("", "<SEL> RW24C")) == ("", "<SEL> RW24C")
    assert split_lr(ln(" SIDS     RTE 1", "RUNWAYS")) == ("SIDS", "RUNWAYS")


def test_page_kinds():
    k = lambda v: page_kind(Screen.from_values(v).title)
    assert k(RTE1) == "rte" and k(DEP) == "dep" and k(ARR) == "arr" and k(PERF) == "perf" and k(OTHER) == ""
    assert page_kind("ACT RTE 1 LEGS 1/4") == "legs"


def test_cdu_full_plan():
    c = CduCollector()
    for v in (RTE1, RTE2, RTE3, DEP, ARR, PERF, OTHER):
        c.feed(Screen.from_values(v))
    p = c.plan()
    assert (p.origin, p.dest, p.dep_rwy, p.flight_no) == ("UUEE", "ULLI", "24C", "AFL1234")
    assert (p.sid, p.sid_trans) == ("LAKI1G", "LAKIB")
    assert (p.star, p.star_trans, p.approach, p.app_trans) == ("BEMA2E", "RIMET", "ILS28R", "SOVIN")
    assert p.arr_rwy == "28R" and p.cruise_fl == 350
    assert p.route_idents() == ["LAKIB", "TOPLA", "SOGMA", "BEMAN", "RIMET"]
    assert p.sources["sid"] == "CDU DEP"


def test_cdu_rte_only_guesses_sid_star():
    c = CduCollector()
    for v in (RTE1, RTE2, RTE3):
        c.feed(Screen.from_values(v))
    p = c.plan()
    assert p.sid == "LAKI1G" and p.star == "BEMA2E" and p.sources["sid"] == "CDU RTE(VIA)"


def test_cdu_layers_small_font_and_new_route_resets():
    v = dict(RTE1)
    # номер рейса мелким шрифтом в отдельном слое
    v["laminar/B738/fmc1/Line02_L"] = ln("RW24C", "")
    v["laminar/B738/fmc1/Line02_S"] = ln("", "SDM6001")
    c = CduCollector()
    c.feed(Screen.from_values(v))
    c.feed(Screen.from_values(DEP))
    assert c.plan().flight_no == "SDM6001" and c.plan().sid == "LAKI1G"
    v2 = screen_values(ln("      RTE 1", "1/2"), [(ln(" ORIGIN", "DEST"), ln("UUDD", "ULLI"))])
    c.feed(Screen.from_values(v2))
    p = c.plan()
    assert p.origin == "UUDD" and p.sid == ""      # SID от старого маршрута сброшена


def test_dep_page_for_other_airport_ignored():
    c = CduCollector()
    c.feed(Screen.from_values(RTE1))
    other = screen_values(ln(" UUDD DEPARTURES", "1/1"), [(ln(" SIDS", "RUNWAYS"), ln("XXX1A <SEL>", "<SEL> RW14R"))])
    c.feed(Screen.from_values(other))
    assert c.plan().sid == ""


def test_legs_pages_preferred_for_waypoints():
    c = CduCollector()
    c.feed(Screen.from_values(RTE1))
    legs = screen_values(ln(" ACT RTE 1 LEGS", "1/1"), [
        (ln(" 236°", "3NM"), ln("(1200)", "/ 1200")),
        (ln(" 241°", "18NM"), ln("LAKIB", "250/FL110")),
        (ln("", ""), ln("TOPLA", ".780/FL350")),
        (ln("", ""), ln("RW28R", "146/  250")),
    ])
    c.feed(Screen.from_values(legs))
    p = c.plan()
    assert p.route_idents() == ["LAKIB", "TOPLA", "RW28R"] and p.sources["waypoints"] == "CDU LEGS"


# ---------------------------------------------------------------- .fms
def test_parse_fms_1100():
    p = parse_fms(FMS_1100)
    assert (p.origin, p.dest, p.dep_rwy, p.sid, p.sid_trans) == ("UUEE", "ULLI", "24C", "LAKI1G", "LAKIB")
    assert (p.star, p.star_trans, p.approach, p.arr_rwy) == ("BEMA2E", "RIMET", "I28R", "28R")
    assert p.route_idents() == ["LAKIB", "TOPLA", "SOGMA", "BEMAN"]
    assert p.waypoints[1].via == "R22" and p.waypoints[0].has_pos
    assert p.cruise_fl == 350 and p.dest_pos[:2] == (59.8003, 30.2625)


def test_parse_fms_v3_and_bad():
    p = parse_fms(FMS_V3)
    assert (p.origin, p.dest) == ("UUDD", "UUWW") and p.route_idents() == ["AKERA", "MR"]
    with pytest.raises(ValueError):
        parse_fms("I\n999 Version\n")


def test_latest_fms_selection(tmp_path):
    d = tmp_path / "Output" / "FMS plans"
    d.mkdir(parents=True)
    a, b = d / "UUEEULLI01.fms", d / "UUDDUUWW01.fms"
    a.write_text(FMS_1100)
    b.write_text(FMS_V3)
    now = time.time()
    os.utime(a, (now - 3600, now - 3600))
    os.utime(b, (now - 60, now - 60))
    assert fms_dir(str(tmp_path)) == d
    assert latest_fms(d) == b
    assert latest_fms(d, origin="UUEE", dest="ULLI") == a
    assert latest_fms(d, origin="UUEE", dest="UUWW") is None
    assert latest_fms(d, max_age_h=0.001, now=now) is None


# ---------------------------------------------------------------- datarefs Zibo
def test_zibo_value_heuristics():
    vals = {"laminar/B738/fms/ref_icao": "UUWW", "laminar/B738/fms/dest_icao": "UUEE",
            "laminar/B738/fms/des_icao_alt": "UUDD", "laminar/B738/fms/dest_runway_alt": 600.0,
            "laminar/B738/fms/sid_name": "ABC1A", "laminar/B738/fms/crz_alt": 32000,
            "laminar/B738/fms/legs": "KUPAN RW06  BILGA", "laminar/B738/fms/num_of_wpts": 2,
            "laminar/B738/fms/legs_lat": [55.6, 55.7, 0.0], "laminar/B738/fms/legs_lon": [37.1, 37.2, 0.0]}
    p = zibo_refs.plan_from_values(vals)
    assert (p.origin, p.dest, p.sid, p.cruise_fl) == ("UUWW", "UUEE", "ABC1A", 320)
    assert p.route_idents() == ["KUPAN", "RW06"] and p.waypoints[1].lat == 55.7
    assert zibo_refs.is_interesting("laminar/B738/fms/dest_icao") and not zibo_refs.is_interesting("laminar/B738/fms/vnav_idx")


# ---------------------------------------------------------------- провайдер (без сети)
class FakeRest:
    def __init__(self, values):
        self.values = dict(values)
        self.info = {}
        self.fail = False
        self.reads = 0

    def connect(self):
        if self.fail:
            raise OSError("connection refused")
        return "v2"

    def discover(self, prefixes):
        out = {n: (i, "data" if isinstance(v, str) else "float") for i, (n, v) in enumerate(self.values.items())
               if n.startswith(prefixes)}
        self.info.update(out)
        return out

    def resolve(self, names):
        return {}

    def value(self, name):
        if self.fail:
            raise OSError("gone")
        self.reads += 1
        return self.values.get(name, "")


def provider(cfg, values, xp=""):
    cfg["flight_plan_import"].update(xplane_path=xp)
    got = []
    p = FlightPlanProvider(cfg, rest=FakeRest(values), on_change=got.append)
    return p, got


def test_provider_collects_pages_and_notifies(cfg):
    p, got = provider(cfg, RTE1)
    assert p.poll_once(now=1000.0) and got[-1].origin == "UUEE"
    for i, page in enumerate((RTE2, RTE3, DEP, ARR, PERF), 1):
        p.rest.values.update({k: "" for k in p.rest.values})   # смена страницы: старые строки гаснут
        p.rest.values.update(page)
        p.poll_once(now=1000.0 + i)
    assert got[-1].sid == "LAKI1G" and got[-1].approach == "ILS28R" and got[-1].cruise_fl == 350
    n = len(got)
    assert not p.poll_once(now=1010.0) and len(got) == n          # без изменений — без уведомления


def test_provider_reads_only_title_on_irrelevant_pages(cfg):
    p, _ = provider(cfg, OTHER)
    p.poll_once(now=1.0)
    first = p.rest.reads
    p.poll_once(now=2.0)
    assert p.rest.reads - first <= 7     # только Line00_* (+ datarefs Zibo раз в 5 с)


def test_provider_fms_fallback_and_match(cfg, tmp_path):
    d = tmp_path / "Output" / "FMS plans"
    d.mkdir(parents=True)
    (d / "UUEEULLI01.fms").write_text(FMS_1100)
    # FMC знает только ORIGIN/DEST — остальное и точки с координатами берём из .fms
    vals = screen_values(ln("      RTE 1", "1/2"), [(ln(" ORIGIN", "DEST"), ln("UUEE", "ULLI"))])
    p, got = provider(cfg, vals, xp=str(tmp_path))
    p.poll_once(now=time.time())
    fp = got[-1]
    assert fp.sid == "LAKI1G" and fp.approach == "I28R" and fp.waypoints[0].has_pos
    assert fp.sources["origin"] == "CDU RTE" and fp.sources["sid"].startswith("fms-файл")
    # FMC: другой маршрут — .fms с UUEE->ULLI не используется
    p2, got2 = provider(cfg, screen_values(ln("RTE 1", "1/2"), [(ln(" ORIGIN", "DEST"), ln("UUEE", "UUWW"))]),
                        xp=str(tmp_path))
    p2.poll_once(now=time.time())
    assert got2[-1].sid == "" and not got2[-1].waypoints


def test_provider_reconnects_after_failures(cfg):
    p, _ = provider(cfg, RTE1)
    p.poll_once(now=1.0)
    assert p.connected
    p.rest.fail = True
    for t in (2.0, 3.0, 4.0):
        p.poll_once(now=t)
    assert not p.connected and any("переподключение" in e for e in p.errors)
    p.rest.fail = False
    p.poll_once(now=20.0)
    assert p.connected


def test_provider_no_zibo(cfg):
    p, got = provider(cfg, {"sim/foo": 1.0})
    p.poll_once(now=1.0)
    assert not p.connected and not got and "не найдены" in p.errors[-1]


# ---------------------------------------------------------------- Web API REST (HTTP, base64)
def test_webapi_rest_strings_over_http(cfg):
    from ru_atc.sources.webapi import WebApiRest
    refs = {n: (5000 + i, "data", v) for i, (n, v) in enumerate({**RTE1}.items())}
    refs["laminar/B738/fms/num_of_wpts"] = (6000, "int", 7)
    refs["sim/flightmodel/position/latitude"] = (1, "double", 55.9)
    by_id = {v[0]: v for v in refs.values()}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/capabilities":
                body = {"api": {"versions": ["v1", "v2"]}}
            elif u.path == "/api/v2/datarefs":
                body = {"data": [{"id": i, "name": n, "value_type": t} for n, (i, t, _) in refs.items()]}
            elif u.path.startswith("/api/v2/datarefs/") and u.path.endswith("/value"):
                i, t, v = by_id[int(u.path.split("/")[4])]
                body = {"data": b64(v + "\x00\x00") if t == "data" else v}
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg["sim"].update(source="webapi", host="localhost", webapi_port=srv.server_address[1])
        got = []
        p = FlightPlanProvider(cfg, on_change=got.append)
        assert isinstance(p.rest, WebApiRest) and p.rest.host == "127.0.0.1"
        p.poll_once(now=1.0)
        assert p.connected and "laminar/B738/fms/num_of_wpts" in p.zibo_names
        assert got and got[-1].origin == "UUEE" and got[-1].flight_no == "AFL1234"
        assert p.rest.value("laminar/B738/fms/num_of_wpts") == 7
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- контроллер
def sim_at(ap, unit=None, **kw):
    s = SimState(t=kw.pop("t", 10.0), connected=True, lat=ap.lat, lon=ap.lon, qnh_hpa=1013, wind_dir=60, wind_kt=12)
    s.com1_khz = unit.khz if unit else 0
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def full_plan():
    c = CduCollector()
    for v in (RTE1, RTE2, RTE3, DEP, ARR, PERF):
        c.feed(Screen.from_values(v))
    p = c.plan()
    return p


def test_controller_clearance_uses_fmc_plan(cfg, airspace):
    ctl = make_ctl(cfg, airspace, dep="UUDD", arr="UUWW")      # config говорит другое
    msgs = ctl.apply_plan(full_plan())
    assert ctl.dep.icao == "UUEE" and ctl.arr.icao == "ULLI" and ctl.cruise_fl == 350
    assert ctl.r.callsign == "Аэрофлот 1234" and ctl.dep_rwy.id == "24C" and ctl.arr_rwy.id == "28R"
    s = sim_at(ctl.dep, ctl.dep.unit("delivery"))       # ветер 060 — без FMC выбралась бы 06-я
    ctl.update(s)
    t = [e for e in ctl.on_pilot("прошу разрешение до Пулково", s) if isinstance(e, Transmission)][0]
    assert "ВПП 24 центральная" in t.display or "24C" in t.display or "24 центр" in t.display, t.display
    assert "LAKI1G" in t.display and "LAKIB" in t.display
    assert "лаки один гольф" in t.speech and not any(ch.isdigit() for ch in t.speech)
    assert any("вылета" in m for m in msgs)


def test_controller_arrival_uses_star_and_approach(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    p = full_plan()
    p.approach = "RNV28R"
    ctl.apply_plan(p)
    ctl.tracker.phase = Phase.DESCENT
    app = ctl.arr.unit("approach")
    s = sim_at(ctl.arr, app, lat=ctl.arr.lat + 0.6, alt_ind_ft=9000, on_ground=False)
    t = ctl._arrival_terminal_checkin(s, app)
    assert "BEMA2E" in t.display and "RNAV" in t.display and "28" in t.display
    d = ctl._issue_descent(s, ctl.sector_unit(s) or app)
    assert "прибытие по схеме BEMA2E" in d.display


def test_controller_unknown_airport(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    msgs = ctl.apply_plan(FlightPlan(origin="UUEE", dest="ZZZZ"))
    assert ctl.arr.icao == "ULLI" and any("ZZZZ" in m for m in msgs)
    fp = parse_fms(FMS_UNKNOWN_DEST)       # UUMO нет в airports.yaml, но есть координаты и ВПП
    msgs = ctl.apply_plan(fp)
    assert ctl.arr.icao == "UUMO" and ctl.arr.runways[0].id == "08"
    assert ctl.unit_of(ctl.arr, "tower").callsign == "Москва-Контроль"
    assert ctl.dep_rwy.id == "06R"


def test_controller_no_plan_keeps_config(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    assert ctl.apply_plan(None) == [] and ctl.apply_plan(FlightPlan()) == []
    assert ctl.dep.icao == "UUEE" and ctl.plan is None and ctl.status()["plan"].startswith("нет")


def test_controller_dep_locked_after_takeoff(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    ctl.flags["takeoff"] = True
    ctl.tracker.phase = Phase.CLIMB
    ctl.apply_plan(FlightPlan(origin="UUDD", dest="ULLI", dep_rwy="14R"))
    assert ctl.dep.icao == "UUEE"


def test_route_distance_for_tod(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim_at(ctl.dep, None)
    direct = ctl.dist_to_go_km(s)
    ctl.apply_plan(parse_fms(FMS_1100))
    along = ctl.dist_to_go_km(s)
    assert along >= direct and along < direct * 1.5
