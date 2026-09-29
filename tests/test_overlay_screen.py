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


# ---------------------------------------------------------------- picked monitor + spot

from PySide6.QtCore import QSize  # noqa: E402

from soundboard.ui.overlay import (OverlaySettings, find_screen, monitor_choices,  # noqa: E402
                                   place, screen_key)


def test_a_saved_monitor_is_found_by_key_then_by_a_unique_name():
    assert screen_key(SECOND) == "SidePanel@-1920,0"
    assert find_screen(TWO, "SidePanel@-1920,0") is SECOND
    # monitors rearranged: the name alone still finds it
    assert find_screen(TWO, "SidePanel@2048,0") is SECOND
    assert find_screen(TWO, "Unplugged@0,0") is None
    # two identical monitors: only the exact key tells them apart
    a, b = Screen("Same", -1920, 0, 1920, 1080), Screen("Same", 0, 0, 1920, 1080)
    assert find_screen([a, b], "Same@0,0") is b
    assert find_screen([a, b], "Same@5000,0") is None


def test_monitor_choices_list_every_screen_and_mark_the_main_one():
    choices = monitor_choices(TWO, PRIMARY)
    assert [v for v, _ in choices] == ["game", "primary", "MainPanel@0,0", "SidePanel@-1920,0"]
    assert "2560×1440" in choices[2][1] and "(main)" in choices[2][1]   # native pixels
    assert "1920×1080" in choices[3][1] and "(main)" not in choices[3][1]


def test_every_position_lands_inside_the_monitor():
    geo, size, m = SECOND.geometry(), QSize(400, 300), 20
    spots = {}
    for pos in ("top-left", "top", "top-right", "left", "center", "right",
                "bottom-left", "bottom", "bottom-right"):
        pt = place(geo, size, OverlaySettings(position=pos), m)
        assert geo.contains(pt) and geo.contains(pt.x() + 399, pt.y() + 299), pos
        spots[pos] = (pt.x(), pt.y())
    assert spots["top-left"] == (-1920 + m, m)
    assert spots["bottom-right"] == (-m - 400, 1080 - m - 300)
    assert spots["center"] == (-1920 + 760, 390)
    assert len(set(spots.values())) == 9


def test_a_custom_spot_is_a_fraction_of_the_room_left():
    geo, size = SECOND.geometry(), QSize(400, 300)
    s = OverlaySettings(position="custom", x=1.0, y=0.5)
    pt = place(geo, size, s, 20)
    assert (pt.x(), pt.y()) == (-400, 390)          # flush right, centred
    s.x = 0.0
    assert place(geo, size, s, 20).x() == -1920
