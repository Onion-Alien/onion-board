"""AI voices module: turns your mic into a character voice, live, on the CPU.

Launched by the Onion Board app (never run by hand; it needs the app's --port and
--token). The app sends your mic (16 kHz) only while you talk; this converts each
20 ms and sends it straight back (24 kHz), and the app plays it in place of your
voice:

    b"A" mic 16 kHz -> Converter (onnxruntime, 1 thread) -> b"B" voice 24 kHz

While you're quiet nothing arrives and this sleeps in recv(): no CPU at all.

With ONIONBOARD_LESS_CPU=1 (the app's Use less CPU) it converts 40 ms a call with the
lighter model (model/stream4.onnx, the same voices), about a third less CPU for 20 ms
more delay; "ready" says the chunk length (chunk_s) so the app sizes its buffer. An
older app never sets it; a download without stream4.onnx carries on at 20 ms.

    helper.py --download     fetch the model (install step), check its SHA-256
    helper.py --self-test    how fast this PC runs it (real-time factor)

Runs in its own Python environment (install.bat makes it): onnxruntime and the model
never touch the app itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import numpy as np

import protocol

log = logging.getLogger("ai-voices")
HERE = Path(__file__).resolve().parent
VERSION = "0.3.0"
OUT_RATE = 24000
CHUNK = 320                       # 20 ms at 16 kHz (40 ms with the lighter model)
LIGHT = os.environ.get("ONIONBOARD_LESS_CPU") == "1"   # the app's Use less CPU
TOO_SLOW = 0.5                    # real-time factor above which gaming will suffer
MODEL_FILES = ("stream.onnx", "speaker.onnx", "voices.npz")


def load_voices() -> dict:
    """voices.json, plus the user's own voices from the app's file
    (ONIONBOARD_MY_AI_VOICES): a copy shipped with the app is never written to, so
    they can't be in its voices.json. An older app never sets it."""
    voices = json.loads((HERE / "voices.json").read_text(encoding="utf-8"))
    mine = os.environ.get("ONIONBOARD_MY_AI_VOICES", "")
    if mine:
        try:
            extra = json.loads(Path(mine).read_text(encoding="utf-8")).get("voices", [])
        except (OSError, ValueError, AttributeError):
            extra = []
        have = {v.get("id") for v in voices["voices"]}
        voices["voices"] += [v for v in extra if isinstance(v, dict) and v.get("mix")
                             and str(v.get("id", "")).startswith("my-")
                             and v["id"] not in have]
    return voices


def model_dir() -> Path:
    return HERE / "model"


def model_ready(folder: Path | None = None) -> bool:
    folder = folder or model_dir()
    return all((folder / f).is_file() for f in MODEL_FILES)


def download(on_line=print) -> int:
    """Fetch and unpack the model named in voices.json ({"url", "sha256", "bytes"})."""
    spec = load_voices().get("model", {})
    url, want, size = spec.get("url", ""), spec.get("sha256", "").lower(), int(spec.get("bytes", 0))
    if model_ready():
        on_line("The voice model is already here.")
        return 0
    if not url.startswith("https://") or len(want) != 64:
        on_line("This copy of the add-on doesn't say where to get its model.")
        return 1
    import urllib.request
    dest = model_dir()
    on_line(f"Downloading the voice model (about {size / 1e6:.0f} MB)…")
    h = hashlib.sha256()
    got = 0
    with tempfile.TemporaryDirectory(dir=HERE) as tmp:
        part = Path(tmp) / "model.zip"
        try:
            # https_proxy (the app's relay) is honoured by urllib
            with urllib.request.urlopen(url, timeout=30) as r, open(part, "wb") as f:
                last = 0.0
                while chunk := r.read(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if size and time.monotonic() - last > 1.0:
                        last = time.monotonic()
                        on_line(f"Downloading the voice model: {got * 100 // size} %")
        except OSError as e:
            on_line(f"Couldn't download the voice model ({e}). If downloads are switched "
                    "off in Settings > Privacy & security, switch them on and try again.")
            return 1
        if h.hexdigest() != want:
            on_line("The download was damaged (its checksum is wrong); try again.")
            return 1
        with zipfile.ZipFile(part) as z:
            names = set(z.namelist())
            if not set(MODEL_FILES) <= names:
                on_line("The download isn't a voice model.")
                return 1
            dest.mkdir(exist_ok=True)
            for name in MODEL_FILES:        # only the files we know: no paths from the zip
                (dest / name).write_bytes(z.read(name))
    on_line("Voice model ready.")
    return 0


class FakeConverter:
    """For tests: no model, no onnxruntime. Your voice, resampled to 24 kHz."""

    def __init__(self, *_a, light: bool = False, **_k):
        self.shift_st = 0.0
        self.auto_pitch = True
        self.t = 4 if light else 2            # 10 ms frames per call, like Converter

    def set_voice(self, voice):
        self.extra = float(voice.get("pitch", 0.0))

    def settle_pitch(self, force=False):
        pass

    def process(self, x):
        n = len(x) * 3 // 2
        t = np.arange(n) * (len(x) / n)
        return np.interp(t, np.arange(len(x)), x).astype(np.float32)


class Link:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.lock = threading.Lock()

    def send(self, **obj):
        try:
            with self.lock:
                protocol.send_json(self.sock, obj)
        except OSError:
            pass

    def audio(self, y: np.ndarray):
        pcm = np.clip(np.rint(y * 32767), -32768, 32767).astype("<i2").tobytes()
        try:
            with self.lock:
                protocol.send(self.sock, protocol.VOICE, pcm)
        except OSError:
            pass


def pick(voices: dict, vid: str) -> dict:
    for v in voices["voices"]:
        if v["id"] == vid:
            return v
    return voices["voices"][0]


def _out_of_memory(e: BaseException) -> bool:
    """A load that failed for want of memory: MemoryError, onnxruntime's "bad
    allocation", or Windows' "paging file is too small" when a DLL won't load."""
    if isinstance(e, MemoryError):
        return True
    text = str(e).lower()
    return any(s in text for s in ("bad allocation", "bad_alloc", "paging file",
                                   "not enough memory", "out of memory"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--voice", default="")
    ap.add_argument("--pitch", type=float, default=0.0, help="extra semitones")
    ap.add_argument("--no-auto-pitch", action="store_true")
    ap.add_argument("--download", action="store_true", help="fetch the model and exit")
    ap.add_argument("--self-test", action="store_true", help="print the real-time factor")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    voices = load_voices()
    if args.download:
        return download(lambda s: print(s, flush=True))
    if args.self_test:
        from converter import self_test
        rtf = self_test(model_dir(), pick(voices, args.voice), light=LIGHT)
        print(f"real-time factor {rtf:.3f}")
        return 0
    if args.port is None or not args.token:
        ap.error("--port and --token are required (Onion Board starts this; don't run it "
                 "by hand)")

    sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    link = Link(sock)
    link.send(type="hello", token=args.token, name="ai-voices", version=VERSION)

    def fail(text: str) -> int:
        log.error("%s", text)          # the module log says why, too
        link.send(type="error", text=text)
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        return 1

    voice = dict(pick(voices, args.voice))
    voice["pitch"] = float(voice.get("pitch", 0.0)) + args.pitch
    rtf = 0.0
    if args.fake:
        conv = FakeConverter(light=LIGHT)
        conv.set_voice(voice)
    else:
        if not model_ready():
            return fail("the voice model isn't downloaded: press Install AI voices again")
        link.send(type="status", text="loading the voice…")
        try:
            from converter import Converter, self_test
            rtf = self_test(model_dir(), voice, seconds=1.0, light=LIGHT)
            conv = Converter(model_dir(), voice, light=LIGHT)
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            if _out_of_memory(e):
                return fail("not enough free memory to load the voice: close a big program "
                            "and try again")
            if isinstance(e, ImportError):
                return fail("AI voices aren't fully installed: press Update under More options")
            return fail(f"couldn't load the voice model ({e}); press Update under More options")
        log.info("self-test: real-time factor %.3f", rtf)
    conv.auto_pitch = not args.no_auto_pitch
    chunk = CHUNK * conv.t // 2
    if conv.t != 2:
        log.info("lighter model: %d ms a call", chunk // 16)
    link.send(type="ready", rate=OUT_RATE, rtf=round(rtf, 3), slow=rtf > TOO_SLOW,
              voice=voice.get("id", ""), chunk_s=chunk / 16000)

    buf = np.zeros(0, np.float32)
    busy = 0.0                     # seconds spent converting since the last stats
    done = 0                       # chunks converted since the last stats
    cpu0, wall0 = time.process_time(), time.monotonic()
    while True:
        try:
            msg = protocol.recv(sock)
        except OSError:
            msg = None
        if msg is None:
            break
        kind, payload = msg
        if kind == protocol.JSON:
            m = protocol.decode_json(payload)
            t = m.get("type")
            if t == "quit":
                break
            if t == "quiet":           # you stopped talking: a good moment to re-aim the pitch
                conv.settle_pitch()
            elif t == "config":
                try:
                    if "voice" in m:
                        if not any(v["id"] == m["voice"] for v in voices["voices"]):
                            voices = load_voices()     # one made since this started
                        voice = dict(pick(voices, str(m["voice"])))
                        voice["pitch"] = float(voice.get("pitch", 0.0)) + float(m.get("pitch", 0.0))
                        conv.set_voice(voice)
                        conv.settle_pitch(force=True)
                    if "auto_pitch" in m:
                        conv.auto_pitch = bool(m["auto_pitch"])
                        conv.settle_pitch(force=True)
                except (KeyError, TypeError, ValueError) as e:
                    link.send(type="status", text=f"couldn't switch voice: {e}")
            continue
        if kind != protocol.AUDIO:
            continue
        buf = np.concatenate([buf, np.frombuffer(payload, "<i2").astype(np.float32) / 32768.0])
        while len(buf) >= chunk:
            t0 = time.perf_counter()
            y = conv.process(buf[:chunk])
            busy += time.perf_counter() - t0
            done += 1
            buf = buf[chunk:]
            link.audio(y)
        now = time.monotonic()
        if now - wall0 >= 2.0:
            cpu = time.process_time()
            rtf = round(busy / max(done * chunk / 16000, 1e-9), 3) if done else 0.0
            link.send(type="stats", rtf=rtf,
                      cpu=round((cpu - cpu0) / (now - wall0) * 100, 1),
                      shift=round(float(getattr(conv, "shift_st", 0.0)), 1))
            busy, done, cpu0, wall0 = 0.0, 0, cpu, now
    return 0


if __name__ == "__main__":
    sys.exit(main())
