"""The once-a-second status check redraws only what changed. Each restyle or refit runs
every style rule and event filter again; on a PC short of memory that held the window
for seconds, once a second."""
import pytest
from PySide6.QtCore import QEvent, QObject, QRect
from PySide6.QtGui import QHideEvent, QPaintEvent, QRegion, QShowEvent
from PySide6.QtWidgets import QPushButton

from soundboard.control import winkeys
from soundboard.ui.kit.glow import Glow
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def _second_ticks(window, n):
    """`n` of the tick's once-a-second checks, back to back."""
    every = max(1, 1000 // window.timer.interval())
    for i in range(1, n + 1):
        window.tickctl._tick_n = i * every - 1   # (tick adds the 1)
        window.tickctl.tick()


def test_a_device_problem_with_drop_outs_isnt_redrawn_every_second(window, monkeypatch):
    e = window.engine
    window._attaching = False
    window._settle_until = 0.0
    monkeypatch.setattr(e, "check_streams", lambda: [])
    monkeypatch.setattr(e, "errors_snapshot", lambda: {"mon": "the device is gone"})
    monkeypatch.setitem(e.xruns, next(iter(e.xruns)), 3)
    window.statusctl._update_status()   # what a device change does: said once
    calls = []
    real = window.statusctl._update_status
    monkeypatch.setattr(window.statusctl, "_update_status",
                        lambda: (calls.append(1), real())[1])
    _second_ticks(window, 5)
    assert calls == []   # (the count of drop-outs was never marked as told: every tick)


def test_the_mini_players_connection_is_restyled_only_when_it_changes(window, monkeypatch):
    ctl = window.statusctl
    pill = window.mini_connection
    ctl._update_flow()
    restyles = []
    real = pill.setProperty
    monkeypatch.setattr(pill, "setProperty",
                        lambda k, v: (restyles.append(k), real(k, v))[1])
    for _i in range(5):
        ctl._update_flow()
    assert restyles == []
    text = pill.text()
    window.cfg.route = "off" if window.cfg.route != "off" else "mic"   # a real change
    ctl._update_flow()
    assert pill.text() != text and restyles == ["state"]


def test_a_new_theme_still_repaints_the_mini_players_connection(window):
    ctl = window.statusctl
    ctl._update_flow()
    window.mini_connection.setToolTip("")   # (a redraw with no change leaves it)
    ctl._update_flow()
    assert window.mini_connection.toolTip() == ""
    window.themectl.set_live_color("#ff0000")
    assert window.mini_connection.toolTip() == window._pill_long


class _NoType:
    """An event whose type() mustn't be asked: the filter knows it from its class."""

    def type(self):
        raise AssertionError("type() asked for an event the filter doesn't handle")


class _Paint(_NoType, QPaintEvent):
    pass


def test_glow_skips_events_it_doesnt_handle_by_their_class(qapp, monkeypatch):
    btn = QPushButton("go")
    glow = Glow(btn)
    painted, applied = [], []
    monkeypatch.setattr(glow, "_paint", lambda k: painted.append(k))
    monkeypatch.setattr("soundboard.ui.kit.glow.QTimer.singleShot",
                        lambda ms, ctx, fn: applied.append(fn))
    assert glow.eventFilter(btn, _Paint(QRegion(QRect(0, 0, 4, 4)))) is False
    assert painted == [] and applied == []
    glow.eventFilter(btn, QShowEvent())
    glow.eventFilter(btn, QHideEvent())
    assert len(applied) == 2
    glow.eventFilter(btn, QEvent(QEvent.Type.StyleChange))
    glow.eventFilter(btn, QEvent(QEvent.Type.PaletteChange))
    glow.eventFilter(btn, QEvent(QEvent.Type.FontChange))
    assert painted == [1.0, 1.0]


class _Plain(_NoType, QEvent):
    def __init__(self):
        super().__init__(QEvent.Type.ToolTipChange)


def test_the_hotkeys_app_filter_skips_anything_but_keys_by_their_class(qapp):
    hk = winkeys.Hotkeys.__new__(winkeys.Hotkeys)
    QObject.__init__(hk)
    hk._typing_combos = winkeys.typing_combos({"ctrl+alt+s": "stop"}, True)
    target = QPushButton()
    assert hk.eventFilter(target, _Plain()) is False
    assert hk.eventFilter(target, _Paint(QRegion(QRect(0, 0, 4, 4)))) is False
