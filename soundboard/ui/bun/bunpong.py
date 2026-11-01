"""The Easter egg: poke Bun enough times (bunnywidget.py, `pong=True`) and he comes back
with a baseball bat and challenges you to a game, in a dialog like the app's guides.

Which game is picked at random each time: Pong (here) or one of the games in
bungames.py (dodgeball, home run, whack-a-Bun). They all share `Game`: Bun
on the left, the score, his quips, sparks and confetti, first to `win_at`.

Pong: he holds his bat up as his paddle on the left; yours is on the right and follows
the mouse's height (anywhere on screen, so leaving the court never sticks it) or the
arrow keys (hold to glide). Every hit speeds the ball up a little, and Bun only moves
so fast, so a long rally is how you beat him.

Nothing is kept: Esc or Close ends the game and Bun calms down again. The game's
sounds (pongsounds.py) play in your headphones only; the speaker button mutes them.
"""
from __future__ import annotations

import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor  # noqa: F401  (the tests steer the mouse through bunpong.QCursor)
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard.sounds import pongsounds
from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.ui.bun.bunny import H, W
from soundboard.i18n import _
from soundboard.ui.kit import appstate, fit, icons
from soundboard.ui.kit.panel import hint_label, icon_button
from soundboard.ui.bun.bunpongbase import (  # noqa: F401
    _alpha,
    _bubble,
    _grain,
    _grain_tile,
    _mix,
    _Spark,
    BALL,
    BODY_CSS,
    BUBBLE,
    BUN_PINK,
    BUN_SPEED,
    CONFETTI,
    EDGE,
    FPS,
    Game,
    GO_KEYS,
    KEY_DIRS,
    KEY_RAMP,
    KEY_SPEED,
    KEY_TAP,
    MAX_ANGLE,
    MILESTONE,
    RALLY_SHOWN,
    SERVE_PAUSE,
    SOUND_SID,
    SPEED0,
    SPEED_MAX,
    SPEEDUP,
    TITLE_CSS,
    WIN_AT,
)
from soundboard.ui.bun.bunpongcourt import Court  # noqa: F401


def games() -> dict[str, type[Game]]:
    """Every game Bun can pick, by name."""
    from soundboard.ui.bun import bungames
    return {"pong": Court, **bungames.GAMES}


_last_pick: list[str] = []


def pick_game(rng: random.Random | None = None, but: str | None = None) -> str:
    """A game at random, never the one just played (or `but`) twice in a row."""
    rng = rng or random.Random()
    avoid = {but} if but else set(_last_pick[-1:])
    name = rng.choice([n for n in games() if n not in avoid])
    _last_pick[:] = [name]
    return name


def open_for(bun, game: str | None = None) -> BunPong:
    """Open a game (`game`, or one at random) for Bun, over his window (one game at a
    time)."""
    win = bun.window()
    for old in win.findChildren(BunPong):
        old.finish()
    dlg = BunPong(win, bun, game=game or pick_game())
    usage.used("egg-pong-opened")   # the names only (usage.py); every game counts here
    usage.used(f"egg-game-{usage.game_tag(dlg.game)}")
    dlg.open()
    dlg.court.setFocus(Qt.FocusReason.OtherFocusReason)
    return dlg


class BunPong(QDialog):
    """The game in a dialog built like the app's guides: a big title and a line on how
    to play, the court on the theme's card, and Close at the bottom. At the end Bun and
    who won sit side by side, centred together on the court, with Play again and
    Another game."""
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work

    def __init__(self, parent: QWidget, bun=None, rng: random.Random | None = None,
                 game: str = "pong"):
        super().__init__(parent)
        fit.watch(self)
        self.bun = bun
        self.win = parent   # the main window: its engine and settings, for the sounds
        self.rng = rng
        self._done = False
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        self.title = QLabel()
        self.title.setStyleSheet(TITLE_CSS)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setStyleSheet(BODY_CSS)
        v.addWidget(self.title)
        v.addWidget(self.body)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.card_lay = QVBoxLayout(self.card)
        self.card_lay.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.card, 1)

        # the end: who won, Play again and Another game, beside Bun (placed in _place_end)
        self.end = QWidget()
        el = QVBoxLayout(self.end)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        self.end_title = QLabel()
        self.end_title.setStyleSheet(TITLE_CSS)
        self.end_score = QLabel()
        self.end_score.setStyleSheet(BODY_CSS)
        self.again = QPushButton(_("Play again"))
        self.again.setObjectName("primary")
        self.again.setAutoDefault(False)
        self.again.clicked.connect(self.play_again)
        self.other = QPushButton(_("Another game"))
        self.other.setAutoDefault(False)
        self.other.clicked.connect(self.another_game)
        el.addWidget(self.end_title)
        el.addWidget(self.end_score)
        el.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.again)
        buttons.addWidget(self.other)
        buttons.addStretch(1)
        el.addLayout(buttons)

        self.court: Game = None   # type: ignore[assignment]   # set_game makes it
        self.game = ""
        self.set_game(game)

        row = QHBoxLayout()
        row.addWidget(hint_label(_("Closing it ends the game. Nothing is kept.")), 1)
        self.mute = icon_button("volume", "")
        self.mute.setAutoDefault(False)
        self.mute.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # the arrow keys stay the game's
        self.mute.clicked.connect(self.toggle_sounds)
        self._mute_look()
        row.addWidget(self.mute)
        close = QPushButton(_("Close"))
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        v.addLayout(row)
        self.finished.connect(lambda _r: self.finish())

        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._timer.stop)

    # ------------------------------------------------------------------ flow
    def set_game(self, name: str):
        """Put game `name` on the card (in place of the one there)."""
        old = self.court
        court = games()[name](self.rng)
        court.setMinimumHeight(320)
        court.on_over = self._show_end
        court.sound = self._sound
        self.end.hide()
        self.end.setParent(court)
        self.end.setCursor(Qt.CursorShape.ArrowCursor)
        if old is not None:
            self.card_lay.replaceWidget(old, court)
            old.deleteLater()
        else:
            self.card_lay.addWidget(court)
        self.court, self.game = court, name
        self.setWindowTitle(court.title())
        self.title.setText(court.title())
        self.body.setText(court.how())
        court.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show_end(self):
        c = self.court
        you, bun = c.score["you"], c.score["bun"]
        if c.winner == "you":
            self.end_title.setText(_("You win!"))
            self.end_score.setText(_("{you} to {bun}. Bun's not happy.", you=you, bun=bun))
        else:
            self.end_title.setText(_("Bun wins!"))
            self.end_score.setText(_("{bun} to {you}. Try again?", you=you, bun=bun))
        self.end.adjustSize()
        self._place_end()
        self.end.show()
        self.end.raise_()
        self.again.setFocus()

    def _place_end(self):
        """Bun and the result side by side, the pair centred on the court."""
        c = self.court
        g = c.geo()
        sz = self.end.sizeHint()
        gap = 28
        bun_w = g["bh"] * W / H
        left = (c.width() - (bun_w + gap + sz.width())) / 2
        c.end_bun_left = left
        self.end.setGeometry(round(left + bun_w + gap), round((c.height() - sz.height()) / 2),
                             sz.width(), sz.height())

    def play_again(self):
        self.end.hide()
        self.court.reset()
        self.court.setFocus()

    def another_game(self):
        """A different game at random, from the start."""
        self.set_game(pick_game(but=self.game))

    def finish(self):
        """End the game: nothing is kept, and Bun calms down."""
        if self._done:
            return
        self._done = True
        self._timer.stop()
        if self.court.playing:   # left mid-game
            usage.used("egg-pong-quit")
        if self.bun is not None:
            try:
                self.bun.calm_down()
            except RuntimeError:   # Bun's widget is already gone
                pass
        if self.isVisible():
            self.reject()
        self.deleteLater()

    def step(self, dt: float):
        """Move the game on by `dt` seconds (the timer's tick; tests call it too)."""
        self.court.step(dt)

    # ------------------------------------------------------------------ sound
    def sounds_on(self) -> bool:
        return bool(getattr(getattr(self.win, "cfg", None), "pong_sounds", True))

    def toggle_sounds(self):
        """The speaker button: the game's sounds off or on again (kept in the settings)."""
        on = not self.sounds_on()
        set_option = getattr(self.win, "set_option", None)   # the main window's
        if set_option is not None:
            set_option("pong_sounds", on)
        self._mute_look()

    def _mute_look(self):
        on = self.sounds_on()
        tip = _("Mute the game's sounds") if on else _("Turn the game's sounds on")
        icons.set_icon(self.mute, "volume" if on else "volume_off", size=18)
        self.mute.setToolTip(tip)
        self.mute.setAccessibleName(tip)

    def _sound(self, name: str, **kw):
        """Play one of the game's sounds, in the theme's style, in your headphones only
        (a preview: never to your mic or the call)."""
        eng = getattr(self.win, "engine", None)
        if eng is None or eng.mon_stream is None or not self.sounds_on():
            return
        data = pongsounds.render(name, pongsounds.style_for(theme.current_name), **kw)
        eng.play(SOUND_SID, data, 1.0, mode="overlap", preview=True)

    # ------------------------------------------------------------------ timing
    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        self.step(dt)
        self.court.update()

    def showEvent(self, ev):
        if appstate.active():
            self._resume()
        super().showEvent(ev)

    def _resume(self):
        if not self._done:
            self._last = time.monotonic()
            self._timer.start()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.end.isVisible():
            self._place_end()

    def keyPressEvent(self, ev):
        if not self.court.press(ev, True):
            super().keyPressEvent(ev)   # Esc closes, as in every dialog

    def keyReleaseEvent(self, ev):
        if not self.court.press(ev, False):
            super().keyReleaseEvent(ev)
