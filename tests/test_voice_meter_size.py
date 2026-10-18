"""The status chips leave room for a readable mic meter after resizing."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QBoxLayout

from soundboard import i18n
from soundboard.ui.kit import theme
from soundboard.ui.voice.voicestatus import VoiceStatusBar


@pytest.fixture(autouse=True)
def meter_theme(qapp):
    previous = theme.current_name
    theme.apply(qapp, "Dark")
    yield
    theme.apply(qapp, previous)


@pytest.mark.parametrize("level", [None, 0.1])
def test_meter_uses_available_room_after_resizing(qapp, level):
    bar = VoiceStatusBar()
    bar.set_items([("none", "Your real voice", "off", "mic", None, "")])
    bar.set_level(level)
    bar.show()
    try:
        for width in (1368, 460, 800, 1368):
            bar.resize(width, bar.sizeHint().height())
            for _ in range(4):
                qapp.processEvents()
            if width >= 800:
                # The Voices switch and Record reserve their own width beside the meter.
                buttons = (bar.master.width() + bar.master_label.width()
                           + bar.record_button.width())
                assert bar.meter.width() >= (width - buttons) // 2
            assert bar.meter.geometry().right() < bar._mic.width()
            assert bar._right.geometry().right() < bar.width()
    finally:
        bar.close()
        bar.deleteLater()


def test_bar_keeps_its_height_when_chips_come_and_go(qapp):
    bar = VoiceStatusBar()
    bar.set_level(0.1)
    # Enough room for the Voices switch and its name, the meter and both status chips
    # on one line.
    bar.resize(1440, 60)
    bar.show()
    try:
        heights = []
        for items in ([("none", "Voice effects off", "off", "mic", None, "")],
                      [("fx", "Male voice", "on", "voice", None, "")],
                      [("fx", "Robot", "on", "voice", None, ""),
                       ("ai", "AI voice off", "warn", "warn", None, "")],
                      [("none", "Voice effects off", "off", "mic", None, "")]):
            bar.set_items(items)
            for _ in range(4):
                qapp.processEvents()
            heights.append(bar.sizeHint().height())
        assert len(set(heights)) == 1, heights
    finally:
        bar.close()
        bar.deleteLater()


def test_many_chips_wrap_and_meter_recovers(qapp):
    bar = VoiceStatusBar()
    bar.set_level(0.1)
    bar.set_items([(key, text, "on", "mic", None, "") for key, text in
                   [("fx", "Robot"), ("ai", "A long AI voice name"),
                    ("speak", "Computer voice"), ("lang", "Speak in another language")]])
    bar.show()
    try:
        for width in (1368, 320, 1368):
            bar.resize(width, bar.sizeHint().height())
            for _ in range(4):
                qapp.processEvents()
            if width == 320:
                assert bar._box.direction() == QBoxLayout.TopToBottom
                assert bar._right.maximumWidth() > width
            else:
                assert bar.meter.width() >= width // 2
    finally:
        bar.close()
        bar.deleteLater()


@pytest.mark.parametrize("language", ["en", "de", "ar", "zh-CN"])
def test_translated_mic_status_fits_with_the_voices_switch_and_meter(qapp, language):
    direction = qapp.layoutDirection()
    i18n.set_language(language)
    qapp.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl(language) else Qt.LeftToRight)
    bar = VoiceStatusBar()
    bar.set_items([("none", i18n._("Voice effects off"), "off", "mic", None, "")])
    bar.set_level(None)
    bar.show()
    try:
        for width in (800, 320, 440, 800):
            bar.resize(width, bar.sizeHint().height())
            for _ in range(4):
                qapp.processEvents()
            label = bar.lbl_mic
            text_width = label.fontMetrics().horizontalAdvance(label.text())
            assert text_width <= label.contentsRect().width()
            assert bar.meter.width() >= bar.meter.minimumWidth()
            for widget in (bar.master_label, bar.master, bar.record_button, label, bar.meter):
                rect = widget.rect().translated(widget.mapTo(bar._mic, QPoint()))
                assert bar._mic.rect().contains(rect)
            assert bar.master.accessibleName() == i18n._("Voices on or off")
            assert bar.master_label.text() == i18n._("Voices")
            words = bar.master_label.fontMetrics().horizontalAdvance(bar.master_label.text())
            assert words <= bar.master_label.contentsRect().width()
    finally:
        bar.close()
        bar.deleteLater()
        i18n.set_language("en")
        qapp.setLayoutDirection(direction)


def test_chips_sit_on_the_mic_row_centre_line(qapp):
    bar = VoiceStatusBar()
    bar.set_level(0.1)
    bar.set_items([("fx", "Secret detective", "on", "voice", None, ""),
                   ("ai", "Bear", "on", "wave", None, "")])
    bar.resize(1100, 60)
    bar.show()
    try:
        for _ in range(4):
            qapp.processEvents()
        assert bar._box.direction() == QBoxLayout.LeftToRight

        def mid(w):
            return w.mapTo(bar, QPoint(0, 0)).y() + w.height() // 2
        line = mid(bar.meter)
        assert [mid(w) for w in (bar.lbl_heard, *bar.chips.values())] == [line] * 3
    finally:
        bar.close()
        bar.deleteLater()
