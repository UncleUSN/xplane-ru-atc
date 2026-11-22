"""Последние реплики эфира для компактной панели: и пилот, и диспетчер.

Новые строки внизу. Длинная реплика обрезается, чтобы панель оставалась в одну строку на сообщение.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class RadioEntry:
    role: str       # "atc" | "pilot"
    speaker: str
    text: str


class RadioHistory:
    def __init__(self, limit: int = 5, max_len: int = 72):
        self.limit = max(1, int(limit))
        self.max_len = int(max_len)
        self._items: List[RadioEntry] = []

    def add(self, role: str, speaker: str, text: str) -> None:
        speaker = " ".join(str(speaker or "").split())
        if not speaker:
            speaker = "ПИЛОТ" if role == "pilot" else "ДИСП"
        text = " ".join(str(text or "").split())
        self._items.append(RadioEntry(role, speaker, text))
        extra = len(self._items) - self.limit
        if extra > 0:
            del self._items[:extra]

    def add_atc(self, callsign: str, text: str) -> None:
        self.add("atc", callsign, text)

    def add_pilot(self, text: str) -> None:
        self.add("pilot", "ПИЛОТ", text)

    def _clip(self, line: str) -> str:
        if self.max_len <= 0 or len(line) <= self.max_len:
            return line
        if self.max_len == 1:
            return "…"
        return line[: self.max_len - 1].rstrip() + "…"

    def lines(self) -> List[Tuple[str, str]]:
        """(роль, строка) от старых к новым: последняя — самая свежая."""
        out: List[Tuple[str, str]] = []
        for e in self._items:
            if e.role == "pilot":
                prefix = "◀ ПИЛОТ: "
            else:
                prefix = f"▶ {e.speaker}: "
            out.append((e.role, self._clip(prefix + e.text)))
        return out

    def display_slots(self) -> List[Tuple[str, str]]:
        """Ровно limit строк: пустые сверху, новые прижаты к низу."""
        lines = self.lines()
        blank = [("", "")] * (self.limit - len(lines))
        return blank + lines
