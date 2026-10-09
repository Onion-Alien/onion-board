"""The "live" mark on a tab (a badge on its icon, or a coloured icon and the rail's bar
in the theme's live colour), and the Voice panel driving it."""
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

from soundboard import theme
from soundboard.speech import tts
from soundboard.ui import icons
from soundboard.ui.livedot import is_tab_live, live_color, set_tab_live, set_tint


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


def washed(before, after, rect) -> int:
    """Pixels inside `rect` moved towards the live colour: it's the theme's own colour,
    so "green-ish" (as it was when it was always green) doesn't say it."""
    live = QColor(live_color())
    n = 0
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            a, b = before.pixelColor(x, y), after.pixelColor(x, y)
            moved = [(q - p, w - p) for p, q, w in zip(a.getRgb()[:3], b.getRgb()[:3],
                                                       live.getRgb()[:3])]
            n += any(d for d, _ in moved) and sum(d * w for d, w in moved) > 0
    return n


def test_live_tab_has_a_badge_or_a_coloured_icon(qapp):
    """Either-or: the dot in the icon, or (tint, the default in the app) the icon in
    the live colour with no dot; the rail draws the bar beside it."""
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
        idle = bar.grab().toImage()
        set_tab_live(tabs, 1, True, "ON")
        qapp.processEvents()
        plain = bar.grab().toImage()
        assert washed(idle, plain, bar.tabRect(1)) > 0                    # the badge
        assert washed(idle, plain, bar.tabRect(0)) == 0
        set_tint(tabs, True)
        assert entries(tabs)[1] == ("live_text", False)   # coloured icon, no dot: either-or
        set_tint(tabs, False)
        qapp.processEvents()
        assert entries(tabs)[1] == (None, True)
        assert bar.grab().toImage() == plain
        set_tab_live(tabs, 1, False)
        qapp.processEvents()
        assert bar.grab().toImage() == idle
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


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_every_theme_has_its_own_readable_live_colour(name):
    """The "it's on" highlight follows the theme (it was the same green in every one):
    a switched-on button is the accent, and the live text / tab wash reads on the
    background."""
    t = theme.THEMES[name]
    assert t["live"] == t["accent"] and t["on_live"] == t["on_accent"]
    assert theme._contrast(t["live_text"], t["bg"]) >= 4.5
    css = theme.stylesheet(name)
    assert "#13a35a" not in css and "$" not in css


def test_your_own_highlight_colour_wins_over_every_theme(qapp):
    try:
        theme.apply(qapp, "Lava", "#3399ff")
        assert theme.T["live"] == "#3399ff" and theme.T["accent"] == "#ff5a1f"
        assert "#3399ff" in theme.stylesheet()
        theme.apply(qapp, "Flashbang")                     # kept when the theme changes
        assert theme.T["live"] == "#3399ff"
        assert theme._contrast(theme.T["live_text"], theme.T["bg"]) >= 4.5
        assert theme._contrast(theme.T["on_live"], "#3399ff") >= 3
        theme.apply(qapp, "Flashbang", "not a colour")     # a damaged setting: the theme's
        assert theme.live_override == "" and theme.T["live"] == theme.T["accent"]
    finally:
        theme.apply(qapp, "Dark", "")


def test_a_theme_change_after_a_colour_pick_keeps_the_buttons_in_step(qapp):
    """apply_live gives the live buttons their own stylesheet; a later theme change
    must not leave them in the old colours."""
    btn = QPushButton("Live")
    btn.setObjectName("onair")
    try:
        theme.apply(qapp, "Lava", "")
        theme.apply_live(qapp, "#3399ff")
        assert "#3399ff" in btn.styleSheet()
        theme.apply_live(qapp, "")
        theme.apply(qapp, "Ocean")
        assert theme.THEMES["Ocean"]["accent"] in btn.styleSheet()
        assert "#ff5a1f" not in btn.styleSheet()
    finally:
        theme.apply(qapp, "Dark", "")
        btn.deleteLater()
