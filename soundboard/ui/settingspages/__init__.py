"""The pages of the Settings window (soundboard.settings.SettingsDialog), one module each.

Each page is a QObject the dialog owns (``SettingsDialog.<page>``), not a plain object: a
timer or signal aimed at one of its methods then stops with the dialog (Qt drops a
connection when its receiver goes), as it did when the method was the dialog's own. The
widgets a page builds stay on the dialog (``self.dlg.x``), where the window and tests
read them. The dialog's card helpers are a page's own too, so a page reads like the
dialog it came from."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

if TYPE_CHECKING:
    from soundboard.settings import SettingsDialog
    from soundboard.ui.mainwindow import MainWindow


class Page(QObject):
    """One page of a SettingsDialog (``dlg``), owned by it."""

    def __init__(self, dlg: SettingsDialog):
        super().__init__(dlg)
        self.dlg = dlg

    @property
    def mw(self) -> MainWindow:
        return self.dlg.mw

    def _card(self, *args, **kwargs):
        return self.dlg._card(*args, **kwargs)

    def _page(self, *args, **kwargs):
        return self.dlg._page(*args, **kwargs)

    def _option(self, *args, **kwargs):
        return self.dlg._option(*args, **kwargs)

    def _link_button(self, *args, **kwargs):
        return self.dlg._link_button(*args, **kwargs)

    def _note_card(self, *args, **kwargs):
        return self.dlg._note_card(*args, **kwargs)


def _button_row():
    """Buttons side by side at their own width, wrapping onto a second line only when
    Settings is too narrow (stacked full-width buttons looked like a form)."""
    from soundboard.ui.panel import Flow   # panel imports this module
    return Flow(gap=8)
