"""Провайдер данных установленного X-Plane 12."""
from __future__ import annotations

from typing import Optional

from ..xplane_install import resolve_xplane_root, user_data_dir
from .cache import NavCache, NavDataError, ensure_cache
from .provider import Progress


def cache_path(cfg: dict):
    from pathlib import Path
    custom = str((cfg.get("navdata") or {}).get("cache_dir") or "").strip()
    if custom:
        path = Path(custom)
        if path.suffix.lower() != ".sqlite":
            path = path / "navdata.sqlite"
        return path
    return user_data_dir() / "navdata.sqlite"


class XPlaneProvider:
    name = "xplane"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.diagnostic = ""
        self.root = None

    def _paths(self):
        nav = str((self.cfg.get("navdata") or {}).get("xplane_path") or "").strip()
        fms = str((self.cfg.get("flight_plan_import") or {}).get("xplane_path") or "").strip()
        root, text = resolve_xplane_root(nav, fms)
        self.root = root
        self.diagnostic = text
        return root, text

    def available(self) -> bool:
        root, _ = self._paths()
        return root is not None

    def explain(self) -> str:
        if not self.diagnostic:
            self._paths()
        return self.diagnostic

    def load(self, progress: Optional[Progress] = None) -> tuple[Optional[NavCache], bool, str]:
        root, text = self._paths()
        if root is None:
            return None, False, text
        nav = self.cfg.get("navdata") or {}
        try:
            cache, rebuilt, sources = ensure_cache(
                root, cache_path(self.cfg), bool(nav.get("rebuild")), progress or (lambda *_: None))
        except NavDataError as exc:
            return None, False, text + "\n" + str(exc)
        detail = text + "\n" + sources.describe()
        detail += "\nКэш: " + str(cache_path(self.cfg))
        detail += "\n" + ("Кэш собран заново." if rebuilt else "Кэш актуален, разбор не повторялся.")
        self.diagnostic = detail
        return cache, rebuilt, detail
