"""Связка: источник данных -> автомат фаз/контроллер -> речь/UI."""
from __future__ import annotations

import argparse
import logging
import queue
import random
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import __version__
from .airspace import Airspace
from .config import load_config, resolve_path
from .controller import Controller
from .events import Hint, PilotMessage, Transmission
from .phases import PHASE_RU

log = logging.getLogger("ru_atc")


def setup_logging(log_dir: str, verbose: bool = False) -> Path:
    d = resolve_path(log_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"atc_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")],
    )
    return path


def make_source(cfg, controller, airspace, demo: bool):
    sc = cfg["sim"]
    src = sc.get("source", "webapi")
    if src == "mock" or demo:
        from .sources.mock import MockFlight, MockSource
        fp = cfg["flight_plan"]
        flight = MockFlight(airspace.airports[fp["departure"]], airspace.airports[fp["arrival"]], controller)
        return MockSource(flight, float(sc.get("mock_time_scale", 4.0)))
    if src == "udp":
        from .sources.udp import UdpSource
        return UdpSource(sc.get("host", "127.0.0.1"), int(sc.get("udp_port", 49000)),
                         int(sc.get("udp_listen_port", 49010)), use_zibo=sc.get("use_zibo_datarefs", True))
    from .sources.webapi import WebApiSource
    return WebApiSource(sc.get("host", "localhost"), int(sc.get("webapi_port", 8086)),
                        sc.get("use_zibo_datarefs", True), sc.get("webapi_version", "auto"))


class App:
    def __init__(self, cfg: dict, demo: bool = False, no_voice: bool = False):
        self.cfg = cfg
        self.airspace = Airspace.load(cfg["airports_file"], cfg["airspace_file"])
        self.ctl = Controller(cfg, self.airspace, random.Random())
        self.source = make_source(cfg, self.ctl, self.airspace, demo)
        self.ui_q: "queue.Queue" = queue.Queue()
        self.lock = threading.Lock()
        self.voice_on = cfg["voice"].get("enabled", True) and not no_voice
        self.speaker = None
        self.stt = None
        self.recorder = None
        self.ptt = None
        self.pilot_bot = None
        if demo:
            from .sources.mock import ScriptedPilot
            self.pilot_bot = ScriptedPilot(self.ctl, self.source.flight)
        # План полёта из FMC Zibo / .fms. В mock-режиме не используется (маршрут демо берётся из config.yaml)
        self.fp_provider = None
        if not demo and cfg["sim"].get("source") != "mock":
            from .flightplan import FlightPlanProvider
            prov = FlightPlanProvider(cfg, on_change=self._on_plan)
            if prov.mode not in ("config", "off", "none"):
                self.fp_provider = prov

    def _on_plan(self, plan):
        with self.lock:
            msgs = self.ctl.apply_plan(plan)
        self.ui_q.put(("info", f"План полёта ({', '.join(sorted(set(v.split(' ')[0] for v in plan.sources.values())))}): "
                               f"{plan.summary()}"))
        for m in msgs:
            self.ui_q.put(("hint_text", m))

    # ---------- голос ----------
    def init_voice(self):
        if not self.voice_on:
            return
        vc = self.cfg["voice"]
        from .voice.ptt import PTT
        from .voice.stt import Recorder, make_stt
        from .voice.tts import Speaker, make_tts
        # 1) Микрофон и тангента — сразу, до загрузки тяжёлых моделей
        if self.pilot_bot is None:
            self.recorder = Recorder(vc.get("input_device"), vc.get("host_api"))
            try:
                self.recorder._resolve()
                self.ui_q.put(("info", f"Микрофон: {self.recorder.describe()}"))
            except Exception as e:
                log.error("Микрофон: %s", e)
                self.ui_q.put(("hint_text", f"Микрофон: {e}"))
            try:
                self.ptt = PTT(vc.get("ptt_key"), vc.get("ptt_joystick"), self._ptt_down, self._ptt_up)
                self.ptt.start()
                self.ui_q.put(("info", f"Тангента: клавиша '{vc.get('ptt_key')}'"
                                       + (f", джойстик {vc.get('ptt_joystick')}" if vc.get("ptt_joystick") else "")))
            except Exception as e:
                log.exception("Тангента")
                self.ui_q.put(("hint_text", f"Тангента не запустилась: {e}"))
        # 2) Синтез речи
        self.ui_q.put(("info", "Загрузка синтеза речи…"))
        try:
            self.speaker = Speaker(make_tts(vc), vc, is_ptt_down=lambda: bool(self.ptt and self.ptt.down))
        except Exception as e:
            log.exception("Синтез речи")
            self.ui_q.put(("hint_text", f"Синтез речи не загрузился: {e}"))
        # 3) Распознавание (большая модель Vosk грузится до минуты)
        if self.pilot_bot is None:
            self.ui_q.put(("info", f"Загрузка распознавания речи ({vc.get('stt_engine')}: "
                                   f"{vc.get('vosk_model_path') if vc.get('stt_engine', 'vosk') == 'vosk' else vc.get('whisper_model')})…"))
            t0 = time.time()
            try:
                from .phraseology.callsign import alias_tokens
                extra = [self.cfg["callsign"]["spoken"]] + list(alias_tokens()) + \
                    [u.callsign for u in self.airspace.all_units()] + \
                    [a.name for a in self.airspace.airports.values()] + [a.name_gen for a in self.airspace.airports.values()]
                self.stt = make_stt(vc, extra)
                if getattr(self.stt, "name", "") == "none":
                    self.ui_q.put(("hint_text", "Распознавание недоступно: модель не найдена. Проверьте voice.vosk_model_path "
                                                "(папка должна содержать am/, conf/, graph/)."))
                else:
                    self.ui_q.put(("info", f"Распознавание готово за {time.time() - t0:.0f} с"))
            except Exception as e:
                log.exception("Распознавание")
                self.ui_q.put(("hint_text", f"Распознавание не загрузилось: {e}"))
        self.ui_q.put(("info", "Голос готов"))

    def _ptt_down(self):
        self.ui_q.put(("ptt", True))
        log.info("Тангента нажата")
        if self.recorder is None:
            self.ui_q.put(("hint_text", "Микрофон ещё не инициализирован"))
            return
        try:
            self.recorder.start()
        except Exception as e:
            log.error("Микрофон: %s", e)
            self.ui_q.put(("hint_text", f"Микрофон недоступен: {e}"))

    def _ptt_up(self):
        self.ui_q.put(("ptt", False))
        if self.recorder is None:
            return
        try:
            audio = self.recorder.stop()
        except Exception as e:
            log.error("Остановка записи: %s", e)
            return
        log.info("Тангента отпущена: записано %.1f с, пик %.3f", audio.size / 16000, self.recorder.last_peak)
        if audio.size < 16000 * 0.3:
            self.ui_q.put(("info", "Слишком короткая передача — держите тангенту, пока говорите"))
            return
        if self.recorder.last_peak == 0.0:
            from .voice.audio import PRIVACY_HINT
            self.ui_q.put(("hint_text", "Микрофон записывает тишину. " + PRIVACY_HINT))
            return
        if self.recorder.last_peak < 0.01:
            self.ui_q.put(("info", f"Очень тихий сигнал микрофона (пик {self.recorder.last_peak:.3f}) — "
                                   "увеличьте уровень записи в настройках звука Windows"))
        threading.Thread(target=self._recognize, args=(audio,), daemon=True).start()

    def _recognize(self, audio):
        if self.stt is None:
            self.ui_q.put(("info", "Распознавание ещё загружается — повторите через несколько секунд"))
            return
        text = self.stt.transcribe(audio)
        log.info("Распознано: %r", text)
        if not text.strip():
            self.ui_q.put(("info", "Ничего не распознано"))
            return
        self.pilot_says(text)

    # ---------- обмен ----------
    def pilot_says(self, text: str):
        with self.lock:
            s = self.source.snapshot()
            evs = self.ctl.on_pilot(text, s)
        self._dispatch(evs)

    def _dispatch(self, evs: List):
        for e in evs:
            if isinstance(e, Transmission):
                log.info("ATC [%s %.3f]: %s", e.unit.callsign, e.unit.freq, e.display)
                self.ui_q.put(("atc", e))
                if self.speaker:
                    self.speaker.say(e.speech, e.unit.type)
            elif isinstance(e, PilotMessage):
                log.info("PILOT: %s  (norm=%r intent=%s)", e.text, e.norm, e.intent)
                self.ui_q.put(("pilot", e))
            elif isinstance(e, Hint):
                log.info("HINT: %s", e.text)
                self.ui_q.put(("hint", e))

    def loop(self, stop: threading.Event):
        while not stop.is_set():
            with self.lock:
                s = self.source.snapshot()
                evs = self.ctl.update(s)
            self._dispatch(evs)
            if self.pilot_bot is not None and not (self.speaker and self.speaker.busy):
                for txt in self.pilot_bot.step(s):
                    self.pilot_says(txt)
            self.ui_q.put(("state", (s, self.ctl.status(), getattr(self.source, "error", None))))
            time.sleep(0.5)

    def _load_navdata(self) -> None:
        from .navdata.service import prepare_navdata

        def progress(message: str, fraction: float) -> None:
            self.ui_q.put(("nav_progress", f"{message} ({int(fraction * 100)}%)"))

        try:
            result = prepare_navdata(self.cfg, progress)
        except Exception:
            log.exception("Навигационные данные")
            self.ui_q.put(("info", "Навигационные данные X-Plane не собраны, остаются yaml."))
            return
        with self.lock:
            notes = result.apply(self.airspace, self.ctl)
        for note in notes:
            self.ui_q.put(("info", note))

    def start(self):
        self.source.start()
        if self.fp_provider:
            self.fp_provider.start()
        self.stop_ev = threading.Event()
        threading.Thread(target=self.loop, args=(self.stop_ev,), daemon=True).start()
        threading.Thread(target=self.init_voice, daemon=True).start()
        threading.Thread(target=self._load_navdata, name="navdata", daemon=True).start()

    def stop(self):
        self.stop_ev.set()
        self.source.stop()
        if self.fp_provider:
            self.fp_provider.stop()
        nav = getattr(self.ctl, "nav", None)
        if nav is not None:
            nav.close()


def smoke_check() -> int:
    """Импорт тяжёлых библиотек собранного exe. Код 0 — всё открылось.

    Окно у сборки без консоли, stdout может быть None, поэтому отчёт ещё
    пишется в RU_ATC_SMOKE_REPORT (его задаёт installer/build.ps1) после
    каждого шага: если импорт зависнет, в файле останется имя модуля.

    ``import sounddevice`` сразу вызывает ``Pa_Initialize()`` и на машине без
    звуковой карты (бегун GitHub) зависает на перечислении устройств. Здесь
    DLL только загружается: ``Pa_GetVersion`` инициализации не требует.
    """
    import ctypes
    import os
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    lines: List[str] = []
    rc = 0
    report = os.environ.get("RU_ATC_SMOKE_REPORT")

    def flush() -> None:
        if not report:
            return
        dest = Path(report)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def ok(text: str) -> None:
        lines.append(f"ок {text}")
        flush()

    def fail(text: str) -> None:
        nonlocal rc
        rc = 1
        lines.append(f"ошибка {text}")
        flush()

    def step(name: str):
        lines.append(f"… {name}")
        flush()
        try:
            __import__(name)
        except Exception as exc:
            fail(f"{name}: {type(exc).__name__}: {exc}")
        else:
            lines.pop()
            ok(name)

    for name in (
        "yaml",
        "numpy",
        "_sounddevice",
        "_sounddevice_data",
        "vosk",
        "torch",
        "omegaconf",
        "scipy.signal",
        "keyboard",
        "pygame",
        "pyttsx3",
        "tkinter",
    ):
        step(name)
    try:
        lines.append("… portaudio dll")
        flush()
        import _sounddevice_data
        dll_path = Path(next(iter(_sounddevice_data.__path__))) / "portaudio-binaries" / "libportaudio64bit.dll"
        if not dll_path.is_file():
            fail(f"нет {dll_path}")
        else:
            lib = ctypes.CDLL(str(dll_path))
            lib.Pa_GetVersion.restype = ctypes.c_int
            lines.pop()
            ok(f"portaudio {dll_path.name} Pa_GetVersion={int(lib.Pa_GetVersion())}")
    except Exception as exc:
        fail(f"portaudio: {type(exc).__name__}: {exc}")
    try:
        from .avatars import avatar_file
        for gender in ("female", "male"):
            path = avatar_file(gender)
            if path is None:
                fail(f"портрет {gender}")
            else:
                ok(f"портрет {path.name}")
    except Exception as exc:
        fail(f"портрет: {type(exc).__name__}: {exc}")
    if getattr(sys, "frozen", False):
        from .config import app_root
        root = app_root()
        expected = Path(sys.executable).resolve().parent
        if root != expected:
            fail(f"app_root {root} (ожидался каталог exe {expected})")
        else:
            ok(f"app_root {root}")
        for rel in ("config.example.yaml", "data/airports.yaml", "data/airspace.yaml", "CHANGELOG.md"):
            path = root / rel
            if path.is_file():
                ok(rel)
            else:
                fail(f"нет файла {path}")
    text = "\n".join(lines) + "\n"
    flush()
    try:
        sys.stdout.write(text)
    except Exception:
        pass
    return rc


def fmt_state(s, st) -> str:
    return (f"[{st['phase']}] {PHASE_RU.get(__import__('ru_atc.phases', fromlist=['Phase']).Phase(st['phase']), '')} | "
            f"COM1 {s.com1_khz / 1000:.3f} | ALT {s.alt_ind_ft:.0f} ft | IAS {s.ias_kt:.0f} | GS {s.gs_kt:.0f} | "
            f"VS {s.vs_fpm:+.0f} | SQ {s.xpdr_code:04d}/{s.xpdr_mode} | Разреш.: {st['cleared']} | "
            f"Орган: {st['controlling']} | План: {st.get('plan', '-')}")


def run_console(app: App):
    print("Русский голосовой диспетчер X-Plane (консоль). Вводите фразы пилота текстом; "
          "'q' — выход, 's' — состояние.")
    app.start()
    last_state = [None]

    def printer():
        while True:
            kind, payload = app.ui_q.get()
            if kind == "atc":
                print(f"\n>>> [{payload.unit.callsign} {payload.unit.freq:.3f}] {payload.display}")
            elif kind == "pilot":
                print(f"<<< ПИЛОТ: {payload.text}   [{payload.intent}]")
            elif kind == "hint":
                print(f"  * {payload.text}")
            elif kind == "nav_progress":
                print(f"  … {payload}")
            elif kind == "info":
                print(f"  i {payload}")
            elif kind == "hint_text":
                print(f"  ! {payload}")
            elif kind == "state":
                last_state[0] = payload
    threading.Thread(target=printer, daemon=True).start()
    try:
        for line in sys.stdin:
            line = line.strip()
            if line in ("q", "quit", "exit"):
                break
            if line == "s" and last_state[0]:
                s, st, err = last_state[0]
                print(fmt_state(s, st) + (f" | ОШИБКА: {err}" if err else ""))
                continue
            if line:
                app.pilot_says(line)
    except KeyboardInterrupt:
        pass
    app.stop()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if "--smoke" in argv:
        raise SystemExit(smoke_check())
    ap = argparse.ArgumentParser(description="Русскоязычный голосовой диспетчер для X-Plane 12")
    ap.add_argument("-c", "--config", help="путь к config.yaml")
    ap.add_argument("--source", choices=["webapi", "udp", "mock"], help="источник данных")
    ap.add_argument("--demo", action="store_true", help="демо: модель полёта + автоматический пилот")
    ap.add_argument("--console", action="store_true", help="консольный интерфейс вместо окна")
    ap.add_argument("--no-voice", action="store_true", help="без голоса (только текст)")
    ap.add_argument("--compact", action="store_true", help="запустить компактной полупрозрачной панелью")
    ap.add_argument("--rebuild-nav", action="store_true",
                    help="пересобрать кэш навигации X-Plane, даже если файлы не менялись")
    ap.add_argument("--dep", help="аэродром вылета (ICAO)")
    ap.add_argument("--arr", help="аэродром назначения (ICAO)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if a.source:
        cfg["sim"]["source"] = a.source
    if a.dep:
        cfg["flight_plan"]["departure"] = a.dep.upper()
    if a.arr:
        cfg["flight_plan"]["arrival"] = a.arr.upper()
    if a.demo:
        cfg["sim"]["source"] = "mock"
    if a.compact:
        cfg["ui"]["start_compact"] = True
    if a.rebuild_nav:
        cfg.setdefault("navdata", {})["rebuild"] = True
    logp = setup_logging(cfg.get("log_dir", "logs"), a.verbose)
    app = App(cfg, demo=a.demo, no_voice=a.no_voice)
    print(f"RU ATC {__version__}")
    print(f"Лог: {logp}")
    if a.console or (cfg.get("ui") or {}).get("mode") == "console":
        run_console(app)
    else:
        try:
            from .ui import run_tk
        except Exception as e:  # нет tkinter
            print(f"tkinter недоступен ({e}), запускаю консоль")
            run_console(app)
            return
        run_tk(app)


if __name__ == "__main__":
    main()
