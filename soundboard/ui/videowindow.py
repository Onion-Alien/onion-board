"""The player's "Video" window: a pad made from a video shows it while it plays.

Only the picture comes from here. The sound is still the pad's own audio from the
engine (so it reaches Discord / the game with the pad's volume and effects like any
other sound); the video player has no audio output, and follows the pad: it plays,
pauses and seeks with it, at a rate that keeps it in step with speed effects.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

DRIFT_MS = 350     # further out of step than this and the video jumps to the sound


class VideoWindow(QWidget):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.resize(640, 380)
        self.setMinimumSize(240, 150)
        self.sid = ""
        self.path: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.view = QVideoWidget()
        self.view.setStyleSheet("background:#000;")
        v.addWidget(self.view, 1)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        self.note.hide()
        v.addWidget(self.note)
        self.player = QMediaPlayer(self)   # no QAudioOutput: silent, the engine plays it
        self.player.setVideoOutput(self.view)
        self.player.errorOccurred.connect(self._on_error)

    def show_for(self, sid: str, name: str, path: Path):
        """Show sound `sid`'s video (`path`)."""
        if sid != self.sid or path != self.path:
            self.sid, self.path = sid, path
            self.note.hide()
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.pause()   # shows the first frame until the sound plays
        self.setWindowTitle(f"{name} — video")
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def follow(self, state: tuple[float, bool] | None, audio_secs: float, speed: float = 1.0):
        """Keep in step with the pad: `state` is the engine's (progress 0..1, paused),
        None when it isn't playing; `audio_secs` how long its audio is (with its saved
        effects), `speed` the player's live speed."""
        p = self.player
        dur = p.duration()
        if dur <= 0 or audio_secs <= 0:   # not loaded yet (or can't be)
            return
        if state is None:
            if p.playbackState() == QMediaPlayer.PlayingState:
                p.pause()
            return
        prog, paused = state
        # the audio may be sped up or slowed down: the video takes as long as it does
        rate = min(max(dur / 1000 / audio_secs * max(speed, 0.01), 0.1), 8.0)
        if abs(p.playbackRate() - rate) > 0.01:
            p.setPlaybackRate(rate)
        want = int(min(max(prog, 0.0), 1.0) * dur)
        if abs(p.position() - want) > DRIFT_MS * max(rate, 1.0):
            p.setPosition(want)
        if paused:
            if p.playbackState() == QMediaPlayer.PlayingState:
                p.pause()
        elif p.playbackState() != QMediaPlayer.PlayingState and want < dur - 50:
            p.play()

    def _on_error(self, _err, text: str):
        log.info("can't show the video %s: %s", self.path, text)
        self.note.setText(f"This video can't be shown ({text or 'unknown format'}). "
                          "The sound plays as normal.")
        self.note.show()

    def closeEvent(self, e):
        self.player.stop()
        self.sid, self.path = "", None
        self.player.setSource(QUrl())
        self.closed.emit()
        super().closeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)
