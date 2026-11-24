"""Страница вики «Радиообмен» говорит теми фразами, которые разбирает программа."""
from pathlib import Path

import pytest

from ru_atc.phraseology.parser import parse

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "wiki" / "Радиообмен.md"

# Фраза пилота из вики и намерение, которое программа ей назначает.
EXAMPLES = [
    ("Диспетчер, Сибирь 213, здравствуйте", "check_in"),
    ("Шереметьево-Деливери, Сибирь 213, здравствуйте, прошу разрешение до Пулково", "request_clearance"),
    ("подтверждаю", "wilco"),
    ("разрешите буксировку и запуск", "request_push_start"),
    ("разрешите руление", "request_taxi"),
    ("разрешите занять исполнительный", "request_lineup"),
    ("на предварительном, к взлёту готов", "ready_departure"),
    ("в наборе, эшелон 120", "report_airborne"),
    ("занял эшелон 330", "report_level"),
    ("разрешите снижение", "request_descent"),
    ("разрешите заход", "request_approach"),
    ("на посадочном", "report_established"),
    ("к посадке готов", "request_landing"),
    ("ухожу на второй круг", "going_around"),
    ("полосу освободил", "runway_vacated"),
    ("разрешите рулить на стоянку", "request_taxi_in"),
    ("дайте АТИС", "request_atis"),
    ("информацию Альфа получил", "atis_ack"),
    ("фактическую погоду в Пулково", "request_weather"),
    ("погоду на аэродроме назначения", "request_weather"),
    ("сообщите погоду", "request_weather"),
    ("какая погода на вылете", "request_weather"),
    ("мэйдэй мэйдэй мэйдэй", "emergency_mayday"),
    ("пан-пан", "emergency_pan"),
    ("отменяю бедствие", "emergency_cancel"),
    ("как слышите", "radio_check"),
    ("повторите", "say_again"),
    ("повторите информацию", "request_atis"),
]


@pytest.mark.parametrize("phrase,intent", EXAMPLES)
def test_wiki_phrase_is_what_the_parser_hears(phrase, intent):
    text = PAGE.read_text(encoding="utf-8")
    assert phrase in text
    assert parse(phrase).intent == intent


def test_radio_page_is_linked():
    side = (ROOT / "docs" / "wiki" / "_Sidebar.md").read_text(encoding="utf-8")
    home = (ROOT / "docs" / "wiki" / "Home.md").read_text(encoding="utf-8")
    first = (ROOT / "docs" / "wiki" / "Первый-полёт.md").read_text(encoding="utf-8")
    assert "[[Радиообмен]]" in side
    assert "[[Радиообмен]]" in home
    assert "[[Радиообмен]]" in first
