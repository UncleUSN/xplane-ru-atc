"""Какой голос реально говорит за орган и какого он пола.

Silero v4_ru: baya, kseniya, xenia — женские; aidar, eugene — мужские.
Для edge-tts пол берётся из имени голоса (Dmitry / Svetlana).
pyttsx3 — один системный голос на всех: мужской, если имя не выдаёт женский (Irina и т.п.).
"""
from __future__ import annotations

from typing import Optional

# Подстроки в нижнем регистре. «ksenia» — частая запись «kseniya».
_FEMALE = ("baya", "kseniya", "ksenia", "xenia", "irina", "svetlana")
_MALE = ("aidar", "eugene", "dmitry", "dmitri", "pavel")


def voice_gender(voice: Optional[str]) -> str:
    """'female' или 'male'. Незнакомое и пустое имя — мужской."""
    v = (voice or "").strip().lower().replace("ё", "е")
    if any(name in v for name in _FEMALE):
        return "female"
    if any(name in v for name in _MALE):
        return "male"
    return "male"


def speaking_voice(voice_cfg: Optional[dict], unit_type: str, engine: Optional[str] = None) -> str:
    """Имя голоса, которым этот орган говорит (или 'male', если выбрать не из чего)."""
    cfg = voice_cfg or {}
    eng = (engine if engine is not None else cfg.get("tts_engine") or "silero")
    eng = str(eng).strip().lower()
    if eng == "edge":
        return str(cfg.get("edge_voice") or "ru-RU-DmitryNeural")
    if eng == "pyttsx3":
        return str(cfg.get("pyttsx3_voice") or "male")
    mapped = (cfg.get("unit_voices") or {}).get(unit_type)
    if mapped:
        return str(mapped)
    return str(cfg.get("silero_speaker") or "aidar")


def controller_gender(voice_cfg: Optional[dict], unit_type: str, engine: Optional[str] = None) -> str:
    return voice_gender(speaking_voice(voice_cfg, unit_type, engine))
