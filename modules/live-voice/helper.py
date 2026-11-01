"""Live voice-to-speech module: listens to the mic, sends back what you said as text.

Launched by the Onion Board app (never run by hand; it needs the app's --port and
--token). The app speaks each line with the text-to-speech voice you picked, so
others hear that voice instead of yours.

    mic audio (16 kHz int16) -> Segmenter (energy VAD) -> utterance
                             -> faster-whisper [-> Translator] -> {"type": "final", "text": ...}

With --translate <folder> (a translation add-on's downloaded model), each line is
translated from English before it's sent; "original" then carries what was said.
The models go from English only: --task translate has Whisper hear any other
language straight into English first.

A whole clip (a sound to say in another language) comes as {"type": "clip", "id"},
its audio, then {"type": "clip_end", "id"}: it's cut up the same way, and each line
comes back with when it starts ({"type": "clip_line", "id", "at", "text"}), then
{"type": "clip_done", "id"}.

Runs in its own Python environment (install.bat makes it) so the ~100 MB of
speech-recognition libraries never touch the app itself.
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import re
import socket
import sys
import threading
import time
from collections import deque

import numpy as np

import protocol

log = logging.getLogger("live-voice")

# plain downloads, written to the cache as they come (fetch_model's progress counts
# them); Xet's put a model there only once it's whole
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# Hugging Face gives up on a read after 10 s, which a slow proxy or Tor (the app's
# Connection setting) can take on a 150 MB model: a minute, and DOWNLOAD_TRIES
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")
DOWNLOAD_TRIES = 3                 # the install's model download; it carries on from
DOWNLOAD_WAIT_S = (5, 15)          # what it got (huggingface_hub keeps the part)

RATE = protocol.AUDIO_RATE
FRAME = RATE * 30 // 1000          # 30 ms analysis frames


class Segmenter:
    """Splits a live stream into utterances by loudness against the noise floor.

    Speech starts when a frame is well above the (slowly tracked) background level
    and ends after `hang_s` of quiet; a little audio from before the start is kept
    so first consonants aren't clipped."""

    def __init__(self, hang_s=0.6, preroll_s=0.3, min_s=0.3, max_s=15.0, min_level=0.01):
        self.hang = int(hang_s * 1000 / 30)
        self.min_frames = int(min_s * 1000 / 30)
        self.max_frames = int(max_s * 1000 / 30)
        self.min_level = min_level
        self.pre: deque[np.ndarray] = deque(maxlen=int(preroll_s * 1000 / 30))
        self.floor = 0.0
        self.speaking = False
        self.frames: list[np.ndarray] = []
        self.voiced = 0
        self.quiet = 0
        self._rest = np.zeros(0, np.float32)

    def threshold(self) -> float:
        return max(self.min_level, self.floor * 3.0)

    def feed(self, x: np.ndarray) -> list[np.ndarray]:
        """Push float32 samples; returns any utterances that just finished."""
        x = np.concatenate([self._rest, x])
        done = []
        n = len(x) // FRAME
        for k in range(n):
            f = x[k * FRAME:(k + 1) * FRAME]
            utt = self._frame(f)
            if utt is not None:
                done.append(utt)
        self._rest = x[n * FRAME:]
        return done

    def _frame(self, f: np.ndarray) -> np.ndarray | None:
        rms = float(np.sqrt(np.mean(f * f)))
        th = self.threshold()
        if not self.speaking:
            # background level: falls quickly, rises slowly (so speech doesn't raise it)
            a = 0.2 if rms < self.floor else 0.01
            self.floor += (rms - self.floor) * a
            if rms > th:
                self.speaking = True
                self.frames = list(self.pre) + [f]
                self.voiced, self.quiet = 1, 0
            else:
                self.pre.append(f)
            return None
        self.frames.append(f)
        if rms > th * 0.7:
            self.voiced += 1
            self.quiet = 0
        else:
            self.quiet += 1
        if self.quiet >= self.hang or len(self.frames) >= self.max_frames:
            self.speaking = False
            self.pre.clear()
            utt = np.concatenate(self.frames)
            voiced, self.frames = self.voiced, []
            return utt if voiced >= self.min_frames else None
        return None


def clip_segments(x: np.ndarray) -> list[tuple[float, np.ndarray]]:
    """A whole clip's utterances, cut like the live stream's, each with when it starts
    (seconds). The clip's end ends the last one."""
    seg = Segmenter()
    out: list[tuple[float, np.ndarray]] = []
    start = 0
    for k in range(len(x) // FRAME):
        was = seg.speaking
        utt = seg._frame(x[k * FRAME:(k + 1) * FRAME])
        if not was and seg.speaking:   # its frames: the ones kept from before, and this
            start = max(0, k + 1 - len(seg.frames))
        if utt is not None:
            out.append((start * FRAME / RATE, utt))
    if seg.speaking and seg.voiced >= seg.min_frames:
        out.append((start * FRAME / RATE, np.concatenate(seg.frames)))
    return out


class FakeTranscriber:
    """For tests: no model, just reports what it was given."""

    def __init__(self):
        self.n = 0

    def __call__(self, audio: np.ndarray) -> str:
        self.n += 1
        return f"utterance {self.n} ({len(audio) / RATE:.1f}s)"


# each speech model's download, for its progress (the files as they land on disk)
MODEL_BYTES = {"tiny": 75_500_000, "tiny.en": 75_500_000, "base": 147_400_000,
               "base.en": 147_400_000, "small": 485_800_000, "small.en": 485_800_000}


def have_model(name: str) -> bool:
    """The speech model is on this PC already (looked up without going online)."""
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001  (not there, or not whole)
        return False


class DownloadFailed(Exception):
    """The speech model isn't on this PC and downloading it failed (no internet, a
    dropped connection)."""


def model_folder(name: str) -> str:
    """The model's folder in the Hugging Face cache (there or not)."""
    from faster_whisper.utils import _MODELS
    from huggingface_hub import constants
    repo = _MODELS.get(name, name)
    return os.path.join(constants.HF_HUB_CACHE, "models--" + repo.replace("/", "--"))


STALE_PART_S = 300      # a part that hasn't grown for this long isn't being written


def clean_parts(name: str) -> int:
    """Delete what a download cut short by End task, a crash or a power cut left
    behind: huggingface_hub names each try's part `<file>.<random>.incomplete` and
    never picks one up again, so they'd sit there for good (up to the model's size,
    and fetch_model's progress would count them). A part still being written is
    open (Windows won't delete it) or recent: kept. Returns how many went."""
    try:
        blobs = os.path.join(model_folder(name), "blobs")
        names = os.listdir(blobs)
    except (ImportError, OSError):     # not installed (the download says so), no parts
        return 0
    gone = 0
    for f in names:
        # <file>.<random>.incomplete only: an older huggingface_hub's <file>.incomplete
        # is carried on from, so it stays
        if not re.fullmatch(r"[^.]+\.[0-9a-f]{8}\.incomplete", f):
            continue
        path = os.path.join(blobs, f)
        try:
            if time.time() - os.path.getmtime(path) > STALE_PART_S:
                os.remove(path)
                gone += 1
        except OSError:
            pass
    if gone:
        log.info("removed %d unfinished speech model download part(s)", gone)
    return gone


def fetch_model(name: str, progress) -> str:
    """The speech model's folder, downloaded first when it isn't on this PC yet;
    `progress(done, total)` (bytes) every half second meanwhile. The download's own
    progress bars belong to huggingface_hub (unpinned, they change), so this counts
    the model's cache folder instead: its files and the parts still coming in."""
    from faster_whisper.utils import download_model
    try:
        return download_model(name, local_files_only=True)
    except Exception:  # noqa: BLE001  (not there yet, or not whole)
        pass
    folder = model_folder(name)
    clean_parts(name)
    total = MODEL_BYTES.get(name, 0)
    stop = threading.Event()

    def watch():
        while not stop.wait(0.5):
            done = 0
            for root, _dirs, files in os.walk(folder):
                for f in files:
                    try:
                        done += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass          # moved from blobs\ to snapshots\ just now
            if done:
                progress(done, max(total, done))

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        return download_model(name)
    except (ValueError, ImportError):   # not a model name, not fully installed
        raise
    except Exception as e:  # noqa: BLE001 - no internet, a dropped connection
        log.warning("speech model download failed: %s", e)
        raise DownloadFailed(str(e)) from e
    finally:
        stop.set()
        t.join()


class WhisperTranscriber:
    # things Whisper "hears" in noise or silence
    JUNK = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.",
            "bye.", "."}

    def __init__(self, model: str, language: str | None, device: str,
                 task: str = "transcribe", progress=lambda done, total: None):
        from faster_whisper import WhisperModel
        self.language = language or None
        self.task = task
        self.model = WhisperModel(fetch_model(model, progress), device=device,
                                  compute_type="int8" if device == "cpu" else "float16")

    def __call__(self, audio: np.ndarray) -> str:
        segs, _ = self.model.transcribe(audio, language=self.language, task=self.task,
                                        beam_size=1,
                                        condition_on_previous_text=False,
                                        without_timestamps=True, vad_filter=False)
        parts = [s.text.strip() for s in segs
                 if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        text = " ".join(p for p in parts if p).strip()
        return "" if text.lower() in self.JUNK else text


class Translator:
    """English -> another language with a CTranslate2 model + SentencePiece (the
    layout of an Argos Translate package, as the app unpacks it)."""
    SENTENCE = re.compile(r"(?<=[.!?])\s+")
    CJK = re.compile("[　-鿿＀-￯]")

    def __init__(self, folder: str, device: str):
        import ctranslate2
        import sentencepiece
        self.sp = sentencepiece.SentencePieceProcessor(model_file=f"{folder}/sentencepiece.model")
        self.model = ctranslate2.Translator(f"{folder}/model", device=device,
                                            compute_type="int8" if device == "cpu" else "auto")
        # the app's Use less CPU: one guess per word instead of two
        self.beams = 1 if os.environ.get("ONIONBOARD_LESS_CPU") == "1" else 2

    def __call__(self, text: str) -> str:
        parts = [p for p in self.SENTENCE.split(text.strip()) if p]
        if not parts:
            return ""
        res = self.model.translate_batch([self.sp.encode(p, out_type=str) for p in parts],
                                         beam_size=self.beams, max_decoding_length=256)
        # joined by hand: some models' target pieces aren't in the source tokenizer
        out = ["".join(r.hypotheses[0]).replace("▁", " ").strip() for r in res]
        text = ""
        for o in (o for o in out if o):   # no space after Chinese / Japanese sentences
            text += ("" if not text or self.CJK.search(text[-1]) else " ") + o
        return text


class FakeTranslator:
    """For tests: no model."""

    def __call__(self, text: str) -> str:
        return f"[translated] {text}"


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


def download(name: str) -> int:
    """The install's step: the speech model downloaded (tried again when the connection
    drops) and loaded once to check it. Returns the exit code."""
    print(f"Downloading the speech model {name} (about 150 MB)...", flush=True)
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    clean_parts(name)
    for attempt in range(DOWNLOAD_TRIES):
        try:
            folder = download_model(name)
            break
        except ValueError:            # not a model name: trying again won't help
            raise
        except Exception as e:  # noqa: BLE001 - a dropped connection, a server error
            log.warning("speech model download failed: %s", e)
            if attempt + 1 == DOWNLOAD_TRIES:
                print(f"Couldn't download the speech model ({e}). Check your internet "
                      "connection and press Install again.", flush=True)
                return 1
            wait = DOWNLOAD_WAIT_S[min(attempt, len(DOWNLOAD_WAIT_S) - 1)]
            print(f"The download stopped ({e}); trying again in {wait} s...", flush=True)
            time.sleep(wait)
    WhisperModel(folder, device="cpu", compute_type="int8")
    print("Speech model ready.", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--download", metavar="MODEL",
                    help="just download a speech model (used by the installer) and exit")
    ap.add_argument("--model", default="base.en",
                    help="tiny.en, base.en, small.en, … (multilingual: base, small, …)")
    ap.add_argument("--language", default="en", help="spoken language code, or 'auto'")
    ap.add_argument("--task", default="transcribe", choices=("transcribe", "translate"),
                    help="translate: write what was said in English (multilingual models)")
    ap.add_argument("--device", default="cpu", help="cpu or cuda")
    ap.add_argument("--translate", metavar="FOLDER",
                    help="a downloaded translation model: speak each line in its language")
    ap.add_argument("--lighter", metavar="MODEL",
                    help="Use less CPU: this smaller model instead, if it's already on "
                         "this PC (never downloaded for it)")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.download:
        return download(args.download)
    if args.port is None or not args.token:
        ap.error("--port and --token are required (Onion Board starts this; don't run it "
                 "by hand)")

    sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    link = Link(sock)
    link.send(type="hello", token=args.token, name="live-voice", version="0.4.0")

    ready = threading.Event()
    failed = threading.Event()
    work: queue.Queue[np.ndarray | tuple | None] = queue.Queue(maxsize=8)
    seg = Segmenter()

    def fail(text: str):
        """Couldn't load: say why, then end the connection so the whole helper exits
        (the app gives the real mic back when it sees that)."""
        failed.set()
        link.send(type="error", text=text)
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        # on Windows the main loop's recv() may not wake up for that: don't linger
        quit_ = threading.Timer(1.0, os._exit, (1,))
        quit_.daemon = True
        quit_.start()

    def transcribe_loop():
        if args.lighter and not args.fake and have_model(args.lighter):
            log.info("Use less CPU: %s in place of %s", args.lighter, args.model)
            args.model = args.lighter
        link.send(type="status", text=f"loading speech model ({args.model})…")
        try:
            t = FakeTranscriber() if args.fake else WhisperTranscriber(
                args.model, None if args.language == "auto" else args.language, args.device,
                args.task, lambda done, total: link.send(type="download", done=done,
                                                         total=total))
        except ImportError:
            fail("speech recognition isn't fully installed: press Update speech recognition "
                 "under More options, then Start again")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            if isinstance(e, DownloadFailed) and os.environ.get("HF_HUB_OFFLINE") != "1":
                fail(f"couldn't download the speech model {args.model}. Check your "
                     "internet connection, then Start again")
                return
            if os.environ.get("HF_HUB_OFFLINE") == "1":   # the app's voices switch is off
                fail(f"the speech model {args.model} isn't downloaded, and downloading "
                     "voices and speech models is switched off in Settings > Privacy & "
                     "security. Switch it on to download the model once, then Start again")
                return
            fail(f"couldn't load the speech model ({e}). Try another Recognition model "
                 "under More options, then Start again")
            return
        tr = None
        if args.translate:
            link.send(type="status", text="loading translation…")
            try:
                tr = FakeTranslator() if args.fake else Translator(args.translate, args.device)
            except ImportError:
                fail("translation needs an update to speech recognition: press Update "
                     "speech recognition under More options, then Start again")
                return
            except Exception as e:  # noqa: BLE001
                log.exception("translation model load failed")
                fail(f"couldn't load the translation ({e}). Delete its download and "
                     "download it again, then Start again")
                return
        ready.set()
        link.send(type="ready")

        def hear(audio: np.ndarray) -> tuple[str, str] | None:
            """(what to say, what was said when it was translated, else "")."""
            t0 = time.monotonic()
            try:
                text = t(audio)
            except Exception as e:  # noqa: BLE001
                log.exception("transcription failed")
                link.send(type="error", text=f"transcription failed: {e}")
                return None
            # never the words: this log is a file on disk, kept with the app log off too
            log.info("%.1fs of speech -> %d characters in %.2fs", len(audio) / RATE,
                     len(text or ""), time.monotonic() - t0)
            if not text or tr is None:
                return (text, "") if text else None
            t0 = time.monotonic()
            try:
                said = tr(text)
            except Exception as e:  # noqa: BLE001
                log.exception("translation failed")
                link.send(type="error", text=f"translation failed: {e}")
                return None
            log.info("  translated -> %d characters in %.2fs", len(said or ""),
                     time.monotonic() - t0)
            return (said, text) if said else None

        while (audio := work.get()) is not None:
            if isinstance(audio, tuple):   # a whole clip: ("clip", id, its utterances)
                _kind, cid, segs = audio
                for i, (at, utt) in enumerate(segs):
                    got = hear(utt)
                    if got is not None:
                        link.send(type="clip_line", id=cid, at=round(at, 3), text=got[0],
                                  original=got[1])
                    link.send(type="clip_progress", id=cid, done=i + 1, total=len(segs))
                link.send(type="clip_done", id=cid)
                continue
            got = hear(audio)
            if got is not None:
                said, orig = got
                if orig:
                    link.send(type="final", text=said, original=orig)
                else:
                    link.send(type="final", text=said)

    threading.Thread(target=transcribe_loop, daemon=True).start()

    was = False
    clip: list[np.ndarray] | None = None   # a whole clip's audio, while it comes in
    clip_id = None
    while True:
        try:
            msg = protocol.recv(sock)
        except OSError:
            msg = None
        if msg is None:
            break
        kind, payload = msg
        if kind == protocol.JSON:
            obj = protocol.decode_json(payload)
            t = obj.get("type")
            if t == "quit":
                break
            if t == "clip":
                clip, clip_id = [], obj.get("id")
            elif t == "clip_end" and clip is not None:
                x = np.concatenate(clip) if clip else np.zeros(0, np.float32)
                work.put(("clip", clip_id, clip_segments(x)))   # waits its turn, all of it
                clip = None
            continue
        if kind != protocol.AUDIO or not ready.is_set():
            continue
        x = np.frombuffer(payload, "<i2").astype(np.float32) / 32768.0
        if clip is not None:
            clip.append(x)
            continue
        for utt in seg.feed(x):
            try:
                work.put_nowait(utt)
            except queue.Full:
                link.send(type="status", text="falling behind; skipped a sentence")
        if seg.speaking != was:
            was = seg.speaking
            link.send(type="vad", speaking=was)
    try:
        work.put_nowait(None)
    except queue.Full:
        pass
    return 1 if failed.is_set() else 0


if __name__ == "__main__":
    sys.exit(main())
