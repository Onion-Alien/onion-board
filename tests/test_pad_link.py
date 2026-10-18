"""A pad whose sound plays from a file outside the library (Copy into library off) shows a
small link mark while the mouse is on it; hovering just the mark names the file."""
from pathlib import Path

from conftest import process_events

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QToolTip

from soundboard.sounds import library
from soundboard.sounds.library import SoundMeta
from soundboard.ui.kit.widgets import Pad


def _pad(file: Path, state="ready", hover=True) -> Pad:
    p = Pad(SoundMeta(id="x", name="Vine boom", file=str(file), duration=1.2,
                      hotkey="Ctrl+1"), 240)   # room for the mark without real fonts (CI)
    p.state = state
    p.hover = hover
    p.grab()   # paints it: the mark's place is worked out while painting
    return p


def _tip(pad: Pad, at: QPoint) -> str:
    QToolTip.hideText()   # Qt lets the last one fade out first
    assert process_events(QApplication.instance(), lambda: not QToolTip.isVisible(), 5)
    QApplication.sendEvent(pad, QHelpEvent(QEvent.Type.ToolTip, at, pad.mapToGlobal(at)))
    QApplication.processEvents()
    return QToolTip.text() if QToolTip.isVisible() else ""


def test_a_linked_pad_shows_the_mark_and_names_its_file_over_it_only(qapp, app_dir):
    outside = app_dir / "Music" / "boom.wav"
    pad = _pad(outside)
    assert pad.linked_file() == str(outside)
    box = pad._link_rect
    assert box is not None and pad.rect().contains(box.toAlignedRect())
    assert _tip(pad, box.center().toPoint()) == f"Plays from: {outside}"
    assert _tip(pad, QPoint(pad.width() // 2, 20)) == ""   # over the name: nothing
    assert str(outside) in pad.accessibleDescription()     # a screen reader says it too


def test_a_sound_in_the_library_or_a_missing_one_has_no_mark(qapp, app_dir):
    ours = _pad(library.SOUNDS_DIR / "My sounds" / "boom.wav")
    assert ours.linked_file() == "" and ours._link_rect is None
    assert _tip(ours, QPoint(ours.width() - 30, ours.height() - 14)) == ""
    gone = _pad(app_dir / "Music" / "gone.wav", state="error")   # "can't load file" stays
    assert gone._link_rect is None


def test_a_slim_row_shows_the_mark_too(qapp, app_dir):
    outside = app_dir / "Music" / "boom.wav"
    p = Pad(SoundMeta(id="x", name="Vine boom", file=str(outside), duration=1.2), 320)
    p.setFixedSize(320, 30)   # the mini player's one-line row
    p.state = "ready"
    p.hover = True
    p.grab()
    assert p._link_rect is not None
    assert _tip(p, p._link_rect.center().toPoint()) == f"Plays from: {outside}"


def test_the_mark_waits_for_the_mouse(qapp, app_dir):
    """On every pad at once it read as "a web link": only the hovered pad shows it."""
    outside = app_dir / "Music" / "boom.wav"
    idle = _pad(outside, hover=False)
    assert idle.linked_file() == str(outside) and idle._link_rect is None
    assert str(outside) in idle.accessibleDescription()   # still said, just not drawn
    row = Pad(SoundMeta(id="x", name="Vine boom", file=str(outside), duration=1.2), 320)
    row.setFixedSize(320, 30)
    row.state = "ready"
    row.grab()
    assert row._link_rect is None
