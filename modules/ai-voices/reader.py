"""Reads text out loud with a Piper voice: the voice a language speaks in.

The AI voices turn sound into another voice, so a translated line (text) has to be
read out first. The app starts this once (`{python} reader.py`, in this add-on's own
Python) and keeps it running; one line at a time on stdin, one answer on stdout:

    {"text": "...", "model": "<voice>.onnx", "out": "<file>.wav", "speed": 1.0}
    -> {"ok": true}  or  {"error": "why"}

The first line is {"ready": true} once Piper is loaded (or {"error": ...} if it
can't be). A voice stays loaded after its first line (the last few are kept), so the
next line in that language starts at once.

    reader.py --say "text" --model x.onnx --out y.wav   one line, for a quick check
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import wave
from collections import OrderedDict
from pathlib import Path

log = logging.getLogger("ai-voices-reader")
KEEP = 3            # voices kept loaded (one is ~60 MB of memory)


class Reader:
    def __init__(self):
        from piper import PiperVoice, SynthesisConfig
        self._load, self._config = PiperVoice.load, SynthesisConfig
        self._voices: OrderedDict[str, object] = OrderedDict()

    def voice(self, model: str):
        v = self._voices.pop(model, None)
        if v is None:
            if not model.endswith(".onnx") or not Path(model).is_file():
                raise FileNotFoundError(f"no voice file {model}")
            v = self._load(model)
        self._voices[model] = v
        while len(self._voices) > KEEP:
            self._voices.popitem(last=False)
        return v

    def say(self, text: str, model: str, out: str, speed: float = 1.0) -> None:
        v = self.voice(model)
        if getattr(v.config, "phoneme_type", "") == "text":
            text = text.lower()   # letters as sounds (Ukrainian): its map has no capitals
        # length_scale: bigger is slower
        cfg = self._config(length_scale=1.0 / max(0.5, min(2.0, speed)))
        with wave.open(out, "wb") as w:
            v.synthesize_wav(text, w, syn_config=cfg)


def serve(stdin=sys.stdin, stdout=sys.stdout) -> int:
    def answer(**obj):
        stdout.write(json.dumps(obj) + "\n")
        stdout.flush()

    try:
        reader = Reader()
    except ImportError:
        answer(error="the language voices aren't installed: press Update under AI voices' "
                     "More options")
        return 1
    answer(ready=True)
    for line in stdin:
        try:
            req = json.loads(line)
            reader.say(str(req["text"]), str(req["model"]), str(req["out"]),
                       float(req.get("speed", 1.0)))
        except Exception as e:  # noqa: BLE001 - one bad line must not end the reader
            log.exception("couldn't read a line")
            answer(error=str(e) or type(e).__name__)
            continue
        answer(ok=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--say", help="read this one line, then exit")
    ap.add_argument("--model", help="the Piper voice (.onnx)")
    ap.add_argument("--out", help="the WAV file to write")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.say is not None:
        if not args.model or not args.out:
            ap.error("--say needs --model and --out")
        Reader().say(args.say, args.model, args.out)
        return 0
    # stdin/stdout carry the lines: UTF-8 whatever the console's code page
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    return serve()


if __name__ == "__main__":
    sys.exit(main())
