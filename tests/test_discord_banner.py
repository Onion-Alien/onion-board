"""Discord's own settings wiping out sounds (soundboard.discordcfg): the urgent bar in
the real MainWindow (offscreen) and the Discord guide's advice on the mic vs the cable.
Discord isn't really read: a fake store sits in the test's own folder."""
import pytest

from soundboard import discordcfg as dc
from soundboard.ui import chatguide
from test_discordcfg import folder, store
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def found(**over):
    return [dc.parse({"default": dict({"activeInputProfile": "CUSTOM",
                                       "noiseCancellation": False, "echoCancellation": False,
                                       "automaticGainControl": False,
                                       "modeOptions": {"vadUseKrisp": False}}, **over)})]


def test_studio_on_the_mic_gets_the_urgent_bar(window, monkeypatch):
    monkeypatch.setattr(chatguide, "on_mic", lambda mw: True)
    window._on_discord((found(activeInputProfile="STUDIO"), ("sig",)))
    assert not window.urgent_bar.isHidden()
    assert "Studio" in window.urgent_lbl.text() and "Custom" in window.urgent_lbl.text()
    assert window.urgent_btn.text() == "Fix Discord"
    guides = []
    monkeypatch.setattr(window, "show_chat_guide", guides.append)
    window.urgent_btn.click()
    assert guides == ["discord"]
    window._on_discord((found(), ("sig2",)))          # fixed in Discord
    assert window.urgent_bar.isHidden()


def test_studio_on_the_cable_is_fine_but_krisp_is_not(window, monkeypatch):
    monkeypatch.setattr(chatguide, "on_mic", lambda mw: False)
    window._on_discord((found(activeInputProfile="STUDIO"), ("a",)))
    assert window.urgent_bar.isHidden()
    window._on_discord((found(noiseCancellation=True), ("b",)))
    assert not window.urgent_bar.isHidden() and "Krisp" in window.urgent_lbl.text()


def test_unchanged_files_and_no_discord(window, monkeypatch):
    monkeypatch.setattr(chatguide, "on_mic", lambda mw: True)
    window._on_discord((found(noiseCancellation=True), ("a",)))
    assert not window.urgent_bar.isHidden()
    window._on_discord((None, ("a",)))               # files unchanged: nothing re-read
    assert not window.urgent_bar.isHidden()
    window._on_discord(([], None))                   # Discord closed
    assert window.urgent_bar.isHidden()


def test_hiding_it_lasts_until_the_settings_change(window, monkeypatch):
    monkeypatch.setattr(chatguide, "on_mic", lambda mw: True)
    window._on_discord((found(echoCancellation=True), ("a",)))
    window.urgent_bar.findChild(type(window.urgent_btn), "urgenthide").click()
    assert window.urgent_bar.isHidden()
    window._on_discord((found(echoCancellation=True, automaticGainControl=True), ("b",)))
    assert not window.urgent_bar.isHidden()          # something new is wrong


def test_the_tick_reads_on_a_worker(window, monkeypatch, qapp):
    from conftest import process_events
    from soundboard import appaudio
    (folder() / "000005.log").write_bytes(store(activeInputProfile="STUDIO"))
    monkeypatch.setattr(chatguide, "on_mic", lambda mw: True)
    monkeypatch.setattr(appaudio, "_process_table", lambda: {7: (1, "discord.exe")})
    window._discord_tick()
    assert process_events(qapp, lambda: window.discord_found)
    assert window.discord_problems() == [dc.STUDIO]
    assert not window._discord_reading


def test_guide_on_the_mic_says_custom_not_studio(window, monkeypatch):
    """Straight into my mic, Studio skips Onion Board: the guide must never send people
    there, and it shows what their Discord is set to."""
    (folder() / "000005.log").write_bytes(store(activeInputProfile="STUDIO"))
    g = chatguide.DiscordGuide(window, window, "Microphone (G733)", kept=True)
    text = " ".join(lbl.text() for lbl in g.findChildren(chatguide.QLabel))
    assert "choose <b>Custom</b>" in text and "choose <b>Studio</b>" not in text
    assert "Bypass System Audio Input Processing" in text
    assert not g.settings.isHidden() and "skips Onion Board" in g.settings.text()
    for issue in ("not_heard", "suppression", "agc"):
        html = chatguide.result_html({"issues": [issue]}, "Mic", kept=True)
        assert "<b>Studio</b>." not in html and "Custom" in html, issue
    g.done(0)


def test_guide_on_the_cable_still_says_studio(window):
    (folder() / "000005.log").write_bytes(store(activeInputProfile="STUDIO"))
    g = chatguide.DiscordGuide(window, window, "CABLE Output")
    text = " ".join(lbl.text() for lbl in g.findChildren(chatguide.QLabel))
    assert "choose <b>Studio</b>" in text
    assert "right for your sounds" in g.settings.text()
    g.done(0)


def test_every_problem_has_words():
    for p in dc.ORDER:
        assert p in chatguide.SETTING_FIXES
        from soundboard.ui.mainwindow import DISCORD_URGENT
        assert "{name}" in DISCORD_URGENT[p]
