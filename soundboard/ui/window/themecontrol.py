"""The main window's look: applying a theme to the whole window (and what it built ahead of
time), the Live colour, the background texture, lite mode, the live tab's tint, and painting
the onion logo.

MainWindow makes one ``ThemeControl`` (``MainWindow.themectl``); everything here runs on
the UI thread."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from soundboard.core import achievements, usage
from soundboard.win import shellicon
from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.settings import lite
from soundboard.ui.window import themecover
from soundboard.ui.window.controller import Controller
from soundboard.ui.window.livedot import set_tint as set_live_tint
from soundboard.ui.bun.logowidget import glow_icon

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

SPARE_AFTER_MS = 1500   # after a theme switch, the spare Edit sound is made again


class ThemeControl(Controller):
    """The theme and look of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def apply_theme(self, name: str):
        # a still of the window with Bun over it while every widget restyles: no frame
        # of a half-styled window, and it fades to the new theme (ui/window/themecover.py)
        mw = self.mw
        achievements.add("themes", name)
        with themecover.covered(mw, name):
            self._apply_theme(name)

    def _apply_theme(self, name: str):
        mw = self.mw
        mw.setctl._drop_spare_dialogs()
        mw.cfg.theme = theme.apply(QApplication.instance(), name)
        self.keep_limited()
        icons.retheme()
        mw.radio.retheme()
        mw.apps.retheme()
        mw.triggers.retheme()
        mw.download_bar.retheme()
        mw.mini_download_bar.retheme()
        mw.ytresults.retheme()
        mw.builder._paint_mini_bun()
        if mw.bunctl.bun_mode is not None:
            mw.bunctl.bun_mode.retheme()
        pp, mw._pp_icon = mw._pp_icon, None
        mw.playctl._set_pp_icon(pp or "play")
        mw._pill_long = ""   # forces _update_flow to repaint its icon
        mw.statusctl._update_status()   # the hints and flow, in this theme's status colours
        mw.rail.refresh_output()   # its status icon is a copy of the pill's: redrawn
        self._paint_logo()
        # the next Edit opens at once: a spare made again a moment later, on its own
        # (~250 ms, ~1 s on a slower PC), not added to this restyle's wait
        QTimer.singleShot(SPARE_AFTER_MS, mw, mw.setctl.prebuild_editor)
        mw._save_later()

    def keep_limited(self, save: bool = True):
        """The theme in use is a limited edition still on offer: theirs to keep."""
        if theme.keep(self.mw.cfg.theme):
            self.mw.cfg.kept_themes = sorted(theme.kept)
            if save:
                self.mw._save_later()

    def set_live_color(self, colour: str) -> bool:
        """The user's own highlight colour ("" = the theme's). Only what's drawn in it
        is restyled (quick); False when it's the colour in use already."""
        mw = self.mw
        if theme.valid_colour(colour) == theme.live_override:
            return False
        with themecover.blended(mw):   # (a fade from the old colour, not a swap)
            mw.set_option("live_color", theme.apply_live(QApplication.instance(), colour))
            icons.retheme_live()
            mw._pill_long = ""   # forces _update_flow to repaint its icon
            mw.statusctl._update_status()
        return True

    def set_theme_texture(self, on: bool):
        """Textured (each theme's own pattern on the panels) or Plain (flat panels)."""
        mw = self.mw
        if on != mw.cfg.theme_texture:
            mw.set_option("theme_texture", on)
        on = on and not lite.on()   # (lite mode: kept for later, Plain till then)
        if on == theme.textures_on:
            return
        theme.textures_on = on
        self.apply_theme(mw.cfg.theme)

    def set_lite_mode(self, on: bool):
        """Lite mode (ui/settings/lite.py): animations, Bun's and the logo's idle moves and the
        textures off, at once; off again puts them back."""
        from soundboard.ui.bun.bunnywidget import BunnyWidget
        mw = self.mw
        if on == lite.on():
            return
        mw.set_option("lite_mode", on)
        lite.set_on(on)
        mw.apply_light_voice()   # (Use less CPU follows it, unless picked by hand)
        mw.devctl.set_lite_block(on)
        BunnyWidget.lite_changed()
        mw.logo.lite_changed()
        mw.netctl._net_follow()   # (the On Air card's Lite mode line)
        setctl = mw.setctl
        for dlg in (setctl._settings_dlg, setctl._settings_kept):   # (switched from a toast)
            box = getattr(dlg, "lite_check", None)
            if box is not None and box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
        textured = mw.cfg.theme_texture and not on
        if textured != theme.textures_on:
            theme.textures_on = textured
            self.apply_theme(mw.cfg.theme)

    def suggest_lite(self):
        """A slower PC (lite.slow_pc): lite mode suggested once, in a toast with a
        button. Never switched on without that click."""
        mw = self.mw
        c = mw.cfg
        if c.lite_mode or c.lite_hint_done or not c.setup_done or not lite.slow_pc():
            return
        c.lite_hint_done = True
        usage.used("lite-suggested")
        mw._save_later()
        mw.toast(_("Onion Board can run lighter on this PC: Lite mode turns off the "
                   "animations. It's in Settings > Appearance too."), ms=12_000,
                 action=(_("Turn on"), lambda: (usage.used("lite-suggested-on"),
                                                self.set_lite_mode(True))))

    def set_live_tab_tint(self, on: bool):
        mw = self.mw
        mw.set_option("live_tab_green", on)
        set_live_tint(mw.tabs, on)

    def _paint_logo(self):
        mw = self.mw
        mw.logo.update()   # it reads the theme colours itself
        # title bar + taskbar follow the theme too, and so do the taskbar's right-click
        # menu, a pin and the app's own Desktop / Start menu shortcuts (shellicon)
        # (they stay still while sound plays: only the header logo glows. Swapping
        # them made Windows redraw the taskbar button, which flickered its layers)
        icon = glow_icon(theme.T["accent"], theme.T["accent2"], 0.0)
        QApplication.setWindowIcon(icon)   # every window, dialogs too
        mw.setWindowIcon(icon)
        tray = getattr(mw, "tray", None)
        if tray is not None:
            tray.setIcon(icon)
        shellicon.follow_theme(mw, theme.T["accent"], theme.T["accent2"])
        shellicon.paint_background(mw, theme.T["bg"])   # fast resizes: no white edge
