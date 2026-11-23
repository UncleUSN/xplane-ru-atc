"""Скачивание модели Vosk с официального адреса, если папки ещё нет.

Установщик делает то же самое во время мастера. Этот модуль — запасной путь
на первый запуск (и для установки из исходников). Silero здесь не качается:
её забирает torch.hub при первой загрузке синтеза.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Callable

from .catalog import VOSK_BY_ID

log = logging.getLogger(__name__)

DownloadFunc = Callable[..., None]


class ModelDownloadError(RuntimeError):
    pass


def _official_url(model_id: str) -> str:
    spec = VOSK_BY_ID.get(model_id)
    if spec is None:
        raise ModelDownloadError(f"нет официального адреса для «{model_id}»")
    url = str(spec["url"])
    if not url.startswith("https://"):
        raise ModelDownloadError(f"адрес модели должен быть https: {url}")
    return url


def _download(url: str, dest: Path, download: DownloadFunc | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    log.info("Скачиваю модель Vosk: %s", url)
    last = {"bucket": -1}

    def hook(block: int, block_size: int, total: int) -> None:
        if total <= 0:
            return
        pct = min(100, int(block * block_size * 100 / total))
        bucket = pct // 10
        if bucket > last["bucket"]:
            last["bucket"] = bucket
            log.info("Загрузка %s: %d%%", dest.name, pct)

    try:
        if download is None:
            import urllib.request
            urllib.request.urlretrieve(url, part, hook)
        else:
            download(url, part, hook)
    except Exception as e:
        part.unlink(missing_ok=True)
        raise ModelDownloadError(f"не удалось скачать {url}: {e}") from e
    part.replace(dest)


def safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Распаковать архив, не выпуская файлы за пределы dest."""
    root = dest.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise ModelDownloadError(f"небезопасный путь в архиве: {info.filename}")
        target = (root / name).resolve()
        if target != root and root not in target.parents:
            raise ModelDownloadError(f"небезопасный путь в архиве: {info.filename}")
    zf.extractall(root)


def model_ready(path: Path) -> bool:
    return (path / "am").is_dir() or (path / "conf").is_dir()


def ensure_vosk_model(path: Path, download: DownloadFunc | None = None) -> Path:
    """Вернуть папку модели. Если её нет и имя есть в каталоге — скачать zip.

    Неизвестное имя не качается: пусть Vosk сообщит, что папка пустая.
    ``download`` подменяется в тестах и принимает (url, dest, reporthook).
    """
    path = Path(path)
    if model_ready(path):
        return path
    spec = VOSK_BY_ID.get(path.name)
    if spec is None:
        log.info("Модель %s не из каталога установщика — автозагрузка пропущена", path.name)
        return path
    url = _official_url(path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    zip_path = path.parent / f"{path.name}.zip"
    log.info(
        "Папка модели не найдена (%s). Скачиваю %s (%s) с %s",
        path, path.name, spec.get("size", ""), url,
    )
    _download(url, zip_path, download)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract(zf, path.parent)
    except zipfile.BadZipFile as e:
        raise ModelDownloadError(f"архив модели повреждён ({zip_path}): {e}") from e
    finally:
        zip_path.unlink(missing_ok=True)
    if not model_ready(path):
        raise ModelDownloadError(
            f"после распаковки нет {path / 'am'} или {path / 'conf'}. "
            f"Проверьте архив с {url}"
        )
    log.info("Модель Vosk готова: %s", path)
    return path
