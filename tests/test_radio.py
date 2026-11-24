"""Автонастройка COM1: флаг, очередь контроллера, Web API и UDP."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ru_atc.app import App
from ru_atc.controller import PendingReadback
from ru_atc.radio import COM1_ACTIVE, COM1_FLIP, COM1_STANDBY, describe_tune, khz_value, parse_auto_tune
from ru_atc.sources.udp import build_cmnd, build_dref
from ru_atc.sources.webapi import WebApiSource

from conftest import make_ctl
from test_controller import sim


def test_flag_defaults_off(cfg):
    assert cfg["radio"]["auto_tune_com1"] is False
    assert parse_auto_tune(False) is False
    assert parse_auto_tune("true") is True
    assert parse_auto_tune("off") is False
    with pytest.raises(ValueError):
        khz_value(100)


def test_auto_tune_off_does_not_queue(cfg, airspace):
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    ctl.on_pilot("подтверждаю", s)
    assert ctl.handoff_to is not None and ctl.handoff_to.type == "ground"
    assert ctl.take_tune() is None


def test_auto_tune_queues_frequency_when_handoff_is_spoken(cfg, airspace):
    cfg["radio"]["auto_tune_com1"] = True
    ctl = make_ctl(cfg, airspace)
    s = sim(ctl)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    assert ctl.take_tune() is None
    ctl.on_pilot("подтверждаю", s)
    assert ctl.take_tune() == ctl.dep.unit("ground").khz == 121800


def test_readback_still_closes_after_radio_moved(cfg, airspace):
    cfg["radio"]["auto_tune_com1"] = True
    ctl = make_ctl(cfg, airspace)
    tower = ctl.dep.unit("tower")
    radar = ctl.dep.unit("radar")
    s = sim(ctl, unit_type="radar")
    ctl.controlling = tower
    ctl.handoff_to = radar
    ctl.pending = PendingReadback(items={"freq": radar.freq}, t=s.t, unit=tower, seq=3)
    ctl.on_pilot("понял", s)
    assert ctl.pending is None
    assert ctl.controlling is not None and ctl.same_unit(ctl.controlling, radar)
    assert ctl.handoff_to is None


def test_app_toggle_does_not_persist_by_itself(cfg, airspace):
    cfg["sim"]["source"] = "mock"
    cfg["radio"]["auto_tune_com1"] = False
    app = App(cfg, demo=True, no_voice=True)
    assert app.ctl.auto_tune_com1 is False
    app.set_auto_tune(True)
    assert app.ctl.auto_tune_com1 is True
    app.set_auto_tune(False)
    assert app.ctl.auto_tune_com1 is False
    # airspace fixture keeps the import used: демо строится по тем же аэропортам.
    assert app.ctl.dep.icao == airspace.airports["UUEE"].icao


def test_udp_packets_name_the_zibo_compatible_datarefs():
    standby = build_dref(COM1_STANDBY, 121800)
    assert standby.startswith(b"DREF\x00")
    assert COM1_STANDBY.encode() in standby
    assert len(standby) == 5 + 4 + 500
    active = build_dref(COM1_ACTIVE, 121800)
    assert COM1_ACTIVE.encode() in active
    cmd = build_cmnd(COM1_FLIP)
    assert cmd == b"CMND\x00" + COM1_FLIP.encode()
    assert "standy_flip" in COM1_FLIP
    assert "резерв" in describe_tune(121800, flipped=True, wrote_active=True)


class _Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode() or "{}")

    def do_GET(self):
        name = ""
        if "filter[name]=" in self.path:
            name = self.path.split("filter[name]=", 1)[1].split("&", 1)[0]
            name = name.replace("%2F", "/")
        if "standby" in name:
            item = {"id": 10, "name": COM1_STANDBY}
        elif name == COM1_ACTIVE:
            item = {"id": 11, "name": COM1_ACTIVE}
        elif "standy_flip" in name:
            item = {"id": 20, "name": COM1_FLIP}
        else:
            item = None
        self._json({"data": [item] if item else []})

    def do_PATCH(self):
        self.server.calls.append(("PATCH", self.path, self._body()))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        self.server.calls.append(("POST", self.path, self._body()))
        self._json({"data": True})

    def log_message(self, *_args):
        return


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.calls = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_webapi_sets_standby_flips_and_writes_active():
    server = _serve()
    try:
        port = server.server_address[1]
        src = WebApiSource("127.0.0.1", port, api_version="v2")
        src.api_ver = "v2"
        ok, note = src.tune_com1(121800)
        assert ok and "121.800" in note
        kinds = [call[0] for call in server.calls]
        assert kinds == ["PATCH", "POST", "PATCH"]
        assert server.calls[0][2] == {"data": 121800}
        assert server.calls[0][1].endswith("/datarefs/10/value")
        assert server.calls[1][2] == {"duration": 0}
        assert server.calls[1][1].endswith("/command/20/activate")
        assert server.calls[2][1].endswith("/datarefs/11/value")
        assert server.calls[2][2] == {"data": 121800}
    finally:
        server.shutdown()


def test_webapi_v1_writes_active_without_flip_command():
    server = _serve()
    try:
        src = WebApiSource("127.0.0.1", server.server_address[1], api_version="v1")
        src.api_ver = "v1"
        ok, note = src.tune_com1(118100)
        assert ok and "активная" in note
        assert [call[0] for call in server.calls] == ["PATCH", "PATCH"]
        assert server.calls[1][2] == {"data": 118100}
    finally:
        server.shutdown()


def test_tune_before_connect_is_a_clean_failure():
    src = WebApiSource("127.0.0.1", 9, api_version="v2")
    ok, note = src.tune_com1(121800)
    assert ok is False and "не подключен" in note


def test_udp_tune_sends_three_datagrams():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    from ru_atc.sources.udp import UdpSource
    src = UdpSource("127.0.0.1", port, listen_port=0)
    src.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ok, note = src.tune_com1(131500)
        assert ok and "131.500" in note
        sock.settimeout(1)
        packets = [sock.recv(2048) for _ in range(3)]
        assert packets[0].startswith(b"DREF\x00") and COM1_STANDBY.encode() in packets[0]
        assert packets[1].startswith(b"CMND\x00") and COM1_FLIP.encode() in packets[1]
        assert packets[2].startswith(b"DREF\x00") and COM1_ACTIVE.encode() in packets[2]
    finally:
        src.sock.close()
        sock.close()
