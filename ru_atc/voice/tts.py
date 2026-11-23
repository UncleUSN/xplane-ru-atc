"""Синтез русской речи: Silero TTS (офлайн, torch) -> pyttsx3 (SAPI5 Windows) -> edge-tts (онлайн) -> только текст."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from .voices import speaking_voice

log = logging.getLogger(__name__)


class TTSBase:
    name = "none"
    sample_rate = 48000

    def synth(self, text: str, voice: Optional[str] = None):  # -> np.ndarray float32 | None
        return None


def _prepare_torch_cache() -> None:
    """В собранном exe кеш torch.hub лежит рядом с программой, а не в профиле пользователя."""
    import os
    import sys
    if os.environ.get("TORCH_HOME"):
        return
    if not getattr(sys, "frozen", False):
        return
    from ..config import app_root
    cache = app_root() / "models" / "torch"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["TORCH_HOME"] = str(cache)


class SileroTTS(TTSBase):
    """https://github.com/snakers4/silero-models — модель v4_ru (голоса aidar, baya, kseniya, xenia, eugene).
    При первом запуске скачивается через torch.hub (~40 МБ) и кешируется."""
    name = "silero"

    def __init__(self, speaker: str = "aidar", sample_rate: int = 48000, device: str = "cpu"):
        _prepare_torch_cache()
        import torch  # noqa
        self.torch = torch
        self.model, _ = torch.hub.load(repo_or_dir="snakers4/silero-models", model="silero_tts",
                                       language="ru", speaker="v4_ru", trust_repo=True)
        self.model.to(torch.device(device))
        self.speaker = speaker
        self.sample_rate = sample_rate

    def synth(self, text: str, voice: Optional[str] = None):
        audio = self.model.apply_tts(text=text, speaker=voice or self.speaker, sample_rate=self.sample_rate,
                                     put_accent=True, put_yo=True)
        return audio.numpy()


class Pyttsx3TTS(TTSBase):
    """Голоса Windows (SAPI5). Для русского нужен установленный русский голос (напр. Microsoft Irina)."""
    name = "pyttsx3"

    def __init__(self):
        import pyttsx3
        self.engine = pyttsx3.init()
        for v in self.engine.getProperty("voices"):
            if "ru" in (str(v.languages) + v.name + v.id).lower() or "irina" in v.name.lower():
                self.engine.setProperty("voice", v.id)
                break
        self.engine.setProperty("rate", 185)

    def speak_direct(self, text: str):
        self.engine.say(text)
        self.engine.runAndWait()


class EdgeTTS(TTSBase):
    """Microsoft Edge online TTS (нужен интернет). Требует edge-tts и miniaudio для декодирования mp3."""
    name = "edge"

    def __init__(self, voice: str = "ru-RU-DmitryNeural"):
        import edge_tts  # noqa
        import miniaudio  # noqa
        self.voice = voice
        self.sample_rate = 24000

    def synth(self, text: str, voice: Optional[str] = None):
        import asyncio
        import edge_tts
        import miniaudio
        import numpy as np

        async def run():
            data = b""
            async for chunk in edge_tts.Communicate(text, self.voice).stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return data
        mp3 = asyncio.run(run())
        dec = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1,
                               sample_rate=self.sample_rate)
        return np.frombuffer(dec.samples, dtype=np.float32)


def make_tts(cfg: dict) -> TTSBase:
    order = [cfg.get("tts_engine", "silero"), "silero", "pyttsx3", "edge"]
    seen = set()
    for name in order:
        if name in seen or name == "none":
            if name == "none":
                break
            continue
        seen.add(name)
        try:
            if name == "silero":
                return SileroTTS(cfg.get("silero_speaker", "aidar"))
            if name == "pyttsx3":
                return Pyttsx3TTS()
            if name == "edge":
                return EdgeTTS(cfg.get("edge_voice", "ru-RU-DmitryNeural"))
        except Exception as e:
            log.warning("TTS %s недоступен: %s", name, e)
    log.warning("Синтез речи отключён — сообщения диспетчера будут только текстом")
    return TTSBase()


class Speaker:
    """Очередь воспроизведения (диспетчер не перебивает сам себя и ждёт, пока отпущена тангента)."""

    def __init__(self, tts: TTSBase, cfg: dict, is_ptt_down: Callable[[], bool] = lambda: False):
        self.tts = tts
        self.cfg = cfg
        self.q: "queue.Queue" = queue.Queue()
        self.is_ptt_down = is_ptt_down
        self.busy = False
        threading.Thread(target=self._run, name="tts", daemon=True).start()

    def say(self, text: str, unit_type: str = "control"):
        self.q.put((text, unit_type))

    def _run(self):
        import time
        while True:
            text, unit_type = self.q.get()
            while self.is_ptt_down():
                time.sleep(0.1)
            self.busy = True
            try:
                self._speak(text, unit_type)
            except Exception as e:
                log.warning("Ошибка синтеза/воспроизведения: %s", e)
            finally:
                self.busy = False

    def _speak(self, text: str, unit_type: str):
        if isinstance(self.tts, Pyttsx3TTS):
            self.tts.speak_direct(text)
            return
        # Тот же выбор, что и у портрета в окне: unit_voices, иначе silero_speaker.
        voice = speaking_voice(self.cfg, unit_type, "silero") if self.tts.name == "silero" else None
        audio = self.tts.synth(text, voice)
        if audio is None:
            return
        sr = self.tts.sample_rate
        if self.cfg.get("radio_effect", True):
            from .radio_fx import radio_effect
            audio = radio_effect(audio, sr, float(self.cfg.get("radio_noise", 0.015)))
        import sounddevice as sd
        if not hasattr(self, "_out_dev"):
            from .audio import resolve_device
            try:
                self._out_dev = resolve_device(self.cfg.get("output_device"), "output", self.cfg.get("host_api"))
            except Exception as e:
                log.error("Устройство вывода: %s — использую устройство по умолчанию", e)
                self._out_dev = None
        from .audio import play_audio
        play_audio(audio, sr, device=self._out_dev)
