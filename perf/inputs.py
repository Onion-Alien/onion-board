"""What the runs work on, made up on the spot (the repo ships no audio or pictures):
sound files for the board and for importing, and trigger pictures for Onion Watch.
Written once per output folder and reused."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

SR = 48000


def tone(secs: float, seed: int) -> np.ndarray:
    """A few seconds of something sound-like: a chord that moves, a beat, some hiss."""
    rng = np.random.default_rng(seed)
    n = int(SR * secs)
    t = np.arange(n) / SR
    f = 110 * 2 ** (rng.integers(0, 24) / 12)
    x = sum(0.12 / k * np.sin(2 * np.pi * f * k * t * (1 + 0.002 * np.sin(t)))
            for k in (1, 2, 3, 5))
    beat = (np.sin(2 * np.pi * 2 * t) > 0.6) * 0.15 * rng.standard_normal(n)
    x = x + beat + 0.005 * rng.standard_normal(n)
    fade = np.minimum(1, np.minimum(t / 0.01, (secs - t) / 0.05))
    x = x * fade
    return np.stack([x, 0.9 * x], 1).astype(np.float32)


def write_wav(path: Path, data: np.ndarray):
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, SR, subtype="PCM_16")


def board_sounds(folder: Path, n: int) -> list[dict]:
    """The board's library at start: n sounds of 1-8 s."""
    out = []
    for i in range(n):
        p = folder / f"board{i:03d}.wav"
        if not p.exists():
            write_wav(p, tone(1 + (i * 7) % 8, i))
        out.append({"id": f"s{i}", "name": f"Sound {i}", "file": str(p)})
    return out


def import_sounds(folder: Path, short: int = 8, long: int = 2, long_s: float = 150) -> list[str]:
    """Files to import: `short` of 2-6 s and `long` long songs."""
    out = []
    for i in range(short):
        p = folder / f"new{i:02d}.wav"
        if not p.exists():
            write_wav(p, tone(2 + i % 5, 100 + i))
        out.append(str(p))
    for i in range(long):
        p = folder / f"song{i}.wav"
        if not p.exists():
            write_wav(p, tone(long_s, 200 + i))
        out.append(str(p))
    return out


def png(path: Path, rgb: np.ndarray):
    """A plain RGB PNG (h x w x 3, uint8), no image library needed."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def trigger_picture(path: Path, k: int):
    """A HUD-like banner: blocks and bars, different for every k."""
    rng = np.random.default_rng(1000 + k)
    w, h = 120 + (k % 5) * 24, 36 + (k % 3) * 10
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = rng.integers(20, 90, 3)
    for _ in range(6):
        x0, y0 = rng.integers(0, w - 10), rng.integers(0, h - 6)
        img[y0:y0 + rng.integers(3, 12), x0:x0 + rng.integers(6, 40)] = rng.integers(120, 255, 3)
    png(path, img)


def triggers(folder: Path, n: int) -> dict:
    """An Onion Watch `screen` setting with n triggers (the first 50 in "triggers",
    the rest in "more_triggers", as the add-on saves them), watching off."""
    raws = []
    for i in range(n):
        p = folder / f"trigger{i:03d}.png"
        if not p.exists():
            trigger_picture(p, i)
        raws.append({"id": f"t{i}", "name": f"Trigger {i}", "images": [str(p)],
                     "sounds": [f"s{i % 10}"], "cooldown": 3.0})
    return {"triggers": raws[:50], "more_triggers": raws[50:], "on": False, "interval_ms": 500}
