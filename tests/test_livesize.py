"""Dragging the window's edge: each step fits with Qt's cached sizes, letting go fits
once more measuring the whole window fresh (ui/livesize.py, Fitter.live)."""
import ctypes
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLayout

from soundboard.ui import livesize, responsive
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
