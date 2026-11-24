"""Где установлен X-Plane 12.

Один и тот же поиск нужен и папке ``Output/FMS plans``, и навигационным файлам.
Раньше автопоиск смотрел только несколько типичных дисков и файл списка установок
как UTF-8. Установщик Laminar на Windows часто пишет этот список в UTF-16,
а путь ``D:\\X-Plane 12`` при этом не находился, хотя X-Plane там стоит.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional

COMMON_ROOTS = (
    "C:/X-Plane 12",
    "D:/X-Plane 12",
    "E:/X-Plane 12",
    "C:/Program Files (x86)/Steam/steamapps/common/X-Plane 12",
    "C:/Program Files/Steam/steamapps/common/X-Plane 12",
    "D:/SteamLibrary/steamapps/common/X-Plane 12",
    "E:/SteamLibrary/steamapps/common/X-Plane 12",
)

_SKIP_INSTALL_LINE = re.compile(r"^(I|A|\d{1,4}(\s+version\b.*)?)$", re.I)


def clean_path(value: str) -> Path:
    """Убрать кавычки, ``file:`` и хвостовой слэш. Если указан ``X-Plane.exe`` — взять папку."""
    text = str(value or "").strip().strip('"').strip("'")
    if text.lower().startswith("file:"):
        text = text[5:]
        text = text.lstrip("/").strip()
    path = Path(text)
    if path.suffix.lower() == ".exe":
        path = path.parent
    return path


def decode_text_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    # UTF-16 без BOM: нулевые байты в начале строки.
    sample = raw[:120]
    if sample.count(b"\x00") >= 4:
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(enc)
            except UnicodeError:
                continue
    return raw.decode("utf-8-sig", errors="replace")


def read_install_paths(path: Path) -> List[Path]:
    """Строки из ``x-plane_install_12.txt``. Пустые, ``I`` и номер версии пропускаются."""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    out: List[Path] = []
    for line in decode_text_bytes(raw).splitlines():
        line = line.strip().strip('"').strip("'")
        if not line or _SKIP_INSTALL_LINE.match(line):
            continue
        if len(line) < 3:
            continue
        out.append(clean_path(line))
    return out


def install_list_files() -> List[Path]:
    found: List[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found.append(Path(local) / "x-plane_install_12.txt")
    home = Path.home()
    found.append(home / ".x-plane" / "x-plane_install_12.txt")
    found.append(home / "Library" / "Preferences" / "x-plane_install_12.txt")
    appdata = os.environ.get("APPDATA")
    if appdata:
        found.append(Path(appdata).parent / "Local" / "x-plane_install_12.txt")
    return found


def _registry_roots() -> List[Path]:
    if not sys.platform.startswith("win"):
        return []
    try:
        import winreg
    except ImportError:
        return []
    out: List[Path] = []
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Laminar Research\X-Plane 12"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Laminar Research\X-Plane 12"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
    )
    value_names = ("InstallPath", "Path", "SteamPath")
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as key:
                for name in value_names:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    if not value:
                        continue
                    path = clean_path(str(value))
                    if path.name.lower() == "steam":
                        out.append(path / "steamapps" / "common" / "X-Plane 12")
                    else:
                        out.append(path)
        except OSError:
            continue
    return out


def steam_library_roots() -> List[Path]:
    """``steamapps/common/X-Plane 12`` по ``libraryfolders.vdf``."""
    vdfs: List[Path] = []
    pf86 = os.environ.get("ProgramFiles(x86)")
    pf = os.environ.get("ProgramFiles")
    if pf86:
        vdfs.append(Path(pf86) / "Steam" / "steamapps" / "libraryfolders.vdf")
    if pf:
        vdfs.append(Path(pf) / "Steam" / "steamapps" / "libraryfolders.vdf")
    home = Path.home()
    vdfs.append(home / ".steam" / "steam" / "steamapps" / "libraryfolders.vdf")
    vdfs.append(home / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf")
    out: List[Path] = []
    for vdf in vdfs:
        try:
            text = decode_text_bytes(vdf.read_bytes())
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            base = Path(match.group(1).replace("\\\\", "\\"))
            out.append(base / "steamapps" / "common" / "X-Plane 12")
    return out


def _dedupe(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    out: List[Path] = []
    for path in paths:
        key = str(path).replace("\\", "/").rstrip("/").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def candidate_roots(configured: str = "") -> List[Path]:
    """Кандидаты папки X-Plane, в том числе те, которых на этой машине нет.

    Отсутствие пути — тоже диагностика, поэтому несуществующие не выкидываются.
    """
    paths: List[Path] = []
    if configured:
        paths.append(clean_path(configured))
    for listing in install_list_files():
        paths.extend(read_install_paths(listing))
    paths.extend(_registry_roots())
    paths.extend(steam_library_roots())
    paths.extend(Path(p) for p in COMMON_ROOTS)
    return _dedupe(paths)


def is_xplane_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "Resources" / "default data" / "earth_nav.dat").is_file():
        return True
    if (path / "X-Plane.exe").is_file():
        return True
    if (path / "X-Plane.app").is_dir():
        return True
    return False


def root_markers(path: Path) -> List[str]:
    marks = []
    if (path / "X-Plane.exe").is_file():
        marks.append("X-Plane.exe")
    if (path / "X-Plane.app").is_dir():
        marks.append("X-Plane.app")
    nav = path / "Resources" / "default data" / "earth_nav.dat"
    if nav.is_file():
        marks.append("Resources/default data/earth_nav.dat")
    return marks


def fms_plans_dir(path: Path) -> Optional[Path]:
    if path.name.lower() == "fms plans" and path.is_dir():
        return path
    folder = path / "Output" / "FMS plans"
    if folder.is_dir():
        return folder
    return None


def classify_root(path: Path) -> str:
    """Короткая причина, почему путь годится или нет. Для журнала и сообщения об ошибке."""
    if fms_plans_dir(path) is not None and path.name.lower() == "fms plans":
        return "это уже папка FMS plans"
    plans = path / "Output" / "FMS plans"
    marks = root_markers(path)
    if marks and plans.is_dir():
        return "установка X-Plane, папка планов на месте (" + ", ".join(marks) + ")"
    if marks and not plans.is_dir():
        return ("установка X-Plane найдена (" + ", ".join(marks) + "), "
                "но каталога Output/FMS plans нет — сохраните маршрут в Zibo "
                "(RTE, страница 1, SAVE ROUTE), X-Plane создаст папку сам")
    if path.exists():
        return ("это не папка X-Plane 12: нет X-Plane.exe и нет "
                "Resources/default data/earth_nav.dat")
    return "пути нет"


def explain_fms_miss(xplane_path: str = "") -> str:
    """Текст, если ``Output/FMS plans`` не найдена. Имя настройки в нём обязано остаться."""
    tail = ("Укажите flight_plan_import.xplane_path в config.yaml — папка установки X-Plane 12, "
            "например \"D:/X-Plane 12\" (внутри неё должна быть Output/FMS plans), "
            "или запустите python tools/fmcdump.py --xplane \"D:/X-Plane 12\". "
            "Тот же путь читает navdata.xplane_path, если он задан отдельно.")
    if xplane_path:
        root = clean_path(xplane_path)
        tried = str(root / "Output" / "FMS plans")
        return f"папка Output/FMS plans не найдена (проверен путь {tried}). {classify_root(root)}. {tail}"
    checked = [f"{p} — {classify_root(p)}" for p in candidate_roots()[:8]]
    where = ("автопоиск, проверены: " + "; ".join(checked)) if checked else "автопоиск ничего не дал"
    return f"папка Output/FMS plans не найдена ({where}). {tail}"


def legacy_user_data_dir() -> Path:
    """Куда 0.3.2-beta клал ``navdata.sqlite`` в профиле.

    ``RU_ATC_DATA`` здесь не учитывается: это явный каталог и тогда, и сейчас.
    Функция нужна только для переноса. Сам каталог и чужие файлы в нём
    программа не удаляет.
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "RU ATC"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "RU ATC"
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return root / "ru-atc"


def user_data_dir() -> Path:
    """Каталог данных программы (кэш навигации).

    Явная ``RU_ATC_DATA`` побеждает. Иначе это ``cache`` в папке программы:
    каталог ``RU-ATC.exe`` или корень репозитория. Папка должна быть доступна
    для записи. Установщик по умолчанию ставит в ``%LOCALAPPDATA%\\RU ATC``.
    """
    override = os.environ.get("RU_ATC_DATA", "").strip()
    if override:
        return Path(override)
    from .config import app_root
    return app_root() / "cache"


def fms_configured_path(cfg: dict) -> str:
    """Папка X-Plane для планов FMC: свой ключ, иначе navdata.xplane_path."""
    fms = str((cfg.get("flight_plan_import") or {}).get("xplane_path") or "").strip()
    nav = str((cfg.get("navdata") or {}).get("xplane_path") or "").strip()
    return fms or nav


def nav_configured_path(cfg: dict) -> str:
    """Папка X-Plane для навигации: свой ключ, иначе flight_plan_import.xplane_path."""
    nav = str((cfg.get("navdata") or {}).get("xplane_path") or "").strip()
    fms = str((cfg.get("flight_plan_import") or {}).get("xplane_path") or "").strip()
    return nav or fms


def resolve_xplane_root(configured: str = "", import_path: str = "") -> tuple[Optional[Path], str]:
    """Выбрать корень X-Plane и собрать диагностику.

    Сначала ``configured`` (navdata.xplane_path), затем путь импорта плана,
    затем автопоиск. Корень — папка, где есть earth_nav.dat или X-Plane.exe.
    """
    lines: List[str] = []
    ordered: List[tuple[str, Path]] = []
    if configured:
        ordered.append(("navdata.xplane_path", clean_path(configured)))
    if import_path and clean_path(import_path) not in [p for _, p in ordered]:
        ordered.append(("flight_plan_import.xplane_path", clean_path(import_path)))
    for path in candidate_roots(""):
        if any(path == have for _, have in ordered):
            continue
        ordered.append(("автопоиск", path))
    chosen: Optional[Path] = None
    for origin, path in ordered:
        marks = root_markers(path)
        if marks:
            lines.append(f"{origin}: {path} — X-Plane ({', '.join(marks)})")
            if chosen is None:
                chosen = path
        else:
            lines.append(f"{origin}: {path} — {classify_root(path)}")
        if origin != "автопоиск" and chosen is not None:
            break
    if chosen is None:
        lines.append("Папка X-Plane 12 не найдена. Частоты останутся из data/airports.yaml и data/airspace.yaml.")
    return chosen, "\n".join(lines)
