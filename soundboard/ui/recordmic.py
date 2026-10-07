"""The Sounds tab's *Record a sound* window: record your own voice with the mic
(raw, or through the voice changer while it's on), cut the ends, listen, name it and
add it as a pad. The audio comes from Engine.start_mic_take via recorder.MicTake,
spooled to disk as it's recorded."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton, QVBoxLayout, QWidget)

from soundboard import library
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS
from soundboard.recorder import MicTake
from soundboard.ui import fit, icons
from soundboard.ui.panel import hint_label
from soundboard.ui.trim import TrimPanel
from soundboard.ui.widgets import Meter
from soundboard.i18n import _

log = logging.getLogger(__name__)

PREVIEW = "recordmic:preview"   # ":preview": headphones only
PUMP_MS = 50                    # how often the take moves to disk and the time updates
NO_SOUND_S = 2.0                # recording this long with nothing from the mic: say so
WARN_LEFT_S = 60                # show the time left once it's this close to the cap
PEAKS = 400


def next_name(names) -> str:
    """"Recording N", one past the highest number already used."""
    used = [int(m.group(1)) for n in names
            if (m := re.fullmatch(r"Recording (\d+)", n.strip()))]
    return f"Recording {max(used, default=0) + 1}"


def _clock(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


def quiet_bounds(data: np.ndarray) -> tuple[int, int]:
    """Where the dead air at both ends of a mic take stops: a mic's hiss sits well
    above the -54 dBFS the program clips use, so the line scales with the take."""
    if not len(data):
        return 0, 0
    peak = float(np.max(np.abs(data)))
    a, b = library.silence_bounds(data, threshold=min(0.03, max(0.004, peak * 0.05)))
    return (a, b) if b > a else (0, len(data))


class RecordDialog(QDialog):
    """`voice_on()`: the voice changer is changing the mic right now. `names()`: the
    sounds' names (for "Recording N"). `save(data, name)` adds the pad and returns
    whether it could. `open_devices()` shows Setup → Devices."""

    def __init__(self, engine, voice_on: Callable[[], bool], names: Callable[[], list],
                 save: Callable[[np.ndarray, str], bool], open_devices: Callable[[], None],
                 parent=None):
        super().__init__(parent)
        fit.watch(self)
        self.engine = engine
        self._voice_on, self._names, self._save, self._open_devices = \
            voice_on, names, save, open_devices
        self.take: MicTake | None = None
        self.data: np.ndarray | None = None   # the finished take, (n, 2) float32 at SR
        self.saved = 0                        # pads added from this window
        self.setWindowTitle(_("Record a sound"))
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(hint_label(_("Record your voice with your mic and keep it as a sound. "
                                   "Nobody hears it while you record.")))

        # no mic / the mic can't open: one line and the way to fix it
        self.problem = QWidget()
        pr = QHBoxLayout(self.problem)
        pr.setContentsMargins(0, 0, 0, 0)
        self.problem_text = QLabel()
        self.problem_text.setWordWrap(True)
        self.problem_text.setProperty("tone", "error")
        pr.addWidget(self.problem_text, 1)
        self.btn_devices = QPushButton(_("Setup → Devices"))
        self.btn_devices.setObjectName("small")
        self.btn_devices.setToolTip(_("Pick the mic to record with"))
        self.btn_devices.clicked.connect(self._to_devices)
        pr.addWidget(self.btn_devices)
        lay.addWidget(self.problem)

        self.source = QWidget()
        sr = QHBoxLayout(self.source)
        sr.setContentsMargins(0, 0, 0, 0)
        self.opt_raw = QRadioButton(_("My own voice"))
        self.opt_raw.setToolTip(_("Your mic as it is"))
        self.opt_fx = QRadioButton(_("Through the voice changer"))
        self.opt_fx.setToolTip(_("Your voice the way the voice changer makes it sound now"))
        self.opt_raw.setChecked(True)
        group = QButtonGroup(self)
        for b in (self.opt_raw, self.opt_fx):
            group.addButton(b)
            sr.addWidget(b)
        sr.addStretch(1)
        lay.addWidget(self.source)

        self.rec_row = QWidget()
        row = QHBoxLayout(self.rec_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.btn_rec = QPushButton(_("Record"))
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setMinimumHeight(40)
        self.btn_rec.setMinimumWidth(120)
        icons.set_icon(self.btn_rec, "record", "#ff4d4f", "#ffffff", size=16)
        self.btn_rec.clicked.connect(self._rec_clicked)
        row.addWidget(self.btn_rec)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.time = QLabel("0:00")
        self.time.setObjectName("fxname")
        col.addWidget(self.time)
        self.meter = Meter()
        self.meter.setMinimumWidth(140)
        self.meter.setToolTip(_("Your mic's level"))
        col.addWidget(self.meter)
        row.addLayout(col, 1)
        lay.addWidget(self.rec_row)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        # after Stop: the take, its ends, a listen and a name
        self.review = QWidget()
        rv = QVBoxLayout(self.review)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        self.trim_home = QVBoxLayout()
        self.trim_home.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(self.trim_home)
        self.trim: TrimPanel | None = None
        nr = QHBoxLayout()
        self.btn_preview = QPushButton(_("Preview"))
        self.btn_preview.setToolTip(_("Listen to the part that's kept, in your headphones only"))
        icons.set_icon(self.btn_preview, "play", size=14)
        self.btn_preview.clicked.connect(self.preview)
        nr.addWidget(self.btn_preview)
        nr.addWidget(QLabel(_("Name")))
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        nr.addWidget(self.name, 1)
        rv.addLayout(nr)
        lay.addWidget(self.review)

        bottom = QHBoxLayout()
        self.btn_again = QPushButton(_("Record again"))
        self.btn_again.setToolTip(_("Throw this one away and record a new one"))
        icons.set_icon(self.btn_again, "record", size=14)
        self.btn_again.clicked.connect(self.record_again)
        bottom.addWidget(self.btn_again)
        bottom.addStretch(1)
        self.btn_save = QPushButton(_("Save"))
        self.btn_save.setObjectName("primary")
        self.btn_save.setToolTip(_("Add it to your sounds"))
        icons.set_icon(self.btn_save, "plus", "on_accent")
        self.btn_save.clicked.connect(self.save)
        bottom.addWidget(self.btn_save)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        for b in (self.btn_devices, self.btn_rec, self.btn_preview, self.btn_again, close):
            b.setAutoDefault(False)
        self.btn_save.setDefault(True)   # Enter in the name box saves
        lay.addLayout(bottom)

        self._timer = QTimer(self, interval=PUMP_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()   # the level bar moves before recording too
        self.setMinimumWidth(540)   # the trim row ("plays 0:05.6 of 0:06.2") fits
        self.status.setText(_("Up to {value} minutes.", value=MAX_SECONDS // 60))
        self._show_state()

    # ------------------------------------------------------------------ state
    def mic_problem(self) -> str:
        """Why the mic can't record, in one line ("" when it can)."""
        e = self.engine
        if not e.names.get("mic"):
            return "No mic is picked. Pick one in Setup → Devices."
        if e.mic_stream is None:
            err = e.errors_snapshot().get("mic")
            return f"Your mic can't open: {err}" if err else \
                "Your mic can't open right now. Check it in Setup → Devices."
        return ""

    def _show_state(self):
        problem = "" if self.take is not None else self.mic_problem()
        self.problem_text.setText(problem)
        self.problem.setVisible(bool(problem))
        recording = self.take is not None
        have = self.data is not None
        self.source.setVisible(self._voice_on() and not have)
        self.source.setEnabled(not recording)
        if not self._voice_on():
            self.opt_raw.setChecked(True)
        self.rec_row.setVisible(not have)
        self.btn_rec.setEnabled(recording or not problem)
        self.btn_rec.setChecked(recording)
        self.btn_rec.setText(_("Stop") if recording else _("Record"))
        icons.set_icon(self.btn_rec, "stop" if recording else "record", "#ff4d4f", "#ffffff",
                       size=16)
        self.review.setVisible(have)
        self.btn_again.setVisible(have)
        self.btn_save.setVisible(have)

    # ------------------------------------------------------------------ recording
    def _rec_clicked(self):
        if self.take is None:
            self.start()
        else:
            self.stop()

    def start(self) -> bool:
        if self.take is not None or self.mic_problem():
            self._show_state()
            return False
        self.engine.stop(PREVIEW)
        processed = self.opt_fx.isChecked() and not self.source.isHidden()
        self.take = MicTake(self.engine, processed=processed)
        self._quiet_s = 0.0
        self.status.setText(_("Recording… click Stop when you're done."))
        self._show_state()
        return True

    def stop(self):
        take, self.take = self.take, None
        if take is None:
            return
        data = take.stop()
        if not len(data):
            self.status.setText(_("Nothing was recorded: your mic sent no sound. Check it in "
                                  "Setup → Devices."))
            self._show_state()
            return
        self.data = data
        peaks = library.peaks(data, PEAKS)
        length = len(data) / SR
        if self.trim is not None:
            self.trim.setParent(None)
            self.trim.deleteLater()
        self.trim = TrimPanel(peaks, length)
        self.trim_home.addWidget(self.trim)
        a, b = quiet_bounds(data)
        self.trim.set_values(a / SR, b / SR)
        if not self.name.text().strip() or self.saved:
            self.name.setText(next_name(self._names()))
        self.status.setText(_("Drag the ends to cut it, then Save.") if not take.rate_changed
                            else _("The mic changed mid-way, so the recording stopped there."))
        self._show_state()
        self.name.setFocus()
        self.name.selectAll()

    def _tick(self):
        take = self.take
        self.meter.set_level(self.engine.level_mic)
        if take is None:
            return
        got = take.pump()
        s = take.seconds
        left = MAX_SECONDS - s
        self.time.setText(_clock(s) if left > WARN_LEFT_S else
                          _("{time}  ·  {left} left", time=_clock(s), left=_clock(left)))
        if take.full:
            self.stop()
            return
        self._quiet_s = 0.0 if got else self._quiet_s + PUMP_MS / 1000
        if self._quiet_s >= NO_SOUND_S:
            self.status.setText(_("Nothing is coming from your mic. Check it in Setup → Devices."))

    # ------------------------------------------------------------------ the take
    def kept(self) -> np.ndarray:
        """The take between the trim handles."""
        if self.data is None:
            return np.zeros((0, 2), np.float32)
        s, e = self.trim.values() if self.trim is not None else (0.0, 0.0)
        a = int(round(s * SR))
        b = int(round(e * SR)) if e else len(self.data)
        return self.data[a:b]

    def preview(self):
        data = self.kept()
        if len(data):
            self.engine.play(PREVIEW, data, 1.0, mode="restart", preview=True)

    def record_again(self):
        self.engine.stop(PREVIEW)
        self.data = None
        if self.trim is not None:
            self.trim.setParent(None)
            self.trim.deleteLater()
            self.trim = None
        self.time.setText("0:00")
        self._show_state()
        self.start()

    def save(self) -> bool:
        data = self.kept()
        if not len(data):
            return False
        name = self.name.text().strip() or next_name(self._names())
        self.engine.stop(PREVIEW)
        if not self._save(data, name):
            return False
        self.saved += 1
        self.accept_take()
        return True

    def accept_take(self):
        """Saved: done with this window."""
        self.data = None
        self.accept()

    def _unsaved(self) -> bool:
        return self.take is not None or self.data is not None

    def _to_devices(self):
        self.discard()
        self._open_devices()
        self.done(QDialog.Rejected)

    def discard(self):
        """Stop and forget whatever is recorded (closing)."""
        self._timer.stop()
        self.engine.stop(PREVIEW)
        if self.take is not None:
            self.take.cancel()
            self.take = None
        self.data = None

    def reject(self):
        if self._unsaved():
            if self.take is not None and self.take.seconds < 0.5 and self.data is None:
                pass   # just started: nothing worth asking about
            elif QMessageBox.question(self, _("Record a sound"), _("Throw this recording away?"),
                                      QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No) != QMessageBox.Yes:
                return
        self.discard()
        super().reject()

    def done(self, r):
        if r == QDialog.Accepted:
            self.discard()
        super().done(r)

    def closeEvent(self, e):
        # the title bar's X goes through reject() (and its question) too
        e.ignore()
        self.reject()
