"""Onion Pocket on the Setup tab: once the add-on is installed, a card of its own in the
left column (Connect your chat moves to the right one to make room). Shut, it says
whether phones can reach Onion Board; its fold opens the add-on's own controls (the
QR code, on / off, the port), the same ones as on Settings → Remote.

The add-on's controls are made fresh each time the fold opens (the add-on's card()
can be called any number of times), so they always show what Settings last set."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from soundboard.i18n import _
from soundboard.ui.kit.panel import card, fold_button, hint_label
from soundboard.ui.kit.widgets import widget_at

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)


class PocketCard(QObject):
    """The Setup card of one MainWindow (``mw.pocket_card``); ``frame`` is the card."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.mw = mw
        self.frame, v = card(_("Onion Pocket"), roomy=True, icon="phone")
        self.frame.setObjectName("card")
        self.state = hint_label("")
        v.addWidget(self.state)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.fold = fold_button(_("Pair a phone and settings"), self.body)
        self.fold.toggled.connect(self._opened)
        v.addWidget(self.fold, 0)
        v.addWidget(self.body)
        v.addStretch(1)
        self.frame.hide()
        self.frame.installEventFilter(self)   # shown again: Settings may have turned it on

    def eventFilter(self, obj, e):
        if obj is self.frame and e.type() == QEvent.Type.Show:
            self.say_state()
        return False

    # ------------------------------------------------------------------ the add-on
    def addon(self):
        """The running Onion Pocket's object, or None (not installed, or didn't start)."""
        from soundboard.addons import pocketaddon
        return next((a for i, a in getattr(getattr(self.mw, "remctl", None),
                                           "remote_addons", [])
                     if i.id == pocketaddon.MODULE_ID and a is not None), None)

    def installed(self) -> bool:
        return self.addon() is not None

    def say_state(self):
        a = self.addon()
        if a is None:
            return
        server = getattr(a, "server", None)
        if not getattr(a, "enabled", False):
            text = _("Off: phones can't reach Onion Board. Open it below to turn it on.")
        elif server is not None and getattr(server, "running", False):
            text = _("On: phones on this Wi-Fi can play your pads.")
        elif getattr(a, "asking", None) is not None:
            # it starts once Windows' firewall prompt is answered: until then that's no
            # "couldn't start". Looked at again until the answer's in.
            text = _("On, waiting for Windows to allow it: answer its prompt.")
            QTimer.singleShot(500, self, self.say_state)
        else:
            text = _("On, but it couldn't start. Open it below to see why.")
        self.state.setText(text)

    # ------------------------------------------------------------------ the fold
    def _clear(self):
        lay = self.body_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.hide()
                w.deleteLater()

    def _opened(self, on: bool):
        self._clear()
        if not on:
            self.say_state()
            return
        a = self.addon()
        if a is None:
            return
        try:
            inner = a.card(self.body)
        except Exception:  # noqa: BLE001 - an add-on can't break the Setup tab
            log.exception("Onion Pocket couldn't make its card for Setup")
            self.body_lay.addWidget(hint_label(_("Onion Pocket's settings didn't open: "
                                                 "they're on Settings → Remote.")))
            return
        flatten(inner)
        self.body_lay.addWidget(inner)

    # ------------------------------------------------------------------ the page
    def refresh(self):
        """Show or hide the card to match whether Onion Pocket is installed, and move
        the Setup cards round it (fitcontrol)."""
        have = self.installed()
        if self.fold.isChecked():   # a new copy's controls, or none (removed)
            if have:
                self._opened(True)
            else:
                self.fold.setChecked(False)
        self.say_state()
        self.mw.fitctl._place_pocket(have)


def flatten(inner: QWidget):
    """The add-on's Settings card, inside this one: no frame or margins of its own, and
    without its title (this card has the heading). Its hint stays: it says who can use it."""
    inner.setObjectName("")
    lay = inner.layout()
    if lay is None:
        return
    lay.setContentsMargins(0, 0, 0, 0)
    first = widget_at(lay, 0)
    if first is not None and first.objectName() == "section":
        first.hide()
