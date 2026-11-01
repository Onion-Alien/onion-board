"""The Settings page of the main window: opening it on a page (in the window's place, never a
pop-up), growing the mini player to fit it, closing it and keeping it for next time when
nothing it shows has changed, and building it (and a spare Edit sound) ahead of time
behind the loading screen so the first click opens at once.

MainWindow makes one ``SettingsControl`` (``MainWindow.setctl``); everything here runs on
the UI thread."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget
from shiboken6 import isValid as qt_valid

from soundboard.control import remote
from soundboard.audio.engine import is_virtual as is_virtual_cable
from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.settings import routewarn
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog, rehome_crash_reports
from soundboard.ui.sounds.dialogs import EditDialog
from soundboard.ui.window.routecontrol import ROUTE_DEVICE
from soundboard.ui.triggers.triggerstab import TriggersTab

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

SETTINGS_ROOM = QSize(480, 520)   # what Settings opened from the mini player grows it to
REBUILD_MS = 2000   # after a Settings that can't be kept closes, a new one is made ahead


def _holds_focus(w: QWidget) -> bool:
    """The keyboard focus is in `w`."""
    fw = QApplication.focusWidget()
    return fw is not None and w.isAncestorOf(fw)


def _polish(w: QWidget, size=None):
    """Style a hidden widget and its children now, and lay it out at `size` (Qt waits
    for the first show for both)."""
    w.ensurePolished()
    for c in w.findChildren(QWidget):
        c.ensurePolished()
    if size is not None:
        w.resize(size)
    for lay in [c.layout() for c in (w, *w.findChildren(QWidget))]:
        if lay is not None:
            lay.activate()


class SettingsControl(Controller):
    """The Settings page of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        # windows beside the board, not over it: the one Settings, and an Edit
        # sound for each sound being edited
        self._settings_dlg: SettingsDialog | None = None
        self._spare_editor: EditDialog | None = None   # a closed one, reused (edit)
        self._settings_kept: SettingsDialog | None = None   # closed Settings, reused
        self._settings_kept_print = None

    def open_settings(self, page: str | None = None):
        """Settings as a page in the window, in the tabs' place (the rail stays, its
        cog selected): they apply as they change, and sounds and hotkeys keep working
        while it's up. [Done], Escape or any tab on the rail goes back to the tab you
        were on. Asked for again while up: the same page, on `page` if one is named."""
        mw = self.mw
        # asked for from Bun (his menu, a toast's button): the window comes back first,
        # or the page opened in a window nobody could see
        if mw.bunctl.bun_up():
            mw.bunctl.leave_bun_mode(False)
        dlg = self._settings_dlg
        fresh = dlg is None or not qt_valid(dlg)
        if dlg is not None and not fresh:
            if page:
                dlg.show_page(page)
        else:
            dlg, self._settings_kept = self._settings_kept, None
            # nothing it shows changed since it closed: the same one, as it was left
            if dlg is not None and qt_valid(dlg) \
                    and self._settings_print() == self._settings_kept_print:
                dlg.show_page(page or "audio")
                if getattr(dlg, "dev_combos", None):
                    dlg.audio._sync_devices()
            else:
                if dlg is not None and qt_valid(dlg):
                    free_dialog(dlg)
                dlg = SettingsDialog(mw, page or "audio", lazy=True)
                dlg.finished.connect(lambda _r, d=dlg: self._settings_closed(d))
            self._settings_dlg = dlg
            # (what "Send my sounds to" was: a new pick is checked on the way out)
            self._route_at_open = (mw.cfg.route, mw.cfg.main_device)
            mw._content.addWidget(dlg)
        mw._content.setCurrentWidget(dlg)
        mw.fitctl._fit_body_top()
        self._opening_settings = True   # (_refit: not closed again for being too small)
        try:
            self._board_counts(False)
            if mw.fitctl.is_mini():
                self._grow_for_settings()
        finally:
            self._opening_settings = False
        mw.rail.select_foot(mw.gear)
        mw.newctl.follow()   # (Sounds out of sight, or back)
        mw.transctl._show_transport()
        # (Escape is for it now; fresh, not the back arrow: the mini player's swap
        # handed the focus on to it, ringed)
        if fresh or not _holds_focus(dlg):
            dlg.categories.setFocus(Qt.FocusReason.OtherFocusReason)
        return dlg

    def _board_counts(self, on: bool):
        """The tabs hidden behind Settings don't count towards the room the window
        needs (a stack takes its widest page's): the board needs 464 px, Settings fits
        in less, so a 440 px window stayed the mini player with Settings out of sight."""
        mw = self.mw
        policy = QSizePolicy.Policy.Preferred if on else QSizePolicy.Policy.Ignored
        mw._tabs_area.setSizePolicy(policy, policy)
        if hasattr(mw.fitctl, "_fit"):
            mw.fitctl._refit()

    def _grow_for_settings(self):
        """Settings asked for from the mini player: the window grows to the smallest
        size that shows them (SETTINGS_ROOM, or what the window needs), on the screen."""
        mw = self.mw
        screen = mw.screen().availableGeometry() if mw.screen() else None
        for _try in range(4):
            size = mw._pages.size()
            need = mw.fitctl._fit.fit(size).expandedTo(SETTINGS_ROOM)
            if (not mw.fitctl.is_mini() and size.width() >= need.width()
                    and size.height() >= need.height()):
                break
            grow = need.expandedTo(size) - size
            w, h = mw.width() + grow.width(), mw.height() + grow.height()
            if screen is not None:
                w, h = min(w, screen.width()), min(h, screen.height())
            mw.resize(w, h)
            mw.fitctl._refit()

    def settings_open(self) -> bool:
        mw = self.mw
        dlg = self._settings_dlg
        return dlg is not None and qt_valid(dlg) and mw._content.currentWidget() is dlg

    def close_settings(self):
        """Back from Settings to the tabs, as [Done] does (nothing to undo: it's live)."""
        if self.settings_open() and self._settings_dlg is not None:   # (settings_open checked)
            self._settings_dlg.accept()

    def _settings_closed(self, dlg):
        mw = self.mw
        if self._settings_dlg is dlg:
            self._settings_dlg = None
        had_focus = getattr(dlg, "had_focus", False) or _holds_focus(dlg)
        mw._content.setCurrentWidget(mw._tabs_area)
        mw._content.removeWidget(dlg)
        mw.fitctl._fit_body_top()
        self._board_counts(True)
        mw.rail.select_foot(None)
        mw.newctl.follow()   # (Sounds out of sight, or back)
        mw.transctl._show_transport()
        if had_focus:   # (not left on a page that's gone)
            mw._focus_sounds_page(mw.tabs.currentIndex())
            if not _holds_focus(mw._tabs_area):
                mw.tabs.currentWidget().setFocus(Qt.FocusReason.OtherFocusReason)
        if self._settings_reusable(dlg):   # opened again as it is: no 100-300 ms rebuild
            # (pages with live state shown: each built afresh when it's shown again)
            dlg.mark_stale(mw.SETTINGS_LIVE_PAGES)
            rehome_crash_reports(dlg)
            old, self._settings_kept = self._settings_kept, dlg
            self._settings_kept_print = self._settings_print()
            if old is not None and old is not dlg and qt_valid(old):
                QTimer.singleShot(0, lambda: free_dialog(old))
        else:   # freed once its finished signal is over (deleting it inside that crashed)
            QTimer.singleShot(0, lambda: free_dialog(dlg))
            # built again while nothing's going on, or every later open built Settings
            # from scratch (80-140 ms, seconds on a busy PC)
            QTimer.singleShot(REBUILD_MS, self._prebuild_settings)
        mw.hkctl.register_hotkeys()   # in case a capture was cancelled
        self._check_route_pick()

    @staticmethod
    def _settings_reusable(dlg) -> bool:
        return qt_valid(dlg) and not dlg.search_box.text()

    def _settings_print(self) -> str:
        """What a kept Settings shows: the config (less what it doesn't show) and the
        device lists. Anything else changed since it closed: a new one is built."""
        mw = self.mw
        from dataclasses import fields
        c = mw.cfg
        state = {f.name: getattr(c, f.name) for f in fields(c)
                 if f.name not in mw.SETTINGS_PRINT_SKIP and not f.name.startswith("stats_")}
        for key, cb in (("~mic", mw.cb_mic), ("~mon", mw.cb_mon), ("~route", mw.cb_route)):
            state[key] = (
                [cb.itemData(i) for i in range(cb.count())], cb.currentIndex())
        return repr(sorted(state.items()))

    def _check_route_pick(self):
        """Leaving Settings with "Send my sounds to" newly on a device that isn't a
        virtual cable (speakers, a headset): asks whether that's meant, since Discord
        and games don't hear it. Only for a new pick, so OBS and mixer users who chose
        it on purpose aren't asked every time."""
        mw = self.mw
        c = mw.cfg
        before = getattr(self, "_route_at_open", None)
        self._route_at_open = None
        if before == (c.route, c.main_device) or not c.main_device \
                or not routewarn.needs_warning(c.route, c.main_device, c.mon_device):
            return
        # (the picker already lists the outputs: no device call here)
        names = [mw.cb_route.itemData(i) or "" for i in range(mw.cb_route.count())]
        cables = [n[len(ROUTE_DEVICE):] for n in names
                  if n.startswith(ROUTE_DEVICE) and is_virtual_cable(n[len(ROUTE_DEVICE):])]
        box = self._route_warning = routewarn.RouteWarning(c.main_device, bool(cables), mw)

        def done(code, dev=c.main_device):
            self._route_warning = None
            QTimer.singleShot(0, lambda: free_dialog(box))   # (not inside finished)
            # (still that device: not changed elsewhere while it was up)
            if mw.cfg.main_device != dev or mw.cfg.route != "device":
                return
            if code == routewarn.MIC:
                mw.routectl.set_route("mic", by_hand=True)
            elif code == routewarn.CABLE:
                # on the cable, then Setup: it shows the cable working, or installing it
                mw.routectl.set_route("cable", cables[0] if cables else None, by_hand=True)
                mw.tabs.setCurrentWidget(mw.setup_page)
                if not cables:
                    mw.micctl.install_cable()
        box.finished.connect(done)
        box.open()

    def preload_dialogs(self):
        """Behind the loading screen: Settings (its first page) and an Edit sound are
        built now, so even the first click of the cog or Edit opens at once (each took
        100-300 ms to build); Settings' other pages follow one at a time once it's up."""
        self._prebuild_settings()
        remote.answer_waiting()   # a Stream Deck press meanwhile: between the two
        self.prebuild_editor()

    def prebuild_editor(self):
        """A closed Edit sound made ahead (~250 ms, ~1 s on a slower PC), unless one is
        kept or open already (closing it keeps it), there's no sound to show, or the
        window is going. Behind the loading screen, or the theme cover."""
        mw = self.mw
        if (self._spare_editor is not None or mw.editctl._editors or not mw.cfg.sounds
                or getattr(mw, "_quitting", False) or not qt_valid(mw)):
            return
        d = mw.editctl._new_editor(mw.cfg.sounds[0], "sound")
        d.hide()
        _polish(d)
        self._spare_editor = d

    def _prebuild_settings(self):
        """A closed Settings made ahead (its first page now, the rest one at a time),
        unless one is up or kept already, or the window is going."""
        mw = self.mw
        if (self._settings_dlg is not None or self._settings_kept is not None
                or getattr(mw, "_quitting", False) or not qt_valid(mw)):
            return
        dlg = SettingsDialog(mw, "audio", lazy=True)
        dlg.hide()
        dlg.finished.connect(lambda _r, d=dlg: self._settings_closed(d))
        _polish(dlg, mw._content.size())
        self._settings_kept, self._settings_kept_print = dlg, self._settings_print()
        self._preload_pages = [i for i, k in enumerate(dlg._page_keys)
                               if i in dlg._unbuilt and k not in mw.SETTINGS_LIVE_PAGES]
        QTimer.singleShot(1500, self._preload_next_page)

    def warm_settings(self):
        """Still behind the loading screen, the window up: the kept Settings goes in
        the window's place once, with drawing off (nothing changes on screen), so Qt's
        first-show work (~100 ms) isn't left for the first click of the cog."""
        mw = self.mw
        dlg = self._settings_kept
        if dlg is None or not qt_valid(dlg) or not mw.isVisible() or self.settings_open():
            return
        mw.setUpdatesEnabled(False)
        try:
            mw._content.addWidget(dlg)
            mw._content.setCurrentWidget(dlg)
            QApplication.processEvents()
            dlg.grab()
        finally:
            mw._content.setCurrentWidget(mw._tabs_area)
            mw._content.removeWidget(dlg)
            dlg.hide()
            mw.setUpdatesEnabled(True)

    def warm_triggers(self):
        """Like warm_settings, for the Triggers tab: Onion Watch is loaded while the
        window is built, but its first show at full size still lays out the list and
        builds the editor beside it (~100-300 ms). Shown once here, with drawing off and
        the tab's signals quiet (nothing saved or counted), then the tab picked before."""
        mw = self.mw
        t = mw.triggers
        if (not isinstance(t, TriggersTab) or t.panel is None or not mw.isVisible()
                or self.settings_open() or mw.tabs.currentWidget() is t):
            return
        before = mw.tabs.currentIndex()
        mw.setUpdatesEnabled(False)
        mw.tabs.blockSignals(True)
        try:
            mw.tabs.setCurrentWidget(t)
            QApplication.processEvents()
            t.grab()
        finally:
            mw.tabs.setCurrentIndex(before)
            mw.tabs.blockSignals(False)
            mw.setUpdatesEnabled(True)

    def _preload_next_page(self):
        """One more of the kept Settings' pages built (~20-60 ms each), while it's closed."""
        mw = self.mw
        dlg, pages = self._settings_kept, getattr(self, "_preload_pages", [])
        if dlg is None or not qt_valid(dlg) or not pages:
            return
        dlg._build_page(pages.pop(0))
        _polish(dlg, mw._content.size())
        QTimer.singleShot(60, self._preload_next_page)

    def _drop_spare_dialogs(self):
        """The kept Edit sound and Settings go before a new theme (restyling them would
        be wasted): the Edit sound is built again in it (prebuild_editor), Settings the
        next time it opens."""
        for attr in ("_spare_editor", "_settings_kept"):
            d = getattr(self, attr, None)
            setattr(self, attr, None)
            if d is not None and qt_valid(d):
                free_dialog(d)
