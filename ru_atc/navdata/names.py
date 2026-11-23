"""Русские позывные органов из английских имён X-Plane.

Частота берётся из данных симулятора. Позывной, если орган уже есть в
``data/airports.yaml``, не трогаем. Новому органу и центру без своей строки
в yaml собирается фраза: известные города Центральной России — как в эфире
программы, остальное — имя из файла и русское окончание роли.
"""
from __future__ import annotations

import re

_ROLE_WORDS = re.compile(
    r"\b(CONTROL|CENTRE|CENTER|RADAR|APPROACH|DEPARTURE|TOWER|GROUND|DELIVERY|"
    r"INTERNATIONAL|AIRPORT|INTL|AIRFIELD|ACC|CTR|APP|TWR|GND|DEL)\b",
    re.I,
)

# Полная фраза РЦ, как её уже говорит программа.
CENTER_CALLSIGN = {
    "MOSCOW": "Москва-Контроль",
    "ST PETERSBURG": "Санкт-Петербург Контроль",
    "SAINT PETERSBURG": "Санкт-Петербург Контроль",
    "SANKT PETERBURG": "Санкт-Петербург Контроль",
    "LENINGRAD": "Санкт-Петербург Контроль",
    "PETERSBURG": "Санкт-Петербург Контроль",
}

# Имя аэродрома в именительном, если в yaml своего нет.
AIRPORT_RU = {
    "SHEREMETYEVO": "Шереметьево",
    "SHEREMETIEVO": "Шереметьево",
    "DOMODEDOVO": "Домодедово",
    "VNUKOVO": "Внуково",
    "PULKOVO": "Пулково",
    "ZHUKOVSKY": "Жуковский",
    "ZHUKOVSKIY": "Жуковский",
}

UNIT_SUFFIX = {
    "delivery": "Деливери",
    "ground": "Руление",
    "tower": "Вышка",
    "approach": "Подход",
    "departure": "Выход",
    "radar": "Круг",
    "atis": "АТИС",
    "control": "Контроль",
}


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def place_key(name: str) -> str:
    text = (name or "").upper().replace(".", " ").replace("-", " ").replace("_", " ")
    text = _ROLE_WORDS.sub(" ", text)
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def control_callsign(name: str, spoken: str = "") -> str:
    raw = (spoken or name or "").strip()
    if _has_cyrillic(raw):
        if re.search(r"контрол", raw, re.I):
            return raw
        return f"{raw}-Контроль"
    key = place_key(raw)
    if key in CENTER_CALLSIGN:
        return CENTER_CALLSIGN[key]
    # «ST PETERSBURG APPROACH» уже схлопнут в ключ. Длинные ключи важнее коротких.
    for known in sorted(CENTER_CALLSIGN, key=len, reverse=True):
        if known in key:
            return CENTER_CALLSIGN[known]
    title = raw or "Контроль"
    if title.upper() in ("TOPLEVEL", "TOP LEVEL"):
        return "Район"
    return f"{title}-Контроль"


def airport_display_name(name: str) -> str:
    if _has_cyrillic(name or ""):
        return name.strip()
    key = place_key(name)
    if key in AIRPORT_RU:
        return AIRPORT_RU[key]
    for known, ru in AIRPORT_RU.items():
        if known in key:
            return ru
    return (name or "").strip()


def unit_callsign(airport_name: str, kind: str) -> str:
    suffix = UNIT_SUFFIX.get(kind, "Диспетчер")
    base = airport_display_name(airport_name) or "Аэродром"
    return f"{base}-{suffix}"
