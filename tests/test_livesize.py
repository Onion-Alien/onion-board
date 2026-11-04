"""Dragging the window's edge: each step fits with Qt's cached sizes, letting go fits
once more measuring the whole window fresh (ui/window/livesize.py, Fitter.live)."""
import ctypes
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QLayout

from soundboard.ui.window import fitcontrol, livesize, responsive
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


def _idle(qapp):
    """Let the settle timer run out (SETTLE_MS is 0 in these tests)."""
    for _ in range(10):
        qapp.processEvents()


@pytest.mark.parametrize("maximized", [False, True])
def test_a_squeezed_window_settles_by_itself(window, qapp, monkeypatch, maximized):  # noqa: F811
    """With no edge dragged and no jump to come: once it's idle, everything that fits
    comes back by itself, in a normal window as in a maximized one, and it checks only
    once (no endless refits)."""
    monkeypatch.setattr(fitcontrol, "SETTLE_MS", 0)
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.showMaximized() if maximized else window.resize(1800, 860)
    _idle(qapp)
    window.fitctl._refit()
    _idle(qapp)
    _stuck(window)
    if maximized:
        window.fitctl._refit()               # any refit at the same size: settles next
    else:
        window.fitctl.window_activated()     # it can grow, so: clicked back into
    assert window.btn_yt.isHidden()
    _idle(qapp)
    assert not window.btn_yt.isHidden() and not window.pad_view_toggle.isHidden()
    _idle(qapp)                              # (a last try for what's left, if anything)
    fits = []
    real = window.fitctl._fit.fit
    window.fitctl._fit.fit = lambda size: (fits.append(size), real(size))[1]
    _idle(qapp)
    assert not fits                          # idle: no retry loop
    for _ in range(3):
        window.fitctl._refit()
        _idle(qapp)
    assert len(fits) <= 6                    # each refit once or twice, nothing more


def test_room_needed_for_a_moment_leaves_nothing_squeezed(window, qapp, monkeypatch):  # noqa: F811
    """Something asks for more room, then stops, and the window never changes size: what
    gave way comes back without anyone touching an edge."""
    monkeypatch.setattr(fitcontrol, "SETTLE_MS", 0)
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1800, 860)
    _idle(qapp)
    window.fitctl._refit()
    assert window.fitctl._fit.compact_count() == 0
    extra = QLabel(window.sounds_toolbar)    # a part that takes room in the top bar
    extra.setFixedWidth(1100)
    window.sounds_toolbar.layout().addWidget(extra)
    extra.show()
    window.fitctl._refit()
    assert window.fitctl._fit.compact_count() and not window.fitctl.is_mini()
    extra.hide()                             # (no refit: only Qt's layout request)
    _idle(qapp)
    assert window.fitctl._fit.compact_count() == 0
    assert window.btn_add.text() == "Add"
    assert not window.btn_yt.isHidden() and not window.pad_view_toggle.isHidden()


def test_the_mini_player_goes_once_the_board_fits_again(window, qapp, monkeypatch):  # noqa: F811
    """The board needed more than a normal window for a moment: the mini player took over,
    and it goes again by itself at the same size."""
    monkeypatch.setattr(fitcontrol, "SETTLE_MS", 0)
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1800, 756)
    _idle(qapp)
    window.fitctl._refit()
    assert window.fitctl._fit.compact_count() == 0
    extra = QLabel(window.sounds_toolbar)
    extra.setFixedWidth(2000)
    window.sounds_toolbar.layout().addWidget(extra)
    extra.show()
    window.fitctl._refit()
    assert window.fitctl.is_mini()
    extra.hide()
    _idle(qapp)
    assert not window.fitctl.is_mini()
    assert window.fitctl._fit.compact_count() == 0
    assert window.btn_add.text() == "Add"


def test_the_log_names_what_made_a_normal_window_the_mini_player(window, qapp, caplog):  # noqa: F811
    """A surprise mini player says which part asked for the room, by name, never its text."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1800, 756)
    _idle(qapp)
    window.fitctl._refit()
    extra = QLabel("a sound's name", window.sounds_toolbar)
    extra.setObjectName("greedy")
    extra.setFixedWidth(2000)
    window.sounds_toolbar.layout().addWidget(extra)
    extra.show()
    with caplog.at_level("INFO", logger="soundboard.ui.window.fitcontrol"):
        window.fitctl._refit()
    assert window.fitctl.is_mini()
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("tallest:"))
    assert "greedy:2000" in line.split("widest:")[1]
    assert "a sound's name" not in line
    extra.hide()


def test_a_tall_page_never_takes_the_top_bar(window, qapp):  # noqa: F811
    """A page too tall for the window: a row of buttons gives up width, never height, so
    they stay. They hid for nothing, and stayed hidden after the mini player."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1500, 860)
    _idle(qapp)
    f = window.fitctl._fit
    f.need = lambda: QSize(800, 5000)        # no height fits it: every step that can help
    f.fit(window._pages.size())
    gone = {id(f.steps[i][2]) for i in f._at}
    del f.need
    assert not gone & {id(run) for _step, _axis, run in window.fitctl._bar_steps}
    assert not window.btn_yt.isHidden() and window.btn_more.text() == "Library"
    assert window.btn_add.text() == "Add" and not window.pad_view_toggle.isHidden()


def test_held_pads_are_laid_out_once_when_let_go(qapp):
    """Each step of a drag stretched every pad to the new width: all of them resized
    again per pixel, columns coming and going under the mouse."""
    from test_pad_speed import grid_of
    grid = grid_of(12)
    grid.show()
    qapp.processEvents()
    shape, laid = grid._shape, []
    grid.laid_out.connect(lambda: laid.append(1))
    grid.hold(True)
    grid.resize(grid.width() + 300, 600)
    grid.resize(grid.width() + 10, 600)
    assert grid._shape == shape and not laid      # held: nothing moved
    grid.hold(False)                              # let go: laid out, once
    assert grid._shape != shape and len(laid) == 1
    shape = grid._shape
    grid.resize(grid.width() + 300, 600)          # not held: right away, as before
    assert grid._shape != shape
    grid.hold(True)
    grid.hold(False)                              # nothing waited: nothing to do
    assert len(laid) == 2
    grid.deleteLater()


def test_a_dragged_edge_shows_a_still_picture_until_it_rests(window, qapp, monkeypatch):  # noqa: F811
    """Qt painted the whole window for each mouse move of a drag (~12 ms with a board of
    pads): a fast mouse kept a CPU core busy. While the edge moves, a still picture of
    the window is shown; it's laid out once when the edge rests, or is let go."""
    window.show()                                 # offscreen: nothing appears
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(880, 720)
    qapp.processEvents()
    at_880 = window.grid._shape                   # the layout without any drag
    window.resize(1180, 720)
    qapp.processEvents()
    live, grid = window.liveresize, window.grid
    refits = []
    real = window.fitctl._refit
    monkeypatch.setattr(window.fitctl, "_refit", lambda: (refits.append(1), real())[1])
    shape = grid._shape
    live.drag(True)
    assert live._still is None                    # held, no step yet (a title bar move)
    window.resize(900, 720)
    still = live._still
    assert still is not None and still.isVisible() and live._rest.isActive()
    window.resize(880, 720)
    assert live._still is still                   # one picture for the whole move
    assert grid._shape == shape and not refits    # nothing laid out mid-drag
    live._rest.timeout.emit()                     # the edge rested
    qapp.processEvents()
    assert live._still is None and not still.isVisible()
    assert grid._shape == at_880 and len(refits) == 1   # as if it had never been dragged
    window.resize(1000, 720)                      # moving again: a fresh picture
    window.resize(1180, 720)
    assert live._still is not None and grid._shape != shape
    live.drag(False)                              # let go: laid out for its size
    qapp.processEvents()
    assert live._still is None and grid._shape == shape and not window.fitctl._fit.live
    window.resize(880, 720)                       # no drag: laid out right away
    qapp.processEvents()
    assert live._still is None and grid._shape == at_880


class _FakeUser32:
    def __init__(self):
        self.moved = []

    def GetWindowRect(self, hwnd, ref):  # noqa: N802 - the Win32 name
        r = ref._obj
        r.left, r.top, r.right, r.bottom = 10, 10, 1010, 610
        return True

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):  # noqa: N802
        self.moved.append((x, y, w, h))
        return True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' size/move loop")
def test_a_dragged_edge_takes_a_new_size_at_most_every_step(window, monkeypatch):  # noqa: F811
    """A size asked for too soon is held back, and given a moment later (or as the edge
    is let go), so the window still ends up where the edge stopped."""
    from ctypes import wintypes
    fake = _FakeUser32()
    monkeypatch.setattr(livesize, "_user32", lambda: fake)
    live = window.liveresize
    rect = wintypes.RECT(10, 10, 1200, 610)
    msg = wintypes.MSG()
    msg.message, msg.lParam = livesize.WM_SIZING, ctypes.addressof(rect)
    assert not live.sizing(ctypes.addressof(msg))        # the first size: as asked
    assert (rect.left, rect.right) == (10, 1200)
    rect.right = 1150
    assert live.sizing(ctypes.addressof(msg))            # too soon: held back...
    assert (rect.left, rect.right) == (10, 1010)         # ...the window keeps its size
    assert live._step.isActive() and not fake.moved
    live.dragging = True
    live.drag(False)                                     # let go: it gets it
    assert fake.moved == [(10, 10, 1140, 600)]
    live.flush()                                         # nothing held: nothing to do
    assert len(fake.moved) == 1
    msg.message = 0x0005                                 # anything else passes through
    assert not live.sizing(ctypes.addressof(msg))
