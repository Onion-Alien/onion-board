"""The Triggers tab: plays a sound when something shows up in a game. The tab
itself is the Onion Watch add-on (soundboard.addons.watchaddon); this is Onion Board's
side of it:

  * Until the add-on is installed, the tab is Hoot's card: what Onion Watch does
    and a *Add Onion Watch to this tab* button (no window popping up on entering). One click
    downloads it (nothing is fetched before that), installs it into
    %APPDATA%\\OnionBoard\\modules and loads it into this tab, no restart needed.
    Triggers made before the add-on existed are kept in Config.screen meanwhile,
    and the tab says so.
  * Once it's loaded, the add-on's own tab (its create(host)), talking to the board
    only through BoardHost (ui/triggers/triggershost.py), with a bar on top when a newer
    Onion Watch is out (found by the app's daily update check).

An add-on that fails to load shows Hoot again with why, and a button to get it
afresh: a broken add-on never stops the app.

*Remove Onion Watch* (last in the add-on's More menu, or beside *Add Onion Watch
again* when it's broken) uninstalls it after asking, and Hoot is back; the triggers are kept.
"""
from __future__ import annotations

import html
import inspect
import logging
import threading

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (QBoxLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from soundboard.addons import addonmarks, modules, watchaddon
from soundboard.online import net, netlog
from soundboard.ui.kit import theme
from soundboard.core import updates, usage
from soundboard.i18n import _, ngettext
from soundboard.ui.voice import art
from soundboard.ui.settings import lite
from soundboard.ui.kit import busy, icons
from soundboard.style.owl import OwlWidget
from soundboard.ui.kit.panel import Flow, HoverCard, ShownStack, hint_label
from soundboard.ui.kit.widgets import LoadingBar
from soundboard.ui.triggers.logoduel import LogoDuel
from soundboard.core import errors

log = logging.getLogger(__name__)

HOOT_PX = 130
HOOT_REST_S = 30.0   # he moves this long, then holds still until the mouse or a sound
# what Hoot says while he waits to be installed, and when he's clicked
HOOT_BEGS = (_("pleeease?"), _("install me?"), _("one click!"), _("hoo? hoo…?"),
             _("I'd watch for you…"), _("so… bored…"))
HOOT_JOY = (_("yay!!"), _("hoo-ray!"), _("↓ that button!"))
# the steps of getting it with no number to show, by key (what _step carries): what
# the button says, and what the update bar says
STEPS = {"Finding the newest…": (_("Finding the newest…"), _("Finding the newest Onion Watch…")),
         "Downloading…": (_("Downloading…"), _("Downloading Onion Watch…")),
         "Installing…": (_("Installing…"), _("Installing Onion Watch…")),
         "Starting…": (_("Starting…"), _("Starting Onion Watch…"))}
SHOW_LOAD_MS = 50   # first shown, the add-on loads after the tab's first paint, or this


def _create(entry, host, parent):
    """The add-on's tab, made straight inside `parent` when it can be (a newer Onion
    Watch): moving a finished tab of a thousand widgets into the window afterwards
    restyles every one of them again, a good part of the second it took to open."""
    try:
        takes = "parent" in inspect.signature(entry.create).parameters
    except (TypeError, ValueError):
        takes = False
    return entry.create(host, parent=parent) if takes else entry.create(host)


class _WaitPage(QWidget):
    """The blank page while the add-on isn't loaded yet; tells the tab it was painted."""
    def __init__(self, painted):
        super().__init__()
        self._painted = painted

    def paintEvent(self, event):
        super().paintEvent(event)
        self._painted()


class TriggersTab(QWidget):
    active_changed = Signal(bool)          # watching or not (the tab's live dot)
    loaded = Signal()                      # the add-on's tab is in
    _progress = Signal(int, int)           # from the download thread (done, total)
    _step = Signal(str)                    # from it too: what it's doing, with no number
    _finished = Signal(object, str, bool)  # ModuleInfo | None, error, was an update

    def __init__(self, host, dirs=None, defer: bool = False):
        """`host` is the BoardHost; `dirs` where to look for the add-on (tests).
        `defer`: don't load the add-on yet; the window calls load() while it's built,
        behind the loading screen (MainWindow.load_triggers). If nothing has by the
        time the tab is shown, it loads then."""
        super().__init__()
        self.host = host
        self._dirs = dirs
        self.pending = defer               # load() hasn't run yet
        self.panel = None                  # the add-on's tab, once loaded
        self.logo_duel = LogoDuel(self)
        self.info: modules.ModuleInfo | None = None
        self._none_at: tuple | None = None   # the add-on folders when it wasn't there
        self.offer: watchaddon.Offer | None = None   # a newer version to update to
        self._busy = False
        self._closed = False
        self._cancel = False
        self._compact: dict[str, bool] = {}          # fit steps applied (see fit_steps)
        self._progress.connect(self._on_progress)
        self._step.connect(self._on_step)
        self._finished.connect(self._on_finished)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = ShownStack()
        v.addWidget(self.stack)
        self._build_get_page()
        self.board_page = QWidget()
        bv = QVBoxLayout(self.board_page)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        self._build_update_bar()
        net.on_change(self._follow_switch)
        bv.addWidget(self.update_bar)
        self.act_remove = None              # "Remove Onion Watch" in the add-on's More menu
        self.foot = QHBoxLayout()           # ...or, if it has none, under its tab
        self.foot.setContentsMargins(0, 6, 0, 0)
        self.foot.addStretch(1)
        self.btn_remove = self._remove_button()
        self.foot.addWidget(self.btn_remove)
        self.stack.addWidget(self.board_page)
        self._load_queued = False           # a load after the first paint is on its way
        if defer:   # blank meanwhile, not Hoot asking to be installed
            self.wait_page = _WaitPage(self._painted)
            self.stack.addWidget(self.wait_page)
            self.stack.setCurrentWidget(self.wait_page)
        else:
            self.load()

    # ------------------------------------------------------------------ pages
    def _build_get_page(self):
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 8, 0, 0)
        # Onion Watch's own card on the tab (it was a window popping up on entering
        # the tab, then a lone button: DESIGN section 0 keeps windows for questions
        # that need an answer). Short, like an ad: its logo and name, one line, what
        # it does as a few points, the button, Hoot beside it all.
        box = HoverCard()   # lights up under the mouse, as the Apps cards do
        bv = QVBoxLayout(box)
        # (16 at the sides: the Get button's icon gap needed 4 px, and this card sets the
        # narrowest window that isn't the mini player)
        bv.setContentsMargins(16, 16, 16, 16)
        box.setMaximumWidth(620)
        row = QHBoxLayout()
        row.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        pm = art.pixmap("onion-watch", 52)
        if pm is not None:
            logo.setPixmap(pm)
            logo.setFixedSize(52, 52)
        else:
            logo.hide()
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.title = QLabel("Onion Watch")
        self.title.setObjectName("helptitle")
        self.title.setWordWrap(True)
        names.addWidget(self.title)
        self.blurb = hint_label(_("Plays one of your sounds when something happens in "
                                  "your game."))
        names.addWidget(self.blurb)
        head.addLayout(names, 1)
        text.addLayout(head)
        points = QVBoxLayout()
        points.setSpacing(6)
        for pic, words in (
                ("gamepad", _("Rare spawns, queue pops, “YOU DIED”")),
                ("eye", _("Watches your game's window while it's open, even behind others")),
                ("volume", _("Can ring until you stop it")),
                ("shield", _("Only looks: never clicks or types in your game"))):
            line = QHBoxLayout()
            line.setSpacing(8)
            dot = QLabel()
            icons.set_label_icon(dot, pic, "accent_hi", size=16)
            line.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            lbl = QLabel(words)
            lbl.setWordWrap(True)
            line.addWidget(lbl, 1)
            points.addLayout(line)
        text.addLayout(points)
        self.kept = hint_label("")        # "Your 3 triggers are kept…"
        text.addWidget(self.kept)
        self.error = hint_label("")
        theme.set_tone(self.error, "warn")
        self.error.hide()
        text.addWidget(self.error)
        buttons = Flow(gap=8)
        self.btn_get = QPushButton()
        self.btn_get.setObjectName("primary")
        icons.set_icon(self.btn_get, "triggers", "on_accent")
        self.btn_get.clicked.connect(lambda: (usage.used("watch-prompt-get"), self.get()))
        buttons.addWidget(self.btn_get)
        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.hide()
        buttons.addWidget(self.btn_cancel)
        self.btn_remove_broken = self._remove_button()
        buttons.addWidget(self.btn_remove_broken)
        text.addLayout(buttons)
        # the download's real progress, and a pill gliding along while there's no
        # number to show (asking GitHub for the newest, installing, starting it): one
        # bar that just sat full looked like nothing was happening
        self.bar = QProgressBar()
        self.bar.setObjectName("downloadprogress")
        self.bar.setAccessibleName(_("Onion Watch download progress"))
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        text.addWidget(self.bar)
        self.working = LoadingBar()
        self.working.hide()
        text.addWidget(self.working)
        self.privacy = hint_label(_("Free, from GitHub, and only downloaded when you click."))
        self.privacy.setToolTip(_(
            "It's downloaded from Onion Watch's page on GitHub only when you click, and "
            "checked before it's installed. It only looks at your screen: it never "
            "clicks, types or touches your game."))
        text.addWidget(self.privacy)
        text.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        # Enough room for Hoot's speech bubble without squeezing the card's text.
        side = 16
        # (no dancing to what's playing: he sleeps in his bed until clicked, then
        # idles until the tab's left)
        self.hoot = OwlWidget(HOOT_PX, HOOT_BEGS, HOOT_JOY, left=side, right=side,
                              rest_after_s=lite.rest_s(HOOT_REST_S), sleeps=True)
        self.hoot.clicked.connect(lambda: (usage.used("hoot-talk"),
                                           self.btn_get.setFocus(Qt.FocusReason.OtherFocusReason)))
        row.addWidget(self.hoot, 0, Qt.AlignmentFlag.AlignCenter)
        bv.addLayout(row)
        # in the middle of the tab, a landing page rather than a box in its corner (a
        # row with stretches, not an alignment: that kept its wrapped text's height)
        mid = QHBoxLayout()
        mid.addStretch(1)
        mid.addWidget(box, 100)
        mid.addStretch(1)
        pv.addStretch(1)
        pv.addLayout(mid)
        pv.addStretch(2)
        self.get_page = page
        self.stack.addWidget(page)
        self._label_get()

    def _build_update_bar(self):
        self.update_bar = QWidget()
        h = QHBoxLayout(self.update_bar)
        h.setContentsMargins(0, 8, 0, 0)
        self.update_text = hint_label("")
        self.update_text.setTextFormat(Qt.TextFormat.PlainText)   # release notes: GitHub's text
        h.addWidget(self.update_text, 1)
        self.btn_update = QPushButton(_("Update"))
        self.btn_update.setObjectName("primary")
        self.btn_update.clicked.connect(self.get)
        h.addWidget(self.btn_update)
        self.btn_later = QPushButton(_("Later"))
        self.btn_later.clicked.connect(lambda: self.update_bar.hide())
        h.addWidget(self.btn_later)
        self.update_bar.hide()

    def _remove_button(self) -> QPushButton:
        b = QPushButton(_("Remove Onion Watch"))
        icons.set_icon(b, "trash", "danger_text")
        b.setToolTip(_("Uninstall the Onion Watch add-on. Your triggers are kept."))
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

    def _trigger_count(self) -> int:
        """How many triggers are saved: Onion Watch 0.6+ keeps those past the 50th
        under "more_triggers" (older versions never read that key)."""
        s = self.host.screen
        return len(s.get("triggers") or []) + len(s.get("more_triggers") or [])

    def _base(self):
        """The modules folder Onion Watch is installed into."""
        return self._dirs[0] if self._dirs else None

    def _label_get(self, error: str = ""):
        """The Hoot page's words: first time, or after it failed to load."""
        n = self._trigger_count()
        broken = self.info is not None and self.panel is None and not self._busy
        self.title.setText(_("Onion Watch couldn't start") if broken and error else
                           "Onion Watch")
        self.btn_get.setText(_("Add Onion Watch again") if broken and error
                             else _("Add Onion Watch to this tab"))
        icons.text_gap(self.btn_get)   # (its icon was set before it had words)
        local = watchaddon.local_zip()
        self.btn_get.setToolTip(_("Install {file}", file=local) if local is not None else
                                _("Download Onion Watch from GitHub and install it"))
        self.kept.setText(ngettext(
            "Your {n} trigger and its pictures are kept. They'll work again as soon as "
            "Onion Watch is installed.",
            "Your {n} triggers and their pictures are kept. They'll work again as soon as "
            "Onion Watch is installed.", n) if n else "")
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
    def has_addon(self) -> bool:
        """Whether Onion Watch is installed, or a local zip is there to install it from
        (Offline mode hides the tab when it's neither: it's only the Get button)."""
        if self.info is None:
            # not there: every add-on's module.json read again on each ask (Offline mode
            # asks a few times for each tab box), unless one of the folders changed
            stamp = modules.dirs_stamp(self._dirs)
            if stamp != self._none_at:
                self.info = watchaddon.installed(self._dirs)
                self._none_at = None if self.info is not None else stamp
        return self.info is not None or watchaddon.local_zip() is not None

    def needed_now(self) -> bool:
        """At the window's start (or the tab switched back on in Settings > Tabs):
        whether to load the add-on straight away. Only when it has to run (watching
        was on with triggers to watch: it picks up again by itself) or there's none
        installed (Hoot's page costs nothing, and the board may point at the tab).
        Otherwise it waits until the tab is first shown: loading it costs ~0.5 s,
        40+ MB and a dozen threads that a board not watching never needs."""
        self.info = watchaddon.installed(self._dirs)   # Settings > Add-ons shows it
        if self.info is None:
            return True
        return bool(self.host.screen.get("on")) and self._trigger_count() > 0

    def ensure_loaded(self):
        """Load the add-on now if it's still waiting to be (something needs it)."""
        if self.pending:
            self.load()

    def showEvent(self, event):
        super().showEvent(event)
        self.logo_duel.bind()
        if self.pending and not self._load_queued:
            # the tab changes at once (its first paint), then it loads; a timer as
            # well, in case that paint never comes
            self._load_queued = True
            QTimer.singleShot(SHOW_LOAD_MS, self, self._load_on_show)
        elif not self.pending:
            QTimer.singleShot(0, self, self._get_page_shown)

    def _get_page_shown(self):
        """Hoot's page came into view: counted (the names only, usage.py)."""
        if (not self._closed and not self.pending and self.panel is None
                and self.isVisible() and self.stack.currentWidget() is self.get_page):
            usage.used("watch-prompt-shown")

    def _painted(self):
        if self._load_queued:
            QTimer.singleShot(0, self, self._load_on_show)

    def _load_on_show(self):
        if not self._load_queued:
            return
        self._load_queued = False
        if self.pending and not self._busy and self.isVisible():
            self.load()

    def load(self, error: str = "") -> bool:
        """Put the installed add-on's tab in, if it's there and loads. False (Hoot
        stays, saying why) otherwise."""
        self.pending = False
        if self.panel is not None:
            return True
        self.info = watchaddon.installed(self._dirs)
        if self.info is None:
            self._label_get(error)
            self.stack.setCurrentWidget(self.get_page)
            QTimer.singleShot(0, self, self._get_page_shown)
            return False
        try:
            entry = modules.load_package(self.info)
            panel = _create(entry, self.host, self.board_page)
        except Exception as e:  # noqa: BLE001 - a broken add-on can't stop the app
            log.warning("Onion Watch couldn't be loaded: %s", e, exc_info=True)
            self._label_get(watchaddon.friendly(e))
            self.stack.setCurrentWidget(self.get_page)
            QTimer.singleShot(0, self, self._get_page_shown)
            return False
        self.panel = panel
        self.logo_duel.bind()
        lay = self.board_page.layout()
        assert isinstance(lay, QBoxLayout)   # made in __init__
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
                                                 _("Remove Onion Watch"), self.remove)
            else:
                lay.addLayout(self.foot)
                self.btn_remove.show()
        if hasattr(panel, "active_changed"):
            panel.active_changed.connect(self.active_changed)
        for key, compact in self._compact.items():
            self._apply_fit(key, compact)
        bar = self._bar()
        if bar is not None:
            bar.installEventFilter(self)    # its width changing: _fit_bar
        self.stack.setCurrentWidget(self.board_page)
        self._fit_bar()
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
        self.ensure_loaded()   # not shown yet: what's installed now is what's updated
        self._busy, self._cancel = True, False
        update = self.panel is not None
        offer = self.offer
        busy.set_busy(self.btn_get, True)
        busy.set_busy(self.btn_update, True)
        self.btn_cancel.show()
        self.error.hide()
        netlog.cause(watchaddon.FEATURE, "You clicked to get Onion Watch (Triggers tab)")
        self._on_step("Finding the newest…" if offer is None else "Downloading…")
        busy.set_busy(self.btn_cancel, False)
        self.btn_cancel.setText(_("Cancel"))

        def run():
            try:
                o = offer or watchaddon.latest(lambda: self._cancel)
                if o is None:
                    raise updates.UpdateError(_(
                        "there's no Onion Watch release the app can check. Try again later."))
                busy.emit(self._step, "Downloading…")
                path = watchaddon.fetch(o, lambda *a: busy.emit(self._progress, *a),
                                        lambda: self._cancel)
                if self._cancel:   # clicked as it finished (or a local zip: no download)
                    raise updates.UpdateError(_("cancelled"))
                busy.emit(self._step, "Installing…")
                info = watchaddon.install(path, self._base())
                busy.emit(self._finished, info, "", update)
            except Exception as e:  # noqa: BLE001 - offline, 404, bad zip…
                log.info("getting Onion Watch failed: %s", e)
                busy.emit(self._finished, None, watchaddon.friendly(e), update)
        threading.Thread(target=addonmarks.marked(addonmarks.WATCH, run), daemon=True,
                         name="onion-watch").start()

    def cancel(self):
        self._cancel = True
        busy.set_busy(self.btn_cancel, True)   # the download notices between chunks
        self.btn_cancel.setText(_("Cancelling…"))

    def _busy_label(self, text: str):
        """What the button that started it says while it runs (the bar and Cancel are
        on the get page; an update from the bar only has its own button and text)."""
        (self.btn_update if self.panel is not None else self.btn_get).setText(text)

    def _on_step(self, step: str):
        """A step with no number to show (a key of STEPS): the gliding pill, and what
        it's doing."""
        if not self._busy:
            return
        self.bar.hide()
        self.bar.setValue(0)
        self.working.show()
        self.working.start()
        if step in ("Installing…", "Starting…"):
            self.btn_cancel.hide()   # can't be stopped half-way: no Cancel to ignore
        button, line = STEPS.get(step, (step, step))
        self._busy_label(button)
        self.update_text.setText(line)

    def _on_progress(self, done: int, total: int):
        if total <= 0 or not self._busy:
            return              # size unknown: the pill keeps gliding
        self.working.stop()
        self.working.hide()
        self.bar.show()
        self.bar.setValue(max(self.bar.value(), min(1000, int(done * 1000 / total))))
        pct = self.bar.value() // 10
        self._busy_label(_("Downloading… {percent}%", percent=pct))
        self.update_text.setText(_("Downloading Onion Watch… {percent}%", percent=pct))

    def _on_finished(self, info, error: str, update: bool):
        if not error and not update:
            # loading it takes a moment on this thread: say so, and let that paint
            # before it starts (the bar would otherwise sit at its last frame)
            self.btn_cancel.hide()
            self._on_step("Starting…")
            QTimer.singleShot(30, self, lambda: self._finish(info, error, update))
            return
        self._finish(info, error, update)

    def _finish(self, info, error: str, update: bool):
        self._busy = False
        self.working.stop()
        self.working.hide()
        busy.set_busy(self.btn_get, False)
        busy.set_busy(self.btn_update, False)
        self.btn_update.setText(_("Update"))
        self._label_get()                   # the get button's own words (and switch) again
        self.btn_cancel.hide()
        self.bar.hide()
        if update:
            if error:
                self.update_text.setText(_("Onion Watch wasn't updated: {error}",
                                           error=errors.plain(error)))
            else:
                self.offer = None
                self.btn_update.hide()
                self.btn_later.setText(_("OK"))
                self.update_text.setText(_("Onion Watch {version} is installed. Restart "
                                           "Onion Board to start using it.",
                                           version=info.version))
            return
        if error:
            # "Cancelled": updates' UpdateError("cancelled") as watchaddon.friendly words it
            self._label_get(_("Cancelled.") if self._cancel or error == "Cancelled" else error)
            return
        self.offer = None
        self.load()

    # ------------------------------------------------------------------ removing it
    def confirm_remove(self) -> bool:
        n = self._trigger_count()
        text = (ngettext("Remove the Onion Watch add-on from Onion Board? Your {n} trigger "
                         "and its pictures are kept for when you get it again.\n\nYou can "
                         "get it again from the Triggers tab any time.",
                         "Remove the Onion Watch add-on from Onion Board? Your {n} triggers "
                         "and their pictures are kept for when you get it again.\n\nYou can "
                         "get it again from the Triggers tab any time.", n) if n else
                _("Remove the Onion Watch add-on from Onion Board?\n\nYou can get it again "
                  "from the Triggers tab any time."))
        return QMessageBox.question(
            self, _("Remove Onion Watch?"), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes

    def remove(self):
        """Uninstall Onion Watch, after asking: its tab is closed and Hoot is back."""
        info = self.info
        if self._busy:
            busy.toast(self, _("Onion Watch is being downloaded right now. Try again "
                               "when it's done."), "warn")
            return
        if info is None or not self.confirm_remove():
            return
        was_active = self.is_active()
        panel, self.panel = self.panel, None
        self.logo_duel.bind()
        if panel is not None:
            try:
                panel.shutdown()
            except Exception:  # noqa: BLE001 - it's being removed anyway
                log.warning("Onion Watch didn't shut down cleanly", exc_info=True)
            lay = self.board_page.layout()
            if lay is not None:
                lay.removeWidget(panel)
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
            busy.toast(self, html.escape(_("Onion Watch wasn't removed: {error}",
                                           error=errors.plain(e))), "error")
            self.load()                     # it's still there: put its tab back
            return
        log.info("Onion Watch %s was removed", info.version)
        self.info = None
        self.pending = False                # nothing left to load
        self._label_get()
        self.stack.setCurrentWidget(self.get_page)
        n = self._trigger_count()
        busy.toast(self, _("✓ Onion Watch removed. Your triggers are kept.") if n
                   else _("✓ Onion Watch removed."), "ok")

    def offer_update(self, offer: watchaddon.Offer):
        """A newer Onion Watch is out (the daily update check): say so on the tab
        (not loaded yet, but installed: the bar is there once it is)."""
        waiting = self.pending and self.info is not None
        if (self.panel is None and not waiting) or self._busy:
            return
        self.offer = offer
        self.update_text.setText(
            _("Onion Watch {version} is out. {notes}", version=offer.version, notes=offer.notes)
            if offer.notes else _("Onion Watch {version} is out.", version=offer.version))
        self.btn_update.show()
        self.btn_later.setText(_("Later"))

        self.update_bar.show()

    # ------------------------------------------------------------------ for the board
    def needs_nudge(self) -> bool:
        """Triggers were being watched before the add-on existed and it isn't in:
        worth pointing at the tab once."""
        s = self.host.screen
        return (self.panel is None and not self.pending
                and bool(s.get("on")) and bool(s.get("triggers"))
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
        self.logo_duel.stop()
        self._closed = True
        self._cancel = True
        if self.panel is not None:
            try:
                self.panel.shutdown()
            except Exception:  # noqa: BLE001 - closing the app must carry on
                log.warning("Onion Watch didn't shut down cleanly", exc_info=True)

    # ------------------------------------------------------------------ small windows
    FIT = {"hint": "hide", "interval_label": "hide", "cut": "icon", "add": "icon",
           "paste": "icon", "watch": "icon"}
    BAR = ("cut", "paste", "add", "watch", "interval_label")   # icon only in this order

    def fit_steps(self):
        """What the main window may squeeze here when it gets small (ui/window/responsive.py):
        the hint at the top. It applies to the add-on's tab whenever it's in, also when
        it arrives later. The bottom bar's buttons go by the bar's own room (_fit_bar):
        as the window's steps they also lost their words when another tab was what
        didn't fit, and kept them off until the window grew."""
        def hint(compact: bool):
            self._compact["hint"] = compact
            self._apply_fit("hint", compact)
        return [(20, "h", hint)]

    def _bar(self) -> QWidget | None:
        """The add-on's bottom bar: what its buttons sit in."""
        parts = self.panel.fit_parts() if self.panel is not None else {}
        button = next((parts[k] for k in self.BAR if k in parts), None)
        return button.parentWidget() if button is not None else None

    def _fit_bar(self):
        """The bar's buttons keep their words while they fit on one line in the bar,
        and go icon only, first to last in BAR, while they don't."""
        bar = self._bar()
        if bar is None or self.panel is None or bar.layout() is None or bar.width() <= 0:
            return
        lay = bar.layout()
        assert lay is not None
        keys = [k for k in self.BAR if k in self.panel.fit_parts()]

        def over() -> bool:
            lay.invalidate()
            if lay.hasHeightForWidth():   # a wrapping row: wraps at this width
                return lay.heightForWidth(bar.width()) > lay.heightForWidth(1 << 20)
            return lay.sizeHint().width() > bar.width()

        if not any(self._compact.get(k) for k in keys) and not over():
            return   # (the usual case: nothing to measure again)
        bar.setUpdatesEnabled(False)
        try:
            for k in keys:
                self._set_bar(k, False)
            for k in keys:
                if not over():
                    break
                self._set_bar(k, True)
        finally:
            bar.setUpdatesEnabled(True)

    def _set_bar(self, key: str, compact: bool):
        if self._compact.get(key, False) != compact:
            self._compact[key] = compact
            self._apply_fit(key, compact)

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Resize and obj is self._bar()
                and event.size().width() != event.oldSize().width()):
            self._fit_bar()
        return False

    def _apply_fit(self, key: str, compact: bool):
        from soundboard.ui.window import responsive as r
        parts = self.panel.fit_parts() if self.panel is not None else {}
        w = parts.get(key)
        if w is None:
            return
        if self.FIT.get(key) == "icon":
            w.setProperty("compact", compact)
            r.icon_only(w)(compact)
        else:
            r.hide(w)(compact)
