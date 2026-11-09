"""The first opens got ready right after the loading screen (SettingsControl.warm_first_opens):
Edit voice, Radio, Voice, the Store, Edit sound, Live controls and the small ones laid out
and drawn while hidden. Nothing shows, nothing a first show starts runs (Radio's stations,
the Store's list), nothing is counted, and each still opens as before."""
import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import __version__
from soundboard.audio import engine
from soundboard.control import winkeys
from soundboard.core import usage
from soundboard.sounds.library import SR, Config, SoundMeta
from soundboard.ui.radio.radiopanel import RadioTab
from soundboard.ui.store.storetab import StoreTab
from soundboard.ui.window import fitcontrol, settingscontrol
from soundboard.ui.window import mainwindow as main


@pytest.fixture
def win(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(fitcontrol, "SETTLE_MS", 10 ** 7)
    sounds = []
    for i, name in enumerate(("Boom", "Airhorn")):
        p = app_dir / f"{name}.wav"
        t = np.arange(SR // 10) / SR
        sf.write(p, np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.3, SR)
        sounds.append(SoundMeta(id=f"s{i}", name=name, file=str(p)))
    # every tab on (the Store is off for a new user), the guide done
    Config(sounds=sounds, mic_first=True, stats_version=__version__, tabs_off=[],
           setup_done=True).save()
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    w.load_triggers()
    yield w
    from PySide6.QtCore import QTimer
    from soundboard.ui.kit import modalframe
    guard = modalframe._opened
    modalframe._opened = lambda dlg: QTimer.singleShot(0, dlg, dlg.reject)
    try:
        w.close()
    finally:
        modalframe._opened = guard


class _Shows(QObject):
    """Every widget that got a Show event."""

    def __init__(self):
        super().__init__()
        self.shown: list[QWidget] = []

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Show and isinstance(obj, QWidget):
            self.shown.append(obj)
        return False


def _spy(monkeypatch):
    """The widgets laid out ahead, from here on."""
    done, polish = [], settingscontrol._polish
    monkeypatch.setattr(settingscontrol, "_polish",
                        lambda wid, size=None: (done.append(wid), polish(wid, size)))
    return done


def _targets(w):
    fx = w.voice.fx
    return {"Edit voice": fx.dlg, "Radio": w.radio_page, "Voice": w.voice, "Store": w.store,
            "Edit sound": w.setctl._spare_editor, "Live controls": w.speed_btn.pop,
            "Radio's Live controls": w.radio.fx_btn.pop,
            "Apps' Live controls": w.apps.fx_btn.pop, "About": w.about_menu}


def test_first_opens_got_ready_hidden(win, qapp, monkeypatch):
    """As app.main does it: a step at a time while the sounds load, the rest once the
    window is up, all behind the loading screen."""
    starts, loads, counted = [], [], []
    monkeypatch.setattr(RadioTab, "start", lambda self, *a, **k: starts.append(self))
    monkeypatch.setattr(StoreTab, "reload", lambda self, *a, **k: loads.append(self))
    shows = _Shows()
    qapp.installEventFilter(shows)
    try:
        done = _spy(monkeypatch)
        early = 0
        while win.setctl.warm_first_opens(early=True):   # (the window isn't up yet)
            early += 1
        assert early >= 6 and not win.isVisible()
        assert win.voice.fx.dlg in done and win.speed_btn.pop in done
        assert win.radio_page not in done   # (the tabs' size isn't known yet)
        win.setctl.preload_dialogs()
        win.resize(1280, 760)
        win.show()
        qapp.processEvents()
        monkeypatch.setattr(usage, "used", lambda key: counted.append(key))
        monkeypatch.setattr(usage, "note", lambda one: counted.append(one))
        tab, size = win.tabs.currentWidget(), win.size()
        shows.shown.clear()
        assert win.setctl.warm_first_opens()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(shows)
    assert not win.setctl._warms and not win.setctl.warm_first_opens()   # all done, once
    assert isinstance(win.radio, RadioTab) and isinstance(win.store, StoreTab)
    targets = _targets(win)
    for name, t in targets.items():   # done: styled, laid out, still hidden
        assert t is not None and t in done and not t.isVisible(), name
    seen = set(shows.shown)
    # (a scroll bar inside one may get a Show of its own while it stays hidden)
    assert not seen & {*targets.values(), win.radio, *win.voice.findChildren(QWidget)}
    assert not [s for s in seen if s.isWindow() and s is not win]   # no window came up
    assert win.voice.fx.dlg.parentWidget() is win   # where it opens (open_tweak)
    assert not starts and not loads and not counted
    assert not win.engine.playing()
    assert win.tabs.currentWidget() is tab and win.size() == size
    assert not win.setctl.settings_open()
    # and each still opens as before
    fx = win.voice.fx
    fx.open_tweak()
    qapp.processEvents()
    assert fx.dlg.isVisible()
    fx.dlg.reject()
    win.tabs.setCurrentWidget(win.radio_page)
    qapp.processEvents()
    assert starts   # the first show loads the stations, as before
    d = win.editctl.edit(win.cfg.sounds[0].id)
    assert d is targets["Edit sound"] and d.isVisible()
    d.reject()
    qapp.processEvents()


def test_the_rest_waits_for_the_window(win, qapp, monkeypatch):
    """Started with Windows into the tray, nothing calls it; and without the window
    up, the steps that need it are left for later."""
    done = _spy(monkeypatch)
    assert not win.setctl.warm_first_opens()
    assert not done


def test_a_warm_that_fails_leaves_the_others(win, qapp, monkeypatch):
    def broken():
        raise RuntimeError("boom")
    monkeypatch.setattr(win.setctl, "_edit_voice_steps", lambda: [(True, broken)])
    win.show()
    qapp.processEvents()
    done = _spy(monkeypatch)
    assert win.setctl.warm_first_opens()
    assert win.radio_page in done and win.voice.fx.dlg not in done
    assert QApplication.activePopupWidget() is None
