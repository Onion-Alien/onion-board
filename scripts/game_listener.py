"""The listener's half of game_roundtrip.py: record what a game plays, and nothing else.

Runs on the listener's PC (a second PC or a laptop in the same lobby) and needs only
numpy and soundboard/appaudio.py next to it (the same per-program capture as the
app's Apps tab), so music, Discord and system sounds stay out of the recording:

    python game_listener.py VALORANT-Win64-Shipping.exe --out listener
    python game_listener.py cs2.exe --out listener --stop-file stop.txt

It records every running copy of each named program into <out>_<exe>.wav (48 kHz
float) until Ctrl+C, until --stop-file exists, or for --max-s seconds. Then, on the
sending PC:

    python scripts/game_roundtrip.py analyze <play dir> listener_<exe>.wav
"""
from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundboard import appaudio  # noqa: E402

SR = 48000


def pids(exe: str) -> list[int]:
    table = appaudio._process_table()
    return sorted({appaudio.root_pid(p, table) for p, (_, n) in table.items()
                   if n.lower() == exe.lower()})


def write_wav(path: Path, x: np.ndarray) -> None:
    """Mono 32-bit PCM (wave has no float), which soundfile and ffmpeg both read."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(4)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * (2 ** 31 - 1)).astype("<i4").tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe", nargs="+", help="the game's process name(s)")
    ap.add_argument("--out", default="listener")
    ap.add_argument("--stop-file", help="stop when this file appears")
    ap.add_argument("--max-s", type=float, default=1800.0)
    a = ap.parse_args()

    caps = []
    for exe in a.exe:
        for pid in pids(exe):
            chunks: list[np.ndarray] = []
            cap = appaudio.AppCapture(pid, lambda c, ch=chunks: ch.append(c[:, 0].copy()),
                                      name=exe)
            if cap.start():
                caps.append((exe, pid, cap, chunks))
                print(f"recording {exe} (pid {pid})", flush=True)
            else:
                print(f"can't record {exe} (pid {pid}): {cap.error}", flush=True)
    if not caps:
        raise SystemExit(f"none of {a.exe} is running (or none could be recorded)")

    t0 = time.time()
    stop = Path(a.stop_file) if a.stop_file else None
    try:
        while time.time() - t0 < a.max_s and not (stop and stop.exists()):
            if all(not c.running for _, _, c, _ in caps):
                print("every recorded program has closed", flush=True)
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    for exe, pid, cap, chunks in caps:
        cap.stop()
        x = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
        out = Path(f"{a.out}_{Path(exe).stem}{'' if len(caps) == 1 else f'_{pid}'}.wav")
        write_wav(out, x)
        peak = float(np.abs(x).max()) if len(x) else 0.0
        print(f"wrote {out}: {len(x) / SR:.1f} s, peak {peak:.3f}", flush=True)


if __name__ == "__main__":
    main()
