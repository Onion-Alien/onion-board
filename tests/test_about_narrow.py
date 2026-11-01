"""Settings > About fits a 440 px window in every language: a long translation of a
button ("Star Onion Board on GitHub" in German, French, Hungarian...) goes onto two
lines instead of pushing the cards under the scroll bar."""
import pytest
from PySide6.QtWidgets import QApplication, QPushButton
from test_mainwindow import window  # noqa: F401

from soundboard import i18n
from soundboard.ui.kit.wrapbutton import WrapButton, two_lines


def _about(w, width):
    w.show()
    w.resize(width, 700)
    dlg = w.setctl.open_settings("about")
    QApplication.processEvents()
    page = dlg.star_btn
    while page.parentWidget().objectName() != "qt_scrollarea_viewport":
        page = page.parentWidget()
    return dlg, page, page.parentWidget()


@pytest.fixture
def german(qapp):
    i18n.set_language("de")
    yield
    i18n.set_language("en")


def test_german_about_page_fits_at_440(german, window):  # noqa: F811
    dlg, page, viewport = _about(window, 440)
    star = dlg.star_btn
    # it was the widest thing on the page, 28 px wider than the room. Measured against
    # the page without it, not in pixels: CI's fallback font is much wider than Windows'
    wide = page.minimumSizeHint().width()
    star.hide()
    QApplication.processEvents()
    assert page.minimumSizeHint().width() == wide
    star.show()
    QApplication.processEvents()
    assert "\n" in QPushButton.text(star)
    assert star.text() == "Onion Board auf GitHub einen Stern geben"
    assert star.geometry().right() < star.parentWidget().contentsRect().right() + 1
    assert star.height() >= star.minimumSizeHint().height()   # both lines show
    _about(window, 1200)
    assert "\n" not in QPushButton.text(star)                 # room again: one line


def test_about_buttons_fit_at_440_in_every_language(window):  # noqa: F811
    dlg, page, viewport = _about(window, 440)
    buttons = [b for b in page.findChildren(WrapButton) if b.isVisibleTo(page)]
    assert dlg.star_btn in buttons and dlg.invite_copy in buttons
    for code in i18n.codes():
        for b in buttons:
            room = b.parentWidget().contentsRect().width()
            said = i18n.in_language(code, lambda b=b: i18n._(b.text()))
            probe = WrapButton(said, b.parentWidget())
            probe.setIcon(b.icon())
            probe.setIconSize(b.iconSize())
            assert probe.minimumSizeHint().width() <= room, (code, said, room)
            probe.deleteLater()


@pytest.mark.parametrize("text, lines", [
    ("Onion Board auf GitHub einen Stern geben", "Onion Board auf GitHub\neinen Stern geben"),
    ("Website", "Website"),
    ("给项目加星", "给项\n目加星"),
])
def test_two_lines_splits_evenly(text, lines):
    assert two_lines(text) == lines
