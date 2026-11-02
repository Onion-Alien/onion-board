"""The real meows, barks, farts and drums the Cat, Dog, Fart and Drum kit voices
play (voicefx.builtin.animals, voicefx.builtin.syllables).

They're public-domain (CC0) recordings, downloaded the first time the voice is
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
_FS = "https://cdn.freesound.org/previews/"
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
    # real farts, CC0: BigSoundBank's "Flatulence #1" to "#4", the rest from
    # Freesound (its preview copies, made from the CC0 uploads named below)
    "fart": (
        Source(_BSB + "0111.ogg",
               "3e0501161f7fad94aca3a9846948706295cb555cff1e1eb6279eb56e2b8fc3d7",
               ((0.0, 1.54),)),
        Source(_BSB + "0240.ogg",
               "0bb93f6948c56f91b6a907c8c877fe72cd98582c44e13e148a5640c4a25b5731",
               ((0.0, 0.38),)),
        Source(_BSB + "0241.ogg",
               "a84d03ca476fd5942b294f01f505859f69a8db5eefd7864eca539bbaf60bb36d",
               ((0.0, 0.23),)),
        Source(_BSB + "1031.ogg",
               "ce8184dfacca397edf836d456df0fb14813891c1f4047f83db38a7ce7a2d7379",
               ((0.11, 1.11),)),
        # Freesound #163386 "Fart 6" (Under7dude)
        Source(_FS + "163/163386_2943714-hq.ogg",
               "8f6edd945d4ce15947a6de1632264ebe36e299f6f4101b871e8643fe1cfc9bd2",
               ((0.02, 0.62),)),
        # Freesound #183551 "Juicy Fart5" (Zott820)
        Source(_FS + "183/183551_2558531-hq.ogg",
               "259b4d1325f0fbd60389b45b14fff882a876ec119041258e360b835e94d25854",
               ((0.04, 3.1),)),
        # Freesound #202528 "Farts, loud and flabby x7" (peridactyloptrix)
        Source(_FS + "202/202528_2737063-hq.ogg",
               "deb09ecea30dcf84f2953077b6131501b4fc680c2423d577c998fe54bab9e007",
               ((0.75, 1.17), (3.19, 3.94), (6.35, 8.12), (8.44, 8.64), (9.19, 9.32),
                (10.61, 12.46), (15.37, 15.87), (15.99, 16.14), (18.54, 19.21),
                (20.83, 21.3))),
        # Freesound #266450 "Chair Fart" (Ezcah)
        Source(_FS + "266/266450_1900515-hq.ogg",
               "0a83ea3571b1f6ca6e0a62803cb9fdbb9cc966df24e165e65eadb65510511a60",
               ((0.05, 2.69),)),
        # Freesound #610067 "Fart.mp3" (TeddyFerguson)
        Source(_FS + "610/610067_7376654-hq.ogg",
               "89c829b5f84ede285b4c719c7f265292e61c42adcb3316096b4924a81f3904dd",
               ((0.62, 0.92),)),
        # Freesound #640804 "2 part fart" (DSISStudios)
        Source(_FS + "640/640804_2628301-hq.ogg",
               "f42fb3c74c673d9e70bd3a075a3d5452e535b8e64faa9ab51497f4c4a02e3c67",
               ((0.0, 0.33), (0.41, 0.61))),
        # Freesound #645339 "Nasty fart" (SamsterBirdies)
        Source(_FS + "645/645339_5487341-hq.ogg",
               "01a61e387286b7c457d7d4ebb42af676cda9b52c6cf073c5cd144923db6de287",
               ((0.0, 0.53),)),
        # Freesound #732936 "Blubberfreak Fart 23" (Blubberfreak)
        Source(_FS + "732/732936_15881540-hq.ogg",
               "dbed51553ec22d45f642ca586d5b3fea8420799632768be16525662728ca367d",
               ((0.95, 1.69), (1.93, 2.57))),
        # Freesound #874487 "Fart - Close recording" (Sadiquecat)
        Source(_FS + "874/874487_5287430-hq.ogg",
               "aaa326536e6db2c31cf3ee6ecd2c6fcaf33d13a02958945ee7bcd719433f94f1",
               ((0.0, 0.19),)),
    ),
    # a real drum kit, CC0: BigSoundBank's recorded kit (snares, closed hi-hats, a 16"
    # crash), and two kicks from Freesound
    "drum-kick": (
        # Freesound #581461 "Fractanimal_Acoustic_Drum_Kit_Kick_7.wav" (johnnydekk)
        Source(_FS + "581/581461_5790048-hq.ogg",
               "b2f304a57383a89aa81b0c2d9294dd0a99abef5b465834294ea54774e6b72d86",
               ((0.0, 0.4),)),
        # Freesound #860524 "Big Rock Bass Drum 24in One Shot" (lennartgreen)
        Source(_FS + "860/860524_3661618-hq.ogg",
               "e9c48439aa8d9985c416d5f466a1534f092929fa31cc899bda95ac3633f0762a",
               ((0.0, 0.6),)),
    ),
    "drum-snare": (
        # BigSoundBank #2304, #2308, #2310 "Snare drum #1", "#5", "#7"
        Source(_BSB + "2304.ogg",
               "4bfc9a823faad7b5cbec153af655fba3479bcbe05cdc0f4a978e085bb83a1978",
               ((0.0, 0.4),)),
        Source(_BSB + "2308.ogg",
               "c84d094c1617ab5916c386fa5d181e0c351f26563b0bc73de5d9f84f7f5bf3ad",
               ((0.0, 0.5),)),
        Source(_BSB + "2310.ogg",
               "136212a5d56fcba12605472bc052bfdb66f0c15ef750c33a37c41e1147050438",
               ((0.01, 0.5),)),
    ),
    "drum-hat": (
        # BigSoundBank #2299, #2301 "Hi-hat close #4", "#6"
        Source(_BSB + "2299.ogg",
               "ee571bf9aed41388e80bf9c1045fa491badfee782fe6c6b9a5d1008c451932e3",
               ((0.01, 0.25),)),
        Source(_BSB + "2301.ogg",
               "3e8db91a54bc63486cecc8fb5fd99dc67dd8311ed9dff4ffb809eb64a6110b30",
               ((0.0, 0.22),)),
    ),
    "drum-crash": (
        # BigSoundBank #2311 "Cymbale 16'' #1"
        Source(_BSB + "2311.ogg",
               "962c27f1b121908384cb67fe5792c7f5c98ff2f67c2007113037177ce239ef7d",
               ((0.0, 4.0),)),
    ),
}

_calls: dict[str, tuple[np.ndarray, ...]] = {}
_busy: set[str] = set()
_lock = threading.Lock()


def calls(kind: str) -> tuple[np.ndarray, ...] | None:
    """The calls for one of SOURCES ("cat", "fart", "drum-kick" ...), once
    downloaded and cut; None until then."""
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
