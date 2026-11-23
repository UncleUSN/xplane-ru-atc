"""Запрос фактической погоды у диспетчера."""
from ru_atc.events import Transmission
from ru_atc.phraseology.parser import parse

from conftest import make_ctl
from test_controller import sim


def _said(evs):
    return [e for e in evs if isinstance(e, Transmission)]


def test_weather_intents():
    assert parse("сообщите погоду").intent == "request_weather"
    assert parse("фактическую погоду в Пулково").intent == "request_weather"
    assert parse("погоду на аэродроме назначения").intent == "request_weather"
    assert parse("какая погода на вылете").intent == "request_weather"
    assert parse("добрый день, сообщите фактическую погоду").intent == "request_weather"
    assert parse("прошу разрешение до Пулково").intent == "request_clearance"


def test_named_airport_and_destination(cfg, airspace, tmp_path):
    folder = tmp_path / "Output" / "real weather"
    folder.mkdir(parents=True)
    (folder / "METAR.rwx").write_text(
        "ULLI 231200Z 18003MPS 8000 FEW010 02/M01 Q1005\n", encoding="utf-8")
    cfg["navdata"]["xplane_path"] = str(tmp_path)
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    s.vis_m = 9999
    s.temp_c = 6
    here = _said(ctl.on_pilot("сообщите погоду", s))[0]
    assert "Шереметьево" in here.display and "QNH" in here.display
    assert not any(ch.isdigit() for ch in here.speech)
    there = _said(ctl.on_pilot("фактическую погоду в Пулково", s))[0]
    assert "Пулково" in there.display and "QNH 1005" in there.display
    assert "у самолёта" not in there.display
    assert not any(ch.isdigit() for ch in there.speech)
    dest = _said(ctl.on_pilot("погоду на аэродроме назначения", s))[0]
    assert "Пулково" in dest.display and "1005" in dest.display
    dep = _said(ctl.on_pilot("погоду на вылете", s))[0]
    assert "Шереметьево" in dep.display


def test_far_airport_without_metar_says_so(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    text = _said(ctl.on_pilot("сообщите погоду в Пулково", s))[0].display
    assert "Пулково" in text and "у самолёта" in text
