"""The Apps tab's clip editor: a program's last minute as a live waveform, to
drag across, play, cut up and save as a sound or send straight back out.

It's opt-in and folded away: a card builds one only when its *Clip editor* is
opened, and nothing listens, keeps audio or draws while it's closed. Live, the
waveform scrolls (newest on the right). The first press on it freezes what's
there into a take to edit (soundboard.clipedit.Take); the program keeps being
kept behind it, and **Live** goes back. Drag selects; Space plays the selection
in your headphones; Ctrl+X / C / V, Delete, Ctrl+Z work as in any editor; Enter
keeps it in the tab's Saved clips (soundboard.ui.clipshelf) and **Send** plays it
to whoever's listening. A copied bit also marks the system clipboard (MIME), so
Ctrl+V on the Sounds tab adds it as a sound."""
from __future__ import annotations

import itertools

import numpy as np
from PySide6.QtCore import QLineF, QMimeData, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.clipedit import BIN, LiveBuffer, Take, bin_peaks
from soundboard.engine import SR
from soundboard.library import level_gain
from soundboard.ui import appstate, icons

PAD = 4                 # the waveform's inner margin, px
EDGE_PX = 6             # how close to a selection edge a press grabs it
TICK_MS = 50            # redraw pace while live or playing (20 a second)
MIN_VIEW = 256          # frames: the furthest it zooms in
STEP_DB = 3.0           # Louder / Quieter
NARROW_PX = 380         # below this the buttons keep only their icons
LIVE_MIN_S = 10         # live, the view shows what's been heard, at least this wide
WAVE_H = 84             # the waveform's height; in the big view it takes what there is
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
    md.setText(f"Onion Board clip ({fmt(len(clipboard))})")
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


class ClipWave(QWidget):
    """The waveform: paints what the editor holds and turns the mouse into
    selections. All the state lives in the editor."""

    def __init__(self, editor: ClipEditor):
        super().__init__(editor)
        self.ed = editor
        self.setMinimumHeight(WAVE_H)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.IBeamCursor)
        self.setAccessibleName("Clip waveform")
        self.setToolTip("Drag to select. Space plays it, Enter saves it, Ctrl+X / C / V "
                        "cut, copy and paste, Delete removes it, Ctrl+Z undoes. "
                        "Ctrl+scroll zooms, Shift+scroll moves.")
        self._anchor: int | None = None
        self._moved = False

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
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        self.setFocus(Qt.MouseFocusReason)
        take = self.ed.freeze(keep_view=True)
        if take is None:
            return
        x = e.position().x()
        f = self.frame_at(x)
        self._moved = False
        if take.has_selection and abs(x - self.x_of(take.a)) <= EDGE_PX:
            self._anchor = take.b       # drag the start edge
        elif take.has_selection and abs(x - self.x_of(take.b)) <= EDGE_PX:
            self._anchor = take.a       # drag the end edge
        elif e.modifiers() & Qt.ShiftModifier:
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
            self.setCursor(Qt.SizeHorCursor if near else Qt.IBeamCursor)
            return
        self._moved = True
        take.select(self._anchor, self.frame_at(e.position().x()))
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
        if self.ed.take is None or not dy or not mods & (Qt.ControlModifier | Qt.ShiftModifier):
            e.ignore()   # plain scrolling scrolls the list of programs, as everywhere
            return
        if mods & Qt.ControlModifier:
            self.ed.zoom(0.8 if dy > 0 else 1.25, self.frame_at(e.position().x()))
        else:
            v0, v1 = self.ed.view
            self.ed.pan(-(v1 - v0) * 0.15 * (1 if dy > 0 else -1))
        e.accept()

    # ---------------------------------------------------------- keys
    def keyPressEvent(self, e):
        ed, take, k = self.ed, self.ed.take, e.key()
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        if k == Qt.Key_Space:
            ed.toggle_play()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            ed.save()
        elif k == Qt.Key_Escape and take is not None and take.has_selection:
            take.select(take.a, take.a)
            ed.changed_selection()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End) and take is not None:
            v0, v1 = ed.view
            step = max(int((v1 - v0) / 100), 1) * (10 if e.modifiers() & Qt.ControlModifier else 1)
            pos = take.b if shift and take.b != take.a else take.a
            pos = {Qt.Key_Left: pos - step, Qt.Key_Right: pos + step,
                   Qt.Key_Home: 0, Qt.Key_End: len(take)}[k]
            if shift:   # grow / shrink the selection's end
                take.select(take.a, pos)
            else:
                take.select(pos, pos)
            ed.changed_selection()
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            ed.zoom(0.8)
        elif k == Qt.Key_Minus:
            ed.zoom(1.25)
        elif k == Qt.Key_0:
            ed.fit()
        elif k == Qt.Key_L:
            ed.go_live()
        else:
            super().keyPressEvent(e)

    # ---------------------------------------------------------- paint
    def paintEvent(self, e):
        T = theme.T
        ed = self.ed
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(T["accent"] if self.hasFocus() else T["border"]), 1))
        p.setBrush(QColor(T["bg"]))
        p.drawRoundedRect(r, 6, 6)
        p.setRenderHint(QPainter.Antialiasing, False)
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
            h = columns(peaks, *ed.view, n) * half
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
            p.drawText(r, Qt.AlignCenter, "Listening… the waveform shows once it plays something"
                       if ed.take is None else "Empty")
        if take is not None and not take.has_selection:   # the cursor: where a paste goes
            x = self.x_of(take.a)
            p.setPen(QPen(QColor(T["text_hi"]), 1, Qt.DashLine))
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
            p.drawText(tr, Qt.AlignLeft | Qt.AlignTop, f"−{ed.window_s():.0f}s")
            p.drawText(tr, Qt.AlignRight | Qt.AlignTop, "now ●")
        else:
            v0, v1 = ed.view
            p.drawText(tr, Qt.AlignLeft | Qt.AlignTop, fmt(max(v0, 0)))
            p.drawText(tr, Qt.AlignRight | Qt.AlignTop, fmt(min(v1, len(ed.take))))
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
        self._send_sid = f"clipedit{n}-send"
        self.buf: LiveBuffer | None = None
        self.take: Take | None = None
        self._stash: Take | None = None   # the take "Live" left behind (Ctrl+Z brings it back)
        self.view = (0.0, 1.0)
        self._peaks: np.ndarray | None = None   # the take's waveform, made once per edit
        self._live_total = -1
        self._play: tuple[str, int, int] | None = None   # (sid, start, end) while playing
        self._msg = ""
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._clear_msg)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.wave = ClipWave(self)
        v.addWidget(self.wave)
        bar = QHBoxLayout()
        bar.setSpacing(6)

        def button(text, icon, tip, slot, name="small"):
            b = QPushButton(text)
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setProperty("full_text", text)
            icons.set_icon(b, icon, size=13)
            b.clicked.connect(slot)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            bar.addWidget(b)
            return b

        self.btn_live = button("Pause", "pause", "Freeze the waveform to pick a bit out of it "
                               "(it keeps listening behind). L goes back to live.",
                               self._live_clicked)
        self.btn_play = button("Play", "play", "Play the selection in your headphones only "
                               "(Space)", self.toggle_play)
        self.btn_save = button("Save clip", "plus", "Keep the selection in Saved clips, "
                               "under the cards (Enter). From there: play it, name it, or "
                               "add it to your Sounds.", self.save)
        self.btn_send = button("Send", "live", "Play the selection to whoever's listening, "
                               "right now, without saving it", self.toggle_send)
        self.btn_edit = button("Edit", "edit", "Cut, copy, paste, fades, louder / quieter, "
                               "reverse, undo", lambda: None)
        self.btn_edit.setMenu(self._make_menu())
        bar.addStretch(1)
        self.btn_big = QPushButton()
        self.btn_big.setObjectName("small")
        self.btn_big.setCheckable(True)
        self.btn_big.setToolTip("Big view: this program's editor takes the whole tab")
        self.btn_big.setAccessibleName("Big view")
        icons.set_icon(self.btn_big, "expand", size=13)
        self.btn_big.toggled.connect(self.big_toggled)
        bar.addWidget(self.btn_big)
        v.addLayout(bar)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setTextFormat(Qt.PlainText)
        self.info.setWordWrap(True)   # a long message wraps, never cut off
        self.info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.info)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        appstate.slow_in_background(self, self.timer, TICK_MS)   # 4 a second behind a game
        self._sync()

    # ---------------------------------------------------------- menu
    def _make_menu(self) -> QMenu:
        m = QMenu(self)
        self.actions_by_name: dict[str, QAction] = {}

        def act(name, text, slot, keys=None, icon=None):
            a = QAction(text, self)
            if keys:
                a.setShortcut(QKeySequence(keys))
                a.setShortcutContext(Qt.WidgetWithChildrenShortcut)   # only while it has focus
                self.addAction(a)
            if icon:
                a.setIcon(icons.icon(icon))
            a.triggered.connect(slot)
            m.addAction(a)
            self.actions_by_name[name] = a
            return a

        act("cut", "Cut", self.cut, QKeySequence.Cut)
        act("copy", "Copy", self.copy, QKeySequence.Copy, "copy")
        act("paste", "Paste", self.paste, QKeySequence.Paste)
        act("delete", "Delete", lambda: self._edit(Take.delete), QKeySequence.Delete, "trash")
        act("crop", "Keep only the selection", lambda: self._edit(Take.crop), "Ctrl+K")
        act("all", "Select all", self.select_all, QKeySequence.SelectAll)
        m.addSeparator()
        act("fade_in", "Fade in", lambda: self._edit(Take.fade_in))
        act("fade_out", "Fade out", lambda: self._edit(Take.fade_out))
        act("louder", f"Louder (+{STEP_DB:g} dB)",
            lambda: self._edit(lambda t: t.gain(10 ** (STEP_DB / 20))), "Ctrl+Up")
        act("quieter", f"Quieter (−{STEP_DB:g} dB)",
            lambda: self._edit(lambda t: t.gain(10 ** (-STEP_DB / 20))), "Ctrl+Down")
        act("normalize", "As loud as it goes", lambda: self._edit(Take.normalize))
        act("reverse", "Reverse", lambda: self._edit(Take.reverse))
        act("silence", "Silence", lambda: self._edit(Take.silence))
        m.addSeparator()
        act("undo", "Undo", self.undo, QKeySequence.Undo)
        act("redo", "Redo", self.redo, QKeySequence.Redo)
        act("fit", "Zoom to fit", self.fit, "Ctrl+0")
        m.aboutToShow.connect(self._enable_actions)
        return m

    def _enable_actions(self):
        t = self.take
        sel = t is not None and t.has_selection
        on = {"cut": sel, "copy": sel or self.length() > 0, "paste": clipboard is not None,
              "delete": sel, "crop": sel, "all": self.length() > 0,
              "undo": (t is not None and t.can_undo) or (t is None and self._stash is not None),
              "redo": t is not None and t.can_redo, "fit": t is not None}
        for name, a in self.actions_by_name.items():
            a.setEnabled(on.get(name, self.length() > 0))

    # ---------------------------------------------------------- buffer / take
    def set_buffer(self, buf: LiveBuffer | None):
        """Listening (a buffer) or not (None: the card's editor was closed)."""
        self.buf = buf
        self._live_total = -1
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
            self.flash("Nothing heard yet: play something in the program first.")
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
            self.flash("Back to live. Ctrl+Z brings back what you had.")
        self._sync()

    def _live_clicked(self):
        if self.take is None:
            self.freeze()
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
        set_clipboard(take.selected())
        self.flash(f"Copied {fmt(len(clipboard))}. Ctrl+V pastes it here, in another "
                   "program's editor, or on the Sounds tab as a new sound.")
        return True

    def cut(self) -> bool:
        take = self.freeze()
        if take is None or not take.has_selection:
            return False
        self.copy()
        return self._edit(Take.delete)

    def paste(self) -> bool:
        if clipboard is None:
            self.flash("Nothing copied yet: select a bit and press Ctrl+C.")
            return False
        piece = clipboard
        return self._edit(lambda t: t.paste(piece))

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
        data, start, _ = self._audio()
        if not len(data):
            return
        if self.engine.play(self._preview_sid, data, self._gain(data), mode="restart",
                            preview=True) is None:
            self.flash("No headphones to play it in: pick them on the Setup tab.", error=True)
            return
        self._play = (self._preview_sid, start, start + len(data))
        self._sync()

    def toggle_send(self):
        if self._play is not None and self._play[0] == self._send_sid:
            self.stop_playing()
            return
        self.stop_playing()
        data, start, _ = self._audio()
        if not len(data):
            return
        if self.engine.play(self._send_sid, data, self._gain(data), mode="restart") is None:
            self.flash("Nowhere to send it: pick where your sounds go on the Setup tab.",
                       error=True)
            return
        self._play = (self._send_sid, start, start + len(data))
        self.flash(f"Sending {fmt(len(data))}…")
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
        data, _start, whole = self._audio()
        if len(data) < int(0.05 * SR):
            self.flash("Select a bit to save first." if self.take is not None
                       else "Nothing heard yet.")
            return
        self.save_clip.emit(np.array(data, np.float32), whole)

    def set_big(self, on: bool):
        """The big view (AppsTab sizes the waveform to the room it has)."""
        self.btn_big.blockSignals(True)
        self.btn_big.setChecked(on)
        self.btn_big.blockSignals(False)
        self.btn_big.setToolTip("Back to the cards" if on else
                                "Big view: this program's editor takes the whole tab")
        if not on:
            self.wave.setMinimumHeight(WAVE_H)

    # ---------------------------------------------------------- state
    def flash(self, text: str, error: bool = False, ms: int = 5000):
        self._msg = text
        theme.set_tone(self.info, "error" if error else "")
        self.info.setText(text)
        self._msg_timer.start(ms)

    def _clear_msg(self):
        self._msg = ""
        theme.set_tone(self.info, "")
        self._sync()

    def _sync(self):
        """Buttons, the line under the waveform, the timer."""
        live = self.take is None
        self.btn_live.setProperty("full_text", "Pause" if live else "Live")
        icons.set_icon(self.btn_live, "pause" if live else "wave", size=13)
        self.btn_live.setToolTip("Freeze the waveform to pick a bit out of it (it keeps "
                                 "listening behind)" if live else
                                 "Back to the live waveform (L)")
        self.btn_live.setEnabled(self.buf is not None)
        playing = self._play[0] if self._play is not None else None
        self.btn_play.setProperty("full_text", "Stop" if playing == self._preview_sid else "Play")
        icons.set_icon(self.btn_play, "stop" if playing == self._preview_sid else "play", size=13)
        self.btn_send.setProperty("full_text", "Stop" if playing == self._send_sid else "Send")
        has = self.length() > 0
        for b in (self.btn_play, self.btn_save, self.btn_send):
            b.setEnabled(has)
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
            return (f"Live · keeping the last {s:.0f}s · press on the waveform to pick a bit"
                    if s >= 1 else "Live · waiting for the program to play something")
        t = self.take
        if t.has_selection:
            return f"{fmt(t.b - t.a)} selected ({fmt(t.a)} – {fmt(t.b)}) of {fmt(len(t))}"
        return f"{fmt(len(t))} · cursor at {fmt(t.a)} · drag to select"

    def _label_buttons(self):
        narrow = self.width() < NARROW_PX
        for b in (self.btn_live, self.btn_play, self.btn_save, self.btn_send, self.btn_edit):
            b.setText("" if narrow else b.property("full_text"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self._label_buttons()

    def minimumSizeHint(self):
        # the buttons' icons alone: with their words it would ask the card to be wider
        # and squeeze the rest of it (AppRow._fit_width), when they'd just drop the words
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
                    self._sync()   # the first sound heard: Play / Save / Send wake up
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
        self.engine.forget(self._send_sid)
