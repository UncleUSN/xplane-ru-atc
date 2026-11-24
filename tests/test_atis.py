"""АТИС, буква информации и погода из сима или METAR."""
from pathlib import Path

from ru_atc.atis import AtisBoard, letter_index, render_broadcast
from ru_atc.events import Transmission
from ru_atc.model import SimState
from ru_atc.sources.base import apply_raw
from ru_atc.weather import Weather, load_metar, parse_metar, qfe_mmhg, weather_for, weather_from_sim

from conftest import make_ctl
from test_controller import sim, tx


def test_metar_and_qfe():
    wx = parse_metar("UUEE 231200Z 24005MPS 9999 BKN020 M03/M05 Q0998 NOSIG")
    assert wx.wind_dir == 240 and wx.wind_ms == 5
    assert wx.visibility_m == 9999
    assert wx.clouds[0].coverage == "BKN" and wx.clouds[0].base_ft == 2000
    assert wx.temp_c == -3 and wx.dew_c == -5 and wx.qnh_hpa == 998
    knots = parse_metar("ULLI 231200Z 27010KT 10SM FEW040 05/02 A2992")
    assert knots.wind_ms == 5
    assert knots.visibility_m == 16090 or abs(knots.visibility_m - 16090) < 2
    assert knots.qnh_hpa == 1013
    # 630 ft / 27.3 ≈ 23.1 гПа вниз от 1013, затем в мм рт. ст.
    mm = qfe_mmhg(1013, 630)
    assert 740 <= mm <= 745


def test_letter_advances_on_weather_and_on_the_hour():
    board = AtisBoard()
    calm = Weather(qnh_hpa=1013, wind_dir=240, wind_ms=5)
    assert board.current("UUEE", calm, 10) == (0, "Альфа")
    assert board.current("UUEE", calm, 10)[1] == "Альфа"
    changed = Weather(qnh_hpa=1000, wind_dir=240, wind_ms=5)
    assert board.current("UUEE", changed, 10)[1] == "Браво"
    assert board.current("UUEE", changed, 11)[1] == "Чарли"
    assert letter_index("альфу") == 0
    assert letter_index("браво") == 1


def test_broadcast_speech_has_no_digits(airspace):
    ap = airspace.airports["UUEE"]
    wx = Weather(wind_dir=250, wind_ms=5, wind_gust_ms=8, visibility_m=9999,
                 clouds=[__import__("ru_atc.weather", fromlist=["CloudLayer"]).CloudLayer("BKN", 2000)],
                 temp_c=-3, dew_c=-5, qnh_hpa=998, source="sim")
    disp, speech = render_broadcast(ap, wx, "Альфа", "24C")
    assert "информация Альфа" in disp
    assert "QNH 998" in disp and "QFE" in disp and "Эшелон перехода" in disp
    assert "24C" in disp
    assert not any(ch.isdigit() for ch in speech)
    assert "альфа" in speech and "гектопаскал" in speech and "миллиметр" in speech


def test_sim_weather_datarefs_fill_state():
    state = apply_raw(SimState(), {
        "vis_m": 8000, "temp_c": 4, "dew_region_c": 1,
        "cloud_cov_0": 0.7, "cloud_base_0": 600,
        "qnh_pas": 99800, "wind_dir": 180, "wind_ms": 4,
    })
    assert state.vis_m == 8000 and state.temp_c == 4 and state.dew_c == 1
    assert state.cloud_cov[0] == 0.7
    wx = weather_from_sim(state)
    assert wx.visibility_m == 8000 and wx.temp_c == 4 and wx.dew_c == 1
    assert wx.clouds and wx.clouds[0].coverage == "BKN"
    assert wx.qnh_hpa == 998


def test_metar_file_used_away_from_the_field(tmp_path):
    folder = tmp_path / "Output" / "real weather"
    folder.mkdir(parents=True)
    (folder / "METAR.rwx").write_text(
        "ULLI 231200Z 18003MPS 8000 FEW010 02/01 Q1005\n", encoding="utf-8")
    got = load_metar(tmp_path, "ULLI")
    assert got is not None and got.qnh_hpa == 1005 and got.wind_ms == 3
    far = weather_for(SimState(qnh_hpa=1013), "ULLI", 800, tmp_path)
    assert far.source.startswith("METAR") and far.qnh_hpa == 1005
    near = weather_for(SimState(qnh_hpa=998, wind_dir=20, wind_kt=6), "ULLI", 2, tmp_path)
    assert near.source == "sim" and near.qnh_hpa == 998
    assert load_metar(tmp_path, "UUEE") is None
    assert Path(folder / "METAR.rwx").is_file()


def test_tuning_atis_plays_once_until_the_letter_changes(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    s.com1_khz = int(round(ctl.dep.atis_mhz * 1000))
    s.vis_m = 9999
    s.temp_c = 5
    s.dew_c = 2
    first = [e for e in ctl.update(s) if isinstance(e, Transmission) and e.kind == "atis"]
    assert len(first) == 1
    assert "Шереметьево" in first[0].display and "Альфа" in first[0].display
    assert "QNH" in first[0].display and not any(ch.isdigit() for ch in first[0].speech)
    again = [e for e in ctl.update(s) if isinstance(e, Transmission) and e.kind == "atis"]
    assert again == []


def test_pilot_can_ask_and_report_the_letter(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    asked = [e for e in ctl.on_pilot("Шереметьево-Деливери, дайте АТИС", s)
             if isinstance(e, Transmission) and e.kind == "atis"]
    assert asked and "Альфа" in asked[0].display
    ack = tx(ctl.on_pilot("информацию Альфа получил", s))
    assert ack and "принята" in ack[0].display
    assert ctl.atis_ack.get("UUEE") == 0
    clearance = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert "разрешено до Пулково" in clearance.display
    assert "информация" not in clearance.display


def test_wrong_letter_is_corrected_and_right_one_stops_the_reminder(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    bad = tx(ctl.on_pilot("информацию Браво получил", s))
    assert bad and "Альфа" in bad[0].display and "Браво" in bad[0].display
    assert ctl.atis_ack.get("UUEE") != 0
    reminded = tx(ctl.on_pilot("прошу разрешение до Пулково", s))[0]
    assert "информация Альфа" in reminded.display
    ctl.on_pilot("информацию альфу получил", s)
    quiet = tx(ctl.on_pilot("разрешите буксировку и запуск", sim(ctl, unit_type="ground")))
    assert quiet and "информация" not in quiet[0].display


def test_atis_ack_does_not_replace_a_clearance_request(cfg, airspace):
    from ru_atc.phraseology.parser import parse
    msg = parse("информация Альфа, прошу разрешение до Пулково")
    assert msg.intent == "request_clearance"
    assert msg.slots["atis"] == "альфа"
    assert parse("повторите").intent == "say_again"
    assert parse("повторите информацию").intent == "request_atis"
    assert parse("информацию чарли получил").intent == "atis_ack"
