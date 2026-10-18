"""Grey hints in text boxes are whole, never cut to their first letters (ui.widgets
fit_placeholder), and the Voice tab's Say bar makes room for its box."""
from conftest import process_events
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

from soundboard.ui.widgets import fit_placeholder


def test_the_longest_hint_that_fits(qapp):
    from PySide6.QtWidgets import QLineEdit
    e = QLineEdit()
    e.show()
    fit_placeholder(e, "Search sounds or paste a link", "Search sounds", "Search")
    for width, hint in ((400, "Search sounds or paste a link"), (150, "Search sounds"),
                        (90, "Search"), (30, "Search")):
        e.resize(width, 30)
        qapp.processEvents()
        assert e.placeholderText() == hint, width


def test_narrow_boxes_say_whole_words(window, qapp):  # noqa: F811
    w = window
    w.show()
    for width in (440, 900, 1280):
        w.resize(width, 700)
        for page, box in ((w.sounds_page, w.search), (w.voice, w.voice.speech.ed)):
            w.tabs.setCurrentWidget(page)
            process_events(qapp, lambda: False, 0.2)
            hint = box.placeholderText()
            assert box.fontMetrics().horizontalAdvance(hint) < box.width() - 30, (width, hint)
    w.resize(440, 700)
    w.tabs.setCurrentWidget(w.voice)
    process_events(qapp, lambda: False, 0.2)
    keep = w.voice.speech.b_keep
    assert keep.text() == "" and keep.accessibleName() == "Save as sound"   # just its +
    w.resize(1280, 700)
    process_events(qapp, lambda: False, 0.2)
    assert keep.text() == "Save as sound"
