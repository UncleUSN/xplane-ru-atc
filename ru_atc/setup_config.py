"""Собрать config.yaml установщика из config.example.yaml, не теряя комментарии."""
from __future__ import annotations

import re

from . import __version__
from .voice.catalog import (
    SILERO_CODE_REPO,
    SILERO_MODEL_ID,
    SILERO_PACKAGE_URL,
    UNIT_VOICE_KEYS,
    VOSK_BY_ID,
    SILERO_BY_ID,
)


def apply_xplane_path(text: str, xplane_dir: str) -> str:
    """Прописать папку X-Plane в строки ``xplane_path:``.

    Так же делает ``installer/set_xplane_path.ps1`` в мастере: оба ключа
    (``flight_plan_import`` и ``navdata``), если они уже есть. Если ключа нет
    вообще, в конец дописывается только ``navdata.xplane_path``, чтобы не
    затереть уже существующий блок ``flight_plan_import``.
    Пустой путь файл не меняет.
    """
    directory = (xplane_dir or "").strip().strip('"').strip("'")
    if not directory:
        return text
    directory = directory.replace("\\", "/").rstrip("/")
    directory = directory.replace('"', "")
    newline = "\r\n" if "\r\n" in text else "\n"
    body = text.replace("\r\n", "\n")
    ends_nl = body.endswith("\n")
    lines = body.split("\n")
    changed = False
    for index, line in enumerate(lines):
        if re.match(r"^\s*xplane_path\s*:", line):
            indent = re.match(r"^(\s*)", line).group(1)
            lines[index] = f'{indent}xplane_path: "{directory}"'
            changed = True
    if not changed:
        extra = f'\nnavdata:\n  xplane_path: "{directory}"\n'
        if not body.endswith("\n"):
            extra = "\n" + extra
        body = body + extra
        return body.replace("\n", newline) if newline != "\n" else body
    body = "\n".join(lines)
    if ends_nl and not body.endswith("\n"):
        body += "\n"
    return body.replace("\n", newline) if newline != "\n" else body


def render_installed_config(example: str, vosk_id: str, speaker: str) -> str:
    """Подставить выбранные модель и голос в текст config.example.yaml.

    Все органы в unit_voices получают один и тот же голос: в мастере
    выбирается ровно один. Разные голоса можно прописать в файле потом.
    """
    if vosk_id not in VOSK_BY_ID:
        raise ValueError(f"неизвестная модель Vosk: {vosk_id}")
    if speaker not in SILERO_BY_ID:
        raise ValueError(f"неизвестный голос Silero: {speaker}")
    text = example.replace("\r\n", "\n")
    text, n_path = re.subn(
        r"(?m)^(\s*vosk_model_path:\s*)\S+",
        rf"\g<1>models/{vosk_id}",
        text,
        count=1,
    )
    text, n_spk = re.subn(
        r"(?m)^(\s*silero_speaker:\s*)\S+",
        rf"\g<1>{speaker}",
        text,
        count=1,
    )
    if n_path != 1 or n_spk != 1:
        raise ValueError("в шаблоне нет vosk_model_path или silero_speaker")

    keys = "|".join(UNIT_VOICE_KEYS)
    block_re = re.compile(rf"(?m)^  unit_voices:.*(?:\n    (?:{keys}):.*)+")

    def repl_block(match: re.Match) -> str:
        return re.sub(
            rf"(?m)^(\s*(?:{keys}):\s*)\S+",
            rf"\g<1>{speaker}",
            match.group(0),
        )

    text, n_units = block_re.subn(repl_block, text, count=1)
    if n_units != 1:
        raise ValueError("в шаблоне нет блока unit_voices")
    url = VOSK_BY_ID[vosk_id]["url"]
    header = (
        f"# Файл создан установщиком RU ATC {__version__}.\n"
        f"# Распознавание: {vosk_id}\n"
        f"#   архив: {url}\n"
        f"# Синтез: Silero {SILERO_MODEL_ID}, голос {speaker} (все органы).\n"
        f"#   пакет модели при первом запуске: {SILERO_PACKAGE_URL}\n"
        f"#   код загрузчика: {SILERO_CODE_REPO}\n"
        "# Другой голос каждому органу можно прописать в unit_voices.\n\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    return header + text
