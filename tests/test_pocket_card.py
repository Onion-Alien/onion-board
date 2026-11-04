"""Onion Pocket's card on the Setup tab: on the left, in Set up your voice apps's place
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


def test_pocket_card_sits_beside_the_eq_only_when_installed(window):  # noqa: F811
    pocket, chat, eq = window.pocket_card.frame, window.helpcard, window.eq_card
    window.fitctl._place_pocket(False)
    window.fitctl._stack_setup(False)
    grid = window._setup_cols

    def place(w):
        i = grid.indexOf(w)
        return grid.getItemPosition(i) if i >= 0 else None   # (row, column, rows, columns)
    row = place(eq)[0]
    assert place(chat) == (row, 1, 1, 1) and place(pocket) is None and pocket.isHidden()

    addon = FakePocket()
    _install(window, addon)
    assert place(pocket) == (row, 1, 1, 1) and place(chat) == (row + 1, 0, 1, 2)   # across both
    assert not pocket.isHidden()
    assert "Off" in window.pocket_card.state.text()

    window.pocket_card.fold.setChecked(True)   # opens the add-on's own controls
    assert addon.made == 1 and window.pocket_card.body_lay.count() == 1
    inner = window.pocket_card.body_lay.itemAt(0).widget()
    assert inner.layout().itemAt(0).widget().isHidden()   # its title: the card has one

    addon.enabled, addon.server.running = True, True
    window.pocket_card.fold.setChecked(False)
    assert window.pocket_card.state.text().startswith("On")

    _install(window, None)   # removed: Set up your voice apps back beside the EQ
    assert place(chat) == (row, 1, 1, 1) and place(pocket) is None and pocket.isHidden()


def test_pocket_card_in_one_column(window):  # noqa: F811
    window.fitctl._stack_setup(True)
    _install(window, FakePocket())
    grid = window._setup_cols

    def row(w):
        return grid.getItemPosition(grid.indexOf(w))[0]
    assert row(window.eq_card) < row(window.pocket_card.frame) < row(window.helpcard)
    assert all(grid.getItemPosition(grid.indexOf(w))[1:] == (0, 1, 1)
               for w in window._setup_narrow)
    _install(window, None)
    assert grid.indexOf(window.pocket_card.frame) < 0


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


def test_opening_the_fold_draws_only_the_settled_page(window, qapp):  # noqa: F811
    """Opening the fold laid Setup out twice, first in the page's old height: the cards
    above were squashed (Devices jumped up) and drawn so for a moment. The window draws
    again only once every card is where it ends up."""
    from conftest import process_events
    from PySide6.QtCore import QEvent, QObject
    _install(window, FakePocket())
    window.resize(1500, 900)
    window.show()
    window.tabs.setCurrentWidget(window.setup_page)
    process_events(qapp, lambda: False, 0.3)
    drawn = []

    class Watch(QObject):
        def eventFilter(self, o, e):
            if e.type() in (QEvent.Type.Move, QEvent.Type.Resize):
                drawn.append(window.updatesEnabled())
            return False
    watch = Watch()
    for w in (*window._setup_cards, window.pocket_card.frame):
        w.installEventFilter(watch)
    window.pocket_card.fold.click()
    assert not window.updatesEnabled()
    assert process_events(qapp, window.updatesEnabled)
    assert drawn and not any(drawn)   # every move made while the window wasn't drawing
    window.pocket_card.fold.click()
    assert process_events(qapp, window.updatesEnabled)
