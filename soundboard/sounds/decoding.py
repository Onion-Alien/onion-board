"""Reading audio files (libsndfile, else ffmpeg; long ones streamed into the cache a
second at a time), loading a library sound as it plays, and writing the library's own
copies (FLAC or MP3)."""
from __future__ import annotations

import contextlib
import itertools
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import numpy as np
import soundfile as sf
import soxr

from soundboard.audio import mapped
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.sounds import cachefiles, paths
from soundboard.sounds.cachefiles import (_NPY_HEAD, _refused, cache_path, load_cached,
                                          store_cached)
from soundboard.sounds.config import SoundMeta
from soundboard.sounds.levels import _block_rms, _gain, _i16, level_gain, peaks, to_int16

log = logging.getLogger("soundboard.sounds.library")


MAX_SECONDS = 120 * 60
FFMPEG_TIMEOUT = 300


def _is_file(p: Path) -> bool:
    """Path.is_file, but False when Windows can't look at it: a WinGet link it can't
    follow raised OSError out of the FFmpeg check (2.2.0)."""
    try:
        return p.is_file()
    except OSError:
        return False


def _ffmpeg() -> str | None:
    """The app's own FFmpeg (ffmpegget downloads it there when winget can't fix one),
    else ffmpeg on PATH, or where winget links it (the installer gets it through
    winget, and a process started before that doesn't see the new PATH yet). Without
    the right to make links (most PCs), winget makes no WinGet\\Links\\ffmpeg.exe: it puts
    the package's bin folder on the user's PATH instead, so that folder is looked in too
    (the app the installer opens would otherwise call a fine FFmpeg broken)."""
    own = paths.APP_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
    if os.name == "nt" and _is_file(own):
        return str(own)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for env, sub in (("LOCALAPPDATA", "Microsoft/WinGet"),   # per-user install
                     ("ProgramFiles", "WinGet")):            # machine-wide install
        base = os.environ.get(env)
        if not base:
            continue
        link = Path(base) / sub / "Links" / "ffmpeg.exe"
        if _is_file(link):
            return str(link)
        try:   # Packages\Gyan.FFmpeg.Essentials_<source>\ffmpeg-<version>-essentials_build\bin
            for exe in (Path(base) / sub / "Packages").glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"):
                if _is_file(exe):
                    return str(exe)
        except OSError:
            pass
    return None


def _ffmpeg_words(stderr: str) -> str:
    """ffmpeg's error as words for people ("[out#0/f32le @ 0000…] Output file does not
    contain any stream" was shown as is); the original goes to the log."""
    s = stderr.lower()
    if (not s or "does not contain any stream" in s or "matches no streams" in s
            or "output file is empty" in s):
        return _("this file has no audio in it")
    if "invalid data found" in s or "could not find codec" in s or "unknown format" in s:
        return _("It isn't a sound file that can be read, or it's damaged.")
    return stderr


# A file is read a second at a time, whatever its length. A sound up to STREAM_S comes
# back whole (float32 in RAM, as it always did); a longer one never is: it's resampled,
# measured and written into its cache (and its converted copy) piece by piece, then
# played from the cache file (mapped). A two-hour import used to hold its float32 audio
# (2.8 GB) and a few copies of it at once; now it holds about a second of it.
STREAM_S = 60


class NeedsFFmpeg(RuntimeError):
    """The file needs FFmpeg to be read and there's none: not a download gone wrong."""
    dl_why = "no-ffmpeg"   # errors.download_reason


class _SourceError(Exception):
    """libsndfile couldn't open or read the file: ffmpeg gets a go (m4a/aac/video etc.)."""


def _stereo(x: np.ndarray) -> np.ndarray:
    if x.shape[1] == 1:
        return np.repeat(x, 2, axis=1)
    return x[:, :2] if x.shape[1] > 2 else x


def _sf_pieces(f, left: int):
    while left > 0:
        try:
            x = f.read(frames=min(f.samplerate, left), dtype="float32", always_2d=True)
        except Exception as e:  # noqa: BLE001 - libsndfile opened it but can't decode it
            raise _SourceError(e) from e
        if not len(x):
            return
        left -= len(x)
        yield x


@contextlib.contextmanager
def _sf_source(path: str):
    """(rate, pieces) of the file's first MAX_SECONDS, by libsndfile."""
    try:
        f = sf.SoundFile(path)
    except Exception as e:  # noqa: BLE001
        raise _SourceError(e) from e
    with f:
        yield f.samplerate, _sf_pieces(f, int(MAX_SECONDS * f.samplerate))


class _Stopwatch:
    """Kills ffmpeg once it has been waited on for FFMPEG_TIMEOUT in all: only the time
    spent waiting for its audio counts, not the import's own work on each piece."""

    def __init__(self, p: subprocess.Popen, out):
        self.p, self.out, self.spent, self.since, self.fired = p, out, 0.0, None, False
        self.done = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="ffmpeg-timeout").start()

    def _run(self):
        while not self.done.wait(0.25):
            since = self.since
            if since is not None and self.spent + time.monotonic() - since > FFMPEG_TIMEOUT:
                self.fired = True
                self.p.kill()
                return

    def read(self, n: int) -> bytes:
        self.since = time.monotonic()
        try:
            return self.out.read(n)
        finally:
            self.spent += time.monotonic() - self.since
            self.since = None


def _ffmpeg_pieces(path: str, p: subprocess.Popen, err, watch: _Stopwatch):
    got = 0
    while True:
        b = watch.read(SR * 8)   # a second of f32le stereo
        if not b:
            break
        n = len(b) // 8 * 8
        got += n
        if n:
            yield np.frombuffer(b, np.float32, count=n // 4).reshape(-1, 2)
    code = p.wait()
    if watch.fired:
        raise RuntimeError(_("ffmpeg took longer than {seconds}s", seconds=FFMPEG_TIMEOUT))
    if code != 0 or not got:
        err.seek(0)
        msg = err.read().decode(errors="ignore").strip()
        log.info("ffmpeg couldn't decode %s: %s", path, msg)
        raise RuntimeError(_ffmpeg_words(msg))


@contextlib.contextmanager
def _ffmpeg_source(path: str, cause: BaseException | None = None):
    """(SR, pieces) of the file's first MAX_SECONDS, by ffmpeg (streamed, never all of
    its output at once). The process is gone when this ends, however it ends."""
    ff = _ffmpeg()
    if not ff:
        from soundboard.core import usage  # the name only, never the file
        usage.used("needs-ffmpeg")
        raise NeedsFFmpeg(_("This file needs FFmpeg to play. Get it in "
                            "Settings > Data & quality.")) from cause
    with tempfile.TemporaryFile() as err:
        try:
            p = subprocess.Popen([ff, "-v", "error", "-i", path, "-vn", "-t", str(MAX_SECONDS),
                                  "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:   # a broken ffmpeg: about the file's format, not the disk
            raise RuntimeError(str(e)) from e
        out = p.stdout
        assert out is not None   # stdout=PIPE
        watch = _Stopwatch(p, out)
        try:
            yield SR, _ffmpeg_pieces(path, p, err, watch)
        finally:
            watch.done.set()
            if p.poll() is None:
                p.kill()
            out.close()
            p.wait()


class _Long(NamedTuple):
    """A sound over STREAM_S, imported straight into its cache (_read)."""
    audio: np.ndarray    # (n, 2) int16, mapped from the cache file
    gain: float          # level_gain() of it
    frames: int
    via_ffmpeg: bool


def _read(path: str, sid: str | None = None,
          store: Callable[[bool], Path | None] | None = None) -> tuple[np.ndarray, bool] | _Long:
    """(audio as (n, 2) float32 at SR, decoded-by-ffmpeg?), or with `sid`, for a sound
    over STREAM_S: a _Long, its audio already in sid's cache and, when store(via_ffmpeg)
    names a file, saved there as it was decoded (write_stored's format).

    Only the first MAX_SECONDS are ever read: libsndfile is asked for that many
    frames and ffmpeg is given -t."""
    if not os.path.exists(path):   # moved or deleted: ffmpeg's own words were shown
        raise RuntimeError(_("its file is gone (it was at {path})", path=path))
    try:
        return _read_from(path, sid, store, None)
    except _SourceError as e:
        log.debug("libsndfile can't read %s (%s); trying ffmpeg", path, e.__cause__)
        return _read_from(path, sid, store, e.__cause__)


def _read_from(path, sid, store, ffmpeg_cause):
    via_ffmpeg = ffmpeg_cause is not None
    src = _ffmpeg_source(path, ffmpeg_cause) if via_ffmpeg else _sf_source(path)
    with src as (rate, pieces):
        head, n = [], 0
        for x in pieces:
            head.append(_stereo(x))
            n += len(x)
            if sid is not None and n > STREAM_S * rate:
                rest = (_stereo(x) for x in pieces)
                return _stream(itertools.chain(head, rest), rate, sid,
                               store(via_ffmpeg) if store else None, via_ffmpeg)
        data = np.concatenate(head) if head else np.zeros((0, 2), np.float32)
    del head
    if rate != SR:
        data = soxr.resample(data, rate, SR, quality="VHQ").astype(np.float32, copy=False)
    return np.ascontiguousarray(data, dtype=np.float32), via_ffmpeg


def _decode(path: str) -> tuple[np.ndarray, bool]:
    """(audio as (n, 2) float32 at SR, decoded-by-ffmpeg?), whole."""
    got = _read(path)
    assert not isinstance(got, _Long)   # only with a sid
    return got


def decode(path: str) -> np.ndarray:
    """Decode any audio file to (n, 2) float32 at SR with high-quality resampling."""
    return _decode(path)[0]


def _stream(pieces, rate: int, sid: str, store: Path | None, via_ffmpeg: bool) -> _Long:
    """The streamed half of _read: resample, then a second at a time measure the level
    and write the stored copy and the int16 cache. Exactly what decode → write_stored →
    level_gain → store_cached make of the whole thing: to_int16 turns a sound that
    goes over full scale down with the limiter (_under_full_scale, run a second at a
    time from the start), else only rounds it. Which one is known only at the end, so
    both are written and the right one kept."""
    from soundboard.audio.sendfx import Limiter
    rs = soxr.ResampleStream(rate, SR, 2, dtype="float32", quality="VHQ") if rate != SR else None
    paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = cache_path(sid)
    tag = uuid.uuid4().hex[:8]   # unique: another thread may be writing this sound's cache
    tmp = {False: dest.with_name(f"{sid}.{tag}.tmp.npy"),
           True: dest.with_name(f"{sid}.{tag}.lim.tmp.npy")}
    lim = Limiter(SR, ceiling_db=-0.05)
    st = {"n": 0, "lim_n": 0, "skip": lim.la, "peak": 0.0}
    rms: list[np.ndarray] = []
    try:
        with contextlib.ExitStack() as stack:
            files = {k: stack.enter_context(open(p, "wb")) for k, p in tmp.items()}
            for f in files.values():
                f.write(bytes(_NPY_HEAD))
            out = stack.enter_context(_stored_writer(store)) if store is not None else None

            def limited(y):
                d = min(st["skip"], len(y))   # the limiter's first `la` frames are its delay
                y, st["skip"] = y[d:], st["skip"] - d
                y = y[:st["n"] - st["lim_n"]]
                if len(y):
                    files[True].write(_i16(y).tobytes())
                    st["lim_n"] += len(y)

            def second(x):
                st["peak"] = max(st["peak"], float(np.max(np.abs(x))))
                rms.append(_block_rms(x))
                if out is not None:
                    out.write(x)
                files[False].write(_i16(x).tobytes())
                st["n"] += len(x)
                limited(lim.process(x))

            buf = np.zeros((0, 2), np.float32)

            def feed(y):
                nonlocal buf
                buf = np.concatenate([buf, y]) if len(buf) else y
                while len(buf) >= SR:
                    second(np.ascontiguousarray(buf[:SR], np.float32))
                    buf = buf[SR:]

            for x in pieces:
                feed(rs.resample_chunk(x) if rs is not None else x)
            if rs is not None:
                feed(rs.resample_chunk(np.zeros((0, 2), np.float32), last=True))
            if len(buf):
                second(np.ascontiguousarray(buf, np.float32))
            limited(lim.process(np.zeros((lim.la, 2), np.float32)))   # push the delay out
            for f in files.values():
                cachefiles._npy_header(f, st["n"])
        keep = tmp[st["peak"] > 1.0]
        try:
            keep.replace(dest)
            _refused.discard(dest)   # a new file there: in use again, not a leftover
        except OSError:   # dest mapped by audio still in use: play the new file where it is
            log.warning("couldn't put the cache of %s in place", sid, exc_info=True)
            dest = keep
        audio = mapped.load(dest)
    finally:
        for p in tmp.values():
            if p != dest:
                p.unlink(missing_ok=True)
    gain = _gain(float(st["peak"]), np.concatenate(rms) if rms else np.zeros(0, np.float32))
    return _Long(audio, gain, st["n"], via_ffmpeg)


def load_original(meta: SoundMeta) -> np.ndarray:
    """int16 audio of the sound as imported (no effects): cache, else decode."""
    data = load_cached(meta.id)
    if data is None:
        got = _read(meta.file, meta.id)   # a long one goes straight into the cache
        data = got.audio if isinstance(got, _Long) else store_cached(meta.id, got[0])
    return data


def decode_int16(path: str) -> tuple[np.ndarray, float]:
    """(int16 audio, level_gain) of a file that isn't a sound of the library (a link
    played before it's added). A long one is streamed into a cache file of its own
    (mapped; prune_cache takes it once nothing plays it), like an import."""
    got = _read(path, f"play-{uuid.uuid4().hex[:10]}")
    if isinstance(got, _Long):
        return got.audio, got.gain
    return to_int16(got[0]), level_gain(got[0])


def load_sound(meta: SoundMeta, cancel: Callable[[], bool] | None = None,
               progress: Callable[[float], None] | None = None) -> np.ndarray:
    """int16 audio for a library sound as it plays, effects included. The first
    load after its effects change renders them (slow for long sounds); after that
    it is one file read. cancel, progress: see render_cached."""
    from soundboard.audio import soundfx
    key = soundfx.key(meta.fx)
    if not key:
        return load_original(meta)
    data = load_cached(meta.id, key)
    if data is None:
        data = cachefiles.render_cached(meta.id, load_original(meta), meta.fx, cancel, progress)
    return data


def original_frames(meta: SoundMeta) -> int:
    """Length of a sound as imported (before effects or trim), in frames at SR:
    from the cache's header when it's there (no audio is read), else the file's."""
    p = cache_path(meta.id)
    try:
        if p.exists():
            return int(np.load(p, mmap_mode="r").shape[0])
    except Exception:  # noqa: BLE001
        log.debug("couldn't read the cache header of %s", meta.id, exc_info=True)
    try:
        info = sf.info(meta.file)
        return int(min(info.frames / info.samplerate, MAX_SECONDS) * SR)
    except Exception:  # noqa: BLE001 - m4a/video etc.: decode it
        return len(load_original(meta))


PEAK_READS = 4      # original_peaks: short reads per waveform column of a long sound...
PEAK_CHUNK = 1024   # ...of this many frames (4 KB of int16 stereo: one page each)


def original_peaks(meta: SoundMeta, n: int = 400) -> tuple[np.ndarray, float]:
    """(waveform peaks, length in seconds) of a sound as imported, for the trim
    control. Read from the cache without loading it: a long one gives a few short
    reads spread over each column, plenty to draw it. No cache yet: no peaks, the
    length from the file."""
    p = cache_path(meta.id)
    try:
        if p.exists():
            data = np.load(p, mmap_mode="r")
            return _sampled_peaks(data, n), len(data) / SR
    except Exception:  # noqa: BLE001
        log.debug("couldn't read the cache of %s for its waveform", meta.id, exc_info=True)
    return np.zeros(0, np.float32), original_length(meta)


def original_length(meta: SoundMeta) -> float:
    """original_peaks()'s length without its peaks: the cache's header, no audio read
    (the Edit dialog opens with this and gets the peaks from a worker)."""
    try:
        return original_frames(meta) / SR
    except Exception:  # noqa: BLE001 - the file is gone: nothing to trim
        return 0.0


def _sampled_peaks(data: np.ndarray, n: int) -> np.ndarray:
    """peaks() of a memory-mapped (m, 2) array, touching only PEAK_READS chunks of
    PEAK_CHUNK frames per column (every frame of a short one). A plain stride over
    the whole file would still read every page of it."""
    if n <= 0 or len(data) <= n * PEAK_READS * PEAK_CHUNK:
        return peaks(np.asarray(data), n)
    edges = np.linspace(0, len(data), n + 1)
    width = edges[1] - edges[0]
    offsets = (np.arange(PEAK_READS) + 0.5) * (width / PEAK_READS) - PEAK_CHUNK / 2
    starts = np.clip((edges[:-1, None] + offsets).astype(np.int64), 0, len(data) - PEAK_CHUNK)
    picked = np.asarray(data[(starts[..., None] + np.arange(PEAK_CHUNK)).ravel()])
    return peaks(picked, n)   # n equal slices of it = each column's own chunks


# Audio the library makes itself (a download, a recording) is kept as Settings > Data
# & quality says (quality.SAVE_FORMATS). MP3 by default: it plays in anything, and is
# ~a quarter of a FLAC that holds no more than the compressed download did. ~V2 VBR
# (~190 kbps on music). libsndfile's MP3 starts on time and keeps the length (no
# encoder gap before a pad's hit). FLAC where it can't write MP3 (an old system
# libsndfile). Only the saved file: a sound plays from its cache, made at import from
# the audio as it came.
_CAN_MP3 = "MP3" in sf.available_formats()
MP3_QUALITY = 0.2   # libsndfile's compression_level: 0 best .. 1 smallest


def stored_ext() -> str:
    from soundboard.online import quality
    return ".mp3" if quality.current.save_format == "mp3" and _CAN_MP3 else ".flac"


def _stored_writer(dest: Path) -> sf.SoundFile:
    """An open writer for library audio ((n, 2) at SR), in the format `dest`'s extension says."""
    if dest.suffix.lower() == ".mp3":
        return sf.SoundFile(dest, "w", SR, 2, format="MP3", compression_level=MP3_QUALITY)
    return sf.SoundFile(dest, "w", SR, 2, subtype="PCM_16")


def write_stored(dest: Path, data: np.ndarray) -> None:
    """Write library audio ((n, 2) at SR) to `dest`, as its extension says."""
    with _stored_writer(dest) as f:
        f.write(data)
