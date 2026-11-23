"""Собрать кэш и отдать его диспетчеру. Вызывается с фонового потока."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from ..airspace import Airspace
from .cache import NavCache
from .overlay import apply_navdata
from .provider import NullProvider, Progress, make_provider
from .xplane import XPlaneProvider

log = logging.getLogger("ru_atc.navdata")


@dataclass
class NavResult:
    cache: Optional[NavCache]
    notes: List[str] = field(default_factory=list)
    rebuilt: bool = False

    def apply(self, airspace: Airspace, controller) -> List[str]:
        if self.cache is None:
            return list(self.notes)
        extra = apply_navdata(airspace, self.cache)
        controller.nav = self.cache
        nav_cfg = controller.cfg.get("navdata") or {}
        try:
            controller.nav_radius_km = float(nav_cfg.get("corridor_km") or 50)
        except (TypeError, ValueError):
            controller.nav_radius_km = 50.0
        return self.notes + extra


def prepare_navdata(cfg: dict, progress: Optional[Progress] = None) -> NavResult:
    progress = progress or (lambda *_: None)
    provider = make_provider(cfg)
    notes: List[str] = []
    if provider.name == "navigraph":
        notes.append(provider.explain())
        log.info("%s", notes[-1])
        provider = XPlaneProvider(cfg)
    if isinstance(provider, NullProvider) or provider.name == "off":
        text = provider.explain()
        log.info("%s", text)
        return NavResult(None, [text])
    if not isinstance(provider, XPlaneProvider):
        provider = XPlaneProvider(cfg)
    cache, rebuilt, detail = provider.load(progress)
    log.info("Навигационные данные:\n%s", detail)
    # В окно — короткая шапка, полный список файлов остаётся в журнале.
    head = detail.strip().splitlines()
    short = [line for line in head if not line.startswith("  ")]
    notes.extend(short[:8])
    if cache is None:
        notes.append("Частоты и секторы остаются из data/airports.yaml и data/airspace.yaml.")
    return NavResult(cache, notes, rebuilt)
