"""Voice-chat mic processing, the real code: what a game's voice stack does to our
sounds before its codec, using the actual libraries instead of chatsim's models.

Development tool, like soundboard.codecsim and soundboard.chatsim; nothing here runs
in the app, and neither library ships with it. Install them into a separate bench
environment (requirements-bench.txt):

  webrtc   Google's WebRTC audio processing module (LiveKit's Python package ships
           a build of it): high-pass, noise suppression, automatic gain control.
           Vivox, EOS, Photon, Steam voice and Discord all build on this code.
  rnnoise  Xiph's RNNoise denoiser (the pyrnnoise package ships the library): the
           optional denoiser in Mumble, Simple Voice Chat and many proximity mods.

Both run on 10 ms mono frames at 48 kHz, the way a voice chat feeds them.

    y = process(x, ("webrtc_ns", "webrtc_agc"))     # (n, 2) float32 at 48 kHz
    if not available(): ...                         # libraries not installed

Stage names, in the order they run: webrtc_hpf, rnnoise, webrtc_ns, webrtc_agc.
The WebRTC stages share one processor, as they do in a real client.
"""
from __future__ import annotations

import ctypes
import importlib.util
from pathlib import Path

import numpy as np

SR = 48000
FRAME = SR // 100          # 10 ms
F32 = np.float32
WEBRTC = ("webrtc_hpf", "webrtc_ns", "webrtc_agc")
STAGES = ("webrtc_hpf", "rnnoise", "webrtc_ns", "webrtc_agc")

_rnnoise_lib = None


def _mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def missing() -> list[str]:
    """Package names of the libraries that aren't installed (empty = all there)."""
    out = []
    if importlib.util.find_spec("livekit") is None:
        out.append("livekit")
    if importlib.util.find_spec("pyrnnoise") is None:
        out.append("pyrnnoise")
    return out


def available(stages=STAGES) -> bool:
    need = set()
    if any(s in WEBRTC for s in stages):
        need.add("livekit")
    if "rnnoise" in stages:
        need.add("pyrnnoise")
    return not need & set(missing())


def _to_i16(y: np.ndarray) -> np.ndarray:
    return (np.clip(y, -1.0, 1.0) * 32767.0).round().astype(np.int16)


def webrtc(y: np.ndarray, hpf: bool = False, ns: bool = False, agc: bool = False) -> np.ndarray:
    """Run mono float y at 48 kHz through one WebRTC audio processor, 10 ms at a time."""
    from livekit import rtc
    apm = rtc.AudioProcessingModule(high_pass_filter=hpf, noise_suppression=ns,
                                    auto_gain_control=agc)
    pcm = _to_i16(np.concatenate([y, np.zeros((-len(y)) % FRAME)]))
    out = np.empty_like(pcm)
    try:
        for i in range(0, len(pcm), FRAME):
            f = rtc.AudioFrame(pcm[i:i + FRAME].tobytes(), SR, 1, FRAME)
            apm.process_stream(f)
            out[i:i + FRAME] = np.frombuffer(f.data, np.int16)
    finally:
        # release it now: left to the garbage collector at interpreter exit, the
        # handle's finaliser can run after LiveKit's FFI is gone and raise
        apm._ffi_handle.dispose()
    return out[:len(y)].astype(np.float64) / 32767.0


def _rnnoise():
    global _rnnoise_lib
    if _rnnoise_lib is None:
        # load the DLL straight from the package: importing pyrnnoise itself pulls in
        # its file-conversion helpers (and their ffmpeg bindings), none of which we use
        spec = importlib.util.find_spec("pyrnnoise")
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError("pyrnnoise is not installed (pip install -r requirements-bench.txt)")
        pkg = Path(next(iter(spec.submodule_search_locations)))
        dll = next((p for p in pkg.iterdir()
                    if p.name in ("rnnoise.dll", "librnnoise.so", "librnnoise.dylib")), None)
        if dll is None:
            raise RuntimeError(f"no RNNoise library in {pkg}")
        lib = ctypes.CDLL(str(dll))
        lib.rnnoise_create.argtypes = [ctypes.c_void_p]
        lib.rnnoise_create.restype = ctypes.c_void_p
        lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float),
                                              ctypes.POINTER(ctypes.c_float)]
        lib.rnnoise_process_frame.restype = ctypes.c_float
        lib.rnnoise_get_frame_size.restype = ctypes.c_int
        if lib.rnnoise_get_frame_size() != FRAME:
            raise RuntimeError("unexpected RNNoise frame size")
        _rnnoise_lib = lib
    return _rnnoise_lib


def rnnoise(y: np.ndarray, with_prob: bool = False):
    """RNNoise over mono float y at 48 kHz. It works on 16-bit-scaled floats, so the
    input is scaled up and back. With with_prob, also returns its per-10 ms voice
    probability (what a mod using it as a voice gate keys on)."""
    lib = _rnnoise()
    st = lib.rnnoise_create(None)
    buf = np.concatenate([y, np.zeros((-len(y)) % FRAME)]).astype(F32) * 32768.0
    out = np.empty_like(buf)
    probs = np.empty(len(buf) // FRAME, F32)
    try:
        for k, i in enumerate(range(0, len(buf), FRAME)):
            fin = np.ascontiguousarray(buf[i:i + FRAME])
            fout = np.empty(FRAME, F32)
            probs[k] = lib.rnnoise_process_frame(
                st, fout.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                fin.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
            out[i:i + FRAME] = fout
    finally:
        lib.rnnoise_destroy(st)
    y2 = out[:len(y)].astype(np.float64) / 32768.0
    return (y2, probs) if with_prob else y2


def process(x: np.ndarray, stages=STAGES) -> np.ndarray:
    """Run x ((n, 2) or (n,) float at 48 kHz) through the chosen stages. Returns
    (n, 2) float32; the mic capture is mono, so both channels are the same."""
    unknown = set(stages) - set(STAGES)
    if unknown:
        raise ValueError(f"unknown stage(s): {', '.join(sorted(unknown))}")
    y = _mono(x)
    rest = {s for s in stages if s in WEBRTC}
    if "rnnoise" in stages:
        if "webrtc_hpf" in rest:            # the high-pass comes before the denoiser
            y = webrtc(y, hpf=True)
            rest.discard("webrtc_hpf")
        y = rnnoise(y)
    if rest:
        y = webrtc(y, hpf="webrtc_hpf" in rest, ns="webrtc_ns" in rest,
                   agc="webrtc_agc" in rest)
    return np.repeat(y[:, None], 2, axis=1).astype(F32)


__all__ = ["STAGES", "available", "missing", "process", "rnnoise", "webrtc"]
