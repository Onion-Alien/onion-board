"""What's really drawn reads, after a real theme switch: pixels, not tokens. The tokens
were fine all along while a dropdown showed the last theme's pale text on a white card
(1.1:1), so these measure the picture on screen against 4.5:1."""
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QIcon, QImage, QPalette
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QFrame, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

from soundboard.ui.kit import theme
from soundboard.ui.voice.voicetiles import VoiceTile

NEED = 4.5
SWITCHES = [("Fireworks", "Cherry Blossom"), ("Cherry Blossom", "Dark"), ("Light", "Swamp"),
            ("Dark", "Paper")]


def _spin(ms: int = 250) -> None:
    """Long enough for what a switch leaves for later (theme._Later) to be done."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _pixels(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    raw = np.frombuffer(img.constBits(), np.uint8)
    return raw.reshape(img.height(), img.bytesPerLine() // 4, 4)[..., 2::-1].copy()


def _luminance(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(float) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return c @ np.array([0.2126, 0.7152, 0.0722])


def _strongest(area: np.ndarray) -> float:
    """The contrast of the strongest colour in `area` against its commonest (its
    background): the ink, wherever the words are."""
    colours, counts = np.unique(area.reshape(-1, 3), axis=0, return_counts=True)
    back = _luminance(colours[counts.argmax()][None])[0]
    ink = _luminance(colours)   # (a short word's darkest shades are a few pixels each)
    return float(((np.maximum(back, ink) + 0.05) / (np.minimum(back, ink) + 0.05)).max())


def _row_contrast(box: QComboBox, row: int) -> float:
    view = box.view()
    area = _pixels(view.grab().toImage())
    r = view.visualRect(box.model().index(row, 0))
    return _strongest(area[max(r.top(), 0):r.bottom() - 1, r.left() + 2:r.right() - 2])


@pytest.mark.parametrize("old, new", SWITCHES)
@pytest.mark.parametrize("opened", [False, True])
def test_a_closed_dropdown_takes_the_new_themes_text(qapp, old, new, opened):
    """Qt polishes a widget once: a dropdown's list, left out of the restyle as a closed
    window, kept the old theme's text over the new theme's background."""
    theme.apply(qapp, old)
    top = QWidget()
    card = QFrame(top)
    card.setObjectName("card")
    QVBoxLayout(top).addWidget(card)
    box = QComboBox()
    box.addItems(["(none)", "Speakers", "Headphones"])
    QVBoxLayout(card).addWidget(box)
    top.show()
    _spin(50)
    try:
        if opened:
            box.showPopup()
            _spin(50)
            box.hidePopup()
        theme.apply(qapp, new)
        _spin()
        box.showPopup()
        _spin(50)
        assert box.view().palette().color(QPalette.ColorRole.Text).name() == theme.T["text"]
        assert _row_contrast(box, 1) >= NEED
    finally:
        box.hidePopup()
        top.close()
        top.deleteLater()
        theme.apply(qapp, theme.DEFAULT)


def _words(w: QWidget) -> str:
    if isinstance(w, QLabel):
        return "" if w.pixmap() and not w.pixmap().isNull() else w.text()
    if isinstance(w, QAbstractButton):
        return w.text()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QLineEdit):
        return w.text() or w.placeholderText()
    return ""


def _unreadable(mw) -> list[tuple]:
    """Everything with words on the page now, and each dropdown's rows, under NEED."""
    area = _pixels(mw.grab().toImage())
    bad = []
    for w in mw.findChildren(QWidget):
        if not w.isVisible() or not any(c.isalnum() for c in _words(w)):
            continue
        seen = w.visibleRegion().boundingRect()
        if seen.width() * seen.height() < 0.6 * max(1, w.width() * w.height()):
            continue   # (mostly scrolled away: what's there is something else)
        at = w.mapTo(mw, seen.topLeft())
        inset = 0 if isinstance(w, QLabel) else 3   # (a button's border isn't its words)
        part = area[at.y() + inset:at.y() + seen.height() - inset,
                    at.x() + inset:at.x() + seen.width() - inset]
        if part.size and (c := _strongest(part)) < NEED:
            bad.append((type(w).__name__, _words(w)[:40], round(c, 2)))
    for box in mw.findChildren(QComboBox):
        if not box.isVisible() or box.count() < 2:
            continue
        box.showPopup()
        QApplication.processEvents()
        row = 0 if box.currentIndex() else 1
        if (c := _row_contrast(box, row)) < NEED:
            bad.append(("dropdown row", box.itemText(row)[:40], round(c, 2)))
        box.hidePopup()
    return bad


@pytest.mark.parametrize("old, new", SWITCHES)
def test_every_word_on_setup_and_voice_reads_after_a_switch(main_window, qapp, old, new):  # noqa: F811
    mw = main_window
    mw.resize(1500, 1000)
    mw.show()
    try:
        mw.themectl._apply_theme(old)
        _spin(50)
        mw.themectl._apply_theme(new)
        _spin()
        for page in (mw.setup_page, mw.voice):
            mw.tabs.setCurrentWidget(page)
            _spin(100)
            assert _unreadable(mw) == [], type(page).__name__
    finally:
        theme.apply(qapp, theme.DEFAULT)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_status_words_read_on_every_surface(name):
    """Arctic's "Not sending" on the Setup card was 3.8:1, Swamp's Remove 3.6:1."""
    t = theme.tokens(name)
    for key, also in (("ok_text", ()), ("warn_text", ()), ("error_text", ()),
                      ("danger_text", ("danger_bg", "danger_hover"))):
        for surface in ("bg", "panel", "card", "card_hi", "inset", *also):
            assert theme._contrast(t[key], t[surface]) >= NEED, (key, surface)


def _ink(icon: QIcon) -> set[str]:
    px = _pixels(icon.pixmap(24, 24).toImage())
    return {f"#{r:02x}{g:02x}{b:02x}" for r, g, b in np.unique(px.reshape(-1, 3), axis=0)}


def test_the_voice_tabs_plain_icons_follow_a_switch(main_window, qapp):  # noqa: F811
    """The search box's magnifier and the + cards stayed in the colours the window was
    built in."""
    mw = main_window
    try:
        mw.themectl._apply_theme("Dark")
        mw.themectl._apply_theme("Light")
        muted = theme.T["muted"]
        old = theme.THEMES["Dark"]["muted"]
        searches = [w for w in mw.voice.findChildren(QLineEdit) if w.objectName() == "voicesearch"]
        icons_now = [s.actions()[0].icon() for s in searches]
        icons_now += [w.make_tile.icon() for w in mw.voice.findChildren(QWidget)
                      if isinstance(getattr(w, "make_tile", None), VoiceTile)]
        assert icons_now
        for icon in icons_now:
            ink = _ink(icon)
            assert muted in ink and old not in ink
    finally:
        theme.apply(qapp, theme.DEFAULT)
