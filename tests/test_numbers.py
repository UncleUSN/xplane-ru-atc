import pytest

from ru_atc.phraseology.numbers import (alt_to_words, digits_to_words, freq_to_words, int_to_words,
                                        runway_to_words, words_to_digits)


@pytest.mark.parametrize("text,expected", [
    ("эшелон три пять ноль", "эшелон 350"),
    ("эшелон двести сорок", "эшелон 240"),
    ("ответчик один пять ноль один", "ответчик 1501"),
    ("ответчик ноль семь один один", "ответчик 0711"),
    ("частота сто восемнадцать запятая семь", "частота 118.7"),
    ("сто двадцать запятая восемь семь пять", "120.875"),
    ("шесть тысяч футов", "6000 футов"),
    ("до четырех тысяч футов", "до 4000 футов"),
    ("десять тысяч", "10000"),
    ("семь тысяч пятьсот", "7500"),
    ("давление тысяча тринадцать", "давление 1013"),
    ("давление девятьсот девяносто восемь", "давление 998"),
    ("полоса двадцать четыре левая", "полоса 24 левая"),
    ("пятьсот первый", "501"),
    ("триста второй", "302"),
    ("сто первый", "101"),
    ("сто восемнадцать семь", "118 7"),
    ("118,7", "118.7"),
])
def test_words_to_digits(text, expected):
    assert words_to_digits(text) == expected


def test_int_to_words():
    assert int_to_words(6000) == "шесть тысяч"
    assert int_to_words(1013) == "тысяча тринадцать"
    assert int_to_words(21000) == "двадцать одна тысяча"
    assert int_to_words(3500) == "три тысячи пятьсот"
    assert int_to_words(0) == "ноль"


def test_speech_helpers():
    assert digits_to_words("1501") == "один пять ноль один"
    assert freq_to_words(118.7) == "сто восемнадцать запятая семь"
    assert freq_to_words(120.875) == "сто двадцать запятая восемь семь пять"
    assert runway_to_words("24L") == "двадцать четыре левая"
    assert runway_to_words("06R") == "ноль шесть правая"
    assert alt_to_words(6000) == "шесть тысяч футов"
    assert alt_to_words(2) == "два фута"


def test_roundtrip_numbers():
    for n in [5, 17, 40, 118, 240, 350, 998, 1013, 2600, 3500, 6000, 10000]:
        assert words_to_digits(int_to_words(n)) == str(n)
