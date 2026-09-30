"""How Windows hands the virtual mic to a game: device choice, resampling, ducking.

A game doesn't open the mic the way Discord does. Three things go wrong before any
codec is involved, and this checks each on the real audio engine:

    python scripts/game_capture.py                 # report only: nothing plays
    python scripts/game_capture.py --resample      # the formats games open the mic in
    python scripts/game_capture.py --ducking       # does a voice stream turn us down?

report     Which recording device Windows gives a game that asks for "the default
           mic" (many do, and never show a picker) and which it gives one asking
           for "the default communications mic" (voice chat SDKs do). Unless that is
           the cable's far end, the game hears your real mic and none of the sounds.
           Also the cable's formats and the Windows ducking setting.
resample   Plays the test signals into the cable and records its far end the ways
           games open it: 48 kHz, 44.1 kHz, 32, 24 and 16 kHz mono through WASAPI's
           shared-mode converter, and 22.05 / 11.025 kHz through the old MME path
           (DirectSound games end up there). Reports the frequency ceiling, the
           level and what the converter folds back (aliasing) for each.
ducking    Plays a steady tone into the cable, then opens a capture stream on the
           default communications device the way a game's voice chat does, and
           measures whether Windows' "reduce other sounds" turns the tone down on
           its way into the cable. Repeats with this process opted out of ducking
           (IAudioSessionControl2::SetDuckingPreference), which the app can do.

resample and ducking play into the cable: mute your mic in the app, close other
soundboards, and don't be in a call that uses the cable as its mic.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import winreg
from ctypes import POINTER, byref, c_int, c_ulong, c_void_p
from pathlib import Path

import numpy as np
import sounddevice as sd
import soxr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundboard import appaudio, cableformat, codecsim  # noqa: E402
from soundboard.appaudio import GUID, Com, ComError, _co_init, _device_name, _enumerator  # noqa: E402

SR = 48000
E_RENDER, E_CAPTURE = 0, 1
ROLES = {"default (console)": 0, "multimedia": 1, "communications": 2}
DUCKING = {0: "mute all other sounds", 1: "reduce other sounds by 80%",
           2: "reduce other sounds by 50%", 3: "do nothing"}
IID_IAudioSessionManager = GUID.of("BFA971F1-4D5E-40BB-935E-967039BFBEE4")


# ------------------------------------------------------------------------ report

def default_devices(flow: int) -> dict[str, str]:
    """Name of the default endpoint for each role ('' when there is none)."""
    _co_init()
    out = {}
    with _enumerator() as en:
        for label, role in ROLES.items():
            d = c_void_p()
            try:
                en.call(4, (c_int, c_int, POINTER(c_void_p)), flow, role, byref(d),
                        what="GetDefaultAudioEndpoint")
            except ComError:
                out[label] = ""
                continue
            with Com(d.value) as dev:
                out[label] = _device_name(dev)
    return out


def ducking_setting() -> int:
    """Sound control panel -> Communications tab (absent = the default, 80%)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Multimedia\Audio") as k:
            return int(winreg.QueryValueEx(k, "UserDuckingPreference")[0])
    except OSError:
        return 1


def report() -> dict:
    cap, ren = default_devices(E_CAPTURE), default_devices(E_RENDER)
    ends = cableformat.cable_ends()
    duck = ducking_setting()
    print("Recording device a game gets when it asks Windows for the default:")
    for role, name in cap.items():
        mark = "cable" if name and appaudio_is_virtual(name) else "NOT the cable"
        print(f"  {role:<18} {name or '(none)'}   <- {mark}")
    print("Playback defaults:", ", ".join(f"{r}: {n}" for r, n in ren.items()))
    print("Cable ends:")
    for e in ends:
        print(f"  {e.flow:<8} {e.name}: {e.rate} Hz, {e.bits}-bit, {e.channels} ch"
              f"{'' if e.ok else '  <- not 48 kHz'}")
    print(f"Windows ducking (Sound -> Communications): {DUCKING.get(duck, duck)}")
    if not appaudio_is_virtual(cap.get("communications", "")):
        print("\n! Voice chat that uses the default communications mic won't hear the"
              " sounds.\n  Games with no mic picker use this.")
    return {"capture_defaults": cap, "render_defaults": ren, "ducking": duck,
            "cable_ends": [e.__dict__ for e in ends]}


def appaudio_is_virtual(name: str) -> bool:
    from soundboard.engine import is_virtual
    return is_virtual(name)


# ---------------------------------------------------------------------- devices

def device(prefix: str, api: str = "Windows WASAPI") -> int:
    for i, d in enumerate(sd.query_devices()):
        if d["name"].startswith(prefix) and sd.query_hostapis(d["hostapi"])["name"] == api:
            return i
    raise SystemExit(f"no {api} device starting with {prefix!r}")


class Tap:
    """One capture stream on the cable's far end, at a game's format."""

    def __init__(self, label: str, rate: int, channels: int, api: str):
        self.label, self.rate, self.chunks = label, rate, []
        extra = sd.WasapiSettings(auto_convert=True) if api == "Windows WASAPI" else None
        self.stream = sd.InputStream(rate, channels=channels, dtype="float32",
                                     device=device("CABLE Output", api), extra_settings=extra,
                                     callback=lambda d, *_: self.chunks.append(d[:, 0].copy()))

    def audio(self) -> np.ndarray:
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)


TAPS = (("WASAPI 48 kHz stereo (reference)", 48000, 2, "Windows WASAPI"),
        ("WASAPI 44.1 kHz stereo", 44100, 2, "Windows WASAPI"),
        ("WASAPI 32 kHz mono", 32000, 1, "Windows WASAPI"),
        ("WASAPI 24 kHz mono", 24000, 1, "Windows WASAPI"),
        ("WASAPI 16 kHz mono", 16000, 1, "Windows WASAPI"),
        ("MME 22.05 kHz mono", 22050, 1, "MME"),
        ("MME 11.025 kHz mono", 11025, 1, "MME"))


def _sweep(seconds: float = 6.0, level: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    f0, f1 = 50.0, 23000.0
    k = np.log(f1 / f0)
    return (level * np.sin(2 * np.pi * f0 * seconds / k * (np.exp(t / seconds * k) - 1))
            ).astype(np.float32)


def _db(x) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12))


def _align(ref: np.ndarray, x: np.ndarray) -> np.ndarray:
    n = min(len(ref), len(x))
    if n < SR:
        return x
    env = lambda v: np.abs(v[:n // 480 * 480]).reshape(-1, 480).max(1)  # noqa: E731
    a, b = env(ref), env(x)
    k = max(range(min(150, len(a) - 1)), key=lambda j: float(np.dot(a[:len(a) - j], b[j:])))
    return x[k * 480:]


def resample(out: Path) -> dict:
    sweep = _sweep()
    pink = codecsim.pink_noise(4.0, level=0.3)[:, 0]
    gap = np.zeros(SR, np.float32)
    track = np.concatenate([gap, sweep, gap, pink, gap])
    taps = []
    for label, rate, ch, api in TAPS:
        try:
            taps.append(Tap(label, rate, ch, api))
        except Exception as e:  # noqa: BLE001 - a format the driver refuses is a finding
            print(f"  {label}: can't open ({e})")
    for t in taps:
        t.stream.start()
    time.sleep(0.3)
    sd.play(np.repeat(track[:, None], 2, 1), SR, device=device("CABLE Input"))
    sd.wait()
    time.sleep(0.8)
    for t in taps:
        t.stream.stop()
        t.stream.close()
    results = {}
    print(f"{'capture format':<34}{'level':>7}{'ceiling':>9}{'alias':>8}{'pink':>7}")
    for t in taps:
        x = t.audio()
        if t.rate != SR:
            x = soxr.resample(x, t.rate, SR, quality="VHQ").astype(np.float32)
        x = _align(track, x)
        s0 = SR
        sw = x[s0:s0 + len(sweep)]
        # the sweep's instantaneous frequency at each 20 ms step: in-band energy is
        # kept signal, energy well away from it is what the converter folded back
        k = np.log(23000 / 50)
        step = SR // 50
        kept, alias, freqs = [], [], []
        for i in range(0, len(sw) - step, step):
            f = 50 * np.exp(i / len(sweep) * k)
            seg = sw[i:i + step] * np.hanning(step)
            spec = np.abs(np.fft.rfft(seg)) ** 2
            fr = np.fft.rfftfreq(step, 1 / SR)
            near = np.abs(fr - f) < max(200, f * 0.08)
            kept.append(10 * np.log10(spec[near].sum() + 1e-20))
            alias.append(10 * np.log10(spec[~near].sum() + 1e-20))
            freqs.append(f)
        kept, alias, freqs = np.array(kept), np.array(alias), np.array(freqs)
        top = kept.max() if len(kept) else 0
        carried = freqs[kept > top - 10]
        ceiling = float(carried.max()) if len(carried) else 0.0
        worst_alias = float((alias - top).max()) if len(alias) else -120.0
        p = x[s0 + len(sweep) + SR:s0 + len(sweep) + SR + len(pink)]
        lvl = _db(sw) - _db(sweep)
        results[t.label] = {"rate": t.rate, "level_db": round(lvl, 1),
                            "ceiling_hz": round(ceiling), "alias_db": round(worst_alias, 1),
                            "pink_level_db": round(_db(p) - _db(pink), 1)}
        r = results[t.label]
        print(f"{t.label:<34}{r['level_db']:+7.1f}{ceiling / 1000:8.1f}k{worst_alias:+8.1f}"
              f"{r['pink_level_db']:+7.1f}")
    print("\nlevel / pink = change against what was played (dB); ceiling = highest"
          " frequency\nstill within 10 dB; alias = loudest energy away from the sweep,"
          " relative to it\n(above about -40 dB is audible junk the converter adds).")
    (out / "resample.json").write_text(json.dumps(results, indent=1))
    return results


# ---------------------------------------------------------------------- ducking

def opt_out_of_ducking(render_prefix: str = "CABLE Input") -> bool:
    """SetDuckingPreference(TRUE) on this process's session on the cable. Call once
    a stream is open (the session exists from then on)."""
    _co_init()
    target = sd.query_devices(device(render_prefix))["name"]
    with _enumerator() as en:
        for dev in appaudio._render_devices(en):
            with dev:
                if not _device_name(dev).startswith(target[:31]):
                    continue
                mgr = c_void_p()
                dev.call(3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
                         byref(IID_IAudioSessionManager), appaudio.CLSCTX_ALL, None, byref(mgr),
                         what="Activate(IAudioSessionManager)")
                with Com(mgr.value) as m:
                    ctl = c_void_p()
                    m.call(3, (c_void_p, c_ulong, POINTER(c_void_p)), None, 0, byref(ctl),
                           what="GetAudioSessionControl")
                    with Com(ctl.value) as c, c.qi(appaudio.IID_IAudioSessionControl2) as c2:
                        c2.call(16, (c_int,), 1, what="SetDuckingPreference")
                        return True
    return False


def ducking(out: Path) -> dict:
    comms = default_devices(E_CAPTURE)["communications"]
    if not comms:
        raise SystemExit("no default communications recording device")
    comms_idx = next((i for i, d in enumerate(sd.query_devices())
                      if d["max_input_channels"] and d["name"].startswith(comms[:31])
                      and sd.query_hostapis(d["hostapi"])["name"] == "Windows WASAPI"), None)
    if comms_idx is None:
        raise SystemExit(f"can't open the communications device {comms!r}")
    results = {}
    for opted in (False, True):
        tone = (0.2 * np.sin(2 * np.pi * 1000 * np.arange(10 * SR) / SR)).astype(np.float32)
        rec: list[np.ndarray] = []
        ins = sd.InputStream(SR, channels=1, dtype="float32", device=device("CABLE Output"),
                             callback=lambda d, *_, rec=rec: rec.append(d[:, 0].copy()))
        ins.start()
        play = sd.OutputStream(SR, channels=2, dtype="float32", device=device("CABLE Input"))
        play.start()
        if opted:
            print("opted out of ducking:", opt_out_of_ducking())
        feeder = threading.Thread(target=play.write, args=(np.repeat(tone[:, None], 2, 1),))
        feeder.start()
        time.sleep(3.0)
        # what a game's voice chat does: a capture stream on the communications mic
        t_open = time.perf_counter()
        game = sd.InputStream(SR, channels=1, dtype="float32", device=comms_idx,
                              callback=lambda *_: None)
        game.start()
        time.sleep(3.0)
        game.stop()
        game.close()
        t_close = time.perf_counter()
        feeder.join()
        play.stop()
        play.close()
        ins.stop()
        ins.close()
        y = np.concatenate(rec)
        w = SR // 2
        levels = [round(_db(y[i:i + w]), 1) for i in range(0, len(y) - w + 1, w)]
        before = float(np.median(levels[2:5]))
        during = float(np.median(levels[7:11]))
        after = float(np.median(levels[-4:-1]))
        key = "opted out" if opted else "default"
        results[key] = {"before_db": before, "during_db": during, "after_db": after,
                        "drop_db": round(during - before, 1), "levels_db": levels,
                        "held_s": round(t_close - t_open, 1)}
        print(f"{key:<10} tone before {before:+.1f} dB, while the game's voice stream is open"
              f" {during:+.1f} dB ({during - before:+.1f}), after {after:+.1f} dB")
        time.sleep(1.0)
    (out / "ducking.json").write_text(json.dumps(results, indent=1))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resample", action="store_true")
    ap.add_argument("--ducking", action="store_true")
    ap.add_argument("--out", default="game-capture-out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res = {"report": report()}
    if a.resample:
        print("\n== resampling")
        res["resample"] = resample(out)
    if a.ducking:
        print("\n== ducking")
        res["ducking"] = ducking(out)
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
