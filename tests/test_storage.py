"""Куда программа пишет кэш, модели и журналы: папка установки, не профиль."""
import errno
import os
import sys
from pathlib import Path

import pytest

from ru_atc.config import (
    app_root,
    huggingface_cache_dir,
    huggingface_hub_explicit,
    prepare_runtime_caches,
    resolve_path,
    torch_cache_dir,
    whisper_download_root,
)
from ru_atc.navdata.xplane import _relocate_file, cache_path
from ru_atc.xplane_install import legacy_user_data_dir, user_data_dir

ROOT = Path(__file__).resolve().parents[1]
_CACHE_ENV = (
    "TORCH_HOME",
    "HF_HOME",
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "XDG_CACHE_HOME",
    "RU_ATC_DATA",
    "XDG_DATA_HOME",
    "LOCALAPPDATA",
)


@pytest.fixture
def cache_env(monkeypatch):
    """Снять чужие переменные кеша и вернуть их после теста."""
    for key in _CACHE_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    return monkeypatch


def test_app_root_frozen_is_exe_dir(tmp_path, cache_env):
    exe_dir = tmp_path / "Games" / "RU ATC"
    exe_dir.mkdir(parents=True)
    exe = exe_dir / "RU-ATC.exe"
    exe.write_bytes(b"MZ")
    cache_env.setattr(sys, "frozen", True, raising=False)
    cache_env.setattr(sys, "executable", str(exe))
    assert app_root() == exe_dir
    assert resolve_path("logs") == exe_dir / "logs"
    assert resolve_path("models/vosk-model-small-ru-0.22") == (
        exe_dir / "models" / "vosk-model-small-ru-0.22"
    )
    assert torch_cache_dir() == exe_dir / "models" / "torch"
    assert huggingface_cache_dir() == exe_dir / "cache" / "huggingface"


def test_source_paths_stay_in_repo(cache_env):
    assert app_root() == ROOT
    existed = (ROOT / "cache").exists()
    assert user_data_dir() == ROOT / "cache"
    assert resolve_path("logs") == ROOT / "logs"
    if not existed:
        assert not (ROOT / "cache").exists()


def test_prepare_runtime_caches_use_install_dir(tmp_path, cache_env):
    install = tmp_path / "install"
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    problems = prepare_runtime_caches()
    assert problems == []
    assert Path(os.environ["TORCH_HOME"]) == install / "models" / "torch"
    assert Path(os.environ["HF_HOME"]) == install / "cache" / "huggingface"
    assert Path(os.environ["HF_HUB_CACHE"]) == install / "cache" / "huggingface" / "hub"
    assert Path(os.environ["HUGGINGFACE_HUB_CACHE"]) == install / "cache" / "huggingface" / "hub"
    assert Path(os.environ["XDG_CACHE_HOME"]) == install / "cache"
    assert (install / "models" / "torch").is_dir()
    assert whisper_download_root() == install / "models" / "whisper"
    assert not huggingface_hub_explicit()


def test_explicit_torch_and_hf_home_win(tmp_path, cache_env):
    install = tmp_path / "install"
    custom_torch = tmp_path / "custom-torch"
    custom_hf = tmp_path / "custom-hf"
    cache_env.setenv("TORCH_HOME", str(custom_torch))
    cache_env.setenv("HF_HOME", str(custom_hf))
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    prepare_runtime_caches()
    assert os.environ["TORCH_HOME"] == str(custom_torch)
    assert os.environ["HF_HOME"] == str(custom_hf)
    assert "HF_HUB_CACHE" not in os.environ
    assert not (install / "models" / "torch").exists()
    assert whisper_download_root() is None
    assert huggingface_hub_explicit()


def test_explicit_xdg_cache_home_wins(tmp_path, cache_env):
    install = tmp_path / "install"
    cache_env.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    prepare_runtime_caches()
    assert os.environ["XDG_CACHE_HOME"] == str(tmp_path / "xdg")
    assert Path(os.environ["TORCH_HOME"]) == install / "models" / "torch"


def test_legacy_profile_ignores_ru_atc_data(tmp_path, cache_env):
    cache_env.setenv("RU_ATC_DATA", str(tmp_path / "explicit"))
    cache_env.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    cache_env.setattr(sys, "platform", "linux")
    assert legacy_user_data_dir() == tmp_path / "xdg" / "ru-atc"
    assert user_data_dir() == tmp_path / "explicit"

    cache_env.setattr(sys, "platform", "win32")
    cache_env.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    cache_env.delenv("RU_ATC_DATA")
    assert legacy_user_data_dir() == tmp_path / "local" / "RU ATC"


def test_cache_path_moves_legacy_sqlite(tmp_path, cache_env):
    install = tmp_path / "install"
    legacy = tmp_path / "profile" / "RU ATC"
    legacy.mkdir(parents=True)
    src = legacy / "navdata.sqlite"
    src.write_bytes(b"sqlite-data")
    (legacy / "navdata.sqlite-journal").write_bytes(b"journal")
    (legacy / "notes.txt").write_bytes(b"keep-me")
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    cache_env.setattr("ru_atc.navdata.xplane.legacy_user_data_dir", lambda: legacy)
    dest = cache_path({})
    assert dest == install / "cache" / "navdata.sqlite"
    assert dest.read_bytes() == b"sqlite-data"
    assert not src.exists()
    assert (install / "cache" / "navdata.sqlite-journal").read_bytes() == b"journal"
    assert (legacy / "notes.txt").read_bytes() == b"keep-me"
    assert not (legacy / "navdata.sqlite-journal").exists()


def test_existing_cache_is_not_replaced_and_legacy_stays(tmp_path, cache_env):
    install = tmp_path / "install"
    legacy = tmp_path / "profile"
    legacy.mkdir()
    src = legacy / "navdata.sqlite"
    src.write_bytes(b"old")
    dest = install / "cache" / "navdata.sqlite"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"new")
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    cache_env.setattr("ru_atc.navdata.xplane.legacy_user_data_dir", lambda: legacy)
    assert cache_path({}).read_bytes() == b"new"
    assert src.read_bytes() == b"old"


def test_failed_move_keeps_legacy_file(tmp_path, cache_env):
    install = tmp_path / "install"
    legacy = tmp_path / "profile"
    legacy.mkdir()
    src = legacy / "navdata.sqlite"
    src.write_bytes(b"old-db")
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    cache_env.setattr("ru_atc.navdata.xplane.legacy_user_data_dir", lambda: legacy)

    def boom(_src, _dest):
        raise OSError("диск занят")

    cache_env.setattr("ru_atc.navdata.xplane._relocate_file", boom)
    dest = cache_path({})
    assert dest == install / "cache" / "navdata.sqlite"
    assert not dest.exists()
    assert src.read_bytes() == b"old-db"


def test_explicit_cache_dir_and_env_skip_migration(tmp_path, cache_env):
    install = tmp_path / "install"
    legacy = tmp_path / "profile"
    legacy.mkdir()
    src = legacy / "navdata.sqlite"
    src.write_bytes(b"old")
    cache_env.setattr("ru_atc.config.app_root", lambda: install)
    cache_env.setattr("ru_atc.navdata.xplane.legacy_user_data_dir", lambda: legacy)

    cache_env.setenv("RU_ATC_DATA", str(tmp_path / "envdata"))
    assert cache_path({}) == tmp_path / "envdata" / "navdata.sqlite"
    assert src.read_bytes() == b"old"
    cache_env.delenv("RU_ATC_DATA")

    custom = tmp_path / "custom"
    assert cache_path({"navdata": {"cache_dir": str(custom)}}) == custom / "navdata.sqlite"
    assert cache_path({"navdata": {"cache_dir": str(custom / "mine.sqlite")}}) == custom / "mine.sqlite"
    assert cache_path({"navdata": {"cache_dir": "relative/nav.sqlite"}}) == install / "relative" / "nav.sqlite"
    assert src.read_bytes() == b"old"
    assert not (install / "cache" / "navdata.sqlite").exists()


def test_relocate_copies_when_rename_crosses_devices(tmp_path, cache_env):
    src = tmp_path / "a" / "navdata.sqlite"
    src.parent.mkdir()
    src.write_bytes(b"abc")
    dest = tmp_path / "b" / "navdata.sqlite"
    real_replace = os.replace
    calls = {"n": 0}

    def replace(src_p, dest_p):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.EXDEV, "cross")
        return real_replace(src_p, dest_p)

    cache_env.setattr("ru_atc.navdata.xplane.os.replace", replace)
    _relocate_file(src, dest)
    assert dest.read_bytes() == b"abc"
    assert not src.exists()
    assert not Path(str(dest) + ".migrating").exists()


def test_frozen_nav_cache_follows_exe_and_moves_legacy(tmp_path, cache_env):
    exe_dir = tmp_path / "D" / "RU ATC"
    exe_dir.mkdir(parents=True)
    exe = exe_dir / "RU-ATC.exe"
    exe.write_bytes(b"MZ")
    legacy = tmp_path / "Local" / "RU ATC"
    legacy.mkdir(parents=True)
    (legacy / "navdata.sqlite").write_bytes(b"db")
    cache_env.setattr(sys, "frozen", True, raising=False)
    cache_env.setattr(sys, "executable", str(exe))
    cache_env.setattr("ru_atc.navdata.xplane.legacy_user_data_dir", lambda: legacy)
    prepare_runtime_caches()
    assert Path(os.environ["TORCH_HOME"]) == exe_dir / "models" / "torch"
    assert cache_path({}) == exe_dir / "cache" / "navdata.sqlite"
    assert (exe_dir / "cache" / "navdata.sqlite").read_bytes() == b"db"
    assert not (legacy / "navdata.sqlite").exists()


def test_download_script_writes_to_dest_not_temp():
    text = (ROOT / "installer" / "download_model.ps1").read_text(encoding="utf-8-sig")
    assert "System.Net.WebClient" in text
    assert "DownloadFile" in text
    assert ".part" in text
    assert "HTTPS_PROXY" in text
    assert "https://" in text
    iss = (ROOT / "installer" / "ru-atc.iss").read_text(encoding="utf-8-sig")
    assert "VoskZipFile" in iss
    assert "{app}\\models\\" in iss
