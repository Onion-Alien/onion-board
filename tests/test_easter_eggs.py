"""Small Easter eggs: the header onion cries when clicked too much, and Bun naps in the
small hours (by this PC's clock) until a click wakes him."""

import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QWidget

from soundboard import usage
from soundboard.ui import bunnywidget as bw
from soundboard.ui import logowidget as lw
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.logowidget import LogoWidget


def _logo():
    win = QWidget()
    win.resize(400, 200)
    QHBoxLayout(win).addWidget(logo := LogoWidget())
    win.show()
    return win, logo


def _run(logo, secs, dt=1 / 30):
    for _ in range(round(secs / dt)):
        logo.advance(dt)


def test_a_few_clicks_only_wobble(qapp):
    win, logo = _logo()
    for _ in range(lw.WELL_UP_AT - 1):
        QTest.mouseClick(logo, Qt.LeftButton)
    assert logo.squish > 0 and logo.welling == 0 and not logo.crying
    win.close()


def test_enough_quick_clicks_make_it_cry_tears_that_land(qapp, monkeypatch):
    monkeypatch.setattr(usage, "_used", set())
    win, logo = _logo()
    for i in range(lw.CRY_CLICKS - 1):
        QTest.mouseClick(logo, Qt.LeftButton)
        if i + 1 >= lw.WELL_UP_AT:
            assert logo.welling > 0   # eyes welling up on the way
    assert not logo.crying
    assert "egg-onion-cried" not in usage._used
    QTest.mouseClick(logo, Qt.LeftButton)
    assert logo.crying
    assert usage._used == {"egg-onion-cried"}   # counted (by name only)
    _run(logo, 1.0)
    assert logo.tears and logo._layer is not None and logo._layer.isVisible()
    assert any(t[5] >= 0 for t in logo.tears)    # some have splashed down
    assert logo.puddle > 0
    assert not logo.grab().isNull() and not logo._layer.grab().isNull()
    win.close()


def test_clicks_while_crying_peel_it_and_it_dries_up_after(qapp, monkeypatch):
    win, logo = _logo()
    for _ in range(lw.CRY_CLICKS):
        logo.poke()
    logo.poke()
    logo.poke()
    assert len(logo.peels) == 2
    clock = [time.monotonic()]
    monkeypatch.setattr(lw.time, "monotonic", lambda: clock[0])
    for _ in range(int((lw.CRY_S + 6) * 30)):
        clock[0] += 1 / 30
        logo.advance(1 / 30)
    assert not logo.crying and not logo.tears and not logo.peels and logo.puddle == 0
    assert logo._layer is None
    win.close()


def test_slow_clicks_never_add_up(qapp, monkeypatch):
    win, logo = _logo()
    clock = [1000.0]
    monkeypatch.setattr(lw.time, "monotonic", lambda: clock[0])
    for _ in range(30):
        logo.poke()
        clock[0] += lw.CRY_WINDOW
        logo.advance(0.03)
    assert not logo.crying
    win.close()


def _frames(b, n, dt=0.035):
    for _ in range(n):
        b._last = time.monotonic() - dt
        b._step()


def test_bun_naps_in_the_small_hours_only(qapp, monkeypatch):
    b = BunnyWidget(joy_lines=("hehe!",), pong=True, naps=True, sad=0.6, lines=("hi",))
    b.resize(b.sizeHint())
    for hour, sleeping in ((1, False), (2, True), (4, True), (5, False), (14, False)):
        monkeypatch.setattr(bw, "local_hour", lambda h=hour: h)
        b._hour_at = -1e9
        assert b.asleep is sleeping, hour
    monkeypatch.setattr(bw, "local_hour", lambda: 3)
    b._hour_at = -1e9
    _frames(b, 80)   # ~3 s
    assert b.zzz and not b.say                  # Zs, and no begging in his sleep
    pose = b.pose()
    assert pose["blink"] == 1.0
    assert not b.grab().isNull()
    plain = BunnyWidget(joy_lines=("hehe!",))
    plain._hour_at = -1e9
    assert not plain.asleep                     # only the Buns that nap


def test_a_click_wakes_him_grumpy_then_he_dozes_off(qapp, monkeypatch):
    monkeypatch.setattr(usage, "_used", set())
    b = BunnyWidget(joy_lines=("hehe!",), pong=True, naps=True)
    monkeypatch.setattr(bw, "local_hour", lambda: 3)
    assert b.asleep
    QTest.mouseClick(b, Qt.LeftButton)
    assert not b.asleep and b.say and not b._pokes   # woken, not a poke towards Pong
    assert usage._used == {"egg-bun-woken"}
    _frames(b, 10)
    assert b.pose()["angry"] > 0.3
    b._woken_until = time.monotonic() - 1           # 30 s later
    assert b.asleep


def test_the_eggs_are_counted_by_name_only():
    for key in ("egg-pong-opened", "egg-pong-quit", "egg-pong-won", "egg-pong-lost",
                "egg-onion-cried", "egg-bun-woken"):
        assert key in usage.FEATURES
