"""Wire format between the app and a service module (stdlib only).

The app listens on 127.0.0.1, launches the module with `--port N --token T`, and
the module connects back. Every message is a frame:

    1 byte kind | 4 bytes little-endian length | payload

    b"J"  a UTF-8 JSON object (both directions)
    b"A"  app -> module: mic audio, int16 mono at AUDIO_RATE

The module's first frame must be {"type": "hello", "token": T}; the app drops a
connection that gets it wrong (any local program could otherwise connect).

Messages a module sends: hello, status {text}, ready, vad {speaking},
partial {text}, final {text}, error {text}. The app sends: config {...}, quit.

Service modules ship their own copy of this file (they run in their own Python and
can't import the app); tests/test_speech.py checks the copies still agree.
"""
from __future__ import annotations

import json
import socket
import struct

JSON = b"J"
AUDIO = b"A"
AUDIO_RATE = 16000
MAX_FRAME = 16 << 20
_HEAD = struct.Struct("<cI")


def send(sock: socket.socket, kind: bytes, payload: bytes) -> None:
    sock.sendall(_HEAD.pack(kind, len(payload)) + payload)


def send_json(sock: socket.socket, obj: dict) -> None:
    send(sock, JSON, json.dumps(obj).encode("utf-8"))


def _exact(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def recv(sock: socket.socket) -> tuple[bytes, bytes] | None:
    """(kind, payload), or None when the other side closed the connection."""
    head = _exact(sock, _HEAD.size)
    if head is None:
        return None
    kind, n = _HEAD.unpack(head)
    if n > MAX_FRAME:
        raise ValueError(f"frame too large ({n} bytes)")
    payload = _exact(sock, n) if n else b""
    if payload is None:
        return None
    return kind, payload


def decode_json(payload: bytes) -> dict:
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    return obj
