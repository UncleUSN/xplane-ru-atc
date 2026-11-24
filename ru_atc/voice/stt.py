"""Распознавание русской речи офлайн: Vosk (лёгкий, быстрый) или faster-whisper (точнее, тяжелее)."""
from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Подсказка для whisper: типичная лексика радиообмена
WHISPER_PROMPT = ("Радиообмен с диспетчером. Шереметьево, Домодедово, Внуково, Пулково, Деливери, Руление, "
                  "Старт, Вышка, Круг, Подход, Москва-Контроль, Санкт-Петербург Контроль. Аэрофлот один два три "
                  "четыре, разрешите запуск, буксировку, руление, к взлёту готов, эшелон три пять ноль, "
                  "ответчик один пять ноль один, на посадочном, полосу освободил, QNH девятьсот девяносто восемь.")


class STTBase:
    name = "none"

    def transcribe(self, audio_int16: np.ndarray) -> str:
        return ""


class VoskSTT(STTBase):
    """Модели: https://alphacephei.com/vosk/models — vosk-model-small-ru-0.22 (45 МБ) или vosk-model-ru-0.42 (1.8 ГБ)."""
    name = "vosk"

    def __init__(self, model_path: str, vocabulary: Optional[list] = None):
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        self.model = Model(model_path)
        # Режим грамматики работает только с «малыми» моделями (small); у больших словарь фиксирован
        self.grammar = json.dumps(vocabulary + ["[unk]"], ensure_ascii=False) if vocabulary else None

    def transcribe(self, audio_int16: np.ndarray) -> str:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self.model, SAMPLE_RATE, self.grammar) if self.grammar else \
            KaldiRecognizer(self.model, SAMPLE_RATE)
        rec.AcceptWaveform(audio_int16.astype(np.int16).tobytes())
        return json.loads(rec.FinalResult()).get("text", "")


class WhisperSTT(STTBase):
    name = "whisper"

    def __init__(self, model: str = "small", device: str = "auto"):
        from ..config import prepare_runtime_caches, whisper_download_root
        # Корень смотрим до prepare: свой HF_HOME не должен подмениться нашим.
        download_root = whisper_download_root()
        prepare_runtime_caches()
        from faster_whisper import WhisperModel
        compute = "int8" if device in ("cpu", "auto") else "float16"
        kwargs = {}
        if download_root is not None:
            download_root.mkdir(parents=True, exist_ok=True)
            kwargs["download_root"] = str(download_root)
        self.model = WhisperModel(model, device=device, compute_type=compute, **kwargs)

    def transcribe(self, audio_int16: np.ndarray) -> str:
        audio = audio_int16.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(audio, language="ru", initial_prompt=WHISPER_PROMPT,
                                            vad_filter=True, beam_size=5)
        return " ".join(s.text.strip() for s in segments)


def make_stt(cfg: dict, extra_words=()) -> STTBase:
    from ..config import resolve_path
    from ..phraseology.vocab import build_vocabulary
    from .download import ensure_vosk_model
    eng = cfg.get("stt_engine", "vosk")
    try:
        if eng == "whisper":
            return WhisperSTT(cfg.get("whisper_model", "small"), cfg.get("whisper_device", "auto"))
        path = ensure_vosk_model(resolve_path(cfg.get("vosk_model_path", "models/vosk-model-small-ru-0.22")))
        path_s = str(path)
        vocab = build_vocabulary(extra_words) if cfg.get("vosk_grammar", False) and "small" in path_s else None
        return VoskSTT(path_s, vocab)
    except Exception as e:
        log.warning("Распознавание речи (%s) недоступно: %s. Используйте ввод текстом.", eng, e)
        return STTBase()


# Запись с микрофона вынесена в audio.py (подбор частоты/каналов, выбор устройства по имени)
from .audio import Recorder  # noqa: E402,F401
