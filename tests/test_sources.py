import struct

from ru_atc.datarefs import all_specs
from ru_atc.model import SimState, normalize_com_khz
from ru_atc.sources.base import apply_raw
from ru_atc.sources.udp import build_rref_request, parse_rref_packet
from ru_atc.sources.webapi import build_name_query, decode_update, group_specs


def test_rref_request_format():
    pkt = build_rref_request(5, 3, "sim/flightmodel/position/latitude")
    assert pkt[:5] == b"RREF\x00"
    assert len(pkt) == 5 + 8 + 400
    freq, idx = struct.unpack_from("<ii", pkt, 5)
    assert (freq, idx) == (5, 3)
    assert pkt[13:13 + 33] == b"sim/flightmodel/position/latitude"


def test_rref_parse():
    body = b"RREF," + struct.pack("<if", 0, 55.97) + struct.pack("<if", 7, 118700.0)
    vals = dict(parse_rref_packet(body))
    assert abs(vals[0] - 55.97) < 1e-4 and vals[7] == 118700.0


def test_webapi_query_and_grouping():
    q = build_name_query(["sim/a", "sim/b"])
    assert "filter[name]=sim/a" in q and "filter[name]=sim/b" in q and "fields=id%2Cname%2Cvalue_type" in q
    g = group_specs(all_specs(True))
    n1 = g["sim/cockpit2/engine/indicators/N1_percent"]
    assert sorted(s.index for s in n1) == [0, 1]


def test_webapi_decode_update():
    g = group_specs(all_specs(False))
    id_map = {101: g["sim/flightmodel/position/latitude"],
              102: g["sim/cockpit2/engine/indicators/N1_percent"],
              103: g["sim/cockpit2/radios/actuators/com1_frequency_hz_833"]}
    raw = decode_update({"101": 55.5, "102 ": [21.0, 22.0], "103": 118700, "999": 1}, id_map)
    assert raw == {"lat": 55.5, "n1_0": 21.0, "n1_1": 22.0, "com1_raw": 118700}


def test_apply_raw_units():
    s = apply_raw(SimState(), {"elev_m": 1000.0, "gs_ms": 100.0, "com1_raw": 118700, "baro_set_inhg": 29.92,
                               "qnh_pas": 99800.0, "on_ground": 0, "xpdr_mode": 3, "n2_1": 61.0,
                               "zibo_xpdr_pos": 5, "local_time_sec": 8 * 3600 + 120})
    assert abs(s.alt_msl_ft - 3280.84) < 0.1
    assert abs(s.gs_kt - 194.38) < 0.1
    assert s.com1_khz == 118700
    assert abs(s.baro_set_hpa - 1013.2) < 0.2
    assert abs(s.qnh_hpa - 998) < 0.01
    assert s.on_ground is False and s.xpdr_alt_reporting and s.n2[1] == 61.0
    assert s.local_time_sec == 8 * 3600 + 120
    assert any(spec.name == "sim/time/local_time_sec" and spec.optional
               for spec in all_specs(False))


def test_com_normalization():
    assert normalize_com_khz(118700) == 118700
    assert normalize_com_khz(118700000) == 118700
    assert normalize_com_khz(11870) == 118700
