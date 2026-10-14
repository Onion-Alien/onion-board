"""An empty list says so in its middle (ui.panel.EmptyList), not in a fake first row."""
from PySide6.QtGui import QImage

from soundboard.ui.panel import EmptyList


def _ink(lst: EmptyList) -> int:
    """Pixels in the middle of the list that differ from its top-left corner."""
    lst.resize(300, 200)
    img = lst.viewport().grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    base = img.pixel(img.width() // 2, 4)
    return sum(img.pixel(x, y) != base
               for x in range(20, img.width() - 20, 3) for y in range(30, img.height() - 30, 3))


def test_empty_list_paints_its_message_and_no_rows(qapp):
    blank = EmptyList("")
    said = EmptyList("Nothing here yet.", "trash")
    assert said.count() == 0
    assert _ink(said) > _ink(blank)      # the icon and the words


def test_a_filled_list_paints_no_message(qapp):
    blank = EmptyList("")
    lst = EmptyList("Nothing here yet.", "trash")
    lst.addItem("")                      # a row, even a blank one: no message over it
    lst.clearSelection()
    lst.setCurrentRow(-1)
    assert _ink(lst) == _ink(blank)
