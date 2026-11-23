# -*- mode: python ; coding: utf-8 -*-
"""Onedir-сборка RU-ATC.exe. Запускать только из installer/build.ps1 на Windows.

Каталог данных рядом с exe докладывает build.ps1: запущенная программа
читает config.yaml и data/ из папки с RU-ATC.exe, а не из _internal.
"""
import sys
from pathlib import Path

# SPECPATH — каталог spec-файла (installer\\). На sys.path нужен корень репозитория,
# иначе spec не импортирует installer.layout.
_spec_dir = Path(SPECPATH).resolve()
if _spec_dir.is_file():
    _spec_dir = _spec_dir.parent
sys.path.insert(0, str(_spec_dir.parent))

from installer.layout import repo_root_from_spec  # noqa: E402
from PyInstaller.utils.hooks import (  # noqa: E402
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    is_module_or_submodule,
)

root = repo_root_from_spec(SPECPATH)

datas = [
    (str(root / "data" / "airports.yaml"), "data"),
    (str(root / "data" / "airspace.yaml"), "data"),
    (str(root / "config.example.yaml"), "."),
    (str(root / "THIRD_PARTY_LICENSES.md"), "."),
    (str(root / "CHANGELOG.md"), "."),
    (str(root / "ru_atc" / "assets" / "atc_female.png"), "ru_atc/assets"),
    (str(root / "ru_atc" / "assets" / "atc_male.png"), "ru_atc/assets"),
]
missing = [src for src, _dest in datas if not Path(src).is_file()]
if missing:
    raise SystemExit("В сборке не хватает файлов:\n" + "\n".join(missing))

binaries = []
hidden = collect_submodules("ru_atc") + [
    "vosk",
    "yaml",
    "sounddevice",
    "_sounddevice",
    "_sounddevice_data",
    "cffi",
    "scipy",
    "scipy.signal",
    "keyboard",
    "pygame",
    "pyttsx3",
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "comtypes",
    "comtypes.client",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "websocket",
    "omegaconf",
    "torch",
]

# sounddevice — модуль (sounddevice.py), не пакет: сбор данных по его имени
# пропускается с предупреждением и не берёт DLL. PortAudio лежит в пакете _sounddevice_data
# и открывается по пути <пакет>/portaudio-binaries/libportaudio64bit.dll.
datas += collect_data_files("_sounddevice_data")
binaries += collect_dynamic_libs("_sounddevice_data")

for package in ("vosk", "pygame", "keyboard", "pyttsx3", "omegaconf"):
    pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_bins
    hidden += pkg_hidden

# tensorboard в сборке нет: torch.utils.tensorboard импортирует его и падает.
# distributed и testing для синтеза Silero не нужны; в граф Analysis они попадут
# сами, если какой-то модуль torch импортирует их напрямую.
_TORCH_SKIP = (
    "torch.utils.tensorboard",
    "torch.distributed",
    "torch.testing",
    "torch.onnx",
)


def _keep_torch(name):
    return not any(is_module_or_submodule(name, skip) for skip in _TORCH_SKIP)


try:
    torch_datas, torch_bins, torch_hidden = collect_all("torch", filter_submodules=_keep_torch)
    datas += torch_datas
    binaries += torch_bins
    hidden += torch_hidden
except Exception as exc:  # сборка без полного torch всё равно должна показать причину в логе
    print("WARN: collect_all(torch) не собрал пакет:", exc)
    hidden += collect_submodules("torch", filter=_keep_torch)

a = Analysis(
    [str(root / "installer" / "entrypoint.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tensorboard", "torch.utils.tensorboard"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RU-ATC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # Ошибка старта иначе показывает MessageBox и ждёт кнопку: бегун CI зависает.
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RU-ATC",
)
