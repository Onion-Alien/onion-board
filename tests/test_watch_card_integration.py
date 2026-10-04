"""Opt-in smoke test of a locally built Watch zip in the real Board host."""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from soundboard import modules
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from test_mainwindow import window  # noqa: F401


@pytest.mark.skipif(not os.environ.get("ONIONBOARD_CARD_TEST_ZIP"), reason="local add-on opt-in")
def test_built_cards_in_board(window, qapp, tmp_path, monkeypatch):  # noqa: F811
    info = modules.install_zip(Path(os.environ["ONIONBOARD_CARD_TEST_ZIP"]),
                               "onion-watch", "triggers", tmp_path / "modules")
    modules.load_package(info)
    from onionwatch import screenwatch
    from onionwatch.ui.viewer import PictureViewer
    monkeypatch.setattr(screenwatch, "monitors", lambda: [])
    tab = TriggersTab(BoardHost(window), [tmp_path / "modules"])
    assert tab.panel is not None, tab.error.text()
    panel = tab.panel
    # The board entry wraps its triggers in an alarm bar.
    if not hasattr(panel, "_new"):
        panel = panel.panel
    image = QImage(60, 40, QImage.Format_RGB32)
    image.fill(Qt.blue)
    painter = QPainter(image)
    painter.fillRect(10, 5, 30, 20, Qt.white)
    painter.fillRect(15, 8, 10, 10, Qt.red)
    painter.end()
    panel._new(image, "Test picture")
    row = next(iter(panel.rows.values()))
    row.t.sounds = ["s0"]
    row.set_sounds(panel.host.sounds())
    row.set_open(False)
    panel.chk_advanced.setChecked(True)
    row.interval.setCurrentIndex(row.interval.findData(50))
    assert row.t.interval_ms == 50
    assert "100%" in row.details.text()
    tab.resize(900, 650)
    tab.show()
    row.strip.thumbs[0].pic.click()
    qapp.processEvents()
    dialogs = [w for w in qapp.topLevelWidgets() if isinstance(w, PictureViewer)]
    assert len(dialogs) == 1 and not dialogs[0].view.img.isNull()
    dialogs[0].close()
    review = os.environ.get("ONIONBOARD_CARD_REVIEW")
    if review:
        out = Path(review)
        out.mkdir(parents=True, exist_ok=True)
        old = window.triggers
        index = window.tabs.indexOf(old)
        window.tabs.removeTab(index)
        old.shutdown()
        old.deleteLater()
        window.triggers = tab
        window.tabs.insertTab(index, tab, "Triggers")
        window.tabs.setCurrentWidget(tab)
        window.resize(1200, 780)
        row.name.setText("Rare spawn")
        row._on_name()
        for name in ("Queue ready", "Health low"):
            panel._new(image, name)
        for card in panel.rows.values():
            card.t.sounds = ["s0"]
            card.set_sounds(panel.host.sounds())
            card.set_open(False)
        window.show()
        for advanced in (False, True):
            panel.chk_advanced.setChecked(advanced)
            panel.chk_advanced.setFocus()
            for _ in range(12):
                qapp.processEvents()
            name = "board-advanced.png" if advanced else "board-simple.png"
            assert window.grab().save(str(out / name))
    tab.shutdown()
    if review:
        return  # now owned and cleaned up by the window fixture
    tab.close()
    tab.deleteLater()
