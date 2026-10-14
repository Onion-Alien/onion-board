"""MainWindow is split by feature: each group of its work is a controller in its own
module that the window owns, not more methods on one 10,000-line class. A method moved
out must not come back, and the window must still make each controller."""
import pytest

from soundboard.ui import (aboutcontrol, alertcontrol, buncontrol, categorycontrol,
                           devicecontrol, editcontrol, ffmpegcontrol, importcontrol, mainwindow,
                           miccontrol, padcontrol, remoteaccess, removecontrol, routecontrol,
                           settingscontrol, statuscontrol, tabcontrol, themecontrol,
                           updatecontrol)
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

# (window attribute, controller class, methods that live there now)
SPLIT = [
    ("ffctl", ffmpegcontrol.FfmpegControl,
     ["_on_ffmpeg", "_ffmpeg_news", "_show_ffmpeg_bar", "fix_ffmpeg", "_may_get_ffmpeg"]),
    ("updctl", updatecontrol.UpdateControl,
     ["check_updates", "_on_update", "show_update", "download_update", "_on_update_ready",
      "install_update", "after_update", "whats_new"]),
    ("impctl", importcontrol.ImportControl,
     ["import_files", "on_imported", "_take_loose", "export_board", "import_package",
      "import_other", "tidy_pack", "remove_pack", "_on_worker"]),
    ("catctl", categorycontrol.CategoryControl,
     ["_build_categories", "_fill_categories", "set_category", "new_category", "toggle_tag",
      "rename_category", "delete_category", "new_subcategory", "_cat_tick",
      "add_category_program"]),
    ("alertctl", alertcontrol.AlertControl,
     ["_urgent_now", "_show_urgent", "_hide_urgent", "_urgent_clicked", "discord_problems",
      "_discord_tick", "_on_discord", "_raw_tick", "_on_mic_users"]),
    ("bunctl", buncontrol.BunControl,
     ["bun_up", "enter_bun_mode", "leave_bun_mode", "_bun_away", "start_as_bun", "toast_seen"]),
    ("remctl", remoteaccess.RemoteAccess,
     ["apply_remote", "_load_remote_addons", "load_remote_addon", "remove_remote_addon",
      "_stop_remote_addons"]),
    ("padctl", padcontrol.PadControl,
     ["pad_menu", "_volume_action", "nudge_volume", "set_picture", "paste_picture",
      "set_pad_sort", "set_pad_view", "set_list_rows", "_fill_view_menu"]),
    ("rmctl", removecontrol.RemoveControl,
     ["ask_remove", "remove_sound", "remove_sounds", "undo_remove", "_put_back",
      "_finish_removals", "show_deleted", "_restore_deleted"]),
    ("editctl", editcontrol.EditControl,
     ["edit", "_edit_done", "_new_editor", "_close_editors", "duplicate_sound",
      "show_sound_file", "_rerender"]),
    ("devctl", devicecontrol.DeviceControl,
     ["refresh_devices", "_device_job", "rescan_with_feedback", "set_latency", "_open_devices",
      "_recover_devices", "_default_tick", "_follow_default_output"]),
    ("routectl", routecontrol.RouteControl,
     ["on_device", "set_route", "_show_route", "_main_name", "_send_plan", "sending_to",
      "set_also_send_at", "set_obs_device", "set_send_kind", "on_mic_toggle"]),
    ("micctl", miccontrol.MicControl,
     ["_offer_mic_update", "_accept_mic_update", "_show_mic_status", "_auto_fix", "attach_mic",
      "_mic_attached", "_check_helper", "use_cable_instead", "_follow_mic_effect",
      "fix_cable_format", "install_cable", "remove_cable", "open_windows_mic"]),
    ("statusctl", statuscontrol.StatusControl,
     ["_update_status", "_say_audio", "_update_flow", "_place_ways", "_set_primary",
      "show_chat_guide"]),
    ("tabctl", tabcontrol.TabControl,
     ["tab_on", "needs_online", "tab_shown", "set_tab_on", "hide_tab", "tab_menu", "_swap_tab",
      "_fill_more_tabs", "_add_from_more", "_go_tab", "_count_tab"]),
    ("setctl", settingscontrol.SettingsControl,
     ["open_settings", "settings_open", "close_settings", "_settings_closed", "_settings_print",
      "_check_route_pick", "preload_dialogs", "warm_settings", "warm_triggers"]),
    ("themectl", themecontrol.ThemeControl,
     ["apply_theme", "_apply_theme", "set_live_color", "set_theme_texture", "set_live_tab_tint",
      "_paint_logo"]),
    ("aboutctl", aboutcontrol.AboutControl,
     ["_show_about_menu", "_fill_about_menu", "ask_feedback", "_open_page"]),
]


@pytest.mark.parametrize("attr,cls,gone", SPLIT, ids=[s[0] for s in SPLIT])
def test_each_feature_is_its_own_controller(window, attr, cls, gone):  # noqa: F811
    ctl = getattr(window, attr)
    assert isinstance(ctl, cls) and ctl.mw is window
    for name in gone:
        assert not hasattr(mainwindow.MainWindow, name), name
