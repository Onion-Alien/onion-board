"""Boxes fold away and out instead of blinking, and the mic box flashes when it works."""
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from soundboard.ui import reveal, toast


def _page(qapp):
    page = QWidget()
    lay = QVBoxLayout(page)
    box = QLabel("A box with a few words in it")
    lay.addWidget(box)
    lay.addStretch(1)
    page.resize(300, 200)
    page.show()
    return page, box


def test_instant_when_animations_are_off(qapp, monkeypatch):
    monkeypatch.setattr(toast, "ANIMATE", False)
    page, box = _page(qapp)
    reveal.set_shown(box, False)
    assert box.isHidden() and not reveal.shown(box)
    reveal.set_shown(box, True)
    assert not box.isHidden() and box.maximumHeight() == reveal.MAX_H
    page.close()


def test_folds_away_then_hides_and_back_out(qapp, monkeypatch):
    monkeypatch.setattr(toast, "ANIMATE", True)
    page, box = _page(qapp)
    QTest.qWait(20)
    reveal.set_shown(box, False)
    assert not box.isHidden() and not reveal.shown(box)   # still folding
    reveal.set_shown(box, False)   # a redraw meanwhile: the same fold goes on
    QTest.qWait(reveal.FOLD_MS + 200)
    assert box.isHidden() and box.maximumHeight() == reveal.MAX_H
    assert box.graphicsEffect() is None   # (nothing left on it)
    reveal.set_shown(box, True)
    assert not box.isHidden() and reveal.shown(box)
    QTest.qWait(reveal.FOLD_MS + 200)
    assert box.maximumHeight() == reveal.MAX_H and box.graphicsEffect() is None
    assert box.height() > 0
    page.close()


def test_turning_back_midway(qapp, monkeypatch):
    """Away, then back before it's gone (the status changed again): it ends shown."""
    monkeypatch.setattr(toast, "ANIMATE", True)
    page, box = _page(qapp)
    QTest.qWait(20)
    reveal.set_shown(box, False)
    QTest.qWait(reveal.FOLD_MS // 3)
    reveal.set_shown(box, True)
    QTest.qWait(reveal.FOLD_MS + 200)
    assert not box.isHidden() and box.maximumHeight() == reveal.MAX_H
    page.close()


def test_flash_paints_and_goes(qapp, monkeypatch):
    monkeypatch.setattr(toast, "ANIMATE", True)
    page, box = _page(qapp)
    reveal.flash(box)
    lit = box.findChild(reveal._Flash)
    assert lit is not None
    QTest.qWait(200)
    assert not page.grab().isNull()   # every moment paints
    QTest.qWait(reveal.FLASH_MS + 200)
    assert box.findChild(reveal._Flash) is None   # (gone by itself)
    monkeypatch.setattr(toast, "ANIMATE", False)
    reveal.flash(box, box)
    assert box.findChild(reveal._Flash) is None   # animations off: no flash
    page.close()
