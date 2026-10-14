"""MainWindow is split by feature: each group of its work is a controller in its own
module that the window owns, not more methods on one 10,000-line class. A method moved
out must not come back, and the window must still make each controller: a QObject it
owns, so timers and signals aimed at the controller stop with the window."""
import pytest

from soundboard.ui import (alertcontrol, buncontrol, categorycontrol, editcontrol,
                           ffmpegcontrol, importcontrol, mainwindow, padcontrol, remoteaccess,
                           removecontrol, updatecontrol)
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
]


@pytest.mark.parametrize("attr,cls,gone", SPLIT, ids=[s[0] for s in SPLIT])
def test_each_feature_is_its_own_controller(window, attr, cls, gone):  # noqa: F811
    ctl = getattr(window, attr)
    assert isinstance(ctl, cls) and ctl.mw is window and ctl.parent() is window
    for name in gone:
        assert not hasattr(mainwindow.MainWindow, name), name


def test_a_link_with_no_pad_finds_none(window):  # noqa: F811
    """_pad_for_link uses sourceinfo, whose import an earlier split dropped while the
    method was being added: every web song looked up crashed."""
    assert window._pad_for_link("https://www.youtube.com/watch?v=nothing") is None
