"""Версия 0.3.1-beta, каталог моделей и страницы мастера установщика."""
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from ru_atc import __version__, window_title
from ru_atc.config import app_root
from ru_atc.setup_config import apply_xplane_path, render_installed_config
from ru_atc.voice.catalog import (
    SILERO_MODEL_ID,
    SILERO_VOICES,
    VOSK_MODELS,
    default_speaker,
    default_vosk_id,
)
from ru_atc.voice.download import ModelDownloadError, ensure_vosk_model, safe_extract
from ru_atc.voice.voices import voice_gender

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_single_source():
    assert __version__ == "0.3.1-beta"
    assert "0.3.1-beta" in window_title()
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "version =" not in text
    script = ROOT / "installer" / "print_version.py"
    assert "__init__.py" in script.read_text(encoding="utf-8")
    printed = subprocess.check_output([sys.executable, str(script)], text=True).strip()
    quad = subprocess.check_output([sys.executable, str(script), "--quad"], text=True).strip()
    assert printed == "0.3.1-beta"
    assert quad == "0.3.1.0"


def test_app_root_is_repo_when_not_frozen():
    assert app_root() == ROOT


def test_apply_xplane_path_rewrites_both_keys_and_appends_when_missing():
    text = "flight_plan_import:\n  xplane_path: \"\"\nnavdata:\n  xplane_path: \"\"\n# xplane_path: не трогать\n"
    got = apply_xplane_path(text, r"D:\X-Plane 12\\")
    assert got.count('xplane_path: "D:/X-Plane 12"') == 2
    assert "# xplane_path: не трогать" in got
    assert apply_xplane_path(text, "  ") == text
    bare = "callsign:\n  spoken: Тест\n"
    added = apply_xplane_path(bare, "E:/X-Plane 12")
    assert 'xplane_path: "E:/X-Plane 12"' in added
    assert "spoken: Тест" in added


def test_catalog_matches_code():
    assert [m["id"] for m in VOSK_MODELS] == [
        "vosk-model-small-ru-0.22",
        "vosk-model-ru-0.42",
    ]
    assert [v["id"] for v in SILERO_VOICES] == ["aidar", "baya", "kseniya", "xenia", "eugene"]
    assert sum(1 for m in VOSK_MODELS if m["default"]) == 1
    assert sum(1 for v in SILERO_VOICES if v["default"]) == 1
    assert default_vosk_id() == "vosk-model-small-ru-0.22"
    assert default_speaker() == "aidar"
    assert SILERO_MODEL_ID == "v4_ru"
    for voice in SILERO_VOICES:
        expected = "female" if voice["gender_ru"] == "женский" else "male"
        assert voice_gender(voice["id"]) == expected
    stt = (ROOT / "ru_atc" / "voice" / "stt.py").read_text(encoding="utf-8")
    for model in VOSK_MODELS:
        assert model["id"] in stt
        assert model["url"].startswith("https://alphacephei.com/vosk/models/")


def test_render_config_keeps_comments_and_one_voice():
    example = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    text = render_installed_config(example, "vosk-model-ru-0.42", "xenia")
    assert "vosk_model_path: models/vosk-model-ru-0.42" in text
    assert "silero_speaker: xenia" in text
    assert "Аэрофлот" in text
    for key in ("delivery", "ground", "tower", "radar", "approach", "control"):
        assert f"{key}: xenia" in text
    assert "baya" not in text.split("unit_voices:", 1)[1].split("edge_voice:", 1)[0]
    with pytest.raises(ValueError):
        render_installed_config(example, "vosk-model-ru-0.10", "aidar")


def test_generated_installer_data_matches_catalog(tmp_path):
    from installer.render_catalog import build

    fresh = build(tmp_path)
    folder = ROOT / "installer" / "generated"
    assert set(fresh) == {p.name for p in folder.iterdir() if p.is_file()}
    for name, text in fresh.items():
        on_disk = (folder / name).read_text(encoding="utf-8-sig")
        assert on_disk.replace("\r\n", "\n") == text.replace("\r\n", "\n")
    pas = fresh["catalog.pas"]
    for model in VOSK_MODELS:
        assert model["url"] in pas
        assert model["caption"] in pas
    for voice in SILERO_VOICES:
        assert voice["caption"] in pas
    iss = (ROOT / "installer" / "ru-atc.iss").read_text(encoding="utf-8-sig")
    assert "AddRadioButton" in iss
    assert iss.count("AddGroup(") == 2
    assert "CreateDownloadPage" in iss
    assert "VoskCaptions" in iss and "SpeakerCaptions" in iss
    assert "config.yaml" in iss
    assert "CreateInputDirPage" in iss
    assert "x-plane_install_12.txt" in iss
    assert "Resources\\default data" in iss
    assert "set_xplane_path.ps1" in iss
    assert "MyVersionInfo" in iss
    ps1 = (ROOT / "installer" / "set_xplane_path.ps1").read_text(encoding="utf-8")
    assert "xplane_path" in ps1 and "UTF8Encoding" in ps1
    assert (ROOT / "installer" / "welcome.txt").is_file()
    assert (ROOT / "installer" / "extract_model.ps1").is_file()
    assert (ROOT / "installer" / "build.ps1").is_file()


def test_ensure_vosk_skips_ready_and_unknown(tmp_path, monkeypatch):
    ready = tmp_path / "vosk-model-small-ru-0.22"
    (ready / "am").mkdir(parents=True)
    calls = []
    monkeypatch.setattr("ru_atc.voice.download._download", lambda *a, **k: calls.append(a))
    assert ensure_vosk_model(ready) == ready
    assert calls == []
    unknown = tmp_path / "not-a-catalog-model"
    assert ensure_vosk_model(unknown) == unknown
    assert calls == []


def test_ensure_vosk_downloads_official_zip(tmp_path, monkeypatch):
    def fake(url, dest, reporthook=None):
        assert url == "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("vosk-model-small-ru-0.22/am/final.mdl", b"x")
            zf.writestr("vosk-model-small-ru-0.22/conf/model.conf", b"x")

    monkeypatch.setattr("ru_atc.voice.download._download", fake)
    dest = tmp_path / "models" / "vosk-model-small-ru-0.22"
    got = ensure_vosk_model(dest)
    assert (got / "conf" / "model.conf").is_file()
    assert not (tmp_path / "models" / "vosk-model-small-ru-0.22.zip").exists()


def test_safe_extract_rejects_parent_path(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", b"no")
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(ModelDownloadError):
            safe_extract(zf, tmp_path)
    assert not (tmp_path.parent / "evil.txt").exists()
