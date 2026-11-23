"""Какие файлы X-Plane читать и когда кэш устарел.

Приоритет, как у самого симулятора (статья «Navdata in X-Plane 11 and 12»):

* ``Custom Data/earth_nav.dat`` + ``earth_fix.dat`` + ``earth_awy.dat`` целиком
  заменяют ``Resources/default data``, только если набор полный и в заголовках
  один и тот же цикл AIRAC. Иначе остаётся штатный набор, в журнал пишется почему.
* ``Custom Data/CIFP/*.dat`` заменяет ``Resources/default data/CIFP``, если в папке
  есть хотя бы один ``.dat``. ``Custom Data/FAACIFP18`` поверх этого заменяет
  процедуры тех аэродромов, которые в нём есть.
* ``user_nav.dat`` и ``user_fix.dat`` добавляются поверх, не заменяя базу.
* ``apt.dat``: ``scenery_packs.ini`` сверху вниз — выше приоритет. Запись аэродрома
  из более приоритетного пакета заменяет запись целиком, а не поле за полем.
  ``Global Scenery/Global Airports`` — нижний слой, если его нет в ini.
* ``Custom Data/1200 atc data/Earth nav data/atc.dat`` заменяет
  ``Resources/default scenery/1200 atc data/Earth nav data/atc.dat``.
  ``atc.dat`` внутри пакета scenery с ``Earth nav data`` перекрывает контроллеров
  с тем же ICAO/facility id.
* ``Custom Data/airspaces/airspace.txt`` (или ``Airspaces``) заменяет
  ``Resources/default data/airspaces/airspace.txt``.

Отпечаток кэша: размер, mtime, заголовок с циклом и короткий хеш начала и конца
крупных файлов. Полный хеш сотен мегабайт на каждом запуске не считается.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .parse_nav import cycle_of, header_lines

SCHEMA = "1"


@dataclass
class DataFile:
    role: str
    path: Path
    layer: str
    header: str = ""
    size: int = 0
    mtime_ns: int = 0
    sample: str = ""

    @property
    def cycle(self) -> str:
        return cycle_of(self.header)

    def stat(self) -> "DataFile":
        try:
            st = self.path.stat()
        except OSError:
            self.size, self.mtime_ns, self.sample, self.header = 0, 0, "", ""
            return self
        self.size = st.st_size
        self.mtime_ns = st.st_mtime_ns
        self.header = header_lines(self.path)
        self.sample = sample_hash(self.path)
        return self


@dataclass
class SourceSet:
    root: Path
    files: List[DataFile] = field(default_factory=list)
    cifp_dirs: List[Path] = field(default_factory=list)
    faa_cifp: Optional[Path] = None
    apt_files: List[DataFile] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(SCHEMA.encode())
        for item in self.files + self.apt_files:
            digest.update(f"{item.role}|{item.layer}|{item.size}|{item.mtime_ns}|{item.header}|{item.sample}\n".encode())
        for folder in self.cifp_dirs:
            digest.update(self._dir_manifest(folder, "cifp"))
        if self.faa_cifp and self.faa_cifp.is_file():
            st = self.faa_cifp.stat()
            digest.update(f"faa|{st.st_size}|{st.st_mtime_ns}|{header_lines(self.faa_cifp)}\n".encode())
        return digest.hexdigest()

    def _dir_manifest(self, folder: Path, tag: str) -> bytes:
        lines = []
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() == ".dat":
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    lines.append(f"{tag}|{path.name}|{st.st_size}|{st.st_mtime_ns}")
        return ("\n".join(lines) + "\n").encode()

    def describe(self) -> str:
        rows = [f"X-Plane: {self.root}"]
        rows.extend(self.notes)
        for item in self.files + self.apt_files:
            cycle = f", цикл {item.cycle}" if item.cycle else ""
            rows.append(f"  {item.role} [{item.layer}]{cycle}: {item.path}")
        for folder in self.cifp_dirs:
            count = len(list(folder.glob("*.dat"))) if folder.is_dir() else 0
            rows.append(f"  CIFP: {folder} ({count} файлов)")
        if self.faa_cifp:
            rows.append(f"  FAACIFP18: {self.faa_cifp}")
        return "\n".join(rows)


def sample_hash(path: Path, chunk: int = 65536) -> str:
    digest = hashlib.sha256()
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            digest.update(handle.read(chunk))
            if size > chunk:
                handle.seek(max(0, size - chunk))
                digest.update(handle.read(chunk))
        digest.update(str(size).encode())
    except OSError:
        return ""
    return digest.hexdigest()[:16]


def _file(role: str, path: Path, layer: str) -> Optional[DataFile]:
    if not path.is_file():
        return None
    return DataFile(role, path, layer).stat()


def _earth_triplet(folder: Path, layer: str) -> List[DataFile]:
    roles = ("earth_nav", "earth_fix", "earth_awy")
    names = ("earth_nav.dat", "earth_fix.dat", "earth_awy.dat")
    found = []
    for role, name in zip(roles, names):
        item = _file(role, folder / name, layer)
        if item:
            found.append(item)
    return found


def _same_cycle(files: List[DataFile]) -> bool:
    cycles = {item.cycle for item in files if item.cycle}
    return len(cycles) <= 1


def scenery_apt_files(root: Path) -> tuple[List[tuple[str, Path]], List[str]]:
    """Файлы apt.dat от низкого приоритета к высокому и замечания."""
    notes: List[str] = []
    low: List[tuple[str, Path]] = []
    legacy = root / "Resources" / "default scenery" / "default apt dat" / "Earth nav data" / "apt.dat"
    if legacy.is_file():
        low.append(("default apt dat", legacy))
    global_apt = root / "Global Scenery" / "Global Airports" / "Earth nav data" / "apt.dat"
    ini = root / "Custom Scenery" / "scenery_packs.ini"
    enabled: List[tuple[str, Path]] = []
    seen_global = False
    if ini.is_file():
        text = ini.read_text(encoding="utf-8", errors="replace")
        # В ini верх файла — самый высокий приоритет. Идём снизу вверх.
        packs = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("SCENERY_PACK_DISABLED"):
                continue
            if not stripped.upper().startswith("SCENERY_PACK") or len(stripped.split(None, 1)) < 2:
                continue
            raw = stripped.split(None, 1)[1].strip().strip('"')
            path = Path(raw)
            if not path.is_absolute():
                path = root / raw
            packs.append(path)
        for pack in reversed(packs):
            apt = pack / "Earth nav data" / "apt.dat"
            try:
                label = str(pack.relative_to(root))
            except ValueError:
                label = pack.name
            if pack.name.lower().replace(" ", "") in ("globalairports",) or "Global Airports" in str(pack):
                seen_global = True
            if apt.is_file():
                enabled.append((label, apt))
            elif pack.is_dir():
                notes.append(f"в пакете нет Earth nav data/apt.dat: {pack.name}")
    else:
        notes.append("Custom Scenery/scenery_packs.ini нет — пакеты Custom Scenery взяты по имени, "
                     "Global Airports ниже них.")
        custom = root / "Custom Scenery"
        if custom.is_dir():
            for pack in sorted(p for p in custom.iterdir() if p.is_dir()):
                apt = pack / "Earth nav data" / "apt.dat"
                if apt.is_file():
                    enabled.append((f"Custom Scenery/{pack.name}", apt))
    ordered = list(low)
    if global_apt.is_file() and not seen_global:
        ordered.append(("Global Scenery/Global Airports", global_apt))
    ordered.extend(enabled)
    if not ordered:
        notes.append("apt.dat не найден ни в Global Airports, ни в Custom Scenery.")
    return ordered, notes


def scenery_atc_files(root: Path) -> List[Path]:
    """Дополнительные atc.dat пакетов, от низкого приоритета к высокому."""
    ini = root / "Custom Scenery" / "scenery_packs.ini"
    packs: List[Path] = []
    if ini.is_file():
        rows = []
        for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if (stripped.upper().startswith("SCENERY_PACK") and "DISABLED" not in stripped.upper()
                    and len(stripped.split(None, 1)) >= 2):
                raw = stripped.split(None, 1)[1].strip().strip('"')
                path = Path(raw)
                rows.append(path if path.is_absolute() else root / raw)
        packs = list(reversed(rows))
    else:
        custom = root / "Custom Scenery"
        if custom.is_dir():
            packs = sorted(p for p in custom.iterdir() if p.is_dir())
    found = []
    for pack in packs:
        path = pack / "Earth nav data" / "atc.dat"
        if path.is_file():
            found.append(path)
    return found


def collect_sources(root: Path) -> SourceSet:
    src = SourceSet(root=root)
    default_dir = root / "Resources" / "default data"
    custom_dir = root / "Custom Data"
    custom_earth = _earth_triplet(custom_dir, "custom")
    default_earth = _earth_triplet(default_dir, "default")
    if len(custom_earth) == 3 and _same_cycle(custom_earth):
        src.files.extend(custom_earth)
        src.notes.append("earth_nav/fix/awy взяты из Custom Data (полный набор, цикл совпадает) "
                         "и заменяют Resources/default data.")
        cifp = custom_dir / "CIFP"
        if not any(cifp.glob("*.dat")):
            cifp = default_dir / "CIFP"
            src.notes.append("В Custom Data нет CIFP — процедуры из Resources/default data/CIFP. "
                             "Цикл схем может не совпасть с Custom Data.")
    else:
        if custom_earth and len(custom_earth) < 3:
            missing = {"earth_nav", "earth_fix", "earth_awy"} - {item.role for item in custom_earth}
            src.notes.append("Custom Data неполный (" + ", ".join(sorted(missing)) +
                             " нет) — X-Plane такой набор не принимает, беру Resources/default data.")
        elif len(custom_earth) == 3 and not _same_cycle(custom_earth):
            cycles = ", ".join(f"{item.role}={item.cycle or '?'}" for item in custom_earth)
            src.notes.append(f"В Custom Data разные циклы ({cycles}) — беру Resources/default data.")
        src.files.extend(default_earth)
        cifp = default_dir / "CIFP"
        custom_cifp = custom_dir / "CIFP"
        if any(custom_cifp.glob("*.dat")) and not (len(custom_earth) == 3 and _same_cycle(custom_earth)):
            # Отдельная папка CIFP без полного набора earth_* всё равно перекрывает схемы.
            cifp = custom_cifp
            src.notes.append("Custom Data/CIFP есть без полного набора earth_* — схемы берутся оттуда, "
                             "точки и маяки из штатных файлов.")
    if cifp.is_dir():
        src.cifp_dirs.append(cifp)
    faa = custom_dir / "FAACIFP18"
    if faa.is_file():
        src.faa_cifp = faa
        src.notes.append("Custom Data/FAACIFP18 заменит процедуры тех аэропортов, которые в нём перечислены.")
    for name, role in (("user_nav.dat", "user_nav"), ("user_fix.dat", "user_fix")):
        item = _file(role, custom_dir / name, "user")
        if item:
            src.files.append(item)
            src.notes.append(f"{name} добавлен поверх базы.")
    apt_list, apt_notes = scenery_apt_files(root)
    src.notes.extend(apt_notes)
    for label, path in apt_list:
        item = _file(f"apt:{label}", path, "scenery")
        if item:
            src.apt_files.append(item)
    custom_atc = custom_dir / "1200 atc data" / "Earth nav data" / "atc.dat"
    default_atc = root / "Resources" / "default scenery" / "1200 atc data" / "Earth nav data" / "atc.dat"
    # Старое расположение XP11 на всякий случай, если 1200-папки нет.
    legacy_atc = root / "Resources" / "default scenery" / "default atc" / "Earth nav data" / "atc.dat"
    if custom_atc.is_file():
        src.files.append(_file("atc", custom_atc, "custom"))
        src.notes.append("atc.dat из Custom Data/1200 atc data заменяет штатный.")
        regions = custom_atc.with_name("atc_regions.dat")
    elif default_atc.is_file():
        src.files.append(_file("atc", default_atc, "default"))
        regions = default_atc.with_name("atc_regions.dat")
    elif legacy_atc.is_file():
        src.files.append(_file("atc", legacy_atc, "legacy"))
        src.notes.append("Найден atc.dat старого расположения XP11 (default atc), файла 1200 atc data нет.")
        regions = legacy_atc.with_name("atc_regions.dat")
    else:
        regions = None
        src.notes.append("atc.dat не найден. Секторы РЦ останутся из data/airspace.yaml.")
    if regions and regions.is_file():
        src.files.append(_file("atc_regions", regions, "regions"))
    for extra in scenery_atc_files(root):
        src.files.append(_file(f"atc_pack:{extra.parent.parent.name}", extra, "scenery"))
    air_custom = None
    for folder_name in ("airspaces", "Airspaces"):
        candidate = custom_dir / folder_name / "airspace.txt"
        if candidate.is_file():
            air_custom = candidate
            break
    air_default = default_dir / "airspaces" / "airspace.txt"
    if air_custom:
        src.files.append(_file("airspace", air_custom, "custom"))
        src.notes.append("airspace.txt из Custom Data заменяет штатный OpenAir.")
    elif air_default.is_file():
        src.files.append(_file("airspace", air_default, "default"))
    if not any(item.role == "earth_nav" for item in src.files):
        src.notes.append("earth_nav.dat нет — кэш навигации собрать нельзя.")
    return src
