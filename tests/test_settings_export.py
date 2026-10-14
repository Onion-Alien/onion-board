"""Settings > General > Backup's Export button: its "done" wording follows the export."""
from PySide6.QtWidgets import QApplication, QPushButton
from test_mainwindow import window  # noqa: F401


def test_backup_export_button_takes_the_finished_signal(window, monkeypatch):  # noqa: F811
    d = window.open_settings("general")
    exp = next(b for b in d.findChildren(QPushButton) if b.text() == "Export everything")

    def export_board():
        window.impctl._exporting = True
    monkeypatch.setattr(window.impctl, "export_board", export_board)
    exp.click()
    QApplication.processEvents()
    # file, sounds written, error, left out: the button reads all four without raising
    window.bridge.exported.emit("backup.zip", 3, "", 1)
    QApplication.processEvents()
    assert exp.text() == "✓ Exported"
