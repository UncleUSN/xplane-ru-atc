"""Проверка микрофона: список устройств, запись 3 с, уровень, воспроизведение, распознавание Vosk.

  python tools/mictest.py --list                      список устройств записи и вывода
  python tools/mictest.py                             записать с устройства по умолчанию
  python tools/mictest.py --device acer               по части имени (без учёта регистра)
  python tools/mictest.py --device 5 --hostapi WASAPI
  python tools/mictest.py --device acer --vosk        + распознать (модель из config.yaml)
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ru_atc.voice.audio import MicError, Recorder, list_devices, resolve_device  # noqa: E402


def print_devices():
    for kind, title in (("input", "УСТРОЙСТВА ЗАПИСИ (микрофоны)"), ("output", "УСТРОЙСТВА ВЫВОДА")):
        print(f"\n{title}:")
        print(f"{'№':>4}  {'Host API':<22} {'Кан.':>4} {'Гц':>7}  Имя")
        for d in list_devices(kind):
            print(f"{d['index']:>4}  {d['hostapi']:<22} {d['channels']:>4} {d['default_samplerate']:>7.0f}  {d['name']}")
    import sounddevice as sd
    try:
        di, do = sd.default.device
        print(f"\nПо умолчанию: запись [{di}], вывод [{do}]")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Проверка микрофона для RU ATC")
    ap.add_argument("--list", action="store_true", help="только показать устройства")
    ap.add_argument("--device", help="индекс или часть имени микрофона")
    ap.add_argument("--output", help="индекс или часть имени устройства вывода")
    ap.add_argument("--hostapi", help="WASAPI | MME | DirectSound")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--vosk", action="store_true", help="распознать запись Vosk")
    ap.add_argument("-c", "--config")
    a = ap.parse_args()
    try:
        print_devices()
        if a.list:
            return
        rec = Recorder(a.device, a.hostapi)
        rec._resolve()
        print(f"\nМикрофон: {rec.describe()}")
        input(f"Нажмите Enter и говорите {a.seconds:.0f} с (например: «Шереметьево-Деливери, Аэрофлот 1234, "
              "прошу разрешение до Пулково»)...")
        rec.start()
        print(f"Запись: {rec.sr} Гц, {rec.channels} кан.")
        time.sleep(a.seconds)
        audio = rec.stop()
    except MicError as e:
        print(f"\nОШИБКА: {e}")
        sys.exit(1)
    peak = rec.last_peak
    rms = float(np.sqrt(np.mean((audio.astype(np.float32) / 32768) ** 2))) if audio.size else 0.0
    bar = "#" * int(min(1.0, peak) * 40)
    print(f"Записано {audio.size / 16000:.1f} с. Пик: {peak:.3f} [{bar:<40}]  RMS: {rms:.4f}")
    if peak == 0.0:
        print("Абсолютная тишина: скорее всего Windows запрещает доступ к микрофону или выбран не тот вход.\n"
              "Параметры → Конфиденциальность и защита → Микрофон → разрешите классическим приложениям.")
    elif peak < 0.02:
        print("Очень тихо: увеличьте уровень микрофона (Параметры → Система → Звук → устройство ввода → Громкость) "
              "или проверьте, что выбран микрофон гарнитуры.")
    else:
        print("Уровень нормальный.")
    if not a.no_play and audio.size:
        import sounddevice as sd
        from ru_atc.voice.audio import resample_to
        from ru_atc.voice.audio import play_audio
        out = None
        for spec in (a.output, a.device):
            if spec is None:
                continue
            try:
                out = resolve_device(spec, "output", a.hostapi)
                break
            except Exception:
                pass
        print(f"Воспроизведение… (устройство вывода: {out if out is not None else 'по умолчанию'})")
        play_audio(audio.astype(np.float32) / 32768, 16000, device=out)
    if a.vosk and audio.size:
        from ru_atc.config import load_config
        from ru_atc.phraseology.parser import parse
        from ru_atc.voice.stt import make_stt
        stt = make_stt(load_config(a.config)["voice"])
        if stt.name == "none":
            print("Vosk недоступен (нет модели в models/?).")
            return
        text = stt.transcribe(audio)
        m = parse(text)
        print(f"Распознано: «{text}»\nНамерение: {m.intent}  {m.slots}")


if __name__ == "__main__":
    main()
