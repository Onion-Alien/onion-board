"""The main window's look: applying a theme to the whole window (and what it built ahead of
time), the Live colour, the background texture, the live tab's tint, and painting the
onion logo.

MainWindow makes one ``ThemeControl`` (``MainWindow.themectl``); everything here runs on
the UI thread."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

from soundboard import shellicon, theme
from soundboard.ui import icons, themecover
from soundboard.ui.controller import Controller
from soundboard.ui.livedot import set_tint as set_live_tint
from soundboard.ui.logowidget import glow_icon

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow


class ThemeControl(Controller):
    """The theme and look of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def apply_theme(self, name: str):
        # a still of the window with Bun over it while every widget restyles: no frame
        # of a half-styled window, and it fades to the new theme (ui/themecover.py)
        mw = self.mw
        with themecover.covered(mw, name):
            self._apply_theme(name)

    def _apply_theme(self, name: str):
        mw = self.mw
        mw.cfg.theme = theme.apply(QApplication.instance(), name)
        self.keep_limited()
        mw.setctl._drop_spare_dialogs()
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
        if on == theme.textures_on:
            return
        mw.set_option("theme_texture", on)
        theme.textures_on = on
        self.apply_theme(mw.cfg.theme)

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
