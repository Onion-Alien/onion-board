"""The Pocket tab: Onion Pocket, the phone remote (soundboard.addons.pocketaddon).

  * Until the add-on is installed, the tab is its card: what it does and a *Get Onion
    Pocket* button. One click downloads it (nothing is fetched before that), installs it
    and starts it, no restart needed (RemoteAccess.load_remote_addon).
  * Once it runs, the add-on's own card (the QR code to pair a phone, on / off, the
    port), and under it the add-on's version with Check for updates (Update to X once a
    newer one is out), Report a problem and Remove.

The tab follows the add-on wherever it's got, updated or removed (Settings → Add-ons
too): RemoteAccess calls refresh(). A broken add-on never stops the app: the card says
why and offers to get it again."""
from __future__ import annotations

import html
import logging
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.core import errors
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons, theme
from soundboard.ui.kit.panel import Flow, HoverCard, ShownStack, heading_row, hint_label
from soundboard.ui.window.taboff import TabOff

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

COLUMN_W = 760   # the installed page's cards: a readable column, centred in a wide window
BUN_ROOM = 620   # the tab's width under which the Get card drops Bun (the words stay)


class _Relay(QObject):
    """A download (`done`: ModuleInfo or None) or an update check (`found`: offer, error)
    back on the UI thread."""
    done = Signal(object)
    found = Signal(object, str)


class PocketTab(TabOff):
    """The Pocket tab of one MainWindow (``mw.pocket``). A TabOff underneath: the window
    calls the same idle methods on every tab, and this one has nothing that plays."""

    def __init__(self, mw: MainWindow):
        super().__init__()
        self.mw = mw
        self._shown_addon = None   # the add-on object whose card is on the page
        self._offer = None         # a newer version, once Check for updates found one
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = ShownStack()
        v.addWidget(self.stack)
        self._build_get_page()
        self._build_have_page()
        self.refresh()

    # ------------------------------------------------------------------ the add-on
    def _running(self):
        """(info, add-on object or None) of the installed Onion Pocket, or (None, None)."""
        from soundboard.addons import pocketaddon
        return next(((i, a) for i, a in getattr(getattr(self.mw, "remctl", None),
                                                "remote_addons", [])
                     if i.id == pocketaddon.MODULE_ID), (None, None))

    # ------------------------------------------------------------------ pages
    def _build_get_page(self):
        """Not installed: Onion Pocket's own card in the middle of the tab, as the
        Triggers tab's is for Onion Watch."""
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 8, 0, 0)
        box = HoverCard()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(18, 18, 18, 18)   # (a roomy card's: panel.card)
        box.setMaximumWidth(740)
        # the words on the left, Bun diving on the right (as Hoot sits on Triggers')
        row = QHBoxLayout()
        row.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(10)
        # the heading as every card's (DESIGN section 4, Card headings): the icon centred
        # on the title's capitals, the line under it a hint
        top = QVBoxLayout()
        top.setSpacing(4)
        head, self.title, _marks = heading_row("Onion Pocket", "phone")
        top.addLayout(head)
        top.addWidget(hint_label(_("your pads on your phone")))
        text.addLayout(top)
        text.addSpacing(2)
        bv.addLayout(row)
        row.addLayout(text, 1)
        from soundboard.ui.pocket.divebun import DiveBun
        self.bun = DiveBun(196)
        row.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignCenter)
        bv = text   # (the points, button and note go under the heading, beside Bun)
        for pic, words in (
                ("phone", _("Scan a code with your phone's camera to pair it")),
                ("sounds", _("Tap a pad on the phone to play it here")),
                ("browser", _("iPhone or Android, in the browser: nothing to install on "
                              "the phone")),
                ("shield", _("Off until you turn it on, for phones on your own Wi-Fi"))):
            line = QHBoxLayout()
            line.setSpacing(8)
            dot = QLabel()
            icons.set_label_icon(dot, pic, "accent_hi", size=16)
            dot.setFixedSize(16, 16)
            lbl = QLabel(words)
            lbl.setWordWrap(True)
            lbl.ensurePolished()
            # the icon on the first line's capitals, from the font (as heading_row)
            fm = lbl.fontMetrics()
            pin = QVBoxLayout()
            pin.setContentsMargins(0, max(0, round(fm.ascent() - (fm.capHeight() + 1) / 2
                                                   - 7.5)), 0, 0)
            pin.addWidget(dot)
            pin.addStretch(1)
            line.addLayout(pin)
            line.addWidget(lbl, 1)
            bv.addLayout(line)
        self.error = hint_label("")
        theme.set_tone(self.error, "warn")
        self.error.hide()
        bv.addWidget(self.error)
        buttons = Flow(gap=8)
        self.btn_get = QPushButton(_("Get Onion Pocket"))
        self.btn_get.setObjectName("primary")
        icons.set_icon(self.btn_get, "phone", "on_accent")
        self.btn_get.clicked.connect(lambda: self.get())
        buttons.addWidget(self.btn_get)
        bv.addLayout(buttons)
        bv.addWidget(hint_label(_("Free, from GitHub, and only downloaded when you click.")))
        mid = QHBoxLayout()   # in the middle of the tab, a landing page
        mid.addStretch(1)
        mid.addWidget(box, 100)
        mid.addStretch(1)
        pv.addStretch(1)
        pv.addLayout(mid)
        pv.addStretch(2)
        # it scrolls, as every tab does, so the window can still be made small
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.get_page = scroll
        self.stack.addWidget(scroll)

    def resizeEvent(self, ev):
        # Bun only where there's room for him beside the words
        self.bun.setVisible(ev.size().width() >= BUN_ROOM)
        super().resizeEvent(ev)

    def _build_have_page(self):
        """Installed: the add-on's card, then its version and buttons, in a column that
        scrolls."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setContentsMargins(0, 8, 0, 8)
        row.addStretch(1)
        col = QWidget()
        col.setMaximumWidth(COLUMN_W)
        self.column = QVBoxLayout(col)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(12)
        row.addWidget(col, 100)
        row.addStretch(1)
        scroll.setWidget(inner)
        self.addon_slot = QVBoxLayout()   # the add-on's own card goes here
        self.addon_slot.setContentsMargins(0, 0, 0, 0)
        self.column.addLayout(self.addon_slot)
        # (Settings' card, as the add-on's own above it is: RemoteHost.card)
        from soundboard.ui.settings.remotehost import RemoteHost
        about, av = RemoteHost.card(_("Add-on"))
        self.version = hint_label("")
        av.addWidget(self.version)
        btns = Flow(gap=8)
        self.btn_check = QPushButton(_("Check for updates"))
        icons.set_icon(self.btn_check, "reload")
        self.btn_check.clicked.connect(self.check)
        btns.addWidget(self.btn_check)
        self.btn_report = QPushButton(_("Report a problem"))
        self.btn_report.setToolTip(_("Opens a bug report on GitHub in your browser, with the "
                                     "versions filled in"))
        self.btn_report.clicked.connect(self._report)
        btns.addWidget(self.btn_report)
        self.btn_remove = QPushButton(_("Remove Onion Pocket"))
        self.btn_remove.setToolTip(_("Takes the add-on out of Onion Board: phones can't play "
                                     "your pads any more. Paired phones are kept for when you "
                                     "get it again."))
        icons.set_icon(self.btn_remove, "trash", "danger_text")
        self.btn_remove.clicked.connect(self.remove)
        btns.addWidget(self.btn_remove)
        av.addLayout(btns)
        self.column.addWidget(about)
        self.column.addStretch(1)
        self.have_page = scroll
        self.stack.addWidget(scroll)

    def _clear_slot(self):
        lay = self.addon_slot
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.hide()
                w.deleteLater()

    # ------------------------------------------------------------------ following it
    def refresh(self):
        """The page for the add-on as it is now: Get (not installed, or it didn't
        start: with why), or its card (made again only for a new copy)."""
        info, addon = self._running()
        if addon is None or info is None:
            self._clear_slot()
            self._shown_addon = None
            self._offer = None
            failed = info is not None and bool(info.error)
            self.error.setText(_("Version {version} is installed but didn't start: {error}. "
                                 "Reinstall it, or report the problem.",
                                 version=info.version, error=info.error)
                               if info is not None and info.error else "")
            self.error.setVisible(failed)
            self.stack.setCurrentWidget(self.get_page)
            return
        if addon is not self._shown_addon:
            self._clear_slot()
            self._shown_addon = addon
            try:
                own = addon.card(self.have_page)
            except Exception as e:  # noqa: BLE001 - an add-on can't break the tab
                log.exception("Onion Pocket couldn't make its card for its tab")
                own = hint_label(_("Onion Pocket's settings didn't open: {error}",
                                   error=errors.plain(e)))
            self.addon_slot.addWidget(own)
        from soundboard.addons import pocketaddon
        self.btn_remove.setVisible(pocketaddon.removable(info))   # (not a copy run from elsewhere)
        self._say_version(info)
        self.stack.setCurrentWidget(self.have_page)

    def _say_version(self, info):
        from soundboard.core import updates
        if self._offer is not None and not updates.newer(self._offer.version, info.version):
            self._offer = None
        self.version.setText(_("Onion Pocket {version} is installed.",
                               version=info.version))
        offer = self._offer
        new = offer is not None
        text = (_("Update to {version}", version=offer.version) if offer is not None
                else _("Check for updates"))
        if self.btn_check.text() != text and not busy.is_busy(self.btn_check):
            self.btn_check.setText(text)
            self.btn_check.setObjectName("primary" if new else "")
            self.btn_check.style().unpolish(self.btn_check)
            self.btn_check.style().polish(self.btn_check)

    # ------------------------------------------------------------------ getting it
    def get(self, offer=None, btn: QPushButton | None = None, text: str = ""):
        """Download, install and start Onion Pocket (the newest, or `offer`) on a thread;
        the page follows once it's in. Returns at once."""
        from soundboard.addons import pocketaddon
        from soundboard.online import netlog
        btn = btn or self.btn_get
        if busy.is_busy(btn):
            return
        release = busy.hold(btn, text or _("Getting Onion Pocket…"))
        self.error.hide()
        netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket (the Pocket tab)")
        relay = _Relay(self.mw)   # the window's: it's loaded even if this tab goes

        def finish(new):
            relay.deleteLater()
            addon = self.mw.remctl.load_remote_addon(new) if new is not None else None
            if not qt_valid(self) or not qt_valid(btn):
                return
            if addon is None or new is None:
                release(_("✗ Didn't work"))
                self.error.setText(_("Couldn't get Onion Pocket right now. Check your "
                                     "internet connection and try again."))
                self.error.show()
                return
            release()
            self._offer = None
            self.refresh()
            busy.toast(self.mw, _("✓ Onion Pocket {version} is in.",
                                  version=html.escape(new.version)), "ok")

        relay.done.connect(finish)
        threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                         daemon=True, name="onion-pocket-tab").start()

    def check(self):
        """Check for updates; once one is found the button says *Update to X* and a
        click gets it (the running copy is swapped, paired phones stay)."""
        from soundboard.addons import pocketaddon
        from soundboard.core import updates
        from soundboard.online import net, netlog
        info, _addon = self._running()
        if info is None or busy.is_busy(self.btn_check):
            return
        if self._offer is not None:
            self.get(self._offer, self.btn_check, _("Updating…"))
            return
        if not net.allowed(pocketaddon.FEATURE) and pocketaddon.local_zip() is None:
            busy.toast(self.mw, html.escape(_("Add-on downloads are off (Privacy)")), "warn")
            return
        release = busy.hold(self.btn_check, _("Checking…"))
        netlog.cause(pocketaddon.FEATURE, "You clicked Check for updates (the Pocket tab)")
        relay = _Relay(self.mw)

        def done(offer, error):
            relay.deleteLater()
            if not qt_valid(self) or not qt_valid(self.btn_check):
                return
            if error:
                release(_("Couldn't check"))
                busy.toast(self.mw, html.escape(error), "warn")
            elif offer is not None and updates.newer(offer.version, info.version):
                release()
                self._offer = self.mw.pocket_offer = offer
                cur, _a = self._running()
                if cur is not None:
                    self._say_version(cur)
            else:
                release(_("✓ Up to date"))

        def ask():
            try:
                offer, error = pocketaddon.check_update(info), ""
            except Exception as e:  # noqa: BLE001 - offline, rate-limited…
                offer, error = None, _("Couldn't reach GitHub ({error}).",
                                       error=errors.plain(e))
            try:
                relay.found.emit(offer, error)
            except RuntimeError:   # the window closed meanwhile
                pass
        relay.found.connect(done)
        threading.Thread(target=ask, daemon=True, name="onion-pocket-tab-check").start()

    def _report(self):
        from soundboard import __version__
        from soundboard.core import feedback
        info, _a = self._running()
        busy.open_url(feedback.problem_url(
            __version__, f"Onion Pocket {info.version}" if info else "Onion Pocket"),
            self.btn_report, opened=_("✓ Opened in your browser"),
            failed=_("Couldn't open your browser. The page is"))

    def remove(self):
        """Uninstall Onion Pocket, after asking: its server stops and the tab offers to
        get it again."""
        from soundboard.addons import modules
        from soundboard.ui.kit import modalframe
        info, _a = self._running()
        if info is None:
            return
        if not modalframe.confirm(
                self.mw, _("Remove Onion Pocket?"),
                _("Remove the Onion Pocket add-on from Onion Board? Phones won't be able to play "
                  "your pads any more. Paired phones are kept for when you get it again.\n\nYou "
                  "can get it again from the Pocket tab any time."), _("Remove")):
            return
        try:
            self.mw.remctl.remove_remote_addon(info)
        except modules.ModuleError as e:
            log.warning("Onion Pocket couldn't be removed: %s", e)
            busy.toast(self.mw, html.escape(_("Onion Pocket wasn't removed: {error}",
                                              error=errors.plain(e))), "error")
            return
        self.mw.pocket_offer = None
        self.refresh()
        busy.toast(self.mw, _("✓ Onion Pocket removed."), "ok")

    # ------------------------------------------------------------------ the window's calls
    def shutdown(self):
        self._clear_slot()   # (the add-on itself runs on: it's the window's)
