"""Модели, которые предлагает установщик.

Это единственный список идентификаторов, адресов и подписей кнопок мастера.
Скрипт installer/render_catalog.py собирает из него страницу Inno Setup и config.yaml.
Веса в репозиторий не входят: их скачивают с адресов ниже.
"""
from __future__ import annotations

from typing import Dict, List

# Код программы грузит только эту модель Silero (см. voice/tts.py).
SILERO_MODEL_ID = "v4_ru"
SILERO_PACKAGE_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"
SILERO_CODE_REPO = "https://github.com/snakers4/silero-models"

VOSK_MODELS_PAGE = "https://alphacephei.com/vosk/models"

# Русские модели со страницы Vosk, на которые рассчитаны комментарии в коде и config.example.yaml.
# Старые vosk-model-ru-0.22 и vosk-model-ru-0.10 установщик не предлагает.
VOSK_MODELS: List[dict] = [
    {
        "id": "vosk-model-small-ru-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
        "size": "45 МБ",
        "default": True,
        "caption": (
            "Лёгкая vosk-model-small-ru-0.22 — 45 МБ, около 300 МБ памяти, "
            "быстрее, хуже разбирает числа (по умолчанию)"
        ),
    },
    {
        "id": "vosk-model-ru-0.42",
        "url": "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
        "size": "1,8 ГБ",
        "default": False,
        "caption": (
            "Большая vosk-model-ru-0.42 — 1,8 ГБ, точнее на речи и числах, "
            "нужно несколько ГБ памяти (большие модели Vosk — вплоть до 16 ГБ)"
        ),
    },
]

# Голоса v4_ru, которые реально принимает SileroTTS. Пол совпадает с voice/voices.py.
SILERO_VOICES: List[dict] = [
    {
        "id": "aidar",
        "gender_ru": "мужской",
        "default": True,
        "caption": "Silero v4_ru, голос aidar — мужской (по умолчанию)",
    },
    {
        "id": "baya",
        "gender_ru": "женский",
        "default": False,
        "caption": "Silero v4_ru, голос baya — женский",
    },
    {
        "id": "kseniya",
        "gender_ru": "женский",
        "default": False,
        "caption": "Silero v4_ru, голос kseniya — женский",
    },
    {
        "id": "xenia",
        "gender_ru": "женский",
        "default": False,
        "caption": "Silero v4_ru, голос xenia — женский",
    },
    {
        "id": "eugene",
        "gender_ru": "мужской",
        "default": False,
        "caption": "Silero v4_ru, голос eugene — мужской",
    },
]

# Органы, которым установщик прописывает выбранный голос.
UNIT_VOICE_KEYS = ("delivery", "ground", "tower", "radar", "approach", "control")


def _index(items: List[dict]) -> Dict[str, dict]:
    return {item["id"]: item for item in items}


VOSK_BY_ID = _index(VOSK_MODELS)
SILERO_BY_ID = _index(SILERO_VOICES)


def default_vosk_id() -> str:
    return next(item["id"] for item in VOSK_MODELS if item["default"])


def default_speaker() -> str:
    return next(item["id"] for item in SILERO_VOICES if item["default"])
