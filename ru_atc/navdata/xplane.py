"""Провайдер данных установленного X-Plane 12."""
from __future__ import annotations

import errno
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from ..xplane_install import legacy_user_data_dir, resolve_xplane_root, user_data_dir
from .cache import NavCache, NavDataError, ensure_cache
from .provider import Progress

log = logging.getLogger(__name__)

# Рядом с sqlite, если журнал не успели закрыть. DELETE — основной режим,
# WAL попадается у файла, который собрала более ранняя копия.
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _cross_device(exc: OSError) -> bool:
    if exc.errno == errno.EXDEV:
        return True
    return getattr(exc, "winerror", None) == 17


def _relocate_file(src: Path, dest: Path) -> None:
    """Перенести ``src`` в ``dest``.

    Сначала переименование на том же томе. Если том другой — копия, проверка
    размера, затем удаление исходника. Не удалось удалить исходник — копия
    уже на месте, исходник остаётся. Ошибка до готового ``dest`` исходник
    не трогает и стирает недописанный хвост ``.migrating``.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
        return
    except OSError as exc:
        if dest.exists() or not src.exists() or not _cross_device(exc):
            raise
    partial = Path(str(dest) + ".migrating")
    try:
        shutil.copy2(src, partial)
        if not partial.is_file() or partial.stat().st_size != src.stat().st_size:
            raise OSError(f"копия {src} не совпала по размеру")
        os.replace(partial, dest)
    except Exception:
        partial.unlink(missing_ok=True)
        if not dest.is_file():
            raise
    try:
        src.unlink()
    except OSError as exc:
        log.warning(
            "Кэш скопирован в %s. Прежний файл не удалён и остаётся на месте: %s (%s)",
            dest, src, exc,
        )


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def migrate_legacy_nav_cache(dest: Path) -> None:
    """Перенести ``navdata.sqlite`` из профиля, если в папке программы его ещё нет.

    Новый файл не затирается. Чужие файлы в старом каталоге не удаляются.
    Если перенос не удался, старый sqlite остаётся где был: кэш соберётся заново.
    """
    if dest.exists():
        return
    src = legacy_user_data_dir() / "navdata.sqlite"
    if not src.is_file() or _same_file(src, dest):
        return
    sources = [src]
    for suffix in _SIDECAR_SUFFIXES:
        extra = Path(str(src) + suffix)
        if extra.is_file():
            sources.append(extra)
    moved_main = False
    for source in sources:
        target = dest if source == src else Path(str(dest) + source.name[len(src.name):])
        if target.exists():
            log.info("Уже есть %s — %s не трогаю", target, source)
            continue
        try:
            _relocate_file(source, target)
        except OSError as exc:
            log.warning(
                "Не удалось перенести %s в %s (%s). Файл оставлен на прежнем месте.",
                source, target, exc,
            )
            if source == src:
                return
            continue
        if source == src:
            moved_main = True
    if moved_main:
        log.info("Кэш навигации перенесён в %s (было %s)", dest, src)


def cache_path(cfg: dict) -> Path:
    """Файл SQLite с разбором X-Plane.

    ``navdata.cache_dir`` и ``RU_ATC_DATA`` побеждают, если заданы.
    Иначе ``cache/navdata.sqlite`` в папке программы. Относительный
    ``cache_dir`` считается от папки программы, не от текущего каталога.
    """
    from ..config import resolve_path
    custom = str((cfg.get("navdata") or {}).get("cache_dir") or "").strip()
    if custom:
        path = resolve_path(custom)
        if path.suffix.lower() != ".sqlite":
            path = path / "navdata.sqlite"
        return path
    dest = user_data_dir() / "navdata.sqlite"
    if not os.environ.get("RU_ATC_DATA", "").strip():
        migrate_legacy_nav_cache(dest)
    return dest


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
