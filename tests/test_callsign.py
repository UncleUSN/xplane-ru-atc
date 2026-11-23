"""Позывной из первой передачи пилота."""
import pytest

from ru_atc.events import Hint, Transmission
from ru_atc.flightplan.model import FlightPlan
from ru_atc.phraseology.callsign import extract_callsign
from ru_atc.phraseology.parser import parse

from conftest import make_ctl
from test_controller import sim, tx


@pytest.mark.parametrize("text,spoken,number,kind", [
    ("Диспетчер, Сибирь 213, здравствуйте", "Сибирь", "213", "airline"),
    ("сибирь двести тринадцать", "Сибирь", "213", "airline"),
    ("сибирь два один три", "Сибирь", "213", "airline"),
    ("аэрофлот один два три четыре прошу разрешение", "Аэрофлот", "1234", "airline"),
    ("ред вингс 45", "Ред Вингс", "45", "airline"),
    ("редвингс 8", "Ред Вингс", "8", "airline"),
    ("ютейр 452", "ЮТэйр", "452", "airline"),
    ("ютэир рейс 7", "ЮТэйр", "7", "airline"),
    ("норд винд 301", "Нордвинд", "301", "airline"),
    ("смарт авиа 12", "Смартавиа", "12", "airline"),
    ("уральские авиалинии 261", "Уральские", "261", "airline"),
    ("свердловск авиа 15", "Уральские", "15", "airline"),
    ("эс 7 213", "Сибирь", "213", "airline"),
    ("победа 102", "Победа", "102", "airline"),
    ("азимут 33", "Азимут", "33", "airline"),
    ("ра 73123", "RA", "73123", "registration"),
    ("RA-73123", "RA", "73123", "registration"),
    ("эр а 73012 здравствуйте", "RA", "73012", "registration"),
    ("регистрация ра 12345", "RA", "12345", "registration"),
    ("сибирь 0213", "Сибирь", "213", "airline"),
])
def test_extract_airline_and_registration(text, spoken, number, kind):
    hit = parse(text).callsign
    assert hit is not None
    assert hit.spoken == spoken and hit.number == number and hit.kind == kind


def test_callsign_does_not_steal_the_request():
    msg = parse("Диспетчер, Сибирь 213, здравствуйте, прошу разрешение до Пулково")
    assert msg.intent == "request_clearance"
    assert msg.callsign.spoken == "Сибирь" and msg.callsign.number == "213"


def test_bare_callsign_is_check_in():
    msg = parse("диспетчер сибирь 213")
    assert msg.intent == "check_in"
    assert msg.callsign.label == "Сибирь 213"


def test_no_callsign_in_ordinary_phrase():
    assert parse("прошу разрешение до Пулково").callsign is None
    assert parse("подтверждаю, ответчик 7777").callsign is None
    assert extract_callsign("круг 120.675") is None


def test_first_radio_call_replaces_config_and_is_used_afterwards(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    assert ctl.r.callsign == "Аэрофлот 1234"
    s = sim(ctl)
    ev = ctl.on_pilot("Диспетчер, Сибирь 213, здравствуйте", s)
    notes = [e.text for e in ev if isinstance(e, Hint) and e.key == "callsign"]
    assert notes and "Сибирь 213" in notes[0] and "Аэрофлот 1234" in notes[0]
    spoken = [e for e in ev if isinstance(e, Transmission)]
    assert spoken and spoken[0].display.startswith("Сибирь 213")
    assert ctl.status()["callsign"].startswith("Сибирь 213")
    assert "эфир" in ctl.status()["callsign"]
    again = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert again.display.startswith("Сибирь 213")
    assert "Аэрофлот" not in again.display


def test_later_mismatch_does_not_replace_the_first_call(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("Сибирь 213, здравствуйте", s)
    ev = ctl.on_pilot("Победа 10, добрый день", s)
    assert ctl.r.callsign == "Сибирь 213"
    notes = [e.text for e in ev if isinstance(e, Hint) and e.key == "callsign"]
    assert notes and "Победа 10" in notes[0] and "Сибирь 213" in notes[0]
    shown = tx(ev)
    assert shown and shown[0].display.startswith("Сибирь 213")
    # Повтор того же расхождения не плодит новые строки.
    ev2 = ctl.on_pilot("Победа 10", s)
    assert not [e for e in ev2 if isinstance(e, Hint) and e.key == "callsign"]


def test_spoken_callsign_wins_over_fmc(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    first = ctl.apply_plan(FlightPlan(flight_no="SBI501"))
    assert ctl.r.callsign == "Сибирь 501"
    assert any("FMC" in m for m in first)
    s = sim(ctl)
    ctl.on_pilot("диспетчер, сибирь 213, здравствуйте", s)
    assert ctl.r.callsign == "Сибирь 213"
    later = ctl.apply_plan(FlightPlan(flight_no="AFL9999"))
    assert ctl.r.callsign == "Сибирь 213"
    assert any("AFL9999" in m and "Сибирь 213" in m for m in later)
    # Повторный план с тем же конфликтом не добавляет вторую строку.
    assert ctl.apply_plan(FlightPlan(flight_no="PBD10")) == []


def test_same_callsign_as_config_is_marked_from_radio(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ev = ctl.on_pilot("Аэрофлот 1234, прошу разрешение до Пулково", s)
    assert ctl.r.callsign == "Аэрофлот 1234"
    assert any(isinstance(e, Hint) and e.key == "callsign" and "Аэрофлот 1234" in e.text for e in ev)
    assert tx(ev)[0].display.startswith("Аэрофлот 1234")
    assert "эфир" in ctl.status()["callsign"]


def test_custom_airline_in_config(cfg, airspace):
    cfg["airlines"]["ZZZ"] = "Заря"
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("Заря 15, здравствуйте", s)
    assert ctl.r.callsign == "Заря 15"
