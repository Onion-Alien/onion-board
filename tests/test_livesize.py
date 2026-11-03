"""Dragging the window's edge: each step fits with Qt's cached sizes, letting go fits
once more measuring the whole window fresh (ui/window/livesize.py, Fitter.live)."""
import ctypes
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLayout

from soundboard.ui.window import livesize, responsive
from test_mainwindow import window  # noqa: F401 - the real window, offscreen
from test_responsive import LONG, SHORT, header


def test_a_live_fit_does_not_walk_every_layout(qapp):
    """Finding and invalidating every layout made Qt measure the whole window again on
    each mouse move of a drag (3-10 ms of each step)."""
    root, pill = header(LONG)
    f = responsive.Fitter(root)
    f.add(10, "w", lambda short: pill.setText(SHORT if short else LONG))
    root.show()
    qapp.processEvents()
    real, walks = root.findChildren, []
    root.findChildren = lambda t: (walks.append(t), real(t))[1]
    f.fit(QSize(2000, 400))
    assert QLayout in walks          # not dragging: measured fresh, as before
    walks.clear()
    f.live = True
    f.fit(QSize(10, 400))            # dragged narrow: the step still goes...
    assert pill.text() == SHORT
    f.fit(QSize(2000, 400))          # ...and comes back
    assert pill.text() == LONG
    assert QLayout not in walks
    root.deleteLater()


def test_letting_go_fits_again_measuring_fresh(window, monkeypatch):  # noqa: F811
    fit = window.fitctl
    refits = []
    monkeypatch.setattr(fit, "_refit", lambda: refits.append(fit._fit.live))
    fit.live(True)
    assert fit._fit.live and refits == []
    fit.live(True)                   # (a second start changes nothing)
    fit.live(False)
    assert not fit._fit.live and refits == [False]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' size/move loop")
def test_the_drag_is_read_from_windows_messages():
    from ctypes import wintypes
    msg = wintypes.MSG()
    for kind, want in ((livesize.WM_ENTERSIZEMOVE, 1), (livesize.WM_EXITSIZEMOVE, -1),
                       (0x0005, 0)):   # WM_SIZE: a step, not the drag's start or end
        msg.message = kind
        assert livesize.drag_edge(ctypes.addressof(msg)) == want


def test_a_drag_measures_fresh_before_the_mini_player(window, monkeypatch):  # noqa: F811
    """A stale cached size says the window doesn't fit: measured fresh, it does, so it
    stays the whole window rather than flashing into the mini player mid-drag."""
    real = responsive.Fitter.fit
    monkeypatch.setattr(responsive.Fitter, "fit", lambda self, size: (
        QSize(size.width() + 500, size.height()) if self.live else real(self, size)))
    window.show()                            # offscreen: nothing appears
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1180, 720)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    window.fitctl.live(True)
    window.fitctl._refit()
    assert not window.fitctl.is_mini() and window.fitctl._fit.live


def _stuck(window):  # noqa: F811
    """The search button and the cards / list switch hidden with a "back once the
    window is wider than this" size it never reaches: the state a few resizes with the
    sidebar shut and opened could leave."""
    f = window.fitctl._fit
    for step, _axis, run in window.fitctl._bar_steps:
        if step in (63, 65):
            i = next(i for i, s in enumerate(f.steps) if s[2] is run)
            f._apply(i, True)
            f._at[i] = (99999, 99999, False)
    assert window.btn_yt.isHidden() and window.pad_view_toggle.isHidden()


def test_a_resize_in_one_go_brings_back_what_fits(window):  # noqa: F811
    """Double-clicking the title bar (maximise / restore) or an edge has no drag to let
    go of: it tries everything again itself, as letting go does."""
    window.show()                            # offscreen: nothing appears
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1500, 860)
    window.fitctl._refit()
    _stuck(window)
    window.resize(1500, 860 - 300)           # one jump, no drag
    assert not window.btn_yt.isHidden() and not window.pad_view_toggle.isHidden()


def test_a_drag_step_does_not_try_everything_again(window):  # noqa: F811
    """Each mouse move of a drag is a small step: trying every hidden part again on
    each made them flash. Letting go does it once."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1500, 860)
    window.fitctl._refit()
    _stuck(window)
    window.resize(1500 - 3, 860)
    assert window.btn_yt.isHidden()
    window.fitctl.live(True)
    window.resize(1500 - 300, 860)           # dragging: no retry mid-drag
    assert window.btn_yt.isHidden()
    window.fitctl.live(False)                # let go
    assert not window.btn_yt.isHidden() and not window.pad_view_toggle.isHidden()


def test_a_squeezed_window_settles_without_a_resize(window, qapp):  # noqa: F811
    """Squeezed with no edge dragged and no jump to come (a maximized window can't
    grow): once it's idle, everything that fits comes back by itself, and it checks
    only once for a size (no endless refits)."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1500, 860)
    window.fitctl._refit()
    qapp.processEvents()
    _stuck(window)
    window.fitctl._refit()                   # any refit at the same size: settles next
    assert window.btn_yt.isHidden()
    qapp.processEvents()
    assert not window.btn_yt.isHidden() and not window.pad_view_toggle.isHidden()
    fits = []
    real = window.fitctl._fit.fit
    window.fitctl._fit.fit = lambda size: (fits.append(size), real(size))[1]
    for _ in range(3):
        window.fitctl._refit()
        qapp.processEvents()
    assert len(fits) <= 6                    # each refit once or twice, no retry loop
