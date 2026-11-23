"""МЭЙДЭЙ, ПАН-ПАН и коды 7700/7600."""
from ru_atc.events import Hint, Transmission
from ru_atc.phraseology.parser import parse

from conftest import make_ctl
from test_controller import sim, tx


class _Talk:
    def random(self):
        return 0.0

    def choice(self, seq):
        return seq[0]


def test_emergency_phrases():
    assert parse("МЭЙДЭЙ МЭЙДЭЙ МЭЙДЭЙ").intent == "emergency_mayday"
    assert parse("мэйдэй").intent == "emergency_mayday"
    assert parse("пан-пан").intent == "emergency_pan"
    assert parse("пан пан пан").intent == "emergency_pan"
    assert parse("отменяю бедствие").intent == "emergency_cancel"
    assert parse("отбой мэйдэй").intent == "emergency_cancel"
    assert parse("ситуация нормальная").intent == "emergency_cancel"
    assert parse("прошу разрешение до Пулково").intent == "request_clearance"


def test_mayday_gets_priority_and_can_be_cancelled(cfg, airspace):
    ctl = make_ctl(cfg, airspace, chattiness="high")
    ctl.talk = _Talk()
    s = sim(ctl)
    s.local_time_sec = 10 * 3600
    ctl.on_pilot("прошу разрешение до Пулково", s)
    assert ctl.pending is not None
    reply = tx(ctl.on_pilot("диспетчер, мэйдэй мэйдэй мэйдэй", s))[0]
    assert ctl.pending is None and ctl.emergency == "mayday" and ctl.emergency_source == "voice"
    assert "бедствие принял" in reply.display and "приоритет" in reply.display
    assert "7700" in reply.display and "Шереметьево" in reply.display
    assert "людей" in reply.display and "топлив" in reply.display
    assert not any(ch.isdigit() for ch in reply.speech)
    assert "добр" not in reply.display
    follow = tx(ctl.on_pilot("на борту 120, топлива 4 тонны", s))[0]
    assert "приоритет сохранён" in follow.display and ctl.emergency == "mayday"
    # Приветствие не возвращается, пока бедствие не снято.
    later = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert "разрешено" in later.display and "добр" not in later.display
    cancelled = tx(ctl.on_pilot("отменяю бедствие", s))[0]
    assert ctl.emergency is None and "отменено" in cancelled.display


def test_pan_and_verbal_cancel_asks_to_drop_7700(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.squawk = "1501"
    text = tx(ctl.on_pilot("пан-пан, пан-пан", s))[0].display
    assert "срочность" in text and "ниже бедствия" in text and ctl.emergency == "pan"
    s.xpdr_code = 7700
    done = tx(ctl.on_pilot("отбой пан-пан", s))[0].display
    assert ctl.emergency is None and "1501" in done and "отменено" in done


def test_squawk_7700_and_7600(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.controlling = ctl.dep.unit("delivery")
    ctl.squawk = "1501"
    s.xpdr_code = 7700
    s.on_ground = False
    s.agl_ft = 4000
    s.alt_ind_ft = 8000
    s.t = 50
    said = tx(ctl.update(s))
    assert said and "7700" in said[0].display and "бедствие" in said[0].display
    assert ctl.emergency == "mayday" and ctl.emergency_source == "squawk"
    s.t = 120
    assert not any("проверьте код" in t.display for t in tx(ctl.update(s)))
    s.xpdr_code = 2000
    s.t = 130
    notes = [e.text for e in ctl.update(s) if isinstance(e, Hint)]
    assert ctl.emergency is None and any("снят" in n for n in notes)

    s.xpdr_code = 7600
    s.t = 140
    radio = tx(ctl.update(s))[0].display
    assert "радиосвязи" in radio and "7600" in radio and ctl.emergency == "radio"
    s.xpdr_code = 2000
    s.t = 150
    ctl.update(s)
    assert ctl.emergency is None


def test_spoken_mayday_is_not_cleared_by_the_transponder(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("мэйдэй", s)
    assert ctl.emergency_source == "voice"
    s.xpdr_code = 2000
    ctl.controlling = ctl.dep.unit("delivery")
    ctl.update(s)
    assert ctl.emergency == "mayday"
    assert tx(ctl.on_pilot("отбой бедствия", s))[0].display
    assert ctl.emergency is None
