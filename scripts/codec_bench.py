"""Run audio through what Discord / a game does to it and print what's lost.

    python scripts/codec_bench.py                       # built-in test signals, every profile
    python scripts/codec_bench.py --library             # every sound in the library
    python scripts/codec_bench.py clip.wav other.mp3    # these files
    python scripts/codec_bench.py --profiles discord steam
    python scripts/codec_bench.py --json out.json       # also save the numbers

Per signal and profile: overall level change, the frequency ceiling the codec
really kept, the energy change in each band, the mono-downmix loss (independent
of the codec: what a mono mic capture does to our stereo), and the waveform SNR
(only comparable between runs; Opus isn't a waveform coder). Needs ffmpeg with
libopus, the same ffmpeg the importer uses for m4a / video.
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

from soundboard import codecsim  # noqa: E402
from soundboard.codecsim import (BANDS, PROFILES, SIGNALS, analyze, band_label,  # noqa: E402
                                 mono_loss_db, roundtrip)

MAX_S = 20.0   # longest stretch of a file to analyse (the middle of it)


def _clip(x: np.ndarray) -> np.ndarray:
    n = int(MAX_S * codecsim.SR)
    if len(x) <= n:
        return x
    start = (len(x) - n) // 2
    return x[start:start + n]


def _sources(args) -> list[tuple[str, np.ndarray]]:
    from soundboard import library
    out = []
    if args.library:
        cfg = library.Config.load()
        for meta in cfg.sounds:
            try:
                data = library.to_float32(library.load_sound(meta))
            except Exception as e:  # noqa: BLE001 - one bad file shouldn't stop the run
                print(f"  skip {meta.name}: {e}", file=sys.stderr)
                continue
            if args.level and meta.level_gain:
                data = data * np.float32(meta.level_gain * meta.volume)
            out.append((meta.name, _clip(data)))
    for f in args.files:
        out.append((Path(f).name, _clip(library.decode(f))))
    if not out:
        for name, fn in SIGNALS.items():
            out.append((name, fn()))
    return out


def _fmt(d: float | None) -> str:
    return "   —  " if d is None else f"{d:+5.1f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="audio files to run (default: built-in test signals)")
    ap.add_argument("--library", action="store_true", help="run every sound in the library")
    ap.add_argument("--level", action="store_true",
                    help="with --library: apply each sound's levelling gain and volume first")
    ap.add_argument("--profiles", nargs="+", choices=sorted(PROFILES), default=sorted(PROFILES))
    ap.add_argument("--json", metavar="FILE", help="also write the numbers as JSON")
    args = ap.parse_args()

    ff = codecsim.available()
    if not ff:
        print("ffmpeg with libopus not found; install ffmpeg (winget install Gyan.FFmpeg) first",
              file=sys.stderr)
        return 2

    heads = "".join(band_label(lo, hi).rjust(8) for lo, hi in BANDS)
    print(f"{'signal':<28}{'profile':<16}{'level':>7}{'ceiling':>9}{'mono':>7}{'snr':>6}  {heads}")
    print("-" * (28 + 16 + 7 + 9 + 7 + 6 + 2 + len(heads)))
    results = []
    for name, x in _sources(args):
        mono = mono_loss_db(x)
        for key in args.profiles:
            p = PROFILES[key]
            try:
                r = analyze(x, roundtrip(x, p, ff))
            except Exception as e:  # noqa: BLE001
                print(f"{name[:27]:<28}{key:<16}  failed: {e}")
                continue
            cells = "".join(_fmt(d).rjust(8) for _, _, d in r["bands"])
            print(f"{name[:27]:<28}{key:<16}{r['level_db']:+6.1f} {r['bandwidth_hz'] / 1000:7.1f}k"
                  f"{mono:+6.1f} {r['snr_db']:5.1f}  {cells}")
            results.append({"signal": name, "profile": key, "mono_loss_db": mono, **r})
        print()
    print("level / mono / bands in dB (negative = lost); ceiling = highest kHz still carried;")
    print("snr = waveform SNR, compare between runs only. Profiles:")
    for key in args.profiles:
        p = PROFILES[key]
        print(f"  {key:<14} {p.label}: {p.bitrate_kbps} kbps, {p.rate // 1000} kHz "
              f"{'mono' if p.channels == 1 else 'stereo'}, {p.application}. {p.note}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
