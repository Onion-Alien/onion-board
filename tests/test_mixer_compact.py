"""The compact footer keeps useful controls together before switching to tabs."""
import pytest
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401

from soundboard.ui.kit import theme


def settle(w, width, height=600):
    w.resize(width, height)
    w.fitctl._fit.reset()
    w.fitctl._refit()
    for _ in range(8):
        QApplication.processEvents()


@pytest.mark.parametrize('name', ['Dark', 'Light'])
def test_compact_footer_keeps_three_then_two_then_one(window, qapp, name):  # noqa: F811
    w = window
    theme.apply(qapp, name)
    w.show()
    w.tabs.setCurrentIndex(0)
    w.rail.set_open(False)
    seen = set()
    for width in range(870, 439, -10):
        settle(w, width)
        shown = tuple(i for i, group in enumerate(w._decks) if group[-1].isVisibleTo(w))
        seen.add(len(shown))
        assert not w.fitctl.is_mini()
        assert w.mixer.minimumSizeHint().width() <= w.mixer.width()
        assert w.out_meter.width() <= max(60, w.mixer.width() // 4)
        if len(shown) == 2:
            assert shown == (0, 1)
            w._deck_tabs[2].click()
            for _ in range(8):
                QApplication.processEvents()
            assert w._decks[2][-1].isVisibleTo(w)
            w._mixer_focus = 1
    assert seen == {1, 2, 3}
    settle(w, 1180, 720)
    assert all(group[-1].isVisibleTo(w) for group in w._decks)
    assert all(title.isVisibleTo(w) for title in w._deck_titles)


def test_collapsed_short_sidebar_uses_available_gaps(window):  # noqa: F811
    w = window
    w.show()
    w.tabs.setCurrentIndex(0)
    w.rail.set_open(False)
    settle(w, 870, 550)
    assert w.rail._lay.spacing() >= 4
    visible = [b for b in w.rail.buttons if b.isVisibleTo(w)]
    assert all(b.y() - a.geometry().bottom() - 1 >= 4
               for a, b in zip(visible, visible[1:]))
    assert w.rail.toggle.geometry().bottom() < w.rail.height()
