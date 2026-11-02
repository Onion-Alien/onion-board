"""The real calls the animal voices play (voicefx.builtin.animals): the meows,
barks, bleats, quacks, oinks and moos (and the Farm voice's cowbell and donkey), and
the Fart and Drum kit voices' farts and drums (voicefx.builtin.syllables).

They're public-domain (CC0) recordings, downloaded the first time a voice is
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
MAX_BYTES = 2 << 20     # the most one file may be (they're all under 1.5 MB)


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    cuts: tuple[tuple[float, float], ...]   # (start, end) seconds of each call in it


_COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"
_BSB = "https://bigsoundbank.com/UPLOAD/ogg/"
_FREESOUND = "https://cdn.freesound.org/previews/"
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
    "goat": (
        # BigSoundBank #0279 "Bleating goat #1", CC0
        Source(_BSB + "0279.ogg",
               "89a481352ecba48fcfd94e2925758f0a616436f38f83abd3657563067f707c95",
               ((0.24, 0.98),)),
        # BigSoundBank #0280 "Bleating goat #2", CC0
        Source(_BSB + "0280.ogg",
               "bc1f2d566a91c92f0781370b36a8731bca1517d88b5f8e5a29671414e2325ea7",
               ((0.22, 0.86),)),
        # BigSoundBank #0880 "Dwarf goat bleating", CC0
        Source(_BSB + "0880.ogg",
               "c71e6bfe6b2d55879d5b3d0e8ac23ef0cf81370eface6c80b507b023d0362b43",
               ((1.73, 2.32), (3.25, 3.89), (5.03, 5.52), (6.65, 7.26), (8.21, 8.69),
                (10.41, 11.20))),
    ),
    "duck": (
        # BigSoundBank #0276 "Ducks", CC0
        Source(_BSB + "0276.ogg",
               "d0cd046f5b76490884fd17da80c7f12dbf48acf606e712ad754f54d4969b6f42",
               ((0.37, 0.72), (0.78, 1.16), (18.28, 18.46), (18.49, 18.70), (18.73, 18.93),
                (18.96, 19.15), (19.18, 19.37))),
        # Wikimedia Commons, CC0: "Ducks snatching.ogg"
        Source(_COMMONS + "f/f1/Ducks_snatching.ogg",
               "24eefe8a596b6c8a4c99b7942b9a094510df240797278618f9534fca819539ec",
               ((1.43, 1.67), (1.72, 1.95), (1.99, 2.20))),
    ),
    "pig": (
        # Freesound #652361 "Pig grunts.wav" by nomerodin1, CC0 (its preview)
        Source(_FREESOUND + "652/652361_9855978-hq.ogg",
               "8a3347eff6284a7a6560deadd68996a6b217bf11706bd8bb8884abbeaa36c7b5",
               ((2.32, 2.92), (6.95, 7.21), (23.77, 24.23), (27.20, 27.93), (28.13, 28.41))),
        # Freesound #536746 "Pig.ogg" by egomassive, CC0 (its preview)
        Source(_FREESOUND + "536/536746_1415754-hq.ogg",
               "de450f91f1058909c082b36ce7c340151c960a50a3218affb70075b2198493f3",
               ((0.10, 0.32), (0.56, 0.77), (0.94, 1.18))),
        # Freesound #421734 "Pig grunts" by gerainsan, CC0 (its preview)
        Source(_FREESOUND + "421/421734_3577171-hq.ogg",
               "d2b11d833cf19fb1a3712e2d44cee80b65adbad2150299a8c806873ba3eca14e",
               ((8.95, 9.23), (12.08, 12.40))),
    ),
    "sheep": (
        # BigSoundBank #2343, #2344, #2346 to #2349 "Sheep #1" to "#7", CC0: one bleat each
        Source(_BSB + "2343.ogg",
               "88442faf01e307727a6b39ad274fed07be56d1ce52dea299b9d56cf56ec8c405",
               ((0.08, 0.76),)),
        Source(_BSB + "2344.ogg",
               "1ff6674033e9eeba35e67b075c2114459853a8d56f74d17dc69097099fe9d5ce",
               ((0.06, 0.78),)),
        Source(_BSB + "2346.ogg",
               "74515d72d733d6c8f9ab8d087fda80a3a6addf2def9ae3c7684ca5fbb47d17d4",
               ((0.06, 0.76),)),
        Source(_BSB + "2347.ogg",
               "5b22ae7d5be43494794202a95fb8813d376d2336a0a1726615d6effcc0de4772",
               ((0.06, 0.83),)),
        Source(_BSB + "2348.ogg",
               "f43bd3d249687b42d3fd037cb4b17578a12f543f7da8b7733536aca14559bad0",
               ((0.07, 0.81),)),
        Source(_BSB + "2349.ogg",
               "2a6d22b38f24658b0c081b99cf9af3799c4b686c59ff65d8f996b9d5d89eb505",
               ((0.06, 0.84),)),
    ),
    "cow": (
        # BigSoundBank #2382 to #2386 "Cow moos #2" to "#6", CC0: one moo each
        Source(_BSB + "2382.ogg",
               "da8241b7bc3696b808cb352ad2e8d996a4d2c1addbc20865fc3f84bf17e23c1d",
               ((0.80, 2.40),)),
        Source(_BSB + "2383.ogg",
               "31a9633efee6f6ba6c82ea4b847d32a50d168033118bc5db3b4ec4189a65467a",
               ((0.95, 2.66),)),
        Source(_BSB + "2384.ogg",
               "eca42677c4e19c7b5bdbafa0f73826af32bbf04ad309cb3359189a8242e3a91c",
               ((0.81, 2.48),)),
        Source(_BSB + "2385.ogg",
               "b06fb4bbf7076742db6ab8b2d6891a29f0d2b45d8472bec82357f75276103471",
               ((1.48, 3.20),)),
        Source(_BSB + "2386.ogg",
               "e48806d1ddc3858e5856bda3df62dcff9caf1190bb3ad192af3c3ea42ae7c450",
               ((0.44, 2.20),)),
    ),
    # the Farm voice's odd cowbell: Wikimedia Commons, public domain: "Cowbell.ogg"
    "cowbell": (
        Source(_COMMONS + "a/ab/Cowbell.ogg",
               "a888c638bbd2872fb830592faf4e55a834b6d57e1be2b8469546c8f7dadb12a6",
               ((0.00, 0.34), (1.94, 2.32), (2.34, 2.72), (3.98, 4.36), (6.34, 6.72),
                (7.98, 8.40))),
    ),
    # and its odd donkey: BigSoundBank #1549 to #1551 "Donkey, braying #1" to "#3",
    # CC0: a whole hee-haw from each
    "donkey": (
        Source(_BSB + "1549.ogg",
               "749f8b6237d2357ecb9a2e0dea865947fd058ee0062b302df212256c772feb51",
               ((3.46, 7.45),)),
        Source(_BSB + "1550.ogg",
               "e502c4fd73c1bee6e722e362f347a8c3e55034dafccb66908e69b6672b6d0d24",
               ((1.78, 5.60),)),
        Source(_BSB + "1551.ogg",
               "3092e04c514416c0a6d4db8cb698c841b532d3704330c1feca83c63a798fd399",
               ((3.27, 8.30),)),
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
        Source(_FREESOUND + "163/163386_2943714-hq.ogg",
               "8f6edd945d4ce15947a6de1632264ebe36e299f6f4101b871e8643fe1cfc9bd2",
               ((0.02, 0.62),)),
        # Freesound #183551 "Juicy Fart5" (Zott820)
        Source(_FREESOUND + "183/183551_2558531-hq.ogg",
               "259b4d1325f0fbd60389b45b14fff882a876ec119041258e360b835e94d25854",
               ((0.04, 3.1),)),
        # Freesound #202528 "Farts, loud and flabby x7" (peridactyloptrix)
        Source(_FREESOUND + "202/202528_2737063-hq.ogg",
               "deb09ecea30dcf84f2953077b6131501b4fc680c2423d577c998fe54bab9e007",
               ((0.75, 1.17), (3.19, 3.94), (6.35, 8.12), (8.44, 8.64), (9.19, 9.32),
                (10.61, 12.46), (15.37, 15.87), (15.99, 16.14), (18.54, 19.21),
                (20.83, 21.3))),
        # Freesound #266450 "Chair Fart" (Ezcah)
        Source(_FREESOUND + "266/266450_1900515-hq.ogg",
               "0a83ea3571b1f6ca6e0a62803cb9fdbb9cc966df24e165e65eadb65510511a60",
               ((0.05, 2.69),)),
        # Freesound #610067 "Fart.mp3" (TeddyFerguson)
        Source(_FREESOUND + "610/610067_7376654-hq.ogg",
               "89c829b5f84ede285b4c719c7f265292e61c42adcb3316096b4924a81f3904dd",
               ((0.62, 0.92),)),
        # Freesound #640804 "2 part fart" (DSISStudios)
        Source(_FREESOUND + "640/640804_2628301-hq.ogg",
               "f42fb3c74c673d9e70bd3a075a3d5452e535b8e64faa9ab51497f4c4a02e3c67",
               ((0.0, 0.33), (0.41, 0.61))),
        # Freesound #645339 "Nasty fart" (SamsterBirdies)
        Source(_FREESOUND + "645/645339_5487341-hq.ogg",
               "01a61e387286b7c457d7d4ebb42af676cda9b52c6cf073c5cd144923db6de287",
               ((0.0, 0.53),)),
        # Freesound #732936 "Blubberfreak Fart 23" (Blubberfreak)
        Source(_FREESOUND + "732/732936_15881540-hq.ogg",
               "dbed51553ec22d45f642ca586d5b3fea8420799632768be16525662728ca367d",
               ((0.95, 1.69), (1.93, 2.57))),
        # Freesound #874487 "Fart - Close recording" (Sadiquecat)
        Source(_FREESOUND + "874/874487_5287430-hq.ogg",
               "aaa326536e6db2c31cf3ee6ecd2c6fcaf33d13a02958945ee7bcd719433f94f1",
               ((0.0, 0.19),)),
    ),
    # a real drum kit, CC0: BigSoundBank's recorded kit (snares, closed hi-hats, a 16"
    # crash), and two kicks from Freesound
    "drum-kick": (
        # Freesound #581461 "Fractanimal_Acoustic_Drum_Kit_Kick_7.wav" (johnnydekk)
        Source(_FREESOUND + "581/581461_5790048-hq.ogg",
               "b2f304a57383a89aa81b0c2d9294dd0a99abef5b465834294ea54774e6b72d86",
               ((0.0, 0.4),)),
        # Freesound #860524 "Big Rock Bass Drum 24in One Shot" (lennartgreen)
        Source(_FREESOUND + "860/860524_3661618-hq.ogg",
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
    """The calls for one of SOURCES ("cat", "cow", "fart", "drum-kick" ...), once
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
