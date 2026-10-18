"""The virtual cable asks first (it's the fallback for the few who need it), its box's
main button is the mic, and the mic button glows."""
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QLabel

from soundboard.audio import engine as eng
from soundboard.ui import cableconfirm
from soundboard.ui.cableconfirm import ask
from test_mainwindow import window  # noqa: F401  (the real MainWindow)


def _boxes():
    return [w for w in QApplication.topLevelWidgets()
            if w.objectName() == "cableconfirm" and w.isVisible()]


def test_the_box_runs_only_what_was_picked(qapp):
    done = []
    d = ask(None, lambda: done.append("cable"), lambda: done.append("mic"))
    assert d.mic_button.objectName() == "primary" and d.mic_button.isDefault()
    said = " ".join(lbl.text() for lbl in d.findChildren(QLabel))
    assert "know you need it" in said and "CABLE Output" in said
    d.mic_button.click()
    assert done == ["mic"]
    d = ask(None, lambda: done.append("cable"), lambda: done.append("mic"))
    d.cable_button.click()
    assert done == ["mic", "cable"]


def test_setup_tab_cable_button_asks_before_installing(window, monkeypatch):  # noqa: F811
    w = window
    w.cfg.route = "cable"
    monkeypatch.setattr(w.statusctl, "virtual_mic", None)
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    installs, attaches, opened = [], [], []
    monkeypatch.setattr(w.micctl, "install_cable", lambda: installs.append(1))
    monkeypatch.setattr(w.micctl, "attach_mic", lambda: attaches.append(1))
    real = cableconfirm.ask
    monkeypatch.setattr(cableconfirm, "ask",
                        lambda *a, **k: opened.append(real(*a, **k)) or opened[-1])
    w.resize(1400, 900)
    w.show()
    w.tabs.setCurrentWidget(w.setup_page)
    w.statusctl._update_flow()
    for _ in range(4):
        QApplication.processEvents()
    w.btn_install.click()
    assert installs == [] and len(opened) == 1   # nothing yet: it asks
    opened[0].mic_button.click()
    assert attaches == [1] and installs == []
    w.btn_install.click()
    opened[1].cable_button.click()
    assert installs == [1] and w._cable_started
    # the mic's button glows (the cable's doesn't)
    assert isinstance(w.btn_attach.graphicsEffect(), QGraphicsDropShadowEffect)
    assert w.btn_install.graphicsEffect() is None


def test_on_the_mic_route_the_main_button_glows(window):  # noqa: F811
    w = window
    w.cfg.route = "mic"
    w.resize(1400, 900)
    w.show()
    w.tabs.setCurrentWidget(w.setup_page)
    w.statusctl._update_flow()
    for _ in range(4):
        QApplication.processEvents()
    assert w.btn_install.isVisible() and w.btn_install.objectName() == "primary"
    assert isinstance(w.btn_install.graphicsEffect(), QGraphicsDropShadowEffect)
    w.tabs.setCurrentWidget(w.sounds_page)   # off screen: no effect left on it
    for _ in range(4):
        QApplication.processEvents()
    assert w.btn_install.graphicsEffect() is None
