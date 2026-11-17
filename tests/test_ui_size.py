"""The main window's two heights (panel.CONTROL_H / BAR_H) and the Interface size
setting (Settings > Appearance, read before the app starts)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFrame

from soundboard.core import app, earlystart
from soundboard.ui.kit.panel import BAR_H, CONTROL_H
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
    from soundboard.ui.settings.settings import SettingsDialog
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


@pytest.mark.parametrize("target", [80, 90, 100, 110, 125, 150])
def test_restart_reads_new_size_in_fresh_qt_process(window, tmp_path, monkeypatch, target):  # noqa: F811
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    monkeypatch.setattr(earlystart, "_config_scale", None)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"ui_scale": 80}), encoding="utf-8")
    assert earlystart.interface_size(tmp_path) == 80
    dlg = window.setctl.open_settings("appearance")
    combo = dlg.ui_scale_combo
    combo.setCurrentIndex(combo.findData(target))
    cfg.write_text(json.dumps({"ui_scale": window.cfg.ui_scale}), encoding="utf-8")
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(kw))
        patch.setattr(window, "quit_app", lambda: None)
        window.restart_app()
    env = calls[0]["env"]
    assert "QT_SCALE_FACTOR" not in env
    assert os.environ["QT_SCALE_FACTOR"] == "0.8"
    code = (
        "import sys; from pathlib import Path; "
        "from soundboard.core import earlystart; "
        "earlystart.interface_size(Path(sys.argv[1])); "
        "from PySide6.QtWidgets import QApplication; "
        "a = QApplication([]); print(a.primaryScreen().devicePixelRatio())"
    )
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                            env=env, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert float(result.stdout.strip()) == pytest.approx(target / 100)


def test_restart_preserves_external_scale(monkeypatch, tmp_path):
    monkeypatch.setattr(earlystart, "_config_scale", None)
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.75")
    (tmp_path / "config.json").write_text('{"ui_scale": 150}', encoding="utf-8")
    earlystart.interface_size(tmp_path)
    assert earlystart.restart_env(dict(os.environ))["QT_SCALE_FACTOR"] == "1.75"
