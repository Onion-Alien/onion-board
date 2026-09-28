"""Which QScreen the in-game overlay opens on: matching Windows' description of the
game's monitor (GDI device name + native rectangle) to Qt's screens. Pure function,
stand-in screens, no windows."""
from PySide6.QtCore import QRect

from soundboard.ui.overlay import pick_screen


class Screen:
    """Stands in for QScreen: name(), geometry() in logical pixels, devicePixelRatio()."""

    def __init__(self, name, x, y, w, h, dpr=1.0):
        self._name, self._geo, self._dpr = name, QRect(x, y, w, h), dpr

    def name(self):
        return self._name

    def geometry(self):
        return self._geo

    def devicePixelRatio(self):
        return self._dpr

    def __repr__(self):
        return f"Screen({self._name})"


# A scaled 2560x1440 primary (125 %, so Qt reports 2048x1152) with a 1920x1080
# monitor to its left. Qt keeps the secondary's native top-left as its logical origin.
PRIMARY = Screen("MainPanel", 0, 0, 2048, 1152, dpr=1.25)
SECOND = Screen("SidePanel", -1920, 0, 1920, 1080)
TWO = [PRIMARY, SECOND]
DISPLAY1, DISPLAY2 = "\\\\.\\DISPLAY1", "\\\\.\\DISPLAY2"


def test_qt5_device_name_matches_directly():
    screens = [Screen(DISPLAY1, 0, 0, 2560, 1440), Screen(DISPLAY2, -1920, 0, 1920, 1080)]
    assert pick_screen(screens, DISPLAY2, (-1920, 0, 1920, 1080)) is screens[1]
    # The name wins even when the rectangle would say otherwise.
    assert pick_screen(screens, DISPLAY1, (-1920, 0, 1920, 1080)) is screens[0]


def test_qt6_friendly_names_fall_back_to_native_geometry():
    assert pick_screen(TWO, DISPLAY2, (-1920, 0, 1920, 1080)) is SECOND
    assert pick_screen(TWO, DISPLAY1, (0, 0, 2560, 1440)) is PRIMARY


def test_same_size_screens_are_told_apart_by_position():
    a, b = Screen("Left", -1920, 0, 1920, 1080), Screen("Right", 0, 0, 1920, 1080)
    assert pick_screen([a, b], DISPLAY2, (-1920, 0, 1920, 1080)) is a
    assert pick_screen([a, b], DISPLAY1, (0, 0, 1920, 1080)) is b


def test_unique_size_match_is_enough_when_the_position_does_not_line_up():
    assert pick_screen(TWO, DISPLAY2, (2560, 0, 1920, 1080)) is SECOND


def test_no_match_returns_none():
    assert pick_screen(TWO, DISPLAY2, (0, 0, 1024, 768)) is None
    assert pick_screen(TWO, "", None) is None
    assert pick_screen([], DISPLAY1, (0, 0, 2560, 1440)) is None
    # Two same-size screens and a position matching neither: ambiguous, so None.
    a, b = Screen("Left", -1920, 0, 1920, 1080), Screen("Right", 0, 0, 1920, 1080)
    assert pick_screen([a, b], DISPLAY1, (5000, 0, 1920, 1080)) is None
