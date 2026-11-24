"""Поиск органа по частоте COM1 после подмены из apt.dat и atc.dat.

Сценарий с UUEE в X-Plane 12.4.4: окно пишет «Деливери 120.875 → 128.600»,
пилот настраивает 128.600 или остаётся на 120.875, а atc.dat уже тихо
поставил третью частоту. Отвечать нужно на всех трёх. Лишнее «север»
от распознавателя выход на связь не ломает.
"""
from ru_atc.airspace import COM_MATCH_KHZ
from ru_atc.events import Hint, Transmission
from ru_atc.navdata.overlay import _set_freq

from conftest import make_ctl
from test_controller import sim, tx

# Как в журнале: «шереметьево деливери север сибирь пятьсот двадцать два здравствуйте»
_LOG = "шереметьево деливери север сибирь пятьсот двадцать два здравствуйте"


def _delivery_like_uuee(cfg, airspace):
    """yaml 120.875, apt.dat 128.600, затем тихий atc.dat 121.900."""
    cfg["callsign"]["spoken"] = "Сибирь"
    cfg["callsign"]["number"] = "501"
    ctl = make_ctl(cfg, airspace)
    ap = ctl.dep
    delivery = ap.unit("delivery")
    assert abs(delivery.freq - 120.875) < 0.001
    notes = []
    _set_freq(ap, "delivery", 128.600, "apt:Global Scenery/Global Airports", notes, quiet=False)
    assert any("128.600" in line and "120.875" in line for line in notes)
    _set_freq(ap, "delivery", 121.900, "atc.dat", [], quiet=True)
    assert abs(delivery.freq - 121.900) < 0.001
    assert any(abs(alias - 128.600) < 0.001 for alias in delivery.aliases)
    assert any(abs(alias - 120.875) < 0.001 for alias in delivery.aliases)
    ctl.nav = object()
    return ctl


def _nofreq(evs):
    return [e for e in evs if isinstance(e, Hint) and e.key == "nofreq"]


def test_answers_on_announced_aptdat_frequency_and_old_yaml(cfg, airspace):
    ctl = _delivery_like_uuee(cfg, airspace)
    s = sim(ctl)
    s.com1_khz = 128600
    ev = ctl.on_pilot(_LOG, s)
    assert _nofreq(ev) == []
    said = tx(ev)
    assert said and said[0].unit.type == "delivery"
    assert said[0].display.startswith("Сибирь 522")
    assert "повторите" not in said[0].display
    assert any(isinstance(e, Hint) and "Сибирь 522" in e.text and "Сибирь 501" in e.text for e in ev)

    s.com1_khz = 120875
    again = ctl.on_pilot("как слышите", s)
    assert _nofreq(again) == []
    assert tx(again) and tx(again)[0].unit.type == "delivery"

    # Частота, которую atc.dat оставил рабочей, тоже слышит.
    s.com1_khz = 121900
    live = ctl.on_pilot("как слышите", s)
    assert _nofreq(live) == []
    assert tx(live) and tx(live)[0].unit.type == "delivery"


def test_833_rounding_within_one_channel_matches_and_25khz_does_not(cfg, airspace):
    ctl = _delivery_like_uuee(cfg, airspace)
    s = sim(ctl)
    # 128.605 — соседний канал 8.33, на 5 кГц от объявленных 128.600. Допуск это покрывает.
    assert COM_MATCH_KHZ >= 5
    s.com1_khz = 128605
    near = ctl.on_pilot("как слышите", s)
    assert _nofreq(near) == [] and tx(near)
    # 128.625 — следующий канал 25 кГц, это уже другая частота.
    s.com1_khz = 128625
    missed = ctl.on_pilot("как слышите", s)
    assert _nofreq(missed)
    assert "навигационн" in _nofreq(missed)[0].text
    assert "X-Plane" in _nofreq(missed)[0].text
    assert "Шереметьево-Деливери" in _nofreq(missed)[0].text
    assert "121.900" in _nofreq(missed)[0].text
    assert "128.600" in _nofreq(missed)[0].text


def test_yaml_only_hint_when_navdata_was_not_loaded(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    assert ctl.nav is None
    s = sim(ctl)
    s.com1_khz = 110000
    text = _nofreq(ctl.on_pilot("здравствуйте", s))[0].text
    assert "data/airports.yaml" in text
    assert "навигационн" not in text
