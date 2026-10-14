"""MainWindow is split by feature: each group of its work is a controller in its own
module that the window owns, not more methods on one 10,000-line class. A method moved
out must not come back, and the window must still make each controller."""
import pytest

from soundboard.ui import ffmpegcontrol, importcontrol, mainwindow, updatecontrol
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
]


@pytest.mark.parametrize("attr,cls,gone", SPLIT, ids=[s[0] for s in SPLIT])
def test_each_feature_is_its_own_controller(window, attr, cls, gone):  # noqa: F811
    ctl = getattr(window, attr)
    assert isinstance(ctl, cls) and ctl.mw is window
    for name in gone:
        assert not hasattr(mainwindow.MainWindow, name), name
