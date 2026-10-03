"""The headphones output follows Windows' default output: switch Windows from the
headset to the speakers with the app open and the sounds come out of the speakers,
unless another device was picked for the headphones by hand."""
import pytest

from soundboard import appaudio
from soundboard import engine as eng
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

OUTS = ["Headphones  (Gaming Headset)", "Speakers (Realtek Audio)",
        "CABLE Input (VB-Audio Virtual Cable)"]


@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    devs = [{"index": i, "name": n} for i, n in enumerate(OUTS)]
    monkeypatch.setattr(eng, "list_devices", lambda kind: devs if kind == "output" else [])
    monkeypatch.setattr(eng, "list_name", lambda i: OUTS[i])
    opened = []
    monkeypatch.setattr(eng.Engine, "set_mon_device", lambda self, n: opened.append(n))
    main_window.opened = opened
    main_window._default_timer.stop()
    return main_window


def windows_default(monkeypatch, name):
    monkeypatch.setattr(appaudio, "default_output_name", lambda: name)


def test_the_headphones_follow_windows_default_output(window, monkeypatch):
    windows_default(monkeypatch, "Headphones (Gaming Headset)")   # spaced its own way
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[0]
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[1] and window.opened[-1] == OUTS[1]
    assert window.cb_mon.currentData() == OUTS[1]
    assert "Speakers" in window.status.text()


def test_a_device_picked_by_hand_stays(window, monkeypatch):
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    window.cb_mon.setCurrentIndex(window.cb_mon.findData(OUTS[0]))
    window.on_device(window.cb_mon, "mon_device")      # the headset, by hand
    assert not window.cfg.mon_follows_default
    windows_default(monkeypatch, "Headphones (Gaming Headset)")
    window._follow_default_output()
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[0]
    window.cb_mon.setCurrentIndex(window.cb_mon.findData(OUTS[1]))
    window.on_device(window.cb_mon, "mon_device")      # Windows' default: follows again
    assert window.cfg.mon_follows_default


def test_the_cable_as_windows_default_isnt_followed(window, monkeypatch):
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    windows_default(monkeypatch, "CABLE Input (VB-Audio Virtual Cable)")
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[1]


def test_the_default_when_the_app_starts(window, monkeypatch):
    window.cfg.mon_device = OUTS[0]
    window._default_out = "Speakers (Realtek Audio)"   # changed while the app was closed
    window._init_devices()
    assert window.cfg.mon_device == OUTS[1]
