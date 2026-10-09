"""The Pong Easter egg: poke Bun enough and he fetches a bat and opens Pong in a
dialog; points and the end work; Esc or Close ends it and calms him."""

import random
import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from soundboard.ui import bunnywidget as bw
from soundboard.ui import bunpong
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.bunpong import WIN_AT, BunPong


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


def test_a_plain_bun_never_plays(qapp):
    bun = BunnyWidget(joy_lines=("hehe!",))
    for _ in range(bw.ANNOY_CLICKS + 3):
        assert not bun.poke()
    assert not bun.building


def test_enough_pokes_fetch_the_bat_and_open_the_game(qapp):
    stack, page, other, bun = _page_with_bun()
    stack.show()
    for _ in range(bw.ANNOY_CLICKS):
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


def test_long_play_never_sticks_and_paints(qapp):
    stack, game = _game(seed=4)
    c = game.court
    c.serve("bun")
    for i in range(60 * 60):        # a minute, your paddle chasing the ball
        c.aim_y = c.by
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
