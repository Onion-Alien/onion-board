"""Cards moved between layouts keep getting the height they need.

Setup's two columns are re-stacked by taking the cards out of their layouts and adding
them back. A taken item that's never freed stays the widget's registered item, so the
new item's height cache never cleared: after the mic status changed, "Your virtual
mic" kept its old taller height and "Connect your chat" was squeezed (its buttons
drawn over its text) until the window's width changed."""
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget
from test_mainwindow import window  # noqa: F401

from soundboard import directmic as dm
from soundboard import engine as eng
from soundboard.ui.widgets import take_out


def pump(n=6):
    for _ in range(n):
        QApplication.processEvents()


def test_readded_widget_follows_its_new_height(qapp):
    host = QWidget()
    col = QVBoxLayout(host)
    box = QFrame()
    inner = QVBoxLayout(box)
    text = QLabel("one line")
    text.setWordWrap(True)
    inner.addWidget(text)
    col.addWidget(box)
    col.addStretch(1)
    host.resize(200, 600)
    host.show()
    pump()
    while col.count():
        take_out(col)
    col.addWidget(box)
    col.addStretch(1)
    pump()
    text.setText("many words that wrap onto several lines in a narrow box " * 4)
    pump()
    item = col.itemAt(0)
    assert item.heightForWidth(box.width()) == box.heightForWidth(box.width())
    assert box.height() >= box.heightForWidth(box.width()) - 1
    host.close()


def squeezed(w):
    out = []
    for c in w.setup_page.widget().findChildren(QFrame):
        if c.objectName() != "card" or not c.isVisible() or not c.hasHeightForWidth():
            continue
        need = c.heightForWidth(c.width())
        if c.height() < need - 1:
            out.append((c.findChildren(QLabel)[0].text(), c.height(), need))
    return out


def test_setup_cards_not_squeezed_after_mic_state_flips(window, monkeypatch):  # noqa: F811
    w = window
    state = {"dead": False}
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w, "_direct_not_running", lambda: state["dead"])
    monkeypatch.setattr(w.engine, "main_stream", object())
    w.cfg.route = "mic"
    w.cfg.mic_device = "Microphone (Example Gaming Headset)"
    w.show()
    w.tabs.setCurrentWidget(w.setup_page)
    for size in ((1270, 770), (1180, 720), (1480, 885)):
        w.resize(1480, 885)   # from wide to narrower: the columns get re-stacked
        pump()
        w.resize(*size)
        pump()
        assert squeezed(w) == [], size
        for dead in (True, False, True, False):
            state["dead"] = dead
            w._update_flow()
            pump()
            assert squeezed(w) == [], (size, dead)
