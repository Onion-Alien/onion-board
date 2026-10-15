"""Onion Pocket's card on the Setup tab: on the left, in Connect your chat's place
(that moves right, under the EQ), only while the add-on is installed."""
from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from test_mainwindow import window  # noqa: F401


class FakePocket:
    """Just what the Setup card asks of the add-on."""

    def __init__(self):
        self.enabled = False
        self.server = SimpleNamespace(running=False)
        self.made = 0

    def card(self, parent=None):
        self.made += 1
        w = QWidget(parent)
        v = QVBoxLayout(w)
        t = QLabel("Onion Pocket: your pads on your phone")
        t.setObjectName("section")
        v.addWidget(t)
        v.addWidget(QLabel("controls"))
        return w

    def stop(self):
        pass


def _install(window, addon):  # noqa: F811
    info = SimpleNamespace(id="onion-pocket", version="0.3.0", error="", package=None)
    window.remctl.remote_addons = [(info, addon)] if addon is not None else []
    window.pocket_card.refresh()


def test_pocket_card_takes_the_left_spot_only_when_installed(window):  # noqa: F811
    left, right = window._setup_lr
    pocket, chat = window.pocket_card.frame, window.helpcard
    window.fitctl._place_pocket(False)
    window.fitctl._stack_setup(False)

    def column(w):
        for col in (left, right):
            if col.indexOf(w) >= 0:
                return col
        return None
    assert column(chat) is left and column(pocket) is None and pocket.isHidden()

    addon = FakePocket()
    _install(window, addon)
    assert column(pocket) is left and column(chat) is right and not pocket.isHidden()
    assert "Off" in window.pocket_card.state.text()

    window.pocket_card.fold.setChecked(True)   # opens the add-on's own controls
    assert addon.made == 1 and window.pocket_card.body_lay.count() == 1
    inner = window.pocket_card.body_lay.itemAt(0).widget()
    assert inner.layout().itemAt(0).widget().isHidden()   # its title: the card has one

    addon.enabled, addon.server.running = True, True
    window.pocket_card.fold.setChecked(False)
    assert window.pocket_card.state.text().startswith("On")

    _install(window, None)   # removed: back where they always were
    assert column(chat) is left and column(pocket) is None and pocket.isHidden()


def test_pocket_card_in_one_column(window):  # noqa: F811
    window.fitctl._stack_setup(True)
    _install(window, FakePocket())
    left, right = window._setup_lr
    order = [left.itemAt(i).widget() for i in range(left.count())]
    assert order.index(window.pocket_card.frame) == order.index(window.helpcard) + 1
    assert right.indexOf(window.helpcard) < 0
    _install(window, None)
    assert left.indexOf(window.pocket_card.frame) < 0


def test_waiting_on_windows_prompt_isnt_couldnt_start(window, qapp):  # noqa: F811
    """Turned on, the add-on waits for Windows' firewall prompt before it starts its
    server: the shut card said "couldn't start" all that time. It says it's waiting,
    then what came of it once the prompt's answered."""
    from conftest import process_events
    addon = FakePocket()
    addon.enabled, addon.asking = True, object()   # the prompt's up
    _install(window, addon)
    assert window.pocket_card.state.text() == ("On, waiting for Windows to allow it: "
                                               "answer its prompt.")
    addon.asking, addon.server.running = None, True   # answered: it started
    assert process_events(qapp, lambda: window.pocket_card.state.text().startswith("On: "))
