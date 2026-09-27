"""Run audio through what Discord / a game does to it and print what's lost.

    python scripts/codec_bench.py                       # built-in test signals, every profile
    python scripts/codec_bench.py --library             # every sound in the library
    python scripts/codec_bench.py clip.wav other.mp3    # these files
    python scripts/codec_bench.py --profiles discord steam
    python scripts/codec_bench.py --json out.json       # also save the numbers
    python scripts/codec_bench.py --dest steam --profiles steam   # with the app's mode on
    python scripts/codec_bench.py --send                # through the app's send stage first
    python scripts/codec_bench.py --processing suppress agc gate   # voice cleanup left on

With --dest the "level" and band columns compare the codec's output against the
*shaped* input, so read the mode's own effect from the <100 and 100-300 columns
of a --dest run next to a plain one (the harmonics land in 100-300).

Per signal and profile: overall level change, the frequency ceiling the codec
really kept, the energy change in each band, the mono-downmix loss (independent
of the codec: what a mono mic capture does to our stereo), and the waveform SNR
(only comparable between runs; Opus isn't a waveform coder), the spectral
distance ("dist": frame by frame how different it sounds, lower is better; unlike
the band columns it hears noise fill and warble) and how much the listener's
decoder clips ("clip%"). --send runs the app's send stage (phase-aware mono +
limiter) first; --processing adds the voice chat's own mic cleanup
(soundboard.chatsim) before the codec, the way it is when it's left on.
Needs ffmpeg with libopus, the same ffmpeg the importer uses for m4a / video.
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
from soundboard import chatsim  # noqa: E402
from soundboard.destination import BUILTIN_BY_KEY, Processor  # noqa: E402
from soundboard.sendfx import Limiter, SmartMono  # noqa: E402

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
    ap.add_argument("--dest", metavar="MODE", choices=sorted(BUILTIN_BY_KEY),
                    help="run the audio through this destination mode first (what the app "
                         "does when the mode is on); use with the plain run to compare")
    ap.add_argument("--send", action="store_true",
                    help="run the app's send stage (phase-aware mono + limiter) first")
    ap.add_argument("--processing", nargs="+", choices=chatsim.STAGES, default=(),
                    help="simulate the voice chat's mic cleanup being left on")
    ap.add_argument("--json", metavar="FILE", help="also write the numbers as JSON")
    args = ap.parse_args()

    ff = codecsim.available()
    if not ff:
        print("ffmpeg with libopus not found; install ffmpeg (winget install Gyan.FFmpeg) first",
              file=sys.stderr)
        return 2

    heads = "".join(band_label(lo, hi).rjust(8) for lo, hi in BANDS)
    print(f"{'signal':<28}{'profile':<16}{'level':>7}{'ceiling':>9}{'mono':>7}{'snr':>6}"
          f"{'dist':>6}{'clip%':>7}  {heads}")
    print("-" * (28 + 16 + 7 + 9 + 7 + 6 + 6 + 7 + 2 + len(heads)))
    results = []
    dest = BUILTIN_BY_KEY[args.dest] if args.dest else None
    for name, x in _sources(args):
        if dest is not None:
            # blocks of 480 like the real callback, so filter state carries the same way
            proc = Processor(codecsim.SR)
            x = np.concatenate([proc.process(x[i:i + 480].copy(), dest)
                                for i in range(0, len(x), 480)])
        mono = mono_loss_db(x)
        sent = x
        if args.send:
            lim, mix = Limiter(codecsim.SR), SmartMono(codecsim.SR)
            sent = np.concatenate([lim.process(mix.process(x[i:i + 480]))
                                   for i in range(0, len(x), 480)])
        ref = sent      # what the app puts into the cable
        if args.processing:
            sent = chatsim.process(sent, args.processing)
        for key in args.profiles:
            p = PROFILES[key]
            try:
                back = roundtrip(sent, p, ff)
                # judged against what went into the cable, so --processing shows the
                # voice cleanup's damage (the send stage's own effect is by design;
                # compare clip% and a plain run for that)
                r = analyze(ref, back)
            except Exception as e:  # noqa: BLE001
                print(f"{name[:27]:<28}{key:<16}  failed: {e}")
                continue
            clip = float(np.mean(np.abs(back) >= 0.999)) * 100
            cells = "".join(_fmt(d).rjust(8) for _, _, d in r["bands"])
            print(f"{name[:27]:<28}{key:<16}{r['level_db']:+6.1f} {r['bandwidth_hz'] / 1000:7.1f}k"
                  f"{mono:+6.1f} {r['snr_db']:5.1f}{r['spec_dist_db']:6.1f}{clip:7.2f}  {cells}")
            results.append({"signal": name, "profile": key, "mono_loss_db": mono,
                            "clipped_pct": clip, **r})
        print()
    print("level / mono / bands in dB (negative = lost); ceiling = highest kHz still carried;")
    print("snr = waveform SNR, compare between runs only; dist = spectral distance in dB,")
    print("lower is better; clip% = samples the listener's decoder clips. Profiles:")
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
