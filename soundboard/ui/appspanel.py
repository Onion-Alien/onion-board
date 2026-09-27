"""The Apps tab: send one running program's sound (a music player, a browser, a
game, a call in another app) out through your mic, without touching what any
other program plays. Each program is a row: its level, a **Send** switch, its own
volume and *Hear it myself*, and **Record**, which waits for the program to make a
sound, records it until you click again and adds it to your Sounds as a pad.

The capture is Windows' per-process loopback (soundboard.appaudio), a *copy* of
the program's audio: the program keeps playing on your speakers. Programs you
switch on are remembered by their .exe and picked up again next time they run.
"""
from __future__ import annotations

import logging
import re
import threading
import time

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QFileIconProvider, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from soundboard import appaudio, library
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS, trim_silence
from soundboard.recorder import ArmedRecorder
from soundboard.ui import icons
from soundboard.ui.panel import VolumeControl, card, hint_label

log = logging.getLogger(__name__)

REFRESH_MS = 1500       # how often the list of programs is re-read while the tab is shown
REFRESH_HIDDEN_MS = 5000   # ...and while it isn't (a remembered program still gets picked up)
METER_MS = 60
MAX_REMEMBERED = 30


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


class AppRow(QFrame):
    """One program: icon, name, level, Send, Record, volume, Hear it myself."""
    send_toggled = Signal(object, bool)     # row, on
    rec_toggled = Signal(object, bool)
    vol_changed = Signal(object, float)
    hear_toggled = Signal(object, bool)
    forget = Signal(object)

    def __init__(self, exe: str, meter_cls, vol: float = 1.0, hear: bool = False):
        super().__init__()
        self.setObjectName("card")
        self.exe = exe
        self.app: appaudio.App | None = None
        self.capture: appaudio.AppCapture | None = None
        self.src = None                 # engine.AuxSource while sending
        self.rec: ArmedRecorder | None = None   # while Record is on
        self.status_text = ""
        self.status_error = False
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.icon.setAlignment(Qt.AlignCenter)
        h.addWidget(self.icon)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.name = QLabel(exe)
        self.name.setStyleSheet("font-weight:600;")
        self.sub = QLabel()
        self.sub.setObjectName("hint")
        for lbl in (self.name, self.sub):   # long titles give way instead of widening the row
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lbl.setTextFormat(Qt.PlainText)   # window titles are set by web pages
        names.addWidget(self.name)
        names.addWidget(self.sub)
        h.addLayout(names, 2)
        self.meter = meter_cls()
        self.meter.setMinimumWidth(60)
        self.meter.setToolTip("What the program is playing")
        h.addWidget(self.meter, 1)
        self.btn_send = QPushButton()
        self.btn_send.setObjectName("live")
        self.btn_send.setCheckable(True)
        self.btn_send.setToolTip("Send this program's sound out through your mic")
        icons.set_icon(self.btn_send, "live", checked_color="#ffffff")
        self.btn_send.toggled.connect(lambda on: self.send_toggled.emit(self, on))
        h.addWidget(self.btn_send)
        self.btn_rec = QPushButton("Record")
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Record this program: it waits for the program to make a "
                                "sound, then records until you click again, and the clip is "
                                "added to your Sounds. Nobody hears it unless Send is on.")
        icons.set_icon(self.btn_rec, "record", "#ff4d4f", "#ffffff", size=14)
        self.btn_rec.toggled.connect(lambda on: self.rec_toggled.emit(self, on))
        h.addWidget(self.btn_rec)
        self.vol = VolumeControl(vol, tip="This program's volume in the mix")
        self.vol.changed.connect(lambda v: self.vol_changed.emit(self, v))
        h.addWidget(self.vol)
        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.setToolTip("Also play it into your headphones (off: the program already "
                                 "plays there on its own)")
        self.chk_hear.setChecked(hear)
        self.chk_hear.toggled.connect(lambda on: self.hear_toggled.emit(self, on))
        h.addWidget(self.chk_hear)
        self.btn_forget = QPushButton("✕")
        self.btn_forget.setObjectName("small")
        self.btn_forget.setToolTip("Forget this program")
        self.btn_forget.setFixedWidth(26)
        self.btn_forget.clicked.connect(lambda: self.forget.emit(self))
        h.addWidget(self.btn_forget)
        self._label_send()
        self.set_app(None)

    @property
    def sending(self) -> bool:
        return self.btn_send.isChecked()

    def _label_send(self):
        self.btn_send.setText("Sending" if self.sending else "Send")

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
            self.sub.setStyleSheet("color:#ff4d4f;" if error else "")
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
            self.btn_rec.setText("Record")

    _icons = QFileIconProvider()

    def _set_icon(self, path: str):
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

    def __init__(self, engine, cfg, save_cb, meter_cls):
        super().__init__()
        self.engine, self.cfg, self._save, self._meter_cls = engine, cfg, save_cb, meter_cls
        if not isinstance(cfg.apps, dict):
            cfg.apps = {}
        self.rows: dict[str, AppRow] = {}     # exe (lower) -> row
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        head, hv = card("Send a program's sound",
                        "Pick a program that's playing — a music player, a browser, a game, "
                        "even a call in another app — and it goes out to whoever's listening, "
                        "on its own volume. Only that program: nothing else you play is "
                        "touched, and it keeps playing on your speakers as before. Programs "
                        "you switch on are remembered and picked up again next time they run.")
        hv.itemAt(0).widget().setWordWrap(True)   # the title too: this tab must fit 300 px
        self.warn = hint_label("")
        self.warn.setStyleSheet("color:#ffb020;")
        self.warn.setVisible(False)
        hv.addWidget(self.warn)
        v.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = QWidget()
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.empty = hint_label("Nothing is playing sound right now. Start some music, a "
                                "video or a call and it'll show up here.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)

        ok, why = appaudio.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)

        for exe, spec in list(cfg.apps.items())[:MAX_REMEMBERED]:   # remembered programs
            if isinstance(spec, dict):
                self._row(exe, float(spec.get("vol", 1.0) or 0.0), bool(spec.get("monitor")))

        self.lister = _Lister(self)
        self.lister.ready.connect(self._on_apps)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.lister.refresh)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._meters)
        self._started = False
        if self.rows:   # remembered programs are picked up even if this tab is never opened
            QTimer.singleShot(1500, self.start)

    # ------------------------------------------------------------------ lifecycle
    def showEvent(self, ev):
        super().showEvent(ev)
        self.start()
        self.timer.start(REFRESH_MS)
        self.meter_timer.start(METER_MS)

    def hideEvent(self, ev):
        super().hideEvent(ev)
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

    def on_air(self) -> bool:
        return self.engine.aux_on_air()

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
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self.empty.setVisible(False)
        return row

    def _drop_row(self, row: AppRow):
        self._stop_capture(row)
        self.rows.pop(row.exe.lower(), None)
        self.list_layout.removeWidget(row)
        row.deleteLater()
        self.empty.setVisible(not self.rows)

    def _on_apps(self, apps: list):
        by_exe: dict[str, appaudio.App] = {}
        for app in apps:
            key = app.exe.lower()
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
            else:
                row.meter.set_level(row.app.peak if row.app else 0.0)

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
        self.clip_ready.emit(data, f"{name} {time.strftime('%H.%M.%S')}")
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
        self.cfg.apps.pop(row.exe.lower(), None)
        self._save()
        if row.app is None:
            self._drop_row(row)
        else:
            self._stop_send(row)
            row.set_sending(False)

    def retheme(self):
        for row in self.rows.values():
            if row.app is not None:
                row._set_icon(row.app.path)
