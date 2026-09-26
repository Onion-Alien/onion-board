"""The Settings window's layout: pages scroll instead of squashing their rows."""
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from soundboard.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_a_short_window_scrolls_the_general_page_instead_of_squashing_it(window, qapp):  # noqa: F811,E501
    d = SettingsDialog(window, "general")
    d.show()
    d.resize(2000, 700)             # wide and short, like a maximized window on a small screen
    for _ in range(5):
        qapp.processEvents()
    sa = d.tabs.currentWidget()
    assert isinstance(sa, QScrollArea)
    page = sa.widget()
    assert page.height() > sa.viewport().height()          # it scrolls
    for wdg in page.findChildren(QLabel) + page.findChildren(QPushButton):
        if wdg.isVisibleTo(page) and wdg.text():
            want = wdg.heightForWidth(wdg.width()) if wdg.hasHeightForWidth() else -1
            assert wdg.height() >= max(want, wdg.minimumSizeHint().height()), wdg.text()
    d.close()
