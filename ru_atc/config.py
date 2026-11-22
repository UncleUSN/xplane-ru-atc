"""Загрузка конфигурации (YAML) с дефолтами."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: Dict[str, Any] = {
    "callsign": {"spoken": "Аэрофлот", "number": "1234"},
    "flight_plan": {"departure": "UUEE", "arrival": "ULLI", "cruise_fl": 330, "route": "по плану",
                    "sid": "", "star": "", "departure_runway": "", "arrival_runway": "",
                    "arrival_stand": ""},
    "flight_plan_import": {"source": "auto", "fmc_side": 1, "poll_s": 2.0, "xplane_path": "",
                           "fms_max_age_h": 12, "callsign_from_fmc": True},
    "airlines": {"AFL": "Аэрофлот", "SDM": "Россия", "PBD": "Победа", "SBI": "Сибирь", "UTA": "Ютэйр",
                 "SVR": "Свердловск авиа"},
    "sim": {"source": "webapi", "host": "localhost", "webapi_port": 8086, "webapi_version": "auto",
            "udp_port": 49000, "udp_listen_port": 49010, "use_zibo_datarefs": True,
            "mock_time_scale": 4.0},
    "atc": {"strict_frequency": True, "confirm_correct_readback": True,
            "readback_strictness": "lenient", "readback_timeout_s": 20,
            "levels_digit_by_digit": False, "auto_descent": True, "speed_limit_kt": 250,
            "voice_warnings": True},
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
    return path if path.is_absolute() else ROOT / path


def normalize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Совместимость со старыми config.yaml: «ui: tk» / «ui: console» -> {"mode": ...}."""
    user = dict(user or {})
    if isinstance(user.get("ui"), str):
        user["ui"] = {"mode": user["ui"]}
    return user


def load_config(path: str | None = None) -> Dict[str, Any]:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    user: Dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    return deep_merge(DEFAULTS, normalize_user(user))
