"""In-game overlay: a small HUD of sound tiles that pops up over a game on a hotkey.

The overlay never takes focus, so the game keeps its keyboard and mouse the whole
time. Its keys are global hotkeys (RegisterHotKey, see winkeys) claimed only while
it's up: the number keys play a tile, Q / E flip pages, R switches category, 0 stops
everything, . pauses, Esc closes. When it closes, the keys go straight back to the game.
It takes clicks too (a tile plays, the Pause / Stop buttons along the bottom) without
ever taking focus, for games that give you a mouse cursor.

Pages are the Sounds tab's pads in order, nine at a time, so dragging pads around
there rearranges the overlay too. It shows the category the Sounds tab shows;
switching category here switches it there too.

In exclusive fullscreen nothing can be drawn over the game, so the overlay opens
"blind": the keys still work, and short beeps in your headphones confirm it.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer)
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import QWidget

from soundboard import theme, winkeys

log = logging.getLogger(__name__)

SLOTS = 9
# key per tile, tiles in reading order (top-left first). The numpad's + and − go by
# their aliases: "num +" can't be written in a combo, where + joins the keys.
KEYSETS = {
    "digits": dict(slots=[str(i) for i in range(1, 10)],
                   prev="q", next="e", stop="0", pause=".", cat="r"),
    "numpad": dict(slots=[f"num {i}" for i in (7, 8, 9, 4, 5, 6, 1, 2, 3)],
                   prev="subtract", next="add", stop="num 0", pause="num .", cat="multiply"),
}
MODES = [("toggle", "Tap to open, tap again to close"),
         ("hold", "Hold to show, let go to hide")]
KEY_CHOICES = [("digits", "Number row 1–9  (Q / E flip pages, R category)"),
               ("numpad", "Numpad  (− / + flip pages, * category)")]
POSITIONS = [("top", "Top"), ("center", "Middle"), ("bottom", "Bottom"),
             ("top-left", "Top left"), ("top-right", "Top right")]
AUTOHIDE = [(0, "Never"), (3, "3 seconds"), (4, "4 seconds"), (6, "6 seconds"),
            (10, "10 seconds")]
CLOSE_DELAY_MS = 220    # after a pick, long enough to see the tile light up
FLASH_S = 0.25
HOLD_POLL_MS = 30


def key_label(key: str) -> str:
    k = key.replace("num ", "")
    return {"subtract": "−", "add": "+", "multiply": "*", "esc": "Esc"}.get(k, k.upper())


@dataclass
class OverlaySettings:
    mode: str = "toggle"            # toggle | hold
    keys: str = "digits"            # digits | numpad
    close_after_play: bool = True   # toggle mode: hide as soon as a sound is picked
    autohide: int = 4               # toggle mode: seconds untouched before it hides; 0 = never
    position: str = "top"
    scale: int = 100                # tile size, %
    opacity: int = 85               # background, %

    @classmethod
    def from_dict(cls, d: dict | None) -> OverlaySettings:
        d, s = d or {}, cls()
        if d.get("mode") in dict(MODES):
            s.mode = d["mode"]
        if d.get("keys") in KEYSETS:
            s.keys = d["keys"]
        if isinstance(d.get("close_after_play"), bool):
            s.close_after_play = d["close_after_play"]
        if d.get("position") in dict(POSITIONS):
            s.position = d["position"]
        for name, lo, hi in (("autohide", 0, 60), ("scale", 60, 160), ("opacity", 30, 100)):
            v = d.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                setattr(s, name, int(min(max(v, lo), hi)))
        return s

    def to_dict(self) -> dict:
        return asdict(self)


class Overlay:
    """What the overlay does; `OverlayWindow` only draws it.

    `host` is the main window. Used: host.cfg (sounds, categories, category,
    overlay_hotkey), host.audio, host.play(sid), host.on_hotkey('__stop__' /
    '__pause__'), host.register_hotkeys() (which asks `layer()` for the extra keys),
    host.cue(kind or notes) and host.set_category(name) (the category key)."""
    ACTION = "__overlay__"
    PREFIX = "__ov:"

    def __init__(self, host, settings: dict | None = None):
        self.host = host
        self.s = OverlaySettings.from_dict(settings)
        self.page = 0
        self.is_open = False
        self.blind = False            # open without a window (exclusive fullscreen)
        self.flash: tuple[int, float] | None = None   # (tile, until) just picked
        self._window: OverlayWindow | None = None
        self._hold_vk: int | None = None
        self._autohide = QTimer()
        self._autohide.setSingleShot(True)
        self._autohide.timeout.connect(self.close)
        self._close_soon = QTimer()
        self._close_soon.setSingleShot(True)
        self._close_soon.timeout.connect(self.close)
        self._hold = QTimer()
        self._hold.timeout.connect(self._poll_hold)
        self._preview_end = QTimer()
        self._preview_end.setSingleShot(True)
        self._preview_end.timeout.connect(self._end_preview)

    @property
    def keyset(self) -> dict:
        return KEYSETS[self.s.keys]

    @property
    def window(self) -> OverlayWindow:
        if self._window is None:
            self._window = OverlayWindow(self)
        return self._window

    # ------------------------------------------------------------------ pages
    def sounds(self) -> list:
        """The sounds of the category the Sounds tab shows (all of them for "")."""
        cat = self.host.cfg.category
        return [m for m in self.host.cfg.sounds if not cat or cat in m.tags]

    def pages(self) -> int:
        return max(1, math.ceil(len(self.sounds()) / SLOTS))

    def page_sounds(self) -> list:
        self.page = min(self.page, self.pages() - 1)
        return self.sounds()[self.page * SLOTS:(self.page + 1) * SLOTS]

    # ------------------------------------------------------------------ keys
    def layer(self) -> dict[str, str]:
        """The keys to claim while open: combo -> action. They win over the app's
        other hotkeys for as long as the overlay is up."""
        if not self.is_open:
            return {}
        ks = self.keyset
        keys = {k: f"{self.PREFIX}slot:{i}" for i, k in enumerate(ks["slots"])}
        keys.update({ks["prev"]: f"{self.PREFIX}prev", ks["next"]: f"{self.PREFIX}next",
                     ks["stop"]: f"{self.PREFIX}stop", ks["pause"]: f"{self.PREFIX}pause",
                     "esc": f"{self.PREFIX}close"})
        if self.host.cfg.categories:   # only claimed when there's something to switch to
            keys[ks["cat"]] = f"{self.PREFIX}cat"
        out = dict(keys)
        if self.s.mode == "hold":
            # while ctrl+alt+O is held, "1" arrives as ctrl+alt+1: claim that too
            parsed = winkeys.parse(self.host.cfg.overlay_hotkey or "")
            if parsed and parsed[0]:
                mods = winkeys.combo_name(parsed[0], ord("A"))[:-1]   # "ctrl+alt+"
                for k, act in keys.items():
                    out.setdefault(mods + k, act)
        return out

    def handle(self, action: str) -> bool:
        """Take a fired hotkey action if it's ours. True if it was."""
        if action == self.ACTION:
            self.trigger()
            return True
        if not action.startswith(self.PREFIX):
            return False
        if not self.is_open:
            return True           # a key press that raced the close: drop it
        what = action[len(self.PREFIX):]
        if what.startswith("slot:"):
            self.pick(int(what[5:]))
        elif what in ("prev", "next"):
            self.flip(-1 if what == "prev" else 1)
        elif what == "cat":
            self.next_category()
        elif what == "stop":
            self.host.on_hotkey("__stop__")
            self._touch()
        elif what == "pause":
            self.host.on_hotkey("__pause__")
            self._touch()
        elif what == "close":
            self.close()
        return True

    def click(self, what: str):
        """A click on the window: "slot:N", "pause" or "stop". Same as its key."""
        self.handle(self.PREFIX + what)

    # ------------------------------------------------------------------ open / close
    def trigger(self):
        if not self.is_open:
            self.open()
        elif self.s.mode == "toggle":
            self.close()
        # hold mode: letting go closes it, a repeat press does nothing

    def open(self):
        if self.is_open:
            return
        self._preview_end.stop()
        self.is_open = True
        self.flash = None
        self.blind = winkeys.exclusive_fullscreen()
        self.host.register_hotkeys()      # claims layer()
        if self.blind:
            log.info("overlay opened without a window: a game is in exclusive fullscreen")
            self.host.cue("start")
            if self._window is not None:
                self._window.dismiss()
        else:
            self.window.present()
            log.info("overlay opened at %s on %s", self.window.geometry().getRect(),
                     self.window.screen().name() if self.window.screen() else "?")
        self._hold_vk = None
        if self.s.mode == "hold":
            parsed = winkeys.parse(self.host.cfg.overlay_hotkey or "")
            if parsed:
                self._hold_vk = parsed[1]
                self._hold.start(HOLD_POLL_MS)
        self._touch()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        for t in (self._autohide, self._close_soon, self._hold):
            t.stop()
        self.host.register_hotkeys()      # the keys go back to the game
        if self.blind:
            self.host.cue("stop")
        if self._window is not None:
            self._window.dismiss()

    def _poll_hold(self):
        if self._hold_vk is not None and not winkeys.is_down(self._hold_vk):
            self.close()

    def _touch(self):
        """Something happened: push the auto-hide back."""
        if self.is_open and self.s.mode == "toggle" and self.s.autohide \
                and not self._close_soon.isActive():
            self._autohide.start(self.s.autohide * 1000)

    # ------------------------------------------------------------------ actions
    def pick(self, tile: int):
        sounds = self.page_sounds()
        if not 0 <= tile < len(sounds):
            self._touch()
            return
        self.host.play(sounds[tile].id)
        self.flash = (tile, time.monotonic() + FLASH_S)
        if self._window is not None:
            self._window.update()
        if self.s.mode == "toggle" and self.s.close_after_play:
            self._autohide.stop()
            self._close_soon.start(CLOSE_DELAY_MS)
        else:
            self._touch()

    def flip(self, step: int):
        n = self.pages()
        self.page = (self.page + step) % n
        self.flash = None
        if self.blind and n > 1:     # 1 beep for page 1, 2 for page 2, …
            self.host.cue(tuple(f for _ in range(min(self.page + 1, 6)) for f in (1175, 0)))
        if self._window is not None:
            self._window.update()
        self._touch()

    def next_category(self):
        """All → the first category → … → the last → All again."""
        cats = ["", *self.host.cfg.categories]
        cur = self.host.cfg.category
        i = cats.index(cur) if cur in cats else 0
        self.host.set_category(cats[(i + 1) % len(cats)])
        self.page = 0
        self.flash = None
        if self.blind:
            self.host.cue("saved")
        if self._window is not None:
            self._window.update()
        self._touch()

    # ------------------------------------------------------------------ host hooks
    def apply(self, settings: dict):
        """New settings from the Settings window."""
        self.s = OverlaySettings.from_dict(settings)
        if self.is_open:
            self.host.register_hotkeys()
        if self._window is not None and self._window.isVisible():
            self._window.present()        # new size / position

    def preview(self, seconds: float = 3.0):
        """Show the overlay (without claiming any keys) so its look can be judged."""
        if self.is_open:
            return
        self.window.present(follow_game=False)
        self._preview_end.start(int(seconds * 1000))

    def _end_preview(self):
        if not self.is_open and self._window is not None:
            self._window.dismiss()

    def tick(self, playing: dict):
        """Called by the main window's UI timer. Repaints only while visible."""
        w = self._window
        if w is not None and w.isVisible():
            w.set_playing(playing)

    def shutdown(self):
        for t in (self._autohide, self._close_soon, self._hold, self._preview_end):
            t.stop()
        self.is_open = False
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
            self._window = None


class OverlayWindow(QWidget):
    """The HUD itself: frameless, see-through, always on top and never focused. It
    takes clicks (a tile plays, the footer buttons pause / stop), but clicking it
    never activates it, so the game keeps the keyboard."""
    TILE_W, TILE_H, GAP, PAD, HEAD, FOOT = 138, 70, 8, 14, 30, 34
    BTN_W, BTN_H = 100, 22
    MARGIN = 36   # from the screen edge

    def __init__(self, ov: Overlay):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.ov = ov
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Onion Board overlay")
        self.playing: dict = {}
        self._hover: str | None = None     # "slot:N" / "pause" / "stop" under the mouse
        self.setMouseTracking(True)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._faded)
        self._styled = False

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
        return bool(self.playing) and all(paused for _, paused in self.playing.values())

    # ------------------------------------------------------------------ mouse
    def mouseMoveEvent(self, e):
        hit = self._hit(e.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.unsetCursor()
            self.update()

    def mousePressEvent(self, e):
        hit = self._hit(e.position()) if e.button() == Qt.LeftButton else None
        if hit:
            self.ov.click(hit)
            self.update()

    def _screen(self, follow_game: bool):
        if follow_game and QGuiApplication.platformName() == "windows":
            name = winkeys.foreground_monitor()
            for sc in QGuiApplication.screens():
                if sc.name() == name:
                    return sc
        return self.screen() if self.isVisible() else QGuiApplication.primaryScreen()

    def _place(self, follow_game: bool):
        size = self.sizeHint()
        self.resize(size)
        sc = self._screen(follow_game)
        if sc is None:
            return
        g, m = sc.geometry(), round(self.MARGIN * self._k())
        pos = self.ov.s.position
        x = {"top-left": g.left() + m, "top-right": g.right() - m - size.width()}.get(
            pos, g.center().x() - size.width() // 2)
        y = {"center": g.center().y() - size.height() // 2,
             "bottom": g.bottom() - m - size.height()}.get(pos, g.top() + m)
        self.move(x, y)

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
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(to)
        self._fade.start()

    def _faded(self):
        if self._fade.endValue() == 0.0:
            self.hide()

    def set_playing(self, playing: dict):
        if playing or self.playing or self.ov.flash:
            self.playing = dict(playing)
            self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, e):
        ov, T, k = self.ov, theme.T, self._k()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(k, k)
        W, H = self.width() / k, self.height() / k
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
        title = f"Page {ov.page + 1} of {n}" if n > 1 else "Sounds"
        if cat:
            title = f"{cat}  ·  {title}" if n > 1 else cat
        p.drawText(head, Qt.AlignLeft | Qt.AlignVCenter, title)
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        if n > 1:
            p.drawText(head, Qt.AlignRight | Qt.AlignVCenter,
                       f"{key_label(ks['prev'])}  ‹  ›  {key_label(ks['next'])}")

        # tiles
        now = time.monotonic()
        flash = ov.flash[0] if ov.flash and ov.flash[1] > now else None
        for i in range(SLOTS):
            self._tile(p, f, self._tile_rect(i), i, sounds[i] if i < len(sounds) else None,
                       flash == i)
        if flash is not None:
            QTimer.singleShot(int((ov.flash[1] - now) * 1000) + 20, self.update)

        # footer: the other keys
        foot = QRectF(self.PAD + 2, H - self.PAD - self.FOOT + 6, W - 2 * self.PAD - 4,
                      self.FOOT - 6)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        cat_key = (f"     {key_label(ks['cat'])}  category"
                   if ov.host.cfg.categories else "")
        if not ov.sounds():
            p.drawText(foot, Qt.AlignCenter,
                       f"Nothing in this category{cat_key}" if cat
                       else "No sounds yet: add some in the Sounds tab")
        else:
            btns, paused, live = self._buttons(), self._all_paused(), bool(self.playing)
            self._button(p, f, "pause", "play" if paused else "pause",
                         "Resume" if paused else "Pause", key_label(ks["pause"]), live)
            self._button(p, f, "stop", "stop", "Stop all", key_label(ks["stop"]), live)
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(T["muted"]))
            left = btns["stop"].right() + 10
            rest = QRectF(left, btns["stop"].top(), W - self.PAD - 2 - left, self.BTN_H)
            close = "let go to close" if ov.s.mode == "hold" else "Esc  close"
            p.drawText(rest, Qt.AlignLeft | Qt.AlignVCenter, cat_key.strip())
            p.drawText(rest, Qt.AlignRight | Qt.AlignVCenter, close)
        p.end()

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
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        ink = QColor(T["text_hi"] if live else T["muted"])
        # the icon is drawn, not a glyph: not every font has ⏸ / ⏹
        cx, cy, s = r.left() + 14, r.center().y(), 4.5
        p.setPen(Qt.NoPen)
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
        p.drawText(body, Qt.AlignLeft | Qt.AlignVCenter, text)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        p.drawText(body, Qt.AlignRight | Qt.AlignVCenter, key)

    def _tile(self, p: QPainter, f: QFont, r: QRectF, i: int, meta, flash: bool):
        T = theme.T
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        key = key_label(self.ov.keyset["slots"][i])
        if meta is None:
            p.setPen(QPen(QColor(T["border"]), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(QColor(T["faint"]))
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.drawText(r.adjusted(10, 6, -8, -6), Qt.AlignLeft | Qt.AlignTop, key)
            return
        accent = QColor(meta.color)
        card = QColor(T["card_hi"] if flash else T["card"])
        card.setAlpha(240)
        p.fillPath(path, card)
        prog, paused = self.playing.get(meta.id, (None, False))
        if prog is not None:
            fill = QColor(accent)
            fill.setAlpha(45 if paused else 85)
            p.save()
            p.setClipPath(path)
            p.fillRect(QRectF(r.left(), r.top(), r.width() * max(prog, 0.02), r.height()), fill)
            p.restore()
        # colour strip down the left edge
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), 4, r.height()), accent)
        p.restore()
        if flash:
            p.setPen(QPen(QColor(T["text_hi"]), 2.2))
        elif self._hover == f"slot:{i}":
            p.setPen(QPen(QColor(T["accent"]), 1.6))
        elif prog is not None:
            p.setPen(QPen(accent, 2, Qt.DashLine if paused else Qt.SolidLine))
        else:
            p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # key badge
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        badge = QRectF(r.left() + 11, r.top() + 7, max(18, p.fontMetrics().horizontalAdvance(key)
                                                       + 10), 17)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T["badge"]))
        p.drawRoundedRect(badge, 5, 5)
        p.setPen(QColor(T["badge_text"]))
        p.drawText(badge, Qt.AlignCenter, key)
        # name
        ready = meta.id in self.ov.host.audio
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(T["text_hi"] if ready else T["muted"]))
        p.drawText(r.adjusted(11, 27, -8, -5), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   meta.name if ready else f"{meta.name} (loading)")
