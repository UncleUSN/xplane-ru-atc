"""UdpSource против поддельного X-Plane (UDP RREF)."""
import socket
import struct
import threading
import time

from ru_atc.sources.udp import UdpSource

VALUES = {"sim/flightmodel/position/latitude": 59.8, "sim/cockpit2/radios/actuators/com1_frequency_hz_833": 118100.0,
          "sim/cockpit2/engine/indicators/N1_percent[1]": 23.5}


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def fake_xplane(sock, stop):
    subs = {}
    sock.settimeout(0.2)
    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            if data[:5] == b"RREF\x00":
                freq, idx = struct.unpack_from("<ii", data, 5)
                name = data[13:].split(b"\x00")[0].decode()
                if freq > 0:
                    subs[idx] = (name, addr)
        except socket.timeout:
            pass
        by_addr = {}
        for idx, (name, addr) in subs.items():
            if name in VALUES:
                by_addr.setdefault(addr, b"RREF,")
                by_addr[addr] += struct.pack("<if", idx, VALUES[name])
        for addr, pkt in by_addr.items():
            sock.sendto(pkt, addr)


def test_udp_source():
    xp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    xp.bind(("127.0.0.1", 0))
    stop = threading.Event()
    threading.Thread(target=fake_xplane, args=(xp, stop), daemon=True).start()
    src = UdpSource("127.0.0.1", xp.getsockname()[1], listen_port=free_udp_port())
    src.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        snap = src.snapshot()
        if snap.com1_khz and snap.n1[1]:
            break
        time.sleep(0.05)
    s = src.snapshot()
    stop.set()
    src.stop()
    assert abs(s.lat - 59.8) < 1e-4
    assert s.com1_khz == 118100
    assert abs(s.n1[1] - 23.5) < 1e-4
    assert s.connected
