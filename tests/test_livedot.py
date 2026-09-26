"""The glowing "live" dot on a tab, and the Voice panel driving it."""
import pytest
from PySide6.QtWidgets import QTabWidget, QWidget

from soundboard.speech import tts
from soundboard.ui import icons
from soundboard.ui.livedot import LiveDot, is_tab_live, set_tab_live


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
    set_tab_live(tabs, 0, False, icon="voice")
    assert not is_tab_live(tabs, 0)
    assert [e[3] for e in icons._tabs if e[0]() is tabs] == [None]
    assert tabs.tabToolTip(0) == "Change your voice"
    LiveDot().grab()                                      # paints without error


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
