"""Произношение латинских названий (точки, схемы SID/STAR, заходы) для русского синтеза речи.

ПРЕДПОЛОЖЕНИЕ по фразеологии: точку читаем как слово по-русски («LAKIB» -> «лакиб»), схему —
«основа + цифра + буква фонетического алфавита» («LAKI1G» -> «лаки один гольф»).
"""
from __future__ import annotations

import re

from .numbers import int_to_words

PHONETIC = {
    "A": "альфа", "B": "браво", "C": "чарли", "D": "дельта", "E": "эхо", "F": "фокстрот", "G": "гольф",
    "H": "отель", "I": "индия", "J": "джульетт", "K": "кило", "L": "лима", "M": "майк", "N": "новэмбер",
    "O": "оскар", "P": "папа", "Q": "квебек", "R": "ромео", "S": "сьерра", "T": "танго", "U": "юниформ",
    "V": "виктор", "W": "виски", "X": "эксрэй", "Y": "янки", "Z": "зулу",
}
DIGRAPHS = [("SCH", "ш"), ("SH", "ш"), ("CH", "ч"), ("KH", "х"), ("ZH", "ж"), ("TS", "ц"), ("YA", "я"),
            ("YU", "ю"), ("YO", "ё"), ("YE", "е"), ("OO", "у"), ("EE", "и"), ("PH", "ф"), ("TH", "т")]
LETTERS = {"A": "а", "B": "б", "C": "к", "D": "д", "E": "е", "F": "ф", "G": "г", "H": "х", "I": "и",
           "J": "дж", "K": "к", "L": "л", "M": "м", "N": "н", "O": "о", "P": "п", "Q": "к", "R": "р",
           "S": "с", "T": "т", "U": "у", "V": "в", "W": "в", "X": "кс", "Y": "и", "Z": "з"}

APPROACH_TYPES = [  # (префикс ARINC/Zibo, отображение)
    ("ILS", "ILS"), ("LOC", "LOC"), ("RNV", "RNAV"), ("RNAV", "RNAV"), ("RNP", "RNAV"), ("GLS", "GLS"),
    ("VOR", "VOR"), ("VDM", "VOR"), ("NDB", "NDB"), ("I", "ILS"), ("L", "LOC"), ("R", "RNAV"), ("H", "RNAV"),
    ("J", "GLS"), ("V", "VOR"), ("D", "VOR"), ("S", "VOR"), ("N", "NDB"), ("Q", "NDB"), ("B", "LOC"),
]
SPEECH_ABBR = {"ILS": "ИЛС", "RNAV": "эр нав", "VOR": "вор", "NDB": "эн дэ бэ", "LOC": "курсовой маяк",
               "GLS": "джи эл эс", "QNH": "кью эн эйч"}


def translit(word: str) -> str:
    w = word.upper()
    out, i = [], 0
    while i < len(w):
        for lat, cyr in DIGRAPHS:
            if w.startswith(lat, i):
                out.append(cyr)
                i += len(lat)
                break
        else:
            ch = w[i]
            if ch == "E" and i == 0:
                out.append("э")
            elif ch.isdigit():
                out.append(" " + int_to_words(int(ch)) + " ")
            else:
                out.append(LETTERS.get(ch, ch.lower()))
            i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def spell(word: str) -> str:
    """Побуквенно фонетическим алфавитом: 'UUBW' -> 'юниформ юниформ браво виски'."""
    return " ".join(PHONETIC.get(c, int_to_words(int(c)) if c.isdigit() else c) for c in word.upper())


def proc_to_words(name: str) -> str:
    """'LAKI1G' -> 'лаки один гольф'; 'TOPL1' -> 'топл один'."""
    m = re.match(r"^([A-Z]+?)(\d)([A-Z]?)$", name.upper())
    if not m:
        return translit(name)
    base, dig, let = m.groups()
    out = f"{translit(base)} {int_to_words(int(dig))}"
    return out + (f" {PHONETIC[let]}" if let else "")


def approach_type(app: str) -> str:
    a = (app or "").upper()
    for pfx, disp in APPROACH_TYPES:
        if a.startswith(pfx):
            return disp
    return ""


def latin_to_speech(text: str) -> str:
    """Страховка для TTS: известные сокращения -> по-русски; оставшиеся латинские слова:
    4 буквы (коды ИКАО) — побуквенно, остальное — транслитом."""
    def rep(m):
        w = m.group(0)
        if w in SPEECH_ABBR:
            return SPEECH_ABBR[w]
        if re.fullmatch(r"[A-Z]{4}", w):
            return spell(w)
        if re.fullmatch(r"[A-Z]{2,5}\d[A-Z]?", w):
            return proc_to_words(w)
        return translit(w)
    return re.sub(r"\b[A-Za-z][A-Za-z0-9]*\b", rep, text)
