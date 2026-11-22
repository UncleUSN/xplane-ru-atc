"""Портреты диспетчера для полного окна. Файлов может не быть — тогда портрет не показывается."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

ASSETS = Path(__file__).resolve().parent / "assets"


def avatar_file(gender: str) -> Optional[Path]:
    """PNG женского или мужского портрета, либо None, если файла нет или пол неизвестен."""
    if gender not in ("female", "male"):
        return None
    path = ASSETS / f"atc_{gender}.png"
    return path if path.is_file() else None
