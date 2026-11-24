"""Загрузка конфигурации (YAML) с дефолтами."""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

from .phraseology.callsign import DEFAULT_AIRLINES


def app_root() -> Path:
    """Каталог с config.yaml, data/ и models/.

    В собранном exe это папка с RU-ATC.exe (её пишет установщик).
    В исходниках — корень репозитория.

    Сюда же пишутся ``cache``, ``logs`` и скачанные модели. Папка должна
    быть доступна для записи. Установщик по умолчанию выбирает
    ``%LOCALAPPDATA%\\RU ATC``, не «Program Files».
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = Path(__file__).resolve().parent.parent


def _same_path(current: str, expected: Path) -> bool:
    try:
        return Path(current).resolve() == expected.resolve()
    except OSError:
        return os.path.normcase(os.path.abspath(current)) == os.path.normcase(str(expected))


def torch_cache_dir() -> Path:
    """Кеш torch.hub (Silero): ``models/torch`` в папке программы."""
    return app_root() / "models" / "torch"


def whisper_model_dir() -> Path:
    """Каталог весов faster-whisper, если свой кеш Hugging Face не задан."""
    return app_root() / "models" / "whisper"


def huggingface_cache_dir() -> Path:
    """Прочие файлы Hugging Face: ``cache/huggingface``."""
    return app_root() / "cache" / "huggingface"


def huggingface_hub_explicit() -> bool:
    """True, если HF_HOME / HF_HUB_CACHE указывают не в папку программы.

    Путь, который выставила сама ``prepare_runtime_caches``, явным не считается:
    повторный вызов и загрузка Whisper не должны уезжать в профиль.
    """
    hf = huggingface_cache_dir()
    expected = {
        "HF_HOME": hf,
        "HF_HUB_CACHE": hf / "hub",
        "HUGGINGFACE_HUB_CACHE": hf / "hub",
    }
    for name, path in expected.items():
        current = os.environ.get(name, "").strip()
        if current and not _same_path(current, path):
            return True
    return False


def whisper_download_root() -> Path | None:
    """Папка модели faster-whisper. None — кеш Hugging Face задан снаружи."""
    if huggingface_hub_explicit():
        return None
    return whisper_model_dir()


def _mkdir_cache(path: Path, problems: list) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        problems.append(f"{path}: {exc}")


def prepare_runtime_caches() -> list:
    """Направить кеши библиотек в папку программы.

    Уже заданные ``TORCH_HOME``, ``HF_HOME``, ``HF_HUB_CACHE``,
    ``HUGGINGFACE_HUB_CACHE`` и ``XDG_CACHE_HOME`` не перезаписываются,
    если они указывают в другое место. Каталоги создаются сразу, чтобы
    ошибка прав была видна до скачивания. Список — это пути, которые
    не удалось создать. Переменные всё равно выставляются: в профиль
    пользователя библиотеки не откатываются.
    """
    problems: list = []
    torch_dir = torch_cache_dir()
    torch_now = os.environ.get("TORCH_HOME", "").strip()
    if not torch_now or _same_path(torch_now, torch_dir):
        _mkdir_cache(torch_dir, problems)
        os.environ["TORCH_HOME"] = str(torch_dir)
    if not huggingface_hub_explicit():
        hf = huggingface_cache_dir()
        _mkdir_cache(hf, problems)
        os.environ["HF_HOME"] = str(hf)
        os.environ["HF_HUB_CACHE"] = str(hf / "hub")
        os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf / "hub")
        if not os.environ.get("TRANSFORMERS_CACHE", "").strip():
            os.environ["TRANSFORMERS_CACHE"] = str(hf / "transformers")
    xdg = app_root() / "cache"
    xdg_now = os.environ.get("XDG_CACHE_HOME", "").strip()
    if not xdg_now or _same_path(xdg_now, xdg):
        _mkdir_cache(xdg, problems)
        os.environ["XDG_CACHE_HOME"] = str(xdg)
    return problems

DEFAULTS: Dict[str, Any] = {
    "callsign": {"spoken": "Аэрофлот", "number": "1234"},
    "flight_plan": {"departure": "UUEE", "arrival": "ULLI", "cruise_fl": 330, "route": "по плану",
                    "sid": "", "star": "", "departure_runway": "", "arrival_runway": "",
                    "arrival_stand": "", "alternates": []},
    # xplane — файлы симулятора; navigraph — заглушка (подписка не подключена); off — только yaml.
    "navdata": {"provider": "xplane", "xplane_path": "", "cache_dir": "",
                "corridor_km": 50, "rebuild": False},
    "flight_plan_import": {"source": "auto", "fmc_side": 1, "poll_s": 2.0, "xplane_path": "",
                           "fms_max_age_h": 12, "callsign_from_fmc": True},
    "airlines": dict(DEFAULT_AIRLINES),
    "sim": {"source": "webapi", "host": "localhost", "webapi_port": 8086, "webapi_version": "auto",
            "udp_port": 49000, "udp_listen_port": 49010, "use_zibo_datarefs": True,
            "mock_time_scale": 4.0},
    # Выключено: пилот сам ставит частоту, диспетчер проверяет активный COM1.
    "radio": {"auto_tune_com1": False},
    "atc": {"strict_frequency": True, "confirm_correct_readback": True,
            "readback_strictness": "lenient", "readback_timeout_s": 20,
            "levels_digit_by_digit": False, "auto_descent": True, "speed_limit_kt": 250,
            "voice_warnings": True,
            "chattiness": "normal"},  # off | normal | high — приветствия и прощания
    "voice": {"enabled": True, "ptt_key": "caps lock", "ptt_joystick": None, "input_device": None,
              "output_device": None, "host_api": None, "stt_engine": "vosk",
              "vosk_model_path": "models/vosk-model-small-ru-0.22", "vosk_grammar": False, "whisper_model": "small",
              "whisper_device": "auto", "tts_engine": "silero", "silero_speaker": "aidar",
              "unit_voices": {}, "edge_voice": "ru-RU-DmitryNeural", "radio_effect": True,
              "radio_noise": 0.015},
    "ui": {"mode": "tk",                    # tk | console
           "always_on_top": True,           # окно поверх X-Plane (оконный/безрамочный полноэкранный режим)
           "topmost_reassert_s": 2.0,       # как часто заново поднимать окно наверх (0 = не поднимать)
           "start_compact": False,          # сразу компактная полупрозрачная панель
           "compact_alpha": 0.85,           # прозрачность компактного режима (0.2..1.0)
           "full_alpha": 1.0,
           "compact_geometry": "560x180-20+40",   # ШxВ±X±Y; "-20+40" = 20 px от правого края, 40 от верха
           "full_geometry": "1100x680",
           "compact_borderless": True,      # компактная панель без рамки (перетаскивается мышью)
           "hotkey_toggle": "ctrl+shift+a", # показать/спрятать окно (глобально); "" = выкл.
           "hotkey_compact": "ctrl+shift+z",# компактный/полный режим; "" = выкл.
           "focus_on_show": False},         # False: при показе вернуть фокус симулятору
    "log_dir": "logs",
    "airports_file": "data/airports.yaml",
    "airspace_file": "data/airspace.yaml",
}


def deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else app_root() / path


def normalize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Совместимость со старыми config.yaml: «ui: tk» / «ui: console» -> {"mode": ...}."""
    user = dict(user or {})
    if isinstance(user.get("ui"), str):
        user["ui"] = {"mode": user["ui"]}
    return user


def load_config(path: str | None = None) -> Dict[str, Any]:
    cfg_path = Path(path) if path else app_root() / "config.yaml"
    user: Dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8-sig") as f:
            user = yaml.safe_load(f) or {}
    return deep_merge(DEFAULTS, normalize_user(user))
