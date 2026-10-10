"""Fixes from an audit of the main window and its helpers: the fitter across a Radio
switch, start with Windows vs Task Manager, the status line's text, hotkeys and
categories, the effects preview, the crash dialog's state, loose empty files, the
link bar's queue and the Discord check's clean-up. Offscreen, fake devices."""
import numpy as np
import pytest
import shiboken6
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from soundboard import appaudio, applog, autostart, library, net
from soundboard.ui import chatguide, crashdialog, responsive
from soundboard.ui import mainwindow as main
from test_trim_updates_autostart import FakeReg

import test_mainwindow

window = test_mainwindow.window   # the real MainWindow fixture


# --------------------------------------------------------------------------- fitter

def _fit_root():
    root = QWidget()
    v = QVBoxLayout(root)
    a, b, c = QWidget(), QWidget(), QWidget()
    a.setMinimumSize(300, 20)    # a width step
    b.setMinimumSize(500, 100)   # a height step that's wide too (like the mixer)
    c.setMinimumSize(200, 20)
    for w in (a, b, c):
        v.addWidget(w)
    return root, a, b


def test_a_height_step_hidden_for_width_comes_back_when_wider(qapp):
    root, a, b = _fit_root()
    f = responsive.Fitter(root)
    f.add(10, "w", responsive.hide(a))
    f.add(20, "h", responsive.hide(b))
    root.show()
    f.fit(QSize(400, 400))
    assert b.isHidden() and f.compact_count() == 2
    f.fit(QSize(1000, 400))   # the same height, wide again: both fit
    assert not b.isHidden() and not a.isHidden() and f.compact_count() == 0
    root.close()


def test_fitter_steps_can_be_removed(qapp):
    root, a, b = _fit_root()
    f = responsive.Fitter(root)
    old = [(10, "w", responsive.hide(a))]
    f.extend(old)
    root.show()
    f.fit(QSize(400, 400))
    assert a.isHidden()
    new = [(20, "h", responsive.hide(b))]
    f.remove(old)   # undone first: the old step's widget shows again
    f.extend(new)
    assert not a.isHidden() and [s[2] for s in f.steps] == [new[0][2]]
    root.close()


def test_radio_switched_off_and_on_swaps_its_fit_steps(window, qapp):
    first = window._radio_steps
    net.configure_features(off=["radio"])
    window._radio_follow_switch()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)   # the old Radio tab is gone
    net.configure_features()
    window._radio_follow_switch()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    ids = {id(s[2]) for s in window._fit.steps}
    assert window._radio_steps and all(id(s[2]) in ids for s in window._radio_steps)
    assert not any(id(s[2]) in ids for s in first)
    window._fit.fit(QSize(300, 200))   # no step of a deleted tab: no RuntimeError
    window._fit.fit(QSize(1600, 1000))


# --------------------------------------------------------------------------- autostart

def test_refresh_keeps_task_managers_off(monkeypatch):
    reg = FakeReg()
    monkeypatch.setattr(autostart, "winreg", reg)
    assert autostart.set_enabled(True, hidden=True)
    reg.approved["OnionBoard"] = b"\x03" + bytes(11)   # Task Manager: off
    autostart.refresh(hidden=False)                     # the command changes
    assert not reg.values["OnionBoard"].endswith("--tray")
    assert "OnionBoard" in reg.approved and not autostart.is_enabled()


# --------------------------------------------------------------------------- status line

def test_status_line_is_always_rich_text(window):
    assert window.status.textFormat() == Qt.RichText
    window.status.setText("It&#x27;s here")
    assert window.status.textFormat() == Qt.RichText


# --------------------------------------------------------------------------- hotkeys

def test_category_changes_reregister_scoped_hotkeys(window, monkeypatch):
    window.cfg.scoped_hotkeys = True
    window.new_category(name="Memes")
    calls = []
    monkeypatch.setattr(window, "register_hotkeys", lambda: calls.append(1))
    window.toggle_tag("s0", "Memes")
    assert calls and "Memes" in window.meta("s0").tags
    calls.clear()
    window.new_category("s1", name="Music")
    assert calls and "Music" in window.meta("s1").tags


def test_a_sound_hotkey_takes_the_push_to_talk_key(window):
    window.cfg.ptt_key = "f8"
    m = window.meta("s0")
    m.hotkey = "f8"
    lost = window._clear_dupe_hotkey(m)
    assert window.cfg.ptt_key == "" and lost


# --------------------------------------------------------------------------- preview

def test_plain_preview_drops_a_render_in_flight(window, monkeypatch):
    played = []
    monkeypatch.setattr(window.engine, "play", lambda sid, *a, **k: played.append(sid))
    window.audio["s0"] = np.zeros((100, 2), np.float32)
    window._preview_gen = 5
    window._preview_done = lambda ok: played.append(("done", ok))
    window.status.setText("Rendering the preview…")
    assert window.preview("s0") == "playing"
    assert window._preview_gen == 6 and window._preview_done is None
    assert window.status.text() != "Rendering the preview…"
    window._on_fx_preview("s0", np.zeros((10, 2), np.float32), 1.0, 5)   # the old render
    assert played == ["s0:preview"]


def test_closing_the_edit_dialog_mid_render_clears_the_status(window, monkeypatch):
    class Closed(main.EditDialog):
        def exec(self):
            window._preview_done = lambda ok: None   # a render was going
            window.status.setText("Rendering the preview…")
            return 0
    monkeypatch.setattr(main, "EditDialog", Closed)
    window.edit("s0")
    assert window.status.text() != "Rendering the preview…"
    assert window._preview_done is None


@pytest.mark.parametrize("ok", [0, 1])
def test_closing_the_edit_dialog_stops_the_preview(window, monkeypatch, ok):
    window.audio["s0"] = np.zeros((48000, 2), np.float32)

    class Previewed(main.EditDialog):
        def exec(self):
            assert window.preview("s0") == "playing"   # same effects: the plain preview
            return ok
    monkeypatch.setattr(main, "EditDialog", Previewed)
    stopped = []
    real = window.engine.stop
    monkeypatch.setattr(window.engine, "stop", lambda sid: (stopped.append(sid), real(sid)))
    window.edit("s0")
    assert "s0:preview" in stopped and "s0~fx:preview" in stopped


# --------------------------------------------------------------------------- crash dialog

def test_crash_dialog_state_clears_when_its_parent_goes(qapp, tmp_path, monkeypatch):
    log_path = tmp_path / applog.LOG_NAME
    log_path.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(applog, "_state", {"log_path": log_path, "version": "t",
                                           "dialogs": 0, "seen": set(), "open": None,
                                           "bridge": None, "pending": None})
    parent = QWidget()

    class Fake(QDialog):
        def __init__(self, rep, _path, parent=None):
            super().__init__(parent)

        def show(self):
            pass

        def raise_(self):
            pass
    monkeypatch.setattr(crashdialog, "CrashDialog", Fake)
    monkeypatch.setattr(applog, "_app_in_front", lambda: True)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.activeWindow",
                        staticmethod(lambda: parent))
    rep = applog.Report(title="boom", text="x", fatal=False)
    applog._show_dialog(rep)
    assert applog._state["open"] is rep
    shiboken6.delete(parent)   # takes the dialog with it, never finished
    assert applog._state["open"] is None


# --------------------------------------------------------------------------- loose files

def test_an_empty_loose_file_stops_the_timer(window):
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    (library.SOUNDS_DIR / "empty.wav").write_bytes(b"")
    for _ in range(main.LOOSE_EMPTY_LOOKS + 2):
        window._loose_timer.stop()
        window._take_loose()
    assert not window._loose_timer.isActive()
    (library.SOUNDS_DIR / "empty.wav").write_bytes(b"RIFF")   # written to: looked at again
    window._take_loose()
    assert window._loose_timer.isActive()
    window._loose_timer.stop()


# --------------------------------------------------------------------------- link bar

def test_link_bar_new_text_ends_a_queued_pick(qapp):
    from soundboard.library import Config
    from soundboard.ui.linkbar import LinkBar
    bar = LinkBar(engine=None, cfg=Config(), color_for=lambda: "#fff", known_for=dict)
    bar.open("https://www.youtube.com/watch?v=abc", "Clip")
    bar._queued = "add"
    got = []
    bar.done.connect(lambda *a: got.append(a))
    bar.set_text("something else")
    assert got == [("https://www.youtube.com/watch?v=abc", "add", False)]


# --------------------------------------------------------------------------- discord check

def test_discord_check_cleans_up_when_play_fails(qapp, monkeypatch):
    from tests.conftest import process_events
    stopped = []

    class Cap:
        ready = True

        def __init__(self, *a, **k):
            self.error = None

        def start(self, timeout=6.0, wait=True):
            return True

        def stop(self, wait=True):
            stopped.append(1)

    class Eng:
        main_stream = object()
        main_tap = None

        def play(self, *a, **k):
            raise RuntimeError("no device")

        def stop(self, sid):
            pass
    monkeypatch.setattr(appaudio, "supported", lambda: (True, ""))
    monkeypatch.setattr(appaudio, "AppCapture", Cap)
    monkeypatch.setattr(chatguide, "find_discord",
                        lambda: appaudio.App(pid=4242, exe="Discord.exe"))
    e = Eng()
    c = chatguide.ChatCheck(e)
    got = []
    c.done.connect(got.append)
    c.start()
    assert process_events(qapp, lambda: got, timeout=5)
    assert "couldn't start" in got[0]["error"] and "no device" in got[0]["error"]
    assert not c.running and e.main_tap is None and stopped
