"""Small Easter eggs: the header onion wobbles when clicked, and Bun naps in the
small hours (by this PC's clock) until a click wakes him."""

import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QWidget

from soundboard.core import usage
from soundboard.ui.bun import bunnywidget as bw
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.bun.logowidget import LogoWidget


def _logo():
    win = QWidget()
    win.resize(400, 200)
    QHBoxLayout(win).addWidget(logo := LogoWidget())
    win.show()
    return win, logo


def test_a_click_wobbles_and_it_settles(qapp):
    win, logo = _logo()
    for _ in range(30):
        QTest.mouseClick(logo, Qt.LeftButton)
    assert logo.squish > 0
    for _ in range(30):
        logo.advance(1 / 30)
    assert logo.squish == 0
    assert not logo.grab().isNull()
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
                "egg-bun-woken"):
        assert key in usage.FEATURES
