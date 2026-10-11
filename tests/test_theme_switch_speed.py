"""Picking a theme in Settings restyles every widget in the app: in 1.7.2 that froze the
window for 5-6 s (the freeze reports). These keep it quick on the real main window
with every Settings page built."""
import os
import time

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

from soundboard import hangwatch, theme
from soundboard.library import SoundMeta
from soundboard.settings import SettingsDialog
import pytest

# ~0.5 s on a real PC. Hosted CI runners take 1.2-2.5 s for the same unchanged code
# (shared cores, three other test workers beside it), so there the budget is the
# point the app itself calls a freeze and reports it (hangwatch.HANG_S).
BUDGET_S = hangwatch.HANG_S if os.environ.get("CI") else 2.0


@pytest.fixture
def settings(main_window, app_dir):  # noqa: F811
    first = main_window.cfg.sounds[0]   # a full board: 60 pads
    main_window.cfg.sounds += [SoundMeta(id=f"x{i}", name=f"Sound {i}", file=first.file)
                               for i in range(58)]
    main_window._rebuild_pads()
    main_window.resize(1280, 760)
    main_window.show()
    dlg = SettingsDialog(main_window, "appearance", lazy=False)
    dlg.show()
    QApplication.processEvents()
    yield dlg
    dlg.close()


def _other(name: str) -> str:
    return next(n for n in theme.THEMES if n != name)


def test_a_theme_switch_stays_under_budget(settings):
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        settings._pick_theme(_other(theme.current_name))
        QApplication.processEvents()
        times.append(time.perf_counter() - t0)
    assert min(times) < BUDGET_S, times


def test_app_wide_filters_sit_out_the_restyle(settings, main_window):  # noqa: F811
    """Each Python filter on the app was called for every one of the ~20,000 events
    a restyle sends (a third of the switch): they're taken off meanwhile, and are
    back afterwards, Space still playing."""
    app = QApplication.instance()
    seen = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            seen.append(ev.type())
            return False

    spy = Spy(main_window)
    theme.app_filter(app, spy)
    real, during = theme._restyle, []

    def restyle(app, css):
        seen.clear()
        real(app, css)
        during.extend(seen)
    theme._restyle = restyle
    try:
        theme.apply(app, _other(theme.current_name))
    finally:
        theme._restyle = real
    assert during == []
    assert main_window._space in theme._app_filters
    QApplication.processEvents()
    main_window.update()
    QApplication.processEvents()
    assert seen   # installed again


def test_the_drag_veil_sits_out_the_restyle_too(settings, main_window):  # noqa: F811
    """The drop veil watched every event app-wide outside app_filter(): 49,000 Python
    calls in each switch on a full board, each one waiting on the audio threads."""
    assert main_window.drop_veil in theme._app_filters


def test_a_switch_shows_a_still_with_bun_then_fades_to_the_new_theme(settings, main_window):  # noqa: F811
    """Never a half-styled frame: the window is covered by a picture of itself while
    every widget restyles, then that fades. A quick second click never stacks two."""
    from soundboard.ui.themecover import ThemeCover
    seen = []
    real = main_window._apply_theme

    def during(name):
        seen.extend(c for c in main_window.findChildren(ThemeCover) if c.isVisible())
        real(name)
    main_window._apply_theme = during
    try:
        main_window.apply_theme(_other(theme.current_name))
        main_window.apply_theme(_other(theme.current_name))
    finally:
        del main_window._apply_theme
    assert len(seen) == 2 and seen[1].geometry() == main_window.rect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    covers = main_window.findChildren(ThemeCover)
    assert len(covers) == 1   # the first went as the second came
    end = time.monotonic() + 3
    while main_window.findChildren(ThemeCover) and time.monotonic() < end:
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not main_window.findChildren(ThemeCover)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_a_hovered_menu_row_shows_in_every_theme(name):
    """The hovered row of a menu or dropdown was 1.07-1.5:1 against the menu (no
    visible change in Flashbang, Blood Moon, Lava): now it stands out, words readable."""
    t = theme.THEMES[name]
    assert theme._contrast(t["item_hover"], t["card"]) >= 1.6
    assert theme._contrast(t["item_hover"], t["text_hi"]) >= 4.5
