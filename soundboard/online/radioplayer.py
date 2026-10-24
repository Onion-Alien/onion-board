"""The radio stream player for soundboard.online.radio (`RadioPlayer`): Qt Multimedia
decodes, a `QAudioBufferOutput` hands 48 kHz PCM to the engine; dropped streams are
reopened, and the decoder's DLLs preload on a thread when the tab first opens."""
from __future__ import annotations

import ipaddress
import logging
import random
import threading
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QMediaMetaData, QMediaPlayer

from soundboard.online import quality
from soundboard.online import net, netlog
from soundboard.i18n import _
from soundboard.audio.engine import SR
from soundboard.online.radiostation import (CONNECT_S, FEATURE, RETRIES, STALL_S, STEADY_S,
    Station, TOR_CONNECT_S, TOR_RETRIES, _name_is_local, _refused, station_off_air)
from soundboard.online.radiodir import _patience, _start_for

log = logging.getLogger("soundboard.online.radio")


# --------------------------------------------------------------------------- player

def buffer_to_array(buf) -> np.ndarray:
    """A QAudioBuffer as (n, 2) float32 at whatever rate it has. Always a copy: the
    buffer's memory is reused once the slot returns."""
    fmt = buf.format()
    ch = max(1, fmt.channelCount())
    raw = buf.constData()
    if raw is None:
        return np.zeros((0, 2), np.float32)
    kind = fmt.sampleFormat()
    if kind == QAudioFormat.SampleFormat.Float:
        x = np.frombuffer(raw, np.float32).copy()
    elif kind == QAudioFormat.SampleFormat.Int16:
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif kind == QAudioFormat.SampleFormat.Int32:
        x = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    elif kind == QAudioFormat.SampleFormat.UInt8:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        return np.zeros((0, 2), np.float32)
    x = x[: len(x) // ch * ch].reshape(-1, ch)
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    elif ch > 2:
        x = x[:, :2]
    return np.ascontiguousarray(x, np.float32)


_preloaded = False


def _decoder_files() -> list[Path]:
    """Qt's FFmpeg libraries and its media plugin, in the order they need each other."""
    import PySide6
    base = Path(PySide6.__file__).parent
    found = [f for pat in ("avutil-*.dll", "swresample-*.dll", "avcodec-*.dll",
                           "avformat-*.dll", "swscale-*.dll") for f in sorted(base.glob(pat))]
    return found + sorted((base / "plugins" / "multimedia").glob("ffmpeg*.dll"))


def preload_decoder():
    """Load Qt's FFmpeg libraries on a thread, once. Qt loads them when the first
    player is made, on the UI thread and holding Python's lock: 10-60 ms (the files
    are big), long enough to hold up the audio threads, so a sound playing skipped as
    the first station started. Loaded here, that player is made in ~4 ms."""
    global _preloaded
    if _preloaded or sys.platform != "win32":
        return
    _preloaded = True

    def load():
        import ctypes
        try:
            files = _decoder_files()
            # read through first: Windows holds its loader lock for the whole of a DLL
            # load, so a cold disk (and the virus scan) under it held up every thread
            # that loaded a DLL or started a thread meanwhile, the window included: a
            # 14 s freeze as the Radio tab first opened. Read beforehand, they're in
            # memory and already scanned, and each load takes milliseconds.
            for f in files:
                with open(f, "rb") as fh:
                    while fh.read(1 << 20):
                        pass
            # and each one's image made first, outside the loader: a file Windows hasn't
            # seen yet (just installed) is checked as its image is made, which in
            # LoadLibrary is under that lock, and the window froze 6 s opening the Apps
            # tab (starting a thread waits for it). Made here, the load reuses it:
            # ~50 ms under the lock became ~4 ms.
            images = [_image_section(f) for f in files]
            try:
                for f in files:
                    ctypes.WinDLL(str(f))   # (ctypes lets go of the lock while it loads)
            finally:
                for handles in images:
                    _close(handles)
        except OSError as e:   # Qt finds them itself later, as before
            log.debug("radio: preloading the decoder failed: %s", e)
    threading.Thread(target=load, daemon=True, name="radio-preload").start()


def _kernel32(name: str, restype, *argtypes):
    """A kernel32 function with its own prototype (the shared ctypes.windll one is left
    as it is)."""
    import ctypes
    return ctypes.WINFUNCTYPE(restype, *argtypes, use_last_error=True)(
        (name, ctypes.windll.kernel32))


def _image_section(path: Path) -> tuple[int, int]:
    """Make `path`'s executable image (what LoadLibrary maps) without loading it:
    (file, section) handles, kept until the load has used it. (0, 0) if it can't."""
    import ctypes
    from ctypes import wintypes
    open_file = _kernel32("CreateFileW", wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
                          wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                          wintypes.HANDLE)
    make_section = _kernel32("CreateFileMappingW", wintypes.HANDLE, wintypes.HANDLE,
                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, wintypes.LPCWSTR)
    GENERIC_READ, GENERIC_EXECUTE = 0x80000000, 0x20000000
    SHARE_READ, SHARE_DELETE, OPEN_EXISTING = 0x1, 0x4, 3
    PAGE_READONLY, SEC_IMAGE = 0x02, 0x1000000
    invalid = ctypes.c_void_p(-1).value
    fh = open_file(str(path), GENERIC_READ | GENERIC_EXECUTE, SHARE_READ | SHARE_DELETE,
                   None, OPEN_EXISTING, 0, None)
    if not fh or fh == invalid:
        log.debug("radio: couldn't open %s (%d)", path.name, ctypes.get_last_error())
        return 0, 0
    section = make_section(fh, None, PAGE_READONLY | SEC_IMAGE, 0, 0, None)
    if not section:
        log.debug("radio: no image for %s (%d)", path.name, ctypes.get_last_error())
    return fh, section or 0


def _close(handles: tuple[int, int]):
    from ctypes import wintypes
    close = _kernel32("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    for h in reversed(handles):
        if h:
            close(h)


class RadioPlayer(QObject):
    """Plays one stream at a time into `audio` (48 kHz stereo float32 chunks).
    `audio` is emitted on Qt's decoding thread, so a busy window can't hold the sound
    up: connect it with Qt.DirectConnection to something thread-safe (the engine's
    feed, the recorder), or Qt queues it to the window like any other signal."""
    audio = Signal(object)
    state = Signal(str)          # connecting | playing | stopped | error
    error = Signal(str)
    now_playing = Signal(str)    # the stream's own title (song / show), when it sends one
    _looked_up = Signal(int, bool)   # (play generation, the host is local): lookup thread
    _first_audio = Signal(int)       # play generation: decoding thread -> UI thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.station: Station | None = None
        self._player: QMediaPlayer | None = None
        self._out: QAudioBufferOutput | None = None
        self._halting = False
        self._retries = 0
        self._got_audio = False
        self._reconnecting = False   # a stream that played dropped: reopen until it's back
        self._reopen_pending = False  # a reopen is scheduled: ignore further trouble till then
        self._gen = 0                # bumped by play/stop so a stale reopen does nothing
        self._first_sent = -1        # the generation _first_audio was last sent for
        self._state = "stopped"
        self._opened = self._last_audio = self._steady_from = 0.0
        # FFmpeg can sit on a station that never answers (or stops sending) for
        # minutes, so the player keeps its own watch
        self._watch = QTimer(self)
        self._watch.setInterval(1000)
        self._watch.timeout.connect(self._check)
        self._looked_up.connect(self._on_looked_up)
        self._first_audio.connect(self._on_first_audio)
        self._conn = 0               # net.generation() when the stream was opened
        # held by _on_buffer (decoding thread) while it runs; shutdown() takes it to know
        # none is running before the player can be freed
        self._buffer_lock = threading.Lock()
        self._closed = False
        net.on_change(self._on_connection)

    def _make(self):
        fmt = QAudioFormat()
        fmt.setSampleRate(SR)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self._player = QMediaPlayer(self)
        self._out = QAudioBufferOutput(fmt, self)
        # no QAudioOutput: Qt decodes (at real-time pace) but never plays it itself
        self._player.setAudioBufferOutput(self._out)
        # straight on the decoding thread: queued to the window, the chunks waited out
        # every busy moment there and the radio ran dry (it skipped)
        self._out.audioBufferReceived.connect(self._on_buffer, Qt.ConnectionType.DirectConnection)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.metaDataChanged.connect(self._on_meta)

    @property
    def playing(self) -> bool:
        return self.station is not None

    @property
    def status(self) -> str:
        return self._state

    def play(self, station: Station):
        netlog.cause(FEATURE, f"Playing the radio station {netlog.quoted(station.name)}")
        if not net.allowed(FEATURE):   # switched off: no lookup, no stream
            why = _refused(station.url)
            self.stop()
            self._set_state("error")
            self.error.emit(why)
            return
        if self._player is None:
            self._make()
        self.station = station
        self._retries = 0
        self._reconnecting = self._reopen_pending = False
        self._gen += 1
        self._conn = net.generation()
        host = QUrl(station.url).host()
        if net.active():
            # a lookup here would tell this PC's DNS server which station it is; the
            # proxy resolves the name, and the relay refuses local addresses itself
            self._open()
            return
        try:
            ipaddress.ip_address(host)   # an address was already checked (_http)
        except ValueError:   # a name: where it leads is looked up first, off the UI thread
            self._set_state("connecting")
            gen = self._gen
            from soundboard.ui.kit import busy  # (emitted on the UI thread, as above)
            _start_for(self, lambda: busy.emit(self._looked_up, gen, _name_is_local(host)),
                       "radio-lookup")
            return
        self._open()

    def _on_looked_up(self, gen: int, local: bool):
        if gen != self._gen or self.station is None:
            return
        if not local:
            self._open()
            return
        log.warning("radio: refused %s, its address is on this PC / home network",
                    self.station.url)
        self.station = None
        self._set_state("error")
        self.error.emit(_("This station points into your home network, so it isn't played."))

    def _open(self):
        self._got_audio = False
        self._first_sent = -1   # a reopen keeps the generation: say so again
        self._opened = time.monotonic()
        self._watch.start()
        self._set_state("connecting")
        player, station = self._player, self.station
        assert player is not None and station is not None   # play() made and set them
        self._halt_player()   # also empties the source: the same URL again would be ignored
        player.setSource(QUrl(station.url))
        player.play()

    def _on_connection(self):
        """The Connection setting changed: a playing station reconnects the new way at
        once (FFmpeg reads the relay's address each time it opens a stream). Radio
        switched off stops it."""
        if self.station is None or self._player is None:
            return
        if not net.allowed(FEATURE):
            log.info("radio: stopped, it was switched off")
            self.stop()
            self._set_state("error")
            self.error.emit(net.off_message(FEATURE))
            return
        if net.generation() != self._conn:   # the connection itself changed, not a switch
            self._conn = net.generation()
            log.info("radio: reconnecting after a connection setting change")
            self._gen += 1            # a reopen already scheduled does nothing
            self._retries = 0
            # the old stream's own error / end arrives after this: as a reconnect it
            # only schedules another try instead of giving up
            self._reconnecting, self._reopen_pending = True, False
            self._open()

    def stop(self):
        self.station = None
        self._reconnecting = self._reopen_pending = False
        self._gen += 1
        self._watch.stop()
        if self._player is not None:
            self._halt_player()
        self._set_state("stopped")

    def _halt_player(self):
        """Qt's stop() waits for its decoding thread while this thread holds Python's
        lock; a buffer that thread is handing to _on_buffer needs that lock too: a
        deadlock (stopping, and reopening a station that dropped). So _on_buffer is
        unhooked first and a buffer already on its way gets a moment (the GIL let go)
        to finish; _halting makes it return."""
        player = self._player
        if player is None:
            return
        self._halting = True
        try:
            self._unhook_buffers()
            time.sleep(0.005)
            player.stop()
            player.setSource(QUrl())
        finally:
            self._halting = False
            if not self._closed:
                self._hook_buffers()

    def _hook_buffers(self):
        if self._out is not None:
            self._out.audioBufferReceived.connect(self._on_buffer,
                                                  Qt.ConnectionType.DirectConnection)

    def _unhook_buffers(self):
        if self._out is not None:
            try:
                self._out.audioBufferReceived.disconnect(self._on_buffer)
            except (RuntimeError, TypeError):   # not connected / already gone
                pass

    def _set_state(self, st: str):
        if st != self._state:
            self._state = st
            self.state.emit(st)

    def _on_buffer(self, buf):
        """On Qt's decoding thread. The player's own state changes on the UI thread
        (_on_first_audio)."""
        with self._buffer_lock:
            if not self._closed:
                self._take_buffer(buf)

    def _take_buffer(self, buf):
        if self.station is None or self._halting:
            return
        gen = self._gen
        x = buffer_to_array(buf)
        if not len(x):
            return
        if buf.format().sampleRate() != SR:   # Qt was asked for SR; this shouldn't happen
            return
        self._last_audio = time.monotonic()
        if not self._got_audio and self._first_sent != gen:
            self._first_sent = gen   # once: every buffer until the UI thread got it sent it
            self._first_audio.emit(gen)
        self.audio.emit(x)

    def _on_first_audio(self, gen: int):
        if gen != self._gen or self.station is None or self._got_audio:
            return
        self._last_audio = self._steady_from = time.monotonic()
        self._got_audio = True
        self._reconnecting = False
        self._set_state("playing")

    def _check(self):
        if self.station is None:
            self._watch.stop()
            return
        if self._reopen_pending:
            return
        now = time.monotonic()
        over_tor = net.mode() == net.TOR
        if not self._got_audio and over_tor and not _tor_ready():
            self._opened = now   # Tor is still connecting: the station's time starts after
        elif not self._got_audio and now - self._opened > (
                TOR_CONNECT_S if over_tor else CONNECT_S) * _patience():
            self._retry("the station didn't answer")
        elif self._got_audio and now - self._last_audio > STALL_S * _patience():
            self._retry("the station stopped sending")
        elif self._got_audio and self._retries and now - self._steady_from > STEADY_S:
            self._retries = 0   # it's back for good: a later drop gets its reopens again

    def _on_error(self, _err, msg: str):
        if self.station is None:
            return
        log.info("radio stream error for %s: %s", self.station.url, msg)
        self._retry(msg or "the stream failed")

    def _on_status(self, st):
        if self.station is None:
            return
        # the server hung up: live radio never ends
        if st == QMediaPlayer.MediaStatus.EndOfMedia:
            self._retry("the station stopped sending")
        elif st == QMediaPlayer.MediaStatus.InvalidMedia:
            self._retry("the stream can't be played")

    def _retry(self, msg: str):
        if self._reopen_pending:   # one reopen at a time: the error/status/watchdog all fire
            return
        over_tor = net.mode() == net.TOR
        if (self._got_audio or self._reconnecting) and self._retries < (
                TOR_RETRIES if over_tor else RETRIES) * (2 if quality.current.patient else 1):
            self._retries += 1
            self._reconnecting = self._reopen_pending = True
            delay = (1000 if over_tor else 500) * self._retries + random.randint(0, 300)
            log.info("reopening the radio stream in %d ms (%s)", delay, msg)
            self._set_state("connecting")
            gen = self._gen
            QTimer.singleShot(delay, lambda: self._reopen(gen))
            return
        url = self.station.url if self.station is not None else ""
        self.station = None
        self._reconnecting = False
        self._watch.stop()
        if self._player is not None:
            self._player.stop()
        self._set_state("error")
        log.warning("radio: gave up on %s (%s)", url, msg)
        # the proxy's / a switch's reason if that's what failed it, else plain words
        self.error.emit(net.last_failure(self._opened) or station_off_air())

    def _reopen(self, gen: int):
        if gen != self._gen or self.station is None:
            return
        self._reopen_pending = False
        self._open()

    def _on_meta(self):
        if self._player is None:
            return
        title = self._player.metaData().stringValue(QMediaMetaData.Key.Title)
        title = " ".join(str(title or "").split())[:160]
        if title:
            self.now_playing.emit(title)

    def shutdown(self):
        """Stop for good, before the player is freed (its tab going, the app closing):
        Qt's decoding thread is cut off and any buffer it's still handing over is
        waited out, so it never calls into a freed player (a crash)."""
        if self._closed:
            return
        with self._buffer_lock:
            self._closed = True   # stop() leaves the buffers unhooked
        self.stop()


def _tor_ready() -> bool:
    from soundboard.online import tor
    return tor.manager().state == tor.READY
