"""Settings' page list on the left: its rows came out 1-4 px taller than the room at
every window size, and a scroll bar showed for those few pixels."""
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_no_scroll_bar_for_a_few_pixels(window):  # noqa: F811
    w = window
    w.show()
    d = w.setctl.open_settings("audio")
    for size in ((800, 600), (1180, 720)):
        w.resize(*size)
        for _ in range(10):
            QApplication.processEvents()
        bar = d.categories.verticalScrollBar()
        assert bar.maximum() <= d.BAR_SLACK, size   # (more is real overflow: a bar is right)
        assert not bar.isVisible(), size
