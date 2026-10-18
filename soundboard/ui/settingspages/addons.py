"""Settings → Add-ons and Remote: Onion Watch, Onion Pocket, remote control."""
from __future__ import annotations

import html
import logging
import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget
from shiboken6 import isValid as qt_valid

from soundboard import errors
from soundboard.i18n import _
from soundboard.ui import busy, icons
from soundboard.ui.settingspages import Page, _button_row
from soundboard.wheelguard import no_wheel


log = logging.getLogger(__name__)


class _AddonGrid(QWidget):
    """Settings → Add-ons: each add-on's name, status line and buttons, the buttons in
    shared columns so they line up from one add-on to the next. As many columns as
    fit (4, else 2, else 1): it never makes the page wider than its window."""
    GAP = 8

    def __init__(self, cols: int):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.GAP)
        self.grid.setVerticalSpacing(6)
        self.max_cols = self.cols = cols
        self.rows: list[tuple[QLabel, QLabel, list[list[QPushButton]]]] = []

    def add(self, title: QLabel, status: QLabel, cells: list[list[QPushButton]]):
        for cell in cells:
            for b in cell:
                b.setMinimumWidth(40)    # the columns decide; resizeEvent keeps it readable
        self.rows.append((title, status, cells))
        self._place()

    def _need(self, cols: int) -> int:
        w = max((b.sizeHint().width() for _t, _s, cells in self.rows
                 for cell in cells for b in cell), default=0)
        return cols * w + (cols - 1) * self.GAP

    def _place(self):
        g, cols = self.grid, self.cols
        from soundboard.ui.widgets import take_out   # (it imports this module)
        while g.count():
            take_out(g)
        for r in range(g.rowCount()):
            g.setRowMinimumHeight(r, 0)
        r = 0
        for i, (title, status, cells) in enumerate(self.rows):
            if i:
                g.setRowMinimumHeight(r, 6)      # a gap between add-ons
                r += 1
            g.addWidget(title, r, 0, 1, cols)
            g.addWidget(status, r + 1, 0, 1, cols)
            r += 2
            for n, cell in enumerate(cells):
                for b in cell:
                    g.addWidget(b, r + n // cols, n % cols)
            r += (len(cells) + cols - 1) // cols
        for c in range(self.max_cols):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e):
        cols = self.max_cols
        while cols > 1 and self._need(cols) > e.size().width():
            cols //= 2
        if cols != self.cols:
            self.cols = cols
            self._place()
        super().resizeEvent(e)


class AddonsPage(Page):
    """Settings → Add-ons and Remote: Onion Watch, Onion Pocket, remote control."""

    def _addons_card(self):
        """Every add-on in one place, each with the same row of buttons in the same
        order: Check for updates (Update to X once one is out), Reinstall (a fresh
        copy of the newest; the user's triggers / paired phones are the board's and
        stay), Report a problem, Remove. Not installed: Get it, and Report a problem.
        One grid for all of them (_AddonGrid): the buttons share columns, so they line
        up from one add-on to the next, folding to two columns in a narrow window."""
        card, cv = self._card(_("Add-ons"),
                              _("Free add-ons from GitHub. Removing or reinstalling one keeps "
                                "your triggers and paired phones."), icon="puzzle")
        grid = _AddonGrid(len(self.dlg.ADDON_COLUMNS))
        cv.addWidget(grid)      # in the card first: a button shown without a parent
        self._watch_block(grid)  # is a window of its own
        self._pocket_block(grid)
        self.dlg._addons_card_w = card
        self.dlg._watch_refresh()   # (_addon_offline: the card, now it's known)
        return card

    def _addon_block(self, grid, name: str, blurb: str):
        """An add-on's name and what it's for, a status line, and its buttons, as rows
        of the Add-ons grid. (status label, {key: button})."""
        title = QLabel(f"<b>{html.escape(name)}</b> · {html.escape(blurb)}")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        status = QLabel()
        status.setObjectName("hint")
        status.setWordWrap(True)
        btns = {}
        for key, text, icon in (("get", _("Get {name}", name=name), ""),
                                ("check", _("Check for updates"), "reload"),
                                ("reinstall", _("Reinstall"), ""),
                                ("report", _("Report a problem"), ""),
                                ("remove", _("Remove"), "trash")):
            b = QPushButton(text)
            if icon:
                icons.set_icon(b, icon, "danger_text" if key == "remove" else None)
            btns[key] = b
        btns["get"].setObjectName("primary")
        btns["reinstall"].setToolTip(_("Downloads the newest {name} again and puts it in place "
                                       "of this one. Your own things are kept.", name=name))
        btns["report"].setToolTip(_("Opens a bug report on GitHub in your browser, with the "
                                    "versions filled in"))
        grid.add(title, status, [[btns[k] for k in keys] for keys in self.dlg.ADDON_COLUMNS])
        if not hasattr(self.dlg, "_addon_titles"):
            self.dlg._addon_titles = {}
        self.dlg._addon_titles[status] = title
        return status, btns

    def _addon_offline(self, status, b, have: bool, can_get: bool):
        """Offline mode on an add-on's row (after its refresh): Check for updates and
        Reinstall go; not installed, with nothing on this PC to install it from, the
        whole row goes. The Add-ons card goes when no row is left."""
        from soundboard import net
        if not net.offline():
            row = True
        else:
            row = have or can_get
            for k in ("check", "reinstall"):
                b[k].hide()
            if not row:
                for btn in b.values():
                    btn.hide()
        b["report"].setVisible(row)
        title = self.dlg._addon_titles.get(status)
        for w in (title, status):
            if w is not None:
                w.setVisible(row)
        card = getattr(self.dlg, "_addons_card_w", None)
        if card is not None and qt_valid(card):
            self.dlg.privacy._offline_card(card, lambda: not any(
                s.isVisibleTo(card) for s in self.dlg._addon_titles if qt_valid(s)))

    def _addon_report(self, btn, what: str):
        from soundboard import __version__, feedback
        busy.open_url(feedback.problem_url(__version__, what), btn,
                      opened=_("✓ Opened in your browser"),
                      failed=_("Couldn't open your browser. The page is"))

    def _addon_check(self, btn, feature: str, latest, newer_than: str, on_offer):
        """Check for updates: asks GitHub on a thread (`latest()` -> offer or None);
        a newer one calls `on_offer(offer)`, else the button says it's up to date."""
        from soundboard import net, netlog, updates
        if not net.allowed(feature):
            busy.toast(self.dlg, html.escape(_("Add-on downloads are off (Privacy)")), "warn")
            return
        release = busy.hold(btn, _("Checking…"))
        relay = self.dlg._AddonRelay(self.dlg)
        netlog.cause(feature, "You clicked Check for updates (Settings > Add-ons)")

        def done(offer, error):
            relay.deleteLater()
            if not qt_valid(btn):
                return
            if error:
                release(_("Couldn't check"))
                busy.toast(self.dlg, html.escape(error), "warn")
            elif offer is not None and updates.newer(offer.version, newer_than):
                release()
                on_offer(offer)
            else:
                release(_("✓ Up to date"))

        def ask():
            try:
                offer, error = latest(), ""
            except Exception as e:  # noqa: BLE001 - offline, rate-limited, switched off…
                offer, error = None, _("Couldn't reach GitHub ({error}).",
                                       error=errors.plain(e))
            try:
                relay.done.emit(offer, error)
            except RuntimeError:        # Settings was closed meanwhile
                pass
        relay.done.connect(done)
        threading.Thread(target=ask, daemon=True, name="addon-check").start()

    # ---- Onion Watch (the Triggers tab's add-on, soundboard.addons.watchaddon)
    def _watch_block(self, grid):
        from soundboard.addons import watchaddon
        status, b = self._addon_block(grid, "Onion Watch", _("the Triggers tab"))
        self.dlg.addon_label, self.dlg.addon_remove = status, b["remove"]
        self.dlg.watch_buttons = b
        state = {}

        def tab():
            """The Triggers tab there now: switched off and on again (Settings > Tabs)
            while this is open, it's a new one; switched off, None (nothing of it is
            loaded)."""
            return self.mw.triggers if self.mw.tabctl.tab_on("triggers") else None

        def refresh(note: str = ""):
            if not qt_valid(status):
                return
            t = tab()
            if t is None:
                status.setText(_("The Triggers tab is switched off (Settings > Tabs)."))
                for btn in b.values():
                    btn.hide()
                return
            b["report"].setVisible(True)   # back on (Settings > Tabs)
            info = t.info
            have = info is not None and watchaddon.removable(info, t._base())
            status.setText(note or (_("Version {version} is installed.", version=info.version)
                                    if have and info is not None
                                    else _("Onion Watch isn't installed.")))
            b["get"].setVisible(not have)
            for k in ("check", "reinstall", "remove"):
                b[k].setVisible(have)
            if not have:
                state.pop("offer", None)
            self._label_update(b["check"], state.get("offer"))
            self._addon_offline(status, b, have, watchaddon.local_zip() is not None)

        def run_get(offer, btn, text):
            """tab.get() does the work (and shows it on the Triggers tab too)."""
            t = tab()
            if t is None:
                return
            if t._busy:
                busy.flash(btn, _("Already downloading"))
                return
            t.offer = offer
            release = busy.hold(btn, text)

            def finished(info, error, _update):
                t._finished.disconnect(finished)
                if not qt_valid(btn):
                    return
                release(_("✗ Didn't work") if error else _("✓ Done"))
                state.pop("offer", None)
                refresh(_("Onion Watch wasn't installed: {error}", error=errors.plain(error))
                        if error else
                        (_("Version {version} is in. Restart Onion Board to start using it.",
                           version=info.version) if _update else ""))
                QTimer.singleShot(0, lambda: refresh() if not error and not _update
                                  else None)
            t._finished.connect(finished)
            t.get()

        def check():
            if state.get("offer") is not None:      # "Update to X"
                run_get(state["offer"], b["check"], _("Updating…"))
                return
            t = tab()
            if t is None:
                return
            info = t.info

            def found(offer):
                state["offer"] = offer
                t = tab()
                if t is not None:
                    t.offer_update(offer)
                refresh()
            self._addon_check(b["check"], watchaddon.FEATURE, watchaddon.latest,
                              info.version if info else "0", found)

        def remove():
            t = tab()
            if t is not None:
                t.remove()              # asks first
            refresh()

        b["get"].clicked.connect(lambda: run_get(None, b["get"], _("Getting it…")))
        b["check"].clicked.connect(check)
        b["reinstall"].clicked.connect(lambda: run_get(None, b["reinstall"],
                                                       _("Reinstalling…")))
        def report():
            t = tab()
            info = t.info if t is not None else None
            self._addon_report(b["report"],
                               f"Onion Watch {info.version}" if info else "Onion Watch")
        b["report"].clicked.connect(report)
        b["remove"].clicked.connect(remove)
        self.dlg._watch_refresh = refresh   # the Tabs page switched Triggers off or on
        refresh()   # in the card first: shown without a parent, it's a window of its own

    @staticmethod
    def _label_update(btn, offer):
        """Check for updates, or *Update to X* (primary) once a newer one is found."""
        text = _("Update to {version}",
                 version=offer.version) if offer is not None else _("Check for updates")
        if btn.text() != text and not busy.is_busy(btn):
            btn.setText(text)
            btn.setObjectName("primary" if offer is not None else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ---- Onion Pocket (the phone remote, soundboard.addons.pocketaddon)
    def _pocket_block(self, grid):
        from soundboard.addons import pocketaddon
        from soundboard import updates
        status, b = self._addon_block(grid, "Onion Pocket", _("your pads on your phone"))
        self.dlg.pocket_remove_addons = b["remove"]
        self.dlg.pocket_buttons = b
        state = {}

        def refresh(note: str = ""):
            if not qt_valid(status):
                return
            info = self._pocket_info()
            have = info is not None and pocketaddon.removable(info)
            if info is not None and info.error and have:
                note = note or _("Version {version} is installed but didn't start: "
                                 "{error}. Reinstall it, or report the problem.",
                                 version=info.version, error=info.error)
            status.setText(note or (_("Version {version} is installed. Its settings are on "
                                      "the Remote page.", version=info.version)
                                    if have and info is not None else
                                    _("Onion Pocket isn't installed.")))
            b["get"].setVisible(not have and pocketaddon.offered())
            for k in ("check", "reinstall", "remove"):
                b[k].setVisible(have)
            offer = state.get("offer")
            if not have or (offer is not None and info is not None
                            and not updates.newer(offer.version, info.version)):
                state.pop("offer", None)
            self._label_update(b["check"], state.get("offer"))
            self._addon_offline(status, b, have, pocketaddon.local_zip() is not None)

        def check():
            if state.get("offer") is not None:      # "Update to X"
                self._pocket_install(b["check"], state["offer"], _("Updating…"))
                return
            info = self._pocket_info()

            def found(offer):
                state["offer"] = offer
                self.mw.pocket_offer = offer
                refresh()
            self._addon_check(b["check"], pocketaddon.FEATURE, pocketaddon.latest,
                              info.version if info else "0", found)

        b["get"].clicked.connect(lambda: self._pocket_install(b["get"], None,
                                                              _("Getting it…")))
        b["check"].clicked.connect(check)
        b["reinstall"].clicked.connect(lambda: self._pocket_install(b["reinstall"], None,
                                                                    _("Reinstalling…")))
        b["report"].clicked.connect(lambda: self._addon_report(
            b["report"], f"Onion Pocket {i.version}" if (i := self._pocket_info())
            else "Onion Pocket"))
        b["remove"].clicked.connect(lambda: self._remove_pocket(b["remove"]))
        self.dlg._pocket_refresh = refresh
        refresh()

    def _pocket_install(self, btn, offer, text: str):
        """Get / reinstall / update Onion Pocket from the Add-ons card: downloads it
        (pocketaddon.get), the main window swaps it in for any running copy (paired
        phones stay), and its card on Settings → Remote is replaced by the new one's."""
        from soundboard import netlog
        from soundboard.addons import pocketaddon

        class Relay(QObject):
            done = Signal(object)

        release = busy.hold(btn, text)
        netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket "
                                          "(Settings > Add-ons)")
        relay = Relay(self.mw)   # the main window's: it's loaded even if Settings closes

        def finish(new):
            relay.deleteLater()
            addon = self.mw.remctl.load_remote_addon(new) if new is not None else None
            if new is not None:
                self.mw.pocket_offer = None
            if not qt_valid(btn):
                return
            if addon is None:
                release(_("✗ Didn't work"))
                busy.toast(self.dlg, _("Couldn't get Onion Pocket right now. Check your "
                                       "internet connection and try again."), "warn")
                self._pocket_changed()
                return
            release(_("✓ Done"))
            assert new is not None   # (addon is None without it)
            if getattr(self.dlg, "_pocket_slot", None) is not None:
                fresh = self._addon_card(new, addon)
                if fresh is not None:
                    self._pocket_remove_button(fresh, new)
                self._swap_pocket_slot(fresh)
            self._pocket_changed()
            busy.toast(self.dlg, _("✓ Onion Pocket {version} is in.",
                                   version=html.escape(new.version)), "ok")

        relay.done.connect(finish)
        threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                         daemon=True, name="onion-pocket-addons").start()

    def _remote(self):
        w, v = self._page()
        v.addWidget(self._remote_card())
        for card in self._remote_addon_cards():
            v.addWidget(card)
        v.addWidget(self._remote_easy_card())
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ remote control
    def _remote_card(self):
        """The local control API (soundboard.control.remote): on / off, port, key."""
        from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

        from soundboard.control import remote
        mw, cfg = self.mw, self.mw.cfg
        card, cv = self._card(_("Remote control (Stream Deck, scripts)"),
                              _("Lets programs on this PC play your sounds: a Stream Deck (its "
                                "API-request or website buttons, Bitfocus Companion, Touch "
                                "Portal), AutoHotkey or a script. Only this PC can connect, and "
                                "only with the key below, treat it like a password."), icon="cable")
        on = QCheckBox(_("Enable remote control"))
        on.setChecked(cfg.api_enabled)
        cv.addWidget(on)
        row = QGridLayout()
        row.addWidget(QLabel(_("Port")), 0, 0)
        port = QSpinBox()
        port.setRange(1024, 65535)
        port.setValue(cfg.api_port)
        port.setAccessibleName(_("Port"))
        no_wheel(port)
        row.addWidget(port, 0, 1)
        row.addWidget(QLabel(_("Key")), 1, 0)
        key = QLineEdit()
        key.setReadOnly(True)
        key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setAccessibleName(_("Key"))
        row.addWidget(key, 1, 1)
        show = QPushButton(_("Show"))
        show.setCheckable(True)

        def show_key(b: bool):
            key.setEchoMode(QLineEdit.EchoMode.Normal if b else QLineEdit.EchoMode.Password)
            show.setText(_("Hide") if b else _("Show"))

        show.toggled.connect(show_key)
        row.addWidget(show, 1, 2)
        new = QPushButton(_("New key"))
        new.setToolTip(_("Make a new key: anything using the old one stops working"))
        row.addWidget(new, 1, 3)
        cv.addLayout(row)
        crow = QHBoxLayout()
        copy = QPushButton(_("Copy an example link"))
        copy.setToolTip(_("A link that plays a random sound, paste it into a Stream Deck "
                          "website / API-request button, or open it to try it"))
        crow.addWidget(copy)
        state = QLabel()
        state.setObjectName("hint")
        state.setWordWrap(True)
        crow.addWidget(state, 1)
        cv.addLayout(crow)
        help_ = QLabel(_("Endpoints: {endpoints}. E.g. /api/play?name=Airhorn, "
                         "/api/random?category=Memes, /api/live?on=toggle. Send the key as "
                         "?token=…, an X-Token header or Authorization: Bearer …. /api/help "
                         "describes each one.",
                         endpoints=" · ".join(f"/api/{a}" for a in remote.ENDPOINTS)))
        help_.setObjectName("hint")
        help_.setWordWrap(True)
        help_.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cv.addWidget(help_)

        def refresh(err: str = ""):
            key.setText(cfg.api_token)
            if not cfg.api_enabled:
                show.setChecked(False)   # turning it off hides the key again
            for w in (port, key, show, new, copy):
                w.setEnabled(cfg.api_enabled)
            if not cfg.api_enabled:
                state.setText(_("Off."))
            elif err or not mw.remote.running:
                state.setText(_("Couldn't start: {error}", error=err or mw.remote.error))
            else:
                state.setText(_("On: listening on {host}:{port}.",
                                host=remote.HOST, port=mw.remote.port))

        # saved on the saver's thread (mw._save_now: its _on_saved says when it fails),
        # never cfg.save() here: the whole config written on the UI thread
        def set_on(b: bool):
            cfg.api_enabled = b
            mw._save_now()
            refresh(mw.remctl.apply_remote())

        def set_port():
            if port.value() != cfg.api_port:
                cfg.api_port = port.value()
                mw._save_now()
                refresh(mw.remctl.apply_remote())

        def new_key():
            cfg.api_token = remote.new_token()
            refresh(mw.remctl.apply_remote())
            running = mw.remote.running

            def saved(ok: bool):   # only now is it the key after a restart too
                if not qt_valid(self.dlg) or not qt_valid(new):
                    return
                if not ok:   # it'd go back to the old one: no "made"
                    busy.toast(self.dlg, html.escape(_(
                        "Couldn't save your settings, see the log in %APPDATA%\\OnionBoard.")),
                        "error")
                    return
                busy.flash(new, _("✓ New key made"))
                if running:
                    busy.toast(self.dlg, html.escape(_(
                        "New key made: anything using the old one has stopped working. Copy "
                        "the example link for the new one.")), "warn")
            mw._save_now(saved)

        def copy_link():
            QApplication.clipboard().setText(
                f"http://{remote.HOST}:{cfg.api_port}/api/random?token={cfg.api_token}")
            busy.toast(self.dlg, html.escape(_("Copied. It holds your key: only paste it into your "
                                               "own tools.")), "ok")

        on.toggled.connect(set_on)
        port.editingFinished.connect(set_port)
        new.clicked.connect(new_key)
        copy.clicked.connect(copy_link)
        refresh()
        self.dlg.remote_on = on   # the streamer guide can turn it on: keep the box in step
        return card

    def _remote_addon_cards(self) -> list:
        """The cards of the "remote" add-ons (soundboard.addons.modules), e.g. Onion Pocket.
        They're optional: one that's broken is left out (it's in the log), never an
        error box. Without a working Onion Pocket, a card offering to get it."""
        from soundboard.addons import pocketaddon
        out, have = [], set()
        for info, addon in getattr(getattr(self.mw, "remctl", None), "remote_addons", []):
            card = self._addon_card(info, addon)
            if card is not None:
                if info.id == pocketaddon.MODULE_ID:
                    self._pocket_update(card, info)
                    self._pocket_remove_button(card, info)
                    self.dlg._pocket_slot = card
                out.append(card)
                have.add(info.id)
        if pocketaddon.MODULE_ID not in have and pocketaddon.offered():
            self.dlg._pocket_slot = self._get_pocket_card()
            out.append(self.dlg._pocket_slot)
        return out

    # ------------------------------------------------------------ Onion Pocket: remove
    def _pocket_info(self):
        """The installed Onion Pocket the app knows of (running or not), or None."""
        from soundboard.addons import pocketaddon
        return next((i for i, _a in getattr(getattr(self.mw, "remctl", None), "remote_addons", [])
                     if i.id == pocketaddon.MODULE_ID), None)

    def _pocket_remove_button(self, card, info):
        """*Remove Onion Pocket* at the foot of its own card on Settings → Remote."""
        from soundboard.addons import pocketaddon
        lay = card.layout()
        if lay is None or not pocketaddon.removable(info):
            return
        btn = QPushButton(_("Remove Onion Pocket"))
        btn.setToolTip(_("Takes the add-on out of Onion Board: phones can't play your pads any "
                         "more. Paired phones are kept for when you get it again."))
        icons.set_icon(btn, "trash", "danger_text")
        btn.clicked.connect(lambda: self._remove_pocket(btn))
        row = _button_row()
        row.addWidget(btn)
        lay.addLayout(row)
        self.dlg.pocket_remove = btn

    def _swap_pocket_slot(self, new):
        """Put `new` (a card, or None) where Onion Pocket's card is on Settings →
        Remote, if that page is built."""
        old = getattr(self.dlg, "_pocket_slot", None)
        self.dlg._pocket_slot = new
        if old is None or not qt_valid(old):
            return
        lay = old.parentWidget().layout() if old.parentWidget() else None
        if new is not None and lay is not None:
            lay.insertWidget(lay.indexOf(old), new)
        old.hide()
        old.deleteLater()

    def _pocket_changed(self):
        refresh = getattr(self.dlg, "_pocket_refresh", None)
        if refresh is not None:
            refresh()

    def _remove_pocket(self, btn):
        """Uninstall Onion Pocket, after asking: its server stops, and its card on
        Settings → Remote turns back into *Get Onion Pocket*."""
        from PySide6.QtWidgets import QMessageBox

        from soundboard.addons import modules, pocketaddon
        info = self._pocket_info()
        if info is None:
            return
        if QMessageBox.question(
                self.dlg, _("Remove Onion Pocket?"),
                _("Remove the Onion Pocket add-on from Onion Board? Phones won't be able to play "
                  "your pads any more. Paired phones are kept for when you get it again.\n\nYou "
                  "can get it again from Settings → Remote any time."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.mw.remctl.remove_remote_addon(info)
        except modules.ModuleError as e:
            log.warning("Onion Pocket couldn't be removed: %s", e)
            busy.toast(self.dlg, html.escape(_("Onion Pocket wasn't removed: {error}",
                                               error=errors.plain(e))), "error")
            return
        self.mw.pocket_offer = None
        if getattr(self.dlg, "_pocket_slot", None) is not None:
            self._swap_pocket_slot(self._get_pocket_card() if pocketaddon.offered()
                                   else None)
        self._pocket_changed()
        busy.toast(self.dlg, _("✓ Onion Pocket removed."), "ok")

    def _addon_card(self, info, addon):
        if addon is None:
            log.info("remote add-on %s left out of Settings: %s", info.id, info.error)
            return None
        try:
            return addon.card(self.dlg)
        except Exception as e:  # noqa: BLE001 - an add-on can't break Settings
            log.exception("add-on %s couldn't make its card", info.id)
            info.error = _("its settings failed: {error}", error=errors.plain(e))
            return None

    def _pocket_update(self, card, info):
        """*Update Onion Pocket to X* on its card (soundboard.addons.pocketaddon), once GitHub
        says a newer one is out: asked on a thread when Settings → Remote opens, at most
        once an hour (the answer is kept on the main window). Clicking it downloads the
        new one, and the main window swaps it in for the running copy, settings and
        all; then its new card takes this one's place. Optional and quiet: if anything
        fails, the old copy keeps running and the button just says it didn't work."""
        from soundboard import net, netlog, updates
        from soundboard.addons import pocketaddon
        mw = self.mw
        lay = card.layout()
        if lay is None:
            return

        class Relay(QObject):
            found = Signal(object)
            done = Signal(object)

        btn = QPushButton()
        btn.setObjectName("primary")
        btn.hide()
        row = _button_row()
        row.addWidget(btn)
        lay.addLayout(row)
        found = Relay(card)
        state = {}

        def show(offer):
            if offer is None or not qt_valid(btn) or not updates.newer(offer.version,
                                                                       info.version):
                return
            state["offer"] = offer
            btn.setText(_("Update Onion Pocket to {version}", version=offer.version))
            btn.setToolTip(_("You have {version}. Downloads it from GitHub and restarts Onion "
                             "Pocket: paired phones stay paired.", version=info.version))
            btn.show()

        def checked(offer):
            mw.pocket_offer = offer
            show(offer)

        def finish(new, relay):
            relay.deleteLater()
            addon = mw.remctl.load_remote_addon(new) if new is not None else None
            if new is not None:
                mw.pocket_offer = None      # installed: on disk now, whatever happens
            if not qt_valid(btn):
                return                      # Settings was closed: it's loaded anyway
            if addon is None:
                state["release"](_("Couldn't update it right now"))
                if new is not None:
                    btn.hide()
                return
            assert new is not None   # (addon is None without it)
            box = card.parentWidget().layout() if card.parentWidget() else None
            fresh = self._addon_card(new, addon)
            if fresh is not None and box is not None:
                self._pocket_remove_button(fresh, new)
                self.dlg._pocket_slot = card
                self._swap_pocket_slot(fresh)
                self._pocket_changed()
            else:
                state["release"]()
                btn.hide()
            busy.toast(self.dlg, _("✓ Onion Pocket {version} is in.",
                                   version=html.escape(new.version)), "ok")

        def run():
            offer = state.get("offer")
            if offer is None:
                return
            state["release"] = busy.hold(btn, _("Updating Onion Pocket…"))
            netlog.cause(pocketaddon.FEATURE, "You clicked to update Onion Pocket "
                                              "(Settings > Remote)")
            relay = Relay(mw)   # the main window's: it's swapped in even if Settings closes
            relay.done.connect(lambda new: finish(new, relay))
            threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                             daemon=True, name="onion-pocket-update").start()

        btn.clicked.connect(run)
        found.found.connect(checked)
        self.dlg.pocket_update = btn
        offer = getattr(mw, "pocket_offer", None)
        if offer is not None:
            show(offer)
        elif (time.time() - getattr(mw, "pocket_checked", 0.0) >= self.dlg.POCKET_CHECK_S
              and (pocketaddon.local_zip() is not None or net.allowed(pocketaddon.FEATURE))):
            mw.pocket_checked = time.time()
            netlog.cause(pocketaddon.FEATURE, "Settings > Remote: is a newer Onion Pocket out?")
            def ask():
                offer = pocketaddon.check_update(info)
                try:
                    found.found.emit(offer)
                except RuntimeError:        # Settings was closed meanwhile
                    pass
            threading.Thread(target=ask, daemon=True, name="onion-pocket-check").start()

    def _get_pocket_card(self):
        """*Get Onion Pocket* (soundboard.addons.pocketaddon): downloads, installs and starts
        it, then its own card takes this one's place. If that fails, this card just
        goes away; Onion Pocket is optional."""
        from soundboard import netlog
        from soundboard.addons import pocketaddon

        class Relay(QObject):
            done = Signal(object)

        card, cv = self._card(_("Onion Pocket: your pads on your phone"),
                              _("Scan a code with your phone's camera and tap a pad on the phone "
                                "to play it here. iPhone or Android, in the browser: nothing to "
                                "install on the phone. A free add-on from GitHub."), icon="phone")
        get = QPushButton(_("Get Onion Pocket"))
        row = _button_row()
        row.addWidget(get)
        cv.addLayout(row)
        relay = Relay(card)

        def finish(info):
            if not qt_valid(card):
                return
            addon = self.mw.remctl.load_remote_addon(info) if info is not None else None
            new = self._addon_card(info, addon) if addon is not None else None
            if new is not None:
                self._pocket_remove_button(new, info)
            self.dlg._pocket_slot = card
            self._swap_pocket_slot(new)
            self._pocket_changed()

        def run():
            busy.hold(get, _("Getting Onion Pocket…"))
            netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket "
                                              "(Settings > Remote)")
            threading.Thread(target=lambda: relay.done.emit(pocketaddon.get()),
                             daemon=True, name="onion-pocket").start()
        relay.done.connect(finish)
        get.clicked.connect(run)
        self.dlg.get_pocket = get
        # Offline mode: gone, unless there's a zip on this PC to install it from
        return self.dlg.privacy._offline_card(card, lambda: pocketaddon.local_zip() is None)

    def _remote_easy_card(self):
        """The easy way in: the streamer guide, and a prompt for an AI assistant."""
        from soundboard.ui.crashdialog import free_dialog
        from soundboard.ui.streamguide import StreamerGuide, copy_prompt
        mw = self.mw
        card, cv = self._card(_("Set it up the easy way"),
                              _("New to this? The streamer guide shows how to put your sounds on "
                                "Stream Deck keys, channel points and chat commands, step by "
                                "step. Or copy a ready-made message for ChatGPT, Claude or any "
                                "AI chat: it explains Onion Board's links and lists your sounds, "
                                "so the AI can set up whatever tools you use with you."),
                              icon="link")
        # side by side, wrapping (not widening the window) when Settings is narrow
        btns = _button_row()
        guide = QPushButton(_("Streamer guide"))
        guide.setObjectName("primary")
        btns.addWidget(guide)
        ai = QPushButton(_("Copy AI prompt"))
        icons.set_icon(ai, "copy")
        ai.setToolTip(_("Paste it into ChatGPT / Claude and say which tools you use"))
        btns.addWidget(ai)
        cv.addLayout(btns)
        with_key = QCheckBox(_("Put my key in the prompt"))
        with_key.setToolTip(_("Saves pasting it in yourself. The key only works on this PC, but "
                              "it's still a password: leave this off if you'd rather the AI "
                              "never sees it"))
        cv.addWidget(with_key)
        state = QLabel()
        state.setObjectName("hint")
        state.setWordWrap(True)
        cv.addWidget(state)

        def open_guide():
            g = StreamerGuide(self.dlg, mw)
            g.exec()
            free_dialog(g)
            box = getattr(self.dlg, "remote_on", None)
            if box is not None and box.isChecked() != mw.cfg.api_enabled:
                box.setChecked(mw.cfg.api_enabled)   # turned on there

        def copy_ai():
            state.setText(copy_prompt(mw, with_key.isChecked()))
            busy.flash(ai, _("✓ Copied"))

        guide.clicked.connect(open_guide)
        ai.clicked.connect(copy_ai)
        return card
