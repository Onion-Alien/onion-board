"""Which "Who's listening" mode suits each game? Tries every built-in destination mode
against every game profile.

    python scripts/dest_fit.py                          # test signals, every game profile
    python scripts/dest_fit.py --library --level        # your own sounds
    python scripts/dest_fit.py --profiles photon fivem_radio --json fit.json

Each sound goes: the mode (soundboard.destination, as the engine runs it) -> the
send stage (phase-aware mono + limiter) -> the game's own cleanup and voice gate
(codec_bench --defaults) -> its codec -> its proximity / radio model at close
range. Every mode changes the sound on purpose (harmonics for the bass the chat
drops, compression, a low-pass at the codec's ceiling), so plain distance from
the original always favours "off". Three numbers per mode instead, all spectral
distances in dB (codec_bench's "dist", lower is better):

  own     the mode's deliberate change: your sound with the mode vs. without
  chat    what the chat does to what the mode sends: in vs. out of the chat
  total   your sound without the mode vs. what the listener hears

and "bass", the energy left under 300 Hz against your original (0 = all of it;
the modes exist mostly to save it). A mode earns its place when it cuts "chat"
(and saves bass) by more than it adds in "own".

Run it from the bench environment (requirements-bench.txt) so the cleanup is the
real WebRTC / RNNoise code; elsewhere it falls back to chatsim's models.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import codec_bench as cb  # noqa: E402  (same folder: its sources and the chat's defaults)
from soundboard import codecsim, proxsim  # noqa: E402
from soundboard.codecsim import PROFILES, analyze, roundtrip  # noqa: E402
from soundboard.destination import BUILTIN, Processor  # noqa: E402
from soundboard.sendfx import Limiter, SmartMono  # noqa: E402

SR = codecsim.SR
DISCORD = ("discord", "discord_low", "discord_128")


def _blocks(fn, x: np.ndarray) -> np.ndarray:
    return np.concatenate([fn(x[i:i + 480].copy()) for i in range(0, len(x), 480)])


def shaped(x: np.ndarray, dest) -> np.ndarray:
    """x through the mode and the send stage, in the engine's 480-sample blocks."""
    if dest.active:
        proc = Processor(SR)
        x = _blocks(lambda b: proc.process(b, dest), x)
    lim, mix = Limiter(SR), SmartMono(SR)
    return _blocks(lambda b: lim.process(mix.process(b)), x)


def heard(x: np.ndarray, p, ff: str) -> np.ndarray:
    back = roundtrip(cb._defaults(x, p), p, ff)
    return proxsim.apply(back, p.proximity, 1.0) if p.proximity else back


def _bass(r: dict) -> float | None:
    lo = [d for _lo, hi, d in r["bands"] if hi <= 300 and d is not None]
    return float(np.mean(lo)) if lo else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--library", action="store_true")
    ap.add_argument("--level", action="store_true")
    ap.add_argument("--profiles", nargs="+", choices=sorted(PROFILES),
                    default=[k for k in PROFILES if k not in DISCORD])
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args()
    ff = codecsim.available()
    if not ff:
        print("ffmpeg with libopus not found", file=sys.stderr)
        return 2
    sources = cb._sources(args)
    off = BUILTIN[0]
    refs = [shaped(x, off) for _, x in sources]
    table: dict[str, dict[str, dict]] = {}
    for key in args.profiles:
        p = PROFILES[key]
        table[key] = {}
        for dest in BUILTIN:
            own, chat, total, bass = [], [], [], []
            for (_, x), ref in zip(sources, refs):
                sent = ref if dest is off else shaped(x, dest)
                out = heard(sent, p, ff)
                r = analyze(ref, out)
                total.append(r["spec_dist_db"])
                chat.append(analyze(sent, out)["spec_dist_db"])
                own.append(0.0 if dest is off else analyze(ref, sent)["spec_dist_db"])
                if (b := _bass(r)) is not None:
                    bass.append(b)
            table[key][dest.key] = {"own": float(np.mean(own)), "chat": float(np.mean(chat)),
                                    "total": float(np.mean(total)),
                                    "bass_db": float(np.mean(bass)) if bass else None}
        print(f"{key} ({p.games or p.label})", flush=True)
        for k, v in table[key].items():
            b = "" if v["bass_db"] is None else f"{v['bass_db']:+6.1f}"
            print(f"    {k:<9} own {v['own']:5.1f}  chat {v['chat']:5.1f}  "
                  f"total {v['total']:5.1f}  bass {b}", flush=True)
    print("\nspectral distances in dB, lower is better; bass = dB left under 300 Hz.")
    if args.json:
        Path(args.json).write_text(json.dumps(table, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
