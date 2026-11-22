"""Пол голоса диспетчера и наличие маленьких портретов."""
import struct
from pathlib import Path

import pytest
import yaml

from ru_atc.avatars import ASSETS, avatar_file
from ru_atc.voice.voices import controller_gender, speaking_voice, voice_gender


def _png_size(path: Path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_avatar_pngs_are_small_icons():
    for gender in ("female", "male"):
        path = avatar_file(gender)
        assert path is not None and path.parent == ASSETS
        w, h = _png_size(path)
        assert 64 <= w <= 128 and 64 <= h <= 128
        assert path.stat().st_size < 80_000


def test_missing_avatar_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr("ru_atc.avatars.ASSETS", tmp_path)
    assert avatar_file("female") is None
    assert avatar_file("male") is None
    assert avatar_file("other") is None


@pytest.mark.parametrize("voice,gender", [
    ("baya", "female"),
    ("kseniya", "female"),
    ("xenia", "female"),
    ("aidar", "male"),
    ("eugene", "male"),
    ("ru-RU-SvetlanaNeural", "female"),
    ("ru-RU-DmitryNeural", "male"),
    ("Microsoft Irina Desktop", "female"),
    ("", "male"),
    (None, "male"),
    ("unknown-voice", "male"),
])
def test_voice_gender(voice, gender):
    assert voice_gender(voice) == gender


def test_unit_voices_and_fallbacks():
    silero = {
        "tts_engine": "silero",
        "silero_speaker": "aidar",
        "unit_voices": {
            "delivery": "baya", "ground": "eugene", "tower": "xenia",
            "radar": "aidar", "approach": "kseniya", "control": "eugene",
        },
    }
    assert controller_gender(silero, "delivery") == "female"
    assert controller_gender(silero, "tower") == "female"
    assert controller_gender(silero, "approach") == "female"
    assert controller_gender(silero, "ground") == "male"
    assert controller_gender(silero, "control") == "male"
    assert speaking_voice(silero, "radar") == "aidar"
    # орган без своей записи — голос по умолчанию
    assert controller_gender(silero, "unknown") == "male"

    edge = {"tts_engine": "edge", "edge_voice": "ru-RU-SvetlanaNeural", "unit_voices": silero["unit_voices"]}
    assert controller_gender(edge, "ground") == "female"   # говорит Светлана, не eugene
    edge["edge_voice"] = "ru-RU-DmitryNeural"
    assert controller_gender(edge, "delivery") == "male"

    assert controller_gender({"tts_engine": "pyttsx3"}, "delivery") == "male"
    assert controller_gender({"tts_engine": "pyttsx3", "pyttsx3_voice": "Irina"}, "tower") == "female"


def test_example_config_matches_voices_and_lenient_readback():
    root = Path(__file__).resolve().parents[1]
    raw = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    assert raw["atc"]["readback_strictness"] == "lenient"
    voice = raw["voice"]
    assert controller_gender(voice, "delivery") == "female"   # baya
    assert controller_gender(voice, "ground") == "male"       # eugene
    assert controller_gender(voice, "tower") == "female"      # xenia
    assert controller_gender(voice, "radar") == "male"        # aidar
    assert controller_gender(voice, "approach") == "male"
    assert controller_gender(voice, "control") == "male"
