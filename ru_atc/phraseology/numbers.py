"""Русские числительные: число -> слова (для TTS) и слова -> цифры (для распознанной речи)."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

DIGITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
         "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
        "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
            "восемьсот", "девятьсот"]


def _under_1000(n: int, feminine: bool = False) -> List[str]:
    words: List[str] = []
    h, rest = divmod(n, 100)
    if h:
        words.append(HUNDREDS[h])
    if 10 <= rest < 20:
        words.append(TEENS[rest - 10])
    else:
        t, u = divmod(rest, 10)
        if t:
            words.append(TENS[t])
        if u:
            if feminine and u in (1, 2):
                words.append("одна" if u == 1 else "две")
            else:
                words.append(DIGITS[u])
    return words


def int_to_words(n: int) -> str:
    """Количественное числительное, именительный падеж (до 999 999)."""
    if n == 0:
        return "ноль"
    if n < 0:
        return "минус " + int_to_words(-n)
    words: List[str] = []
    th, rest = divmod(n, 1000)
    if th:
        tw = _under_1000(th, feminine=True)
        last2 = th % 100
        last = th % 10
        if 10 <= last2 < 20 or last == 0 or last >= 5:
            suffix = "тысяч"
        elif last == 1:
            suffix = "тысяча"
        else:
            suffix = "тысячи"
        if th == 1:
            tw = []
        words += tw + [suffix]
    if rest:
        words += _under_1000(rest)
    return " ".join(words)


def digits_to_words(s: str) -> str:
    """'1501' -> 'один пять ноль один' (ответчик, позывной)."""
    return " ".join(DIGITS[int(c)] for c in str(s) if c.isdigit())


def freq_to_words(freq: float | str) -> str:
    """118.7 -> 'сто восемнадцать запятая семь'; 120.875 -> '... запятая восемь семь пять'."""
    s = f"{float(freq):.3f}".rstrip("0").rstrip(".")
    if "." in s:
        a, b = s.split(".")
    else:
        a, b = s, "0"
    return f"{int_to_words(int(a))} запятая {digits_to_words(b)}"


def freq_display(freq: float | str) -> str:
    s = f"{float(freq):.3f}"
    s = s.rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def level_to_words(fl: int, digit_by_digit: bool = False) -> str:
    """Эшелон 240 -> 'двести сорок' (или 'два четыре ноль')."""
    return digits_to_words(f"{int(fl):03d}") if digit_by_digit else int_to_words(int(fl))


def feet_word(n: int) -> str:
    n100 = n % 100
    n10 = n % 10
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "футов"
    if n10 == 1:
        return "фут"
    return "фута"


def alt_to_words(ft: int) -> str:
    return f"{int_to_words(int(ft))} {feet_word(int(ft))}"


RUNWAY_SIDE = {"L": "левая", "R": "правая", "C": "центральная"}


def runway_display(rwy: str) -> str:
    m = re.match(r"(\d{2})([LRC]?)", rwy.upper())
    if not m:
        return rwy
    num, side = m.groups()
    return f"{num}{' ' + RUNWAY_SIDE[side] if side else ''}"


def runway_to_words(rwy: str) -> str:
    m = re.match(r"(\d{2})([LRC]?)", rwy.upper())
    if not m:
        return rwy
    num, side = m.groups()
    w = int_to_words(int(num)) if num[0] != "0" else digits_to_words(num)
    return f"{w}{' ' + RUNWAY_SIDE[side] if side else ''}"


# ----------------------------------------------------------------------------
# Слова -> цифры
# ----------------------------------------------------------------------------
_UNITS = {w: i for i, w in enumerate(DIGITS)}
_UNITS.update({"одна": 1, "одну": 1, "одной": 1, "две": 2, "единица": 1, "единицу": 1,
               "нуль": 0, "двойка": 2, "тройка": 3, "четвёрка": 4, "четверка": 4,
               "пятёрка": 5, "пятерка": 5, "шестёрка": 6, "шестерка": 6, "семёрка": 7,
               "семерка": 7, "восьмёрка": 8, "восьмерка": 8, "девятка": 9})
# Косвенные падежи (после ё->е): "до четырех тысяч", "двухсот" и т.п.
_UNITS.update({"одного": 1, "двух": 2, "трех": 3, "четырех": 4, "пяти": 5, "шести": 6,
               "семи": 7, "восьми": 8, "девяти": 9, "четыре": 4})
# Порядковые только как хвост числа: «пятьсот первый» = 501. Само по себе «второй» не цифра
# («ухожу на второй круг» должно остаться фразой).
_ORDINALS = {
    "первый": 1, "первая": 1, "первое": 1, "первого": 1, "первому": 1, "первым": 1, "первой": 1,
    "второй": 2, "вторая": 2, "второе": 2, "второго": 2, "второму": 2, "вторым": 2,
    "третий": 3, "третья": 3, "третье": 3, "третьего": 3, "третью": 3,
    "четвертый": 4, "четвертая": 4, "четвертое": 4, "четвертого": 4,
    "пятый": 5, "пятая": 5, "пятое": 5, "пятого": 5,
    "шестой": 6, "шестая": 6, "шестое": 6, "шестого": 6,
    "седьмой": 7, "седьмая": 7, "седьмое": 7, "седьмого": 7,
    "восьмой": 8, "восьмая": 8, "восьмое": 8, "восьмого": 8,
    "девятый": 9, "девятая": 9, "девятое": 9, "девятого": 9,
}
_TEENS = {w: 10 + i for i, w in enumerate(TEENS)}
_TEENS.update({w[:-1] + "и": 10 + i for i, w in enumerate(TEENS)})   # десяти, двенадцати...
_TENS = {w: i * 10 for i, w in enumerate(TENS) if w}
_TENS.update({"двадцати": 20, "тридцати": 30, "сорока": 40, "пятидесяти": 50, "шестидесяти": 60,
              "семидесяти": 70, "восьмидесяти": 80, "девяноста": 90})
_HUNDREDS = {w: i * 100 for i, w in enumerate(HUNDREDS) if w}
_HUNDREDS.update({"ста": 100, "двухсот": 200, "трехсот": 300, "четырехсот": 400, "пятисот": 500,
                  "шестисот": 600, "семисот": 700, "восьмисот": 800, "девятисот": 900})
_THOUSAND = {"тысяча", "тысячи", "тысяч", "тысячу", "тысячах", "тысячам"}
_DECIMAL = {"запятая", "точка"}


def _is_num_word(w: str) -> bool:
    return w in _UNITS or w in _TEENS or w in _TENS or w in _HUNDREDS or w in _THOUSAND


def _extends_number(w: str) -> bool:
    return _is_num_word(w) or w in _ORDINALS


def _parse_run(words: List[str]) -> List[str]:
    """Последовательность числовых слов -> список чисел (строк).
    'три пять ноль' -> ['350'], 'сто восемнадцать семь' -> ['118','7'],
    'шесть тысяч' -> ['6000'], 'двадцать четыре' -> ['24']."""
    if len(words) >= 2 and all(w in _UNITS for w in words):
        return ["".join(str(_UNITS[w]) for w in words)]
    out: List[str] = []
    total = 0      # тысячи
    cur = 0
    have = {"h": False, "t": False, "u": False}
    started = False

    def flush():
        nonlocal total, cur, have, started
        if started:
            out.append(str(total + cur))
        total, cur, started = 0, 0, False
        have = {"h": False, "t": False, "u": False}

    for w in words:
        if w in _THOUSAND:
            total = (cur or 1) * 1000 + 0
            cur = 0
            have = {"h": False, "t": False, "u": False}
            started = True
            continue
        if w in _HUNDREDS:
            if have["h"] or have["t"] or have["u"]:
                flush()
            cur += _HUNDREDS[w]; have["h"] = True
        elif w in _TEENS:
            if have["t"] or have["u"]:
                flush()
            cur += _TEENS[w]; have["t"] = have["u"] = True
        elif w in _TENS:
            if have["t"] or have["u"]:
                flush()
            cur += _TENS[w]; have["t"] = True
        elif w in _UNITS:
            if have["u"] or (started and not (have["h"] or have["t"]) and total == 0):
                flush()
            cur += _UNITS[w]; have["u"] = True
            if _UNITS[w] == 0 and not (have["h"] or have["t"]):
                # одиночный ноль — отдельное число
                started = True
                flush()
                continue
        elif w in _ORDINALS:
            if have["h"] or have["t"] or total:
                if have["u"]:
                    flush()
                cur += _ORDINALS[w]
                have["u"] = True
            else:
                # «второй круг» — не число
                flush()
                out.append(w)
                continue
        started = True
    flush()
    return out


def words_to_digits(text: str) -> str:
    """Заменить числительные в тексте цифрами; 'N запятая M' -> 'N.M'."""
    tokens = text.split()
    res: List[str] = []
    i = 0
    while i < len(tokens):
        if _is_num_word(tokens[i]):
            j = i + 1
            while j < len(tokens) and _extends_number(tokens[j]):
                j += 1
            res.extend(_parse_run(tokens[i:j]))
            i = j
        else:
            res.append(tokens[i])
            i += 1
    s = " ".join(res)
    s = re.sub(r"(\d+)\s*(?:запятая|точка)\s*(\d+)", r"\1.\2", s)
    s = re.sub(r"(\d+),(\d+)", r"\1.\2", s)
    return s
