"""Help in the main window: switching tutorials off, a tab's About this tab box, the mic
tips and the Help menu.

MainWindow makes one ``TipControl`` (``MainWindow.tipctl``); everything here runs on the
UI thread."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QWidget

from soundboard.i18n import _
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.dialogs import TabHelpPopup


class TipControl(Controller):
    """The help of one MainWindow (``mw``)."""

    def set_tutorials_on(self, on: bool):
        """Settings > General > Show tutorials: off ends a running one too."""
        mw = self.mw
        mw.cfg.tutorials_on = bool(on)
        if not on:
            from soundboard.ui.setup import firsttour, tabtours
            firsttour.stop(mw)
            tabtours.stop(mw)
        mw._save_later()

    def _tab_info_at(self, i: int) -> tuple[str, str] | None:
        mw = self.mw
        page = mw.tabs.widget(i)
        return next((v for k, v in mw.tab_info.items() if getattr(mw, k, None) is page),
                    None)

    def _show_tab_info(self, i: int):
        """A tab's right-click "About this tab": its explanation, next to the tab."""
        mw = self.mw
        info = self._tab_info_at(i)
        if info:
            button = next((b for b in mw.rail.buttons if b.index == i), mw.tabs)
            self._show_help(TabHelpPopup(*info, owl=mw.tabs.widget(i) is mw.triggers,
                                         parent=mw), button)

    def _show_mic_tips(self):
        """Your mic's ⓘ: the voice app settings that stop it chopping your sounds up."""
        mw = self.mw
        box = TabHelpPopup(
            _("Sounds chopped up?"),
            _("If sounds get chopped up, switch off the voice app's noise suppression "
              "(Discord: <b>Input Profile → Custom</b>, <b>Noise Suppression → None</b>, "
              "<b>Echo Cancellation</b> off. Not Studio: it skips Onion Board)."),
            parent=mw)
        box.body.setTextFormat(Qt.TextFormat.RichText)   # (the setting names in bold)
        self._show_help(box, mw.btn_mictips)

    def _show_cable_tips(self):
        """The cable tile's ⓘ: who's better off with the virtual cable than the mic."""
        mw = self.mw
        box = TabHelpPopup(
            _("When to use the cable"),
            _("Most people don't need it: your sounds go into the mic you already use. "
              "The cable is for two cases:<br><br>"
              "• <b>You don't have a mic.</b> Without one there's nothing to put your sounds "
              "into, but the cable works on its own: others hear your sounds through it.<br>"
              "• <b>You'd rather Onion Board didn't touch your mic.</b> Putting sounds into "
              "your mic adds Onion Board's audio driver to it, and Windows asks you to "
              "allow that. With the cable, Onion Board leaves your mic as it is: the cable "
              "is VB-Audio's own free driver (its installer asks Windows too).<br><br>"
              "With the cable, pick <b>CABLE Output</b> as the mic in Discord and in each "
              "game."),
            parent=mw)
        box.body.setTextFormat(Qt.TextFormat.RichText)   # (the bold and the list)
        self._show_help(box, mw.btn_cableinfo)

    def _show_help(self, box: QDialog, beside: QWidget):
        """Open a help card to the right of `beside` (a rail button), inside the
        window: never off its left edge."""
        mw = self.mw
        lay = box.layout()
        assert lay is not None   # the popup's own
        lay.activate()   # wrapped text: as tall as the words need
        box.resize(box.width(), box.heightForWidth(box.width()) if box.hasHeightForWidth()
                   else box.sizeHint().height())
        top_left = beside.mapToGlobal(QPoint(beside.width() + 8, 0))
        area = mw.geometry() & beside.screen().availableGeometry()
        x = max(area.left(), min(top_left.x(), area.right() - box.width() + 1))
        y = max(area.top(), min(top_left.y(), area.bottom() - box.height() + 1))
        box.move(x, y)
        box.exec()
        box.deleteLater()
