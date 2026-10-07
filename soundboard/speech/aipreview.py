"""Hear an AI voice before you use it: a short line said by a Windows voice, run
through the add-on's converter offline, played to your headphones only.

The converting happens in the add-on's own Python (CHILD, run with `-c`, so it works
with any copy of the add-on that has converter.py) and takes a couple of seconds;
the result is kept for the rest of the run, keyed by the voice's sound. Nothing goes
online. Call everything here off the UI thread.
"""
from __future__ import annotations

import json
import logging
import subprocess

import numpy as np

from soundboard import errors, net
from soundboard.modules import ModuleInfo

log = logging.getLogger(__name__)

LINE = "Hey, can you hear me okay? This is what I sound like now."
IN_RATE, OUT_RATE = 16000, 24000
TIMEOUT_S = 60
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# argv: add-on folder, voice JSON; stdin: float32 mono 16 kHz; stdout: float32 24 kHz
CHILD = r"""
import json, sys
from pathlib import Path
import numpy as np
d = Path(sys.argv[1]); sys.path.insert(0, str(d))
import converter as C
x = np.frombuffer(sys.stdin.buffer.read(), np.float32)
c = C.Converter(d / "model", json.loads(sys.argv[2]), seed=0)
step = C.HOP_IN * C.T
x = np.concatenate([x, np.zeros(step * 10, np.float32)])
x = x[:len(x) - len(x) % step]
out = [c.process(x[i:i + step]) for i in range(0, len(x), step)]
sys.stdout.buffer.write(np.concatenate(out).astype(np.float32).tobytes())
"""

_sample: np.ndarray | None = None
_cache: dict[str, np.ndarray] = {}


class PreviewError(RuntimeError):
    """str() says why, in plain words."""


def key(voice: dict) -> str:
    """What a voice sounds like (its name and words don't change that)."""
    return json.dumps([voice.get("mix"), voice.get("formant"), voice.get("pitch_hz")])


def cached(voice: dict) -> np.ndarray | None:
    return _cache.get(key(voice))


def sample() -> np.ndarray:
    """The line to convert: float32 mono at 16 kHz (made once per run)."""
    global _sample
    if _sample is None:
        from soundboard.engine import resample
        from soundboard.speech.tts import SapiTTS
        tts = SapiTTS()
        try:
            mono, sr = tts.synth(LINE)
        except (OSError, RuntimeError) as e:
            raise PreviewError(f"Windows' speech voice couldn't make the sample line "
                               f"({errors.plain(e)})") from e
        finally:
            tts.close()
        if not len(mono):
            raise PreviewError("Windows' speech voice made no sound")
        _sample = resample(np.asarray(mono, np.float32), int(sr), IN_RATE)
    return _sample


def render(module: ModuleInfo, voice: dict, mono16: np.ndarray) -> np.ndarray:
    """`mono16` in `voice`: float32 mono at 24 kHz. Raises PreviewError."""
    py = module.path / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        raise PreviewError("AI voices aren't installed yet")
    spec = {k: voice[k] for k in ("mix", "formant", "pitch_hz") if k in voice}
    try:
        p = subprocess.run([str(py), "-c", CHILD, str(module.path), json.dumps(spec)],
                           input=np.asarray(mono16, np.float32).tobytes(),
                           capture_output=True, timeout=TIMEOUT_S, creationflags=_NO_WINDOW,
                           env=net.child_env("voices"))
    except subprocess.TimeoutExpired as e:
        raise PreviewError("making the sample took too long") from e
    except OSError as e:
        raise PreviewError(f"the add-on couldn't start ({errors.plain(e)})") from e
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["?"]
        log.warning("AI voice preview failed: %s", p.stderr.decode("utf-8", "replace")[-2000:])
        raise PreviewError(f"the add-on couldn't make the sample ({tail[0][:160]})")
    out = np.frombuffer(p.stdout, np.float32)
    if not len(out):
        raise PreviewError("the add-on made no sound")
    return out


def make(module: ModuleInfo, voice: dict) -> np.ndarray:
    """The sample in `voice`, ready for engine.play: float32 stereo at 48 kHz, peak
    0.8 at most. Raises PreviewError."""
    k = key(voice)
    if k not in _cache:
        from soundboard.engine import SR, resample
        y = resample(render(module, voice, sample()), OUT_RATE, SR)
        peak = float(np.max(np.abs(y))) if len(y) else 0.0
        if peak > 0.8:
            y = y * (0.8 / peak)
        _cache[k] = np.ascontiguousarray(np.stack([y, y], axis=1), np.float32)
    return _cache[k]
