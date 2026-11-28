"""The two entry points share live readings and an in-flight cleanup."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_mainwindow import window  # noqa: F401
from test_modals import wait_for

from soundboard.sounds.library import Config
from soundboard.ui.kit import busy
from soundboard.ui.window import resourcemonitor


def test_open_from_toolbar_and_bun_and_release_once(window, qapp, monkeypatch):  # noqa: F811
    readings = iter(((40, 100), (65, 200)))
    monkeypatch.setattr(resourcemonitor, "_cpu_times", lambda: next(readings, (65, 200)))
    monkeypatch.setattr(resourcemonitor.hangwatch, "memory_load", lambda: 42)
    monkeypatch.setattr(resourcemonitor.hangwatch, "working_set", lambda: 64 << 20)
    monkeypatch.setattr(resourcemonitor.shutil, "disk_usage",
                        lambda _path: SimpleNamespace(used=75, total=100))

    helpers_called = []
    proceed = threading.Event()
    monkeypatch.setattr(resourcemonitor.ytworker, "drop_all",
                        lambda: (helpers_called.append("downloads"), proceed.wait(5)))
    monkeypatch.setattr(window.voice.controller, "release_idle_helpers",
                        lambda: helpers_called.append("speech"))

    window.show()
    window.tabctl._open_tab("sounds")
    assert window.btn_resources.isVisible()
    QTest.mouseClick(window.btn_resources, Qt.MouseButton.LeftButton)
    monitor = window.resourcectl._monitor
    assert monitor.isVisible()
    assert wait_for(qapp, lambda: monitor._rows[0][0].value() == 75, timeout=4.0)
    assert [bar.value() for bar, _ in monitor._rows] == [75, 42, 75]
    assert monitor._app_ram.text().startswith("64")

    try:
        QTest.mouseClick(monitor._release, Qt.MouseButton.LeftButton)
        assert wait_for(qapp, lambda: bool(helpers_called))
        QTest.mouseClick(monitor._release, Qt.MouseButton.LeftButton)
        QTest.keyClick(monitor, Qt.Key.Key_Escape)
        assert not monitor.isVisible() and not monitor._timer.isActive()

        window.btn_about.click()
        resource_action = next(a for a in window.about_menu.actions()
                               if a.text() == "Resource monitor")
        QTest.mouseClick(window.about_menu, Qt.MouseButton.LeftButton,
                         pos=window.about_menu.actionGeometry(resource_action).center())
        assert monitor.isVisible() and busy.is_busy(monitor._release)
    finally:
        proceed.set()
    assert wait_for(qapp, lambda: monitor._release.text() == "Done")
    assert helpers_called == ["downloads", "speech"]
    monitor.frame.close_btn.click()
    assert not monitor.isVisible()


def test_auto_release_waits_for_audio_to_finish_with_the_monitor_closed(
        window, qapp, monkeypatch):  # noqa: F811
    controller = window.resourcectl
    controller.show_monitor()
    monitor = controller._monitor
    combo = monitor._interval
    assert [combo.itemData(i) for i in range(combo.count())] == [0, 30, 60, 120, 300, 600, 900]
    assert combo.currentData() == 0 and not controller._timer.isActive()
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentData() == window.cfg.ram_release_interval == 30
    assert controller._timer.interval() == 30000
    assert wait_for(qapp, lambda: Config.load().ram_release_interval == 30)
    monitor.reject()

    calls = []
    monkeypatch.setattr(window.engine, "quiet", lambda: False)
    monkeypatch.setattr(resourcemonitor.ytworker, "drop_all", lambda: calls.append("cleanup"))
    monkeypatch.setattr(resourcemonitor, "RETRY_MS", 200)
    controller._timer.start(1)
    assert wait_for(qapp, lambda: controller._timer.interval() == 200)
    assert calls == []

    monkeypatch.setattr(window.engine, "quiet", lambda: True)
    assert wait_for(qapp, lambda: calls == ["cleanup"] and not controller.releasing)
    assert not monitor.isVisible() and controller._timer.interval() == 30000
    controller.show_monitor()
    QTest.keyClick(combo, Qt.Key.Key_Up)
    assert combo.currentData() == window.cfg.ram_release_interval == 0
    assert not controller._timer.isActive()
    monitor.reject()
