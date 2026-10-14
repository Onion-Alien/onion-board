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


@pytest.mark.skipif(not os.environ.get("ONIONBOARD_CARD_TEST_ZIP"), reason="local add-on opt-in")
def test_built_bar_keeps_its_words_with_triggers_coming_and_going(
        qapp, app_dir, monkeypatch):
    """The real add-on's bottom bar in a window tight for another tab: its buttons keep
    their words from no triggers to one blank one, after deleting it and across tab
    switches, and go icon only only when the bar itself is narrow."""
    from PySide6.QtCore import QEvent

    from soundboard import engine, winkeys
    from soundboard.library import Config
    from soundboard.ui import mainwindow as main
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    modules.install_zip(Path(os.environ["ONIONBOARD_CARD_TEST_ZIP"]), "onion-watch",
                        "triggers", app_dir / "modules")
    Config(screen={"on": False, "triggers": []}, mic_first=True).save()
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    try:
        w.load_triggers()
        w.resize(1100, 800)
        w.show()
        w.tabs.setCurrentWidget(w.triggers)
        qapp.processEvents()
        panel = w.triggers.panel
        assert panel is not None, w.triggers.error.text()
        if not hasattr(panel, "_new"):
            panel = panel.panel
        words = (panel.btn_watch, panel.btn_cut, panel.btn_add)

        def shown():
            for _ in range(5):
                qapp.processEvents()
            return all(b.text() for b in words)

        assert w.fitctl._fit.compact_count() and shown()      # no triggers
        panel.btn_new.click()                          # one, blank
        assert len(panel.triggers) == 1 and shown()
        w.tabs.setCurrentIndex(0)
        w.tabs.setCurrentWidget(w.triggers)
        assert shown()
        panel._remove(next(iter(panel.rows.values())))  # the last one deleted
        assert not panel.triggers and shown()
        w.resize(640, 800)                             # the bar itself narrow
        assert not shown() and panel.btn_cut.text() == ""
        w.resize(1100, 800)
        assert shown()
    finally:
        w.close()
        w.soundctl._load_thread.join(15)
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)
