"""Приветствия и прощания: генерация, chattiness off и терпимость разбора."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ru_atc.config import DEFAULTS
from ru_atc.phraseology.confirm import is_bare_confirmation
from ru_atc.phraseology.courtesy import (
    PROBS, append_clause, day_part, farewell_options, greeting_options, hour_of,
    insert_greeting, normalize_chattiness, strip_courtesy_text,
)
from ru_atc.phraseology.parser import parse
from ru_atc.phraseology.vocab import build_vocabulary

from conftest import make_ctl
from test_controller import sim, tx


class FixedTalk:
    def __init__(self, roll=0.0, pick=0):
        self.roll = roll
        self.pick = pick
        self.used = []

    def random(self):
        self.used.append(self.roll)
        return self.roll

    def choice(self, seq):
        return seq[self.pick % len(seq)]


class ScriptedTalk:
    def __init__(self, rolls):
        self.rolls = list(rolls)
        self.used = []

    def random(self):
        roll = self.rolls.pop(0) if self.rolls else 0.99
        self.used.append(roll)
        return roll

    def choice(self, seq):
        return seq[0]


def _at(ctl, hour, **kw):
    s = sim(ctl, **kw)
    s.local_time_sec = hour * 3600
    return s


def test_day_part_and_sim_hour():
    assert day_part(5) == day_part(11) == "morning"
    assert day_part(12) == day_part(16) == "day"
    assert day_part(17) == day_part(22) == "evening"
    assert day_part(23) == day_part(0) == day_part(4) == "night"
    assert hour_of(8 * 3600 + 60) == (8, "sim")
    assert hour_of(86400 + 15 * 3600) == (15, "sim")
    moment = datetime(2026, 6, 1, 20, 30, tzinfo=timezone.utc)
    assert hour_of(None, now=moment) == (20, "system")
    assert hour_of(float("nan"), now=moment)[1] == "system"
    assert hour_of(-5, now=moment)[1] == "system"


def test_greeting_follows_local_hour_and_farewell_pool():
    assert greeting_options("morning")[0] == "доброе утро"
    assert greeting_options("day")[0] == "добрый день"
    assert greeting_options("evening")[0] == "добрый вечер"
    assert greeting_options("night") == ("здравствуйте",)
    assert "мягкой посадки" in farewell_options("day", landing=True)
    assert "мягкой посадки" not in farewell_options("morning", landing=False)
    assert "хорошего дня" in farewell_options("day", landing=False)
    assert "хорошего дня" not in farewell_options("morning", landing=False)
    assert "принято, хорошего полёта" in farewell_options("evening", landing=False)


def test_probabilities_and_yaml_off():
    assert PROBS["off"] == {k: 0.0 for k in PROBS["normal"]}
    for name, normal in PROBS["normal"].items():
        assert 0 < normal <= PROBS["high"][name] < 1
    assert normalize_chattiness("high") == "high"
    assert normalize_chattiness(" Off ") == "off"
    assert normalize_chattiness("что-то") == "normal"
    # PyYAML 1.1 читает голое off как false.
    assert yaml.safe_load("chattiness: off\n")["chattiness"] is False
    assert normalize_chattiness(False) == "off"
    assert normalize_chattiness(True) == "normal"
    assert DEFAULTS["atc"]["chattiness"] == "normal"
    example_path = Path(__file__).resolve().parents[1] / "config.example.yaml"
    example = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    assert example["atc"]["chattiness"] == "normal"


def test_insert_keeps_clearance_tags():
    src = "{cs}, Шереметьево-Деливери, разрешено до Пулково, набор {fl:240}, ответчик {sq:1501}"
    out = insert_greeting(src, "доброе утро")
    assert out.startswith("{cs}, доброе утро,")
    assert "{fl:240}" in out and "{sq:1501}" in out
    assert out.index("доброе утро") < out.index("разрешено") < out.index("{fl:240}") < out.index("{sq:1501}")
    bye = append_clause(out, "счастливого полёта")
    assert bye.endswith("счастливого полёта")
    assert "{sq:1501}" in bye and bye.index("{sq:1501}") < bye.index("счастливого")


def test_off_matches_previous_phraseology(cfg, airspace):
    def issue(mode):
        ctl = make_ctl(cfg, airspace, chattiness=mode)
        ctl.talk = FixedTalk(0.0)
        s = _at(ctl, 9)
        issued = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
        closed = tx(ctl.on_pilot("подтверждаю", s))[0]
        return ctl.squawk, issued, closed

    sq_off, off_clr, off_bye = issue("off")
    sq_on, on_clr, on_bye = issue("high")
    assert sq_off == sq_on
    assert "добр" not in off_clr.display and "счастл" not in off_bye.display
    assert "спасибо" not in off_clr.display and "до свидания" not in off_bye.display
    assert strip_courtesy_text(on_clr.display) == off_clr.display
    assert strip_courtesy_text(on_bye.display) == off_bye.display
    assert "доброе утро" in on_clr.display
    assert on_clr.display.index("Аэрофлот") < on_clr.display.index("доброе утро") < on_clr.display.index("разрешено")
    assert "разрешено до Пулково" in on_clr.display and "ответчик" in on_clr.display and "6000" in on_clr.display
    assert "до свидания" in on_bye.display
    assert on_bye.display.index("Руление") < on_bye.display.index("до свидания")
    assert "правильно" in on_bye.display
    assert not any(ch.isdigit() for ch in on_clr.speech + on_bye.speech)


def test_time_of_day_variants_and_system_fallback(cfg, airspace, monkeypatch):
    def greet(hour):
        ctl = make_ctl(cfg, airspace, chattiness="high")
        ctl.talk = FixedTalk(0.0)
        s = _at(ctl, hour)
        return tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0].display

    assert "добрый день" in greet(14)
    assert "добрый вечер" in greet(19)
    night = greet(2)
    assert "здравствуйте" in night and "доброе утро" not in night and "добрый день" not in night

    monkeypatch.setattr("ru_atc.controller.hour_of", lambda sec, now=None: (20, "system"))
    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = FixedTalk(0.0)
    s = sim(ctl)  # local_time_sec нет — берём подмену системных часов
    assert s.local_time_sec is None
    text = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0].display
    assert "добрый вечер" in text and "доброе утро" not in text


def test_not_every_transmission_and_once_per_station(cfg, airspace):
    ctl = make_ctl(cfg, airspace, chattiness="normal")
    ctl.talk = FixedTalk(0.99)
    s = _at(ctl, 10)
    quiet = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert "разрешено до Пулково" in quiet.display
    assert "доброе утро" not in quiet.display and "здравствуйте" not in quiet.display

    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = ScriptedTalk([0.0, 0.99, 0.0])
    s = _at(ctl, 10)
    first = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert "доброе утро" in first.display
    closed = tx(ctl.on_pilot("подтверждаю", s))[0]
    assert "до свидания" not in closed.display and "счастливого" not in closed.display
    assert "правильно" in closed.display and "Руление" in closed.display
    s = sim(ctl, unit_type="ground")
    s.local_time_sec = 10 * 3600
    push = tx(ctl.on_pilot("разрешите буксировку и запуск", s))[0]
    assert "буксировку и запуск разрешаю" in push.display
    assert "доброе утро" in push.display
    assert push.display.index("доброе утро") < push.display.index("разрешаю")


def test_repeat_prompt_does_not_spend_the_greeting(cfg, airspace):
    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = FixedTalk(0.0)
    s = _at(ctl, 10)
    bad = tx(ctl.on_pilot("абракадабра", s))[0]
    assert "повторите" in bad.display and "доброе утро" not in bad.display
    issued = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert "доброе утро" in issued.display and "разрешено до Пулково" in issued.display


def test_landing_farewell_follows_the_clearance(cfg, airspace):
    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = FixedTalk(0.0)
    s = sim(ctl, unit_type="tower", ap=ctl.arr, on_ground=False, agl_ft=800, alt_ind_ft=1200)
    s.local_time_sec = 15 * 3600
    r = tx(ctl.on_pilot("к посадке готов", s))[0]
    assert "посадку разрешаю" in r.display and "ВПП" in r.display
    assert "мягкой посадки" in r.display
    assert r.display.index("посадку разрешаю") < r.display.index("мягкой посадки")
    assert "добрый день" in r.display
    assert not any(ch.isdigit() for ch in r.speech)


def test_pilot_greeting_does_not_reopen_clearance(cfg, airspace):
    cfg["callsign"]["spoken"] = "Сибирь"
    cfg["callsign"]["number"] = "501"
    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = FixedTalk(0.0)
    s = _at(ctl, 11)
    issued = tx(ctl.on_pilot(
        "шереметьево делились сибирь пятьсот один прошу разрешения вылет пулково", s))[0]
    assert "разрешено до Пулково" in issued.display and ctl.pending is not None
    sq = ctl.squawk
    held = ctl.on_pilot("добрый день", s)
    assert ctl.pending is not None and ctl.pending.attempts == 0
    assert not any("подтвердите" in t.display or "повторите" in t.display or "разрешено" in t.display
                   for t in tx(held))
    phrase = "шереметев деливери сибирь пятьсот первый добрый день подтверждаю приём"
    reply = tx(ctl.on_pilot(phrase, s))[0]
    assert reply.display.startswith("Сибирь 501")
    assert "правильно" in reply.display and "подтвердите" not in reply.display
    assert "Руление" in reply.display and sq
    assert ctl.pending is None and ctl.handoff_to is not None and ctl.handoff_to.type == "ground"
    again = ctl.on_pilot("добрый день, подтверждаю приём", s)
    assert ctl.pending is None
    assert not any("подтвердите" in t.display or "разрешено до Пулково" in t.display for t in tx(again))


def test_wrong_value_still_corrected_when_pilot_is_polite(cfg, airspace):
    ctl = make_ctl(cfg, airspace, chattiness="off")
    s = _at(ctl, 12)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    bad = tx(ctl.on_pilot("подтверждаю приём, добрый день, ответчик 7777", s))[0]
    assert "неправильно" in bad.display and ctl.squawk in bad.display
    assert ctl.pending is not None and "добрый" not in bad.display
    garbage = tx(ctl.on_pilot("абракадабра, спасибо", s))[0]
    assert "подтвердите" in garbage.display and ctl.pending is not None


def test_goodbye_and_thanks_do_not_ask_to_repeat(cfg, airspace):
    ctl = make_ctl(cfg, airspace, chattiness="off")
    s = _at(ctl, 16)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    ctl.on_pilot("подтверждаю", s)
    for phrase in ("спасибо", "до свидания", "всего доброго", "хорошего дня"):
        ev = ctl.on_pilot(phrase, s)
        assert tx(ev) == [], phrase
        assert not any("повторите" in getattr(e, "text", "") for e in ev)

    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = FixedTalk(0.0)
    s = _at(ctl, 16)
    ev = ctl.on_pilot("до свидания", s)
    reply = tx(ev)
    assert reply and "до свидания" in reply[0].display
    assert "повторите" not in reply[0].display and "разрешено" not in reply[0].display

    ctl.talk = FixedTalk(0.99)
    ev = ctl.on_pilot("спасибо", s)
    assert tx(ev) == []


@pytest.mark.parametrize("text,intent,greet,farewell", [
    ("добрый день, разрешите руление", "request_taxi", True, False),
    ("разрешите руление, спасибо", "request_taxi", False, True),
    ("здравствуйте, прошу разрешение до Пулково", "request_clearance", True, False),
    ("подтверждаю, всего доброго", "wilco", False, True),
    ("добрый день, шесть тысяч футов, ответчик 1501", "readback", True, False),
    ("до свидания", "farewell", False, True),
    ("Пулково Вышка, добрый вечер", "check_in", True, False),
])
def test_parser_keeps_the_operational_intent(text, intent, greet, farewell):
    msg = parse(text)
    assert msg.intent == intent
    assert msg.greet is greet and msg.farewell is farewell
    if intent == "readback":
        assert msg.slots["alt_ft"] == 6000 and msg.slots["squawk"] == "1501"


def test_bare_confirmation_ignores_courtesy_words():
    assert is_bare_confirmation("подтверждаю, добрый день", callsign="Аэрофлот", number="1234")
    assert is_bare_confirmation("спасибо, подтверждаю приём", callsign="Аэрофлот", number="1234")
    assert is_bare_confirmation("до свидания, так точно", callsign="Сибирь", number="501")
    assert not is_bare_confirmation("подтверждаю, добрый день, ВПП 24", callsign="Аэрофлот", number="1234")
    assert not is_bare_confirmation("спасибо, ответчик 7777", callsign="Аэрофлот", number="1234")


def test_vocabulary_has_courtesy_words():
    words = set(build_vocabulary())
    for word in ("спасибо", "свидания", "полета", "мягкой", "здравствуйте", "принято"):
        assert word in words


def test_strip_removes_courtesy_and_leaves_clearance():
    raw = ("Аэрофлот 1234, доброе утро, Шереметьево-Деливери, разрешено до Пулково, "
           "взлёт ВПП 24, ответчик 1501, счастливого полёта")
    cleaned = strip_courtesy_text(raw)
    assert cleaned == ("Аэрофлот 1234, Шереметьево-Деливери, разрешено до Пулково, "
                       "взлёт ВПП 24, ответчик 1501")
