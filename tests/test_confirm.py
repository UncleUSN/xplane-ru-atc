"""Короткие подтверждения: точные фразы, опечатки Vosk и отказ, если в фразе есть значения."""
import pytest

from ru_atc.phraseology.confirm import is_bare_confirmation
from ru_atc.phraseology.parser import parse


@pytest.mark.parametrize("text", [
    "подтверждаю",
    "подтвреждаю",          # переставлены буквы, как у Vosk
    "подтвержаю",           # пропущена буква
    "потверждаю",
    "понял",
    "поняла",
    "принял",
    "выполняю",
    "вас понял",
    "васпонял",
    "так точно",
    "такточно",
    "роджер",
    "уилко",
    "wilco",
    "roger",
    "под тверждаю",
    "подтверждаю, Аэрофлот 1234",
    "Аэрофлот 1234, понял",
    "Аэрофлот один два три четыре, выполняю",
    "Шереметьево-Деливери, Аэрофлот 1234, так точно",
    "подтверждаю аэрофлод 1234",   # позывной с одной опечаткой
])
def test_bare_confirmations(text):
    assert is_bare_confirmation(
        text, callsign="Аэрофлот", number="1234", extra="Шереметьево-Деливери")


@pytest.mark.parametrize("text", [
    "",
    "абракадабра",
    "прошу разрешение до Пулково",
    "подтверждаю ВПП 24",
    "понял, эшелон 350",
    "ответчик 7777",
    "эшелон 240",
    "не понял",
    "не подтверждаю",
    "неподтверждаю",
    "разрешение",
    "полет",
    "частота 121.8",
])
def test_not_a_bare_confirmation(text):
    assert not is_bare_confirmation(
        text, callsign="Аэрофлот", number="1234", extra="Шереметьево-Деливери")


def test_parser_marks_wilco_and_keeps_values_as_readback():
    assert parse("подтвреждаю").intent == "wilco"
    assert parse("вас понял").intent == "wilco"
    assert parse("не понял").intent == "say_again"
    msg = parse("понял, эшелон 240")
    assert msg.intent == "readback"
    assert msg.slots["level"] == 240
