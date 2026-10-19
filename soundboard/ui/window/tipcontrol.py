"""Tips and help in the main window: a tip once things have settled (tried again while the
window is hidden or a game is up), Show me, switching tips off, a tab's About this tab
box, the mic tips and the Help menu.

MainWindow makes one ``TipControl`` (``MainWindow.tipctl``); everything here runs on the
UI thread."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QDialog, QWidget

from soundboard.core import tips
from soundboard.i18n import _
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.dialogs import TabHelpPopup
from soundboard.ui.window.tabcontrol import TAB_INDEX

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

TIP_RETRY_MS = 60_000  # ...and is tried again this often while it can't show


class TipControl(Controller):
    """The tips and help of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._tip_timer = QTimer(mw, interval=TIP_RETRY_MS)   # see _maybe_tip
        self._tip_timer.timeout.connect(self._maybe_tip)

    def _start_tips(self):
        if not self._maybe_tip():
            self._tip_timer.start()

    def _game_up(self) -> bool:
        mw = self.mw
        return mw.overlay.is_open or tips.fullscreen_in_front()

    @staticmethod
    def _touring() -> bool:
        """A tutorial is up: the tip waits (one thing at a time)."""
        from soundboard.ui.setup import firsttour, tabtours
        return firsttour._current is not None or tabtours._current is not None

    def _maybe_tip(self) -> bool:
        """Show today's tip if it's time. True when there's nothing more to try this
        start (one shown, or none due)."""
        mw = self.mw
        tip = tips.due(mw.cfg, mw.tabctl.tab_on)
        if tip is None:
            self._tip_timer.stop()
            return True
        if not mw.isVisible() or mw.isMinimized() or self._game_up() or self._touring():
            return False
        self.show_tip(tip)
        self._tip_timer.stop()
        return True

    def show_tip(self, tip: tips.Tip):
        mw = self.mw
        mw.tip = tip
        mw.tip_lbl.setText(_("💡 Did you know? {text}", text=tip.text))
        mw.tip_bar.show()
        if tip.key not in mw.cfg.tips_seen:
            mw.cfg.tips_seen.append(tip.key)
        mw.cfg.tip_day = tips.today()
        mw._save_later()

    def _tip_show_me(self):
        mw = self.mw
        tip, mw.tip = mw.tip, None
        mw.tip_bar.hide()
        if tip is None:
            return
        kind, __, where = tip.show.partition(":")
        if kind == "tab":
            mw.tabs.setCurrentIndex(TAB_INDEX[where])
        elif kind == "settings":
            mw.setctl.open_settings(where)
        elif kind == "search":
            mw.tabs.setCurrentWidget(mw.sounds_page)
            mw.search.setFocus()
        elif kind == "record" and hasattr(mw.soundctl, "record_dialog"):
            mw.tabs.setCurrentWidget(mw.sounds_page)
            mw.soundctl.record_dialog()
        elif kind == "deleted":
            mw.rmctl.show_deleted()
        else:
            mw.tabs.setCurrentWidget(mw.sounds_page)

    def set_tips_on(self, on: bool):
        mw = self.mw
        mw.cfg.tips_on = bool(on)
        if not on:
            mw.tip_bar.hide()
        mw._save_later()

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
