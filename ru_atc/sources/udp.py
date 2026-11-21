"""Резервный источник: классический UDP-протокол RREF (порт 49000).

Запрос:  b"RREF\\0" + int32 freq + int32 index + char[400] имя_dataref[индекс]   (little-endian)
Ответ:   b"RREF" + 1 байт + N x (int32 index, float32 value)
freq=0 отменяет подписку. Значения приходят как float32 (для lat/lon точность ~1 м, достаточно).
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
from typing import Dict, List, Tuple

from .base import DataSource
from ..datarefs import all_specs

log = logging.getLogger(__name__)


def build_rref_request(freq: int, index: int, name: str) -> bytes:
    payload = name.encode("ascii")[:399]
    return b"RREF\x00" + struct.pack("<ii", freq, index) + payload.ljust(400, b"\x00")


def parse_rref_packet(data: bytes) -> List[Tuple[int, float]]:
    if not data.startswith(b"RREF") or len(data) < 5:
        return []
    body = data[5:]
    out = []
    for off in range(0, len(body) - 7, 8):
        idx, val = struct.unpack_from("<if", body, off)
        out.append((idx, val))
    return out


class UdpSource(DataSource):
    name = "udp"

    def __init__(self, host: str = "127.0.0.1", port: int = 49000, listen_port: int = 49010,
                 freq: int = 5, use_zibo: bool = True) -> None:
        super().__init__()
        self.addr = (host, port)
        self.listen_port = listen_port
        self.freq = freq
        self.specs = all_specs(use_zibo)
        self._stop = threading.Event()
        self.sock: socket.socket | None = None

    def start(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", self.listen_port))
        self.sock.settimeout(1.0)
        self._subscribe(self.freq)
        threading.Thread(target=self._run, name="xp-udp", daemon=True).start()

    def _subscribe(self, freq: int) -> None:
        for i, s in enumerate(self.specs):
            name = s.name if s.index is None else f"{s.name}[{s.index}]"
            self.sock.sendto(build_rref_request(freq, i, name), self.addr)

    def stop(self) -> None:
        self._stop.set()
        try:
            self._subscribe(0)
            self.sock.close()
        except Exception:
            pass

    def _run(self) -> None:
        silent = 0
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                silent += 1
                if silent % 5 == 0:   # X-Plane перезапущен — переподписываемся
                    self._subscribe(self.freq)
                continue
            except OSError:
                break
            silent = 0
            raw: Dict[str, float] = {}
            for idx, val in parse_rref_packet(data):
                if 0 <= idx < len(self.specs):
                    raw[self.specs[idx].key] = val
            if raw:
                self._update_raw(raw)
