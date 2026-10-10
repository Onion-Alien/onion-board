"""Picking a theme in Settings restyles every widget in the app: in 1.7.2 that froze the
window for 5-6 s (the freeze reports). These keep it quick on the real main window
with every Settings page built."""
import os
import time

from PySide6.QtCore import QObject
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
