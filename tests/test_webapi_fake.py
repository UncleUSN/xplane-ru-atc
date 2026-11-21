"""Интеграционный тест WebApiSource против поддельного сервера X-Plane (REST + WebSocket на одном порту)."""
import asyncio
import json
import socket
import threading
import time
import urllib.parse

import pytest

websockets = pytest.importorskip("websockets")
from websockets.asyncio.server import serve  # noqa: E402
from websockets.http11 import Response  # noqa: E402
from websockets.datastructures import Headers  # noqa: E402

from ru_atc.sources.webapi import WebApiSource  # noqa: E402

DATAREFS = {
    "sim/flightmodel/position/latitude": (1001, "double", 55.97),
    "sim/flightmodel/position/longitude": (1002, "double", 37.41),
    "sim/cockpit2/radios/actuators/com1_frequency_hz_833": (1003, "int", 120875),
    "sim/cockpit2/engine/indicators/N2_percent": (1004, "float_array", [61.0, 62.0, 0, 0]),
    "sim/flightmodel/failures/onground_any": (1005, "int", 1),
}
SUBSCRIBED = []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(status, obj):
    body = json.dumps(obj).encode()
    return Response(status, "OK" if status == 200 else "ERR",
                    Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))]), body)


def process_request(conn, request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    u = urllib.parse.urlparse(request.path)
    if u.path == "/api/capabilities":
        return http_json(200, {"api": {"versions": ["v1", "v2"]}, "x-plane": {"version": "12.1.4"}})
    if u.path == "/api/v2/datarefs":
        q = urllib.parse.parse_qs(u.query)
        names = q.get("filter[name]", [])
        unknown = [n for n in names if n not in DATAREFS]
        if unknown:
            return http_json(404, {"error_code": "invalid_dataref_name", "error_message": unknown[0]})
        return http_json(200, {"data": [{"id": DATAREFS[n][0], "name": n, "value_type": DATAREFS[n][1]} for n in names]})
    return http_json(404, {"error_code": "not_found"})


async def handler(ws):
    msg = json.loads(await ws.recv())
    assert msg["type"] == "dataref_subscribe_values"
    SUBSCRIBED.extend(msg["params"]["datarefs"])
    await ws.send(json.dumps({"req_id": msg["req_id"], "type": "result", "success": True}))
    by_id = {v[0]: v for v in DATAREFS.values()}
    data = {}
    for d in msg["params"]["datarefs"]:
        val = by_id[d["id"]][2]
        if "index" in d:
            val = [val[i] for i in d["index"]]
        data[str(d["id"])] = val
    await ws.send(json.dumps({"type": "dataref_update_values", "data": data}))
    await asyncio.sleep(5)


def run_server(port, ready):
    async def main():
        async with serve(handler, "127.0.0.1", port, process_request=process_request):
            ready.set()
            await asyncio.sleep(10)
    asyncio.run(main())


def test_webapi_source_against_fake_server():
    port = free_port()
    ready = threading.Event()
    threading.Thread(target=run_server, args=(port, ready), daemon=True).start()
    assert ready.wait(5)
    src = WebApiSource("127.0.0.1", port, use_zibo=True)
    src.start()
    deadline = time.time() + 8
    while time.time() < deadline and src.snapshot().lat == 0:
        time.sleep(0.1)
    src.stop()
    s = src.snapshot()
    assert abs(s.lat - 55.97) < 1e-6 and abs(s.lon - 37.41) < 1e-6
    assert s.com1_khz == 120875
    assert s.n2 == [61.0, 62.0]
    assert s.on_ground is True
    n2 = [d for d in SUBSCRIBED if d["id"] == 1004][0]
    assert n2["index"] == [0, 1]
    assert "laminar/B738/knob/transponder_pos" in src.missing   # нет в фейке — пропущен, не падаем
