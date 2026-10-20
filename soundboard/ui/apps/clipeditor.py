"""The Apps tab's clip editor: a program's last minute as a live waveform, to
drag across, preview, trim and save.

It's opt-in and folded away: a card builds one only when its *Clip editor* is
opened, and nothing listens, keeps audio or draws while it's closed. Live, the
waveform scrolls (newest on the right). The first press on it freezes what's
there into a take to edit (soundboard.sounds.clipedit.Take); the program keeps being
kept behind it, and **Live** goes back. Drag selects; Space plays the selection
in your headphones; Ctrl+X / C / V, Delete, Ctrl+Z work as in any editor; Enter
keeps it in the tab's Saved clips (soundboard.ui.apps.clipshelf) and returns to live
capture. A copied bit also marks the system clipboard (MIME), so
Ctrl+V on the Sounds tab adds it as a sound."""
from __future__ import annotations

import html
import itertools

import numpy as np
from PySide6.QtCore import QLineF, QMimeData, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.sounds.clipedit import BIN, LiveBuffer, Take, bin_peaks
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.sounds.library import level_gain
from soundboard.ui.kit import appstate, busy, icons
from soundboard.ui.kit.panel import CONTROL_H, Flow
from soundboard.ui.kit.pixels import snap_to_pixels

PAD = 4                 # the waveform's inner margin, px
EDGE_PX = 6             # how close to a selection edge a press grabs it
DRAG_PX = 4             # a press that moves less than this is a click: it places the cursor
TICK_MS = 50            # redraw pace while live or playing (20 a second)
MIN_VIEW = 256          # frames: the furthest it zooms in
STEP_DB = 3.0           # Louder / Quieter
LIVE_MIN_S = 10         # live, the view shows what's been heard, at least this wide
WAVE_H = 180            # the waveform's height; in the big view it takes what there is
_ids = itertools.count(1)
clipboard: np.ndarray | None = None   # Ctrl+C in one card, Ctrl+V in any other
MIME = "application/x-onionboard-clip"   # on the system clipboard while `clipboard` is the copy


def set_clipboard(data: np.ndarray):
    """Copy audio: for any card's editor, and (marked on the system clipboard, so
    the newest copy wins over a picture) for Ctrl+V on the Sounds tab."""
    global clipboard
    clipboard = np.array(data, np.float32)
    md = QMimeData()
    md.setData(MIME, b"1")
    md.setText(_("Onion Board clip ({length})", length=fmt(len(clipboard))))
    try:
        QApplication.clipboard().setMimeData(md)
    except Exception:  # noqa: BLE001 - another program holding the clipboard
        pass


def pasted_clip() -> np.ndarray | None:
    """The copied audio, if it's still what's on the system clipboard."""
    if clipboard is None:
        return None
    md = QApplication.clipboard().mimeData()
    return clipboard if md is not None and md.hasFormat(MIME) else None


def fmt(frames: float) -> str:
    """0:03.25"""
    s = max(frames, 0) / SR
    return f"{int(s // 60)}:{s % 60:05.2f}"


def columns(peaks: np.ndarray, v0: float, v1: float, n: int) -> np.ndarray:
    """One height per pixel column for frames v0..v1 of audio whose BIN-frame
    waveform is `peaks` (0 outside it)."""
    out = np.zeros(max(n, 0), np.float32)
    m = len(peaks)
    if not m or n <= 0 or v1 <= v0:
        return out
    edges = np.floor((v0 + (v1 - v0) * np.arange(n + 1) / n) / BIN).astype(np.int64)
    lo, hi = edges[:-1], np.maximum(edges[1:], edges[:-1] + 1)
    inside = (hi > 0) & (lo < m)
    if not inside.any():
        return out
    idx = np.clip(lo[inside], 0, m - 1)
    end = int(min(max(hi[inside][-1], idx[-1] + 1), m))
    out[inside] = np.maximum.reduceat(peaks[:end], idx)
    return out


def heights(peaks: np.ndarray, half: float) -> np.ndarray:
    """How far each column's line reaches from the middle. On a fixed scale, so Louder,
    Quieter and normalising show, and nothing jumps as a loud bit scrolls by; the square
    root keeps quiet audio readable (-20 dB still reaches a third of the way)."""
    return np.sqrt(np.clip(peaks, 0.0, 1.0)) * half


class ClipWave(QWidget):
    """The waveform: paints what the editor holds and turns the mouse into
    selections. All the state lives in the editor."""

    def __init__(self, editor: ClipEditor):
        super().__init__(editor)
        self.ed = editor
        self.setMinimumHeight(WAVE_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAccessibleName(_("Clip waveform"))
        # no tooltip: it covered the waveform being dragged on (the keys are in the
        # Edit menu and the line under it)
        self.setAccessibleDescription(_("Drag to select. Space plays it, Enter saves it, "
                                        "Ctrl+X / C / V cut, copy and paste, Delete removes "
                                        "it, Ctrl+Z undoes. Ctrl+scroll zooms, Shift+scroll "
                                        "moves."))
        self._anchor: int | None = None
        self._moved = False
        self._press_x = 0.0
        self._edge = False   # the press grabbed a selection's edge: it moves at once

    # ---------------------------------------------------------- mapping
    def _span(self) -> float:
        return max(self.width() - 2 * PAD, 1)

    def x_of(self, frame: float) -> float:
        v0, v1 = self.ed.view
        return PAD + (frame - v0) / max(v1 - v0, 1) * self._span()

    def frame_at(self, x: float) -> int:
        v0, v1 = self.ed.view
        f = v0 + (x - PAD) / self._span() * (v1 - v0)
        return int(min(max(f, 0), self.ed.length()))

    # ---------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        take = self.ed.freeze(keep_view=True)
        if take is None:
            return
        x = e.position().x()
        f = self.frame_at(x)
        self._moved = False
        self._press_x = x
        self._edge = False
        if take.has_selection and abs(x - self.x_of(take.a)) <= EDGE_PX:
            self._anchor = take.b       # drag the start edge
            self._edge = True
        elif take.has_selection and abs(x - self.x_of(take.b)) <= EDGE_PX:
            self._anchor = take.a       # drag the end edge
            self._edge = True
        elif e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._anchor = take.a if abs(f - take.a) > abs(f - take.b) else take.b
            take.select(self._anchor, f)
        else:
            self._anchor = f
            take.select(f, f)
        self.ed.changed_selection()

    def mouseMoveEvent(self, e):
        take = self.ed.take
        if self._anchor is None or take is None:
            x = e.position().x()
            near = (take is not None and take.has_selection
                    and min(abs(x - self.x_of(take.a)), abs(x - self.x_of(take.b))) <= EDGE_PX)
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.IBeamCursor)
            return
        x = e.position().x()
        if not self._edge and not self._moved and abs(x - self._press_x) < DRAG_PX:
            return   # a hand's wobble on a click: still just a cursor
        self._moved = True
        take.select(self._anchor, self.frame_at(x))
        self.ed.changed_selection()

    def mouseReleaseEvent(self, e):
        self._anchor = None
        v0, v1 = self.ed.view
        if self.ed.take is not None and (v0 < 0 or v1 > len(self.ed.take)):
            self.ed.fit()   # just frozen: the empty part of the minute goes (not mid-drag)

    def mouseDoubleClickEvent(self, e):
        if self.ed.take is not None:
            self.ed.take.select_all()
            self.ed.changed_selection()

    def wheelEvent(self, e):
        mods = e.modifiers()
        dy = e.angleDelta().y() or e.angleDelta().x()
        if self.ed.take is None or not dy or not mods & (Qt.KeyboardModifier.ControlModifier
                                                         | Qt.KeyboardModifier.ShiftModifier):
            e.ignore()   # plain scrolling scrolls the list of programs, as everywhere
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.ed.zoom(0.8 if dy > 0 else 1.25, self.frame_at(e.position().x()))
        else:
            v0, v1 = self.ed.view
            self.ed.pan(-(v1 - v0) * 0.15 * (1 if dy > 0 else -1))
        e.accept()

    # ---------------------------------------------------------- keys
    def keyPressEvent(self, e):
        ed, take, k = self.ed, self.ed.take, e.key()
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_Space:
            ed.toggle_play()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            ed.save()
        elif k == Qt.Key.Key_Escape and take is not None and take.has_selection:
            take.select(take.a, take.a)
            ed.changed_selection()
        elif (k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End)
              and take is not None):
            v0, v1 = ed.view
            fast = e.modifiers() & Qt.KeyboardModifier.ControlModifier
            step = max(int((v1 - v0) / 100), 1) * (10 if fast else 1)
            pos = take.b if shift and take.b != take.a else take.a
            pos = {Qt.Key.Key_Left: pos - step, Qt.Key.Key_Right: pos + step,
                   Qt.Key.Key_Home: 0, Qt.Key.Key_End: len(take)}[k]
            if shift:   # grow / shrink the selection's end
                take.select(take.a, pos)
            else:
                take.select(pos, pos)
            ed.changed_selection()
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            ed.zoom(0.8)
        elif k == Qt.Key.Key_Minus:
            ed.zoom(1.25)
        elif k == Qt.Key.Key_0:
            ed.fit()
        elif k == Qt.Key.Key_L:
            ed.go_live()
        else:
            super().keyPressEvent(e)

    # ---------------------------------------------------------- paint
    def paintEvent(self, e):
        T = theme.T
        ed = self.ed
        p = QPainter(self)
        snap_to_pixels(p)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(T["accent"] if self.hasFocus() else T["border"]), 1))
        p.setBrush(QColor(T["bg"]))
        p.drawRoundedRect(r, 6, 6)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        peaks = ed.peaks()
        n = int(self._span())
        mid, half = r.center().y(), r.height() / 2 - 6
        take = ed.take
        sel = take.span() if take is not None and take.has_selection else None
        if sel is not None:
            x0, x1 = self.x_of(sel[0]), self.x_of(sel[1])
            fill = QColor(T["accent"])
            fill.setAlpha(55)
            p.fillRect(QRectF(max(x0, r.left()), r.top() + 1,
                              max(min(x1, r.right()) - max(x0, r.left()), 1), r.height() - 2), fill)
        if len(peaks):
            h = heights(columns(peaks, *ed.view, n), half)
            xs = PAD + np.arange(n) + 0.5
            if sel is not None:
                lit = (xs >= x0) & (xs <= x1)
            else:
                lit = np.ones(n, bool)
            for on, colour in ((False, T["faint"]), (True, T["accent"])):
                pick = (lit == on) & (h > 0)
                if not pick.any():
                    continue
                p.setPen(QPen(QColor(colour), 1))
                p.drawLines([QLineF(x, mid - max(v, 0.5), x, mid + max(v, 0.5))
                             for x, v in zip(xs[pick].tolist(), h[pick].tolist())])
        else:
            p.setPen(QColor(T["muted"]))
            text = _("Listening… the waveform shows once it plays something")
            if ed.take is not None:
                text = _("Empty")
            elif p.fontMetrics().horizontalAdvance(text) > r.width() - 2 * PAD - 8:
                text = _("Listening…")   # a small card: the long line ran off both sides
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        if take is not None and not take.has_selection:   # the cursor: where a paste goes
            x = self.x_of(take.a)
            p.setPen(QPen(QColor(T["text_hi"]), 1, Qt.PenStyle.DashLine))
            p.drawLine(QLineF(x, r.top() + 3, x, r.bottom() - 3))
        play = ed.playhead()
        if play is not None:
            x = self.x_of(play)
            p.setPen(QPen(QColor(T["text_hi"]), 2))
            p.drawLine(QLineF(x, r.top() + 2, x, r.bottom() - 2))
        p.setPen(QColor(T["muted"]))
        f = p.font()
        f.setPointSizeF(max(f.pointSizeF() - 1.5, 7))
        p.setFont(f)
        tr = r.adjusted(6, 2, -6, -2)
        if ed.take is None:
            p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       _("−{seconds}s", seconds=f"{ed.window_s():.0f}"))
            p.drawText(tr, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, _("now ●"))
        else:
            v0, v1 = ed.view
            p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, fmt(max(v0, 0)))
            p.drawText(tr, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                       fmt(min(v1, len(ed.take))))
        p.end()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()


class ClipEditor(QWidget):
    """One card's editor. AppsTab hands it a LiveBuffer (set_buffer) while it's
    open; `save_clip(audio, whole)` asks for the audio to become a sound (`whole`:
    nothing was selected, so dead air at its ends may be trimmed)."""
    save_clip = Signal(object, bool)
    big_toggled = Signal(bool)   # the Big view button: this card takes the whole tab

    def __init__(self, engine, cfg, parent=None):
        super().__init__(parent)
        self.engine, self.cfg = engine, cfg
        n = next(_ids)
        self._preview_sid = f"clipedit{n}:preview"   # ":preview": headphones only
        self.buf: LiveBuffer | None = None
        self.take: Take | None = None
        self._stash: Take | None = None   # the take "Live" left behind (Ctrl+Z brings it back)
        self.view = (0.0, 1.0)
        self._peaks: np.ndarray | None = None   # the take's waveform, made once per edit
        self._live_total = -1
        self._saved_total = -1   # buf.total when all of it was last saved from live
        self._play: tuple[str, int, int] | None = None   # (sid, start, end) while playing
        self._msg = ""
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._clear_msg)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        heading = QHBoxLayout()
        self.state_label = QLabel()
        self.state_label.setObjectName("section")
        heading.addWidget(self.state_label)
        heading.addStretch(1)
        v.addLayout(heading)
        self._copied_from: tuple[int, int, int] | None = None   # (take data id, a, b)
        self.wave = ClipWave(self)
        v.addWidget(self.wave)
        bar = Flow(gap=8)

        def button(text, icon, tip, slot, name=""):
            b = QPushButton(text)
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setAccessibleName(text)
            b.setMinimumSize(CONTROL_H, CONTROL_H)
            b.setProperty("full_text", text)
            icons.set_icon(b, icon, size=18)
            b.clicked.connect(slot)
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            bar.addWidget(b)
            return b

        self.btn_save = button(_("Save to clips"), "plus",
                               _("Keep the selection in Saved clips, under the cards "
                                 "(Enter). From there: play it, name it, or add it to "
                                 "your Sounds."), self.save, "primary")
        self.btn_live = button(_("Pause"), "pause",
                               _("Freeze the waveform to pick a bit out of it "
                                 "(it keeps listening behind). L goes back to live."),
                               self._live_clicked)
        self.btn_play = button(_("Preview"), "play",
                               _("Play the selection in your headphones only (Space)"),
                               self.toggle_play)
        self.btn_edit = button(_("Edit"), "edit",
                               _("Cut, copy, paste, fades, louder / quieter, reverse, undo"),
                               lambda: None)
        self.btn_edit.setMenu(self._make_menu())
        QApplication.clipboard().dataChanged.connect(self._enable_actions)
        self.btn_trim = button(_("Trim"), "edit", _("Keep only the selection"),
                               self.trim)
        self.btn_undo = button(_("Undo"), "back", _("Undo"), self.undo)
        self.btn_big = QPushButton()
        self.btn_big.setFixedSize(CONTROL_H, CONTROL_H)
        self.btn_big.setCheckable(True)
        self.btn_big.setToolTip(_("Big view: this program's editor takes the whole tab"))
        self.btn_big.setAccessibleName(_("Big view"))
        icons.set_icon(self.btn_big, "expand", size=18)
        self.btn_big.toggled.connect(self.big_toggled)
        bar.addWidget(self.btn_big)
        v.addLayout(bar)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setWordWrap(True)   # a long message wraps, never cut off
        self.info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        v.addWidget(self.info)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        appstate.slow_in_background(self, self.timer, TICK_MS)   # 4 a second behind a game
        self._sync()

    # ---------------------------------------------------------- menu
    def _make_menu(self) -> QMenu:
        m = QMenu(self)
        m.setMinimumWidth(280)
        m.setStyleSheet("QMenu::item { padding: 10px 24px; }")
        self.actions_by_name: dict[str, QAction] = {}

        def act(name, text, slot, keys=None, icon=None):
            a = QAction(text, self)
            if keys:
                a.setShortcut(QKeySequence(keys))
                # only while it has focus
                a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self.addAction(a)
            if icon:
                a.setIcon(icons.icon(icon))
            a.triggered.connect(slot)
            m.addAction(a)
            self.actions_by_name[name] = a
            return a

        act("cut", _("Cut"), self.cut, QKeySequence.StandardKey.Cut)
        act("copy", _("Copy"), self.copy, QKeySequence.StandardKey.Copy, "copy")
        act("paste", _("Paste"), self.paste, QKeySequence.StandardKey.Paste)
        act("delete", _("Delete"), lambda: self._edit(Take.delete), QKeySequence.StandardKey.Delete,
            "trash")
        act("crop", _("Keep only the selection"), self.trim, "Ctrl+K")
        act("all", _("Select all"), self.select_all, QKeySequence.StandardKey.SelectAll)
        m.addSeparator()
        act("fade_in", _("Fade in"), lambda: self._edit(Take.fade_in))
        act("fade_out", _("Fade out"), lambda: self._edit(Take.fade_out))
        act("louder", _("Louder (+{db} dB)", db=f"{STEP_DB:g}"),
            lambda: self._edit(lambda t: t.gain(10 ** (STEP_DB / 20))), "Ctrl+Up")
        act("quieter", _("Quieter (−{db} dB)", db=f"{STEP_DB:g}"),
            lambda: self._edit(lambda t: t.gain(10 ** (-STEP_DB / 20))), "Ctrl+Down")
        act("normalize", _("As loud as it goes"), lambda: self._edit(Take.normalize))
        act("reverse", _("Reverse"), lambda: self._edit(Take.reverse))
        act("silence", _("Silence"), lambda: self._edit(Take.silence))
        m.addSeparator()
        act("undo", _("Undo"), self.undo, QKeySequence.StandardKey.Undo)
        act("redo", _("Redo"), self.redo, QKeySequence.StandardKey.Redo)
        act("fit", _("Zoom to fit"), self.fit, "Ctrl+0")
        m.aboutToShow.connect(self._enable_actions)
        return m

    @Slot()
    def _enable_actions(self):
        t = self.take
        sel = t is not None and t.has_selection
        on = {"cut": sel, "copy": sel or self.length() > 0, "paste": clipboard is not None,
              "delete": sel, "crop": sel, "all": self.length() > 0,
              "undo": (t is not None and t.can_undo) or (t is None and self._stash is not None),
              "redo": t is not None and t.can_redo, "fit": t is not None}
        for name, a in self.actions_by_name.items():
            a.setEnabled(on.get(name, self.length() > 0))
        self.btn_edit.setEnabled(any(a.isEnabled() for a in self.actions_by_name.values()))

    # ---------------------------------------------------------- buffer / take
    def set_buffer(self, buf: LiveBuffer | None):
        """Listening (a buffer) or not (None: the card's editor was closed)."""
        self.buf = buf
        self._live_total = -1
        self._saved_total = -1
        if buf is None:
            self.stop_playing()
            if self.take is not None and not self.take.edited:
                self.take = None   # nothing done to it: not worth the memory
            self._stash = None
            self._peaks = None
        self._sync()

    def live_span(self) -> int:
        """Frames the live view spans: what's been heard so far (no empty minute
        waiting to fill), at least LIVE_MIN_S, at most the whole buffer."""
        if self.buf is None:
            return int(LIVE_MIN_S * SR)
        most = self.buf.cols * BIN
        return min(max(self.buf.filled * BIN, int(LIVE_MIN_S * SR)), most)

    def window_s(self) -> float:
        return self.live_span() / SR

    def length(self) -> int:
        if self.take is not None:
            return len(self.take)
        return self.buf.filled * BIN if self.buf is not None else 0

    def peaks(self) -> np.ndarray:
        if self.take is not None:
            if self._peaks is None:
                self._peaks = bin_peaks(self.take.data)
            return self._peaks
        if self.buf is None:
            return np.zeros(0, np.float32)
        wave, _total = self.buf.peaks()
        n = len(wave) * BIN
        self.view = (n - self.live_span(), n)   # live: the window ends at "now"
        return wave

    def freeze(self, keep_view: bool = False) -> Take | None:
        """The take being edited; made from what's been heard if still live (zoomed
        to fit it, or with `keep_view` where it was, as a press on it needs)."""
        if self.take is not None:
            return self.take
        if self.buf is None:
            return None
        data = self.buf.snapshot()
        if not len(data):
            self.flash(_("Nothing heard yet: play something in the program first."))
            return None
        n = len(data)
        self.take = Take(data)
        self.take.select(n, n)
        self._stash = None
        self._peaks = None
        self.view = (float(n - self.live_span()), float(n))   # nothing moves under the mouse
        if not keep_view:
            self.fit()
        self._sync()
        return self.take

    def go_live(self):
        if self.take is None or self.buf is None:
            return
        self.stop_playing()
        if self.take.edited or self.take.has_selection:
            self._stash = self.take
        self.take = None
        self._peaks = None
        if self._stash is not None:
            self.flash(_("Back to live. Ctrl+Z brings back what you had."))
        self._sync()

    def _live_clicked(self):
        if self.take is None:
            # the keys pick from the waveform: Home, Ctrl+Right, Shift+End would
            # otherwise go to this button, which takes none of them
            if self.freeze() is not None:
                self.wave.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.go_live()

    # ---------------------------------------------------------- view
    def _clamp_view(self, v0: float, v1: float):
        n = self.length()
        most = max(n, self.live_span() if self.buf is not None else n, MIN_VIEW)
        span = min(max(v1 - v0, MIN_VIEW), most)
        v0 = min(max(v0, min(0.0, n - span)), max(0.0, n - span))
        self.view = (v0, v0 + span)
        self.wave.update()

    def zoom(self, factor: float, around: float | None = None):
        if self.take is None:
            return
        v0, v1 = self.view
        c = (v0 + v1) / 2 if around is None else around
        self._clamp_view(c - (c - v0) * factor, c + (v1 - c) * factor)

    def pan(self, frames: float):
        if self.take is not None:
            v0, v1 = self.view
            self._clamp_view(v0 + frames, v1 + frames)

    def fit(self):
        if self.take is not None:
            self._clamp_view(0.0, float(max(len(self.take), MIN_VIEW)))

    # ---------------------------------------------------------- edits
    def _edit(self, fn) -> bool:
        take = self.freeze()
        if take is None:
            return False
        self.stop_playing()
        done = fn(take)
        if done:
            self._peaks = None
            v0, v1 = self.view
            self._clamp_view(v0, v1)
        self._sync()
        return bool(done)

    def trim(self) -> bool:
        """Keep only the selection, and show all of what's left: in the live-wide view
        a short bit was a sliver at the left edge."""
        if not self._edit(Take.crop):
            return False
        self.fit()
        return True

    def changed_selection(self):
        self._sync()

    def select_all(self):
        take = self.freeze()
        if take is not None:
            take.select_all()
            self._sync()

    def copy(self) -> bool:
        take = self.freeze()
        if take is None or not len(take):
            return False
        copied = take.selected()
        set_clipboard(copied)
        self._enable_actions()
        self._copied_from = (id(take.data), take.a, take.b) if take.has_selection else None
        if take.has_selection:
            self.say(_("Copied {length}. Ctrl+V pastes it at the cursor, in another "
                         "program's editor, or on the Sounds tab as a new sound.",
                         length=fmt(len(copied))), "ok")
        else:
            self.say(_("Copied all of it ({length}). Ctrl+V pastes it at the cursor, in "
                         "another program's editor, or on the Sounds tab as a new sound.",
                         length=fmt(len(copied))), "ok")
        return True

    def cut(self) -> bool:
        take = self.freeze()
        if take is None or not take.has_selection:
            return False
        self.copy()
        return self._edit(Take.delete)

    def paste(self) -> bool:
        if clipboard is None:
            self.flash(_("Nothing copied yet: select a bit and press Ctrl+C."))
            return False
        piece = clipboard
        take = self.freeze()
        if take is None:
            return False
        if take.has_selection and self._copied_from == (id(take.data), take.a, take.b):
            take.select(take.b, take.b)   # pasted over what was just copied: it'd change
            #                               nothing, so it goes in after it (a copy of it)
        at = take.a
        if not self._edit(lambda t: t.paste(piece)):
            self.say(_("Couldn't paste: the clip can't get any longer."), "warn")
            return False
        self._copied_from = None
        self.say(_("Pasted {length} at {position}: it's {total} long now. Ctrl+Z undoes it.",
                   length=fmt(len(piece)), position=fmt(at), total=fmt(len(take))), "ok")
        return True

    def undo(self):
        if self.take is None and self._stash is not None:
            self.take, self._stash = self._stash, None   # back to the take Live left
            self._peaks = None
            self._sync()
            return
        self._edit(Take.undo)

    def redo(self):
        self._edit(Take.redo)

    # ---------------------------------------------------------- play / save / send
    def _audio(self) -> tuple[np.ndarray, int, bool]:
        """(what Play / Save / Send use, where it starts, whole): the selection; else
        from the cursor on; else all of it."""
        take = self.freeze()
        if take is None:
            return np.zeros((0, 2), np.float32), 0, True
        if take.has_selection:
            return take.data[take.a:take.b], take.a, False
        start = take.a if 0 < take.a < len(take) - SR // 20 else 0
        return take.data[start:], start, start == 0

    def _gain(self, data) -> float:
        return level_gain(data) if getattr(self.cfg, "level_volumes", True) else 1.0

    def toggle_play(self):
        if self._play is not None and self._play[0] == self._preview_sid:
            self.stop_playing()
            return
        self.stop_playing()
        data, start, __ = self._audio()
        if not len(data):
            return
        if self.engine.play(self._preview_sid, data, self._gain(data), mode="restart",
                            preview=True) is None:
            self.say(_("No headphones to play it in: pick them on the Setup tab."), "error")
            return
        self._play = (self._preview_sid, start, start + len(data))
        self._sync()

    def stop_playing(self):
        if self._play is not None:
            self.engine.stop(self._play[0])
            self._play = None
            self._sync()

    def playhead(self) -> float | None:
        if self._play is None:
            return None
        st = self.engine.state(self._play[0])
        if st is None:
            return None
        sid, a, b = self._play
        return a + st[0] * (b - a)

    def save(self):
        buf = self.buf if self.take is None else None   # live
        if buf is not None and buf.total == self._saved_total:   # in Saved clips already
            self.flash(_("Nothing new since the last save: play something in the "
                         "program first."))
            return
        total = buf.total if buf is not None else -1
        data, _start, whole = self._audio()
        if len(data) < int(0.05 * SR):
            self.flash(_("Select a bit to save first.") if self.take is not None
                       else _("Nothing heard yet."))
            return
        if buf is not None and whole:
            self._saved_total = total
        self.save_clip.emit(np.array(data, np.float32), whole)

    def set_big(self, on: bool):
        """The big view (AppsTab sizes the waveform to the room it has)."""
        self.btn_big.blockSignals(True)
        self.btn_big.setChecked(on)
        self.btn_big.blockSignals(False)
        self.btn_big.setToolTip(_("Back to the cards") if on else
                                _("Big view: this program's editor takes the whole tab"))
        if not on:
            self.wave.setMinimumHeight(WAVE_H)

    # ---------------------------------------------------------- state
    def flash(self, text: str, error: bool = False, ms: int = 5000):
        self._msg = text
        theme.set_tone(self.info, "error" if error else "")
        self.info.setText(text)
        self._msg_timer.start(ms)

    def say(self, text: str, kind: str):
        """A result or a problem, as a corner card; hints stay on the line (flash)."""
        busy.toast(self, html.escape(text), kind)

    def _clear_msg(self):
        self._msg = ""
        theme.set_tone(self.info, "")
        self._sync()

    def _sync(self):
        """Buttons, the line under the waveform, the timer."""
        live = self.take is None
        self.state_label.setText(_("Live") if live else _("Edit"))
        self.btn_live.setProperty("full_text", _("Pause") if live else _("Live"))
        icons.set_icon(self.btn_live, "pause" if live else "wave", size=18)
        self.btn_live.setToolTip(_("Freeze the waveform to pick a bit out of it (it keeps "
                                   "listening behind)") if live else
                                 _("Back to the live waveform (L)"))
        self.btn_live.setEnabled(self.buf is not None)
        playing = self._play[0] if self._play is not None else None
        self.btn_play.setProperty("full_text",
                                  _("Stop") if playing == self._preview_sid else _("Preview"))
        icons.set_icon(self.btn_play, "stop" if playing == self._preview_sid else "play", size=18)
        has = self.length() > 0
        for b in (self.btn_play, self.btn_save):
            b.setEnabled(has)
        self._enable_actions()
        self.btn_trim.setEnabled(self.actions_by_name["crop"].isEnabled())
        self.btn_undo.setEnabled(self.actions_by_name["undo"].isEnabled())
        self.btn_live.setAccessibleName(self.btn_live.toolTip())
        self.btn_play.setAccessibleName(self.btn_play.property("full_text"))
        self._label_buttons()
        if not self._msg:
            self.info.setText(self._describe())
        self._run_timer()
        self.wave.update()

    def _describe(self) -> str:
        if self.buf is None and self.take is None:
            return ""
        if self.take is None:
            s = self.buf.seconds if self.buf is not None else 0
            return (_("Live · keeping the last {seconds}s · press on the waveform to pick a bit",
                      seconds=f"{s:.0f}")
                    if s >= 1 else _("Live · waiting for the program to play something"))
        t = self.take
        if t.has_selection:
            return _("{length} selected ({start} – {end}) of {total}", length=fmt(t.b - t.a),
                     start=fmt(t.a), end=fmt(t.b), total=fmt(len(t)))
        return _("{total} · cursor at {position} · drag to select", total=fmt(len(t)),
                 position=fmt(t.a))


    def _label_buttons(self):
        for b in (self.btn_live, self.btn_play, self.btn_save, self.btn_edit,
                  self.btn_trim, self.btn_undo):
            b.setText(b.property("full_text"))
            icons.text_gap(b)

    def minimumSizeHint(self):
        # The toolbar wraps rather than making the card wider.
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), 230), hint.height())

    # ---------------------------------------------------------- the clock
    def _run_timer(self):
        want = self.isVisible() and (
            (self.take is None and self.buf is not None) or self._play is not None)
        if want and not self.timer.isActive():
            self.timer.start(appstate.interval(TICK_MS))
        elif not want and self.timer.isActive():
            self.timer.stop()

    def _tick(self):
        if self._play is not None:
            if self.engine.state(self._play[0]) is None:   # it finished
                self._play = None
                self._sync()
            self.wave.update()
            return
        if self.take is None and self.buf is not None:
            total = self.buf.total
            if total != self._live_total:   # nothing new heard: nothing to redraw
                self._live_total = total
                self.wave.update()
                if self.btn_play.isEnabled() != (self.length() > 0):
                    self._sync()   # the first sound heard: Preview / Save wake up
                elif not self._msg:
                    self.info.setText(self._describe())
        else:
            self._run_timer()

    def showEvent(self, e):
        super().showEvent(e)
        self._run_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def shutdown(self):
        self.stop_playing()
        self.timer.stop()
