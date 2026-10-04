"""The "live" mark on a tab (a badge on its icon, optionally a green wash), and the
Voice panel driving it."""
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from soundboard import theme
from soundboard.speech import tts
from soundboard.ui import icons
from soundboard.ui.livedot import (TAB_MARGIN_RIGHT, LiveTint, is_tab_live, live_color,
                                   set_tab_live, set_tint)


def entries(tabs):
    return [(e[3], e[4]) for e in icons._tabs if e[0]() is tabs]


def test_badge_comes_and_goes_and_the_tooltip_is_restored(qapp):
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Voice")
    tabs.setTabToolTip(0, "Change your voice")
    set_tab_live(tabs, 0, True, "ON", icon="voice")
    assert is_tab_live(tabs, 0)
    assert entries(tabs) == [(None, True)]                  # badge, no tint by default
    assert tabs.tabToolTip(0) == "ON\nChange your voice"
    set_tab_live(tabs, 0, True, "ON")                       # idempotent, keeps its icon
    assert tabs.tabToolTip(0) == "ON\nChange your voice"
    assert entries(tabs) == [(None, True)]
    set_tab_live(tabs, 0, False)
    assert not is_tab_live(tabs, 0)
    assert entries(tabs) == [(None, False)]
    assert tabs.tabToolTip(0) == "Change your voice"


def test_going_live_never_changes_a_tabs_size(qapp):
    """The old dot sat beside the name: it widened the tab, shoved the ones after it
    along and made the bar taller."""
    tabs = QTabWidget()
    for name in ("Sounds", "Voice", "Setup"):
        tabs.addTab(QWidget(), name)
        icons.set_tab_icon(tabs, tabs.count() - 1, "voice")
    tabs.resize(500, 200)
    tabs.show()
    qapp.processEvents()
    bar = tabs.tabBar()
    before = [bar.tabRect(i) for i in range(3)], bar.sizeHint()
    try:
        for tint in (False, True):
            set_tint(tabs, tint)
            set_tab_live(tabs, 1, True, "ON")
            qapp.processEvents()
            assert ([bar.tabRect(i) for i in range(3)], bar.sizeHint()) == before
            set_tab_live(tabs, 1, False)
    finally:
        tabs.close()


def green_pixels(bar: QTabBar, index: int) -> int:
    """How many pixels of the tab are close to the live colour (badge, wash)."""
    img = bar.grab().toImage()
    want = QColor(live_color())
    r = bar.tabRect(index)
    return sum(1 for y in range(r.top(), r.bottom() + 1) for x in range(r.left(), r.right() + 1)
               if all(abs(a - b) < 40 for a, b in
                      zip(img.pixelColor(x, y).getRgb()[:3], want.getRgb()[:3])))


def wash_pixels(bar: QTabBar, index: int) -> int:
    """Pixels inside the tab that the wash turned green-ish (green above red and blue)."""
    img = bar.grab().toImage()
    r = bar.tabRect(index).adjusted(4, 4, -4, -4)
    n = 0
    for y in range(r.top(), r.bottom() + 1):
        for x in range(r.left(), r.right() + 1):
            c = img.pixelColor(x, y)
            n += c.green() > c.red() + 6 and c.green() > c.blue() + 6
    return n


def test_live_tab_has_a_badge_and_the_optional_wash(qapp):
    theme.apply(qapp, "Dark")
    tabs = QTabWidget()
    for name in ("Radio", "Apps"):
        tabs.addTab(QWidget(), name)
        icons.set_tab_icon(tabs, tabs.count() - 1, name.lower())
    tabs.resize(400, 200)
    tabs.show()                                   # offscreen: nothing appears
    qapp.processEvents()
    bar = tabs.tabBar()
    try:
        assert green_pixels(bar, 1) == 0
        set_tab_live(tabs, 1, True, "ON")
        qapp.processEvents()
        assert green_pixels(bar, 1) > 0 and green_pixels(bar, 0) == 0     # the badge
        plain = wash_pixels(bar, 1)
        assert bar.findChild(LiveTint) is None                            # no wash by default
        set_tint(tabs, True)
        qapp.processEvents()
        assert entries(tabs)[1] == ("ok_text", False)   # green icon, no dot: either-or
        assert wash_pixels(bar, 1) > plain + 200 and wash_pixels(bar, 0) == 0
        # the wash lines up with the tab's own box (the selected tab's underline),
        # not its margin: nothing green past its right edge
        r = bar.tabRect(1)
        img = bar.grab().toImage()
        edge = r.right() - TAB_MARGIN_RIGHT + 2
        assert all(QColor(img.pixel(edge, y)).green() <= QColor(img.pixel(edge, y)).red() + 8
                   for y in range(r.top() + 8, r.bottom() - 2))
        set_tint(tabs, False)
        qapp.processEvents()
        assert entries(tabs)[1] == (None, True)
        assert wash_pixels(bar, 1) == plain
        set_tab_live(tabs, 1, False)
        qapp.processEvents()
        assert green_pixels(bar, 1) == 0
    finally:
        tabs.close()


class FakeEngine:
    voice_chain = None


@pytest.fixture
def panel(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {})
    yield p
    p.shutdown()
    p.deleteLater()


def test_voice_panel_reports_when_it_is_changing_your_voice(panel):
    seen = []
    panel.active_changed.connect(seen.append)
    assert not panel.is_active()
    panel.fx.pick("Robot")
    assert seen[-1] is True and panel.is_active()
    panel.fx.btn_power.setChecked(False)
    assert seen[-1] is False and not panel.is_active()
    panel.speech._set_live_ui(True, "starting…")          # the computer voice counts too
    assert seen[-1] is True
    panel.speech._set_live_ui(False, "")
    assert seen[-1] is False


def test_random_voice_is_a_silly_own_mix(panel):
    import random

    from soundboard.ui.voicepanel import CUSTOM
    for seed in range(20):
        panel.fx.randomize(random.Random(seed))
        on = {t: r.state() for t, r in panel.fx.rows.items()
              if r.state().get("on") and t != "cleanup"}   # mic clean-up: yours, kept
        assert panel.fx.preset == CUSTOM and panel.fx.btn_power.isChecked()
        assert "pitch" in on and abs(on["pitch"]["semitones"]) >= 4
        assert 2 <= len(on) <= 3
        if "compressor" in on:
            assert on["compressor"]["boost"] <= 9
