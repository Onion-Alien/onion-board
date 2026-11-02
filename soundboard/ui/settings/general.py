"""Settings → General: start-up, app set-up, programs, background, backup, reset."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard.mic import appsetup, profiles
from soundboard.core import autostart
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.settings import Page
from soundboard.ui.kit.wheelguard import no_wheel


class GeneralPage(Page):
    """Settings → General: start-up, app set-up, programs, background, backup, reset."""

    def _general(self):
        w, v = self._page()
        card, cv = self._card(_("Window"), icon="panel_open")
        top = QCheckBox(_("Keep window on top"))
        top.setChecked(self.mw.cfg.always_on_top)
        top.toggled.connect(self.mw.on_top_toggle)
        cv.addWidget(top)
        # its explanation under the box's text like every other option's (it sat at
        # the card's edge)
        one = self._option(cv, _("Play pads with one click"),
                           _("Otherwise, double-click to play. Ctrl+click selects without "
                             "playing."), self.mw.cfg.single_click, self.mw.set_single_click)
        one.setToolTip(_("Then Ctrl+click picks a pad without playing it"))
        if hasattr(getattr(self.mw, "tipctl", None), "set_tutorials_on"):
            self.dlg.box_tutorials = self._option(
                cv, _("Show tutorials"),
                _("A quick how-to the first time you open each tab."),
                self.mw.cfg.tutorials_on, self.mw.tipctl.set_tutorials_on)
        v.addWidget(card)
        v.addWidget(self._speed_card())
        v.addWidget(self._app_setup_card())
        if self.mw.cfg.category_programs:   # rules made before the category menu lost it
            v.addWidget(self._programs_card())
        v.addWidget(self._background_card())
        v.addWidget(self._backup_card())
        v.addWidget(self._reset_card())
        v.addStretch(1)
        return w

    def _speed_card(self):
        """Lite mode (ui/settings/lite.py): calmer and lighter for slower PCs, applied at
        once. Here, near the top, rather than at the end of Appearance's second tab, where
        people looking for it didn't find it."""
        card, cv = self._card(_("Speed"), icon="leaf")
        self.dlg.lite_check = self._option(
            cv, _("Lite mode"), _("For slower PCs, uses less CPU: no animations, Bun holds "
                                  "still and the themes are plain. Everything still works."),
            self.mw.cfg.lite_mode, self.mw.themectl.set_lite_mode)
        return card

    def _app_setup_card(self):
        """Set up for the app you're using (soundboard.mic.appsetup): ask or not, and the
        apps remembered or never asked about."""
        card, cv = self._card(
            _("Set up for the app you're using"),
            _("When a voice chat app or a game starts listening to you, a small bar offers "
              "to set the board up for it. Apps you set up switch the mode by themselves "
              "next time."), icon="setup")
        self.dlg.box_app_setup = self._option(
            cv, _("Offer to set up for new apps"),
            _("Off: nothing asks. Apps already set up still switch."),
            appsetup.settings(self.mw.cfg)["ask"], self._app_setup_ask)
        self.dlg.app_setup_list = QVBoxLayout()
        self.dlg.app_setup_list.setSpacing(4)
        cv.addLayout(self.dlg.app_setup_list)
        self._fill_app_setup()
        if hasattr(self.mw, "app_setup_changed"):
            self.mw.app_setup_changed.connect(self._fill_app_setup)
        return card

    def _app_setup_ask(self, on: bool):
        appsetup.settings(self.mw.cfg)["ask"] = bool(on)
        self.mw._save_later()

    def _fill_app_setup(self):
        lay = self.dlg.app_setup_list
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        s = appsetup.settings(self.mw.cfg)
        if not s["apps"] and not s["never"]:
            none = QLabel(_("No apps set up yet."))
            none.setObjectName("muted")
            lay.addWidget(none)
        names = {k: profiles.BY_KEY[k].name for k in appsetup.MODES}
        for exe, mode in sorted(s["apps"].items()):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel(exe), 1)
            if mode in names:
                cb = QComboBox()
                for k, n in names.items():
                    cb.addItem(n, k)
                cb.setCurrentIndex(cb.findData(mode))
                cb.setAccessibleName(_("Mode for {program}", program=exe))
                no_wheel(cb)
                cb.currentIndexChanged.connect(
                    lambda _i, e=exe, c=cb: self._app_setup_mode(e, c.currentData()))
                h.addWidget(cb)
            rm = QPushButton(_("Remove"))
            rm.setObjectName("small")
            rm.setToolTip(_("Forget {program}: it asks again next time", program=exe))
            icons.set_icon(rm, "trash", "danger_text", size=12)
            rm.clicked.connect(lambda _c=False, e=exe: self._app_setup_forget(e))
            h.addWidget(rm)
            lay.addWidget(row)
        for exe in sorted(s["never"]):
            if exe in s["apps"]:
                continue
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(_("{program}  (never asks)", program=exe))
            lbl.setObjectName("muted")
            h.addWidget(lbl, 1)
            again = QPushButton(_("Ask again"))
            again.setObjectName("small")
            again.clicked.connect(lambda _c=False, e=exe: self._app_setup_forget(e))
            h.addWidget(again)
            lay.addWidget(row)

    def _app_setup_mode(self, exe: str, mode: str):
        appsetup.remember(self.mw.cfg, exe, mode)
        self.mw._save_later()

    def _app_setup_forget(self, exe: str):
        appsetup.forget(self.mw.cfg, exe)
        self.mw._save_later()
        self._fill_app_setup()

    def _programs_card(self):
        """Switch category when a program is in front: every rule in one place."""
        card, cv = self._card(_("Switch category by program"), icon="apps")
        self.dlg.box_programs = self._option(
            cv, _("Switch by itself"),
            _("When the program closes, the board goes back to what it showed before."),
            self.mw.cfg.category_programs_on, self.mw.catctl.set_category_programs_on)
        self.dlg.programs_list = QVBoxLayout()
        self.dlg.programs_list.setSpacing(4)
        cv.addLayout(self.dlg.programs_list)
        self._fill_programs()
        if hasattr(self.mw, "category_programs_changed"):
            self.mw.category_programs_changed.connect(self._fill_programs)
        return card

    def _fill_programs(self):
        lay = self.dlg.programs_list
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        rules = self.mw.cfg.category_programs
        if not rules:
            none = QLabel(_("No programs set yet."))
            none.setObjectName("muted")
            lay.addWidget(none)
        for exe, cat in sorted(rules.items()):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            missing = cat not in self.mw.cfg.categories
            lbl = QLabel(_("{program}  →  “{category}”  (no such category now)",
                           program=exe, category=cat) if missing else
                         _("{program}  →  “{category}”", program=exe, category=cat))
            lbl.setObjectName("muted" if missing else "")
            h.addWidget(lbl, 1)
            rm = QPushButton(_("Remove"))
            rm.setObjectName("small")
            rm.setToolTip(_("Stop switching to “{category}” when {program} is in front",
                            category=cat, program=exe))
            icons.set_icon(rm, "trash", "danger_text", size=12)
            rm.clicked.connect(lambda _c=False, e=exe: self.mw.catctl.remove_category_program(e))
            h.addWidget(rm)
            lay.addWidget(row)

    def _reset_card(self):
        card, cv = self._card(_("Start over"),
                              _("Something's not right? Reset just the parts you pick: settings, "
                                "hotkeys, sounds, Recently deleted, Apps tab programs or audio "
                                "devices. A restore point is saved first, so it can always be "
                                "undone."), icon="history")
        row = QHBoxLayout()
        rst = QPushButton(_("Reset"))
        icons.set_icon(rst, "reload")
        rst.clicked.connect(lambda: self._open_reset(points=False))
        pts = QPushButton(_("Restore points"))
        pts.clicked.connect(lambda: self._open_reset(points=True))
        row.addWidget(rst)
        row.addWidget(pts)
        row.addStretch(1)
        cv.addLayout(row)
        return card

    def _open_reset(self, points: bool):
        from soundboard.ui.settings.resetguide import ResetGuide, RestorePoints
        (RestorePoints if points else ResetGuide)(self.mw, self.dlg).exec()

    # ------------------------------------------------------------------ backup
    def _backup_card(self):
        card, cv = self._card(_("Backup"),
                              _("Export puts every sound (with its picture, effects, hotkey and "
                                "categories) and your settings into one .zip: keep it safe, or "
                                "import it on another PC. Importing a friend's sound pack adds "
                                "its sounds; ones you already have are skipped."), icon="archive")
        row = QHBoxLayout()
        exp = QPushButton(_("Export everything"))
        icons.set_icon(exp, "folder")
        def export():
            mw = self.mw
            mw.impctl.export_board()
            if mw.impctl._exporting:   # it started (not cancelled in the save dialog)
                busy.hold_until(exp, _("Exporting…"), mw.bridge.exported,
                                lambda _p, _n, err, *_rest: _("Didn't export") if err
                                else _("✓ Exported"))
        exp.clicked.connect(export)
        imp = QPushButton(_("Import"))
        imp.clicked.connect(self.mw.impctl.import_dialog)
        row.addWidget(exp)
        row.addWidget(imp)
        row.addStretch(1)
        cv.addLayout(row)
        return card

    # ------------------------------------------------------------------ background
    def _background_card(self):
        mw = self.mw
        card, cv = self._card(_("Running in the background"),
                              _("A soundboard is most useful left running: your hotkeys and the "
                                "overlay work while the window is closed. The tray icon (by the "
                                "clock) opens it again; right-click it to quit."), icon="play")
        tray = QCheckBox(_("Close to tray"))
        tray.setChecked(mw.cfg.tray)
        tray.toggled.connect(lambda b: mw.set_option("tray", b))
        if mw.tray is None:
            tray.setEnabled(False)
            tray.setToolTip(_("This desktop has no system tray, so closing the window quits."))
        cv.addWidget(tray)
        auto = QCheckBox(_("Start when I sign in"))
        hidden = QCheckBox(_("Start in the tray"))
        auto.setChecked(autostart.is_enabled())
        hidden.setContentsMargins(22, 0, 0, 0)

        def sync_hidden():
            """Ticked only when it would do something: with sign-in start off it read
            as on by default. The saved choice is kept for when that's turned on."""
            on = auto.isChecked()
            hidden.blockSignals(True)
            hidden.setChecked(on and mw.cfg.autostart_hidden)
            hidden.blockSignals(False)
            hidden.setEnabled(on)
        sync_hidden()

        def set_auto(on: bool):
            if not mw.set_autostart(on):
                auto.blockSignals(True)
                auto.setChecked(autostart.is_enabled())
                auto.blockSignals(False)
                busy.toast(self.dlg, _("Couldn't change Windows startup, see the log in "
                                       "{folder}.", folder=r"%APPDATA%\OnionBoard"), "warn")
            sync_hidden()
        auto.toggled.connect(set_auto)
        hidden.toggled.connect(mw.set_autostart_hidden)
        if not autostart.available():
            auto.setEnabled(False)
            hidden.setEnabled(False)
        cv.addWidget(auto)
        cv.addWidget(hidden)
        return card
