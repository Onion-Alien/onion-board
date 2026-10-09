"""Apps recording the mic without Onion Board (soundboard.rawmic): the count check, and
its line on the real MainWindow's urgent bar (offscreen). Windows isn't asked: the
session list and the effect's stream count are fed in."""
import pytest

from soundboard import rawmic
from soundboard.appaudio import App
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

ME = 100
G = rawmic.GRACE_S


def app(pid, exe, active=True):
    return App(pid, exe, active=active)


BOARD, CHAT, GAME = app(ME, "onionboard.exe"), app(7, "voicechat.exe"), app(9, "somegame.exe")


def test_counts_matching_is_fine():
    w = rawmic.BypassWatch(me=ME)
    for t in range(20):
        assert w.update([BOARD, CHAT], 2, float(t)) == []


def test_a_raw_app_is_named_after_the_grace():
    w = rawmic.BypassWatch(me=ME)
    w.update([BOARD], 1, 0.0)
    assert w.update([BOARD, CHAT], 1, 1.0) == []          # starting up
    assert w.update([BOARD, CHAT], 1, 1.0 + G - 0.5) == []
    assert w.update([BOARD, CHAT], 1, 1.0 + G) == [CHAT]
    assert w.update([BOARD, CHAT], 2, 1.0 + G + 1) == []  # reopened the normal way


def test_a_slow_starter_never_shows():
    """The app's stream opens a few seconds before the effect's first block."""
    w = rawmic.BypassWatch(me=ME)
    w.update([BOARD], 1, 0.0)
    for t in (1.0, 2.0, 3.0):
        assert w.update([BOARD, CHAT], 1, t) == []
    assert w.update([BOARD, CHAT], 2, 4.0) == []
    assert w.update([BOARD, CHAT], 2, 40.0) == []


def test_a_blip_restarts_the_grace():
    w = rawmic.BypassWatch(me=ME)
    w.update([BOARD, CHAT], 1, 0.0)
    w.update([BOARD, CHAT], 2, G - 1)                     # the counts matched again
    assert w.update([BOARD, CHAT], 1, G + 1) == []        # short again: a new grace
    assert w.update([BOARD, CHAT], 1, 2 * G + 0.5) == []
    assert w.update([BOARD, CHAT], 1, 2 * G + 1) == [CHAT]


def test_the_newcomer_is_named_not_the_app_already_fine():
    w = rawmic.BypassWatch(me=ME)
    w.update([BOARD, CHAT], 2, 0.0)
    w.update([BOARD, CHAT, GAME], 2, 1.0)
    assert w.update([BOARD, CHAT, GAME], 2, 1.0 + G) == [GAME]


def test_an_app_reopening_raw_is_named_with_the_others():
    """No newcomer to blame (an app already fine switched to raw): every app is."""
    w = rawmic.BypassWatch(me=ME)
    w.update([BOARD, CHAT, GAME], 3, 0.0)
    w.update([BOARD, CHAT, GAME], 2, 10.0)
    assert w.update([BOARD, CHAT, GAME], 2, 10.0 + G) == [GAME, CHAT]


def test_the_board_is_never_named_and_quiet_sessions_dont_count():
    w = rawmic.BypassWatch(me=ME)
    # the board's own stream missing: nobody else to name
    assert w.update([BOARD], 0, 0.0) == [] and w.update([BOARD], 0, 2 * G) == []
    # an app that recorded earlier and stopped keeps an inactive session
    w = rawmic.BypassWatch(me=ME)
    assert w.update([BOARD, app(7, "voicechat.exe", active=False)], 1, 0.0) == []
    assert w.update([BOARD, app(7, "voicechat.exe", active=False)], 1, 3 * G) == []


def test_an_app_leaving_forgets_it():
    w = rawmic.BypassWatch(me=ME)
    w.update([BOARD, CHAT], 1, 0.0)
    assert w.update([BOARD, CHAT], 1, G) == [CHAT]
    assert w.update([BOARD], 1, G + 1) == []
    assert w.update([BOARD, CHAT], 1, G + 2) == []        # back: a new grace


# ---------------------------------------------------------------- the urgent bar

@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    w = main_window
    w.raw_watch = rawmic.BypassWatch(me=ME)
    monkeypatch.setattr(w.engine, "direct_stream", lambda: object())
    return w


def look(window, monkeypatch, apps, streams, t):
    monkeypatch.setattr(window.engine, "direct_apps", lambda: streams)
    window._on_mic_users(apps, now=t)


def test_the_bar_names_the_app(window, monkeypatch):
    look(window, monkeypatch, [BOARD, CHAT], 1, 1000.0)
    assert window.urgent_bar.isHidden()
    look(window, monkeypatch, [BOARD, CHAT], 1, 1000.0 + G)
    assert not window.urgent_bar.isHidden()
    text = window.urgent_lbl.text()
    assert text.startswith("Voicechat is using your mic without Onion Board")
    assert "bypass processing" in text and window.urgent_btn.isHidden()
    look(window, monkeypatch, [BOARD, CHAT], 2, 1000.0 + G + 2)   # fixed in the app
    assert window.urgent_bar.isHidden()


def test_hiding_it_lasts_for_that_app(window, monkeypatch):
    look(window, monkeypatch, [BOARD, CHAT], 1, 0.0)
    look(window, monkeypatch, [BOARD, CHAT], 1, G)
    window.urgent_bar.findChild(type(window.urgent_btn), "urgenthide").click()
    assert window.urgent_bar.isHidden()
    look(window, monkeypatch, [BOARD, CHAT], 1, G + 2)
    assert window.urgent_bar.isHidden()
    look(window, monkeypatch, [BOARD, CHAT, GAME], 1, G + 3)
    look(window, monkeypatch, [BOARD, CHAT, GAME], 1, 2 * G + 3)
    assert not window.urgent_bar.isHidden() and "Somegame" in window.urgent_lbl.text()


def test_off_the_mic_route_it_clears(window, monkeypatch):
    look(window, monkeypatch, [BOARD, CHAT], 1, 0.0)
    look(window, monkeypatch, [BOARD, CHAT], 1, G)
    assert not window.urgent_bar.isHidden()
    window.cfg.route = "cable"
    window._raw_tick()
    assert window.urgent_bar.isHidden() and not window.raw_watch.culprits


def test_the_tick_lists_on_a_worker(window, monkeypatch, qapp):
    from conftest import process_events
    from soundboard import appaudio
    seen = []
    monkeypatch.setattr(appaudio, "recording_apps",
                        lambda dev, mine=False: seen.append((dev, mine)) or [BOARD])
    monkeypatch.setattr(window, "_direct_not_running", lambda: False)
    monkeypatch.setattr(window.engine, "direct_apps", lambda: 1)
    window.cfg.route, window.cfg.mic_device = "mic", "Microphone (Test)"
    window._raw_tick()
    assert process_events(qapp, lambda: not window._raw_looking)
    # the board's own tick timer can fire a second look on a slow runner: same question
    assert seen and set(seen) == {("Microphone (Test)", True)}
