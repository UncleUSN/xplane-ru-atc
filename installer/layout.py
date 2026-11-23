"""Куда смотрят пути сборки установщика.

PyInstaller кладёт в SPECPATH каталог spec-файла (installer\\), а не сам файл.
Корень репозитория — родитель этого каталога. Лишний уровень вверх на бегуне
GitHub даёт D:\\a\\xplane-ru-atc\\ вместо D:\\a\\xplane-ru-atc\\xplane-ru-atc\\.
"""
from __future__ import annotations

from pathlib import Path


def repo_root_from_spec(specpath: str | Path) -> Path:
    """Корень репозитория по SPECPATH или по пути к ru_atc.spec."""
    spec_dir = Path(specpath).resolve()
    if spec_dir.is_file():
        spec_dir = spec_dir.parent
    root = spec_dir.parent
    entry = root / "ru_atc" / "__main__.py"
    if not entry.is_file():
        raise SystemExit(
            f"Не найден {entry}. SPECPATH={specpath}. "
            "Каталог spec-файла должен называться installer и лежать в корне репозитория."
        )
    return root
