"""Процедуры CIFP: записи ARINC 424, как в ``Resources/default data/CIFP/<ICAO>.dat``.

X-Plane кладёт в CIFP те же 132-символьные записи, что и FAA CIFP.
Нужны первичные записи процедур аэродрома (секция P, подсекции D/E/F):

* 14–19 идентификатор схемы, 20 тип участка, 21–25 переход, 27–29 номер,
  30–34 точка, 48–49 путь (TF, IF, …).

Продолжения записи в этих колонках не содержат код пути и пропускаются.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

PATH_TERMS = {
    "IF", "TF", "CF", "DF", "FA", "FC", "FD", "FM", "CA", "CD", "CI", "CR",
    "AF", "VA", "VD", "VI", "VM", "VR", "PI", "HA", "HF", "HM",
}
KIND = {"D": "sid", "E": "star", "F": "approach"}
_RUNWAY = re.compile(r"^(?:RW)?(\d{2}[LRC]?)$", re.I)


@dataclass
class ProcedureLeg:
    airport: str
    kind: str
    ident: str
    route_type: str
    transition: str
    runway: str
    seq: int
    fix: str
    path_term: str


def _put_runway(transition: str) -> str:
    match = _RUNWAY.match((transition or "").strip().upper())
    return match.group(1).upper() if match else ""


def parse_cifp_line(line: str) -> Optional[ProcedureLeg]:
    raw = line.rstrip("\n\r")
    if len(raw) < 49 or raw[0] != "S" or raw[4] != "P":
        return None
    kind = KIND.get(raw[5])
    if not kind:
        return None
    path = raw[47:49].strip().upper()
    if path not in PATH_TERMS:
        return None
    airport = raw[6:10].strip().upper()
    ident = raw[13:19].strip().upper()
    if not airport or not ident:
        return None
    transition = raw[20:25].strip().upper()
    seq_text = raw[26:29].strip()
    try:
        seq = int(seq_text) if seq_text else 0
    except ValueError:
        seq = 0
    fix = raw[29:34].strip().upper() if len(raw) >= 34 else ""
    return ProcedureLeg(
        airport=airport, kind=kind, ident=ident, route_type=raw[19].strip().upper(),
        transition=transition, runway=_put_runway(transition), seq=seq, fix=fix, path_term=path,
    )


def parse_cifp_text(text: str) -> List[ProcedureLeg]:
    return [row for row in (parse_cifp_line(line) for line in text.splitlines()) if row]


def parse_cifp_file(path) -> Iterator[ProcedureLeg]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            row = parse_cifp_line(line)
            if row:
                yield row


def iter_cifp_paths(folder) -> Iterable:
    if folder is None or not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".dat")
