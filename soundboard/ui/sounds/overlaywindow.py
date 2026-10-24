"""The in-game overlay's window (`OverlayWindow`, ui/sounds/overlay.py has how it works): the
tiles, the page and category buttons, dragging it, fading in and out, following the game's
monitor and painting it in cached layers. `overlay` re-exports it."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from soundboard.control import winkeys
from soundboard.i18n import _
from soundboard.ui.kit import theme
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import lite
from soundboard.ui.sounds.overlaysettings import (
    DRAG_START_PX,
    MONITOR_GAME,
    MONITOR_PRIMARY,
    SLOTS,
    find_screen,
    key_label,
    pick_screen,
    place,
)

if TYPE_CHECKING:
    from soundboard.ui.sounds.overlay import Overlay


class _AnyInput(QObject):
    """Calls `done` on the first click or key press anywhere in the app."""

    def __init__(self, done):
        super().__init__()
        self._done = done

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            QTimer.singleShot(0, self._done)   # not from inside the event's delivery
        return False


class OverlayWindow(QWidget):
    """The HUD itself: frameless, see-through, always on top and never focused. It
    takes clicks (a tile plays, the footer buttons pause / stop), but clicking it
    never activates it, so the game keeps the keyboard."""
    TILE_W, TILE_H, GAP, PAD, HEAD, FOOT = 138, 70, 8, 14, 30, 34
    BTN_W, BTN_H = 100, 22
    MARGIN = 36   # from the screen edge

    def __init__(self, ov: Overlay):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.ov = ov
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(_("Onion Board overlay"))
        self.playing: dict = {}
        self._hover: str | None = None     # "slot:N" / "pause" / "stop" under the mouse
        self.setMouseTracking(True)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._faded)
        self._styled = False
        self._press: QPoint | None = None     # where a press on an empty part was
        self._grab: QPoint | None = None      # while dragging: that point − window pos
        self._placed_on = None                # the screen present() put it on
        self._cache_key: tuple | None = None  # what the cached layers were drawn from
        self._layers: tuple[QPixmap, QPixmap] | None = None

    # ------------------------------------------------------------------ geometry
    def _k(self) -> float:
        return self.ov.s.scale / 100

    def sizeHint(self):
        k = self._k()
        w = 2 * self.PAD + 3 * self.TILE_W + 2 * self.GAP
        h = 2 * self.PAD + self.HEAD + 3 * self.TILE_H + 2 * self.GAP + self.FOOT
        return QSize(round(w * k), round(h * k))

    def _tile_rect(self, i: int) -> QRectF:
        return QRectF(self.PAD + (i % 3) * (self.TILE_W + self.GAP),
                      self.PAD + self.HEAD + (i // 3) * (self.TILE_H + self.GAP),
                      self.TILE_W, self.TILE_H)

    def _buttons(self) -> dict[str, QRectF]:
        """The footer buttons, in the unscaled coordinates everything is painted in."""
        top = self.sizeHint().height() / self._k() - self.PAD - self.FOOT + 8
        return {"pause": QRectF(self.PAD, top, self.BTN_W, self.BTN_H),
                "stop": QRectF(self.PAD + self.BTN_W + 6, top, self.BTN_W, self.BTN_H)}

    def _hit(self, pos) -> str | None:
        k = self._k()
        pt = QPointF(pos.x() / k, pos.y() / k)
        if self.ov.sounds():
            for name, r in self._buttons().items():
                if r.contains(pt):
                    return name
        for i in range(len(self.ov.page_sounds())):
            if self._tile_rect(i).contains(pt):
                return f"slot:{i}"
        return None

    def _all_paused(self) -> bool:
        return bool(self.playing) and all(paused for __, paused in self.playing.values())

    # ------------------------------------------------------------------ mouse
    def mouseMoveEvent(self, e):
        self.ov.keep_preview()
        self.ov._touch()   # the mouse is on it: don't auto-hide from under it
        if self._press is not None and e.buttons() & Qt.MouseButton.LeftButton:
            at = e.globalPosition().toPoint()
            if self._grab is None and (at - self._press).manhattanLength() >= DRAG_START_PX:
                self._grab = self._press - self.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._grab is not None:
                self.move(self._clamped(at - self._grab, at))
                self.ov._touch()
            return
        hit = self._hit(e.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit
                           else Qt.CursorShape.OpenHandCursor)
            self.update()

    def _clamped(self, top_left: QPoint, cursor: QPoint) -> QPoint:
        """Keep the whole window on the monitor under the mouse."""
        sc = QGuiApplication.screenAt(cursor) or self.screen()
        if sc is None:
            return top_left
        g = sc.geometry()
        return QPoint(min(max(top_left.x(), g.left()), g.left() + g.width() - self.width()),
                      min(max(top_left.y(), g.top()), g.top() + g.height() - self.height()))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        dragged, self._grab, self._press = self._grab is not None, None, None
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._hover
                       else Qt.CursorShape.OpenHandCursor)
        if dragged:
            geo = self.geometry()
            sc = QGuiApplication.screenAt(geo.center()) or self.screen()
            if sc is not None:
                self.ov.dropped(geo, sc, self._placed_on)

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.unsetCursor()
            self.update()

    def mousePressEvent(self, e):
        hit = self._hit(e.position()) if e.button() == Qt.MouseButton.LeftButton else None
        if hit:
            self.ov.click(hit)
            self.update()
        elif e.button() == Qt.MouseButton.LeftButton:     # anywhere else grabs it, to move it
            self._press = e.globalPosition().toPoint()

    def _screen(self, follow_game: bool):
        monitor = self.ov.s.monitor
        if monitor == MONITOR_GAME:
            if follow_game and QGuiApplication.platformName() == "windows":
                name, rect = winkeys.foreground_monitor_info()
                sc = pick_screen(QGuiApplication.screens(), name, rect)
                if sc is not None:
                    return sc
            return self.screen() if self.isVisible() else QGuiApplication.primaryScreen()
        if monitor != MONITOR_PRIMARY:
            sc = find_screen(QGuiApplication.screens(), monitor)
            if sc is not None:
                return sc
        return QGuiApplication.primaryScreen()   # also when that monitor is unplugged

    def _place(self, follow_game: bool):
        size = self.sizeHint()
        self.resize(size)
        sc = self._screen(follow_game)
        if sc is None:
            return
        self._placed_on = sc
        self.move(place(sc.geometry(), size, self.ov.s, round(self.MARGIN * self._k())))

    # ------------------------------------------------------------------ show / hide
    def present(self, follow_game: bool = True):
        self._place(follow_game)
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            if not self._styled and QGuiApplication.platformName() == "windows":
                winkeys.make_overlay(int(self.winId()))
                self._styled = True
        if QGuiApplication.platformName() == "windows":
            winkeys.raise_topmost(int(self.winId()))
        self._animate(1.0, 120)
        self.update()

    def dismiss(self):
        if self.isVisible():
            self._animate(0.0, 140)

    def _animate(self, to: float, ms: int):
        self._fade.stop()
        if lite.on():   # (Lite mode: there or gone at once)
            self.setWindowOpacity(to)
            if to == 0.0:
                self.hide()
            return
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(to)
        self._fade.start()

    def _faded(self):
        if self._fade.endValue() == 0.0:
            self.hide()

    def set_playing(self, playing: dict):
        """Called ~30x/s while open. Repaints only what changed: a tile whose bar moved
        a pixel or more, or that started, stopped or was paused, and the footer when
        its buttons light up or flip to Resume. A paused sound's bar doesn't move, so it
        costs nothing. (Repainting all of it every tick took ~2 ms a frame.)"""
        if not (playing or self.playing or self.ov.flash):
            return
        old, self.playing = self.playing, dict(playing)
        if self.ov.flash or self._static_key() != self._cache_key:
            self.update()   # a pick's flash, the footer, a page flip, a sound loaded …
            return
        px = self.TILE_W * self._k()
        for i, meta in enumerate(self.ov.page_sounds()[:SLOTS]):
            was, now = old.get(meta.id), self.playing.get(meta.id)
            if was == now:
                continue
            if was is not None and now is not None and was[1] == now[1] \
                    and abs(was[0] - now[0]) * px < 1:
                self.playing[meta.id] = was   # under a pixel: keep what's drawn
                continue
            self.update(self._scaled(self._tile_rect(i)))

    def _scaled(self, r: QRectF) -> QRect:
        """A rect in painted (unscaled) units → widget pixels, with room for the border."""
        k = self._k()
        return QRectF(r.left() * k, r.top() * k, r.width() * k,
                      r.height() * k).toAlignedRect().adjusted(-2, -2, 2, 2)

    # ------------------------------------------------------------------ paint
    # The parts that don't move are drawn once into two cached layers: `under` (panel,
    # header, footer, tile cards) and `over` (each tile's strip, key and name). A
    # paint just stacks under → progress bars → over → tile borders.
    THEMED = ("bg", "border", "text_hi", "muted", "card", "card_hi", "accent", "badge",
              "badge_text")

    def _flash(self) -> int | None:
        ov = self.ov
        return ov.flash[0] if ov.flash and ov.flash[1] > time.monotonic() else None

    def _static_key(self) -> tuple:
        """Everything the cached layers are drawn from."""
        ov = self.ov
        cfg, T = ov.host.cfg, theme.T
        return (self.width(), self.height(), self.devicePixelRatioF(), self.font().key(),
                ov.s.scale, ov.s.opacity, ov.s.mode, ov.s.keys, ov.page, ov.pages(),
                cfg.category, cfg.category_colors.get(cfg.category), bool(cfg.categories),
                bool(ov.sounds()),
                tuple(T.get(t) for t in self.THEMED),
                tuple((m.id, m.name, m.color, m.id in ov.host.audio)
                      for m in ov.page_sounds()),
                self._hover, self._flash(), bool(self.playing), self._all_paused())

    def _layer(self, draw) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self._k(), self._k())
        draw(p)
        p.end()
        return pm

    def paintEvent(self, e):
        ov, k = self.ov, self._k()
        now = time.monotonic()
        flash = self._flash()
        if flash is None:
            ov.flash = None   # over: set_playing needn't repaint for it any more
        key = self._static_key()
        if key != self._cache_key:
            self._layers = (self._layer(lambda p: self._paint_under(p, flash)),
                            self._layer(self._paint_over))
            self._cache_key = key
        assert self._layers is not None   # made above on the first paint (no key yet)
        under, over = self._layers
        dirty = e.rect()
        tiles = [(i, self._tile_rect(i), m) for i, m in enumerate(ov.page_sounds()[:SLOTS])]
        tiles = [t for t in tiles if dirty.intersects(self._scaled(t[1]))]
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, under)
        p.scale(k, k)
        for __, r, meta in tiles:
            self._tile_bar(p, r, meta)
        p.resetTransform()
        p.drawPixmap(0, 0, over)
        p.scale(k, k)
        for i, r, meta in tiles:
            self._tile_edge(p, r, i, meta, flash == i)
        p.end()
        if flash is not None and ov.flash is not None:   # (flash is read from it)
            QTimer.singleShot(int((ov.flash[1] - now) * 1000) + 20, self.update)

    def _paint_under(self, p: QPainter, flash: int | None):
        ov, T = self.ov, theme.T
        W, H = self.width() / self._k(), self.height() / self._k()
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 14, 14)
        bg = QColor(T["bg"])
        bg.setAlpha(round(255 * ov.s.opacity / 100))
        p.fillPath(panel, bg)
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawPath(panel)

        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setBold(True)
        ks = ov.keyset
        sounds = ov.page_sounds()
        n = ov.pages()

        # header: page, and how to flip
        head = QRectF(self.PAD + 2, self.PAD - 2, W - 2 * self.PAD - 4, self.HEAD - 6)
        p.setFont(f)
        p.setPen(QColor(T["text_hi"]))
        cat = ov.host.cfg.category
        title = _("Page {value} of {n}", value=ov.page + 1, n=n) if n > 1 else _("Sounds")
        if cat:
            title = f"{cat}  ·  {title}" if n > 1 else cat
        hint = f"{key_label(ks['prev'])}  ‹  ›  {key_label(ks['next'])}" if n > 1 else ""
        small = QFont(f)
        small.setBold(False)
        small.setPointSizeF(8.5)
        # a long category name ran into the page keys: it's cut with "…" before them
        room = head.width() - (QFontMetrics(small).horizontalAdvance(hint) + 12 if hint else 0)
        col = ov.host.cfg.category_colors.get(cat) if cat else None
        if col:   # the category's colour, as on its tab
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QRectF(head.left(), head.center().y() - 5, 10, 10))
            p.restore()
            head = head.adjusted(16, 0, 0, 0)
            room -= 16
        p.drawText(head, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight,
                                              max(0, int(room))))
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        if hint:
            p.drawText(head, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, hint)

        # tiles: an empty slot whole, a sound's card (the bar and the rest go on top)
        for i in range(SLOTS):
            self._tile_under(p, f, self._tile_rect(i), i,
                             sounds[i] if i < len(sounds) else None, flash == i)

        # footer: the other keys
        foot = QRectF(self.PAD + 2, H - self.PAD - self.FOOT + 6, W - 2 * self.PAD - 4,
                      self.FOOT - 6)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        cat_key = ("     " + _("{key}  category", key=key_label(ks["cat"]))
                   if ov.host.cfg.categories else "")
        if not ov.sounds():
            p.drawText(foot, Qt.AlignmentFlag.AlignCenter,
                       _("Nothing in this category") + cat_key if cat
                       else _("No sounds yet: add some in the Sounds tab"))
        else:
            btns, paused, live = self._buttons(), self._all_paused(), bool(self.playing)
            self._button(p, f, "pause", "play" if paused else "pause",
                         _("Resume") if paused else _("Pause"), key_label(ks["pause"]), live)
            self._button(p, f, "stop", "stop", _("Stop all"), key_label(ks["stop"]), live)
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(T["muted"]))
            left = btns["stop"].right() + 10
            rest = QRectF(left, btns["stop"].top(), W - self.PAD - 2 - left, self.BTN_H)
            close = _("let go to close") if ov.s.mode == "hold" else _("Esc  close")
            p.drawText(rest, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       cat_key.strip())
            p.drawText(rest, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, close)

    def _paint_over(self, p: QPainter):
        f = QFont(self.font())
        for i, meta in enumerate(self.ov.page_sounds()[:SLOTS]):
            self._tile_over(p, f, self._tile_rect(i), i, meta)

    def _button(self, p: QPainter, f: QFont, name: str, icon: str, text: str, key: str,
                live: bool):
        """A footer button: icon, name, key. Dimmed while nothing is playing."""
        T = theme.T
        r = self._buttons()[name]
        hover = self._hover == name
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        card = QColor(T["card_hi"] if hover else T["card"])
        card.setAlpha(240)
        p.fillPath(path, card)
        p.setPen(QPen(QColor(T["accent"] if hover else T["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        ink = QColor(T["text_hi"] if live else T["muted"])
        # the icon is drawn, not a glyph: not every font has ⏸ / ⏹
        cx, cy, s = r.left() + 14, r.center().y(), 4.5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        if icon == "pause":
            p.drawRect(QRectF(cx - s, cy - s, 3.2, 2 * s))
            p.drawRect(QRectF(cx + s - 3.2, cy - s, 3.2, 2 * s))
        elif icon == "play":
            p.drawPolygon(QPolygonF([QPointF(cx - s + 1, cy - s), QPointF(cx + s + 1, cy),
                                     QPointF(cx - s + 1, cy + s)]))
        else:
            p.drawRoundedRect(QRectF(cx - s, cy - s, 2 * s, 2 * s), 1.5, 1.5)
        body = r.adjusted(26, 0, -8, 0)
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(ink)
        p.drawText(body, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if key:   # the key on a little keycap, like a pad's hotkey badge
            f.setBold(False)
            p.setFont(f)
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(key) + 10
            cap = QRectF(body.right() - w, cy - fm.height() / 2 - 1, w, fm.height() + 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["badge"]))
            p.drawRoundedRect(cap, 4, 4)
            p.setPen(QColor(T["badge_text"]))
            p.drawText(cap, Qt.AlignmentFlag.AlignCenter, key)

    @staticmethod
    def _path(r: QRectF) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        return path

    def _tile_under(self, p: QPainter, f: QFont, r: QRectF, i: int, meta, flash: bool):
        T = theme.T
        path = self._path(r)
        if meta is None:
            p.setPen(QPen(QColor(T["border"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QColor(T["muted"]))   # faint was unreadable (2.6:1) in some themes
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.drawText(r.adjusted(10, 6, -8, -6), Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignTop,
                       key_label(self.ov.keyset["slots"][i]))
            return
        card = QColor(T["card_hi"] if flash else T["card"])
        card.setAlpha(240)
        p.fillPath(path, card)

    def _tile_bar(self, p: QPainter, r: QRectF, meta):
        """How far the sound has got, over the card and under its name."""
        prog, paused = self.playing.get(meta.id, (None, False))
        if prog is None:
            return
        fill = QColor(meta.color)
        fill.setAlpha(45 if paused else 85)
        p.save()
        p.setClipPath(self._path(r))
        p.fillRect(QRectF(r.left(), r.top(), r.width() * max(prog, 0.02), r.height()), fill)
        p.restore()

    def _tile_over(self, p: QPainter, f: QFont, r: QRectF, i: int, meta):
        T = theme.T
        # colour strip down the left edge
        p.save()
        p.setClipPath(self._path(r))
        p.fillRect(QRectF(r.left(), r.top(), 4, r.height()), QColor(meta.color))
        p.restore()
        # key badge
        key = key_label(self.ov.keyset["slots"][i])
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        badge = QRectF(r.left() + 11, r.top() + 7, max(18, p.fontMetrics().horizontalAdvance(key)
                                                       + 10), 17)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T["badge"]))
        p.drawRoundedRect(badge, 5, 5)
        p.setPen(QColor(T["badge_text"]))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, key)
        # name
        ready = meta.id in self.ov.host.audio
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(T["text_hi"] if ready else T["muted"]))
        p.drawText(r.adjusted(11, 27, -8, -5), Qt.AlignmentFlag.AlignLeft
                   | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   meta.name if ready else _("{name} (loading)", name=meta.name))

    def _tile_edge(self, p: QPainter, r: QRectF, i: int, meta, flash: bool):
        T = theme.T
        prog, paused = self.playing.get(meta.id, (None, False))
        if flash:
            p.setPen(QPen(QColor(T["text_hi"]), 2.2))
        elif self._hover == f"slot:{i}":
            p.setPen(QPen(QColor(T["accent"]), 1.6))
        elif prog is not None:
            ink = QColor(meta.color)
            if paused:   # paused: the same line, faded
                ink.setAlpha(110)
            p.setPen(QPen(ink, 2))
        else:
            p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._path(r))
