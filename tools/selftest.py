"""Самопроверка голоса на вашем ПК: список аудиоустройств, синтез -> распознавание -> разбор фраз.

Запуск:  python tools/selftest.py            (по config.yaml)
         python tools/selftest.py --play     (ещё и проиграть фразу диспетчера с радиоэффектом)
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ru_atc.config import load_config  # noqa: E402
from ru_atc.phraseology.parser import parse  # noqa: E402

PHRASES = [
    ("Шереметьево Деливери, Аэрофлот один два три четыре, стоянка двадцать, прошу разрешение до Пулково", "request_clearance"),
    ("набор шесть тысяч футов, ответчик один пять ноль один, Аэрофлот один два три четыре", "readback"),
    ("Аэрофлот один два три четыре, разрешите буксировку и запуск", "request_push_start"),
    ("разрешите руление", "request_taxi"),
    ("на предварительном, к взлёту готов", "ready_departure"),
    ("Москва Контроль, Аэрофлот один два три четыре, добрый день, эшелон сто двадцать в наборе эшелона сто пятьдесят", "report_airborne"),
    ("занял эшелон три три ноль", "report_level"),
    ("на посадочном, вэ пэ пэ двадцать восемь правая", "report_established"),
    ("полосу освободил, разрешите рулить на стоянку", "request_taxi_in"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config")
    ap.add_argument("--play", action="store_true")
    a = ap.parse_args()
    cfg = load_config(a.config)
    vc = cfg["voice"]
    try:
        import sounddevice as sd
        print("Аудиоустройства:\n", sd.query_devices())
    except Exception as e:
        print("sounddevice недоступен:", e)
    from ru_atc.voice.stt import make_stt
    from ru_atc.voice.tts import make_tts
    tts = make_tts(vc)
    stt = make_stt(vc)
    print(f"TTS: {tts.name}, STT: {stt.name}")
    if tts.name not in ("silero", "edge") or stt.name == "none":
        print("Для автопроверки нужен Silero/edge TTS и Vosk/Whisper STT.")
        return
    ok = 0
    for text, intent in PHRASES:
        audio = tts.synth(text, None)
        n = int(len(audio) * 16000 / tts.sample_rate)
        a16 = (np.clip(np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio), -1, 1) * 32767).astype(np.int16)
        heard = stt.transcribe(a16)
        m = parse(heard)
        good = m.intent == intent
        ok += good
        print(f"{'OK ' if good else 'BAD'} {m.intent:20} {m.slots}  <- «{heard}»")
    print(f"Итого: {ok}/{len(PHRASES)}")
    if a.play:
        import sounddevice as sd
        from ru_atc.voice.radio_fx import radio_effect
        audio = tts.synth("Аэрофлот один два три четыре, Шереметьево-Старт, ветер двести пятьдесят градусов "
                          "пять метров, вэ пэ пэ двадцать четыре центральная, взлёт разрешаю", None)
        sd.play(radio_effect(audio, tts.sample_rate), tts.sample_rate)
        sd.wait()


if __name__ == "__main__":
    main()
