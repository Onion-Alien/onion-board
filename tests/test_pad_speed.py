"""The sounds grid staying quick with hundreds of pads: the grid laid out once per
regrid, pictures scaled once per size, the footer worked out once, and typing in the
search box / dragging Pad size not regridding on every step. Work is counted, not
timed, so a slow test runner can't make these flaky."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from soundboard import midi, thumbs
from soundboard.library import SoundMeta
from soundboard.ui import widgets
from soundboard.ui.widgets import Pad, PadGrid

from conftest import process_events
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def make_image(path, w=480, h=300, color="#2040ff"):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return str(path)


def grid_of(n, width=100):
    grid = PadGrid()
    grid.pad_w = width
    grid.resize(8 + 4 * width + 3 * 10, 600)   # four a row
    grid.set_pads([Pad(SoundMeta(id=f"s{i}", name=f"Sound {i}", file=""), width)
                   for i in range(n)])
    return grid


# ---------------------------------------------------------------------- the grid

def test_regrid_adds_pads_with_the_layout_switched_off(qapp):
    """Each pad shown into a live grid laid the whole grid out again: clearing a
    search over 600 pads took 85-145 ms. The layout is off until they're all in."""
    grid = grid_of(12)
    for p in grid.pads[3:]:
        p.setProperty("filtered", True)
    grid.relayout(force=True)
    seen = []
    real = grid.grid.addWidget
    grid.grid.addWidget = lambda *a: (seen.append(grid.grid.isEnabled()), real(*a))
    for p in grid.pads:
        p.setProperty("filtered", False)
    grid.relayout(force=True)
    assert len(seen) == 12 and not any(seen)
    assert grid.grid.isEnabled()
    # ...and laid out once at the end, four a row as before
    for i, p in enumerate(grid.pads):
        assert grid.grid.getItemPosition(grid.grid.indexOf(p))[:2] == (i // 4, i % 4)
        assert not p.isHidden()
    assert grid.pads[5].geometry().topLeft() == grid.pads[1].geometry().topLeft() + \
        grid.pads[4].geometry().topLeft() - grid.pads[0].geometry().topLeft()


def test_a_new_pad_size_with_the_same_columns_only_resizes(qapp):
    """Pad size / a window resize that keeps the columns: the pads stay where they
    are in the grid, only bigger or smaller (no taking out and putting back 600)."""
    grid = grid_of(8)
    added = []
    real = grid.grid.addWidget
    grid.grid.addWidget = lambda *a: (added.append(a), real(*a))
    grid.set_pad_width(95)
    assert added == [] and grid.grid.isEnabled()
    a, b, c = grid.pads[0], grid.pads[1], grid.pads[4]
    assert a.width() == 95 and b.geometry().left() == a.geometry().right() + 1 + 10
    assert c.geometry().top() == a.geometry().bottom() + 1 + 10
    grid.pads[2].setProperty("filtered", True)   # another set shown: placed again
    grid.relayout(force=True)
    assert len(added) == 7 and grid.pads[2].isHidden()


# ---------------------------------------------------------------------- pictures

def test_fitted_picture_is_made_once_per_size_screen_and_shade(qapp, tmp_path, monkeypatch):
    path = make_image(tmp_path / "a.png")
    loads = []
    real = thumbs.pixmap
    monkeypatch.setattr(thumbs, "pixmap", lambda p: (loads.append(p), real(p))[1])
    a = thumbs.fitted(path, 146, 89, 1.0, widgets.PIC_SHADE)
    assert a is not None and (a.width(), a.height()) == (146, 89)
    assert thumbs.fitted(path, 146, 89, 1.0, widgets.PIC_SHADE) is a and len(loads) == 1
    b = thumbs.fitted(path, 292, 178, 2.0, widgets.PIC_SHADE)          # another screen
    assert b is not a and b.devicePixelRatio() == 2.0
    assert thumbs.fitted(path, 146, 89, 1.0, widgets.PIC_SHADE_HOVER) is not a   # hover
    assert thumbs.fitted(path, 150, 89, 1.0, widgets.PIC_SHADE) is not a         # resized
    round_ = thumbs.fitted(path, 146, 89, 1.0, widgets.PIC_SHADE, 12).toImage()
    assert round_.pixelColor(0, 0).alpha() == 0          # the card shows at the corners
    assert round_.pixelColor(73, 44).alpha() == 255
    thumbs.forget(path)     # replaced or removed: every size of it goes
    assert not [k for k in thumbs._fitted if k[0] == path]
    assert thumbs.fitted(str(tmp_path / "missing.png"), 10, 10, 1.0) is None


def test_fitted_pictures_are_capped_by_size(qapp, tmp_path, monkeypatch):
    path = make_image(tmp_path / "a.png")
    cap = 3 * 106 * 60 * 4    # three of the biggest below
    monkeypatch.setattr(thumbs, "MAX_FITTED_BYTES", cap)
    for w in range(100, 106):
        thumbs.fitted(path, w, 60, 1.0)
    assert thumbs._fitted_bytes <= cap
    assert len([k for k in thumbs._fitted if k[0] == path]) == 3   # the newest kept
    assert (path, 105, 60, 1.0, (), 0) in thumbs._fitted
    thumbs.forget(path)


def test_pad_paints_its_picture_without_scaling_it_again(qapp, tmp_path, monkeypatch):
    """Scrolling a board of pictures smooth-scaled each one on every paint (77 ms a
    step). A pad draws a copy made for its size, rebuilt only when that changes."""
    m = SoundMeta(id="p", name="Boom", file="f", duration=1.0,
                  image=make_image(tmp_path / "a.png"))
    pad = Pad(m, 150)
    pad.state = "ready"
    made = []
    real = thumbs.fitted

    def counting(*a):
        before = len(thumbs._fitted)
        pm = real(*a)
        made.append(len(thumbs._fitted) > before)
        return pm
    monkeypatch.setattr(thumbs, "fitted", counting)
    for _ in range(3):
        img = pad.grab().toImage()
    assert made == [True, False, False]
    mid = img.pixelColor(img.width() // 2, img.height() // 3)
    assert mid.blue() > mid.red()                  # the picture shows through the shade
    pad.hover = True                               # lighter shade under the mouse
    lit = pad.grab().toImage().pixelColor(img.width() // 2, img.height() // 3)
    assert made[-1] and lit.blue() > mid.blue()
    pad.hover = False
    pad.setFixedSize(180, widgets.pad_height(180))   # resized: made again for the size
    pad.grab()
    assert made[-1]
    m.image = make_image(tmp_path / "b.png", color="#ff2020")   # a new picture
    img = pad.grab().toImage()
    assert made[-1]
    mid = img.pixelColor(img.width() // 2, img.height() // 3)
    assert mid.red() > mid.blue()
    thumbs.forget(m.image)


def test_pad_footer_is_worked_out_only_when_it_changes(qapp, monkeypatch):
    m = SoundMeta(id="p", name="Boom", file="f", duration=1.0,
                  hotkey=midi.make("note", 36, "Pads"))
    pad = Pad(m, 200)
    pad.state = "ready"
    calls = []
    real = midi.short
    monkeypatch.setattr(midi, "short", lambda c: (calls.append(c), real(c))[1])
    for _ in range(3):
        pad.grab()
    assert len(calls) == 1
    assert pad._foot[1][1] == "1.0s" and pad._foot[1][2][0] == "♪36"
    m.loop = True
    pad.grab()
    assert len(calls) == 2 and pad._foot[1][1] == "⟳ 1.0s"


def test_pad_colours_follow_the_theme(qapp, monkeypatch):
    from soundboard import theme
    first = widgets.pad_colours()
    assert widgets.pad_colours() is first          # made once, not on every paint
    monkeypatch.setitem(theme.T, "card", "#123456")
    assert widgets.pad_colours()["card"] == QColor("#123456")


# ---------------------------------------------------------------------- the window

def test_typing_in_search_filters_once_it_pauses(qapp, window):  # noqa: F811
    calls = []
    real = window.apply_filter
    window.apply_filter = lambda t, lazy=False: (calls.append(t), real(t, lazy))
    QTest.keyClicks(window.search, "boom")
    assert calls == [] and not window.pads["s1"].property("filtered")
    assert process_events(qapp, lambda: calls, 3)
    assert calls == ["boom"] and window.pads["s1"].property("filtered")
    QTest.keyClick(window.search, Qt.Key_Backspace)
    window.flush_search()          # Enter / Search don't wait for it
    assert calls == ["boom", "boo"] and not window._search_wait.isActive()
    window.flush_search()          # nothing waiting: nothing to do
    window.search.setText("")      # set by the app (not typed): filters at once
    assert calls[-1] == "" and not window.pads["s1"].property("filtered")


def test_dragging_pad_size_relays_the_pads_once_per_pause(qapp, window, monkeypatch):  # noqa: F811
    widths = []
    real = window.grid.set_pad_width
    monkeypatch.setattr(window.grid, "set_pad_width", lambda w: (widths.append(w), real(w)))
    slider = window._pad_size[1]
    for v in range(150, 200, 5):
        slider.setValue(v)
    assert widths == []
    assert process_events(qapp, lambda: widths, 3)
    assert widths == [195] and window.cfg.pad_width == 195


@pytest.fixture(autouse=True)
def _fresh_picture_caches(monkeypatch):
    monkeypatch.setattr(thumbs, "_fitted", type(thumbs._fitted)())
    monkeypatch.setattr(thumbs, "_fitted_bytes", 0)
