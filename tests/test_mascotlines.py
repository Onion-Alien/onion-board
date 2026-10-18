"""Bun and Hoot's click lines, in each theme's character (style/mascotlines.py)."""
import random

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from soundboard.ui.kit import theme
from soundboard.style import mascotlines, owl
from soundboard.ui.bun.bunnywidget import BunnyWidget


def test_every_theme_has_its_own_lines():
    for name in theme.THEMES:
        bun, hoot = mascotlines._bun().get(name), mascotlines._hoot().get(name)
        assert bun and len(bun) == 4, name
        assert hoot and len(hoot) == 3, name
        assert len(set(bun + hoot)) == 7, name                  # no line twice
        for line in bun + hoot:
            assert line.strip() and len(line) <= 28, (name, line)   # one short bubble


def test_no_lines_for_a_theme_that_does_not_exist():
    names = set(theme.THEMES) | {"Halloween"}   # (a limited theme, while it's out)
    assert set(mascotlines._bun()) <= names and set(mascotlines._hoot()) <= names


def test_an_unknown_theme_says_darks():
    assert mascotlines.bun("Nope") == mascotlines.bun("Dark")
    assert mascotlines.hoot("Nope") == mascotlines.hoot("Dark")


def test_never_the_same_line_twice_in_a_row():
    rng, last = random.Random(1), ""
    for _i in range(50):
        line = mascotlines.pick(rng, ("a", "b", "c"), last)
        assert line != last
        last = line
    assert mascotlines.pick(rng, ("a",), "a") == "a"   # only one: it says it again
    assert mascotlines.pick(rng, (), "") == ""


def test_a_longer_line_stays_up_longer():
    assert mascotlines.read_secs("hi") == 1.6
    assert mascotlines.read_secs("x" * 28) > 2.0


def _click(w):
    c = QPointF(w.width() / 2, w.height() / 2)
    w.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, c, c, Qt.LeftButton,
                                  Qt.LeftButton, Qt.NoModifier))


def test_a_click_says_the_themes_lines(qapp, monkeypatch):
    monkeypatch.setattr(theme, "current_name", "Ocean")
    from soundboard.style import hooks
    monkeypatch.setattr(hooks, "theme_name", lambda: "Ocean")
    b = BunnyWidget(joy_lines=("yay",))
    b.resize(b.sizeHint())
    said = set()
    for _i in range(40):
        b.cheer()
        said.add(b.say)
    assert said & set(mascotlines.bun("Ocean")) and "yay" in said
    assert not said - set(mascotlines.bun("Ocean")) - {"yay"}
    h = owl.OwlWidget(80, lines=(), joy=("hoo",))
    h.resize(h.sizeHint())
    heard = set()
    for _i in range(30):
        _click(h)
        heard.add(h.say)
    assert heard & set(mascotlines.hoot("Ocean"))
    assert not heard - set(mascotlines.hoot("Ocean")) - {"hoo"}


def test_a_hoot_that_says_nothing_on_a_click_stays_quiet(qapp):
    h = owl.OwlWidget(80, lines=(), joy=())   # (the busy owl on the search page)
    h.cheer()
    assert h.say == ""


def test_a_long_line_wraps_in_buns_bubble(qapp):
    b = BunnyWidget(height=110, joy_lines=("yay",))
    b.resize(260, b.sizeHint().height())
    b.say = "my broom's parked outside, careful"
    assert not b.grab().isNull()   # (paints on two lines, doesn't drop it)
