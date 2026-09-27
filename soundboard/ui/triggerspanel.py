"""The Triggers tab: play a sound when a picture shows up on your screen — a game's
"YOU DIED", a victory banner, a kill-feed icon. Each trigger is a card: the picture
to look for (a file, or pasted after Win+Shift+S), the sound from your board, how
long to wait before playing it, how soon it may play again, and how close a match
must be, with the live match next to it so the number is easy to set.

The watching itself (screen capture and matching on a worker thread) is
soundboard.screenwatch. Triggers are kept in Config.screen and their pictures in
%APPDATA%\\OnionBoard\\triggers.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from soundboard import library, screenwatch
from soundboard.library import AUDIO_EXTS
from soundboard.screenwatch import INTERVALS_MS, Trigger, Watched
from soundboard.ui import icons
from soundboard.ui.panel import Flow, card, hint_label
from soundboard.wheelguard import no_wheel

log = logging.getLogger(__name__)

PICTURE_EXTS = "*.png *.jpg *.jpeg *.bmp *.webp *.gif"
FILE = "__file__"       # the sound list's "Choose a sound file…" entry
POLL_MS = 150           # how often the live match numbers refresh
MAX_TRIGGERS = 50
MAX_SIDE = 1600         # bigger pictures are scaled down when added
THUMB = QSize(80, 45)
GREEN = "#13ce66"


def pictures_dir() -> Path:
    return library.APP_DIR / "triggers"


def picture_gray(path: str) -> np.ndarray | None:
    """A picture file as grey float32 0..1 (transparent parts count as black)."""
    img = QImage(path)
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_RGB32)   # B, G, R, 0xff in memory
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    bgra = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    return screenwatch.to_gray(bgra)


def save_picture(img: QImage, tid: str) -> str:
    """Keep a copy of the picture (scaled down if huge) as <id>.png; returns its path."""
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    folder = pictures_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{tid}.png"
    if not img.save(str(path), "PNG"):
        raise OSError(f"couldn't save the picture to {path}")
    return str(path)


def narrow(combo: QComboBox, chars: int) -> QComboBox:
    """A list that doesn't grow to its longest entry (the window must fit 300 px)."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    return combo


def labelled(text: str, w: QWidget) -> QWidget:
    """`text` and its control kept together on one line of a wrapping row."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    if text:
        h.addWidget(QLabel(text))
    h.addWidget(w)
    return box


def flatness(gray: np.ndarray) -> float:
    return float(gray.std()) if gray.size else 0.0


class TriggerRow(QFrame):
    """One trigger's card."""
    changed = Signal(object)            # row: a setting changed
    picture_wanted = Signal(object)     # row: pick a new picture
    sound_file_wanted = Signal(object)  # row: "Choose a sound file…"
    test = Signal(object)
    remove = Signal(object)

    def __init__(self, t: Trigger, sounds: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("card")
        self.t = t
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.thumb = QPushButton()
        self.thumb.setFixedSize(THUMB + QSize(8, 8))
        self.thumb.setIconSize(THUMB)
        self.thumb.setCursor(Qt.PointingHandCursor)
        self.thumb.setToolTip("The picture to look for — click to change it")
        self.thumb.clicked.connect(lambda: self.picture_wanted.emit(self))
        top.addWidget(self.thumb)
        names = QVBoxLayout()
        names.setSpacing(4)
        self.name = QLineEdit(t.name)
        self.name.setMinimumWidth(50)
        self.name.setPlaceholderText("Name, e.g. Died")
        self.name.setMaxLength(60)
        self.name.editingFinished.connect(self._on_name)
        names.addWidget(self.name)
        self.state = QLabel()
        self.state.setObjectName("hint")
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.state)
        top.addLayout(names, 1)
        self.chk_on = QCheckBox("On")
        self.chk_on.setToolTip("Watch for this picture (untick to keep it but pause it)")
        self.chk_on.setChecked(t.enabled)
        self.chk_on.toggled.connect(self._on_enabled)
        top.addWidget(self.chk_on, 0, Qt.AlignTop)
        self.btn_del = QPushButton("✕")
        self.btn_del.setObjectName("small")
        self.btn_del.setFixedWidth(26)
        self.btn_del.setToolTip("Delete this trigger")
        self.btn_del.clicked.connect(lambda: self.remove.emit(self))
        top.addWidget(self.btn_del, 0, Qt.AlignTop)
        v.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Play"))
        self.sound = QComboBox()
        narrow(self.sound, 10)
        self.sound.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.sound.setToolTip("The sound to play (from your Sounds tab, or pick a file and "
                              "it's added there too)")
        no_wheel(self.sound)
        self.sound.activated.connect(self._on_sound)
        row.addWidget(self.sound, 1)
        self.btn_test = QPushButton()
        self.btn_test.setToolTip("Play the sound now, to check it")
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(lambda: self.test.emit(self))
        row.addWidget(self.btn_test)
        v.addLayout(row)

        row = Flow(gap=10)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(t.delay)
        self.delay.setToolTip("How long after the picture shows up to play the sound "
                              "(0 = straight away)")
        row.addWidget(labelled("Wait", self.delay))
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(0.0, 600.0)
        self.cooldown.setDecimals(0)
        self.cooldown.setSingleStep(1.0)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(t.cooldown)
        self.cooldown.setToolTip("After playing, ignore this picture for this long. It "
                                 "also has to leave the screen before it can play again.")
        row.addWidget(labelled("Not again for", self.cooldown))
        self.threshold = QSpinBox()
        self.threshold.setRange(30, 99)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(round(t.threshold * 100))
        self.threshold.setToolTip("How alike the screen must be to count. Lower it if the "
                                  "picture is missed, raise it if it plays by mistake — "
                                  "the live number on the right helps.")
        self.live = QLabel("—")
        self.live.setMinimumWidth(64)
        self.live.setToolTip("How well the screen matches the picture right now")
        match = labelled("Match", self.threshold)
        match.layout().addWidget(self.live)
        row.addWidget(match)
        v.addLayout(row)
        for w in (self.delay, self.cooldown, self.threshold):
            no_wheel(w)
            w.valueChanged.connect(self._on_numbers)

        self.set_sounds(sounds)
        self.refresh_picture()
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._update_state)
        self._update_state()

    # ------------------------------------------------------------------ view
    def set_sounds(self, sounds: list[tuple[str, str]]):
        self.sound.blockSignals(True)
        self.sound.clear()
        self.sound.addItem("Pick a sound…", "")
        for sid, name in sounds:
            self.sound.addItem(name, sid)
        self.sound.insertSeparator(self.sound.count())
        self.sound.addItem(icons.icon("folder"), "Choose a sound file…", FILE)
        i = self.sound.findData(self.t.sound) if self.t.sound else -1
        if i < 0 and self.t.pending:
            self.sound.insertItem(1, "Adding the sound…", "")
            i = 1
        self.sound.setCurrentIndex(max(i, 0))
        self.sound.blockSignals(False)
        self._update_state()

    def refresh_picture(self):
        pm = QPixmap(self.t.image) if self.t.image else QPixmap()
        if pm.isNull():
            self.thumb.setIcon(icons.icon("image", "muted"))
            self.thumb.setText("")
        else:
            self.thumb.setIcon(pm.scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def show_score(self, score: float | None):
        if score is None:
            self.live.setText("—")
            self.live.setStyleSheet("")
            return
        pct = max(0, round(score * 100))
        hit = score >= self.t.threshold
        self.live.setText(f"now {pct}%")
        self.live.setStyleSheet(f"color:{GREEN}; font-weight:600;" if hit else "")

    def flash(self, text: str, ms: int = 2500):
        self.state.setText(text)
        self.state.setStyleSheet(f"color:{GREEN};")
        self._flash.start(ms)

    def _update_state(self):
        t = self.t
        self.state.setStyleSheet("")
        if not t.image:
            text, warn = "No picture yet — click the box on the left", True
        elif not t.sound and not t.pending:
            text, warn = "Pick the sound to play", True
        else:
            wait = f"{t.delay:g} s after it shows up" if t.delay else "as soon as it shows up"
            text, warn = f"Plays {wait}", False
        self.state.setText(text)
        if warn:
            self.state.setStyleSheet("color:#ffb020;")

    # ------------------------------------------------------------------ edits
    def _on_name(self):
        name = self.name.text().strip() or "Trigger"
        if name != self.t.name:
            self.t.name = name
            self.changed.emit(self)

    def _on_enabled(self, on: bool):
        self.t.enabled = on
        self.changed.emit(self)

    def _on_sound(self, i: int):
        sid = self.sound.itemData(i)
        if sid == FILE:
            self.set_sounds_back()
            self.sound_file_wanted.emit(self)
            return
        if sid != self.t.sound or self.t.pending:
            self.t.sound, self.t.pending = sid or "", ""
            self.changed.emit(self)
        self._update_state()

    def set_sounds_back(self):
        """Put the list back on the trigger's own sound (after Choose a file…)."""
        self.sound.blockSignals(True)
        i = self.sound.findData(self.t.sound) if self.t.sound else 0
        self.sound.setCurrentIndex(max(i, 0))
        self.sound.blockSignals(False)

    def _on_numbers(self, _v=None):
        t = self.t
        t.delay = round(self.delay.value(), 1)
        t.cooldown = float(self.cooldown.value())
        t.threshold = self.threshold.value() / 100
        self._update_state()
        self.changed.emit(self)


class TriggersTab(QWidget):
    """The list of triggers, the on / off switch and the watcher behind them."""
    active_changed = Signal(bool)       # watching or not (for the tab's live dot)
    add_sound = Signal(str)             # a sound file to add to the board
    _fired = Signal(str)                # from the watcher thread

    def __init__(self, cfg, save_cb, sounds_cb, play_cb):
        """`sounds_cb()` lists the board's sounds as [(id, name, fingerprint)];
        `play_cb(id)` plays one."""
        super().__init__()
        self.cfg, self._save, self._sounds, self._play = cfg, save_cb, sounds_cb, play_cb
        if not isinstance(cfg.screen, dict):
            cfg.screen = {}
        s = cfg.screen
        self.triggers: list[Trigger] = []
        for d in s.get("triggers", []) if isinstance(s.get("triggers"), list) else []:
            t = Trigger.from_raw(d)
            if t is not None and len(self.triggers) < MAX_TRIGGERS:
                self.triggers.append(t)
        self.rows: dict[str, TriggerRow] = {}
        self._gray: dict[str, tuple[str, float, np.ndarray]] = {}   # id -> (path, mtime, grey)
        self._gen = 0                   # bumped to drop sounds still waiting to play
        self.watcher = screenwatch.Watcher(self._fired.emit)
        self._fired.connect(self._on_fired)
        interval = s.get("interval_ms", screenwatch.DEFAULT_INTERVAL_MS)
        if interval not in INTERVALS_MS:
            interval = screenwatch.DEFAULT_INTERVAL_MS
        self.watcher.interval = interval / 1000
        mon = s.get("monitor", 0)
        self.watcher.monitor = mon if isinstance(mon, int) and not isinstance(mon, bool) else 0

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        head, hv = card("Play a sound when something shows up on screen",
                        "Give it a picture to look for — a game's “YOU DIED”, a victory "
                        "banner, a kill icon — and the sound to play. It watches your screen "
                        "and plays the sound when the picture appears, straight away or after "
                        "a wait you choose. Cut the picture from a screenshot of the same "
                        "game at the same resolution: press Win+Shift+S, drag around it, "
                        "then click Paste picture.")
        hv.itemAt(0).widget().setWordWrap(True)
        self.hint = hv.itemAt(1).widget()
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
        self.empty = hint_label("No triggers yet. Add a picture to look for below.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)

        f = QFrame()
        f.setObjectName("transport")
        h = Flow(f, gap=8)
        h.setContentsMargins(10, 8, 12, 8)
        self.btn_watch = QPushButton()
        self.btn_watch.setObjectName("live")
        self.btn_watch.setCheckable(True)
        self.btn_watch.setToolTip("Watch the screen for the pictures below")
        icons.set_icon(self.btn_watch, "triggers", checked_color="#ffffff")
        self.btn_watch.toggled.connect(self.set_watching)
        h.addWidget(self.btn_watch)
        self.btn_add = QPushButton("Add picture…")
        self.btn_add.setObjectName("primary")
        self.btn_add.setToolTip("A new trigger from a picture file (PNG, JPG…)")
        icons.set_icon(self.btn_add, "plus", "on_accent")
        self.btn_add.clicked.connect(self.add_from_file)
        h.addWidget(self.btn_add)
        self.btn_paste = QPushButton("Paste picture")
        self.btn_paste.setToolTip("A new trigger from the picture you copied (Win+Shift+S "
                                  "cuts a piece of the screen)")
        icons.set_icon(self.btn_paste, "image")
        self.btn_paste.clicked.connect(self.add_from_clipboard)
        h.addWidget(self.btn_paste)
        self.cb_interval = narrow(QComboBox(), 6)
        for ms in INTERVALS_MS:
            label = f"{ms} ms" + (" (every frame)" if ms == 16 else "")
            self.cb_interval.addItem(label, ms)
        self.cb_interval.setCurrentIndex(self.cb_interval.findData(interval))
        self.cb_interval.setToolTip("How often the screen is checked. Faster reacts sooner "
                                    "but uses more of your processor; 100 ms is a tenth of "
                                    "a second.")
        self.cb_interval.currentIndexChanged.connect(self._on_interval)
        no_wheel(self.cb_interval)
        every = labelled("Check every", self.cb_interval)
        self.lbl_interval = every.layout().itemAt(0).widget()
        h.addWidget(every)
        self.cb_monitor = narrow(QComboBox(), 10)
        self.cb_monitor.setToolTip("Which screen to watch (the one the game is on)")
        self.cb_monitor.currentIndexChanged.connect(self._on_monitor)
        no_wheel(self.cb_monitor)
        h.addWidget(self.cb_monitor)
        v.addWidget(f)

        ok, why = screenwatch.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)
            self.btn_watch.setEnabled(False)
        self._fill_monitors()
        for t in self.triggers:
            self._add_row(t)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        self._label_watch()
        if ok and s.get("on") and self.triggers:
            self.btn_watch.setChecked(True)    # it was on when the app last closed

    # ------------------------------------------------------------------ watching
    def showEvent(self, ev):
        super().showEvent(ev)
        self.sounds_changed()      # names may have changed on the Sounds tab

    def is_active(self) -> bool:
        return self.btn_watch.isChecked()

    def set_watching(self, on: bool):
        if self.btn_watch.isChecked() != on:
            self.btn_watch.setChecked(on)      # comes back here
            return
        if on:
            self._sync()
            self.watcher.start()
            self.poll.start(POLL_MS)
        else:
            self.watcher.stop()
            self.poll.stop()
            self.cancel_pending()
            for row in self.rows.values():
                row.show_score(None)
        self.cfg.screen["on"] = on
        self._save()
        self._label_watch()
        self._show_warning()
        self.active_changed.emit(on)

    def _label_watch(self):
        text = "Watching" if self.is_active() else "Start watching"
        self.btn_watch.setProperty("full_text", text)   # read back by responsive.icon_only
        if not self.btn_watch.property("compact"):       # icon only while the window is small
            self.btn_watch.setText(text)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r

        def watch_icon(compact: bool):
            self.btn_watch.setProperty("compact", compact)
            r.icon_only(self.btn_watch)(compact)
        return [(20, "h", r.hide(self.hint)),
                (26, "w", r.icon_only(self.btn_paste)),
                (27, "w", r.icon_only(self.btn_add)),
                (28, "w", watch_icon),
                (29, "w", r.hide(self.lbl_interval))]

    def cancel_pending(self):
        """Drop sounds that are still waiting out their delay (Stop all / switch off)."""
        self._gen += 1

    def shutdown(self):
        self.poll.stop()
        self.watcher.stop()
        self.cancel_pending()

    def _sync(self):
        """Hand the watcher the triggers that can fire, pictures loaded and grey."""
        items = []
        for t in self.triggers:
            if not (t.enabled and t.image and (t.sound or t.pending)):
                continue
            gray = self._picture(t)
            if gray is not None:
                items.append(Watched(t.id, gray, t.threshold, t.cooldown))
        self.watcher.set_items(items)

    def _picture(self, t: Trigger) -> np.ndarray | None:
        try:
            mtime = Path(t.image).stat().st_mtime
        except OSError:
            return None
        got = self._gray.get(t.id)
        if got is not None and got[0] == t.image and got[1] == mtime:
            return got[2]
        gray = picture_gray(t.image)
        if gray is not None:
            self._gray[t.id] = (t.image, mtime, gray)
        return gray

    def _on_fired(self, tid: str):
        t = next((t for t in self.triggers if t.id == tid), None)
        if t is None or not self.is_active():
            return
        gen = self._gen
        if t.delay > 0:
            row = self.rows.get(tid)
            if row is not None:
                row.flash(f"Seen! Playing in {t.delay:g} s…", int(t.delay * 1000) + 1500)
            QTimer.singleShot(int(t.delay * 1000), self, lambda: self._fire(tid, gen))
        else:
            self._fire(tid, gen)

    def _fire(self, tid: str, gen: int):
        t = next((t for t in self.triggers if t.id == tid), None)
        if gen != self._gen or t is None or not t.enabled or not t.sound:
            return
        log.info("screen trigger %r matched", t.name)
        self._play(t.sound)
        row = self.rows.get(tid)
        if row is not None:
            row.flash("Played!")

    def _poll(self):
        w = self.watcher
        if not w.running and self.is_active():
            self.set_watching(False)           # the thread died: _show_warning says why
            return
        if not self.isVisible():
            return
        for tid, row in self.rows.items():
            row.show_score(w.scores.get(tid))
        self._show_warning()

    def _show_warning(self):
        w, why = self.watcher, ""
        ok, unsupported = screenwatch.supported()
        if not ok:
            why = unsupported
        elif w.error:
            why = f"Watching stopped: {w.error}"
        elif self.is_active() and w.black:
            why = ("The screen looks all black to the app. If a game is running in "
                   "fullscreen, set it to Borderless or Windowed fullscreen so it can be seen.")
        elif self.is_active() and not w.scores and not any(
                t.enabled and t.image and t.sound for t in self.triggers):
            why = "Nothing to watch for yet: each trigger needs a picture and a sound."
        self.warn.setText(why)
        self.warn.setVisible(bool(why))

    def _on_interval(self, _i: int):
        ms = self.cb_interval.currentData()
        self.watcher.interval = ms / 1000
        self.cfg.screen["interval_ms"] = ms
        self._save()

    def _fill_monitors(self):
        mons = screenwatch.monitors()
        self.cb_monitor.blockSignals(True)
        self.cb_monitor.clear()
        for i, m in enumerate(mons):
            self.cb_monitor.addItem(f"Screen {i + 1}: {m.label}", i)
        if not mons:
            self.cb_monitor.addItem("Main screen", 0)
        idx = self.watcher.monitor if 0 <= self.watcher.monitor < self.cb_monitor.count() else 0
        self.cb_monitor.setCurrentIndex(idx)
        self.cb_monitor.setVisible(len(mons) > 1)
        self.cb_monitor.blockSignals(False)

    def _on_monitor(self, i: int):
        self.watcher.set_monitor(i)
        self.cfg.screen["monitor"] = i
        self._save()

    # ------------------------------------------------------------------ the list
    def _board_sounds(self) -> list[tuple[str, str]]:
        return [(sid, name) for sid, name, _fp in self._sounds()]

    def sounds_changed(self):
        """The board's sounds changed: a sound picked here may have finished adding."""
        board = self._sounds()
        by_fp = {fp: sid for sid, _name, fp in board if fp}
        changed = False
        for t in self.triggers:
            if t.pending and t.pending in by_fp:
                t.sound, t.pending = by_fp[t.pending], ""
                changed = True
        sounds = [(sid, name) for sid, name, _fp in board]
        for row in self.rows.values():
            row.set_sounds(sounds)
        if changed:
            self._store()

    def _add_row(self, t: Trigger) -> TriggerRow:
        row = TriggerRow(t, self._board_sounds())
        row.changed.connect(lambda _r: self._store())
        row.picture_wanted.connect(self._change_picture)
        row.sound_file_wanted.connect(self._choose_sound_file)
        row.test.connect(lambda r: r.t.sound and self._play(r.t.sound))
        row.remove.connect(self._remove)
        self.rows[t.id] = row
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.empty.setVisible(False)
        return row

    def _store(self):
        self.cfg.screen["triggers"] = [asdict(t) for t in self.triggers]
        self._save()
        if self.is_active():
            self._sync()
        self._show_warning()

    def _new(self, img: QImage, name: str) -> Trigger | None:
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers.")
            return None
        t = Trigger(id=uuid.uuid4().hex[:12], name=name[:60] or "Trigger")
        if not self._set_picture(t, img):
            return None
        self.triggers.append(t)
        row = self._add_row(t)
        self._store()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        row.name.setFocus()
        row.name.selectAll()
        return t

    def _set_picture(self, t: Trigger, img: QImage) -> bool:
        if img.isNull():
            QMessageBox.warning(self, "Not a picture", "That picture couldn't be read.")
            return False
        if min(img.width(), img.height()) < 6:
            QMessageBox.warning(self, "Picture too small",
                                "Cut a bigger piece of the screen: at least 6 pixels each way.")
            return False
        try:
            path = save_picture(img, t.id)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't keep the picture", str(e))
            return False
        gray = picture_gray(path)
        if gray is None or flatness(gray) < screenwatch.FLAT_STD:
            QMessageBox.warning(self, "Picture is one plain colour",
                                "There's nothing in it to recognise. Cut a piece with some "
                                "detail, like the words or an icon.")
            return False
        t.image = path
        self._gray.pop(t.id, None)
        row = self.rows.get(t.id)
        if row is not None:
            row.refresh_picture()
            row._update_state()
        return True

    def add_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Picture to look for", str(Path.home()),
                                              f"Pictures ({PICTURE_EXTS});;All files (*)")
        if path:
            self._new(QImage(path), Path(path).stem)

    def add_from_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "No picture copied",
                                    "Copy a picture first: press Win+Shift+S, drag around "
                                    "the thing to look for, then click Paste picture.")
            return
        self._new(img, f"Trigger {len(self.triggers) + 1}")

    def _change_picture(self, row: TriggerRow):
        path, _ = QFileDialog.getOpenFileName(self, "Picture to look for", str(Path.home()),
                                              f"Pictures ({PICTURE_EXTS});;All files (*)")
        if path and self._set_picture(row.t, QImage(path)):
            self._store()

    def _choose_sound_file(self, row: TriggerRow):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, "Sound to play", str(Path.home()),
                                              f"Audio ({exts});;All files (*)")
        if not path:
            return
        fp = library.fingerprint(path)
        known = {f: sid for sid, _n, f in self._sounds() if f}
        if fp and fp in known:                 # already on the board
            row.t.sound, row.t.pending = known[fp], ""
        else:
            row.t.sound, row.t.pending = "", fp
            self.add_sound.emit(path)
        row.set_sounds(self._board_sounds())
        self._store()

    def _remove(self, row: TriggerRow):
        t = row.t
        self.triggers = [x for x in self.triggers if x.id != t.id]
        self.rows.pop(t.id, None)
        self._gray.pop(t.id, None)
        self.list_layout.removeWidget(row)
        row.deleteLater()
        if t.image and Path(t.image).parent == pictures_dir():
            try:
                Path(t.image).unlink(missing_ok=True)
            except OSError:
                log.debug("couldn't delete %s", t.image, exc_info=True)
        self.empty.setVisible(not self.triggers)
        self._store()
        if not self.triggers and self.is_active():
            self.set_watching(False)
