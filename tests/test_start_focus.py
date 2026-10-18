"""The window's first focus: the open tab's page, never a rail button with its ring. Left
to Qt, a window shown with nothing focused focuses its first focusable widget as if Tab
were pressed: the Sounds button got the ring while another tab was open, so it looked
like a second selected tab."""
from PySide6.QtCore import QEvent

from soundboard import __version__
from soundboard.audio import engine
from soundboard.control import winkeys
from soundboard.sounds.library import Config
from soundboard.ui import mainwindow as main
from soundboard.ui.tabcontrol import TAB_INDEX


def test_start_focus_is_the_open_tab_without_the_ring(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    voice = TAB_INDEX["voice"]
    Config(mic_first=True, stats_version=__version__, tab=voice, tabs_off=[],
           setup_done=True).save()
    w = main.MainWindow()
    try:
        w.soundctl._load_thread.join(15)
        w.show()
        w.activateWindow()
        for _ in range(20):
            qapp.processEvents()
        cur = w.tabs.currentIndex()
        assert cur != 0   # another tab than Sounds is open
        ringed = [b.index for b in w.rail.buttons if b._kbd_focus]
        assert ringed == []
        assert [b.index for b in w.rail.buttons if b.hasFocus()] == []
    finally:
        w.close()
        w.soundctl._load_thread.join(15)
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)
