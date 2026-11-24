"""Перестройка COM1: резервная частота и обмен с активной.

X-Plane хранит частоту COM в dataref как целое в килогерцах, хотя в описании
стоит «hertz»: 121.800 МГц — это 121800. Команда обмена исторически называется
``sim/radios/com1_standy_flip`` (без буквы b). Её понимает и Zibo 737, потому что
радиостанция читает штатные ``sim/cockpit2/radios/actuators/com1_*_hz_833``.

Если команды нет (Web API v1), активная частота пишется напрямую.
"""
from __future__ import annotations

from typing import Optional, Tuple

COM1_ACTIVE = "sim/cockpit2/radios/actuators/com1_frequency_hz_833"
COM1_STANDBY = "sim/cockpit2/radios/actuators/com1_standby_frequency_hz_833"
# Опечатка «standy» — так команда называется в X-Plane 11 и 12.
COM1_FLIP = "sim/radios/com1_standy_flip"


def khz_value(khz: int) -> int:
    """Число для dataref: 118700 для 118.700, 121800 для 121.800."""
    value = int(khz)
    if not 118000 <= value <= 137000:
        raise ValueError(f"частота COM вне диапазона: {value}")
    return value


def describe_tune(khz: int, *, flipped: bool, wrote_active: bool) -> str:
    mhz = khz_value(khz) / 1000.0
    shown = f"{mhz:.3f}"
    if flipped and wrote_active:
        return f"COM1 {shown}: резерв, обмен с активной"
    if flipped:
        return f"COM1 {shown}: резерв и обмен с активной"
    if wrote_active:
        return f"COM1 {shown}: записана активная частота (обмен резерва недоступен)"
    return f"COM1 {shown}: не перестроена"


def parse_auto_tune(value) -> bool:
    """Ключ radio.auto_tune_com1. По умолчанию выключено."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "да")
    return bool(value)


TuneResult = Tuple[bool, str]


def idle_tune(_khz: int) -> TuneResult:
    return False, "источник данных не перестраивает COM1"
