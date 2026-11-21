from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .airspace import Unit


@dataclass
class Transmission:
    unit: Unit
    display: str
    speech: str
    t: float = 0.0
    kind: str = "atc"         # atc | warning


@dataclass
class Hint:
    text: str
    t: float = 0.0
    key: str = ""


@dataclass
class PilotMessage:
    text: str
    norm: str
    intent: str
    t: float = 0.0
    unit: Optional[Unit] = None
