"""The Store tab's "New" pill on the rail: there until the tab is first opened, then
never again (Config.store_seen)."""
from test_mainwindow import window  # noqa: F401

from soundboard.ui.window import sidebar
from soundboard.ui.window.tabcontrol import TAB_INDEX


def _store_button(w):
    return next(b for b in w.rail.buttons if b.index == TAB_INDEX["store"])


def test_new_until_the_store_is_opened(window):  # noqa: F811
    w = window
    w.tabs.setCurrentIndex(0)
    assert not w.cfg.store_seen and _store_button(w).is_new()
    w.tabs.setCurrentIndex(TAB_INDEX["voice"])
    assert _store_button(w).is_new()   # another tab: still new
    w.tabs.setCurrentIndex(TAB_INDEX["store"])
    assert w.cfg.store_seen and not _store_button(w).is_new()
    w.tabs.setCurrentIndex(0)
    assert not _store_button(w).is_new()


def test_seen_stays_seen(window):  # noqa: F811
    w = window
    sidebar.set_tab_new(w.tabs, TAB_INDEX["store"], False)
    w.cfg.store_seen = True
    w.tabctl.mark_store_new()
    assert not _store_button(w).is_new()
