"""Run audio through what Discord / a game does to it and print what's lost.

    python scripts/codec_bench.py                       # built-in test signals, every profile
    python scripts/codec_bench.py --library             # every sound in the library
    python scripts/codec_bench.py clip.wav other.mp3    # these files
    python scripts/codec_bench.py --profiles discord steam
    python scripts/codec_bench.py --json out.json       # also save the numbers
    python scripts/codec_bench.py --dest steam --profiles steam   # with the app's mode on
    python scripts/codec_bench.py --send                # through the app's send stage first
    python scripts/codec_bench.py --processing suppress agc gate   # voice cleanup left on
    python scripts/codec_bench.py --processing webrtc_ns webrtc_agc  # the real WebRTC code
    python scripts/codec_bench.py --list                # every profile: games, confidence
    python scripts/codec_bench.py --defaults            # each chat's own cleanup + voice gate
    python scripts/codec_bench.py --profiles svc lethal --defaults --at 10   # 10 m away
    python scripts/codec_bench.py --profiles dissonance --situation lethal:walkie

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
(soundboard.chatsim) before the codec, the way it is when it's left on; its
webrtc_* and rnnoise stages run the real libraries instead of the models
(soundboard.realproc, which needs the bench environment: requirements-bench.txt).
--defaults instead runs each profile's own cleanup and voice gate, as the game
ships it (outside the bench environment the real stages fall back to chatsim's
models, and the run says so). --at puts the listener that far away in the
proximity-chat profiles (soundboard.proxsim); --situation picks a listening
situation (behind a wall, over a radio) for every profile.
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
from soundboard import chatsim, proxsim, realproc  # noqa: E402
from soundboard.destination import BUILTIN_BY_KEY, Processor, cut_shares, makeup  # noqa: E402
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


def _process(x: np.ndarray, stages) -> np.ndarray:
    """The real libraries first, then the models, so `webrtc_ns webrtc_agc gate` is
    a real cleanup followed by a voice gate (the WebRTC module has none of its own)."""
    model = [s for s in stages if s in chatsim.STAGES]
    real = [s for s in stages if s in realproc.STAGES]
    if real:
        x = realproc.process(x, real)
    if model:
        x = chatsim.process(x, model)
    return x


# what a real stage becomes when its library isn't installed
_FALLBACK = {"webrtc_ns": "suppress", "webrtc_agc": "agc", "rnnoise": "suppress"}


def _defaults(x: np.ndarray, p) -> np.ndarray:
    """The profile's own cleanup, then its voice gate (none = push-to-talk)."""
    stages = list(p.cleanup)
    real = [s for s in stages if s in realproc.STAGES]
    if real and not realproc.available(real):
        stages = list(dict.fromkeys(_FALLBACK.get(s, s) for s in stages
                                    if s != "webrtc_hpf"))
    if stages:
        x = _process(x, stages)
    if p.gate_db is not None:
        y = chatsim.gate(chatsim._mono(x), threshold_db=p.gate_db, hang_s=p.gate_hang_s)
        x = np.repeat(y[:, None], 2, axis=1).astype(np.float32)
    return x


def _list() -> None:
    for key, p in PROFILES.items():
        clean = " + ".join(p.cleanup) or "none"
        gate = "push-to-talk" if p.gate_db is None else f"gate {p.gate_db:.0f} dB"
        prox = f"; proximity {p.proximity}" if p.proximity else ""
        print(f"{key:<14}{p.label} [{p.confidence}]")
        print(f"{'':<14}{p.games or '-'}")
        print(f"{'':<14}{p.rate // 1000} kHz, {p.bitrate_kbps} kbps{' CBR' if p.cbr else ''}, "
              f"{p.application}, {p.frame_ms} ms; cleanup {clean}; {gate}{prox}\n")


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
    ap.add_argument("--processing", nargs="+", choices=chatsim.STAGES + realproc.STAGES,
                    default=(), help="simulate the voice chat's mic cleanup being left on "
                    "(webrtc_* / rnnoise: the real libraries)")
    ap.add_argument("--defaults", action="store_true",
                    help="run each profile's own mic cleanup and voice gate (as shipped)")
    ap.add_argument("--at", type=float, metavar="DIST",
                    help="proximity profiles: the listener this far away (game units)")
    ap.add_argument("--situation", metavar="MODEL:VARIANT",
                    help="a proxsim listening situation for every profile, e.g. "
                         "lethal:occluded, lethal:walkie, pma_voice:radio, crewlink:vent")
    ap.add_argument("--list", action="store_true", help="list the profiles and exit")
    ap.add_argument("--json", metavar="FILE", help="also write the numbers as JSON")
    args = ap.parse_args()
    if args.list:
        _list()
        return 0
    if args.defaults and not realproc.available():
        print(f"(--defaults: {', '.join(realproc.missing())} not installed, so the real "
              "cleanup stages run as chatsim's models)", file=sys.stderr)

    real = [s for s in args.processing if s in realproc.STAGES]
    if real and not realproc.available(real):
        print(f"--processing {' '.join(real)} needs {', '.join(realproc.missing())}: "
              "run from the bench environment (pip install -r requirements-bench.txt)",
              file=sys.stderr)
        return 2
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
            if dest.lowcut:   # the sound's make-up for the cut, as Engine._render gives it
                x = x * np.float32(makeup(cut_shares(x, codecsim.SR).get(dest.lowcut, 0.0)))
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
            sent = _process(sent, args.processing)
        for key in args.profiles:
            p = PROFILES[key]
            try:
                back = roundtrip(_defaults(sent, p) if args.defaults else sent, p, ff)
                listen = args.situation or p.proximity
                if listen and (args.at is not None or args.situation):
                    back = proxsim.apply(back, listen, args.at or 0.0)
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
