"""No Windows ding from everyday message boxes (soundboard.ui.quietbox)."""
import pytest
from PySide6.QtWidgets import QMessageBox

from soundboard.ui import quietbox


@pytest.fixture
def quiet(qapp):
    f = quietbox._Filter(qapp)
    qapp.installEventFilter(f)
    yield
    qapp.removeEventFilter(f)


@pytest.mark.parametrize("icon", [QMessageBox.Icon.Information, QMessageBox.Icon.Warning])
def test_info_and_warning_boxes_lose_the_sound_not_the_picture(quiet, icon):
    box = QMessageBox(icon, "Title", "Text")
    box.show()
    try:
        assert box.icon() == QMessageBox.Icon.NoIcon   # Qt plays nothing for NoIcon
        assert not box.iconPixmap().isNull()           # but the picture is still there
    finally:
        box.close()


def test_critical_keeps_its_sound(quiet):
    box = QMessageBox(QMessageBox.Icon.Critical, "Title", "Text")
    box.show()
    try:
        assert box.icon() == QMessageBox.Icon.Critical
    finally:
        box.close()

