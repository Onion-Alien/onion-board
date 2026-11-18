"""Card mascots fit their display slot without a second scaling pass."""
import math

import pytest

from soundboard.ui.kit import theme
from soundboard.ui.kit.modalframe import MASCOT, ModalFrame, mascot_pixmap


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0])
@pytest.mark.parametrize("kind", ["bun", "owl"])
def test_mascot_image_fits_header_at_screen_resolution(qapp, kind, dpr):
    image = mascot_pixmap(kind, MASCOT, dpr)
    # Extra ear padding once made Bun's 56-pixel slot use a 61-pixel image.
    assert image.height() == math.ceil(MASCOT * dpr)
    assert image.devicePixelRatio() == dpr


def test_card_mascot_refreshes_for_display_and_theme(qapp, monkeypatch):
    from soundboard.ui.kit import modalframe

    frame = ModalFrame("Voice chat")
    label = frame.mascot
    assert label is not None
    frame.show()
    qapp.processEvents()
    calls = []

    def render(kind, height, dpr):
        calls.append((kind, height, dpr, theme.current_name))
        return mascot_pixmap(kind, height, dpr)

    monkeypatch.setattr(modalframe, "mascot_pixmap", render)
    monkeypatch.setattr(type(label), "devicePixelRatioF", lambda self: 1.5)
    with theme.previewing("Light"):
        label.update()
        qapp.processEvents()
        label.grab()
        assert calls[-1] == ("bun", MASCOT, 1.5, "Light")
    frame.close()
    frame.deleteLater()
