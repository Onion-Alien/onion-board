"""Dialogs grow to fit their wrapped text (ui/fit.py) instead of clipping it."""
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from conftest import process_events
from soundboard.ui import fit
from test_setupwizard import devices, wizard  # noqa: F401  (fixtures)


def clipped(label: QLabel) -> bool:
    return label.height() < label.heightForWidth(label.width())


def long_dialog(watch: bool) -> tuple[QDialog, QLabel]:
    d = QDialog()
    v = QVBoxLayout(d)
    lbl = QLabel("Some words that wrap onto many lines. " * 40)
    lbl.setWordWrap(True)
    v.addWidget(lbl)
    v.addWidget(QPushButton("OK"))
    if watch:
        fit.watch(d)
    d.resize(300, 120)
    return d, lbl


def test_a_watched_dialog_grows_to_fit_its_text(qapp):
    d, lbl = long_dialog(watch=True)
    d.show()
    assert process_events(qapp, lambda: not clipped(lbl), 3)
    assert d.width() >= 300 and d.height() > 120
    d.close()


def test_text_set_later_grows_it_too(qapp):
    d, lbl = long_dialog(watch=True)
    lbl.setText("short")
    d.show()
    process_events(qapp, lambda: False, 0.2)
    h = d.height()
    lbl.setText("Now a much longer text that needs room. " * 40)
    assert process_events(qapp, lambda: not clipped(lbl) and d.height() > h, 3)
    d.close()


def test_never_taller_than_the_screen(qapp):
    d, lbl = long_dialog(watch=True)
    lbl.setText("x " * 20000)
    d.show()
    process_events(qapp, lambda: False, 0.3)
    avail = d.screen().availableGeometry()
    assert d.frameGeometry().height() <= avail.height()
    assert d.width() > 300                       # widened instead
    d.close()


def test_setup_wizard_last_page_text_is_not_squashed(qapp, wizard):  # noqa: F811
    w, wiz = wizard
    w.cfg.main_device = "CABLE Input (VB-Audio Virtual Cable)"
    _last_page_fits(qapp, wiz)


def test_setup_wizard_last_page_fits_straight_into_the_mic(qapp, wizard, monkeypatch):  # noqa: F811
    from soundboard import directmic
    w, wiz = wizard
    w.cfg.route = "mic"
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    w.cfg.mic_device = "Microphone (A Very Long Gaming Headset Name With A Model Number)"
    _last_page_fits(qapp, wiz)


def _last_page_fits(qapp, wiz):
    wiz.resize(wiz.minimumSize())
    wiz.show()
    wiz.go(3)
    assert process_events(qapp, lambda: not clipped(wiz.discord_text), 3)
    assert wiz.height() >= fit.needed_height(wiz, wiz.width())
