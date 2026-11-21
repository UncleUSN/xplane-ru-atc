"""Шаблоны фраз диспетчера с разметкой чисел -> текст для экрана и текст для синтеза речи.

Разметка: {cs} позывной, {fl:240}, {alt:6000}, {sq:1501}, {freq:118.7}, {rwy:24L},
{qnh:998}, {wind:240/5} (направление/скорость м/с), {hdg:240}, {num:5}, {km:30},
{proc:LAKI1G} схема SID/STAR, {fix:LAKIB} точка, {app:ILS28R} тип захода (ILS/RNAV/VOR...)
"""
from __future__ import annotations

import re
from typing import Tuple

from .names import approach_type, latin_to_speech, proc_to_words, translit
from .numbers import (alt_to_words, digits_to_words, freq_display, freq_to_words, int_to_words,
                      level_to_words, runway_display, runway_to_words)

TAG_RE = re.compile(r"\{(\w+)(?::([^}]*))?\}")


def _ms_word(n: int) -> str:
    n100, n10 = n % 100, n % 10
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "метров"
    if n10 == 1:
        return "метр"
    return "метра"


def _deg_word(n: int) -> str:
    n100, n10 = n % 100, n % 10
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "градусов"
    if n10 == 1:
        return "градус"
    return "градуса"


def _km_word(n: int) -> str:
    n100, n10 = n % 100, n % 10
    if 10 <= n100 < 20 or n10 == 0 or n10 >= 5:
        return "километров"
    if n10 == 1:
        return "километр"
    return "километра"


class Renderer:
    def __init__(self, cs_spoken: str, cs_number: str, levels_digit_by_digit: bool = False):
        self.cs_spoken = cs_spoken
        self.cs_number = str(cs_number)
        self.digit_levels = levels_digit_by_digit

    @property
    def callsign(self) -> str:
        return f"{self.cs_spoken} {self.cs_number}".strip()

    def _display(self, tag: str, val: str) -> str:
        if tag == "cs":
            return self.callsign
        if tag == "fl":
            return f"эшелон {int(val):03d}"
        if tag == "fla":   # эшелона (род. падеж)
            return f"эшелона {int(val):03d}"
        if tag == "alt":
            return f"{int(val)} футов"
        if tag == "sq":
            return str(val)
        if tag == "freq":
            return freq_display(val)
        if tag == "rwy":
            return runway_display(val)
        if tag == "qnh":
            return f"QNH {int(val)}"
        if tag == "wind":
            d, sp = val.split("/")
            return f"ветер {int(d):03d}° {int(sp)} м/с"
        if tag == "hdg":
            return f"{int(val):03d}"
        if tag == "km":
            return f"{int(val)} км"
        if tag == "app":
            return approach_type(val) or val
        return str(val)

    def _speech(self, tag: str, val: str) -> str:
        if tag == "cs":
            num = self.cs_number
            spoken_num = digits_to_words(num) if num.isdigit() else " ".join(num)
            return f"{self.cs_spoken} {spoken_num}".strip()
        if tag == "fl":
            return f"эшелон {level_to_words(int(val), self.digit_levels)}"
        if tag == "fla":
            return f"эшелона {level_to_words(int(val), self.digit_levels)}"
        if tag == "alt":
            return alt_to_words(int(val))
        if tag == "sq":
            return digits_to_words(val)
        if tag == "freq":
            return freq_to_words(val)
        if tag == "rwy":
            return runway_to_words(val)
        if tag == "qnh":
            return f"кью эн эйч {int_to_words(int(val))}"
        if tag == "wind":
            d, sp = (int(x) for x in val.split("/"))
            return f"ветер {int_to_words(d)} {_deg_word(d)} {int_to_words(sp)} {_ms_word(sp)}"
        if tag == "hdg":
            return digits_to_words(f"{int(val):03d}")
        if tag == "km":
            return f"{int_to_words(int(val))} {_km_word(int(val))}"
        if tag == "num":
            return int_to_words(int(val))
        if tag == "proc":
            return proc_to_words(val)
        if tag == "fix":
            return translit(val)
        if tag == "app":
            return approach_type(val) or val
        return str(val)

    def render(self, template: str) -> Tuple[str, str]:
        disp = TAG_RE.sub(lambda m: self._display(m.group(1), m.group(2) or ""), template)
        speech = TAG_RE.sub(lambda m: self._speech(m.group(1), m.group(2) or ""), template)
        # В речи убираем символы, которые TTS читает плохо
        speech = speech.replace("—", ",").replace("ВПП", "вэ пэ пэ")
        speech = latin_to_speech(speech)
        speech = re.sub(r"\s+", " ", speech).strip()
        return disp, speech
