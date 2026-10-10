"""Search results must never briefly show their labels as desktop windows."""
import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from soundboard.ytdl import Result
from soundboard.ui.ytsearch import ResultRow


@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("views", [None, 100])
def test_result_stats_never_show_as_standalone_windows(qapp, wide, views):
    flashed = []

    class Watch(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                flashed.append(type(obj).__name__)
            return False

    watch = Watch()
    qapp.installEventFilter(watch)
    rows = []
    try:
        for i in range(10):
            row = ResultRow(Result(str(i), f"Result {i}", "Channel", 1,
                                   views=views), wide=wide)
            rows.append(row)
            assert row.stats.parentWidget() is row
            assert row.stats.isHidden() == (views is None)
        assert not flashed
    finally:
        qapp.removeEventFilter(watch)
        for row in rows:
            row.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)
