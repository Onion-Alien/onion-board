"""Playing from the Store tab (`StorePlay`, a mixin of StoreTab): Play / Stop / Play next,
hearing a sound first in your headphones, and a shared link's card following the player."""
from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget

from soundboard.core import usage
from soundboard.sounds import library
from soundboard.online import store
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.ui.kit import busy
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.store.storerow import SoundRow, _blocked

log = logging.getLogger("soundboard.ui.store.storetab")

# what the mixin gets from StoreTab, for the type checker only: at run time
# it is a plain class (StoreTab itself is the widget)
_Base = QWidget if TYPE_CHECKING else object


class StorePlay(_Base):
    """StoreTab's Play, Stop, Play next and hear-it-first."""
    if TYPE_CHECKING:
        _closed: bool
        _decoded: Signal
        _hear_serial: int
        _link: Callable[[str, str, str], None]
        _link_state: Callable[[str], str]
        _play: Callable[[object, float], bool]
        _playing: SoundRow | None
        _rows: list[SoundRow]
        bun: BunnyWidget
        used: int
        voices: Any

        def _get(self, row: SoundRow, what: str): ...
        def _row_alive(self, row: SoundRow) -> bool: ...

    @staticmethod
    def _is_voice(row) -> bool:
        from soundboard.online.storevoices import Voice
        return isinstance(row.sound, Voice)

    def _hear_voice(self, row: SoundRow):
        """A community voice's sample: the line said through it, made off the UI thread."""
        serial, v = self._hear_serial, row.sound
        assert not isinstance(v, store.Sound)   # (a voice's row: _is_voice)
        module = self.voices.ai_module() if self.voices is not None else None

        def run():
            from soundboard.online import storevoices
            try:
                data, left_out = storevoices.preview(v, module)
                busy.emit(self._decoded, row, (data, left_out), 1.0, serial)
            except Exception as e:  # noqa: BLE001 - no sound, no crash
                log.info("couldn't make a voice's sample: %s", e)
                busy.emit(self._decoded, row, None, 1.0, serial)
        threading.Thread(target=run, daemon=True, name="store-voice-sample").start()

    def _is_link(self, row) -> bool:
        return not self._is_voice(row) and row.sound.is_link

    def play_clicked(self, row: SoundRow):
        """The card's Play. A link (from its site, as a search hit): played now, over a
        link that's playing; while it plays, Pause (and Resume). Else its sample, to you."""
        self.used += 1
        if not self._is_link(row):
            self.hear(row, row is not self._playing)
            return
        s = row.sound
        state = self._link_state(s.link)
        if state in ("playing", "paused"):
            self._link(s.link, s.name, "pause")
        elif state != "loading":
            self._stop_preview()
            usage.used("store-heard")
            self._link(s.link, s.name, "now")
        self._follow_links()
        if not row.state:   # (the click switched it on: off until the player has it)
            row.link_look("")

    def stop_clicked(self, row: SoundRow):
        if self._is_link(row):
            self._link(row.sound.link, row.sound.name, "stop")
            self._follow_links()
        else:
            self._stop_preview()

    def queue(self, row: SoundRow):
        """Play next: a link plays after what's playing (Up next), at once if nothing is."""
        usage.used("store-play-next")
        if self._is_link(row):
            self._stop_preview()
            usage.used("store-heard")
            self._link(row.sound.link, row.sound.name, "play")
            self._follow_links()

    def _follow_links(self):
        """Every link card shows what the player is doing with it (the bottom strip and
        Up next stop, pause and start it too)."""
        if self._closed:
            return
        for r in self._rows:
            if self._is_link(r):
                state = self._link_state(r.sound.link)
                if state != r.state:
                    r.link_look(state)

    def hear(self, row: SoundRow, on: bool):
        if self._is_voice(row):
            if self._playing is not None and self._playing is not row:
                self._stop_preview()
            self._hear_serial += 1
            if not on:
                self._stop_preview()
                return
            self._playing = row
            row.playing_look(True)
            self._hear_voice(row)
            return
        if self._playing is not None and self._playing is not row:
            self._stop_preview()
        self._hear_serial += 1
        if not on:
            self._stop_preview()
            return
        self._playing = row
        row.playing_look(True)
        self._get(row, "play")

    def _decode(self, row: SoundRow, path: str):
        serial = self._hear_serial

        def run():
            try:
                data = library.decode(path)
                busy.emit(self._decoded, row, data, library.level_gain(data), serial)
            except Exception:  # noqa: BLE001 - a broken file: no sound, no crash
                log.warning("couldn't decode store sound %s", path, exc_info=True)
                busy.emit(self._decoded, row, None, 1.0, serial)
        threading.Thread(target=run, daemon=True, name="store-decode").start()

    def _on_decoded(self, row: SoundRow, data, gain: float, serial: int):
        if not self._row_alive(row) or serial != self._hear_serial or self._playing is not row:
            return
        if isinstance(data, tuple):   # a voice's sample, and whether its AI part was left out
            data, left_out = data
            if left_out:
                busy.toast(self.window(), html.escape(
                    _("You're hearing it without its AI voice: get AI voices (Voice tab "
                      "→ AI voices) to hear all of it.")), "warn", 7000)
        if data is None or not self._play(data, gain):
            self._stop_preview()
            if data is not None:
                busy.toast(self.window(), html.escape(
                    _("Pick your headphones in Settings → Audio to hear the samples.")), "warn")
            return
        usage.used("store-heard")
        self.bun.burst(3)
        QTimer.singleShot(int(len(data) / SR * 1000) + 150, self,
                          lambda s=serial: s == self._hear_serial and self._stop_preview())

    def _stop_preview(self):
        row, self._playing = self._playing, None
        if row is not None:
            try:
                with _blocked(row.btn_play):
                    row.btn_play.setChecked(False)
                row.playing_look(False)
            except RuntimeError:   # its row went meanwhile
                pass
            self._play(None, 1.0)
