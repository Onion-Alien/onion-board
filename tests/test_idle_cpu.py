"""The window's background work stays cheap: polls whose answer nobody uses are
skipped or slowed down, and animations stop while nobody can see them."""
import time

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication

from soundboard import appaudio
from test_mainwindow import window  # noqa: F401 - the real window, offscreen


def test_windows_default_output_is_only_asked_while_followed(window, monkeypatch):  # noqa: F811
    asked = []
    monkeypatch.setattr(appaudio, "default_output_name",
                        lambda: asked.append(1) or "Speakers (Realtek Audio)")
    window._default_timer.stop()
    window.cfg.mon_follows_default = False
    window._default_tick()
    assert not asked                                  # a device picked by hand: not used
    window.cfg.mon_follows_default = True
    window._ui_live = True
    window._default_tick()
    window._default_tick()
    assert len(asked) == 2                            # on screen: every tick
    window._ui_live = False
    window._default_tick()
    assert len(asked) == 2                            # in the tray: every few seconds
    window._default_at -= 10
    window._default_tick()
    assert len(asked) == 3


def test_an_unplugged_device_is_looked_for_less_often(window, monkeypatch):  # noqa: F811
    e = window.engine
    monkeypatch.setitem(e.names, "mic", "Microphone (USB Mic)")
    monkeypatch.setitem(e.errors, "mic", "device not found")
    e.mic_stream = None
    looks = []
    monkeypatch.setattr(appaudio, "endpoint_names", lambda kind: looks.append(kind) or set())
    for _ in range(10):
        window._recover_devices()
    assert len(looks) == 4                            # a few quick looks, then it waits
    window._recover_at = 0.0
    window._recover_devices()
    assert len(looks) == 5


def test_whos_listening_poll_slows_down_while_hidden(window, monkeypatch):  # noqa: F811
    polls = []
    monkeypatch.setattr(window, "_poll_voice", lambda: polls.append(1))
    window.cfg.dest = {"mode": "off", "auto": False}
    window._ui_live = True
    window._voice_tick()
    window._voice_tick()
    assert len(polls) == 2
    window._ui_live = False
    window._voice_tick()
    assert len(polls) == 2                            # nobody sees the hint
    window.cfg.dest = {"mode": "off", "auto": True}
    window._voice_tick()
    assert len(polls) == 3                            # it switches by itself: keeps up


def test_icon_glow_sets_only_the_windows_own_icon(window, monkeypatch):  # noqa: F811
    app_wide = []
    monkeypatch.setattr(QApplication, "setWindowIcon", lambda icon: app_wide.append(icon))
    monkeypatch.setattr(window, "isVisible", lambda: True)
    now = time.monotonic() + 100
    window._glow_icons(1.0, now)
    assert window._icon_step > 0 and not app_wide
    window._glow_icons(0.0, now + 1)
    assert window._icon_step == 0 and not app_wide
    window._glow_icons(0.0, now + 2, force=True)      # a theme change: every window
    assert len(app_wide) == 1


def test_mic_check_pulse_pauses_while_hidden(window):  # noqa: F811
    window._pulse.start()
    window._ui_live = True
    window._set_tick_rate()                           # not shown (offscreen): not live
    assert window._pulse.state() == QAbstractAnimation.Paused
    window.show()
    assert window._pulse.state() == QAbstractAnimation.Running
    window.hide()
    assert window._pulse.state() == QAbstractAnimation.Paused
    window._pulse.stop()
