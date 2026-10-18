"""The main window's two heights (panel.CONTROL_H / BAR_H) and the Interface size
setting (Settings > Appearance, read before the app starts)."""
import json

import pytest
from PySide6.QtWidgets import QApplication, QFrame

from soundboard.core import app
from soundboard.ui.panel import BAR_H, CONTROL_H
from test_mainwindow import window  # noqa: F401


def _pump():
    for _ in range(6):
        QApplication.processEvents()


@pytest.mark.parametrize("size", [(1280, 760), (800, 600)])
def test_sounds_bars_share_one_height(window, size):  # noqa: F811
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(*size)
    _pump()
    bars = {f.objectName(): f.height() for f in window.findChildren(QFrame)
            if f.objectName() in ("soundstoolbar", "transport", "deck") and f.isVisible()}
    assert set(bars) == {"soundstoolbar", "transport", "deck"}
    assert set(bars.values()) == {BAR_H}, bars
    assert window.search.height() == CONTROL_H
    assert window.btn_pp.height() == window.btn_st.height() == CONTROL_H


def test_ui_scale_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_SCALE_FACTOR", "1")   # recorded, so the test's own value is undone
    monkeypatch.delenv("QT_SCALE_FACTOR")
    cfg = tmp_path / "config.json"
    assert app.ui_scale_startup(tmp_path) == 100   # no config yet
    for bad in ("big", 77, True, None):              # hand-edited: ignored
        cfg.write_text(json.dumps({"ui_scale": bad}), encoding="utf-8")
        assert app.ui_scale_startup(tmp_path) == 100
    assert "QT_SCALE_FACTOR" not in app.os.environ
    cfg.write_text(json.dumps({"ui_scale": 125}), encoding="utf-8")
    assert app.ui_scale_startup(tmp_path) == 125
    assert app.os.environ["QT_SCALE_FACTOR"] == "1.25"
    # set from outside (scripts, tests): left alone
    cfg.write_text(json.dumps({"ui_scale": 150}), encoding="utf-8")
    assert app.ui_scale_startup(tmp_path) == 100
    assert app.os.environ["QT_SCALE_FACTOR"] == "1.25"


def test_interface_size_card_offers_restart(window, monkeypatch):  # noqa: F811
    from soundboard.settings import SettingsDialog
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    restarts = []
    monkeypatch.setattr(window, "restart_app", lambda: restarts.append(1))
    dlg = SettingsDialog(window, "appearance")
    try:
        combo = dlg.ui_scale_combo
        assert combo.currentData() == 100
        assert dlg.ui_scale_restart.isHidden() and dlg.ui_scale_note.isHidden()
        combo.setCurrentIndex(combo.findData(125))
        assert window.cfg.ui_scale == 125
        assert not dlg.ui_scale_restart.isHidden() and not dlg.ui_scale_note.isHidden()
        dlg.ui_scale_restart.click()
        assert restarts == [1]
        combo.setCurrentIndex(combo.findData(100))   # back to the running size
        assert dlg.ui_scale_restart.isHidden()
    finally:
        dlg.close()
        dlg.deleteLater()
