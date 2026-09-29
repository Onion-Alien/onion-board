"""The Triggers tab: play a sound when a picture shows up on your screen — a game's
"YOU DIED", a victory banner, a kill-feed icon. Each trigger is a card: the pictures
to look for (files, or pasted after Win+Shift+S; any of them showing up counts),
the sounds from your board and which of them play (one at random, in turn, or all
at once), how long to wait before playing, how soon it may play again, how close a
match must be, with the live match next to it so the number is easy to set, and
(with more than one screen) which screen to look on — "Same as below" being the
one picked at the bottom of the tab.

The watching itself (screen capture and matching on a worker thread) is
soundboard.screenwatch. Triggers are kept in Config.screen and their pictures in
%APPDATA%\\OnionBoard\\triggers.
"""
from __future__ import annotations

import logging
import math
import os
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from soundboard import library, screenwatch, theme
from soundboard.library import AUDIO_EXTS
from soundboard.screenwatch import (INTERVALS_MS, MAX_PICTURES, MAX_SOUNDS, Monitor, Picture,
                                    Trigger, Watched)
from soundboard.shuffle import ShuffleBag
from soundboard.ui import icons
from soundboard.ui.panel import Flow, card, hint_label
from soundboard.wheelguard import no_wheel

log = logging.getLogger(__name__)

PICTURE_EXTS = "*.png *.jpg *.jpeg *.bmp *.webp *.gif"
ADD = "__add__"         # the sound list's "+ Add sound…" entry (its resting state)
FILE = "__file__"       # ...its "Choose a sound file…" entry
PENDING = "__pending__"  # a chip for a sound still being added to the board
POLL_MS = 150           # how often the live match numbers refresh
MAX_TRIGGERS = 50
MAX_SIDE = 8192         # bigger pictures are refused (kept pixel for pixel, never resized)
THUMB = QSize(80, 45)
STRIP_THUMBS = 3        # thumbnails a card's strip shows before it scrolls
CHIP_CHARS = 24         # a sound chip's name is cut to this many characters
PICKS = (("random", "Random"), ("order", "In order"), ("all", "All at once"))


def pictures_dir() -> Path:
    return library.APP_DIR / "triggers"


def load_picture(path: str) -> Picture | None:
    """A picture file as grey float32 0..1, plus which pixels count: the opaque ones
    (None when it has no transparency). Transparent parts are left out of matching."""
    return picture_of(QImage(path))


def picture_of(img: QImage) -> Picture | None:
    """load_picture() for a picture already in memory."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)   # B, G, R, A in memory
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    bgra = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    mask = bgra[..., 3] >= 128
    return screenwatch.to_gray(bgra), (None if mask.all() else mask)


def save_picture(img: QImage, name: str) -> str:
    """Keep a copy of the picture as <name>.png; returns its path. It's kept pixel for
    pixel: resized, it would no longer match the screen it was cut from. Written
    beside it first, so a failed save leaves the old picture as it was."""
    folder = pictures_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    tmp = folder / f"{name}.saving"
    if not img.save(str(tmp), "PNG"):
        tmp.unlink(missing_ok=True)
        raise OSError(f"couldn't save the picture to {path}")
    os.replace(tmp, path)
    return str(path)


def picture_name(t: Trigger) -> str:
    """A file name (without .png) for a picture being added to `t`: <id> for the
    first, as older versions saved it, then <id>-<random> so removing and adding
    pictures never reuses a name."""
    if not t.images and not (pictures_dir() / f"{t.id}.png").exists():
        return t.id
    return f"{t.id}-{uuid.uuid4().hex[:6]}"


def delete_picture(path: str):
    """Remove a picture file this tab keeps (never one the user pointed at)."""
    if path and Path(path).parent == pictures_dir():
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            log.debug("couldn't delete %s", path, exc_info=True)


def narrow(combo: QComboBox, chars: int) -> QComboBox:
    """A list that doesn't grow to its longest entry (the window must fit 300 px)."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    return combo


class WideCombo(QComboBox):
    """A list as wide as its longest entry when there's room ("Screen 2: 1920×1080"
    isn't cut off) that still gives way when the window is small. A plain
    AdjustToContents list can never be narrower than its entries, and the tab, so
    the whole window, then can't shrink below it (the window must fit 300 px)."""

    MIN_WIDTH = 90

    def __init__(self, parent: QWidget | None = None, min_width: int = MIN_WIDTH):
        super().__init__(parent)
        self.min_width = min_width
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)   # sizeHint: the entries
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Maximum)   # up to that, down to min_width
        self.setSizePolicy(pol)

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        return QSize(min(s.width(), self.min_width), s.height())


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


def flatness(gray: np.ndarray, mask: np.ndarray | None = None) -> float:
    """How much detail there is to recognise (the opaque part's spread of greys)."""
    px = gray if mask is None else gray[mask]
    return float(px.std()) if px.size >= 16 else 0.0


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


class Thumb(QWidget):
    """One picture in a card's strip: the thumbnail (click to swap it for another
    file) with a ✕ in its corner while the mouse is over it."""
    clicked = Signal(int)
    removed = Signal(int)

    def __init__(self, index: int, path: str):
        super().__init__()
        self.index = index
        self.pic = QPushButton(self)
        self.pic.setFixedSize(THUMB + QSize(8, 8))
        self.pic.setIconSize(THUMB)
        self.pic.setCursor(Qt.PointingHandCursor)
        self.pic.clicked.connect(lambda: self.clicked.emit(self.index))
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            self.pic.setIcon(icons.icon("image", "muted"))
            self.pic.setToolTip(f"{Path(path).name}: this picture can't be read — click to "
                                "swap it for another file")
        else:
            self.pic.setIcon(pm.scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.pic.setToolTip(f"{Path(path).name} ({pm.width()}×{pm.height()})\n"
                                "Click to swap it for another file")
        self.setFixedSize(self.pic.size())
        self.x = QPushButton("✕", self)
        self.x.setObjectName("danger")
        self.x.setStyleSheet("padding:0; font-size:8pt;")
        self.x.setFixedSize(18, 18)
        self.x.setToolTip("Remove this picture")
        self.x.move(self.width() - self.x.width() - 3, 3)
        self.x.clicked.connect(lambda: self.removed.emit(self.index))
        self.x.hide()

    def enterEvent(self, ev):
        self.x.show()
        self.x.raise_()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.x.hide()
        super().leaveEvent(ev)


class Strip(QScrollArea):
    """A card's pictures in a row: up to STRIP_THUMBS wide, scrolling sideways
    past that, so a trigger with a hundred pictures stays a short card."""
    picture_clicked = Signal(int)
    picture_removed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.box = QWidget()
        self.row = QHBoxLayout(self.box)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.row.addStretch(1)
        self.setWidget(self.box)
        self.thumbs: list[Thumb] = []
        self._h = 0
        self._fit_height()

    @property
    def slot(self) -> int:
        return THUMB.width() + 8 + self.row.spacing()

    def set_paths(self, paths: list[str]):
        for th in self.thumbs:
            self.row.removeWidget(th)
            th.setParent(None)   # out of the strip now, not when the event loop gets to it
            th.deleteLater()
        self.thumbs = []
        for i, p in enumerate(paths):
            th = Thumb(i, p)
            th.clicked.connect(self.picture_clicked)
            th.removed.connect(self.picture_removed)
            self.row.insertWidget(i, th)
            self.thumbs.append(th)
        self.updateGeometry()
        self._fit_height()

    def sizeHint(self) -> QSize:
        n = min(max(len(self.thumbs), 1), STRIP_THUMBS)
        return QSize(n * self.slot, self._h)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.slot, self._h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_height()

    def _fit_height(self):
        """The thumbnails' height, plus the scrollbar's only when there's more than fits."""
        h = THUMB.height() + 8
        if len(self.thumbs) * self.slot - self.row.spacing() > self.viewport().width():
            h += self.horizontalScrollBar().sizeHint().height()
        if h != self._h:
            self._h = h
            self.setFixedHeight(h)


class TriggerRow(QFrame):
    """One trigger's card."""
    changed = Signal(object)             # row: a setting changed
    pictures_wanted = Signal(object)     # row: "+ Add pictures…" (files)
    paste_wanted = Signal(object)        # row: "Paste picture"
    picture_swap = Signal(object, int)   # row, index: swap that picture for another file
    picture_removed = Signal(object, int)  # row, index
    sound_file_wanted = Signal(object)   # row: "Choose a sound file…"
    hear = Signal(str)                   # a sound chip was clicked: play that sound id
    test = Signal(object)
    remove = Signal(object)

    def __init__(self, t: Trigger, sounds: list[tuple[str, str]],
                 screens: list[Monitor] = ()):
        super().__init__()
        self.setObjectName("card")
        self.t = t
        self.missing: list[str] = []    # its sounds that were removed from the board
        self.fallback = False           # its own screen isn't there: the default is watched
        self._screens = 0               # how many screens there are
        self._sounds: list[tuple[str, str]] = []   # the board's sounds as last given
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.strip = Strip()
        self.strip.setToolTip("The pictures to look for: any of them showing up plays the sound")
        self.strip.picture_clicked.connect(lambda i: self.picture_swap.emit(self, i))
        self.strip.picture_removed.connect(lambda i: self.picture_removed.emit(self, i))
        top.addWidget(self.strip, 0, Qt.AlignTop)
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
        names.addStretch(1)
        top.addLayout(names, 1)
        self.chk_on = QCheckBox("On")
        self.chk_on.setToolTip("Watch for this trigger (untick to keep it but pause it)")
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

        row = Flow(gap=8)
        self.count = QLabel()
        self.count.setObjectName("muted")
        row.addWidget(self.count)
        self.btn_pictures = QPushButton("+ Add pictures…")
        self.btn_pictures.setObjectName("small")
        self.btn_pictures.setToolTip(f"Add picture files to this trigger (up to {MAX_PICTURES}): "
                                     "any of them showing up plays the sound")
        self.btn_pictures.clicked.connect(lambda: self.pictures_wanted.emit(self))
        row.addWidget(self.btn_pictures)
        self.btn_paste = QPushButton("Paste picture")
        self.btn_paste.setObjectName("small")
        self.btn_paste.setToolTip("Add the picture you copied (Win+Shift+S cuts a piece of "
                                  "the screen) to this trigger")
        self.btn_paste.clicked.connect(lambda: self.paste_wanted.emit(self))
        row.addWidget(self.btn_paste)
        v.addLayout(row)

        # "Play", the chips (one per sound), "+ Add sound…", the Play mode, the test
        # button: a wrapping row, rebuilt by _layout_sounds when the chips change
        self.sounds_row = Flow(gap=6)
        self.lbl_play = QLabel("Play")
        self.chips: list[QFrame] = []
        self.sound = QComboBox()
        narrow(self.sound, 10)
        self.sound.setToolTip("Add a sound to play (from your Sounds tab, or pick a file and "
                              "it's added there too)")
        no_wheel(self.sound)
        self.sound.activated.connect(self._on_sound)
        self.pick = WideCombo()
        for key, label in PICKS:
            self.pick.addItem(label, key)
        self.pick.setCurrentIndex(max(self.pick.findData(t.pick), 0))
        self.pick.setToolTip("With several sounds: play one at random (each once before any "
                             "repeats), take them in turn, or play them all at once")
        no_wheel(self.pick)
        self.pick.currentIndexChanged.connect(self._on_pick)
        self.btn_test = QPushButton()
        self.btn_test.setToolTip("Play now, as the trigger would, to check it")
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(lambda: self.test.emit(self))
        v.addLayout(self.sounds_row)

        row = Flow(gap=10)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(t.delay)
        self.delay.setToolTip("How long after a picture shows up to play the sound "
                              "(0 = straight away)")
        row.addWidget(labelled("Wait", self.delay))
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(0.0, 600.0)
        self.cooldown.setDecimals(0)
        self.cooldown.setSingleStep(1.0)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(t.cooldown)
        self.cooldown.setToolTip("After playing, ignore this trigger for this long. Its "
                                 "picture also has to leave the screen before it can play again.")
        row.addWidget(labelled("Not again for", self.cooldown))
        self.threshold = QSpinBox()
        self.threshold.setObjectName("stepper")   # arrows like Wait / Not again for
        self.threshold.setRange(30, 99)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(round(t.threshold * 100))
        self.threshold.setToolTip("How alike the screen must be to count. Lower it if the "
                                  "picture is missed, raise it if it plays by mistake — "
                                  "the live number on the right helps.")
        self.live = QLabel("—")
        self.live.setMinimumWidth(64)
        self.live.setToolTip("How well the screen matches right now (the best of its pictures)")
        match = labelled("Match", self.threshold)
        match.layout().addWidget(self.live)
        row.addWidget(match)
        self.screen = WideCombo()
        self.screen.setToolTip("Which screen to look for the pictures on. “Same as below” "
                               "is the screen picked at the bottom of the tab.")
        no_wheel(self.screen)
        self.screen.currentIndexChanged.connect(self._on_screen)
        self.screen_box = labelled("Screen", self.screen)
        row.addWidget(self.screen_box)
        v.addLayout(row)
        for w in (self.delay, self.cooldown, self.threshold):
            no_wheel(w)
            w.valueChanged.connect(self._on_numbers)

        self.set_sounds(sounds)
        self.set_screens(list(screens))
        self.refresh_pictures()
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._update_state)
        self._update_state()

    # ------------------------------------------------------------------ view
    def set_sounds(self, sounds: list[tuple[str, str]]):
        """The board's sounds: fill the "+ Add sound" list and redraw the chips."""
        self._sounds = list(sounds)
        cb = self.sound
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("+ Add sound…", ADD)
        for sid, name in sounds:
            cb.addItem(name, sid)
        cb.insertSeparator(cb.count())
        cb.addItem(icons.icon("folder"), "Choose a sound file…", FILE)
        cb.setCurrentIndex(0)
        cb.blockSignals(False)
        names = dict(sounds)
        # a removed sound keeps its id (Undo on the Sounds tab brings it back)
        self.missing = [sid for sid in self.t.sounds if sid not in names]
        old, self.chips = self.chips, []
        for sid in self.t.sounds:
            self.chips.append(self._chip(names.get(sid, "Removed sound"), sid,
                                         warn=sid not in names))
        if self.t.pending:
            self.chips.append(self._chip("Adding the sound…", PENDING))
        self.pick.setVisible(len(self.t.sounds) > 1)
        self._layout_sounds()
        for chip in old:
            # off the card now: a chip waiting for the event loop to delete it is still
            # a child of the card, and one never laid out paints its frame at Qt's
            # default size over the card (the README screenshots showed exactly that)
            chip.setParent(None)
            chip.deleteLater()
        self._update_state()

    def _layout_sounds(self):
        """Put the sounds row's widgets back in order (the Flow layout has no insert)."""
        while self.sounds_row.count():
            self.sounds_row.takeAt(0)
        for w in (self.lbl_play, *self.chips, self.sound, self.pick, self.btn_test):
            self.sounds_row.addWidget(w)
        self.sounds_row.invalidate()

    def _chip(self, text: str, sid: str, warn: bool = False) -> QFrame:
        """A sound the trigger plays: its name (click to hear it) and a ✕."""
        chip = QFrame()
        chip.setObjectName("chip")
        h = QHBoxLayout(chip)
        h.setContentsMargins(4, 0, 2, 0)
        h.setSpacing(2)
        name = QPushButton(text if len(text) <= CHIP_CHARS else text[:CHIP_CHARS - 1] + "…")
        name.setObjectName("chipname")
        if sid == PENDING:
            name.setToolTip("This sound file is still being added to your Sounds tab")
            name.setEnabled(False)
        elif warn:
            name.setToolTip("This sound was removed from your Sounds tab (Undo there "
                            "brings it back)")
            name.setStyleSheet(f"color:{theme.status('warn')};")
        else:
            name.setToolTip(f"{text} — click to hear it")
            name.clicked.connect(lambda _=False, s=sid: self.hear.emit(s))
        h.addWidget(name)
        x = QPushButton("✕")
        x.setObjectName("chipstop")
        x.setFixedSize(22, 22)
        x.setToolTip("Stop adding this sound" if sid == PENDING else "Take this sound off "
                     "the trigger")
        x.clicked.connect(lambda _=False, s=sid: self._remove_sound(s))
        h.addWidget(x)
        return chip

    def set_screens(self, mons: list[Monitor]):
        """Fill the screen list. It's shown when there's more than one screen, or when
        this trigger picked one that isn't plugged in (so it can be put back)."""
        cb, t = self.screen, self.t
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("Same as below", None)
        for i, m in enumerate(mons):
            cb.addItem(f"Screen {i + 1}: {m.label}", i)
        self._screens = len(mons)
        self.fallback = t.monitor is not None and not 0 <= t.monitor < len(mons)
        if self.fallback:
            cb.addItem(f"Screen {t.monitor + 1} (not plugged in)", t.monitor)
        cb.setCurrentIndex(0 if t.monitor is None else max(cb.findData(t.monitor), 0))
        cb.blockSignals(False)
        self.screen_box.setVisible(len(mons) > 1 or t.monitor is not None)
        self._update_state()

    def refresh_pictures(self):
        """Redraw the strip after the trigger's pictures changed."""
        t = self.t
        self.strip.set_paths(t.images)
        self.count.setText(plural(len(t.images), "picture") if t.images else "No picture")
        room = len(t.images) < MAX_PICTURES
        self.btn_pictures.setEnabled(room)
        self.btn_paste.setEnabled(room)
        self._update_state()

    def show_score(self, score: float | None):
        if score is None:
            self.live.setText("—")
            self.live.setStyleSheet("")
            return
        pct = max(0, round(score * 100))
        hit = score >= self.t.threshold
        self.live.setText(f"now {pct}%")
        self.live.setStyleSheet(f"color:{theme.status('ok')}; font-weight:600;" if hit else "")

    def flash(self, text: str, ms: int = 2500, tone: str = "ok"):
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self._flash.start(ms)

    def _update_state(self):
        t = self.t
        n = len(t.sounds)
        if not t.images:
            text, warn = "No picture yet — click Add pictures… or Paste picture", True
        elif not n and not t.pending:
            text, warn = "Pick the sound to play", True
        elif n and len(self.missing) == n:
            text, warn = ("Its sound was removed from Sounds — pick another" if n == 1 else
                          "Its sounds were removed from Sounds — pick others"), True
        elif self.fallback:
            where = "the screen picked below" if self._screens > 1 else "the main screen"
            text, warn = (f"Screen {t.monitor + 1} isn't plugged in, so it's looked for "
                          f"on {where}"), True
        else:
            wait = f"{t.delay:g} s after it shows up" if t.delay else "as soon as it shows up"
            if n > 1:
                what = {"random": f"one of its {n} sounds at random",
                        "order": f"its {n} sounds in turn",
                        "all": f"all {n} sounds at once"}[t.pick]
                text = f"Plays {what}, {wait}"
            else:
                text = f"Plays {wait}"
            warn = False
        self.state.setText(text)
        theme.set_tone(self.state, "warn" if warn else "")

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
        """An entry of the "+ Add sound" list was picked: add it to the trigger."""
        sid = self.sound.itemData(i)
        self.sound.blockSignals(True)
        self.sound.setCurrentIndex(0)
        self.sound.blockSignals(False)
        if sid == FILE:
            self.sound_file_wanted.emit(self)
            return
        if not sid or sid == ADD or sid in self.t.sounds:
            return
        if len(self.t.sounds) >= MAX_SOUNDS:
            self.flash(f"A trigger can play up to {MAX_SOUNDS} sounds", 4000, "warn")
            return
        self.t.sounds.append(sid)
        self.set_sounds(self._sounds)
        self.changed.emit(self)

    def _remove_sound(self, sid: str):
        if sid == PENDING:
            self.t.pending = ""
        elif sid in self.t.sounds:
            self.t.sounds.remove(sid)
        else:
            return
        self.set_sounds(self._sounds)
        self.changed.emit(self)

    def _on_pick(self, i: int):
        key = self.pick.itemData(i)
        if key in screenwatch.PICKS and key != self.t.pick:
            self.t.pick = key
            self._update_state()
            self.changed.emit(self)

    def _on_screen(self, i: int):
        m = self.screen.itemData(i)
        m = m if isinstance(m, int) and not isinstance(m, bool) else None
        if m != self.t.monitor:
            self.t.monitor = m
            self.fallback = m is not None and not 0 <= m < self._screens
            self._update_state()
            self.changed.emit(self)

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
        self._mons: list[Monitor] = []      # the screens as last listed
        self._fell_back: frozenset[str] = frozenset()   # watcher.fell_back as last seen
        self._gray: dict[str, tuple[float, Picture]] = {}   # picture path -> (mtime, picture)
        self._gen = 0                   # bumped to drop sounds still waiting to play
        self._bag = ShuffleBag()        # "Random": each trigger's sounds, each once per round
        self._order: dict[str, int] = {}   # "In order": each trigger's next sound
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
                        "then click Paste picture. A trigger can hold several pictures (any "
                        "of them counts) and several sounds.")
        hv.itemAt(0).widget().setWordWrap(True)
        self.hint = hv.itemAt(1).widget()
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
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
        # six characters ("100 ms") when there's room, just enough for them when the
        # window is small: the theme's padding for the arrow made a fixed six too wide
        self.cb_interval = narrow(WideCombo(min_width=110), 6)
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
        # Wide enough for "Screen 2: 2560×1440  (main)": it grows with its entries
        # (and re-adjusts when _fill_monitors refills them), else the size is cut off;
        # narrower again when the window is.
        self.cb_monitor = WideCombo()
        self.cb_monitor.setToolTip("Which screen to watch (the one the game is on). A trigger "
                                   "that picks its own screen on its card is looked for "
                                   "there instead.")
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
        self._fill_monitors()      # ...and screens been plugged in or out

    def is_active(self) -> bool:
        return self.btn_watch.isChecked()

    def set_watching(self, on: bool, remember: bool = True):
        """Start / stop watching. `remember`: keep it as the setting for next launch
        (not when watching stopped by itself: it's tried again then)."""
        if self.btn_watch.isChecked() != on:
            self.btn_watch.blockSignals(True)
            self.btn_watch.setChecked(on)
            self.btn_watch.blockSignals(False)
        if on:
            self._fill_monitors()
            self._sync()
            self.watcher.start()
            self.poll.start(POLL_MS)
        else:
            self.watcher.stop()
            self.poll.stop()
            self.cancel_pending()
            for row in self.rows.values():
                row.show_score(None)
        if remember:
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
            if not (t.enabled and t.images and (self._playable(t) or t.pending)):
                continue
            pics = [p for p in map(self._picture, t.images) if p is not None]
            if pics:
                items.append(Watched(t.id, pics, t.threshold, t.cooldown, monitor=t.monitor))
        self.watcher.set_items(items)

    def _picture(self, path: str) -> Picture | None:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            return None
        got = self._gray.get(path)
        if got is not None and got[0] == mtime:
            return got[1]
        pic = load_picture(path)
        if pic is not None:
            self._gray[path] = (mtime, pic)
        return pic

    def _playable(self, t: Trigger) -> list[str]:
        """The trigger's sounds that are on the board right now, in its order."""
        board = {s for s, _n, _fp in self._sounds()}
        return [sid for sid in t.sounds if sid in board]

    def _on_fired(self, tid: str):
        t = next((t for t in self.triggers if t.id == tid), None)
        if t is None or not self.is_active() or not self._playable(t):
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
        if gen != self._gen or t is None or not t.enabled:
            return
        if self._play_trigger(t):
            log.info("screen trigger %r matched", t.name)
            row = self.rows.get(tid)
            if row is not None:
                row.flash("Played!")

    def _play_trigger(self, t: Trigger) -> list[str]:
        """Play the trigger's sound(s) the way its Play setting says: one at random
        (a shuffle bag: each once before any repeats, never twice running), the next
        in turn, or all of them. Sounds no longer on the board are skipped. Returns
        what played."""
        pool = self._playable(t)
        if not pool:
            return []
        if t.pick == "all":
            chosen = pool
        elif t.pick == "order":
            n, i = len(t.sounds), self._order.get(t.id, 0)
            chosen = []
            for _ in range(n):
                sid, i = t.sounds[i % n], i + 1
                if sid in pool:
                    chosen = [sid]
                    break
            self._order[t.id] = i % n
        else:
            chosen = [self._bag.next(t.id, pool)]
        for sid in chosen:
            self._play(sid)
        return chosen

    def _poll(self):
        w = self.watcher
        if not w.running and self.is_active():
            # the thread died (_show_warning says why): stop, but leave the setting on
            self.set_watching(False, remember=False)
            return
        if w.fell_back != self._fell_back:
            # a trigger's own screen went away (or came back) while watching
            self._fell_back = w.fell_back
            self._fill_monitors()
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
        elif self.is_active() and w.failed:
            i, err = next(iter(w.failed.items()))
            why = (f"Screen {i + 1} can't be captured ({err}). Triggers on it wait until "
                   "it can; the others carry on.")
        elif self.is_active() and w.lost:
            why = ("Waiting for the screen to come back. A game switching to or from "
                   "fullscreen does this for a moment.")
        elif self.is_active() and w.black:
            why = ("The screen looks all black to the app. If a game is running in "
                   "exclusive fullscreen and this stays, set it to Borderless or Windowed "
                   "fullscreen so it can be seen.")
        elif self.is_active() and not w.scores and not any(
                t.enabled and t.images and t.sounds for t in self.triggers):
            why = "Nothing to watch for yet: each trigger needs a picture and a sound."
        self.warn.setText(why)
        self.warn.setVisible(bool(why))

    def _on_interval(self, _i: int):
        ms = self.cb_interval.currentData()
        self.watcher.interval = ms / 1000
        self.cfg.screen["interval_ms"] = ms
        self._save()

    def _fill_monitors(self):
        """List the screens again: the picker at the bottom (the default) and each
        card's own list. A change while watching is passed on to the watcher."""
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
        for row in self.rows.values():
            row.set_screens(mons)
        if mons != self._mons and self.watcher.running:
            self.watcher.rescan()
        self._mons = mons

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
                if by_fp[t.pending] not in t.sounds:
                    t.sounds.append(by_fp[t.pending])
                t.pending = ""
                changed = True
        sounds = [(sid, name) for sid, name, _fp in board]
        for row in self.rows.values():
            row.set_sounds(sounds)
        if changed:
            self._store()

    def import_done(self):
        """The board has finished adding files: a sound picked here that isn't on it
        by now couldn't be added, so stop saying it's being added."""
        self.sounds_changed()
        failed = [t for t in self.triggers if t.pending]
        for t in failed:
            t.pending = ""
            row = self.rows.get(t.id)
            if row is not None:
                row.set_sounds(self._board_sounds())
        if failed:
            self._store()

    def _add_row(self, t: Trigger) -> TriggerRow:
        row = TriggerRow(t, self._board_sounds(), self._mons)
        row.changed.connect(lambda _r: self._store())
        row.pictures_wanted.connect(self._add_picture_files)
        row.paste_wanted.connect(self._paste_picture)
        row.picture_swap.connect(self._change_picture)
        row.picture_removed.connect(self._remove_picture)
        row.sound_file_wanted.connect(self._choose_sound_file)
        row.hear.connect(lambda sid: sid in self._playable(row.t) and self._play(sid))
        row.test.connect(lambda r: self._play_trigger(r.t))
        row.remove.connect(self._remove)
        self.rows[t.id] = row
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.empty.setVisible(False)
        return row

    def _store(self):
        self.cfg.screen["triggers"] = [t.to_raw() for t in self.triggers]
        self._save()
        if self.is_active():
            self._sync()
        self._show_warning()

    def _new(self, img: QImage | list[QImage], name: str) -> Trigger | None:
        """A new trigger from a picture (or several); None when none could be used."""
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers.")
            return None
        t = Trigger(id=uuid.uuid4().hex[:12], name=name[:60] or "Trigger")
        if not self._add_pictures(t, [img] if isinstance(img, QImage) else list(img)):
            return None
        self.triggers.append(t)
        row = self._add_row(t)
        self._store()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        row.name.setFocus()
        row.name.selectAll()
        return t

    def _check_picture(self, img: QImage) -> tuple[Picture | None, tuple[str, str]]:
        """Whether a picture can be looked for: (its grey and mask, ()) or (None,
        (why not, in detail))."""
        if img.isNull():
            return None, ("Not a picture", "That picture couldn't be read.")
        if min(img.width(), img.height()) < 6:
            return None, ("Picture too small",
                          "Cut a bigger piece of the screen: at least 6 pixels each way.")
        if max(img.width(), img.height()) > MAX_SIDE:
            return None, ("Picture too big", "Cut a smaller piece of the screen: at most "
                          f"{MAX_SIDE} pixels each way.")
        pic = picture_of(img)
        if pic is None or flatness(*pic) < screenwatch.FLAT_STD:
            return None, ("Picture is one plain colour",
                          "There's nothing in it to recognise. Cut a piece with some detail, "
                          "like the words or an icon. (Transparent parts don't count.)")
        return pic, ()

    def _add_pictures(self, t: Trigger, imgs: list[QImage], names: list[str] = (),
                      at: int | None = None) -> int:
        """Add pictures to a trigger (`at`: replace that one instead). Each is checked
        before it's saved, so a refused picture never replaces or joins the others;
        what was refused, and what may not be found, is said once for the lot.
        Returns how many were added."""
        refused: list[tuple[str, str, str]] = []      # (name, title, text)
        notes: list[tuple[str, str]] = []             # (name, note)
        added = left_out = 0
        for i, img in enumerate(imgs):
            name = names[i] if i < len(names) else f"Picture {len(t.images) + 1}"
            if at is None and len(t.images) >= MAX_PICTURES:
                left_out = len(imgs) - i
                break
            pic, why = self._check_picture(img)
            if pic is None:
                refused.append((name, *why))
                continue
            try:
                path = save_picture(img, picture_name(t))
            except OSError as e:
                refused.append((name, "Couldn't keep the picture", str(e)))
                continue
            if at is not None and 0 <= at < len(t.images):
                old, t.images[at] = t.images[at], path
                delete_picture(old)
                self._gray.pop(old, None)
                at = None                   # a second picture would only be added
            else:
                t.images.append(path)
            added += 1
            for note in self._picture_notes(pic, t):
                notes.append((name, note))
        row = self.rows.get(t.id)
        if row is not None:
            row.refresh_pictures()
            if left_out:
                row.flash(f"A trigger can look for up to {MAX_PICTURES} pictures — "
                          f"{plural(left_out, 'picture')} not added", 4000, "warn")
        self._say(refused, "Some pictures couldn't be used")
        self._say([(n, "This picture may not be found", note) for n, note in notes],
                  "Some pictures may not be found")
        return added

    def _say(self, items: list[tuple[str, str, str]], title: str):
        """One warning for a list of (picture name, title, text): the picture's own
        title when there's only one, `title` with the names when there are more."""
        if len(items) == 1:
            QMessageBox.warning(self, items[0][1], items[0][2])
        elif items:
            QMessageBox.warning(self, title, "\n\n".join(f"{n}: {text}" for n, _t, text in items))

    def _picture_notes(self, pic: Picture, t: Trigger) -> list[str]:
        """What may stop a picture being found on the screen it's watched on (it's kept
        anyway: it may be meant for another screen)."""
        mons = screenwatch.monitors()
        if not mons:
            return []
        i = self.watcher.monitor if t.monitor is None else t.monitor
        mon = mons[i] if 0 <= i < len(mons) else mons[0]
        gray, mask = pic
        h, w = gray.shape
        notes = []
        if w > mon.width or h > mon.height:
            notes.append(f"It's bigger than the screen being watched ({mon.width}×{mon.height}), "
                         "so it can't be found there. Cut it from a screenshot of that screen.")
            return notes
        top = screenwatch.work_scale(mon.width, [1])     # the most detail a check keeps
        need = math.ceil(screenwatch.MIN_SIDE / top)
        if min(w, h) < need:
            notes.append(f"It's very small for a {mon.width}-pixel-wide screen, so it may be "
                         "missed or match the wrong thing. A bigger piece (at least "
                         f"{need} pixels each way) works better.")
        scale = screenwatch.work_scale(mon.width, [min(w, h)])
        if mask is not None and int(screenwatch.shrink_mask(mask, scale).sum()) < \
                screenwatch.MASK_MIN:
            notes.append("Most of it is see-through and what's left is thin, so there's "
                         "almost nothing to compare once the screen is scaled down for "
                         "checking. Keep more of the background around it, or use a "
                         "picture without transparency.")
        return notes

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

    def _add_picture_files(self, row: TriggerRow):
        """The card's "+ Add pictures…": any number of files onto this trigger."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Pictures to look for", str(Path.home()),
                                                f"Pictures ({PICTURE_EXTS});;All files (*)")
        if paths and self._add_pictures(row.t, [QImage(p) for p in paths],
                                        [Path(p).name for p in paths]):
            self._store()

    def _paste_picture(self, row: TriggerRow):
        """The card's "Paste picture": the copied picture onto this trigger."""
        img = QApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "No picture copied",
                                    "Copy a picture first: press Win+Shift+S, drag around "
                                    "the thing to look for, then click Paste picture.")
            return
        if self._add_pictures(row.t, [img]):
            self._store()

    def _change_picture(self, row: TriggerRow, index: int = 0):
        """Swap one of the trigger's pictures for a file."""
        path, _ = QFileDialog.getOpenFileName(self, "Picture to look for", str(Path.home()),
                                              f"Pictures ({PICTURE_EXTS});;All files (*)")
        if path and self._add_pictures(row.t, [QImage(path)], [Path(path).name], at=index):
            self._store()

    def _remove_picture(self, row: TriggerRow, index: int):
        t = row.t
        if not 0 <= index < len(t.images):
            return
        path = t.images.pop(index)
        delete_picture(path)
        self._gray.pop(path, None)
        row.refresh_pictures()
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
            if known[fp] not in row.t.sounds:
                row.t.sounds.append(known[fp])
        else:
            row.t.pending = fp
            self.add_sound.emit(path)
        row.set_sounds(self._board_sounds())
        self._store()

    def _remove(self, row: TriggerRow):
        t = row.t
        self.triggers = [x for x in self.triggers if x.id != t.id]
        self.rows.pop(t.id, None)
        self._bag.forget(t.id)
        self._order.pop(t.id, None)
        self.list_layout.removeWidget(row)
        row.setParent(None)   # gone from the list now, not when the event loop gets to it
        row.deleteLater()
        for path in t.images:
            delete_picture(path)
            self._gray.pop(path, None)
        self.empty.setVisible(not self.triggers)
        self._store()
        if not self.triggers and self.is_active():
            self.set_watching(False)
