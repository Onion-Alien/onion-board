"""A theme switch drops the spare Edit sound and builds it again in the new theme: the
dropped one must go with everything in it. Its effect pages were parentless, so each
switch left ~650 widgets behind (46,000 after 68 switches) and later switches crawled."""
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QScrollArea

THEMES = ("Dark", "Light", "Midnight", "Dark", "Light", "Midnight",
          "Dark", "Light", "Midnight", "Dark")


def _settle(qapp):
    for _ in range(3):
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _stray_pages():
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, QScrollArea)]


def test_theme_switches_free_the_dropped_spare_editor(window, qapp):  # noqa: F811
    sw = window.setctl
    window.themectl.apply_theme("Dark")
    sw.prebuild_editor()   # (what the switch's timer does a moment later)
    _settle(qapp)
    before = len(QApplication.allWidgets())
    for name in THEMES:
        window.themectl.apply_theme(name)
        sw.prebuild_editor()
        _settle(qapp)
    assert sw._spare_editor is not None
    assert len(QApplication.allWidgets()) <= before + 20
    assert not _stray_pages()


def test_advanced_and_back_keeps_the_pages_in_the_window(window, qapp):  # noqa: F811
    window.setctl.prebuild_editor()
    d = window.setctl._spare_editor
    assert d is not None
    d.set_advanced(True)
    d.set_advanced(False)
    _settle(qapp)
    assert all(s.parentWidget() is d for s in d._fx_scrolls)
    assert not _stray_pages()
