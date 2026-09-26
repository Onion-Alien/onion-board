"""Live voice-to-speech module: listens to the mic, sends back what you said as text.

Launched by the Soundboard app (never run by hand; it needs the app's --port and
--token). The app speaks each line with the text-to-speech voice you picked, so
others hear that voice instead of yours.

    mic audio (16 kHz int16) -> Segmenter (energy VAD) -> utterance
                             -> faster-whisper [-> Translator] -> {"type": "final", "text": ...}

With --translate <folder> (a translation add-on's downloaded model), each line is
translated from English before it's sent; "original" then carries what was said.

Runs in its own Python environment (install.bat makes it) so the ~100 MB of
speech-recognition libraries never touch the app itself.
"""
from __future__ import annotations

import argparse
import logging
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


class FakeTranscriber:
    """For tests: no model, just reports what it was given."""

    def __init__(self):
        self.n = 0

    def __call__(self, audio: np.ndarray) -> str:
        self.n += 1
        return f"utterance {self.n} ({len(audio) / RATE:.1f}s)"


class WhisperTranscriber:
    # things Whisper "hears" in noise or silence
    JUNK = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.",
            "bye.", "."}

    def __init__(self, model: str, language: str | None, device: str):
        from faster_whisper import WhisperModel
        self.language = language or None
        self.model = WhisperModel(model, device=device,
                                  compute_type="int8" if device == "cpu" else "float16")

    def __call__(self, audio: np.ndarray) -> str:
        segs, _ = self.model.transcribe(audio, language=self.language, beam_size=1,
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

    def __call__(self, text: str) -> str:
        parts = [p for p in self.SENTENCE.split(text.strip()) if p]
        if not parts:
            return ""
        res = self.model.translate_batch([self.sp.encode(p, out_type=str) for p in parts],
                                         beam_size=2, max_decoding_length=256)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--download", metavar="MODEL",
                    help="just download a speech model (used by the installer) and exit")
    ap.add_argument("--model", default="base.en",
                    help="tiny.en, base.en, small.en, … (multilingual: base, small, …)")
    ap.add_argument("--language", default="en", help="spoken language code, or 'auto'")
    ap.add_argument("--device", default="cpu", help="cpu or cuda")
    ap.add_argument("--translate", metavar="FOLDER",
                    help="a downloaded translation model: speak each line in its language")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.download:
        print(f"Downloading the speech model {args.download} (about 150 MB)...", flush=True)
        from faster_whisper import WhisperModel
        WhisperModel(args.download, device="cpu", compute_type="int8")
        print("Speech model ready.", flush=True)
        return 0
    if args.port is None or not args.token:
        ap.error("--port and --token are required (Soundboard starts this; don't run it "
                 "by hand)")

    sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    link = Link(sock)
    link.send(type="hello", token=args.token, name="live-voice", version="0.3.0")

    ready = threading.Event()
    work: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=8)
    seg = Segmenter()

    def transcribe_loop():
        link.send(type="status", text=f"loading speech model ({args.model})…")
        try:
            t = FakeTranscriber() if args.fake else WhisperTranscriber(
                args.model, None if args.language == "auto" else args.language, args.device)
        except ImportError:
            link.send(type="error", text="speech recognition isn't installed: run install.bat "
                                         "in the live-voice module folder")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            link.send(type="error", text=f"couldn't load the speech model: {e}")
            return
        tr = None
        if args.translate:
            link.send(type="status", text="loading translation…")
            try:
                tr = FakeTranslator() if args.fake else Translator(args.translate, args.device)
            except ImportError:
                link.send(type="error", text="translation needs an update to speech "
                                             "recognition: press Update speech recognition "
                                             "under More options, then Start again")
                return
            except Exception as e:  # noqa: BLE001
                log.exception("translation model load failed")
                link.send(type="error", text=f"couldn't load the translation: {e}")
                return
        ready.set()
        link.send(type="ready")
        while (audio := work.get()) is not None:
            t0 = time.monotonic()
            try:
                text = t(audio)
            except Exception as e:  # noqa: BLE001
                log.exception("transcription failed")
                link.send(type="error", text=f"transcription failed: {e}")
                continue
            log.info("%.1fs of speech -> %r in %.2fs", len(audio) / RATE, text,
                     time.monotonic() - t0)
            if text and tr is not None:
                t0 = time.monotonic()
                try:
                    said = tr(text)
                except Exception as e:  # noqa: BLE001
                    log.exception("translation failed")
                    link.send(type="error", text=f"translation failed: {e}")
                    continue
                log.info("  translated -> %r in %.2fs", said, time.monotonic() - t0)
                if said:
                    link.send(type="final", text=said, original=text)
            elif text:
                link.send(type="final", text=text)

    threading.Thread(target=transcribe_loop, daemon=True).start()

    was = False
    while True:
        try:
            msg = protocol.recv(sock)
        except OSError:
            msg = None
        if msg is None:
            break
        kind, payload = msg
        if kind == protocol.JSON:
            if protocol.decode_json(payload).get("type") == "quit":
                break
            continue
        if kind != protocol.AUDIO or not ready.is_set():
            continue
        x = np.frombuffer(payload, "<i2").astype(np.float32) / 32768.0
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
