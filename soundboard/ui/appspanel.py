"""The Apps tab: send one running program's sound (a music player, a browser, a
game, a call in another app) out through your mic, without touching what any
other program plays. Each program is a card: its level, a **Send** switch, its own
volume and *Hear it myself*, and **Record**, which waits for the program to make a
sound, records it until you click again and adds it to your Sounds as a pad.

The capture is Windows' per-process loopback (soundboard.appaudio), a *copy* of
the program's audio: the program keeps playing on your speakers. Programs you
switch on are remembered by their .exe and picked up again next time they run.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QCheckBox, QFileIconProvider, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from soundboard import appaudio, library, theme, trash
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS, trim_silence
from soundboard.recorder import ArmedRecorder
from soundboard.ui import icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.panel import CardGrid, HoverCard, UndoBar, VolumeControl, hint_label
from soundboard.ui.responsive import FitWidth
from soundboard.wheelguard import no_wheel

log = logging.getLogger(__name__)

REFRESH_MS = 1500       # how often the list of programs is re-read while the tab is shown
REFRESH_HIDDEN_MS = 5000   # ...and while it isn't (a remembered program still gets picked up)
METER_MS = 60
MAX_REMEMBERED = 30
CARD_MIN_W = 300        # programs are cards, as many across as fit at this width
MAX_VOL = 10.0          # 1000 %, the most the volume box takes


def saved_volume(v) -> float:
    """A remembered program's volume from the config, whatever was written there."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return min(max(v, 0.0), MAX_VOL) if math.isfinite(v) else 1.0


class _Lister(QObject):
    """Reads the audio sessions on a worker thread (COM, ~50 ms) and hands the
    result to the UI thread."""
    ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._stopped = False

    def refresh(self):
        if self._busy or self._stopped:
            return
        self._busy = True
        threading.Thread(target=self._work, name="applist", daemon=True).start()

    def _work(self):
        try:
            apps = appaudio.list_apps()
        except Exception:  # noqa: BLE001
            # skip this round: an empty list would stop every capture and drop the rows
            log.exception("listing programs failed")
            return
        finally:
            self._busy = False
        if not self._stopped:
            self.ready.emit(apps)

    def stop(self):
        self._stopped = True


class ElidedLabel(QLabel):
    """A one-line label that ends in "…" when it doesn't fit (the full text in its
    tooltip), instead of being cut off mid-word."""

    def paintEvent(self, e):
        text = self.text()
        r = self.contentsRect()
        shown = self.fontMetrics().elidedText(text, Qt.ElideRight, r.width())
        self.setToolTip(text if shown != text else "")
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment() | Qt.AlignVCenter), shown)


class AppRow(HoverCard):
    """One program, as a card: icon and name, its level, Send and Record, volume and
    Hear it myself."""
    send_toggled = Signal(object, bool)     # row, on
    rec_toggled = Signal(object, bool)
    vol_changed = Signal(object, float)
    hear_toggled = Signal(object, bool)
    forget = Signal(object)

    def __init__(self, exe: str, meter_cls, vol: float = 1.0, hear: bool = False):
        super().__init__()
        self.exe = exe
        self.app: appaudio.App | None = None
        self.capture: appaudio.AppCapture | None = None
        self.src = None                 # engine.AuxSource while sending
        self.rec: ArmedRecorder | None = None   # while Record is on
        self.status_text = ""
        self.status_error = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.icon.setAlignment(Qt.AlignCenter)
        top.addWidget(self.icon)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.name = ElidedLabel(exe)
        self.name.setStyleSheet("font-weight:600;")
        self.sub = ElidedLabel()
        self.sub.setObjectName("hint")
        for lbl in (self.name, self.sub):   # long titles give way instead of widening the card
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lbl.setTextFormat(Qt.PlainText)   # window titles are set by web pages
        names.addWidget(self.name)
        names.addWidget(self.sub)
        top.addLayout(names, 1)
        self.btn_forget = QPushButton("✕")
        self.btn_forget.setObjectName("small")
        self.btn_forget.setToolTip("Take this program off the list")
        self.btn_forget.setFixedWidth(26)
        self.btn_forget.clicked.connect(lambda: self.forget.emit(self))
        top.addWidget(self.btn_forget, 0, Qt.AlignTop)
        v.addLayout(top)
        self.meter = meter_cls()
        self.meter.setMinimumWidth(60)
        self.meter.setToolTip("What the program is playing")
        v.addWidget(self.meter)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_send = QPushButton()
        self.btn_send.setObjectName("live")
        self.btn_send.setCheckable(True)
        self.btn_send.setToolTip("Send this program's sound out through your mic")
        icons.set_icon(self.btn_send, "live", checked_color="#ffffff")
        self.btn_send.toggled.connect(lambda on: self.send_toggled.emit(self, on))
        self.btn_rec = QPushButton("Record")
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Record this program: it waits for the program to make a "
                                "sound, then records until you click again, and the clip is "
                                "added to your Sounds. Nobody hears it unless Send is on.")
        icons.set_icon(self.btn_rec, "record", "#ff4d4f", "#ffffff", size=14)
        self.btn_rec.toggled.connect(lambda on: self.rec_toggled.emit(self, on))
        for b in (self.btn_send, self.btn_rec):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            buttons.addWidget(b)
        v.addLayout(buttons)
        mix = QHBoxLayout()
        mix.setSpacing(8)
        self.vol = VolumeControl(vol, tip="This program's volume in the mix")
        self.vol.slider.setMaximumWidth(16777215)   # the card's width, not a row's sliver
        self.vol.changed.connect(lambda v: self.vol_changed.emit(self, v))
        mix.addWidget(self.vol, 1)
        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.setToolTip("Also play it into your headphones (off: the program already "
                                 "plays there on its own)")
        self.chk_hear.setChecked(hear)
        self.chk_hear.toggled.connect(lambda on: self.hear_toggled.emit(self, on))
        mix.addWidget(self.chk_hear)
        v.addLayout(mix)
        self._tight = 0   # how many of _TIGHTEN are applied (a narrow window)
        self._label_send()
        self.set_app(None)

    NAME_ROOM = 0    # the name has its own line in the card: nothing to keep room for
    # narrow card, in this order: the typed volume goes, the buttons keep only their
    # icons (their tooltips say what they are), "Hear it myself" becomes "Hear"
    _TIGHTEN = ("spin", "send", "rec", "hear")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_width(self.width())

    def _fit_width(self, width: int):
        want = 0
        while want < len(self._TIGHTEN):
            self._set_tight(want)
            if self.minimumSizeHint().width() + self.NAME_ROOM <= width:
                break
            want += 1
        self._set_tight(want)

    def _set_tight(self, n: int):
        if n == self._tight:
            return
        self._tight = n
        on = set(self._TIGHTEN[:n])
        self.vol.spin.setVisible("spin" not in on)
        self.chk_hear.setText("Hear" if "hear" in on else "Hear it myself")
        self._label_send()
        if not self.btn_rec.isChecked():   # while recording it shows how long it's been
            self.btn_rec.setText("" if "rec" in on else "Record")
        self.layout().activate()

    @property
    def sending(self) -> bool:
        return self.btn_send.isChecked()

    def _label_send(self):
        self.btn_send.setText("" if "send" in self._TIGHTEN[:self._tight]
                              else "Sending" if self.sending else "Send")

    def set_app(self, app: appaudio.App | None):
        """The program is running (app) or not (None)."""
        self.app = app
        running = app is not None
        if running:
            self.name.setText(app.name)
            self._set_icon(app.path)
            where = ", ".join(app.devices[:2])
            sub = app.title or app.exe
            if where:
                sub += f"  ·  playing on {where}"
            if not self.status_text:   # an error stays up until the next attempt
                self.sub.setText(sub)
        else:
            self.name.setText(self.exe.rsplit(".", 1)[0].capitalize() if self.exe else "?")
            self.set_status("")
            self.sub.setText("Not running — it'll be picked up when it starts")
        self.btn_send.setEnabled(running)
        self.btn_rec.setEnabled(running)
        self.btn_forget.setVisible(not running or not self.sending)
        self.setEnabled(True)
        self.name.setEnabled(running)

    def set_status(self, text: str, error: bool = False):
        self.status_text = text
        self.status_error = error
        if text:
            self.sub.setText(text)
            theme.set_tone(self.sub, "error" if error else "")
        else:
            self.sub.setStyleSheet("")
            if self.app is not None:
                self.set_app(self.app)   # back to the program's own line

    def set_sending(self, on: bool):
        self.btn_send.blockSignals(True)
        self.btn_send.setChecked(on)
        self.btn_send.blockSignals(False)
        self._label_send()
        self.btn_forget.setVisible(not on or self.app is None)

    def set_recording(self, on: bool):
        self.btn_rec.blockSignals(True)
        self.btn_rec.setChecked(on)
        self.btn_rec.blockSignals(False)
        if not on:
            self.btn_rec.setText("" if "rec" in self._TIGHTEN[:self._tight] else "Record")

    _icons = QFileIconProvider()

    def _set_icon(self, path: str, force: bool = False):
        # set_app runs on every refresh (each 1.5 s, 5 s while hidden): the shell's
        # icon lookup is only worth doing when the program changed
        if not force and path == getattr(self, "_icon_path", None):
            return
        self._icon_path = path
        pm = None
        if path:
            try:
                pm = self._icons.icon(QFileInfo(path)).pixmap(QSize(24, 24))
            except Exception:  # noqa: BLE001
                pm = None
        if pm is None or pm.isNull():
            pm = icons.icon("apps", "muted").pixmap(QSize(22, 22))
        self.icon.setPixmap(pm)


class AppsTab(QWidget):
    """Lists the programs that have sound and captures the ones you switch on."""
    clip_ready = Signal(object, str)   # audio, suggested name (like RadioTab's)
    clip_error = ""                    # set by whoever saves the clip, when it can't
    active_changed = Signal(bool)      # some program is / no program is sent (the tab's live dot)

    def __init__(self, engine, cfg, save_cb, meter_cls):
        super().__init__()
        self.engine, self.cfg, self._save, self._meter_cls = engine, cfg, save_cb, meter_cls
        if not isinstance(cfg.apps, dict):
            cfg.apps = {}
        self.rows: dict[str, AppRow] = {}     # exe (lower) -> row
        self._sending: tuple[str, ...] = ()   # the programs being sent, as last reported
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        # the explanation is behind the ⓘ at the end of the tab bar (MainWindow)
        self.info = ("Send a program's sound",
                     "Pick a program that's playing — a music player, a browser, a game, "
                        "even a call in another app — and it goes out to whoever's listening, "
                        "on its own volume. Only that program: nothing else you play is "
                        "touched, and it keeps playing on your speakers as before. Programs "
                        "you switch on are remembered and picked up again next time they run.")
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
        self.warn.setVisible(False)
        v.addWidget(self.warn)
        self.btn_bin = QPushButton("Forgotten programs…")
        self.btn_bin.setToolTip("Bring back a program you forgot, with its volume and "
                                "“Hear it myself”")
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_forgotten)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.btn_bin)
        toolbar.addStretch(1)
        size_label = QLabel("Card size")
        size_label.setObjectName("muted")
        toolbar.addWidget(size_label)
        self.card_size = QSlider(Qt.Horizontal)
        self.card_size.setRange(240, 480)
        self.card_size.setValue(cfg.app_card_width)
        self.card_size.setFixedWidth(100)
        self.card_size.setAccessibleName("App card size")
        self.card_size.setToolTip("App card size: smaller fits more programs across")
        no_wheel(self.card_size)
        toolbar.addWidget(self.card_size)
        v.addLayout(toolbar)
        self.undo_bar = UndoBar("Remember the program again, as it was")
        v.addWidget(self.undo_bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = FitWidth()   # the cards re-flow to the width they get (AppRow._fit_width)
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(6)
        self.grid = CardGrid(min_w=self.card_size.value(), gap=10)
        self.card_size.valueChanged.connect(self._set_card_size)
        # nothing playing: Bun waits, a bit glum, above the how-to
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 12, 0, 0)
        ev.setSpacing(4)
        self.bun = BunnyWidget(height=72, pad=18, sad=0.6,
                               lines=("play something?", "so quiet…", "music, please?"),
                               joy_lines=("hehe!", "yay!"))
        ev.addWidget(self.bun, 0, Qt.AlignHCenter)
        self.empty_text = hint_label("Nothing is playing sound right now. Start some music, "
                                     "a video or a call and it'll show up here.")
        self.empty_text.setAlignment(Qt.AlignCenter)
        ev.addWidget(self.empty_text)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addLayout(self.grid)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)

        ok, why = appaudio.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)

        for exe, spec in list(cfg.apps.items())[:MAX_REMEMBERED]:   # remembered programs
            if isinstance(spec, dict):
                self._row(exe, saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")))

        self.lister = _Lister(self)
        self.lister.ready.connect(self._on_apps)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.lister.refresh)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._meters)
        self.peaks = appaudio.PeakWatcher()   # live levels; the list is only re-read every 1.5 s
        self._started = False
        self._label_bin()
        if self.rows:   # remembered programs are picked up even if this tab is never opened
            QTimer.singleShot(1500, self.start)

    def _set_card_size(self, width: int):
        self.cfg.app_card_width = width
        self.grid.min_w = width
        self.grid.invalidate()
        self.list.updateGeometry()
        self.list_layout.activate()
        self._save()

    # ------------------------------------------------------------------ lifecycle
    def showEvent(self, ev):
        super().showEvent(ev)
        self.start()
        self.timer.start(REFRESH_MS)
        self.meter_timer.start(METER_MS)
        self.peaks.start()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.peaks.stop()
        if self._started:
            self.timer.start(REFRESH_HIDDEN_MS)

    def start(self):
        """Begin watching for programs (also called before the tab is first shown,
        so remembered programs are picked up right after launch)."""
        if self._started:
            return
        self._started = True
        # the meters run while shown / recording; the list is re-read slowly until then
        self.timer.start(REFRESH_MS if self.isVisible() else REFRESH_HIDDEN_MS)
        self.lister.refresh()

    def shutdown(self):
        self.timer.stop()
        self.meter_timer.stop()
        self.peaks.stop()
        self.lister.stop()
        for row in list(self.rows.values()):
            self._stop_capture(row, save=False)

    def stop_all(self):
        """Stop all: switch every program off (they stay remembered). A recording
        keeps going: nobody hears it."""
        for row in self.rows.values():
            if row.sending:
                row.set_sending(False)
                self._stop_send(row)
        self._report_active()

    def on_air(self) -> bool:
        return self.engine.aux_on_air()

    def is_active(self) -> bool:
        """Some program's sound is being sent."""
        return any(row.sending for row in self.rows.values())

    def live_tip(self) -> str:
        """The "● ON" line for the Apps tab's tooltip while a program is sent."""
        names = [row.name.text() for row in self.rows.values() if row.sending]
        return "● ON: sending " + (", ".join(names) if names else "a program's sound")

    def _report_active(self):
        """Tell the tab's live dot when the set of programs being sent changes
        (on / off, and which: its tip names them)."""
        now = tuple(sorted(exe for exe, row in self.rows.items() if row.sending))
        if now != self._sending:
            self._sending = now
            self.active_changed.emit(bool(now))

    # ------------------------------------------------------------------ rows
    def _row(self, exe: str, vol: float = 1.0, hear: bool = False) -> AppRow:
        key = exe.lower()
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = AppRow(exe, self._meter_cls, vol, hear)
            row.send_toggled.connect(self._on_send)
            row.rec_toggled.connect(self._on_rec)
            row.vol_changed.connect(self._on_vol)
            row.hear_toggled.connect(self._on_hear)
            row.forget.connect(self._on_forget)
            self.grid.addWidget(row)
            self.empty.setVisible(False)
        return row

    def _drop_row(self, row: AppRow):
        self._stop_capture(row)
        self.rows.pop(row.exe.lower(), None)
        self.grid.removeWidget(row)
        row.deleteLater()
        self.empty.setVisible(not self.rows)
        self._report_active()

    def _hidden(self) -> set[str]:
        return {str(e).lower() for e in self.cfg.apps_hidden}

    def _on_apps(self, apps: list):
        by_exe: dict[str, appaudio.App] = {}
        hidden = self._hidden()
        for app in apps:
            key = app.exe.lower()
            if key in hidden and key not in self.rows:
                continue                          # taken off the list with ✕
            cur = self.rows.get(key)
            if cur is not None and cur.capture is not None and cur.capture.pid == app.pid:
                by_exe[key] = app   # two copies running: stay on the one being captured
            else:
                by_exe.setdefault(key, app)
            self._row(app.exe)
        for key, row in list(self.rows.items()):
            app = by_exe.get(key)
            remembered = key in self.cfg.apps
            if app is None:                       # not running
                self._stop_capture(row)
                row.set_sending(False)
                if not remembered:
                    self._drop_row(row)
                    continue
                row.set_app(None)
                continue
            appeared = row.app is None
            row.set_app(app)
            cap = row.capture
            if cap is not None and cap.error:     # the capture died: say so, don't retry blindly
                self._stop_capture(row)
                row.set_sending(False)
                row.set_status(cap.error, error=True)
                log.warning("capturing %s stopped: %s", row.exe, cap.error)
                continue
            if cap is not None and (cap.ended or cap.pid != app.pid):
                rec, row.rec = row.rec, None      # a recording carries on across the restart
                self._stop_capture(row)           # it closed / restarted / the device changed
                if rec is not None:
                    row.rec = rec
                    if not row.sending and not self._open_capture(row):
                        self._finish_rec(row)
            if row.capture is None:
                if remembered and appeared:
                    row.set_sending(True)         # a remembered program just started
                if row.sending:
                    self._start_capture(row)
            elif row.status_text and row.status_error:
                row.set_status("")
        self.empty.setVisible(not self.rows)
        self._report_active()

    def _meters(self):
        if not self.isVisible() and not any(r.rec for r in self.rows.values()):
            self.meter_timer.stop()   # hidden, nothing to cap: showEvent restarts it
            return
        for row in list(self.rows.values()):
            rec = row.rec
            if rec is not None:
                secs = rec.seconds
                if secs >= MAX_SECONDS:
                    self._finish_rec(row)
                elif rec.triggered:
                    row.btn_rec.setText(f"Stop  {int(secs // 60)}:{int(secs % 60):02d}")
                else:
                    row.btn_rec.setText("Waiting for sound…")
            if row.src is not None:
                row.meter.set_level(row.src.level)
                row.src.level *= 0.8
            elif row.app is None:
                row.meter.set_level(0.0)
            else:
                live = self.peaks.peak(row.app.pid)
                row.meter.set_level(row.app.peak if live is None else live)

    # ------------------------------------------------------------------ capture
    # One capture per program, open while it's being sent, recorded, or both.
    def _sink(self, row: AppRow, x):
        """A chunk of the program's audio (on the capture thread)."""
        src = row.src
        if src is not None:
            self.engine.feed_aux(src, x)
        rec = row.rec
        if rec is not None:
            rec.push(x)

    def _open_capture(self, row: AppRow) -> bool:
        if row.capture is not None:
            return True
        if row.app is None:
            return False
        cap = appaudio.AppCapture(row.app.pid, lambda x, r=row: self._sink(r, x),
                                  name=row.app.name)
        if not cap.start():
            row.set_status(cap.error or "Couldn't capture it.", error=True)
            log.warning("capturing %s failed: %s", row.exe, cap.error)
            return False
        row.capture = cap
        log.info("capturing %s (pid %d)", row.exe, row.app.pid)
        return True

    def _close_capture(self, row: AppRow):
        cap, row.capture = row.capture, None
        if cap is not None:
            cap.stop()
        row.meter.set_level(0.0)

    def _start_capture(self, row: AppRow):
        """Send on: the program's audio goes into the mix."""
        if row.app is None or row.src is not None:
            return
        row.set_status("Connecting…")   # opening its audio can take a moment
        row.sub.repaint()
        key = ("app", row.exe.lower())
        src = self.engine.add_aux(key)
        src.vol = row.vol.value()
        src.monitor = row.chk_hear.isChecked()
        row.src = src
        if not self._open_capture(row):
            row.src = None
            self.engine.remove_aux(key)
            row.set_sending(False)
            return
        row.set_status("")
        row.set_sending(True)

    def _stop_send(self, row: AppRow):
        """Send off; the capture stays open while Record is on."""
        src, row.src = row.src, None
        if src is not None:
            self.engine.remove_aux(src.key)
        if row.rec is None:
            self._close_capture(row)

    def _stop_capture(self, row: AppRow, save: bool = True):
        """Stop everything on this row: sending, and recording (kept if `save`)."""
        self._finish_rec(row, save)
        src, row.src = row.src, None
        if src is not None:
            self.engine.remove_aux(src.key)
        self._close_capture(row)

    # ------------------------------------------------------------------ record
    def _spool_path(self, row: AppRow):
        return library.APP_DIR / f"app-recording-{re.sub(r'[^A-Za-z0-9._-]', '_', row.exe)}.tmp.wav"

    def _on_rec(self, row: AppRow, on: bool):
        if not on:
            self._finish_rec(row)
            return
        if row.app is None or row.rec is not None:
            row.set_recording(row.rec is not None)
            return
        row.rec = ArmedRecorder(self._spool_path(row))
        if not self._open_capture(row):
            row.rec = None
            row.set_recording(False)
            return
        row.btn_rec.setText("Waiting for sound…")
        self.meter_timer.start(METER_MS)   # also enforces the length cap while hidden

    def _finish_rec(self, row: AppRow, save: bool = True):
        rec, row.rec = row.rec, None
        if rec is None:
            return
        row.set_recording(False)
        if save:
            row.set_status("Saving the clip…")
            row.sub.repaint()
        heard = rec.triggered
        data = rec.stop()
        if row.src is None:
            self._close_capture(row)
        if not save:
            return
        data = trim_silence(data)
        if len(data) < int(0.2 * SR):
            self._flash(row, "Too short to keep." if heard
                        else "Nothing was recorded: it didn't make a sound.")
            return
        name = (row.app.name if row.app else row.name.text())[:30] or "App"
        self.clip_error = ""
        self.clip_ready.emit(data, f"{name} {time.strftime('%H.%M.%S')}")
        if self.clip_error:   # the window couldn't save it
            row.set_status(f"Couldn't save the clip: {self.clip_error}", error=True)
            return
        self._flash(row, f"✓ Saved a {len(data) / SR:.1f}s clip to your Sounds.")

    def _flash(self, row: AppRow, text: str):
        row.set_status(text)

        def clear():
            if row.status_text == text and not row.status_error:
                row.set_status("")
        QTimer.singleShot(5000, row, clear)

    # ------------------------------------------------------------------ controls
    def _remember(self, row: AppRow):
        self.cfg.apps[row.exe.lower()] = {"vol": row.vol.value(),
                                          "monitor": row.chk_hear.isChecked()}
        while len(self.cfg.apps) > MAX_REMEMBERED:
            self.cfg.apps.pop(next(iter(self.cfg.apps)))
        self._save()

    def _on_send(self, row: AppRow, on: bool):
        row._label_send()
        if on:
            self._start_capture(row)
            if row.capture is not None:
                self._remember(row)
        else:
            self._stop_send(row)
            self.cfg.apps.pop(row.exe.lower(), None)
            self._save()
            row.btn_forget.setVisible(True)
            if row.app is None:
                self._drop_row(row)
        self._report_active()

    def _on_vol(self, row: AppRow, v: float):
        if row.src is not None:
            row.src.vol = v
        if row.exe.lower() in self.cfg.apps:
            self._remember(row)

    def _on_hear(self, row: AppRow, on: bool):
        if row.src is not None:
            row.src.monitor = on
        if row.exe.lower() in self.cfg.apps:
            self._remember(row)

    def _on_forget(self, row: AppRow):
        """✕: forget what's remembered about the program and take it off the list. A
        running one stays off (cfg.apps_hidden) until it's brought back from the
        Undo bar or *Forgotten programs…*."""
        key = row.exe.lower()
        spec = self.cfg.apps.pop(key, None)
        spec = spec if isinstance(spec, dict) else {}
        running = row.app is not None
        if running and key not in self._hidden():
            self.cfg.apps_hidden.append(key)
        self._save()
        if spec or running:          # something to bring back: keep it in the bin
            name = row.name.text() or row.exe
            item = trash.put_app(key, spec, name, hidden=running)
            self._label_bin()
            self.undo_bar.show_for(f"Removed “{name}”",
                                   lambda: self._undo_forget(item.id))
        self._stop_send(row)
        self._drop_row(row)
        self._report_active()

    def _undo_forget(self, item_id: str):
        it = trash.take(item_id)
        if it is not None:
            self._unforget(it)

    def show_forgotten(self):
        from soundboard.ui.deleted import DeletedDialog
        self.undo_bar.finish()
        DeletedDialog(trash.APP, "programs", self._unforget, self).exec()
        self._label_bin()

    def _label_bin(self):
        self.btn_bin.setVisible(bool(trash.items(trash.APP)))

    def _unforget(self, item: trash.Item) -> bool:
        """A forgotten program taken out of the bin: remember it again."""
        exe, spec = str(item.data.get("exe", "")).lower(), item.data.get("spec")
        if not exe or not isinstance(spec, dict):
            return False
        self.cfg.apps_hidden = [e for e in self.cfg.apps_hidden if str(e).lower() != exe]
        if not spec:                 # only taken off the list: back on the next listing
            self._save()
            self._label_bin()
            if self._started:
                self.lister.refresh()
            return True
        self.cfg.apps[exe] = dict(spec)
        while len(self.cfg.apps) > MAX_REMEMBERED:
            self.cfg.apps.pop(next(iter(self.cfg.apps)))
        self._save()
        old = self.rows.get(exe)
        app = old.app if old is not None else None
        if old is not None and not old.sending:
            self._drop_row(old)   # built again with the remembered volume
        row = self._row(exe, saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")))
        row.set_app(app)
        self._label_bin()
        if not self._started:
            self.start()
        return True

    def retheme(self):
        for row in self.rows.values():   # a program that isn't running: the placeholder
            row._set_icon(row.app.path if row.app is not None else "", force=True)
