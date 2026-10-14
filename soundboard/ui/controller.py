"""The base of MainWindow's feature controllers (ui/*control.py, ui/remoteaccess.py).

Each one is a QObject the window owns, not a plain object: a timer or signal aimed at
one of its methods then stops with the window (Qt drops a connection when its receiver
goes), as it did when the method was the window's own. A plain object's bound method
kept firing into a deleted window. It also lets a test replace a method on the
controller after the method was connected (Qt looks a QObject's slot up when called)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow


class Controller(QObject):
    """One feature of a MainWindow (``mw``), owned by it."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.mw = mw
