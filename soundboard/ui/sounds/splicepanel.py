"""Splices in Edit sound's Advanced view: the Add splices switch (two clicks on the big
waveform mark a part) and the Splices button, whose pop-up lists each splice's times
with a button to play it and one to remove it, and Combine splices, which asks
whether the splices back to back become a new pad (with its name) or this pad's
sound, and saves. The splices themselves live on the waveform (trim.Waveform) and in
the sound's effects (soundfx)."""
from __future__ import annotations

import logging
import re
import tempfile
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QGraphicsDropShadowEffect, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
                               QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.audio import soundfx
from soundboard.audio.engine import SR
from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import load_original
from soundboard.ui.kit import busy, fit, icons, theme
from soundboard.ui.kit.panel import card, hint_label, icon_button
from soundboard.ui.sounds.trim import BADGE_H, TrimPanel

log = logging.getLogger(__name__)
SHADOW = 14   # room round the pop-up's card for its shadow (it floats over the editor)


def safe_name(name: str) -> str:
    """`name` as a file name Windows takes (no \\ / : * ? " < > |)."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:60] or "splice"


class Badge(QWidget):
    """A splice's number on a round accent badge, the same as on the waveform."""

    def __init__(self, n: int):
        super().__init__()
        self.n = n
        self.setFixedSize(QSize(BADGE_H + 4, BADGE_H))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["accent"]))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QColor(theme.T["on_accent"]))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(self.n))
        p.end()


class SplicePopup(QWidget):
    """The Splices pop-up: one row per splice, then Combine splices (or Split again).
    Closes on a click outside or Esc. Its card floats over the editor on a soft shadow,
    and belongs to the window (inside the editor's card it would be drawn see-through)."""

    def __init__(self, bar: SpliceBar):
        super().__init__(bar.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.bar = bar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW // 2, SHADOW, SHADOW + 4)
        self.box, v = card(_("Splices"), icon="scissors")
        self.box.setMinimumWidth(372)
        self.shadow = QGraphicsDropShadowEffect(self.box)
        self.shadow.setBlurRadius(28)
        self.shadow.setOffset(0, 6)
        self.box.setGraphicsEffect(self.shadow)
        outer.addWidget(self.box)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        v.addLayout(self.rows)
        self.empty = hint_label(_("No splices yet. Turn on Add splices, then click where "
                                  "a part starts and where it ends."))
        v.addWidget(self.empty)
        self.say = hint_label("")
        v.addWidget(self.say)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.combine = QPushButton(_("Combine splices"))
        self.combine.setObjectName("primary")
        self.combine.clicked.connect(bar.ask_combine)
        self.split = QPushButton(_("Split again"))
        self.split.setToolTip(_("Play the sound as before: the splices stay marked"))
        self.split.clicked.connect(lambda: bar.trim.set_joined(False))
        row.addWidget(self.combine)
        row.addWidget(self.split)
        row.addStretch(1)
        v.addLayout(row)
        self._row_widgets: list[QWidget] = []

    def fill(self):
        """Rows for the splices the waveform has now."""
        for w in self._row_widgets:
            w.setParent(None)
            w.deleteLater()
        self._row_widgets = []
        wave = self.bar.trim.wave
        for i, (a, b) in enumerate(wave.splices):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            h.addWidget(Badge(i + 1))
            times = QLabel(f"{soundfx.fmt_s(a)} – {soundfx.fmt_s(b)}")
            h.addWidget(times)
            size = QLabel(_("{n} s", n=f"{b - a:.1f}"))
            size.setObjectName("muted")
            h.addWidget(size)
            h.addStretch(1)
            play = icon_button("play", _("Play splice {n}", n=i + 1), size=16)
            play.setFixedSize(24, 24)
            play.clicked.connect(lambda _c=False, i=i: self.bar.play(i))
            drop = icon_button("close", _("Remove splice {n}", n=i + 1), size=16)
            drop.setFixedSize(24, 24)
            drop.clicked.connect(lambda _c=False, i=i: self.bar.trim.remove_splice(i))
            h.addWidget(play)
            h.addWidget(drop)
            self.rows.addWidget(w)
            self._row_widgets.append(w)
        n = len(wave.splices)
        self.empty.setVisible(not n)
        self.say.setVisible(bool(n))
        self.say.setText(_("Combined: the sound plays them back to back, 1 first.")
                         if wave.joined else
                         _("Combine splices makes the sound play them back to back, "
                           "1 first."))
        self.combine.setVisible(bool(n) and not wave.joined)
        self.split.setVisible(wave.joined)
        self.adjustSize()

    def show_under(self, anchor: QWidget):
        self.shadow.setColor(QColor(0, 0, 0, 70 if theme.is_light() else 150))   # (the theme now)
        self.fill()
        # the card (not its shadow's room) right-aligned under the button
        at = anchor.mapToGlobal(QPoint(anchor.width() + SHADOW, anchor.height() + 6 - SHADOW // 2))
        screen = anchor.screen().availableGeometry()
        x = min(at.x() - self.width(), screen.right() - self.width() - 8)
        y = at.y()
        if y + self.height() > screen.bottom() - 8:   # no room under it: above it
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6
        self.move(max(x, screen.left() + 8), max(y, screen.top() + 8))
        self.show()


class CombineDialog(QDialog):
    """Combine splices: save them back to back as a new pad (named here) or as this
    pad's sound. `choice` is "new" or "replace" once one is clicked."""

    def __init__(self, n: int, name: str, parent=None):
        super().__init__(parent)
        title = ngettext("Combine {n} splice", "Combine {n} splices", n, n=n)
        self.setWindowTitle(title)
        self.setMaximumWidth(620)
        self.choice = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        head = QLabel(title)
        head.setObjectName("helptitle")
        v.addWidget(head)
        v.addWidget(hint_label(_("They play back to back, 1 first. Your file itself is "
                                 "never cut.")))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(_("New pad's name")))
        self.name = QLineEdit(_("{name} (splices)", name=name)[:40])
        self.name.setMaxLength(40)
        self.name.setMinimumWidth(240)
        self.name.setAccessibleName(_("New pad's name"))
        row.addWidget(self.name, 1)
        v.addLayout(row)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        new = QPushButton(_("Save as new pad"))
        new.setObjectName("primary")
        new.setDefault(True)
        new.setToolTip(_("A new pad of just the splices: this pad stays as it is"))
        new.clicked.connect(lambda: self._pick("new"))
        replace = QPushButton(_("Replace this pad"))
        replace.setToolTip(_("This pad plays just the splices from now on (Split again "
                             "undoes it)"))
        replace.clicked.connect(lambda: self._pick("replace"))
        cancel = QPushButton(_("Cancel"))
        cancel.setProperty("quiet", True)
        cancel.clicked.connect(self.reject)
        for b in (new, replace, cancel):
            foot.addWidget(b)
        v.addLayout(foot)
        fit.watch(self)

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()


class SpliceBar(QWidget):
    """[Add splices] [Splices (n)] for Edit sound `d`'s editor button row (Advanced),
    and a splice's right-click menu on the waveform (menu)."""
    copied = Signal(int, str, str)   # (which copy, its file or "", why not) from the worker

    def __init__(self, d):
        super().__init__()
        self.d = d
        self._copy_gen = 0
        self._menu: QMenu | None = None
        self.copied.connect(self._copied)
        trim: TrimPanel = d.effects.trim
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.cut = QPushButton(_("Add splices"))
        icons.set_icon(self.cut, "scissors")
        self.cut.setCheckable(True)
        self.cut.setToolTip(_("Click where a part starts, then where it ends. Each part is "
                              "a splice. Esc lets go of a half-made one."))
        self.cut.toggled.connect(self._cutting)
        self.list = QPushButton()
        self.list.setToolTip(_("Each splice's times, play or remove one, combine them"))
        self.list.clicked.connect(self._open)
        h.addWidget(self.cut)
        h.addWidget(self.list)
        self.popup: SplicePopup | None = None
        self.dlg: CombineDialog | None = None
        self.trim = trim
        self.attach(trim)

    def attach(self, trim: TrimPanel):
        """Work on `trim` (Edit sound made a new one for another sound)."""
        if self.trim is not trim:
            for sig, slot in ((self.trim.splices_changed, self._sync),
                              (self.trim.wave.spliced, self._sync),
                              (self.trim.wave.menu_asked, self.menu)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self.trim = trim
        trim.splices_changed.connect(self._sync)
        trim.wave.spliced.connect(self._sync)   # (also when loaded: the panel's are held)
        trim.wave.menu_asked.connect(self.menu)
        trim.wave.set_cutting(self.cut.isChecked())
        self._sync()

    def _cutting(self, on: bool):
        self.trim.wave.set_cutting(on)

    def _sync(self):
        n = len(self.trim.wave.splices)
        self.list.setText(_("Splices ({n})", n=n))
        if self.popup is not None and self.popup.isVisible():
            self.popup.fill()

    def _open(self):
        if self.popup is None:
            self.popup = SplicePopup(self)
        self.popup.show_under(self.list)

    def play(self, i: int):
        fx = self.trim.play_solo(i, self.d.effects.fx())
        if fx is not None:   # the draft's effects, and its own, on just that part
            usage.used("edit-splice-play")
            self.d.play_preview(fx=fx)

    # ------------------------------------------------------------------ its menu
    def menu(self, i: int, at: QPoint):
        """A splice's right-click menu: play it, edit it on its own, save it as a pad of
        its own, copy it (a sound file to paste in a chat or a folder), remove it."""
        if not 0 <= i < len(self.trim.wave.splices):
            return
        n = i + 1
        m = QMenu(self)
        icons.set_icon(m.addAction(_("Play now")), "play")
        m.actions()[-1].triggered.connect(lambda: self.play(i))
        icons.set_icon(m.addAction(_("Edit its effects")), "sliders")
        m.actions()[-1].triggered.connect(lambda: self.trim.wave.pick(i))
        m.addSeparator()
        icons.set_icon(m.addAction(_("Save as new pad…")), "plus")
        m.actions()[-1].triggered.connect(lambda: self.save_as_pad(i))
        icons.set_icon(m.addAction(_("Copy to clipboard")), "copy")
        m.actions()[-1].triggered.connect(lambda: self.copy(i))
        m.addSeparator()
        icons.set_icon(m.addAction(_("Remove splice {n}", n=n)), "trash")
        m.actions()[-1].triggered.connect(lambda: self.trim.remove_splice(i))
        self._menu = m   # (kept: tests and screenshots look at it)
        m.popup(at)

    def save_as_pad(self, i: int):
        """Splice `i` as a new pad of its own (named here), with its own effects and the
        sound's: this pad stays as it is."""
        d = self.d
        default = _("{name} (splice {n})", name=d.name.text().strip() or d.meta.name,
                    n=i + 1)[:40]
        name, ok = QInputDialog.getText(d, _("Save as new pad"), _("New pad's name"),
                                        text=default)
        name = name.strip()[:40]
        if ok and name and 0 <= i < len(self.trim.wave.splices):
            usage.used("edit-splice-pad")
            d.splice_saved.emit(soundfx.splice_alone(d.effects.fx(), i), name)

    def copy(self, i: int):
        """Splice `i`, with its effects, as a WAV file on the clipboard: paste it into a
        chat, a folder or another app. Made on a worker (effects take a moment)."""
        d = self.d
        if not 0 <= i < len(self.trim.wave.splices):
            return
        usage.used("edit-splice-copy")
        fx, meta = soundfx.splice_alone(d.effects.fx(), i), d.meta
        fi, fo = d.fades()
        gain = d.vol.value() / 100
        name = f"{d.name.text().strip() or meta.name} {i + 1}"
        d._say(_("Copying splice {n}…", n=i + 1), 0)
        self._copy_gen += 1
        gen = self._copy_gen

        def work():
            try:
                x = soundfx.render(load_original(meta), fx) * gain
                ends = np.ones(len(x), np.float32)   # the sound's fades, as it plays
                for k, rising in ((min(int(fi * SR), len(x)), True),
                                  (min(int(fo * SR), len(x)), False)):
                    if k > 0:
                        ramp = np.linspace(0, 1, k, dtype=np.float32)
                        if rising:
                            ends[:k] = ramp
                        else:
                            ends[len(x) - k:] = np.minimum(ends[len(x) - k:], ramp[::-1])
                x = np.clip(x * ends[:, None], -1.0, 1.0)
                folder = Path(tempfile.gettempdir()) / "OnionBoard clips"
                folder.mkdir(exist_ok=True)
                path = folder / f"{safe_name(name)}.wav"
                sf.write(str(path), x, SR, subtype="PCM_16")
                busy.emit(self.copied, gen, str(path), "")
            except Exception as e:  # noqa: BLE001 - said in the window, not a crash
                log.warning("couldn't copy splice %d: %s", i + 1, e)
                busy.emit(self.copied, gen, "", str(e))
        threading.Thread(target=work, daemon=True, name="splice-copy").start()

    def _copied(self, gen: int, path: str, err: str):
        if gen != self._copy_gen or not qt_valid(self.d):
            return
        if not path:
            self.d._say(_("Couldn't copy it: {why}", why=err), 4000)
            return
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(path)])
        QApplication.clipboard().setMimeData(data)
        self.d._say(_("✓ Copied: paste it into a chat or a folder"), 3000)

    def ask_combine(self):
        """Combine splices: ask new pad or this one, then join them and save that way."""
        if self.popup is not None:
            self.popup.close()
        n = len(self.trim.wave.splices)
        if not n:
            return
        dlg = CombineDialog(n, self.d.name.text().strip(), self.d)
        dlg.finished.connect(lambda _code, dlg=dlg: self._combined(dlg))
        self.dlg = dlg
        dlg.open()

    def _combined(self, dlg: CombineDialog):
        d, choice, name = self.d, dlg.choice, dlg.name.text().strip()
        self.dlg = None
        dlg.deleteLater()
        if not choice or not d.isVisible():   # cancelled, or the window closed meanwhile
            return
        self.trim.set_joined(True)
        usage.used("edit-splices-new" if choice == "new" else "edit-splices-replace")
        if choice == "new":
            if name:
                d.name.setText(name)   # (Save a copy names the copy; this pad keeps its own)
            d.btn_copy.click()
        else:
            d.btn_save.click()
