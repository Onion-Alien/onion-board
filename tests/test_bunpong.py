"""The Pong Easter egg: poke Bun enough and he fetches a bat and opens Pong in a
dialog; points and the end work; Esc or Close ends it and calms him."""

import math
import random
import time

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from soundboard.core import usage
from soundboard.ui.bun import bunnywidget as bw
from soundboard.ui.bun import bunpong
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.bun.bunpong import WIN_AT, BunPong


def _frames(b, n, dt=0.035):
    for _ in range(n):
        b._last = time.monotonic() - dt
        b._step()


def _page_with_bun():
    stack = QStackedWidget()
    page = QWidget()
    other = QWidget()
    stack.addWidget(page)
    stack.addWidget(other)
    QVBoxLayout(page).addWidget(bun := BunnyWidget(joy_lines=("hehe!",), pong=True))
    stack.resize(720, 520)
    return stack, page, other, bun


def _game(seed=1):
    stack, page, other, bun = _page_with_bun()
    stack.show()
    game = BunPong(stack, bun, rng=random.Random(seed))
    game._timer.stop()
    game.show()
    return stack, game


def test_a_few_pokes_are_fine_more_make_him_cross(qapp):
    _stack, _page, _other, bun = _page_with_bun()
    for _ in range(bw.GRUMPY_AT - 1):
        assert not bun.poke()
    assert bun.poke()          # now he's cross
    assert bun.say and not bun.building
    _frames(bun, 10)
    assert bun.pose()["angry"] > 0.5


def test_pokes_spread_out_never_add_up(qapp, monkeypatch):
    _stack, _page, _other, bun = _page_with_bun()
    clock = [1000.0]
    monkeypatch.setattr(bw.time, "monotonic", lambda: clock[0])
    for _ in range(20):
        assert not bun.poke()
        clock[0] += bw.ANNOY_WINDOW   # one poke every few seconds: just happy hops


def test_once_cross_five_more_pokes_fetch_the_bat(qapp, monkeypatch):
    _stack, _page, _other, bun = _page_with_bun()
    clock = [1000.0]
    monkeypatch.setattr(bw.time, "monotonic", lambda: clock[0])
    for _ in range(bw.GRUMPY_AT):
        bun.poke()
        clock[0] += 0.05
    assert bun.say and not bun.building   # cross now
    for _ in range(20):   # spam before he's gone red counts for nothing
        clock[0] += 0.01
        assert bun.poke() and not bun.building
    clock[0] += bw.RED_IN
    for _ in range(4):
        clock[0] += 2.0   # slower pokes still count while he's cross
        assert bun.poke() and not bun.building
    clock[0] += 2.0
    assert bun.poke() and bun.building   # the fifth: off for his bat


def test_a_plain_bun_never_plays(qapp):
    bun = BunnyWidget(joy_lines=("hehe!",))
    for _ in range(bw.ANNOY_CLICKS + 3):
        assert not bun.poke()
    assert not bun.building


def test_enough_pokes_fetch_the_bat_and_open_the_game(qapp):
    stack, page, other, bun = _page_with_bun()
    stack.show()
    for _ in range(bw.GRUMPY_AT):
        QTest.mouseClick(bun, Qt.LeftButton)
    QTest.qWait(round(bw.RED_IN * 1000) + 50)   # until he's red
    for _ in range(bw.BAT_POKES):
        QTest.mouseClick(bun, Qt.LeftButton)
    assert bun.act_phase() == "dash"
    seen = set()
    for _ in range(150):
        _frames(bun, 1)
        seen.add(bun.act_phase())
        if stack.findChildren(BunPong):
            break
    assert {"dash", "cloud", "back", "bat"} <= seen
    assert bun.prop == "bat"
    game = stack.findChildren(BunPong)[0]
    assert game.isVisible() and game.isModal()
    # closing it ends the game, and Bun calms down
    game.reject()
    assert game._done
    assert not bun.building and bun.prop is None
    stack.close()


def test_esc_ends_the_game(qapp):
    stack, page, _other, bun = _page_with_bun()
    stack.show()
    bun.fetch_bat()
    game = bunpong.open_for(bun)
    QTest.keyClick(game.court, Qt.Key_Escape)
    assert game._done and not game.isVisible()
    assert not bun.building
    stack.close()


def test_esc_ends_the_game_wherever_the_focus_is(qapp):
    """Esc goes to whatever has the focus (a real key press, through the window): the
    court, Close, Play again, Another game, or the next game after it."""
    from PySide6.QtWidgets import QPushButton

    def focus_close(g):
        next(b for b in g.findChildren(QPushButton) if b.text() == "Close").setFocus()

    def ended(g):
        g.court.on_over()

    def another(g):
        g.court.on_over()
        QTest.mouseClick(g.other, Qt.MouseButton.LeftButton)

    def other_button(g):
        g.court.on_over()
        g.other.setFocus()

    for put in (lambda g: None, focus_close, ended, other_button, another):
        stack, page, _other, bun = _page_with_bun()
        stack.show()
        bun.fetch_bat()
        game = bunpong.open_for(bun)
        game.activateWindow()
        qapp.processEvents()
        put(game)
        qapp.processEvents()
        assert qapp.focusWidget() is not None
        QTest.keyClick(game.windowHandle(), Qt.Key.Key_Escape)
        assert game._done
        stack.close()


def test_a_click_serves_and_bun_returns_an_easy_ball(qapp):
    stack, game = _game()
    c = game.court
    assert c.state == "ready"
    QTest.mouseClick(c, Qt.LeftButton, pos=c.rect().center())
    assert c.state == "play" and c.vx < 0       # served toward Bun
    for _ in range(200):
        game.step(1 / 60)
        if c.vx > 0:
            break
    assert c.vx > 0 and c.state == "play"       # he hit it back
    assert c.flash
    game.finish()
    stack.close()


def test_your_paddle_follows_the_mouse_and_hits(qapp):
    stack, game = _game()
    c = game.court
    c.serve("you")
    c.vy = 0.0
    c.by = 0.3
    QTest.mouseMove(c, QPointF(10, c.height() * 0.3).toPoint())
    c.aim_y = 0.3
    for _ in range(200):
        game.step(1 / 60)
        if c.vx < 0:
            break
    assert abs(c.you_y - 0.3) < 0.01
    assert c.vx < 0 and c.score == {"you": 0, "bun": 0}
    game.finish()
    stack.close()


def test_a_missed_ball_scores_and_the_next_serve_comes(qapp):
    stack, game = _game()
    c = game.court
    c.serve("you")
    c.vy, c.by = 0.0, 0.05
    c.aim_y = 0.95                  # paddle far away
    for _ in range(300):
        game.step(1 / 60)
        if c.state == "point":
            break
    assert c.score == {"you": 0, "bun": 1}
    for _ in range(80):
        game.step(1 / 60)
    assert c.state == "play" and c.vx > 0   # served toward you, who lost the point
    game.finish()
    stack.close()


def test_first_to_win_ends_with_play_again(qapp):
    stack, game = _game()
    c = game.court
    for _ in range(WIN_AT):
        c._point("you")
    assert c.state == "over" and c.winner == "you"
    assert not game.end.isHidden()
    # Bun and the result are centred together on the court
    bun = c.bun_rect(c.geo())
    left, right = bun.left(), game.end.geometry().right()
    assert abs(left - (c.width() - right)) <= 2
    assert abs(bun.center().y() - c.height() / 2) <= 1
    assert "win" in game.end_title.text().lower()
    assert not game.grab().isNull()
    game.again.click()
    assert c.state == "ready" and c.score == {"you": 0, "bun": 0}
    assert game.end.isHidden()
    game.finish()
    stack.close()


@pytest.mark.windows   # the court's size comes from Segoe UI's text
def test_long_play_never_sticks_and_paints(qapp):
    stack, game = _game(seed=4)
    c = game.court
    c.serve("bun")
    # two minutes, your paddle chasing the ball a little off its middle, as a person
    # does: dead-centre hits send it flat forever, and Bun reaches every flat ball
    # near the top or bottom, so a perfect robot never scores
    for i in range(60 * 120):
        c.aim_y = c.by + 0.06 * math.sin(i / 23)
        game.step(1 / 60)
        if i % 300 == 0:
            game.grab()
        assert 0 <= c.by <= 1
        if c.state == "over":
            break
    assert sum(c.score.values()) >= 1   # Bun misses now and then
    game.finish()
    stack.close()


def test_arrow_keys_move_and_serve(qapp):
    stack, game = _game()
    c = game.court
    QTest.keyClick(c, Qt.Key_Down)
    assert c.state == "play" and c.aim_y > 0.5
    game.finish()
    stack.close()


def test_bun_stays_whole_on_the_court_and_still_reaches_the_edges(qapp):
    stack, game = _game(seed=6)
    c = game.court
    g = c.geo()
    for y in (0.02, 0.98):
        c.serve("bun")
        c.bx, c.by, c.vy = 0.5, y, 0.0
        for _ in range(240):
            game.step(1 / 60)
            r = c.bun_rect(g)
            assert r.top() >= 0 and r.bottom() <= c.height()
            if c.vx > 0 or c.state != "play":
                break
        assert c.vx > 0 and c.score == {"you": 0, "bun": 0}   # he got it, bat stretched
    game.finish()
    stack.close()


def test_pong_counts_opened_quit_won_and_lost(qapp, monkeypatch):
    monkeypatch.setattr(usage, "_used", set())
    stack, page, _other, bun = _page_with_bun()
    stack.show()
    bun.fetch_bat()
    game = bunpong.open_for(bun, game="pong")
    assert usage._used == {"egg-pong-opened", "egg-game-pong"}
    game.court.serve("bun")
    game.reject()                       # closed mid-game
    assert usage._used == {"egg-pong-opened", "egg-game-pong", "egg-pong-quit"}
    for who, key in (("you", "egg-pong-won"), ("bun", "egg-pong-lost")):
        usage._used.clear()
        stack2, g = _game()
        for _ in range(WIN_AT):
            g.court._point(who)
        g.finish()                      # closed after the end: not a quit
        assert usage._used == {key}
        stack2.close()
    stack.close()


class _Engine:
    """Records what the game plays."""

    def __init__(self):
        self.mon_stream = object()
        self.played = []

    def play(self, sid, data, gain, **kw):
        self.played.append((sid, data, kw))


def _game_with_sound(seed=1):
    stack, game = _game(seed)
    stack.engine = _Engine()
    stack.cfg = type("Cfg", (), {"pong_sounds": True})()
    stack.set_option = lambda attr, v: setattr(stack.cfg, attr, v)
    game._mute_look()
    return stack, game, stack.engine


def test_the_game_plays_its_sounds_in_the_headphones_only(qapp, monkeypatch):
    stack, game, eng = _game_with_sound()
    heard = []
    real = bunpong.pongsounds.render

    def render(name, style, **kw):
        heard.append((name, kw))
        return real(name, style, **kw)

    monkeypatch.setattr(bunpong.pongsounds, "render", render)
    c = game.court
    c.serve("bun")
    for _ in range(400):
        game.step(1 / 60)
        if c.vx > 0:
            break
    c._point("bun")
    names = [n for n, _kw in heard]
    assert names[0] == "serve" and "bun" in names and "score_bun" in names
    assert eng.played and all(sid == bunpong.SOUND_SID and kw["preview"] and kw["mode"] == "overlap"
                              for sid, _d, kw in eng.played)
    game.finish()
    stack.close()


def test_your_hits_climb_and_milestones_chime(qapp):
    stack, game, eng = _game_with_sound()
    heard = []
    game.court.sound = lambda name, **kw: heard.append((name, kw))
    c = game.court
    c.serve("you")
    for _i in range(5):
        c._hit(0.0, -1, 0.9)
    rallies = [kw["rally"] for n, kw in heard if n == "you"]
    assert rallies == [0, 1, 2, 3, 4]
    assert ("milestone", {"level": 1}) in heard
    c._hit(1.0, -1, 0.9)   # off the very tip: a close call
    assert heard[-1][1]["edge"] is True
    game.finish()
    stack.close()


def test_the_speaker_button_mutes_and_is_kept(qapp):
    stack, game, eng = _game_with_sound()
    game.court.serve("bun")
    assert eng.played
    eng.played.clear()
    game.mute.click()
    assert stack.cfg.pong_sounds is False
    assert "on" in game.mute.toolTip()
    game.court.serve("bun")
    assert not eng.played
    game.mute.click()
    assert stack.cfg.pong_sounds is True
    game.finish()
    stack.close()


def test_no_headphones_open_means_no_sound(qapp):
    stack, game, eng = _game_with_sound()
    eng.mon_stream = None
    game.court.serve("bun")
    assert not eng.played
    game.finish()
    stack.close()


# ---------------------------------------------------------------- the controls

class _Key:
    """A stand-in key event."""

    def __init__(self, key, repeat=False):
        self._k, self._r = key, repeat

    def key(self):
        return self._k

    def isAutoRepeat(self):
        return self._r


def test_holding_a_key_glides_the_paddle_and_letting_go_stops_it(qapp):
    stack, game = _game()
    c = game.court
    c.serve("you")
    c.vx = 0.0                                   # keep the ball out of the way
    assert c.press(_Key(Qt.Key.Key_Down), True)
    start = c.aim_y
    for _ in range(15):                          # a quarter of a second held
        assert c.press(_Key(Qt.Key.Key_Down, repeat=True), True)   # repeats do nothing
        game.step(1 / 60)
    moved = c.aim_y - start
    assert 0.2 < moved < 0.6                     # smooth: no stutter, no teleport
    c.press(_Key(Qt.Key.Key_Down), False)
    stopped = c.aim_y
    for _ in range(10):
        game.step(1 / 60)
    assert c.aim_y == stopped
    # held to the bottom, then turned round: it comes back at once
    c.press(_Key(Qt.Key.Key_Down), True)
    for _ in range(120):
        game.step(1 / 60)
    c.press(_Key(Qt.Key.Key_Down), False)
    c.press(_Key(Qt.Key.Key_Up), True)
    game.step(1 / 60)
    game.step(1 / 60)
    assert c.you_y < 0.9 - 0.02
    game.finish()
    stack.close()


def test_the_dialog_passes_key_releases_on(qapp):
    stack, game = _game()
    c = game.court
    QTest.keyPress(game, Qt.Key.Key_Up)
    assert Qt.Key.Key_Up in c.held
    QTest.keyRelease(game, Qt.Key.Key_Up)
    assert not c.held
    game.finish()
    stack.close()


def test_the_mouse_steers_from_anywhere_even_off_the_court(qapp, monkeypatch):
    stack, game = _game()
    c = game.court
    c.serve("you")
    c.vx = 0.0
    below = c.mapToGlobal(QPointF(-400, c.height() + 300).toPoint())   # off left and down
    monkeypatch.setattr(bunpong.QCursor, "pos", staticmethod(lambda: below))
    game.step(1 / 60)
    assert c.you_y == pytest.approx(0.9)         # at the bottom, not stuck mid-court
    mid = c.mapToGlobal(QPointF(c.width() + 200, c.height() * 0.4).toPoint())
    monkeypatch.setattr(bunpong.QCursor, "pos", staticmethod(lambda: mid))
    game.step(1 / 60)
    assert c.you_y == pytest.approx(0.4, abs=0.01)
    # a still mouse leaves the keys in charge
    c.press(_Key(Qt.Key.Key_Down), True)
    for _ in range(10):
        game.step(1 / 60)
    assert c.you_y > 0.45
    game.finish()
    stack.close()


# ---------------------------------------------------------------- the other games

def _play(name, seed=1):
    stack, page, other, bun = _page_with_bun()
    stack.show()
    game = BunPong(stack, bun, rng=random.Random(seed), game=name)
    game._timer.stop()
    game.show()
    return stack, game


def test_each_open_picks_a_game_never_the_same_twice_running(qapp):
    seen, last = set(), None
    rng = random.Random(3)
    for _ in range(40):
        name = bunpong.pick_game(rng)
        assert name != last
        seen.add(name)
        last = name
    assert seen == set(bunpong.games())
    assert len(seen) >= 4


def test_another_game_switches_and_keeps_the_dialog(qapp):
    stack, game = _play("pong")
    for _ in range(WIN_AT):
        game.court._point("you")
    assert not game.end.isHidden()
    old = game.game
    game.other.click()
    assert game.game != old and game.court.state != "over"
    assert game.title.text() == game.court.title() == game.windowTitle()
    assert game.end.isHidden() and game.end.parent() is game.court
    for _ in range(game.court.win_at):
        game.court._point("bun")
    assert not game.end.isHidden() and "bun" in game.end_title.text().lower()
    game.finish()
    stack.close()


def _until(game, cond, secs=5.0, dt=1 / 120):
    for _ in range(int(secs / dt)):
        if cond():
            return True
        game.step(dt)
    return cond()


def test_dodgeball_hit_him_while_he_winds_up_and_he_dodges_what_he_sees(qapp):
    stack, game = _play("dodge")
    c = game.court
    QTest.mouseClick(c, Qt.MouseButton.LeftButton)   # the first click starts it
    assert c.state == "play"
    # he's planted for his wind-up: a throw straight at him lands
    c.next_throw, c.act, c.act_t, c.windup = 99, "windup", 0.0, 9.0
    c.you[1] = c.aim[1] = c.bun_y
    c.rng.random = lambda: 0.99                      # he sees it in time
    QTest.keyClick(c, Qt.Key.Key_Space)
    assert _until(game, lambda: c.score["you"] == 1)
    assert _until(game, lambda: c.state == "play")
    # not winding up: he sees it coming and gets out of the way
    c.next_throw, c.act = 99, "idle"
    c.you[1] = c.aim[1] = c.bun_y
    c.spot = c.bun_y
    was = c.bun_y
    c.throw()
    _until(game, lambda: not c.balls, 2.0)
    assert c.score["you"] == 1 and abs(c.bun_y - was) > 0.1
    # his throw finds you if you stand still
    c.act, c.act_t, c.windup = "windup", 0.0, 0.1
    assert _until(game, lambda: c.score["bun"] == 1, 4.0)
    game.finish()
    stack.close()


def test_dodgeball_you_only_run_so_fast_and_stay_in_your_half(qapp):
    stack, game = _play("dodge")
    c = game.court
    c.start()
    c.next_throw = 99
    c.aim = [0.0, 0.0]                               # off to Bun's side and the top
    game.step(0.1)
    g = c.geo()
    left, _r, top, _b = c._area(g)
    assert c.you[0] >= left - 1e-6 and c.you[1] >= top - 1e-6
    ran = (0.8 - c.you[0]) * g["w"], (0.5 - c.you[1]) * g["h"]
    assert math.hypot(*ran) <= c.YOU_SPEED * g["h"] * 0.1 + 1
    c.reload = 0
    c.throw()
    c.throw()                                        # reloading: one ball, not two
    assert len([b for b in c.balls if b["who"] == "you"]) == 1
    game.finish()
    stack.close()


def _pitch(c, ty, kind="fast", bend=0.0, T=0.6):
    c.start()
    c.windup = 0.0
    c.step(1 / 120)
    c.pitch.update(kind=kind, ty=ty, bend=bend, T=T)


def _at_plate(game, c):
    _until(game, lambda: c.pitch["t"] >= c.pitch["T"] - 1 / 240, 2.0, 1 / 240)


def test_home_run_on_time_and_height_is_yours_a_miss_is_his(qapp):
    stack, game = _play("homerun")
    c = game.court
    QTest.keyClick(c, Qt.Key.Key_Space)              # starts it
    g = c.geo()
    zy = g["zone_y"] / g["h"]
    _pitch(c, zy)
    c.bat_y = zy
    _at_plate(game, c)
    c.swing_bat()
    assert c.result == "hr" and c.score == {"you": 1, "bun": 0}
    _pitch(c, zy)
    c.bat_y = zy
    game.step(0.2)
    c.swing_bat()                                    # way too early
    assert c.result == "strike" and c.score["bun"] == 1
    _pitch(c, zy)
    c.bat_y = zy + 0.2                               # on time but nowhere near it
    _at_plate(game, c)
    c.swing_bat()
    assert c.result == "strike" and c.score["bun"] == 2
    _pitch(c, zy)                                    # let a good one go by: a strike too
    _until(game, lambda: c.result, 2.0)
    assert c.result == "strike" and c.score["bun"] == 3
    game.finish()
    stack.close()


def test_home_run_let_the_ones_outside_the_box_go(qapp):
    stack, game = _play("homerun")
    c = game.court
    g = c.geo()
    out = (g["zone_y"] + g["zone_h"] * 1.6) / g["h"]
    _pitch(c, out)
    _until(game, lambda: c.result, 2.0)
    assert c.result == "ball" and c.score == {"you": 0, "bun": 0}
    _pitch(c, out)
    c.bat_y = out
    _at_plate(game, c)
    c.swing_bat()                                    # chased it, however well timed
    assert c.result == "strike" and c.score["bun"] == 1
    zy = g["zone_y"] / g["h"]                        # a curve still ends where it's aimed
    _pitch(c, zy, "curve", bend=-0.2)
    assert c.in_box(g, c._ball_at(g, c.pitch["T"])[1] / g["h"])
    assert not c.in_box(g, c._ball_at(g, c.pitch["T"] * 0.6)[1] / g["h"])
    game.finish()
    stack.close()


def test_whack_a_bun_whack_them_never_the_carrots_or_nothing(qapp):
    stack, game = _play("whack")
    c = game.court
    QTest.keyClick(c, Qt.Key.Key_Space)
    assert c.state == "play"
    c.next_pop = 99
    c.holes[4] = {"kind": "bun", "t": 0.0, "up": 1.0, "hit": False}
    game.step(0.1)
    QTest.keyClick(c, Qt.Key.Key_5)                  # the middle, as on the number pad
    assert c.score == {"you": 1, "bun": 0}
    c.holes[0] = {"kind": "carrot", "t": 0.0, "up": 1.0, "hit": False}
    game.step(0.1)
    cx, cy, _w = c.hole(c.geo(), 0)
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPointF(cx, cy - 4).toPoint())
    assert c.score == {"you": 1, "bun": 1}
    game.step(0.5)
    c.holes[8] = {"kind": "bun", "t": 0.0, "up": 1.0, "hit": False}
    game.step(0.1)
    QTest.keyClick(c, Qt.Key.Key_1)                  # an empty one: the mallet sticks
    assert c.stuck > 0
    QTest.keyClick(c, Qt.Key.Key_3)                  # ... so this one misses its chance
    assert c.score["you"] == 1
    _until(game, lambda: c.holes[8] is None, 3.0)    # and it gets away
    assert c.score == {"you": 1, "bun": 2}
    game.finish()
    stack.close()


def test_whack_a_bun_is_twenty_for_you_five_for_him(qapp):
    stack, game = _play("whack")
    c = game.court
    for _ in range(4):
        c._point("bun", quip=False)
    for _ in range(19):
        c._point("you", quip=False)
    assert c.state != "over"
    c._point("you", quip=False)
    assert c.winner == "you" and not game.end.isHidden()
    assert c.score_text("you") == "20/20" and c.score_text("bun") == "4/5"
    game.finish()
    stack.close()


def _whack_bot(c, react, rng):
    """Whacks a Bun once it's been up `react` seconds, never a carrot; react 0: swings
    about at random."""
    if not react:
        if rng.random() < 0.08:
            c.whack(rng.randrange(9))
        return
    for i, hl in enumerate(c.holes):
        if hl and not hl["hit"] and hl["kind"] == "bun" and hl["t"] >= react:
            c.whack(i)
            return


def _homerun_bot(c, rng, sd):
    """Takes the ones outside the box and swings on time give or take `sd` seconds
    (and the ball's height give or take as much); sd 0: swings at everything early."""
    if c.state == "windup":
        c.plan = rng.gauss(0, sd)
    if c.state != "pitch" or c.swung is not None:
        return
    g = c.geo()
    y = c._ball_at(g, c.pitch["T"])[1] / g["h"]
    if not sd:
        if c.pitch["t"] > c.pitch["T"] * 0.8:
            c.swing_bat()
    elif c.in_box(g, y):
        c.bat_y = y + c.plan
        if c.pitch["t"] >= c.pitch["T"] + c.plan:
            c.swing_bat()


@pytest.mark.parametrize("name", ["homerun", "whack"])
def test_good_play_beats_him_and_mashing_never_does(qapp, name):
    """Hard, not impossible: a sharp player wins, swinging about loses."""
    wins = {}
    for skill in ("sharp", "masher"):
        wins[skill] = 0
        for seed in range(3):
            stack, game = _play(name, seed=seed)
            c = game.court
            c.sound = None
            rng = random.Random(seed)
            c.plan = 0.0
            c.start()
            for _ in range(120 * 240):
                if name == "whack":
                    _whack_bot(c, 0.3 if skill == "sharp" else 0.0, rng)
                else:
                    _homerun_bot(c, rng, 0.012 if skill == "sharp" else 0.0)
                game.step(1 / 120)
                if c.state == "over":
                    break
            wins[skill] += c.winner == "you"
            game.finish()
            stack.close()
    assert wins["sharp"] >= 2 and wins["masher"] == 0, wins


@pytest.mark.parametrize("name", ["dodge", "homerun", "whack"])
def test_every_game_paints_through_a_whole_match(qapp, name):
    stack, game = _play(name, seed=5)
    c = game.court
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPointF(2, 2).toPoint())
    assert c.state != "ready"
    for i in range(60 * 60):
        if name == "dodge" and c.state == "play" and i % 20 == 0:
            c.throw()
        elif name == "homerun" and c.state == "pitch" and c.pitch["t"] > c.pitch["T"] * 0.98:
            c.swing_bat()
        elif name == "whack" and c.state == "play" and i % 9 == 0:
            c.whack(i % 9)
        game.step(1 / 60)
        if i % 40 == 0:
            game.grab()
        if c.state == "over":
            break
    while c.state != "over":                         # a long match: finish it off
        c._point("bun", quip=False)
    assert not game.end.isHidden()
    assert not game.grab().isNull()
    game.finish()
    stack.close()
