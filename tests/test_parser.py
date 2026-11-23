import pytest

from ru_atc.phraseology.parser import parse


@pytest.mark.parametrize("text,intent", [
    ("Шереметьево Деливери, Аэрофлот один два три четыре, стоянка двадцать, прошу разрешение до Пулково", "request_clearance"),
    ("Аэрофлот 1234, запрашиваю условия выхода", "request_clearance"),
    ("Аэрофлот 1234, разрешите буксировку и запуск", "request_push_start"),
    ("разрешите буксировку", "request_pushback"),
    ("Аэрофлот 1234, разрешите запуск", "request_startup"),
    ("разрешите руление", "request_taxi"),
    ("на предварительном, к взлёту готов", "ready_departure"),
    ("разрешите занять исполнительный", "request_lineup"),
    ("Москва Контроль, Аэрофлот 1234, добрый день, эшелон двести сорок в наборе эшелона триста пятьдесят", "report_airborne"),
    ("занял эшелон три пять ноль", "report_level"),
    ("разрешите снижение", "request_descent"),
    ("на посадочном ВПП двадцать восемь правая", "report_established"),
    ("к посадке готов", "request_landing"),
    ("полосу освободил", "runway_vacated"),
    ("разрешите рулить на стоянку", "request_taxi_in"),
    ("ухожу на второй круг", "going_around"),
    ("как слышите", "radio_check"),
    ("повторите", "say_again"),
    ("Пулково Вышка, Аэрофлот 1234, добрый вечер", "check_in"),
    ("добрый день", "check_in"),
    ("здравствуйте", "check_in"),
    ("до свидания", "farewell"),
    ("спасибо", "farewell"),
    ("всего доброго", "farewell"),
    ("хорошего дня", "farewell"),
    ("добрый день, разрешите руление", "request_taxi"),
    ("разрешите руление, спасибо", "request_taxi"),
    ("подтверждаю, до свидания", "wilco"),
    ("добрый день, подтверждаю приём", "wilco"),
])
def test_intents(text, intent):
    assert parse(text).intent == intent


def test_readback_slots_words():
    m = parse("разрешено до Пулково, набор шесть тысяч футов, ответчик один пять ноль один, Аэрофлот 1234")
    assert m.intent == "readback"
    assert m.slots["alt_ft"] == 6000
    assert m.slots["squawk"] == "1501"


def test_slots_runway_qnh_freq():
    m = parse("рулю к предварительному ВПП двадцать четыре центральная, давление девятьсот девяносто восемь")
    assert m.slots["runway"] == "24C"
    assert m.slots["qnh"] == 998
    m = parse("работаю с Санкт-Петербург Контроль сто тридцать два запятая шесть")
    assert m.slots["freq"] == 132.6
    m = parse("Круг сто двадцать шесть семьсот пятьдесят")   # без "запятая"
    assert "freq" in m.slots


def test_target_level():
    m = parse("эшелон 120 снижаюсь до эшелона 100")
    assert m.slots["level"] == 120 and m.slots["target_level"] == 100


def test_whisper_style_digits():
    m = parse("Аэрофлот 1234, эшелон 350, ответчик 1501, частота 127,0")
    assert m.slots["level"] == 350
    assert m.slots["squawk"] == "1501"
    assert m.slots["freq"] == 127.0


@pytest.mark.parametrize("heard,intent", [
    # реальные ошибки Vosk small на синтезированной речи
    ("шереметьево деливери аэрофлот один два три четыре стоянка двадцать прошу разрешения да пулково", "request_clearance"),
    ("разрешите руле не", "request_taxi"),
    ("москва контроль аэрофлот один два три четыре добрый день эшелон сто двадцать наборе шалуна сто пятьдесят", "report_airborne"),
    ("заняло шалун три три ноль", "report_level"),
    ("на посадочным бы по двадцать восемь права", "report_established"),
    ("аэрофлот один два три четыре разрешите буксировка и запуска", "request_push_start"),
])
def test_vosk_misrecognitions(heard, intent):
    assert parse(heard).intent == intent


def test_vosk_misrecognition_slots():
    m = parse("заняло шалун три три ноль")
    assert m.slots["level"] == 330
    m = parse("на посадочным бы по двадцать восемь права")
    assert m.slots["runway"] == "28R"
