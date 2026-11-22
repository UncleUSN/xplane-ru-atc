import pytest

from ru_atc.events import Hint, Transmission
from ru_atc.model import SimState

from conftest import make_ctl


def sim(ctl, unit_type="delivery", ap=None, **kw):
    ap = ap or ctl.dep
    s = SimState(t=kw.pop("t", 10.0), connected=True, lat=ap.lat, lon=ap.lon, qnh_hpa=998.4,
                 wind_dir=250, wind_kt=10)
    u = ap.unit(unit_type)
    s.com1_khz = u.khz if u else 0
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def tx(evs):
    return [e for e in evs if isinstance(e, Transmission)]


def test_clearance_and_correct_readback(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.update(s)
    t = tx(ctl.on_pilot("Шереметьево Деливери, Аэрофлот 1234, прошу разрешение до Пулково", s))[0]
    assert "разрешено до Пулково" in t.display and "ответчик" in t.display and "6000" in t.display
    assert t.unit.callsign == "Шереметьево-Деливери"
    assert "один" in t.speech or "пять" in t.speech      # номер ответчика в речи словами
    sq = ctl.squawk
    words = " ".join({"0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре", "5": "пять",
                      "6": "шесть", "7": "семь"}[c] for c in sq)
    r = tx(ctl.on_pilot(f"шесть тысяч футов, ответчик {words}, Аэрофлот 1234", s))[0]
    assert "правильно" in r.display and "Шереметьево-Руление" in r.display
    assert ctl.pending is None
    assert ctl.handoff_to.callsign == "Шереметьево-Руление"


@pytest.mark.parametrize("phrase", [
    "подтверждаю",
    "подтвреждаю",
    "понял",
    "принял",
    "выполняю",
    "вас понял",
    "так точно",
    "роджер",
    "уилко",
    "Аэрофлот 1234, понял",
    "Шереметьево-Деливери, Аэрофлот один два три четыре, подтверждаю",
])
def test_bare_confirmation_accepts_clearance(cfg, airspace, phrase):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    ev = ctl.on_pilot(phrase, s)
    assert ctl.pending is None
    assert ctl.handoff_to is not None and ctl.handoff_to.callsign == "Шереметьево-Руление"
    shown = tx(ev)
    assert shown and "Руление" in shown[0].display
    assert "правильно" not in shown[0].display


def test_confirmation_with_wrong_value_is_still_corrected(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    r = tx(ctl.on_pilot("подтверждаю, ответчик 7777", s))[0]
    assert "неправильно" in r.display and ctl.squawk in r.display
    assert ctl.pending is not None
    # голое подтверждение после поправки диспетчера указание закрывает
    ev = ctl.on_pilot("понял", s)
    assert ctl.pending is None
    assert any("Руление" in t.display for t in tx(ev))


def test_wrong_runway_and_level_and_frequency(cfg, airspace):
    from ru_atc.controller import PendingReadback

    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    ctl.on_pilot("подтверждаю", s)
    s = sim(ctl, unit_type="ground")
    ctl.on_pilot("разрешите буксировку и запуск", s)
    tx(ctl.on_pilot("разрешите руление", s))
    bad = tx(ctl.on_pilot("ВПП 06 левая", s))[0]
    assert "неправильно" in bad.display and ctl.pending is not None

    unit = ctl.dep.unit("delivery")
    s = sim(ctl)
    ctl.controlling = unit
    ctl.pending = PendingReadback(items={"level": 330}, t=s.t, unit=unit, seq=7)
    r = tx(ctl.on_pilot("эшелон 240", s))[0]
    assert "неправильно" in r.display and "330" in r.display
    ctl.pending = PendingReadback(items={"freq": 121.8}, t=s.t, unit=unit, seq=8)
    r = tx(ctl.on_pilot("частота 132.6", s))[0]
    assert "неправильно" in r.display and "121.8" in r.display
    ctl.pending = PendingReadback(items={"level": 150}, t=s.t, unit=unit, seq=9)
    assert tx(ctl.on_pilot("так точно", s)) == []
    assert ctl.pending is None


def test_garbage_does_not_confirm(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    r = tx(ctl.on_pilot("абракадабра", s))[0]
    assert "подтвердите" in r.display and ctl.pending is not None


def test_strict_readback_rejects_bare_confirmation(cfg, airspace):
    ctl = make_ctl(cfg, airspace, readback_strictness="strict")
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    r = tx(ctl.on_pilot("подтверждаю", s))[0]
    assert "подтвердите" in r.display and ctl.pending is not None
    # в строгом режиме по-прежнему принимается полное повторение
    words_sq = " ".join({"0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре",
                         "5": "пять", "6": "шесть", "7": "семь"}[c] for c in ctl.squawk)
    r = tx(ctl.on_pilot(f"6000 футов, ответчик {words_sq}", s))[0]
    assert "правильно" in r.display and ctl.pending is None


def test_wrong_readback(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    r = tx(ctl.on_pilot("6000 футов, ответчик 7777", s))[0]
    assert "неправильно" in r.display and ctl.squawk in r.display
    r = tx(ctl.on_pilot("ответчик " + ctl.squawk, s))[0]
    assert "подтвердите" in r.display and "6000" in r.display


def test_strict_frequency_no_station(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl, com1_khz=123450)
    evs = ctl.on_pilot("прошу разрешение до Пулково", s)
    assert not tx(evs)
    assert any(isinstance(e, Hint) and "никто не отвечает" in e.text for e in evs)


def test_redirect_to_correct_unit(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl, unit_type="tower")
    r = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert r.unit.callsign == "Шереметьево-Старт"
    assert "работайте с Шереметьево-Деливери" in r.display


def test_push_without_clearance(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl, unit_type="ground")
    r = tx(ctl.on_pilot("разрешите буксировку и запуск", s))[0]
    assert "не получено" in r.display


def test_taxi_and_takeoff(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    ctl.on_pilot(f"6000 футов ответчик {ctl.squawk}", s)
    s = sim(ctl, unit_type="ground")
    tx(ctl.on_pilot("разрешите буксировку и запуск", s))
    r = tx(ctl.on_pilot("разрешите руление", s))[0]
    assert "предварительному старту ВПП 24" in r.display and "QNH 998" in r.display
    assert ctl.handoff_to.type == "tower"
    s = sim(ctl, unit_type="tower")
    r = tx(ctl.on_pilot("на предварительном, к взлёту готов", s))[0]
    assert "взлёт разрешаю" in r.display and "ветер 250° 5 м/с" in r.display
    assert ctl.flags["takeoff"]


def test_non_strict_mode(cfg, airspace):
    ctl = make_ctl(cfg, airspace, strict_frequency=False)
    s = sim(ctl, com1_khz=0)
    r = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert r.unit.type == "delivery"


def test_radio_check_and_say_again(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    r = tx(ctl.on_pilot("Деливери, Аэрофлот 1234, проверка связи", s))[0]
    assert "слышу" in r.display
    r2 = tx(ctl.on_pilot("повторите", s))[0]
    assert r2.display == r.display


def test_unknown_phrase(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    r = tx(ctl.on_pilot("абракадабра", s))[0]
    assert "повторите" in r.display


def test_regional_fallback_units(cfg, airspace):
    # У UUBW нет своих органов — обслуживает Москва-Контроль
    ctl = make_ctl(cfg, airspace, dep="UUBW", arr="UUEE")
    u = ctl.unit_of(ctl.dep, "delivery")
    assert u.callsign == "Москва-Контроль"


def test_speech_has_no_digits(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    r = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert not any(ch.isdigit() for ch in r.speech), r.speech
