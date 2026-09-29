"""Real voice-chat round trip: what does a listener in the call actually get?

codec_bench.py simulates Discord; this measures it. Set up once:

  * your Discord: input device = CABLE Output (the app's virtual mic)
  * a second client in the same call on another account (Discord Canary installs
    beside Discord and can log in separately), its mic muted

Then, with nothing else talking into the cable:

    python scripts/discord_roundtrip.py                  # raw, onion, onion+discord
    python scripts/discord_roundtrip.py --modes onion    # just the app, your settings
    python scripts/discord_roundtrip.py --listen 20      # 20 s of you talking (mic path)

The listener is recorded by process loopback (soundboard.appaudio, the Apps tab's
capture), so its output device and volume don't matter, muted speakers included.
The cable's far end (CABLE Output) is recorded at the same time, which splits every
change into what the app did (source -> cable) and what the chat did (cable -> ear).

Modes: raw = the file straight into the cable (what a plain soundboard does);
onion = through the engine with limiter, mono and levelling on; onion+discord = the
same with the Discord destination mode. Signals: three 55 Hz booms after silence,
a 60 Hz-18 kHz sweep, 6 s of pink noise, speech-like noise and, with --song, 15 s
of any file. WAVs and results.json land in --out.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundboard import appaudio, codecsim, destination  # noqa: E402
from soundboard.engine import Engine  # noqa: E402
from soundboard.library import _ffmpeg, level_gain  # noqa: E402

SR = 48000
BANDS = ((50, 120), (120, 300), (300, 1000), (1000, 3000), (3000, 6000), (6000, 12000),
         (12000, 18000))
SWEEP = (60, 18000, 5.0)
SWEEP_POINTS = (60, 70, 80, 90, 100, 120, 150, 300, 1000, 3000, 6000, 10000, 14000, 17500)


def wasapi(prefix: str) -> int:
    for i, d in enumerate(sd.query_devices()):
        api = sd.query_hostapis(d["hostapi"])["name"]
        if d["name"].startswith(prefix) and api == "Windows WASAPI":
            return i
    raise SystemExit(f"no WASAPI device starting with {prefix!r}")


def listener_pid(exe: str) -> int:
    table = appaudio._process_table()
    roots = sorted({appaudio.root_pid(p, table) for p, (_, n) in table.items()
                    if n.lower() == exe.lower()})
    if not roots:
        raise SystemExit(f"{exe} isn't running: start the listening client and join the call")
    return roots[0]


# ------------------------------------------------------------------------ signals

def signals(song: str | None) -> tuple[np.ndarray, list[tuple[str, int, int]]]:
    rng = np.random.default_rng(1)
    t = lambda s: np.arange(int(s * SR)) / SR  # noqa: E731
    sil = lambda s: np.zeros(int(s * SR))  # noqa: E731

    def boom():
        x = t(0.5)
        b = np.sin(2 * np.pi * 55 * x) * np.exp(-x * 6) * 0.9
        return np.clip(b + rng.normal(0, 1, len(x)) * np.exp(-x * 40) * 0.5, -1, 1)

    f0, f1, dur = SWEEP
    k = np.log(f1 / f0)
    x = t(dur)
    sweep = 0.3 * np.sin(2 * np.pi * f0 * dur / k * (np.exp(x / dur * k) - 1))
    ramp = np.linspace(0, 1, 2400)
    sweep[:2400] *= ramp
    sweep[-2400:] *= ramp[::-1]
    segs = [("booms", np.concatenate([np.concatenate([sil(1.5), boom()]) for _ in range(3)])),
            ("sweep", sweep),
            ("pink noise", codecsim.pink_noise(6.0, level=0.3)[:, 0]),
            ("speech-like", codecsim.speech_like(4.0, level=0.5)[:, 0])]
    stereo = [(n, np.repeat(s[:, None], 2, 1)) for n, s in segs]
    if song:
        raw = subprocess.run([_ffmpeg(), "-v", "quiet", "-ss", "30", "-t", "15", "-i", song,
                              "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        stereo.append(("song", np.frombuffer(raw, np.float32).reshape(-1, 2).copy()))
    parts, marks, pos = [np.zeros((SR, 2))], [], SR
    for name, s in stereo:
        marks.append((name, pos, pos + len(s)))
        parts += [s, np.zeros((2 * SR, 2))]
        pos += len(s) + 2 * SR
    return np.concatenate(parts).astype(np.float32), marks


# ---------------------------------------------------------------------- recording

class Recorder:
    """The cable's far end and the listener process, started and stopped together."""

    def __init__(self, listener: str):
        self.cable, self.ear = [], []
        self.cap = appaudio.AppCapture(listener_pid(listener), lambda c: self.ear.append(c.copy()))
        self.ins = sd.InputStream(SR, channels=2, device=wasapi("CABLE Output"), dtype="float32",
                                  callback=lambda d, *_: self.cable.append(d.copy()))

    def __enter__(self):
        if not self.cap.start():
            raise SystemExit(f"can't record the listener: {self.cap.error}")
        self.ins.start()
        return self

    def __exit__(self, *_):
        self.ins.stop()
        self.ins.close()
        self.cap.stop()

    def result(self) -> tuple[np.ndarray, np.ndarray]:
        return np.concatenate(self.cable)[:, 0], np.concatenate(self.ear)[:, 0]


def send(track: np.ndarray, mode: str, listener: str,
         sound_vol: float) -> tuple[np.ndarray, np.ndarray]:
    secs = len(track) / SR
    with Recorder(listener) as rec:
        time.sleep(0.3)
        if mode == "raw":
            sd.play(track, SR, device=wasapi("CABLE Input"))
            sd.wait()
        else:
            eng = Engine()
            eng.set_main_device(sd.query_devices(wasapi("CABLE Input"))["name"])
            eng.sound_vol, eng.send_mono, eng.limiter_on = sound_vol, True, True
            eng.dest = destination.BUILTIN_BY_KEY["discord"] if mode == "onion+discord" else None
            eng.play("roundtrip", track, level_gain(track))
            time.sleep(secs)
            eng.shutdown()
        time.sleep(1.5)
    return rec.result()


# ----------------------------------------------------------------------- analysis

def lag(a: np.ndarray, b: np.ndarray, max_s: float = 1.5) -> int:
    """Samples b trails a by (10 ms envelope cross-correlation)."""
    env = lambda x: np.abs(x[: len(x) // 480 * 480]).reshape(-1, 480).max(1)  # noqa: E731
    ea, eb = env(a), env(b)
    n = min(len(ea), len(eb))
    ea, eb = ea[:n], eb[:n]
    return 480 * max(range(int(max_s * 100)), key=lambda k: float(np.dot(ea[: n - k], eb[k:])))


def db(x) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12))


def bands(x: np.ndarray) -> np.ndarray:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.array([10 * np.log10(spec[(f >= lo) & (f < hi)].sum() + 1e-20) for lo, hi in BANDS])


def analyze(src, cable, ear, marks) -> dict:
    out = {}
    for name, a, b in marks:
        s, c, e = src[a:b], cable[a:b], ear[a:b]
        if len(e) < b - a:
            continue
        m = {"app_level_db": db(c) - db(s), "chat_level_db": db(e) - db(c),
             "chat_bands_db": (bands(e) - bands(c)).round(1).tolist(),
             "app_bands_db": (bands(c) - bands(s)).round(1).tolist()}
        if name == "booms":   # the start of a sound after silence: a voice gate eats it
            m["first_30ms_kept_db"] = []
            for h in range(3):
                i = int((1.5 + 2.0 * h) * SR)
                w = int(0.03 * SR)
                m["first_30ms_kept_db"].append(round(db(e[i:i + w]) - db(c[i:i + w]), 1))
        if name == "sweep":
            f0, f1, dur = SWEEP
            k = np.log(f1 / f0)
            curve = {}
            for f in SWEEP_POINTS:
                i = int(np.log(f / f0) / k * dur * SR)
                w = int(0.02 * SR)
                curve[f] = round(db(e[max(i - w, 0):i + w]) - db(c[max(i - w, 0):i + w]), 1)
            m["chat_response_db"] = curve
        if name == "pink noise":   # noise suppression fades a steady sound away
            q = SR // 2
            m["chat_level_over_time_db"] = [round(db(e[i:i + q]), 1)
                                            for i in range(0, len(e) - q + 1, q)]
        out[name] = m
    return out


def listen(secs: float, listener: str, out: Path):
    print(f"Talk now for {secs:.0f} s ...", flush=True)
    with Recorder(listener) as rec:
        time.sleep(secs)
    cable, ear = rec.result()
    sf.write(out / "listen_cable.wav", cable, SR)
    sf.write(out / "listen_ear.wav", ear, SR)
    k = lag(cable, ear)
    ear = ear[k:]
    n = min(len(cable), len(ear)) // 4800 * 4800
    ec = np.abs(cable[:n]).reshape(-1, 4800).max(1)
    ee = np.abs(ear[:n]).reshape(-1, 4800).max(1)
    row = lambda e: "".join("#" if v > 0.1 else "+" if v > 0.02 else "." for v in e)  # noqa: E731
    for i in range(0, len(ec), 120):
        print("sent    ", row(ec[i:i + 120]))
        print("received", row(ee[i:i + 120]), "\n")
    said = ec > 0.02
    kept = float((ee[said] > 0.02).mean() * 100) if said.any() else 0.0
    change = db(ear[:n]) - db(cable[:n])
    print(f"of what was sent, received: {kept:.0f}%   level change {change:+.1f} dB")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modes", default="raw,onion,onion+discord")
    ap.add_argument("--listener", default="DiscordCanary.exe", help="the listening client's exe")
    ap.add_argument("--song", help="also send 15 s of this file (from 0:30)")
    ap.add_argument("--sound-vol", type=float, default=1.0, help="the app's sound volume")
    ap.add_argument("--listen", type=float, metavar="SECONDS", help="record you talking instead")
    ap.add_argument("--out", default="roundtrip-out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.listen:
        listen(a.listen, a.listener, out)
        return
    track, marks = signals(a.song)
    src = track[:, 0]
    results = {}
    for mode in a.modes.split(","):
        print(f"== {mode}", flush=True)
        cable, ear = send(track, mode, a.listener, a.sound_vol)
        k = lag(src, cable)
        floor = db(cable[k + SR // 4:k + 3 * SR // 4])   # the lead-in silence
        if floor > -60:
            print(f"  ! something else is feeding the cable ({floor:.0f} dB in the silence): "
                  "close other soundboards / mute your mic in the app, or quiet parts read wrong")
        cable = cable[k:]
        ear = ear[lag(cable, ear):]
        sf.write(out / f"{mode}_cable.wav", cable, SR)
        sf.write(out / f"{mode}_ear.wav", ear, SR)
        results[mode] = analyze(src, cable, ear, marks)
        for name, m in results[mode].items():
            print(f"  {name}: {json.dumps(m)}")
        time.sleep(1.5)
    (out / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
