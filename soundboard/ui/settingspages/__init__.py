"""The pages of the Settings window (soundboard.settings.SettingsDialog), one module each.

Each page is a QObject the dialog owns (``SettingsDialog.<page>``), not a plain object: a
timer or signal aimed at one of its methods then stops with the dialog (Qt drops a
connection when its receiver goes), as it did when the method was the dialog's own. The
widgets a page builds stay on the dialog (``self.dlg.x``), where the window and tests
read them. The dialog's card helpers are a page's own too, so a page reads like the
dialog it came from."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject

if TYPE_CHECKING:
    from PySide6.QtWidgets import QCheckBox, QWidget

    from soundboard.settings import SettingsDialog
    from soundboard.ui.mainwindow import MainWindow


class Built:
    """What the pages build and keep on the dialog (``self.dlg.x``), for the dialog,
    the window and the tests to read: declared for the type checker. SettingsDialog
    inherits it; it has nothing at run time."""

    about_version: Any
    addon_label: Any
    addon_remove: Any
    _addon_titles: Any
    _addons_card_w: Any
    app_log_box: Any
    app_setup_list: Any
    box_app_setup: Any
    box_programs: Any
    box_tips: Any
    btn_ffmpeg: Any
    copy_local_sounds: Any
    count_dialog: Any
    count_eye: Any
    data_folder: Any
    data_low: Any
    _data_video_rows: Any
    _data_widgets: Any
    dev_combos: Any
    discord_btn: Any
    feedback_box: Any
    feedback_btn: Any
    ff_box: Any
    ff_note: Any
    ff_state: Any
    get_pocket: Any
    _has_ff: Any
    hue_now: Any
    hue_reset: Any
    hue_settle: Any
    hue_slider: Any
    hue_swatch: Any
    lang_button: Any
    lang_dialog: Any
    lang_note: Any
    lang_restart: Any
    live_dot: Any
    live_green: Any
    look_box: Any
    look_pages: Any
    look_shown: Any
    look_tabs: Any
    _look_pick: Any
    net_activity: Any
    net_addr: Any
    _net_body: Any
    net_boxes: dict[str, QCheckBox]
    net_bridge: Any
    net_direct: Any
    net_get: Any
    net_get_note: Any
    net_hide: Any
    net_newnym: Any
    net_note: Any
    _net_subs: dict[str, QWidget]
    net_test: Any
    net_tor: Any
    net_tor_state: Any
    net_via: Any
    netlog_keep_box: Any
    offline_box: Any
    _offline_cards: Any
    ov_monitor: Any
    ov_position: Any
    ov_toggle_only: Any
    playing_background_check: Any
    playing_background_opacity: Any
    plays_box: Any
    pocket_buttons: Any
    _pocket_refresh: Any
    pocket_remove: Any
    pocket_remove_addons: Any
    _pocket_slot: Any
    pocket_update: Any
    problem_btn: Any
    programs_list: Any
    remote_on: Any
    _save_video_hint: Any
    _sync_highlight: Any
    texture_off: Any
    texture_on: Any
    theme_cards: Any
    ui_scale_combo: Any
    ui_scale_note: Any
    ui_scale_restart: Any
    _upd_asked: Any
    upd_btn: Any
    upd_chk: Any
    upd_label: Any
    voices_card: Any
    voices_show: Any
    watch_buttons: Any
    _watch_refresh: Any
    ytdlp_auto_box: Any
    ytdlp_btns: Any
    ytdlp_label: Any


class Page(QObject):
    """One page of a SettingsDialog (``dlg``), owned by it."""

    def __init__(self, dlg: SettingsDialog):
        super().__init__(dlg)
        self.dlg = dlg

    @property
    def mw(self) -> MainWindow:
        return self.dlg.mw

    def _card(self, *args, **kwargs):
        return self.dlg._card(*args, **kwargs)

    def _page(self, *args, **kwargs):
        return self.dlg._page(*args, **kwargs)

    def _option(self, *args, **kwargs):
        return self.dlg._option(*args, **kwargs)

    def _link_button(self, *args, **kwargs):
        return self.dlg._link_button(*args, **kwargs)

    def _note_card(self, *args, **kwargs):
        return self.dlg._note_card(*args, **kwargs)


def _button_row():
    """Buttons side by side at their own width, wrapping onto a second line only when
    Settings is too narrow (stacked full-width buttons looked like a form)."""
    from soundboard.ui.panel import Flow   # panel imports this module
    return Flow(gap=8)
