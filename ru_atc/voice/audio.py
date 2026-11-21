"""Выбор аудиоустройств и надёжная запись с микрофона (Windows: MME / DirectSound / WASAPI).

* Устройство задаётся индексом ИЛИ подстрокой имени (без учёта регистра), плюс предпочтение host API.
* Если 16 кГц/моно не поддерживается — открываем на родной частоте устройства и/или с его числом
  каналов, затем сводим в моно и передискретизируем в 16 кГц для распознавания.
* Понятные русские сообщения об ошибках (нет устройства, занято, запрет доступа к микрофону).
"""
from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

log = logging.getLogger(__name__)

TARGET_SR = 16000
HOSTAPI_ALIASES = {"wasapi": "wasapi", "mme": "mme", "directsound": "directsound", "ds": "directsound",
                   "wdm": "wdm-ks", "wdm-ks": "wdm-ks", "asio": "asio"}

PRIVACY_HINT = ("Проверьте доступ к микрофону: Параметры Windows → Конфиденциальность и защита → Микрофон → "
                "включите «Доступ к микрофону» и «Разрешить классическим приложениям доступ к микрофону».")


class MicError(RuntimeError):
    """Ошибка микрофона с понятным русским текстом."""


def _sd():
    try:
        import sounddevice as sd
        return sd
    except OSError as e:  # нет PortAudio
        raise MicError(f"Библиотека звука PortAudio не найдена ({e}). Переустановите: pip install --force-reinstall sounddevice")
    except ImportError:
        raise MicError("Не установлен пакет sounddevice: pip install sounddevice")


def _hostapi_name(sd, dev: Dict[str, Any]) -> str:
    try:
        return sd.query_hostapis(dev["hostapi"])["name"]
    except Exception:
        return "?"


def list_devices(kind: str = "input", sd=None) -> List[Dict[str, Any]]:
    """[{index, name, hostapi, channels, default_samplerate}] для устройств ввода/вывода."""
    sd = sd or _sd()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d.get(key, 0) > 0:
            out.append({"index": i, "name": d["name"], "hostapi": _hostapi_name(sd, d),
                        "channels": int(d[key]), "default_samplerate": float(d.get("default_samplerate") or 0)})
    return out


def _hostapi_matches(api_name: str, pref: Optional[str]) -> bool:
    if not pref:
        return True
    p = HOSTAPI_ALIASES.get(pref.strip().lower(), pref.strip().lower())
    return p in api_name.lower().replace(" ", "")  # "Windows WASAPI", "MME", "Windows DirectSound"


def resolve_device(spec: Union[None, int, str], kind: str = "input", hostapi: Optional[str] = None,
                   sd=None) -> Optional[int]:
    """Индекс устройства по индексу/подстроке имени (+ предпочтение host API). None = устройство по умолчанию."""
    sd = sd or _sd()
    devs = list_devices(kind, sd)
    if not devs:
        raise MicError("В системе не найдено ни одного устройства " +
                       ("записи (микрофона). Подключите гарнитуру и проверьте Панель управления → Звук → Запись."
                        if kind == "input" else "воспроизведения."))
    if spec is None or (isinstance(spec, str) and spec.strip() == ""):
        if hostapi:   # устройство по умолчанию выбранного host API
            for api_idx, api in enumerate(sd.query_hostapis()):
                if _hostapi_matches(api["name"], hostapi):
                    key = "default_input_device" if kind == "input" else "default_output_device"
                    idx = api.get(key, -1)
                    if idx is not None and idx >= 0:
                        log.info("Аудио (%s): устройство по умолчанию %s: [%d] %s", kind, api["name"], idx,
                                 sd.query_devices(idx)["name"])
                        return int(idx)
        return None
    if isinstance(spec, int) or (isinstance(spec, str) and spec.strip().isdigit()):
        idx = int(spec)
        match = [d for d in devs if d["index"] == idx]
        if not match:
            raise MicError(f"Устройство с индексом {idx} не найдено или не является устройством "
                           f"{'записи' if kind == 'input' else 'вывода'}. Список: python tools/mictest.py --list")
        log.info("Аудио (%s): [%d] %s (%s)", kind, idx, match[0]["name"], match[0]["hostapi"])
        return idx
    needle = str(spec).strip().lower()
    cands = [d for d in devs if needle in d["name"].lower()]
    if not cands:
        names = "; ".join(f"[{d['index']}] {d['name']}" for d in devs)
        raise MicError(f"Не найдено устройство, содержащее «{spec}». Доступные: {names}")
    pref = [d for d in cands if _hostapi_matches(d["hostapi"], hostapi)] if hostapi else cands
    chosen = (pref or cands)[0]
    if hostapi and not pref:
        log.warning("Устройство «%s» с host API %s не найдено, беру %s", spec, hostapi, chosen["hostapi"])
    log.info("Аудио (%s): [%d] %s (%s, %d кан., %.0f Гц)", kind, chosen["index"], chosen["name"],
             chosen["hostapi"], chosen["channels"], chosen["default_samplerate"])
    return chosen["index"]


def resample_to(audio: np.ndarray, sr_from: int, sr_to: int = TARGET_SR) -> np.ndarray:
    """Передискретизация (scipy.signal.resample_poly, иначе линейная интерполяция). float32 на выходе."""
    x = np.asarray(audio, dtype=np.float32).flatten()
    if sr_from == sr_to or x.size == 0:
        return x
    try:
        from scipy.signal import resample_poly
        fr = Fraction(sr_to, int(sr_from)).limit_denominator(1000)
        return resample_poly(x, fr.numerator, fr.denominator).astype(np.float32)
    except ImportError:
        n = int(round(x.size * sr_to / sr_from))
        return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def to_mono(frames: np.ndarray) -> np.ndarray:
    a = np.asarray(frames)
    if a.ndim == 2 and a.shape[1] > 1:
        return a.astype(np.float32).mean(axis=1)
    return a.astype(np.float32).flatten()


def explain_error(e: Exception, device_desc: str = "") -> str:
    msg = str(e)
    low = msg.lower()
    where = f" ({device_desc})" if device_desc else ""
    if "-9985" in msg or "unavailable" in low or "busy" in low or "in use" in low:
        return (f"Микрофон занят другим приложением{where} (Discord, Teams, браузер или эксклюзивный режим). "
                "Закройте его или в свойствах устройства записи → Дополнительно снимите «Разрешить приложениям "
                "использовать устройство в монопольном режиме».")
    if "-9999" in msg or "unanticipated host error" in low or "access" in low or "denied" in low:
        return f"Windows не дал доступ к микрофону{where}. " + PRIVACY_HINT
    if "-9996" in msg or "invalid device" in low or "no default" in low:
        return (f"Устройство записи не найдено{where}. Подключите гарнитуру, назначьте её устройством записи по "
                "умолчанию (Параметры → Система → Звук → Ввод) или укажите voice.input_device в config.yaml.")
    if "-9997" in msg or "sample rate" in low:
        return f"Устройство не поддерживает частоту дискретизации{where}: {msg}"
    if "-9998" in msg or "channels" in low:
        return f"Устройство не поддерживает число каналов{where}: {msg}"
    return f"Ошибка микрофона{where}: {msg}"


class Recorder:
    """Запись с микрофона, пока нажата тангента. Возвращает int16 моно 16 кГц."""

    def __init__(self, device: Union[None, int, str] = None, hostapi: Optional[str] = None, sd=None):
        self.spec = device
        self.hostapi = hostapi
        self._sd = sd
        self.frames: List[np.ndarray] = []
        self.stream = None
        self.sr = TARGET_SR
        self.channels = 1
        self.device_index: Optional[int] = None
        self._resolved = False
        self.last_peak = 0.0

    @property
    def sd(self):
        if self._sd is None:
            self._sd = _sd()
        return self._sd

    def describe(self) -> str:
        try:
            d = self.sd.query_devices(self.device_index if self.device_index is not None else None, "input")
            return f"[{self.device_index if self.device_index is not None else 'по умолч.'}] {d['name']}"
        except Exception:
            return str(self.spec or "устройство по умолчанию")

    def _candidates(self) -> List[Tuple[int, int]]:
        sd = self.sd
        try:
            info = sd.query_devices(self.device_index, "input")
        except Exception as e:
            raise MicError(explain_error(e, str(self.spec or "по умолчанию")))
        if int(info.get("max_input_channels", 0)) < 1:
            raise MicError(f"«{info['name']}» не является устройством записи. Список: python tools/mictest.py --list")
        native = int(round(float(info.get("default_samplerate") or 0))) or 48000
        maxch = max(1, int(info.get("max_input_channels", 1)))
        cands = [(TARGET_SR, 1), (native, 1), (native, min(maxch, 2)), (native, maxch), (48000, 1), (44100, 1)]
        seen, out = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _resolve(self):
        if not self._resolved:
            self.device_index = resolve_device(self.spec, "input", self.hostapi, self.sd)
            self._resolved = True

    def start(self):
        sd = self.sd
        self._resolve()
        self.frames = []

        def cb(indata, frames, t, status):
            self.frames.append(indata.copy())

        last_err: Optional[Exception] = None
        for sr, ch in self._candidates():
            try:
                try:
                    sd.check_input_settings(device=self.device_index, samplerate=sr, channels=ch, dtype="int16")
                except AttributeError:
                    pass
                stream = sd.InputStream(samplerate=sr, channels=ch, dtype="int16", device=self.device_index,
                                        callback=cb)
                stream.start()
            except Exception as e:  # PortAudioError / ValueError
                last_err = e
                log.debug("Микрофон: %d Гц / %d кан. не подошло: %s", sr, ch, e)
                continue
            self.stream, self.sr, self.channels = stream, sr, ch
            if (sr, ch) != (TARGET_SR, 1):
                log.info("Микрофон открыт на %d Гц, %d кан. (сведение в моно и пересчёт в 16 кГц)", sr, ch)
            return
        raise MicError(explain_error(last_err or RuntimeError("не удалось открыть"), self.describe()))

    def stop(self) -> np.ndarray:
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            finally:
                self.stream = None
        if not self.frames:
            return np.zeros(0, dtype=np.int16)
        mono = to_mono(np.concatenate(self.frames, axis=0))
        audio = resample_to(mono, self.sr, TARGET_SR)
        self.last_peak = float(np.max(np.abs(audio))) / 32768.0 if audio.size else 0.0
        if audio.size > TARGET_SR * 0.3 and self.last_peak == 0.0:
            log.warning("Микрофон пишет абсолютную тишину — вероятно, запрещён доступ. %s", PRIVACY_HINT)
        return np.clip(audio, -32768, 32767).astype(np.int16)


def play_audio(audio: np.ndarray, sr: int, device=None, timeout_extra: float = 1.5) -> None:
    """Проигрывает звук на устройстве в его родной частоте и никогда не зависает.

    Некоторые USB-гарнитуры под Windows (особенно через WASAPI) молча принимают
    «чужую» частоту, но поток так и не завершается, и sd.wait() висит вечно.
    Поэтому: всегда пересчитываем в default_samplerate устройства, ждём с таймаутом
    и принудительно останавливаем поток.
    """
    import time
    sd = _sd()
    data = np.asarray(audio, dtype=np.float32)
    if data.dtype != np.float32:
        data = data.astype(np.float32)
    try:
        native = int(sd.query_devices(device, "output")["default_samplerate"])
    except Exception:
        native = sr
    if native and native != sr:
        data = resample_to(data, sr, native).astype(np.float32)
        sr = native
    duration = len(data) / float(sr) if sr else 0.0
    sd.play(data, sr, device=device)
    deadline = time.monotonic() + duration + timeout_extra
    try:
        while time.monotonic() < deadline:
            stream = sd.get_stream()
            if stream is None or not stream.active:
                return
            time.sleep(0.05)
        log.warning("Воспроизведение не завершилось само за %.1f с — останавливаю поток (устройство: %s)",
                    duration + timeout_extra, device)
    except Exception:
        time.sleep(max(0.0, deadline - time.monotonic()))
    finally:
        try:
            sd.stop()
        except Exception:
            pass
