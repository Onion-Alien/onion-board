"""Bun mode: the mini player as a little Bun floating over everything.

For people who'd rather have a small mascot on screen than the mini player. The
mini player's Bun button turns the window into him (BunControl.enter_bun_mode);
everything else keeps running as it does with the window in the tray: hotkeys, the
overlay, sounds, downloads.

He shows how the app is doing:

- a sound playing: headphones on, dancing to it (soundboard/audio/groove.py hears its beat
  and guesses its style): headbanging to rock, quick hops to electronic music, a cool
  nod to hip-hop, a slow sway to something calm, talking along to someone speaking;
  notes fly out on the beat, as big as he is
- paused: headphones on, quiet
- nothing playing for a while: bored (BORED_S), then sad (SAD_S); a sound starts and
  he hops for joy
- a download running: off for his hammer and building (BunnyWidget.build), a
  star and a hop when it's done, sad when it failed
- a notice (any toast on the window): he says it in a bubble above his head;
  an error makes him sad, a success makes him hop
- the small hours: asleep in his nightcap, unless something plays

Hovering shows play / pause, stop all, Live, the mic and Back to the board under
him (and for a few seconds as he lands, FIRST_LOOK_MS); Back brings the window back
as it was (the mini player), in front with the keyboard. A click on him only makes
him hop (a mouse that double clicks by itself kept switching back mid-drag). Drag to
move him; the mouse wheel or the corner grip makes him any size from tiny to most of
the screen. Back to the board is only ever on purpose: the button, or the right-click
menu (which also has the full board).

His window never takes focus (a game keeps its keyboard), sits on top, and is see-
through around him, so clicks there go to whatever is underneath. Size and place
are kept in ``cfg.bun`` ({"on", "size", "pos"}); "on" also starts the app as Bun.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMenu, QPushButton, QWidget

from soundboard.ui.kit import theme
from soundboard.audio.groove import Groove
from soundboard.ui.bun.bunny import H, INK, W
from soundboard.i18n import _
from soundboard.ui.kit import a11y, icons
from soundboard.ui.bun.bunnywidget import BUBBLE, BunnyWidget
from soundboard.ui.kit.pixels import snap_to_pixels

MIN_H, START_H = 32, 130   # Bun's own height, px; as big as the screen has room for
FONT_MAX = 16          # the bubble's text stops growing here
STEP = 1.12           # one wheel notch: this much bigger or smaller
ICONS_H = 48          # the row of buttons under him (room kept, shown on hover)
# The row is laid out in steps of 4 px (buttons, icons, gaps, its place in the window):
# at 125 / 150 / 175 % every edge then falls on a whole screen pixel. 30 px buttons with
# 15 px icons put each icon half a pixel off, and it came out soft and jaggy.
SNAP = 4
BUTTON = 32
ICON = 16
GRIP = 16             # the resize corner, at full size; it shrinks with him...
GRIP_MIN = 7          # ...down to this (a 16 px corner beside a tiny Bun looked huge)
MARGIN = 24           # from the screen's edge, where he first lands
RESIZE_REST_MS = 350   # the wheel stopped this long: the buttons come back
HIDE_ICONS_MS = 450   # the mouse left: the buttons go after this
FIRST_LOOK_MS = 4000  # as he lands, his buttons show this long (then on hover)
SAY_MS = {"error": 7000, "warn": 5000, "ok": 3000, "busy": 3000, "": 3500}
SAD_ERROR = 0.85      # how sad an error makes him
SETTLE_MS = 2500      # after a download's star, back to how he was
EDGE = {"error": "#ff4d6d", "warn": "#f5a524", "ok": "#13ce66"}
BORED_S, BORED = 45.0, 0.35   # nothing playing this long: this sad...
SAD_S, LONELY = 150.0, 0.7    # ...and after this long, this sad


class BunMode(QWidget):
    back = Signal()   # clicked: the window as it was
    full = Signal()   # the right-click menu's Open the full board

    def __init__(self, host):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("Onion Board")
        self.setAccessibleName(_("Bun"))
        self.setToolTip(_("Drag: move him. Scroll: bigger or smaller. Hover for the "
                          "buttons."))
        s = self._saved()
        self.bun_h = START_H
        self.bun = BunnyWidget(height=self.bun_h, naps=True, in_background=True, parent=self)
        self.bun.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text, self.kind = "", ""
        self._text_until = 0.0
        self._hover = False
        self._press: QPoint | None = None   # where a left press started (global)
        self._press_h = self.bun_h
        self._pin = QPoint()   # his top-left corner on screen when a press started
        self._moved = False
        self._sizing = False
        self._dl = False
        self._dl_failed = 0
        self._shown: tuple | None = None   # (playing, mic on) the buttons show
        self.groove = Groove()   # the beat and style of what plays (he dances to it)
        self._quiet_since: float | None = None   # nothing playing since then (moods)
        self._build_icons()
        self._hide_icons = QTimer(self, singleShot=True, interval=HIDE_ICONS_MS)
        self._hide_icons.timeout.connect(self._icons_off)
        self._icons_back = QTimer(self, singleShot=True, interval=RESIZE_REST_MS)
        self._icons_back.timeout.connect(lambda: self.icons.setVisible(self._hover))
        self._settle = QTimer(self, singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(self._settled)
        self.bun_h = self._fit(int(s.get("size") or START_H))
        self._lay_out()

    # ------------------------------------------------------------------ parts
    def _saved(self) -> dict:
        if not isinstance(self.host.cfg.bun, dict):
            self.host.cfg.bun = {}
        return self.host.cfg.bun

    def _build_icons(self):
        row = self.icons = QFrame(self)
        row.setObjectName("transport")
        h = QHBoxLayout(row)
        h.setContentsMargins(SNAP, SNAP, SNAP, SNAP)
        h.setSpacing(SNAP)

        def button(name: str, tip: str, fn, checkable: bool = False) -> QPushButton:
            b = QPushButton()
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCheckable(checkable)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.setFixedSize(BUTTON, BUTTON)
            b.clicked.connect(fn)
            icons.set_icon(b, name, size=ICON)
            h.addWidget(b)
            return b
        mw = self.host
        self.b_play = button("play", _("Play / pause"), mw.playctl.toggle_play_pause)
        self.b_stop = button("stop", _("Stop all sounds"), mw.playctl.stop_all)
        self.b_air = button("live", mw.btn_air.toolTip(), lambda: mw.mini_air.click(), True)
        self.b_air.setObjectName("onair")
        icons.set_icon(self.b_air, "live", "danger_text", "on_live", size=ICON)
        self.b_mic = button("mic", mw.mini_mic.toolTip(), lambda: mw.mini_mic.click(), True)
        h.addSpacing(SNAP)   # apart from the sound buttons: it changes the view, not the sound
        # (the board's grid icon blurred into a blob at this size: the corners are clean)
        self.b_back = button("expand", _("Back to the board"), self.back.emit)
        self.b_back.setObjectName("primary")
        icons.set_icon(self.b_back, "expand", "on_accent", size=ICON)
        self.retheme()
        row.adjustSize()
        row.hide()

    def retheme(self):
        """The button row in this theme's colours (ThemeControl._apply_theme). Each button
        carries every state itself: a rule shared from the row lost the plain buttons'
        fill, and Live and the mic, lit up, only went a shade lighter on hover. Now a
        hover is a clear outline in every state."""
        t = theme.T
        edge = t["text"] if theme.current_name == "High Contrast" else "transparent"
        ring = t["text_hi"]
        # some themes give the player bar a 1 px top edge: it pushed every button in
        # here a pixel down, off the 4 px grid
        self.icons.setStyleSheet("QFrame#transport { border:none; }")
        shape = f"border:1px solid {edge}; border-radius:8px; padding:0;"
        plain = (f"QPushButton {{ background:{t['btn']}; {shape} }}"
                 f"QPushButton:hover {{ background:{t['btn_hover']}; border-color:{ring}; }}"
                 f"QPushButton:pressed {{ background:{t['btn_press']}; }}"
                 f"QPushButton:checked {{ background:{theme.accent_fill()}; "
                 f"border-color:{t['accent']}; }}"
                 f"QPushButton:checked:hover {{ background:{theme.accent_fill(hover=True)}; "
                 f"border-color:{ring}; }}")
        for b in (self.b_play, self.b_stop, self.b_mic):
            b.setStyleSheet(plain)
        # (Live's pill radius, 15, is over half this height: Qt then drew it square)
        self.b_air.setStyleSheet(
            f"QPushButton#onair {{ background:{t['danger_bg']}; {shape} }}"
            f"QPushButton#onair:hover {{ border-color:{ring}; }}"
            f"QPushButton#onair:checked {{ background:{t['live']}; border-color:{t['live']}; }}"
            f"QPushButton#onair:checked:hover {{ background:{t['live_hover']}; "
            f"border-color:{ring}; }}")
        # the main-action style's lighter top edge (accent_rim) showed as a ragged line
        # of white pixels along the top at this size: one even edge all round instead
        rim = t.get("accent_rim_side") or t["accent"]
        self.b_back.setStyleSheet(
            f"QPushButton#primary {{ border:1px solid {rim}; border-radius:8px; padding:0; }}"
            f"QPushButton#primary:hover {{ border-color:{ring}; }}"
            f"QPushButton#primary:pressed {{ border-color:{rim}; }}")

    def _lay_out(self, pin: QPoint | None = None):
        """Size the window round Bun at bun_h, in one step (resized, then moved after,
        the button row jumped about mid-resize). `pin`: the screen spot his own top-left
        corner stays on while his corner grip is dragged, so only his size follows the
        mouse; otherwise (the wheel) his feet stay where they were."""
        shown = self.isVisible()
        feet = self._feet() if shown else None
        h = self.bun_h
        self.bun.bun_h = h
        self.bun.pad = round(h * 0.12)
        bw, bh = self.bun.sizeHint().width(), self.bun.sizeHint().height()
        hint = self.icons.sizeHint()   # its whole height: shorter cut the buttons off
        w = max(bw, min(round(h * 1.5), 300), hint.width() + 8, 200)
        w += -w % (2 * SNAP)   # the button row then centres on the 4 px grid by itself
        total = self._talk_h() + bh + ICONS_H
        total += -total % SNAP
        talk = total - bh - ICONS_H   # (the rounding goes to the bubble's room)
        self.bun.setGeometry((w - bw) // 2, talk, bw, bh)
        self.icons.setGeometry((w - hint.width()) // 2 // SNAP * SNAP,
                               (total - ICONS_H + (ICONS_H - hint.height()) // 2) // SNAP * SNAP,
                               hint.width(), hint.height())
        if not shown:
            self.resize(w, total)
        else:
            if pin is not None or feet is None:
                corner = self.bun.pos() + self.bun._bun_rect().topLeft().toPoint()
                top_left = (pin if pin is not None else self._bun_corner()) - corner
            else:
                top_left = feet - QPoint(w // 2, talk + bh)
            self.setGeometry(QRect(top_left, QSize(w, total)))
            if pin is None:
                self._keep_on_screen()
        self.update()

    def _bun_corner(self) -> QPoint:
        """His own top-left corner, on screen."""
        return self.mapToGlobal(self.bun.pos() + self.bun._bun_rect().topLeft().toPoint())

    def _talk_h(self) -> int:
        """Room above his head for the speech bubble (three lines)."""
        return 3 * self._font().pixelSize() + 14

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(max(11, min(FONT_MAX, round(self.bun_h * 0.07))))
        f.setBold(True)
        return f

    def _feet(self) -> QPoint:
        g = self.geometry()
        b = self.bun.geometry()
        return QPoint(g.x() + g.width() // 2, g.y() + b.bottom() + 1)

    def _bun_rect(self) -> QRect:
        """Bun himself (no room around him), in window pixels: what the grip sits on."""
        r = self.bun._bun_rect().toRect()
        return r.translated(self.bun.pos())

    def _grip(self) -> QRect:
        r = self._bun_rect()
        g = max(GRIP_MIN, min(GRIP, round(self.bun_h * 0.13)))
        return QRect(r.right() - g // 2, r.bottom() - g, g + 4, g + 4)

    # ------------------------------------------------------------------ show
    def present(self, near: QRect | None = None):
        """Up on screen: Bun himself centred on `near` (the window he came from, so he
        turns up right where it was), else where he was last, else the main screen's
        bottom-right corner."""
        self._lay_out()
        pos = self._saved().get("pos")
        if near is not None:
            self.move(near.center() - self._bun_rect().center())
        elif isinstance(pos, (list, tuple)) and len(pos) == 2 and self._on_a_screen(
                QPoint(int(pos[0]), int(pos[1]))):
            self.move(int(pos[0]), int(pos[1]))
        else:
            room = QGuiApplication.primaryScreen().availableGeometry()
            self.move(room.bottomRight() - QPoint(self.width() + MARGIN, self.height() + MARGIN))
        self._keep_on_screen()
        self.show()
        self.raise_()
        # his buttons for a moment as he lands, so the way back is seen once even by
        # someone who doesn't know to hover; then they come with the mouse
        self.icons.show()
        QTimer.singleShot(FIRST_LOOK_MS, self, self._first_look_over)

    def _first_look_over(self):
        if not self._hover and self._press is None:
            self.icons.hide()

    def _on_a_screen(self, top_left: QPoint) -> bool:
        spot = top_left + QPoint(self.width() // 2, self.height() // 2)
        return QGuiApplication.screenAt(spot) is not None

    def _keep_on_screen(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or \
            QGuiApplication.primaryScreen()
        room = screen.availableGeometry()
        x = min(max(self.x(), room.left()), room.right() + 1 - self.width())
        y = min(max(self.y(), room.top()), room.bottom() + 1 - self.height())
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _remember(self):
        s = self._saved()
        s["size"] = self.bun_h
        s["pos"] = [self.x(), self.y()]
        self.host._save_later()

    def max_h(self) -> int:
        """The biggest he goes: his window (bubble, Bun, buttons) still fits the screen."""
        screen = (QGuiApplication.screenAt(self.geometry().center()) if self.isVisible()
                  else None)
        room = (screen or QGuiApplication.primaryScreen()).availableGeometry().height()
        return max(MIN_H, int((room - 3 * FONT_MAX - 14 - ICONS_H - 8) / 1.25))

    def _fit(self, h: int) -> int:
        return max(MIN_H, min(self.max_h(), int(h)))

    def set_size(self, h: int, pin: QPoint | None = None):
        """Any size from MIN_H to the screen's height: past either end it just stops."""
        h = self._fit(h)
        if h != self.bun_h:
            self.bun_h = h
            self._lay_out(pin)

    # ------------------------------------------------------------------ status
    def tick(self, *, live: bool, paused: bool, level: float, sending: bool, mic: bool,
             downloading: bool, failed: int, song: tuple | None = None):
        """The app's state, from TickControl.tick (a few times a second or more).
        `song`: (samples, 0..1 position) of the sound playing, which he dances to."""
        b = self.bun
        now = time.monotonic()
        if live and song is not None and song[0] is not None:
            self.groove.feed(song[0], song[1], now)
            b.set_groove(self.groove)
            b.set_level(0.0)
        else:   # (nothing to read: the level alone, as before)
            b.set_groove(None)
            b.set_level(level if live else 0.0)
        b.naps = not (live or downloading)
        if downloading and not self._dl:
            self._settle.stop()
            self._dl_failed = failed
            b.build()
        elif not downloading and self._dl:
            b.stop_building(failed <= self._dl_failed)
            self._settle.start()
        self._dl = downloading
        if not b.building and not self._settle.isActive():
            b.prop = "headphones" if (live or paused) else None
        mood = self._mood(now, live, paused or downloading or b.building)
        if self.text and now >= self._text_until:
            self.text = ""
            self.update()
        if not b.building and not self._settle.isActive():
            b.sad = SAD_ERROR if self.text and self.kind == "error" else mood
        if self._shown != (live, mic):
            self._shown = (live, mic)
            icons.set_icon(self.b_play, "pause" if live else "play", size=ICON)
            icons.set_icon(self.b_mic, "mic" if mic else "mic_off", size=ICON)
        if self.b_air.isChecked() != sending:
            self.b_air.setChecked(sending)
        if self.b_mic.isChecked() != mic:
            self.b_mic.setChecked(mic)

    def _mood(self, now: float, live: bool, busy: bool) -> float:
        """How sad nothing playing has made him: bored after BORED_S, sad after SAD_S.
        Music again after he got bored: a hop for joy."""
        if live or busy:
            if live and self._quiet_since is not None and now - self._quiet_since >= BORED_S:
                self.bun.cheer()
            self._quiet_since = None
            return 0.0
        if self._quiet_since is None:
            self._quiet_since = now
        quiet = now - self._quiet_since
        return LONELY if quiet >= SAD_S else BORED if quiet >= BORED_S else 0.0

    def _settled(self):
        self._settle.stop()
        b = self.bun
        b.prop, b.celebrate, b.sad = None, False, 0.0

    def say(self, text: str, kind: str = ""):
        """A notice from the window (any toast): in his bubble for a few seconds."""
        text = a11y.plain(text)
        if not text:
            return
        self.text, self.kind = text, kind if kind in SAY_MS else ""
        self._text_until = time.monotonic() + SAY_MS[self.kind] / 1000
        if self.kind == "ok":
            self.bun.cheer()
        elif self.kind == "error":
            self.bun.sad = SAD_ERROR
        self.update()

    # ------------------------------------------------------------------ mouse
    def enterEvent(self, e):
        self._hide_icons.stop()
        if not self._hover:
            self._hover = True
            self.icons.show()
            self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._press is None:
            self._hide_icons.start()
        super().leaveEvent(e)

    def _icons_off(self):
        self._hover = False
        self.icons.hide()
        self.unsetCursor()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._press_pos = self.pos()
            self._press_h = self.bun_h
            self._moved = False
            self._sizing = self._grip().contains(e.position().toPoint())
            self._pin = self._bun_corner()
            if self._sizing:   # it'd only jump about while he changes size
                self.icons.hide()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None:
            over = self._grip().contains(e.position().toPoint()) and self._hover
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if over
                           else Qt.CursorShape.PointingHandCursor)
            return
        d = e.globalPosition().toPoint() - self._press
        if not self._moved and d.manhattanLength() < QApplication.startDragDistance():
            return
        self._moved = True
        if self._sizing:
            # the grip follows the mouse: whichever way it went further (his width is
            # W / H of his height); his top-left corner stays put, he never moves
            self.set_size(round(self._press_h + max(d.y(), d.x() * H / W)), self._pin)
        else:
            self.move(self._press_pos + d)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return super().mouseReleaseEvent(e)
        self._press = None
        if self._sizing and self._hover:
            self.icons.show()
        if self._moved:
            self._keep_on_screen()
            self._remember()
        else:   # a click (or a mouse's stray double click) only makes him hop:
            self.bun.cheer()   # switching back is the button's job, so dragging is safe

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        grown = round(self.bun_h * STEP ** steps)
        if grown == self.bun_h:   # tiny: a notch still moves him a pixel
            grown += 1 if steps > 0 else -1
        self.icons.hide()   # back once the wheel stops: it'd only jump about meanwhile
        self._icons_back.start()
        self.set_size(grown)
        self._remember()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        icons.set_icon(menu.addAction(_("Back to the board"), self.back.emit), "expand")
        icons.set_icon(menu.addAction(_("Open the full board"), self.full.emit), "sounds")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("Stop all sounds"), self.host.playctl.stop_all), "stop")
        icons.set_icon(menu.addAction(_("Settings"), lambda: self.host.setctl.open_settings()),
                       "settings")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("Quit"), self.host.quit_app), "stop")
        menu.popup(e.globalPos())

    # ------------------------------------------------------------------ paint
    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            # all but invisible, but Windows only sends a see-through window the
            # clicks that land on something drawn: this keeps the buttons and the grip
            # reachable once the mouse is over him
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))
            self._paint_grip(p)
        if self.text:
            self._bubble(p)
        p.end()

    def _paint_grip(self, p: QPainter):
        r = QRectF(self._grip())
        pen = QPen(QColor(theme.T["text_hi"]), 1.6 if r.width() >= 14 else 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for k in (0.35, 0.65, 0.95):
            p.drawLine(QPointF(r.right() - r.width() * k, r.bottom() - 2),
                       QPointF(r.right() - 2, r.bottom() - r.height() * k))

    def _bubble(self, p: QPainter):
        f = self._font()
        p.setFont(f)
        fm = QFontMetrics(f)
        pad = 7
        width = self.width() - 8 - 2 * pad
        flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter
        lines = 3
        box_h = fm.lineSpacing() * lines
        text = self.text
        need = fm.boundingRect(QRect(0, 0, width, 10_000), flags, text)
        if need.height() > box_h:   # too long: as much as fits, then …
            while text and fm.boundingRect(QRect(0, 0, width, 10_000), flags,
                                           text + "…").height() > box_h:
                text = text[:-max(1, len(text) // 12)].rstrip()
            text += "…"
            need = fm.boundingRect(QRect(0, 0, width, 10_000), flags, text)
        bw, bh = need.width() + 2 * pad + 2, need.height() + 2 * pad - 2
        head = self._bun_rect()
        bottom = head.top() + 2
        box = QRectF((self.width() - bw) / 2, max(2.0, bottom - bh - 8), bw, bh)
        tip = QPointF(head.center().x() + head.width() * 0.12, head.top() + head.height() * 0.2)
        tail = QPainterPath(QPointF(box.center().x() - 6, box.bottom() - 2))
        tail.lineTo(tip)
        tail.lineTo(box.center().x() + 8, box.bottom() - 2)
        shape = QPainterPath()
        shape.addRoundedRect(box, min(12.0, bh / 2), min(12.0, bh / 2))
        shape = shape.united(tail)
        edge = QColor(EDGE.get(self.kind, INK.name()))
        p.setPen(QPen(edge, 2.2 if self.kind in EDGE else 1.6))
        p.setBrush(BUBBLE)
        p.drawPath(shape)
        p.setPen(INK)
        p.drawText(box.adjusted(pad, pad - 1, -pad, -pad + 1), flags, text)

    def sizeHint(self) -> QSize:
        return self.size()
