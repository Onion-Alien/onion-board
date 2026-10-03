"""The glowing "live" dot on a tab (and its green name), and the Voice panel driving it."""
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from soundboard import theme
from soundboard.speech import tts
from soundboard.ui import icons
from soundboard.ui.livedot import LiveDot, LiveTabStyle, is_tab_live, live_color, set_tab_live


def test_dot_comes_and_goes_and_the_tooltip_is_restored(qapp):
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Voice")
    tabs.setTabToolTip(0, "Change your voice")
    set_tab_live(tabs, 0, True, "ON", icon="voice")
    assert is_tab_live(tabs, 0)
    assert [e[3] for e in icons._tabs if e[0]() is tabs] == ["#13ce66"]   # green, once
    assert tabs.tabToolTip(0) == "ON\nChange your voice"
    set_tab_live(tabs, 0, True, "ON")                     # idempotent
    assert tabs.tabToolTip(0) == "ON\nChange your voice"
    assert len(tabs.tabBar().findChildren(LiveTabStyle)) == 1   # one style per bar
    set_tab_live(tabs, 0, False, icon="voice")
    assert not is_tab_live(tabs, 0)
    assert [e[3] for e in icons._tabs if e[0]() is tabs] == [None]
    assert tabs.tabToolTip(0) == "Change your voice"
    LiveDot().grab()                                      # paints without error


def live_pixels(bar: QTabBar, index: int) -> int:
    """How many pixels of the live colour the tab is drawn with (its name's glyphs)."""
    img = bar.grab().toImage()
    want = QColor(live_color())
    r = bar.tabRect(index)
    return sum(1 for y in range(r.top(), r.bottom() + 1) for x in range(r.left(), r.right() + 1)
               if all(abs(a - b) < 40 for a, b in
                      zip(img.pixelColor(x, y).getRgb()[:3], want.getRgb()[:3])))


def test_a_live_tab_is_named_in_the_live_colour_under_the_theme(qapp):
    """The theme's stylesheet colours every tab's name, which hides QTabBar's own
    per-tab text colour: a live tab must still come out green, selected or not, in
    the new theme's green after a theme change, and in the plain colour once off."""
    theme.apply(qapp, "Dark")
    tabs = QTabWidget()
    for name in ("Radio", "Apps"):
        tabs.addTab(QWidget(), name)
    tabs.resize(400, 200)
    tabs.show()                                   # offscreen: nothing appears
    qapp.processEvents()
    bar = tabs.tabBar()
    try:
        assert live_pixels(bar, 1) == 0
        set_tab_live(tabs, 1, True, "ON")
        assert live_pixels(bar, 1) > 0 and live_pixels(bar, 0) == 0
        tabs.setCurrentIndex(1)                   # a selected tab has its own colour rule
        assert live_pixels(bar, 1) > 0
        theme.apply(qapp, "Light")                # a darker green there
        assert live_color() != "#13ce66" and live_pixels(bar, 1) > 0
        set_tab_live(tabs, 1, False)
        assert live_pixels(bar, 1) == 0
    finally:
        theme.apply(qapp, "Dark")
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
        on = {t: r.state() for t, r in panel.fx.rows.items() if r.state().get("on")}
        assert panel.fx.preset == CUSTOM and panel.fx.btn_power.isChecked()
        assert "pitch" in on and abs(on["pitch"]["semitones"]) >= 4
        assert 2 <= len(on) <= 3
        if "compressor" in on:
            assert on["compressor"]["boost"] <= 9
