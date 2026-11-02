"""The real meows and barks the Cat and Dog voices play (voicefx.builtin.animals).

They're public-domain (CC0) recordings, downloaded the first time Cat or Dog is
used and kept in the app's cache: the app ships no audio of its own. Each file is
pinned to its SHA-256 and cut into single calls at the times listed here, so a file
that changed upstream is never used (the voice keeps its made-up call instead, as it
does until the download is in, or offline).

`fetch(kind)` (any thread but the audio one) starts the download in the background;
`calls(kind)` (any thread, the audio one too) is the calls once they're ready, or
None. The calls are mono float32 at RATE, each at the same loudness (CALL_RMS).
"""
from __future__ import annotations

import logging
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from soundboard.core import errors

log = logging.getLogger(__name__)

RATE = 48000
CALL_RMS = 0.1          # every call made this loud (about -20 dBFS)
FADE_IN_S, FADE_OUT_S = 0.004, 0.04
TIMEOUT_S = 30
MAX_BYTES = 2 << 20     # the most one file may be (they're all under 1 MB)


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    cuts: tuple[tuple[float, float], ...]   # (start, end) seconds of each call in it


_COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"
_BSB = "https://bigsoundbank.com/UPLOAD/ogg/"
SOURCES: dict[str, tuple[Source, ...]] = {
    "cat": (
        # Wikimedia Commons, CC0: "Meow of a Siamese cat - freemaster2.wav"
        Source(_COMMONS + "8/81/Meow_of_a_Siamese_cat_-_freemaster2.wav",
               "c5ae80383913b599b697bdb03481807dce908b44497f68583183530c6490f9d4",
               ((0.04, 1.12),)),
        # Wikimedia Commons, CC0: "MeowUSA.wav"
        Source(_COMMONS + "7/7d/MeowUSA.wav",
               "268fd93f966804df6cb6c518c4393dd99b36ce814ae1cb6499b5e032c0a233bf",
               ((0.53, 1.13),)),
        # Wikimedia Commons, CC0: "Black cat sound begging the foods.flac"
        Source(_COMMONS + "7/77/Black_cat_sound_begging_the_foods.flac",
               "4c045e57dc1b8af4fadce9146481f4c5b3b233bcf28d07bf2c567d8dd168739f",
               ((0.02, 0.66), (0.80, 1.56), (2.30, 2.95), (3.43, 3.97), (4.63, 5.40),
                (6.13, 7.08))),
    ),
    "dog": (
        # BigSoundBank #0112 "Barking dog inside", CC0
        Source(_BSB + "0112.ogg",
               "d9779ac6b04dd6d1d7372bb2c9ce1830d5485564749eb03b8c9c25dcdea561ed",
               ((0.06, 0.42), (0.84, 1.22), (1.41, 1.89), (2.07, 2.47), (3.80, 4.19),
                (4.66, 5.07), (6.61, 7.01), (7.51, 7.93), (8.81, 9.21))),
        # BigSoundBank #2954 "Barking dog #2", CC0
        Source(_BSB + "2954.ogg",
               "5663ebf5326cb7f3317ec2bf582e66bd62829491f2eac06f387c1b9356c4df54",
               ((0.05, 0.35), (0.39, 0.66), (2.44, 2.69), (8.02, 8.32), (11.76, 12.00))),
        # BigSoundBank #2955 "Barking dog #3", CC0: one bark (then a long room tail)
        Source(_BSB + "2955.ogg",
               "226a416d51343c71f9ecfc2518720b7cf43a28f8f8616ee730f9aed5b1af886c",
               ((0.02, 0.36),)),
    ),
}

_calls: dict[str, tuple[np.ndarray, ...]] = {}
_busy: set[str] = set()
_lock = threading.Lock()


def calls(kind: str) -> tuple[np.ndarray, ...] | None:
    """The calls for "cat" / "dog", once downloaded and cut; None until then."""
    return _calls.get(kind)


def cache_dir() -> Path:
    from soundboard.sounds.paths import CACHE_DIR
    return CACHE_DIR / "voice-calls"


def fetch(kind: str):
    """Get `kind`'s calls ready in the background (once; a failed try is tried
    again the next time the voice is picked)."""
    if kind not in SOURCES:
        return
    with _lock:
        if kind in _calls or kind in _busy:
            return
        _busy.add(kind)
    threading.Thread(target=_load, args=(kind,), name=f"voice-calls-{kind}",
                     daemon=True).start()


def _load(kind: str):
    try:
        cut: list[np.ndarray] = []
        for src in SOURCES[kind]:
            try:
                cut += _cut(_read(_file(src)), src.cuts)
            except Exception as ex:  # noqa: BLE001 - the others may still do
                log.warning("%s sounds: %s couldn't be used: %s", kind, src.url,
                            errors.plain(ex))
        if cut:
            _calls[kind] = tuple(cut)   # one write: the audio thread sees all or none
            log.info("%s sounds ready: %d calls", kind, len(cut))
    finally:
        with _lock:
            _busy.discard(kind)


def _file(src: Source) -> Path:
    """The source's file in the cache, downloaded (and checked) if it isn't there."""
    import hashlib
    dest = cache_dir() / (src.sha256[:16] + Path(src.url).suffix)
    if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == src.sha256:
        return dest
    from soundboard.online import net
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        req = urllib.request.Request(src.url, headers={"User-Agent": "OnionBoard"})
        with net.urlopen(req, timeout=TIMEOUT_S, feature="voices") as r, open(tmp, "wb") as f:
            got = net.read_capped(r, f, MAX_BYTES)
        if got != src.sha256:
            raise RuntimeError("the file has changed since this version of the app was made")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _read(path: Path) -> np.ndarray:
    """The file as mono float32 at RATE."""
    import soundfile
    x, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if rate != RATE:
        import soxr
        x = soxr.resample(x, rate, RATE)
    return np.ascontiguousarray(x, np.float32)


def _cut(x: np.ndarray, cuts) -> list[np.ndarray]:
    """Each call cut out, faded in and out, and made CALL_RMS loud."""
    out = []
    fin, fout = int(FADE_IN_S * RATE), int(FADE_OUT_S * RATE)
    for a, b in cuts:
        c = x[int(a * RATE):int(b * RATE)].copy()
        if len(c) < fin + fout:
            continue
        c -= c.mean()
        c[:fin] *= np.linspace(0, 1, fin, dtype=np.float32)
        c[-fout:] *= np.linspace(1, 0, fout, dtype=np.float32)
        rms = float(np.sqrt(np.mean(c * c)))
        if rms > 1e-5:
            c *= np.float32(CALL_RMS / rms)
            peak = float(np.max(np.abs(c)))
            if peak > 0.95:          # a spiky one: its peak kept under full scale
                c *= np.float32(0.95 / peak)
            out.append(c)
    return out
