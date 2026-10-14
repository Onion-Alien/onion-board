"""Card headings line up (DESIGN section 4, *Card headings*): the heading icon, the ⓘ
and the status pill sit on the title's cap-height centre, measured on the drawn ink,
and two cards side by side have their titles on one line."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QLabel, QWidget
import pytest
from test_mainwindow import window  # noqa: F401


def _ink(img, rect: QRect, bg) -> list[tuple[int, int]]:
    """The (x, y) of every pixel in `rect` that differs clearly from `bg`."""
    out = []
    for y in range(max(0, rect.top()), min(img.height(), rect.bottom() + 1)):
        for x in range(max(0, rect.left()), min(img.width(), rect.right() + 1)):
            c = img.pixelColor(x, y)
            if max(abs(c.red() - bg.red()), abs(c.green() - bg.green()),
                   abs(c.blue() - bg.blue())) > 60:
                out.append((x, y))
    return out


def _rect(w: QWidget, card: QWidget) -> QRect:
    return QRect(w.mapTo(card, QPoint()), w.size())


def cap_centre(title: QLabel, card: QWidget, img) -> float:
    """The vertical middle of the title's first letter (a capital: its ink runs from
    the cap height to the baseline)."""
    r = _rect(title, card)
    bg = img.pixelColor(r.left(), r.top())
    ink = _ink(img, r, bg)
    assert ink, title.text()
    left = min(x for x, _y in ink)
    cols = {x for x, _y in ink}
    end = left
    limit = left + title.fontMetrics().horizontalAdvance(title.text()[0]) - 1
    while end + 1 in cols and end < limit:   # never include a touching descender
        end += 1
    ys = [y for x, y in ink if left <= x <= end]
    return (min(ys) + max(ys)) / 2


def ink_centre(w: QWidget, card: QWidget, img) -> float:
    r = _rect(w, card)
    bg = img.pixelColor(r.left(), r.top())
    ys = [y for _x, y in _ink(img, r, bg)]
    assert ys, w
    return (min(ys) + max(ys)) / 2


def heading_parts(card: QWidget):
    """The heading row's title and the widgets centred on it (heading_row())."""
    return card.heading_title, [w for w in card.heading_marks if w.isVisible()]


def _shown_setup(window, route):  # noqa: F811
    window.apply_theme("Dark")
    window.cfg.route = route
    window.routectl._show_route()
    window._update_status()
    window.tabs.setCurrentWidget(window.setup_page)
    window.show()
    window.resize(1500, 920)
    for _ in range(6):
        QApplication.processEvents()
        window._refit()


def test_setup_card_headings_line_up(window):  # noqa: F811
    for route in ("mic", "cable"):
        _shown_setup(window, route)
        cards = window._setup_narrow
        titles = {}
        for card in cards:
            if not card.isVisible():
                continue
            img = card.grab().toImage()
            title, marks = heading_parts(card)
            cap = cap_centre(title, card, img)
            titles[card] = cap + card.mapTo(window, QPoint()).y()
            for m in marks:   # the icon, the ⓘ, the pill: on the cap centre, within 1 px
                assert abs(ink_centre(m, card, img) - cap) <= 1, (route, title.text(), m)
        # side by side: your mic and who's listening's titles on one line
        mic, dest = window._setup_top
        assert abs(titles[mic] - titles[dest]) <= 1, route


@pytest.mark.parametrize("theme_name", ["Dark", "Amber Terminal", "Comic Sans"])
def test_setup_heading_ink_follows_live_font_changes(window, theme_name):  # noqa: F811
    _shown_setup(window, "mic")
    # The cards were built in the default font; a live theme switch must realign them.
    for name in (theme_name, "Dark", theme_name):
        window.apply_theme(name)
        for _ in range(8):
            QApplication.processEvents()
            window._refit()
        for card in window._setup_narrow:
            if not card.isVisible():
                continue
            title, marks = heading_parts(card)
            img = card.grab().toImage()
            cap = cap_centre(title, card, img)
            for mark in marks:
                assert abs(ink_centre(mark, card, img) - cap) <= 1, (name, title.text())


def test_setup_card_pairs_share_top_and_bottom_with_the_eq_on_or_off(window):  # noqa: F811
    """Devices and Equalizer and volume line up top and bottom whether the EQ's sliders
    show or not (and so do your mic and who's listening)."""
    _shown_setup(window, "mic")
    for on in (False, True, False):
        window.eq.chk_on.setChecked(on)
        for _ in range(6):
            QApplication.processEvents()
            window._refit()
        assert window.eq.body.isVisible() == on
        for a, b in window._setup_pairs:
            ga, gb = a.geometry(), b.geometry()
            assert ga.top() == gb.top() and ga.bottom() == gb.bottom(), on
