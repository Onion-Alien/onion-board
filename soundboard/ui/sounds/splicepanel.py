"""Splices in Edit sound's Advanced view: the Add splices switch (two clicks on the big
waveform mark a part) and the Splices button, whose pop-up lists each splice's times
with a button to play it and one to remove it, and Combine splices, which asks
whether the splices back to back become a new pad (with its name) or this pad's
sound, and saves. The splices themselves live on the waveform (trim.Waveform) and in
the sound's effects (soundfx)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

from soundboard.audio import soundfx
from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import fit, icons, theme
from soundboard.ui.kit.panel import card, hint_label, icon_button
from soundboard.ui.sounds.trim import BADGE_H, TrimPanel

SHADOW = 14   # room round the pop-up's card for its shadow (it floats over the editor)


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
    """[Add splices] [Splices (n)] for Edit sound `d`'s editor button row (Advanced)."""

    def __init__(self, d):
        super().__init__()
        self.d = d
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
            for sig in (self.trim.splices_changed, self.trim.wave.spliced):
                try:
                    sig.disconnect(self._sync)
                except (RuntimeError, TypeError):
                    pass
        self.trim = trim
        trim.splices_changed.connect(self._sync)
        trim.wave.spliced.connect(self._sync)   # (also when loaded: the panel's are held)
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
        part = self.trim.play_solo(i)
        if part is not None:   # the draft's effects, on just that part
            usage.used("edit-splice-play")
            self.d.play_preview(fx={**self.d.effects.fx(), **part})

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
