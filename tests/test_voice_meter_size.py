"""The status chips leave room for a readable mic meter after resizing."""
import pytest
from PySide6.QtWidgets import QBoxLayout

from soundboard import theme
from soundboard.ui.voicestatus import VoiceStatusBar


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
                assert bar.meter.width() >= width // 2
            assert bar.meter.geometry().right() < bar._mic.width()
            assert bar._right.geometry().right() < bar.width()
    finally:
        bar.close()
        bar.deleteLater()


def test_bar_keeps_its_height_when_chips_come_and_go(qapp):
    bar = VoiceStatusBar()
    bar.set_level(0.1)
    bar.resize(1200, 60)
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
