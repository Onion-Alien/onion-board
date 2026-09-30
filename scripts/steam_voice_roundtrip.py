"""Real Steam voice round trip: what does a CS2 / Dota / TF2 listener actually get?

codec_bench.py's "steam" profile is an estimate; this measures it, on one PC and
one account. Steamworks' voice API records the mic, compresses it with Steam's own
codec (ISteamUser::GetVoice) and decompresses it again (DecompressVoice): exactly the
bytes a game sends and what the other players' clients turn them back into.

Set up once:

  * Steam running and logged in
  * Steam > Settings > Voice > Voice input device = CABLE Output (the app's virtual
    mic), or Windows' default recording device set to it (Steam follows that when
    its own setting is "Default"). Put it back afterwards.
  * nothing else talking into the cable (mute your mic in the app, close other
    soundboards), and not in a Discord call that uses the cable as its mic: the
    test tones go out wherever the cable does

Then:

    python scripts/steam_voice_roundtrip.py                    # raw, onion, onion+steam
    python scripts/steam_voice_roundtrip.py --modes raw --song clip.mp3

It needs a steam_api64.dll. Every Steamworks game ships one; the script finds one
in your Steam libraries, or pass --steam-api PATH. It runs as Valve's public test
app (Spacewar, app ID 480), so Steam shows you "in game" while it runs.

The signals and the analysis are discord_roundtrip.py's: the cable's far end is
recorded at the same time, which splits every change into what the app did
(source -> cable) and what Steam did (cable -> decoded). WAVs and results.json land
in --out.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import threading
import time
import winreg
from ctypes import POINTER, byref, c_bool, c_uint32, c_void_p
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord_roundtrip as rt  # noqa: E402  (same folder: its signals and analysis)
from soundboard import destination  # noqa: E402
from soundboard.engine import Engine  # noqa: E402
from soundboard.library import level_gain  # noqa: E402

SR = rt.SR
SPACEWAR = "480"
VOICE_OK, VOICE_NO_DATA = 0, 3
RESULTS = {1: "not initialised", 2: "not recording", 4: "buffer too small",
           5: "data corrupted", 6: "restricted (this account can't use voice)",
           7: "unsupported codec", 8: "receiver out of date", 9: "receiver did not answer"}


# ------------------------------------------------------------------ Steamworks

def steam_libraries() -> list[Path]:
    roots = []
    for hive, key, name in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam",
                             "InstallPath"),
                            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                roots.append(Path(winreg.QueryValueEx(k, name)[0]))
        except OSError:
            continue
    libs = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return list(dict.fromkeys(p / "steamapps" / "common" for p in libs))


def find_steam_api() -> Path | None:
    """The newest steam_api64.dll in the Steam libraries that has the voice calls."""
    best = None
    for common in steam_libraries():
        if not common.is_dir():
            continue
        for game in common.iterdir():
            for dll in game.glob("**/steam_api64.dll") if game.is_dir() else ():
                v = _user_version(dll)
                if v and (best is None or v > best[0]):
                    best = (v, dll)
    return best[1] if best else None


def _user_version(dll: Path) -> int:
    """The highest SteamAPI_SteamUser_vNNN the DLL exports (0 = none: too old)."""
    data = dll.read_bytes()
    found = [int(v) for v in re.findall(rb"SteamAPI_SteamUser_v(\d{3})\x00", data)]
    return max(found) if found and b"SteamAPI_ISteamUser_DecompressVoice" in data else 0


class SteamVoice:
    """ISteamUser's voice calls through the flat C API."""

    def __init__(self, dll: Path):
        self.lib = lib = ctypes.CDLL(str(dll))
        lib.SteamAPI_Init.restype = c_bool
        if not lib.SteamAPI_Init():
            raise SystemExit("SteamAPI_Init failed: is Steam running and logged in?")
        getter = getattr(lib, f"SteamAPI_SteamUser_v{_user_version(dll):03d}")
        getter.restype = c_void_p
        self.user = c_void_p(getter())
        lib.SteamAPI_ISteamUser_GetAvailableVoice.argtypes = [
            c_void_p, POINTER(c_uint32), POINTER(c_uint32), c_uint32]
        lib.SteamAPI_ISteamUser_GetVoice.argtypes = [
            c_void_p, c_bool, c_void_p, c_uint32, POINTER(c_uint32),
            c_bool, c_void_p, c_uint32, POINTER(c_uint32), c_uint32]
        lib.SteamAPI_ISteamUser_DecompressVoice.argtypes = [
            c_void_p, c_void_p, c_uint32, c_void_p, c_uint32, POINTER(c_uint32), c_uint32]
        lib.SteamAPI_ISteamUser_GetVoiceOptimalSampleRate.argtypes = [c_void_p]
        lib.SteamAPI_ISteamUser_GetVoiceOptimalSampleRate.restype = c_uint32
        for f in ("StartVoiceRecording", "StopVoiceRecording"):
            getattr(lib, f"SteamAPI_ISteamUser_{f}").argtypes = [c_void_p]
        self.buf = ctypes.create_string_buffer(64 * 1024)
        self.pcm = ctypes.create_string_buffer(1024 * 1024)

    @property
    def optimal_rate(self) -> int:
        return int(self.lib.SteamAPI_ISteamUser_GetVoiceOptimalSampleRate(self.user))

    def start(self):
        self.lib.SteamAPI_ISteamUser_StartVoiceRecording(self.user)

    def stop(self):
        self.lib.SteamAPI_ISteamUser_StopVoiceRecording(self.user)

    def get(self) -> bytes | None:
        """One compressed packet, or None when there's nothing yet."""
        n = c_uint32(0)
        r = self.lib.SteamAPI_ISteamUser_GetVoice(self.user, True, self.buf, len(self.buf),
                                                  byref(n), False, None, 0, None, 0)
        if r == VOICE_NO_DATA or (r == VOICE_OK and not n.value):
            return None
        if r != VOICE_OK:
            raise RuntimeError(f"GetVoice: {RESULTS.get(r, r)}")
        return self.buf.raw[:n.value]

    def decompress(self, packet: bytes, rate: int = SR) -> np.ndarray:
        n = c_uint32(0)
        r = self.lib.SteamAPI_ISteamUser_DecompressVoice(self.user, packet, len(packet),
                                                         self.pcm, len(self.pcm), byref(n), rate)
        if r != VOICE_OK:
            raise RuntimeError(f"DecompressVoice: {RESULTS.get(r, r)}")
        return np.frombuffer(self.pcm.raw[:n.value], np.int16).astype(np.float32) / 32768.0

    def shutdown(self):
        self.lib.SteamAPI_Shutdown()


class Capture:
    """Polls Steam's voice while the cable's far end records: the decoded packets are
    laid on a timeline by arrival (a packet's audio ends when it arrives), so a voice
    gate's silences stay silences instead of closing up."""

    def __init__(self, steam: SteamVoice):
        self.steam = steam
        self.cable: list[np.ndarray] = []
        self.packets: list[tuple[float, bytes]] = []
        self._run = False
        self.ins = sd.InputStream(SR, channels=2, device=rt.wasapi("CABLE Output"),
                                  dtype="float32", callback=self._on_cable)
        self.t0 = 0.0

    def _on_cable(self, d, *_):
        self.cable.append(d.copy())

    def _poll(self):
        while self._run:
            self.steam.lib.SteamAPI_RunCallbacks()
            while (p := self.steam.get()) is not None:
                self.packets.append((time.perf_counter() - self.t0, p))
            time.sleep(0.005)

    def __enter__(self):
        self.steam.start()
        self.t0 = time.perf_counter()
        self.ins.start()
        self._run = True
        self._th = threading.Thread(target=self._poll, daemon=True)
        self._th.start()
        return self

    def __exit__(self, *_):
        time.sleep(0.5)
        self._run = False
        self._th.join()
        self.steam.stop()
        self.ins.stop()
        self.ins.close()

    def result(self) -> tuple[np.ndarray, np.ndarray, dict]:
        cable = np.concatenate(self.cable)[:, 0] if self.cable else np.zeros(0, np.float32)
        out = np.zeros(len(cable) + 5 * SR, np.float32)
        cur = 0
        sizes = []
        for t, p in self.packets:
            pcm = self.steam.decompress(p)
            sizes.append(len(p))
            at = max(cur, int(t * SR) - len(pcm))
            end = min(at + len(pcm), len(out))
            out[at:end] = pcm[:end - at]
            cur = end
        secs = len(cable) / SR
        info = {"packets": len(self.packets),
                "avg_kbps": round(sum(sizes) * 8 / max(secs, 1e-9) / 1000, 1),
                "optimal_rate": self.steam.optimal_rate}
        return cable, out[:cur], info


def send(steam: SteamVoice, track: np.ndarray, mode: str, sound_vol: float):
    secs = len(track) / SR
    with Capture(steam) as cap:
        time.sleep(0.3)
        if mode == "raw":
            sd.play(track, SR, device=rt.wasapi("CABLE Input"))
            sd.wait()
        else:
            eng = Engine()
            eng.set_main_device(sd.query_devices(rt.wasapi("CABLE Input"))["name"])
            eng.sound_vol, eng.send_mono, eng.limiter_on = sound_vol, True, True
            eng.dest = destination.BUILTIN_BY_KEY["steam"] if mode == "onion+steam" else None
            eng.play("roundtrip", track, level_gain(track))
            time.sleep(secs)
            eng.shutdown()
        time.sleep(1.5)
    return cap.result()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modes", default="raw,onion,onion+steam")
    ap.add_argument("--steam-api", help="path of a steam_api64.dll (default: found in your "
                                        "Steam libraries)")
    ap.add_argument("--song", help="also send 15 s of this file (from 0:30)")
    ap.add_argument("--sound-vol", type=float, default=1.0, help="the app's sound volume")
    ap.add_argument("--out", default="steam-roundtrip-out")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    dll = Path(a.steam_api) if a.steam_api else find_steam_api()
    if not dll or not dll.is_file():
        raise SystemExit("no steam_api64.dll with the voice API found; pass --steam-api")
    print(f"steam api: {dll} (ISteamUser v{_user_version(dll):03d})")
    # SteamAPI_Init reads the app ID from steam_appid.txt in the working directory
    (out / "steam_appid.txt").write_text(SPACEWAR)
    os.chdir(out)
    os.add_dll_directory(str(dll.parent))
    steam = SteamVoice(dll)
    print(f"Steam voice optimal sample rate: {steam.optimal_rate} Hz")
    track, marks = rt.signals(a.song)
    src = track[:, 0]
    results = {}
    try:
        for mode in a.modes.split(","):
            print(f"== {mode}", flush=True)
            cable, ear, info = send(steam, track, mode, a.sound_vol)
            print(f"  {info['packets']} packets, {info['avg_kbps']} kbps average")
            if not info["packets"]:
                print("  ! Steam sent nothing: is its voice input device CABLE Output?")
                continue
            k = rt.lag(src, cable)
            floor = rt.db(cable[k + SR // 4:k + 3 * SR // 4])
            if floor > -60:
                print(f"  ! something else is feeding the cable ({floor:.0f} dB in the silence)")
            cable = cable[k:]
            ear = ear[rt.lag(cable, ear):]
            sf.write(out / f"{mode}_cable.wav", cable, SR)
            sf.write(out / f"{mode}_steam.wav", ear, SR)
            results[mode] = {"info": info, **rt.analyze(src, cable, ear, marks)}
            for name, m in results[mode].items():
                print(f"  {name}: {json.dumps(m)}")
            time.sleep(1.5)
    finally:
        steam.shutdown()
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(f"wrote {out / 'results.json'}")


if __name__ == "__main__":
    main()
