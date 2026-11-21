"""Тесты выбора устройства и записи с подставным модулем sounddevice (без реального звука)."""
import numpy as np
import pytest

from ru_atc.voice.audio import MicError, Recorder, explain_error, resample_to, resolve_device, to_mono


class PortAudioError(Exception):
    pass


class FakeStream:
    def __init__(self, sd, samplerate, channels, dtype, device, callback):
        self.sd, self.sr, self.ch, self.cb = sd, samplerate, channels, callback
        dev = sd.devs[device if device is not None else sd.default_in]
        if dev.get("busy"):
            raise PortAudioError("Error opening InputStream: Device unavailable [PaErrorCode -9985]")
        if samplerate not in dev["rates"]:
            raise PortAudioError("Error opening InputStream: Invalid sample rate [PaErrorCode -9997]")
        if channels not in dev["chans"]:
            raise PortAudioError("Error opening InputStream: Invalid number of channels [PaErrorCode -9998]")
        self.silent = dev.get("silent", False)

    def start(self):
        n = self.sr  # 1 секунда
        t = np.arange(n) / self.sr
        sig = np.zeros(n) if self.silent else 8000 * np.sin(2 * np.pi * 440 * t)
        block = np.repeat(sig[:, None], self.ch, axis=1).astype(np.int16)
        self.cb(block, n, None, None)

    def stop(self):
        pass

    def close(self):
        pass


class FakeSD:
    PortAudioError = PortAudioError

    def __init__(self, devs, default_in=0):
        self.devs = devs
        self.default_in = default_in

    def query_hostapis(self, idx=None):
        apis = [{"name": "MME", "default_input_device": 0, "default_output_device": 3},
                {"name": "Windows DirectSound", "default_input_device": 1, "default_output_device": 3},
                {"name": "Windows WASAPI", "default_input_device": 2, "default_output_device": 3}]
        return apis if idx is None else apis[idx]

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return [self._pub(d) for d in self.devs]
        if device is None:
            device = self.default_in
        return self._pub(self.devs[device])

    @staticmethod
    def _pub(d):
        return {k: v for k, v in d.items() if k not in ("rates", "chans", "busy", "silent")}

    def InputStream(self, **kw):
        return FakeStream(self, **kw)


def dev(name, api, inch, outch, sr, rates, chans, **kw):
    d = {"name": name, "hostapi": api, "max_input_channels": inch, "max_output_channels": outch,
         "default_samplerate": sr, "rates": rates, "chans": chans}
    d.update(kw)
    return d


@pytest.fixture
def sd():
    return FakeSD([
        dev("Микрофон (Acer AHW120 Headset)", 0, 2, 0, 44100, {16000, 44100}, {1, 2}),
        dev("Микрофон (Acer AHW120 Headset)", 1, 2, 0, 44100, {44100}, {1, 2}),
        dev("Микрофон (Acer AHW120 Headset)", 2, 2, 0, 48000, {48000}, {2}),     # WASAPI: только родной формат
        dev("Динамики (Realtek)", 0, 0, 2, 48000, {48000}, {2}),
    ])


def test_resolve_by_name_and_hostapi(sd):
    assert resolve_device("acer", sd=sd) == 0
    assert resolve_device("AHW120", hostapi="wasapi", sd=sd) == 2
    assert resolve_device("acer", hostapi="DirectSound", sd=sd) == 1
    assert resolve_device(None, sd=sd) is None
    assert resolve_device(None, hostapi="WASAPI", sd=sd) == 2
    assert resolve_device("2", sd=sd) == 2
    assert resolve_device("realtek", kind="output", sd=sd) == 3


def test_resolve_errors(sd):
    with pytest.raises(MicError, match="Не найдено устройство"):
        resolve_device("logitech", sd=sd)
    with pytest.raises(MicError, match="индексом 3"):
        resolve_device(3, kind="input", sd=sd)
    with pytest.raises(MicError, match="ни одного устройства"):
        resolve_device(None, sd=FakeSD([dev("Динамики", 0, 0, 2, 48000, {48000}, {2})]))


def test_recorder_falls_back_to_native_rate_and_stereo(sd):
    rec = Recorder("acer", "wasapi", sd=sd)
    rec.start()
    assert (rec.sr, rec.channels) == (48000, 2)
    audio = rec.stop()
    assert audio.dtype == np.int16
    assert abs(audio.size - 16000) <= 2          # 1 с -> 16 кГц
    assert 0.2 < rec.last_peak < 0.3


def test_recorder_direct_16k(sd):
    rec = Recorder(0, sd=sd)
    rec.start()
    assert (rec.sr, rec.channels) == (16000, 1)
    assert rec.stop().size == 16000


def test_recorder_busy_message():
    sd = FakeSD([dev("Mic", 0, 1, 0, 48000, {48000}, {1}, busy=True)])
    rec = Recorder(None, sd=sd)
    with pytest.raises(MicError, match="занят"):
        rec.start()


def test_recorder_silence_detected():
    sd = FakeSD([dev("Mic", 0, 1, 0, 16000, {16000}, {1}, silent=True)])
    rec = Recorder(None, sd=sd)
    rec.start()
    rec.stop()
    assert rec.last_peak == 0.0


def test_explain_privacy():
    assert "Конфиденциальность" in explain_error(Exception("Unanticipated host error [PaErrorCode -9999]"))
    assert "не найдено" in explain_error(Exception("Error querying device -1 [PaErrorCode -9996] Invalid device"))


def test_resample_and_mono():
    x = np.sin(np.linspace(0, 100, 48000)).astype(np.float32)
    assert resample_to(x, 48000, 16000).size == 16000
    assert resample_to(x, 44100, 16000).size == pytest.approx(17415, abs=2)
    st = np.stack([np.ones(10), np.zeros(10)], axis=1)
    assert np.allclose(to_mono(st), 0.5)
