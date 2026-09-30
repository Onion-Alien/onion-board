"""Real in-game voice round trip: what does another player actually hear?

discord_roundtrip.py records a second client on the same PC. A game rarely runs
twice on one PC, so this splits the job in two and needs a friend (or a second PC)
in the same lobby / party / proximity range:

  1. You, with your game's mic set to the cable (and nothing else feeding it):

         python scripts/game_roundtrip.py play --out cs2           # raw, then the app
         python scripts/game_roundtrip.py play --modes onion+game --dest game

     It sends a start chirp, then the test signals, once per mode, and saves what
     went into the cable (cs2/sent_<mode>.wav) and the timing (cs2/play.json).

  2. The listener records their game audio for the whole run with anything that
     saves a WAV / MP3 / FLAC: OBS (audio only), Audacity on "Windows WASAPI
     loopback", ShareX. Game music and effects off or low, stand still near you in
     proximity games. They send you the file.

  3. You:

         python scripts/game_roundtrip.py analyze cs2 listener.wav

     finds each mode's start chirp in their recording and reports what the game did
     to each signal: level, per-band change, the frequency response from the sweep,
     how much of the first 30 ms of a sound after silence survived (a voice gate),
     and the level over time of steady noise (noise suppression).

--ptt KEY holds the game's push-to-talk key during each run, the way the app's Auto
push-to-talk does. Games under kernel anti-cheat (Valorant) ignore injected keys: there
the player has to hold the key, and on voice activation only speech gets sent.

If the game *can* run twice on one PC (a second Steam account in a sandbox, a
game with a local test mode), `play --listener game.exe` records the second copy
by process loopback, the way discord_roundtrip.py does, and analyses at once.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import soxr
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord_roundtrip as rt  # noqa: E402  (same folder: its signals and analysis)
from soundboard import destination, winkeys  # noqa: E402
from soundboard.engine import Engine  # noqa: E402
from soundboard.library import decode, level_gain  # noqa: E402

SR = rt.SR
CHIRP_S = 0.6


def chirp() -> np.ndarray:
    """A 400 Hz -> 3 kHz upsweep: in every voice codec's band, gate-proof (loud from
    the first sample) and unlike anything in a game, so it's found reliably."""
    t = np.arange(int(CHIRP_S * SR)) / SR
    f0, f1 = 400.0, 3000.0
    k = (f1 - f0) / CHIRP_S
    x = 0.5 * np.sin(2 * np.pi * (f0 * t + k * t * t / 2))
    ramp = np.linspace(0, 1, 240)
    x[:240] *= ramp
    x[-240:] *= ramp[::-1]
    return x.astype(np.float32)


def find_chirps(rec: np.ndarray, count: int, min_gap_s: float) -> list[int]:
    """Sample positions of the `count` strongest chirps, at least min_gap_s apart, in order."""
    c = chirp()
    corr = np.abs(fftconvolve(rec, c[::-1], mode="valid"))
    norm = np.sqrt(fftconvolve(rec ** 2, np.ones(len(c)), mode="valid")) + 1e-9
    score = corr / norm
    picks = []
    gap = int(min_gap_s * SR)
    order = np.argsort(score)[::-1]
    for i in order:
        if all(abs(int(i) - p) > gap for p in picks):
            picks.append(int(i))
            if len(picks) == count:
                break
    return sorted(picks)


def send(track: np.ndarray, mode: str, dest: str, sound_vol: float,
         ptt: str = "") -> np.ndarray:
    """Play one run into the cable and return what reached the cable's far end. With
    `ptt`, hold that key for the whole run, as the app's Auto push-to-talk does."""
    cable: list[np.ndarray] = []
    ins = sd.InputStream(SR, channels=2, device=rt.wasapi("CABLE Output"), dtype="float32",
                         callback=lambda d, *_: cable.append(d.copy()))
    ins.start()
    if ptt and not winkeys.press(ptt):
        print(f"  ! couldn't press {ptt}", flush=True)
    try:
        return _send(track, mode, dest, sound_vol, ins, cable)
    finally:
        if ptt:
            winkeys.release(ptt)


def _send(track, mode, dest, sound_vol, ins, cable) -> np.ndarray:
    time.sleep(0.3)
    if mode == "raw":
        sd.play(track, SR, device=rt.wasapi("CABLE Input"))
        sd.wait()
    else:
        eng = Engine()
        eng.set_main_device(sd.query_devices(rt.wasapi("CABLE Input"))["name"])
        eng.sound_vol, eng.send_mono, eng.limiter_on = sound_vol, True, True
        eng.dest = destination.BUILTIN_BY_KEY[dest] if mode.startswith("onion+") else None
        eng.play("roundtrip", track, level_gain(track))
        time.sleep(len(track) / SR)
        eng.shutdown()
    time.sleep(1.0)
    ins.stop()
    ins.close()
    return np.concatenate(cable)[:, 0]


def cmd_play(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    body, marks = rt.signals(a.song)
    lead = np.zeros((SR, 2), np.float32)
    c = np.repeat(chirp()[:, None], 2, 1)
    # chirp, 1 s, then the signals (their marks are relative to the body's start)
    track = np.concatenate([lead, c, lead, body])
    offset = len(lead) + len(c) + len(lead)
    modes = a.modes.split(",")
    rec = None
    if a.listener:
        rec = rt.Recorder(a.listener)
        rec.__enter__()
    t0 = time.time()
    starts = []
    try:
        for mode in modes:
            print(f"== {mode}", flush=True)
            starts.append(round(time.time() - t0, 2))
            cable = send(track, mode, a.dest, a.sound_vol, a.ptt)
            sf.write(out / f"sent_{mode}.wav", cable, SR)
            time.sleep(2.0)
    finally:
        if rec is not None:
            rec.__exit__()
    meta = {"modes": modes, "dest": a.dest, "starts_s": starts, "offset": offset,
            "track_len": len(track), "marks": marks, "song": a.song}
    (out / "play.json").write_text(json.dumps(meta, indent=1))
    print(f"saved {out}. Now the listener's recording: "
          f"python scripts/game_roundtrip.py analyze {out} <their file>")
    if rec is not None:
        _, ear = rec.result()
        sf.write(out / "listener.wav", ear, SR)
        analyze(out, ear)


def analyze(out: Path, ear: np.ndarray) -> dict:
    meta = json.loads((out / "play.json").read_text())
    modes, n = meta["modes"], meta["track_len"]
    marks = [tuple(m) for m in meta["marks"]]
    body, _ = rt.signals(meta.get("song"))
    src = body[:, 0]
    found = find_chirps(ear, len(modes), min_gap_s=n / SR * 0.8)
    if len(found) < len(modes):
        raise SystemExit(f"found {len(found)} start chirp(s) for {len(modes)} runs: "
                         "did the recording cover the whole run?")
    lead = int(SR)                        # silence between the chirp and the signals
    results = {}
    for mode, at in zip(modes, found):
        sent = sf.read(out / f"sent_{mode}.wav", dtype="float32")[0]
        if sent.ndim > 1:
            sent = sent[:, 0]
        # line the cable recording up on its own chirp, then both on the body
        k = find_chirps(sent, 1, 1.0)[0]
        cable = sent[k + len(chirp()) + lead:]
        e = ear[at + len(chirp()) + lead:at + n]
        e = e[rt.lag(cable, e, max_s=0.5):]
        floor = rt.db(ear[max(at - SR, 0):at - SR // 10])
        print(f"== {mode}: chirp at {at / SR:.1f} s, background {floor:.0f} dB")
        if floor > -50:
            print("  ! the listener's recording has game sound under it; quiet parts read "
                  "high and the gate / noise numbers are unreliable")
        res = rt.analyze(src, cable, e, marks)
        for name, m in res.items():
            print(f"  {name}: {json.dumps(m)}")
        results[mode] = res
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(f"wrote {out / 'results.json'}")
    return results


def cmd_analyze(a) -> None:
    out = Path(a.dir)
    x, rate = decode_any(a.recording)
    analyze(out, x if rate == SR else soxr.resample(x, rate, SR, quality="VHQ"))


def decode_any(path: str) -> tuple[np.ndarray, int]:
    try:
        x, rate = sf.read(path, dtype="float32", always_2d=True)
        return x.mean(axis=1), rate
    except RuntimeError:                  # mp3 / m4a / video: through ffmpeg
        return decode(path)[:, 0], SR


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play", help="send the test signals into the cable")
    p.add_argument("--modes", default="raw,onion,onion+dest",
                   help="raw = straight into the cable; onion = through the engine; "
                        "onion+dest = with the --dest mode on")
    p.add_argument("--dest", default="game", choices=sorted(destination.BUILTIN_BY_KEY))
    p.add_argument("--song", help="also send 15 s of this file (from 0:30)")
    p.add_argument("--sound-vol", type=float, default=1.0)
    p.add_argument("--ptt", default="", help="hold this key during each run (the game's "
                   "push-to-talk, e.g. V), as the app's Auto push-to-talk does")
    p.add_argument("--listener", help="a second copy of the game on this PC: its exe")
    p.add_argument("--out", default="game-roundtrip-out")
    q = sub.add_parser("analyze", help="compare the listener's recording with what was sent")
    q.add_argument("dir", help="the folder play wrote")
    q.add_argument("recording", help="the listener's recording of the game")
    a = ap.parse_args()
    (cmd_play if a.cmd == "play" else cmd_analyze)(a)


if __name__ == "__main__":
    main()
