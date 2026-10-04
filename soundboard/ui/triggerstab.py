"""The Triggers tab: plays a sound when something shows up in a game. The tab
itself is the Onion Watch add-on (soundboard.watchaddon); this is Onion Board's
side of it:

  * Until the add-on is installed, Hoot and a *Get Onion Watch* button. One click
    downloads it (nothing is fetched before that), installs it into
    %APPDATA%\\OnionBoard\\modules and loads it into this tab, no restart needed.
    Triggers made before the add-on existed are kept in Config.screen meanwhile,
    and the tab says so.
  * Once it's loaded, the add-on's own tab (its create(host)), talking to the board
    only through BoardHost (ui/triggershost.py), with a bar on top when a newer
    Onion Watch is out (found by the app's daily update check).

An add-on that fails to load shows Hoot again with why, and a button to get it
afresh: a broken add-on never stops the app.

*Remove Onion Watch…* (last in the add-on's More menu, or beside *Get Onion Watch
again* when it's broken) uninstalls it after asking, and Hoot is back; the triggers are kept.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QMessageBox, QProgressBar, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from soundboard import modules, net, netlog, theme, updates, watchaddon
from soundboard.ui import busy, icons
from soundboard.ui.owl import OwlWidget
from soundboard.ui.panel import card, hint_label, section_label
from soundboard import errors

log = logging.getLogger(__name__)

HOOT_PX = 130
# what Hoot says while he waits to be installed, and when he's clicked
HOOT_BEGS = ("pleeease?", "install me?", "one click!", "hoo? hoo…?", "I'd watch for you…",
             "so… bored…")
HOOT_JOY = ("yay!!", "hoo-ray!", "↓ that button!")


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


class TriggersTab(QWidget):
    active_changed = Signal(bool)          # watching or not (the tab's live dot)
    loaded = Signal()                      # the add-on's tab is in
    _progress = Signal(int, int)           # from the download thread
    _finished = Signal(object, str, bool)  # ModuleInfo | None, error, was an update

    def __init__(self, host, dirs=None):
        """`host` is the BoardHost; `dirs` where to look for the add-on (tests)."""
        super().__init__()
        self.host = host
        self._dirs = dirs
        self.panel = None                  # the add-on's tab, once loaded
        self.info: modules.ModuleInfo | None = None
        self.offer: watchaddon.Offer | None = None   # a newer version to update to
        self._busy = False
        self._cancel = False
        self._compact: dict[str, bool] = {}          # fit steps applied (see fit_steps)
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        self._build_get_page()
        self.board_page = QWidget()
        bv = QVBoxLayout(self.board_page)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        self._build_update_bar()
        net.on_change(self._follow_switch)
        bv.addWidget(self.update_bar)
        self.act_remove = None              # "Remove Onion Watch…" in the add-on's More menu
        self.foot = QHBoxLayout()           # ...or, if it has none, under its tab
        self.foot.setContentsMargins(0, 6, 0, 0)
        self.foot.addStretch(1)
        self.btn_remove = self._remove_button()
        self.foot.addWidget(self.btn_remove)
        self.stack.addWidget(self.board_page)
        self.load()

    # ------------------------------------------------------------------ pages
    def _build_get_page(self):
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 8, 0, 0)
        box, bv = card()
        row = QHBoxLayout()
        row.setSpacing(18)
        # the same room both sides, so he stands in the middle of his corner of the
        # card (his speech bubble may overlap him a little on the right)
        side = round(HOOT_PX * 0.6)
        self.hoot = OwlWidget(HOOT_PX, HOOT_BEGS, HOOT_JOY, left=side, right=side)
        self.hoot.setToolTip("Hoot is waiting for Onion Watch")
        row.addWidget(self.hoot, 0, Qt.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(8)
        self.title = section_label("")
        self.title.setWordWrap(True)
        text.addWidget(self.title)
        self.blurb = hint_label(
            "Onion Watch plays a sound when something shows up in your game: a rare "
            "spawn, a queue popping, “YOU DIED”. It watches the game's own window, even "
            "while other windows cover it, can tell two copies of a game apart, and can "
            "ring until you stop it. Your sounds play through the board as usual.")
        text.addWidget(self.blurb)
        self.kept = hint_label("")        # "Your 3 triggers are kept…"
        text.addWidget(self.kept)
        self.error = hint_label("")
        theme.set_tone(self.error, "warn")
        self.error.hide()
        text.addWidget(self.error)
        buttons = QHBoxLayout()
        self.btn_get = QPushButton()
        self.btn_get.setObjectName("primary")
        icons.set_icon(self.btn_get, "triggers", "on_accent")
        self.btn_get.clicked.connect(self.get)
        self.hoot.clicked.connect(lambda: self.btn_get.setFocus(Qt.OtherFocusReason))
        buttons.addWidget(self.btn_get)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.hide()
        buttons.addWidget(self.btn_cancel)
        self.btn_remove_broken = self._remove_button()
        buttons.addWidget(self.btn_remove_broken)
        buttons.addStretch(1)
        text.addLayout(buttons)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        text.addWidget(self.bar)
        self.privacy = hint_label(
            "It's downloaded from Onion Watch's page on GitHub only when you click, and "
            "checked before it's installed. It only looks at your screen: it never "
            "clicks, types or touches your game.")
        text.addWidget(self.privacy)
        text.addStretch(1)
        row.addLayout(text, 1)
        bv.addLayout(row)
        pv.addWidget(box)
        pv.addStretch(1)
        self.get_page = page
        self.stack.addWidget(page)
        self._label_get()

    def _build_update_bar(self):
        self.update_bar = QWidget()
        h = QHBoxLayout(self.update_bar)
        h.setContentsMargins(0, 8, 0, 0)
        self.update_text = hint_label("")
        h.addWidget(self.update_text, 1)
        self.btn_update = QPushButton("Update")
        self.btn_update.setObjectName("primary")
        self.btn_update.clicked.connect(self.get)
        h.addWidget(self.btn_update)
        self.btn_later = QPushButton("Later")
        self.btn_later.clicked.connect(lambda: self.update_bar.hide())
        h.addWidget(self.btn_later)
        self.update_bar.hide()

    def _remove_button(self) -> QPushButton:
        b = QPushButton("Remove Onion Watch…")
        icons.set_icon(b, "trash", "danger_text")
        b.setToolTip("Uninstall the Onion Watch add-on. Your triggers are kept.")
        b.clicked.connect(self.remove)
        b.hide()
        return b

    @staticmethod
    def _more_menu(panel):
        """The add-on's More menu (its btn_more), if it has one."""
        btn = getattr(panel, "btn_more", None)
        try:
            return btn.menu() if btn is not None else None
        except (AttributeError, RuntimeError):
            return None

    def _base(self):
        """The modules folder Onion Watch is installed into."""
        return self._dirs[0] if self._dirs else None

    def _label_get(self, error: str = ""):
        """The Hoot page's words: first time, or after it failed to load."""
        n = len(self.host.screen.get("triggers") or [])
        broken = self.info is not None and self.panel is None and not self._busy
        self.title.setText("Onion Watch couldn't start" if broken and error else
                           "Get Onion Watch for the Triggers tab")
        self.btn_get.setText("Get Onion Watch again" if broken and error
                             else "Get Onion Watch")
        local = watchaddon.local_zip()
        self.btn_get.setToolTip(f"Install {local}" if local is not None else
                                "Download Onion Watch from GitHub and install it")
        self.kept.setText(f"Your {plural(n, 'trigger')} and {'its' if n == 1 else 'their'} "
                          "pictures are kept. They'll work again as soon as Onion Watch is "
                          "installed." if n else "")
        self.kept.setVisible(bool(n))
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self.btn_remove_broken.setVisible(
            self.info is not None and watchaddon.removable(self.info, self._base()))
        self._follow_switch()

    def _follow_switch(self):
        """Getting add-ons switched off in Settings > Privacy & security: Get / Update
        are greyed, saying why (a local zip, ONIONBOARD_ONION_WATCH_ZIP, still installs)."""
        if self._busy:
            return
        ok = net.allowed(watchaddon.FEATURE) or watchaddon.local_zip() is not None
        why = "" if ok else net.off_message(watchaddon.FEATURE)
        self.btn_get.setEnabled(ok)
        if why:
            self.btn_get.setToolTip(why)
        if hasattr(self, "btn_update"):   # not yet while the get page is being built
            self.btn_update.setEnabled(ok)
            self.btn_update.setToolTip(why)

    # ------------------------------------------------------------------ loading
    def load(self, error: str = "") -> bool:
        """Put the installed add-on's tab in, if it's there and loads. False (Hoot
        stays, saying why) otherwise."""
        if self.panel is not None:
            return True
        self.info = watchaddon.installed(self._dirs)
        if self.info is None:
            self._label_get(error)
            self.stack.setCurrentWidget(self.get_page)
            return False
        try:
            entry = modules.load_package(self.info)
            panel = entry.create(self.host)
        except Exception as e:  # noqa: BLE001 - a broken add-on can't stop the app
            log.warning("Onion Watch couldn't be loaded: %s", e, exc_info=True)
            self._label_get(watchaddon.friendly(e))
            self.stack.setCurrentWidget(self.get_page)
            return False
        self.panel = panel
        lay = self.board_page.layout()
        lay.addWidget(panel, 1)
        if self.foot.parent() is not None:  # from an earlier load: put back only if needed
            lay.removeItem(self.foot)
            self.foot.setParent(None)
        self.act_remove = None
        if watchaddon.removable(self.info, self._base()):
            menu = self._more_menu(panel)
            if menu is not None:            # last in its More menu, no row of its own
                menu.addSeparator()
                self.act_remove = menu.addAction(icons.icon("trash", "danger_text"),
                                                 "Remove Onion Watch…", self.remove)
            else:
                lay.addLayout(self.foot)
                self.btn_remove.show()
        if hasattr(panel, "active_changed"):
            panel.active_changed.connect(self.active_changed)
        for key, compact in self._compact.items():
            self._apply_fit(key, compact)
        self.stack.setCurrentWidget(self.board_page)
        log.info("Onion Watch %s is the Triggers tab", self.info.version)
        self.loaded.emit()
        if self.is_active():
            self.active_changed.emit(True)
        return True

    # ------------------------------------------------------------------ getting it
    def get(self):
        """Get Onion Watch (the newest release, or the one offered as an update),
        on a thread; the tab loads it when it's in."""
        if self._busy:
            return
        self._busy, self._cancel = True, False
        update = self.panel is not None
        offer = self.offer
        self.btn_get.setEnabled(False)
        self.btn_update.setEnabled(False)
        self.btn_cancel.show()
        self.bar.setRange(0, 0)           # busy until the size is known
        self.bar.show()
        self.error.hide()
        self.update_text.setText("Downloading Onion Watch…")
        netlog.cause(watchaddon.FEATURE, "You clicked to get Onion Watch (Triggers tab)")
        self._busy_label("Downloading…")
        busy.set_busy(self.btn_cancel, False)
        self.btn_cancel.setText("Cancel")

        def run():
            try:
                o = offer or watchaddon.latest(lambda: self._cancel)
                if o is None:
                    raise updates.UpdateError(
                        "there's no Onion Watch release the app can check. Try again later.")
                path = watchaddon.fetch(o, self._progress.emit, lambda: self._cancel)
                info = watchaddon.install(path, self._base())
                self._finished.emit(info, "", update)
            except Exception as e:  # noqa: BLE001 - offline, 404, bad zip…
                log.info("getting Onion Watch failed: %s", e)
                self._finished.emit(None, watchaddon.friendly(e), update)
        threading.Thread(target=run, daemon=True, name="onion-watch").start()

    def cancel(self):
        self._cancel = True
        busy.set_busy(self.btn_cancel, True)   # the download notices between chunks
        self.btn_cancel.setText("Cancelling…")

    def _busy_label(self, text: str):
        """What the button that started it says while it runs (the bar and Cancel are
        on the get page; an update from the bar only has its own button and text)."""
        (self.btn_update if self.panel is not None else self.btn_get).setText(text)

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            pct = int(done * 100 / total)
            self._busy_label(f"Downloading… {pct}%")
            self.update_text.setText(f"Downloading Onion Watch… {pct}%")
            if done >= total:
                self._busy_label("Installing…")

    def _on_finished(self, info, error: str, update: bool):
        self._busy = False
        self.btn_get.setEnabled(True)
        self.btn_update.setEnabled(True)
        self.btn_update.setText("Update")
        self._label_get()                   # the get button's own words (and switch) again
        self.btn_cancel.hide()
        self.bar.hide()
        if update:
            if error:
                self.update_text.setText(f"Onion Watch wasn't updated: {errors.plain(error)}")
            else:
                self.offer = None
                self.btn_update.hide()
                self.btn_later.setText("OK")
                self.update_text.setText(f"Onion Watch {info.version} is installed. Restart "
                                         "Onion Board to start using it.")
            return
        if error:
            self._label_get("Cancelled." if error == "Cancelled" else error)
            return
        self.offer = None
        self.load()

    # ------------------------------------------------------------------ removing it
    def confirm_remove(self) -> bool:
        n = len(self.host.screen.get("triggers") or [])
        kept = (f" Your {plural(n, 'trigger')} and {'its' if n == 1 else 'their'} pictures "
                "are kept for when you get it again." if n else "")
        return QMessageBox.question(
            self, "Remove Onion Watch?",
            f"Remove the Onion Watch add-on from Onion Board?{kept}\n\n"
            "You can get it again from the Triggers tab any time.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def remove(self):
        """Uninstall Onion Watch, after asking: its tab is closed and Hoot is back."""
        info = self.info
        if self._busy:
            QMessageBox.information(self, "Remove Onion Watch",
                                    "Onion Watch is being downloaded right now. Try again "
                                    "when it's done.")
            return
        if info is None or not self.confirm_remove():
            return
        was_active = self.is_active()
        panel, self.panel = self.panel, None
        if panel is not None:
            try:
                panel.shutdown()
            except Exception:  # noqa: BLE001 - it's being removed anyway
                log.warning("Onion Watch didn't shut down cleanly", exc_info=True)
            self.board_page.layout().removeWidget(panel)
            panel.setParent(None)
            panel.deleteLater()
        self.btn_remove.hide()
        self.act_remove = None              # went with the add-on's menu
        self.update_bar.hide()
        self.offer = None
        if was_active:
            self.active_changed.emit(False)
        try:
            watchaddon.remove(info, self._base())
        except modules.ModuleError as e:
            log.warning("Onion Watch couldn't be removed: %s", e)
            QMessageBox.warning(self, "Onion Watch wasn't removed",
                                f"Onion Watch wasn't removed: {errors.plain(e)}")
            self.load()                     # it's still there: put its tab back
            return
        log.info("Onion Watch %s was removed", info.version)
        self.info = None
        self._label_get()
        self.stack.setCurrentWidget(self.get_page)
        n = len(self.host.screen.get("triggers") or [])
        busy.toast(self, "✓ Onion Watch removed." + (" Your triggers are kept." if n else ""),
                   "ok")

    def offer_update(self, offer: watchaddon.Offer):
        """A newer Onion Watch is out (the daily update check): say so on the tab."""
        if self.panel is None or self._busy:
            return
        self.offer = offer
        self.update_text.setText(f"Onion Watch {offer.version} is out."
                                 + (f" {offer.notes}" if offer.notes else ""))
        self.btn_update.show()
        self.btn_later.setText("Later")
        self.update_bar.show()

    # ------------------------------------------------------------------ for the board
    def needs_nudge(self) -> bool:
        """Triggers were being watched before the add-on existed and it isn't in:
        worth pointing at the tab once."""
        s = self.host.screen
        return (self.panel is None and bool(s.get("on")) and bool(s.get("triggers"))
                and not s.get("board_nudged"))

    def nudged(self):
        self.host.screen["board_nudged"] = True
        self.host.save()

    def is_active(self) -> bool:
        return self.panel is not None and bool(self.panel.is_active())

    def sounds_changed(self):
        self.host.sounds_changed()
        if self.panel is not None:
            self.panel.sounds_changed()

    def import_done(self):
        self.host.import_done()
        if self.panel is not None:
            self.panel.sounds_changed()

    def cancel_pending(self):
        """Stop all: sounds still waiting out a trigger's wait, and ringing."""
        if self.panel is not None:
            self.panel.cancel_pending()

    def retheme(self):
        theme.set_tone(self.error, "warn")
        if self.panel is not None:
            self.panel.retheme()

    def shutdown(self):
        self._cancel = True
        if self.panel is not None:
            try:
                self.panel.shutdown()
            except Exception:  # noqa: BLE001 - closing the app must carry on
                log.warning("Onion Watch didn't shut down cleanly", exc_info=True)

    # ------------------------------------------------------------------ small windows
    FIT = {"hint": "hide", "interval_label": "hide", "cut": "icon", "add": "icon",
           "paste": "icon", "watch": "icon"}

    def fit_steps(self):
        """What the main window may squeeze here when it gets small (ui/responsive.py).
        They apply to the add-on's tab whenever it's in, also when it arrives later."""
        from soundboard.ui import responsive as r

        def step(key):
            def apply(compact: bool):
                self._compact[key] = compact
                self._apply_fit(key, compact)
            return apply
        return [(20, "h", step("hint")), (21, "h", r.hide(self.hoot, self.blurb)),
                (25, "w", step("cut")), (26, "w", step("paste")), (27, "w", step("add")),
                (28, "w", step("watch")), (29, "w", step("interval_label"))]

    def _apply_fit(self, key: str, compact: bool):
        from soundboard.ui import responsive as r
        parts = self.panel.fit_parts() if self.panel is not None else {}
        w = parts.get(key)
        if w is None:
            return
        if self.FIT.get(key) == "icon":
            w.setProperty("compact", compact)
            r.icon_only(w)(compact)
        else:
            r.hide(w)(compact)
