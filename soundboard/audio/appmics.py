"""Windows' recording and playback endpoints asked now (not PortAudio's list from
start-up): whether a mic opens and is silent, a short recording of one, the
active devices' names. The mic helper runs mic_is_silent (without numpy).
Part of soundboard.audio.appaudio, which re-exports all of it.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
import typing
from ctypes import (POINTER, byref, c_float, c_int, c_int64, c_uint, c_ulong, c_void_p,
                    c_wchar_p, cast)

if typing.TYPE_CHECKING:
    import numpy as np
else:
    try:
        import numpy as np
    except ImportError:   # the mic helper (soundboard/mic/michelper.py) ships without numpy:
        np = None         # it only uses mic_is_silent(), which never needs it

from soundboard.audio.appcom import (
    AUDCLNT_BUFFERFLAGS_SILENT,
    AUDCLNT_SHAREMODE_SHARED,
    CLSCTX_ALL,
    Com,
    ComError,
    DEVICE_STATE_ACTIVE,
    E_CAPTURE,
    E_RENDER,
    GUID,
    IID_IAudioCaptureClient,
    IID_IAudioClient,
    KSDATAFORMAT_SUBTYPE_IEEE_FLOAT,
    WAVEFORMATEX,
    WAVEFORMATEXTENSIBLE,
    WAVE_FORMAT_EXTENSIBLE,
    WAVE_FORMAT_IEEE_FLOAT,
    _co_init,
    _cotaskmem_str,
    _device_name,
    _enumerator,
    _render_devices,
    _win,
    to_stereo_f32,
)
if _win:
    from soundboard.audio.appcom import _ole32

log = logging.getLogger("soundboard.audio.appaudio")


IID_IAudioEndpointVolume = GUID.of("5CDF2C82-841E-4546-9722-0CF74078229A")
CAPTURE_ID = "{0.0.1.00000000}."   # a recording endpoint's id: this + its GUID


def mic_is_silent(guid: str, seconds: float = 1.0, wait: float = 8.0) -> bool | None:
    """Open the recording endpoint `guid` (as in MMDevices\\Audio\\Capture) for up to
    `seconds` and say whether it delivers nothing but exact zeros: True for digital
    silence (a quiet room still has noise, so a working mic never does), False at the
    first real sample. None when it can't tell: the mic isn't back within `wait`
    seconds, it's muted or at 0%, Windows refused, or too little audio came."""
    if not _win:
        return None
    own = _co_init()
    try:
        return _mic_is_silent(guid if guid.startswith("{") else "{" + guid + "}",
                              seconds, wait)
    except ComError:
        log.info("couldn't listen to mic %s", guid, exc_info=True)
        return None
    finally:
        if own:
            _ole32.CoUninitialize()


def mic_opens(guid: str, wait: float = 8.0) -> bool | None:
    """Whether an app can record the recording endpoint `guid` now: opened in shared mode
    and started for a moment, as a voice chat opens it (muted or not). False when Windows
    refuses (a mic left broken refuses every app the same way); None when it can't tell
    (not Windows, or the mic not active within `wait` seconds: unplugged, switched off)."""
    if not _win:
        return None
    own = _co_init()
    try:
        dev = _active_capture(guid if guid.startswith("{") else "{" + guid + "}", wait,
                              muted_too=True)
        if dev is None:
            return None
        with dev:
            _open_briefly(dev)
        return True
    except ComError:
        log.info("mic %s doesn't open", guid, exc_info=True)
        return False
    finally:
        if own:
            _ole32.CoUninitialize()


def _open_briefly(dev: Com) -> None:
    """Open `dev` in shared mode in its own format, start it for 0.1 s, stop it."""
    out = c_void_p()
    dev.call(3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
             byref(IID_IAudioClient), CLSCTX_ALL, None, byref(out),
             what="Activate(IAudioClient)")
    with Com(out.value) as client:
        pfmt = c_void_p()
        client.call(8, (POINTER(c_void_p),), byref(pfmt), what="GetMixFormat")
        try:
            client.call(3, (c_ulong, c_ulong, c_int64, c_int64, c_void_p, c_void_p),
                        AUDCLNT_SHAREMODE_SHARED, 0, 2_000_000, 0, pfmt, None,
                        what="Initialize")
        finally:
            _ole32.CoTaskMemFree(pfmt)
        client.call(10, (), what="Start")
        try:
            time.sleep(0.1)
        finally:
            client.call(11, (), what="Stop")


def _active_capture(guid: str, wait: float, muted_too: bool = False) -> Com | None:
    """The recording endpoint `guid` once it's active (right after an audio restart it
    takes a moment to be back), or None after `wait` seconds or when it's muted or at
    0% (silent on purpose; `muted_too`: then too)."""
    dev = None
    give_up = time.monotonic() + wait
    with _enumerator() as en:
        while dev is None:
            d, state, got = c_void_p(), c_ulong(), None
            try:
                en.call(5, (c_wchar_p, POINTER(c_void_p)), CAPTURE_ID + guid.lower(),
                        byref(d), what="GetDevice")
                got = Com(d.value)
                got.call(6, (POINTER(c_ulong),), byref(state), what="GetState")
                if state.value == DEVICE_STATE_ACTIVE:
                    dev, got = got, None
                    break
            except ComError:
                pass
            finally:
                if got is not None:
                    got.release()
            if time.monotonic() > give_up:
                return None
            time.sleep(0.25)
    if muted_too:
        return dev
    try:
        out = c_void_p()
        dev.call(3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
                 byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None, byref(out),
                 what="Activate(IAudioEndpointVolume)")
        with Com(out.value) as vol:
            muted, level = c_int(), c_float()
            vol.call(15, (POINTER(c_int),), byref(muted), what="GetMute")
            vol.call(9, (POINTER(c_float),), byref(level), what="GetMasterVolumeLevelScalar")
            if muted.value or level.value <= 0:
                dev.release()
                return None   # silent on purpose
    except BaseException:
        dev.release()
        raise
    return dev


def _mic_is_silent(guid: str, seconds: float, wait: float) -> bool | None:
    dev = _active_capture(guid, wait)
    if dev is None:
        return None
    with dev:
        out = c_void_p()
        dev.call(3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
                 byref(IID_IAudioClient), CLSCTX_ALL, None, byref(out),
                 what="Activate(IAudioClient)")
        with Com(out.value) as client:
            pfmt = c_void_p()
            client.call(8, (POINTER(c_void_p),), byref(pfmt), what="GetMixFormat")
            try:
                # its own format: exact zeros are zero bytes in every sample format
                align = cast(pfmt, POINTER(WAVEFORMATEX))[0].nBlockAlign
                rate = cast(pfmt, POINTER(WAVEFORMATEX))[0].nSamplesPerSec
                client.call(3, (c_ulong, c_ulong, c_int64, c_int64, c_void_p, c_void_p),
                            AUDCLNT_SHAREMODE_SHARED, 0, 2_000_000, 0, pfmt, None,
                            what="Initialize")
            finally:
                _ole32.CoTaskMemFree(pfmt)
            out = c_void_p()
            client.call(14, (POINTER(GUID), POINTER(c_void_p)), byref(IID_IAudioCaptureClient),
                        byref(out), what="GetService(IAudioCaptureClient)")
            with Com(out.value) as cap:
                client.call(10, (), what="Start")
                try:
                    zeros = _all_zero(cap, align, seconds)
                finally:
                    client.call(11, (), what="Stop")
    if zeros is None:
        return False
    return True if zeros >= rate * seconds / 2 else None


def _all_zero(cap: Com, align: int, seconds: float) -> int | None:
    """How many frames came, all exact zeros; None at the first one that isn't."""
    n, frames, flags, data = c_uint(), c_uint(), c_ulong(), c_void_p()
    count = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.01)
        while True:
            cap.call(5, (POINTER(c_uint),), byref(n), what="GetNextPacketSize")
            if not n.value:
                break
            cap.call(3, (POINTER(c_void_p), POINTER(c_uint), POINTER(c_ulong), c_void_p,
                         c_void_p), byref(data), byref(frames), byref(flags), None, None,
                     what="GetBuffer")
            try:
                if not flags.value & AUDCLNT_BUFFERFLAGS_SILENT and data.value \
                        and any(ctypes.string_at(data.value, frames.value * align)):
                    return None
                count += frames.value
            finally:
                cap.call(4, (c_uint,), frames.value, what="ReleaseBuffer")
    return count


def record_mic(guid: str, seconds: float, wait: float = 8.0,
               started: threading.Event | None = None) -> tuple[np.ndarray, int] | None:
    """Record the recording endpoint `guid` for `seconds`: (mono float32, its rate), or
    None when it can't (not back within `wait`, muted or at 0%, Windows refused).
    `started` is set once it's recording. Its own shared-mode format, so nothing is
    converted on the way but the samples to float."""
    if not _win or np is None:
        return None
    own = _co_init()
    try:
        dev = _active_capture(guid if guid.startswith("{") else "{" + guid + "}", wait)
        if dev is None:
            return None
        with dev:
            return _record(dev, seconds, started)
    except ComError:
        log.info("couldn't record mic %s", guid, exc_info=True)
        return None
    finally:
        if own:
            _ole32.CoUninitialize()


def _record(dev: Com, seconds: float, started) -> tuple[np.ndarray, int]:
    out = c_void_p()
    dev.call(3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
             byref(IID_IAudioClient), CLSCTX_ALL, None, byref(out),
             what="Activate(IAudioClient)")
    with Com(out.value) as client:
        pfmt = c_void_p()
        client.call(8, (POINTER(c_void_p),), byref(pfmt), what="GetMixFormat")
        try:
            fmt = WAVEFORMATEX.from_buffer_copy(cast(pfmt, POINTER(WAVEFORMATEX))[0])
            is_float = fmt.wFormatTag == WAVE_FORMAT_IEEE_FLOAT or (
                fmt.wFormatTag == WAVE_FORMAT_EXTENSIBLE
                and cast(pfmt, POINTER(WAVEFORMATEXTENSIBLE))[0].SubFormat
                == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)
            client.call(3, (c_ulong, c_ulong, c_int64, c_int64, c_void_p, c_void_p),
                        AUDCLNT_SHAREMODE_SHARED, 0, 2_000_000, 0, pfmt, None,
                        what="Initialize")
        finally:
            _ole32.CoTaskMemFree(pfmt)
        out = c_void_p()
        client.call(14, (POINTER(GUID), POINTER(c_void_p)), byref(IID_IAudioCaptureClient),
                    byref(out), what="GetService(IAudioCaptureClient)")
        chunks: list[bytes] = []
        n, frames, flags, data = c_uint(), c_uint(), c_ulong(), c_void_p()
        with Com(out.value) as cap:
            client.call(10, (), what="Start")
            if started is not None:
                started.set()
            try:
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    time.sleep(0.01)
                    while True:
                        cap.call(5, (POINTER(c_uint),), byref(n), what="GetNextPacketSize")
                        if not n.value:
                            break
                        cap.call(3, (POINTER(c_void_p), POINTER(c_uint), POINTER(c_ulong),
                                     c_void_p, c_void_p), byref(data), byref(frames),
                                 byref(flags), None, None, what="GetBuffer")
                        try:
                            size = frames.value * fmt.nBlockAlign
                            chunks.append(bytes(size) if flags.value & AUDCLNT_BUFFERFLAGS_SILENT
                                          or not data.value else ctypes.string_at(data.value, size))
                        finally:
                            cap.call(4, (c_uint,), frames.value, what="ReleaseBuffer")
            finally:
                client.call(11, (), what="Stop")
    x = to_stereo_f32(b"".join(chunks), fmt, is_float)
    return x.mean(axis=1).astype(np.float32), int(fmt.nSamplesPerSec)


def endpoint_names(kind: str) -> set[str] | None:
    """Names of Windows' active playback ('output') or recording ('input') devices,
    asked now (PortAudio's list is from when it started or was last re-scanned).
    None if Windows can't be asked."""
    if not _win:
        return None
    own = _co_init()
    try:
        with _enumerator() as en:
            devs = _render_devices(en, E_CAPTURE if kind == "input" else E_RENDER)
        try:
            return {n for n in map(_device_name, devs) if n}
        finally:
            for d in devs:
                d.release()
    except ComError:
        log.debug("listing %s devices failed", kind, exc_info=True)
        return None
    finally:
        if own:
            _ole32.CoUninitialize()


def capture_mics() -> list[tuple[str, str]] | None:
    """Windows' active recording devices as [(endpoint GUID, name)], asked now: the
    names PortAudio's list shows, straight from Windows rather than from the registry
    (directmic.mic_lookup's last try). None if Windows can't be asked."""
    if not _win:
        return None
    own = _co_init()
    try:
        with _enumerator() as en:
            devs = _render_devices(en, E_CAPTURE)
        out = []
        try:
            for d in devs:
                p = c_void_p()
                d.call(5, (POINTER(c_void_p),), byref(p), what="GetId")
                guid = _cotaskmem_str(p).rpartition(".")[2].lower()
                name = _device_name(d)
                if guid.startswith("{") and name:
                    out.append((guid, name))
        finally:
            for d in devs:
                d.release()
        return out
    except ComError:
        log.debug("listing recording devices failed", exc_info=True)
        return None
    finally:
        if own:
            _ole32.CoUninitialize()

