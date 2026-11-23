# -*- mode: python ; coding: utf-8 -*-
"""Onedir-сборка RU-ATC.exe. Запускать только из installer/build.ps1 на Windows.

Каталог данных рядом с exe докладывает build.ps1: запущенная программа
читает config.yaml и data/ из папки с RU-ATC.exe, а не из _internal.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve().parent.parent

datas = [
    (str(root / "data" / "airports.yaml"), "data"),
    (str(root / "data" / "airspace.yaml"), "data"),
    (str(root / "config.example.yaml"), "."),
    (str(root / "THIRD_PARTY_LICENSES.md"), "."),
    (str(root / "CHANGELOG.md"), "."),
    (str(root / "ru_atc" / "assets" / "atc_female.png"), "ru_atc/assets"),
    (str(root / "ru_atc" / "assets" / "atc_male.png"), "ru_atc/assets"),
]
binaries = []
hidden = collect_submodules("ru_atc") + [
    "vosk",
    "yaml",
    "sounddevice",
    "scipy",
    "scipy.signal",
    "keyboard",
    "pygame",
    "pyttsx3",
    "websocket",
    "omegaconf",
    "torch",
]

for package in ("vosk", "sounddevice", "pygame", "keyboard", "pyttsx3", "omegaconf"):
    pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_bins
    hidden += pkg_hidden

try:
    torch_datas, torch_bins, torch_hidden = collect_all("torch")
    datas += torch_datas
    binaries += torch_bins
    hidden += torch_hidden
except Exception as exc:  # сборка без полного torch всё равно должна показать причину в логе
    print("WARN: collect_all(torch) не собрал пакет:", exc)
    hidden += collect_submodules("torch")

a = Analysis(
    [str(root / "ru_atc" / "__main__.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    disable_windowed_traceback=False,
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
