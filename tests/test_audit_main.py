"""Fixes from an audit of the main window and its helpers: the fitter across a Radio
switch, start with Windows vs Task Manager, the status line's text, hotkeys and
categories, the effects preview, the crash dialog's state, loose empty files, the
link bar's queue and the Discord check's clean-up. Offscreen, fake devices."""
import numpy as np
import pytest
import shiboken6
from PySide6.QtCore import QEvent, QSize
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from conftest import said
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


# --------------------------------------------------------------------------- notices

def test_an_old_status_text_loses_its_colour_wrapper(window):
    t = window.say("<span style='color:#f00'>It&#x27;s here</span>", "warn")
    assert t.text() == "It&#x27;s here" and t.kind == "warn"


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
    window.toast("Rendering the preview…", "busy", key="preview")
    assert window.preview("s0") == "playing"
    assert window._preview_gen == 6 and window._preview_done is None
    assert "Rendering the preview" not in said(window)
    window._on_fx_preview("s0", np.zeros((10, 2), np.float32), 1.0, 5)   # the old render
    assert played == ["s0:preview"]


def test_a_long_sounds_effects_preview_renders_only_what_plays_first(window, qapp,
                                                                    monkeypatch):
    """A 2-hour song's pitch shift took minutes before its preview played."""
    from tests.conftest import process_events
    monkeypatch.setattr(main, "PREVIEW_WHOLE_S", 2)
    monkeypatch.setattr(main, "PREVIEW_S", 1)
    long_ = np.zeros((5 * main.SR, 2), np.int16)
    window.audio["s0"] = long_
    monkeypatch.setattr(main, "load_original", lambda m: long_)
    monkeypatch.setattr(library, "render_cached", lambda *a, **k: pytest.fail("whole render"))
    played = []
    monkeypatch.setattr(window.engine, "play", lambda sid, data, *a, **k: played.append(
        (sid, len(data))))
    assert window.preview("s0", fx={"pitch": 5}) == "rendering"
    assert process_events(qapp, lambda: played, timeout=10)
    assert played == [("s0~fx:preview", main.SR)]


def test_a_newer_preview_stops_the_render_still_going(window, monkeypatch):
    seen = []

    def render(sid, data, fx, cancel=None):
        seen.append(cancel())
        window._preview_gen += 1          # a newer preview starts meanwhile
        seen.append(cancel())
        raise library.Cancelled
    monkeypatch.setattr(library, "render_cached", render)
    monkeypatch.setattr(main, "load_original", lambda m: np.zeros((10, 2), np.int16))
    window.audio["s0"] = np.zeros((10, 2), np.int16)
    threads = []
    monkeypatch.setattr(main.threading, "Thread",
                        lambda target, **k: threads.append(target) or type(
                            "T", (), {"start": lambda self: None})())
    window.preview("s0", fx={"pitch": 5})
    threads[-1]()                         # runs the render here: no error, nothing played
    assert seen == [False, True]


def test_closing_the_edit_dialog_mid_render_clears_the_status(window, qapp):
    d = window.edit("s0")
    window._preview_done = lambda ok: None   # a render was going
    window.toast("Rendering the preview…", "busy", key="preview")
    d.done(0)
    qapp.processEvents()
    assert "Rendering the preview" not in said(window)
    assert window._preview_done is None


@pytest.mark.parametrize("ok", [0, 1])
def test_closing_the_edit_dialog_stops_the_preview(window, monkeypatch, qapp, ok):
    window.audio["s0"] = np.zeros((48000, 2), np.float32)
    d = window.edit("s0")
    assert window.preview("s0") == "playing"   # same effects: the plain preview
    stopped = []
    real = window.engine.stop
    monkeypatch.setattr(window.engine, "stop", lambda sid: (stopped.append(sid), real(sid)))
    d.done(ok)
    qapp.processEvents()
    assert "s0:preview" in stopped and "s0~fx:preview" in stopped


def test_edit_sound_sits_beside_the_board_one_per_sound(window, qapp):
    """Edit sound doesn't hold up the board any more (U4), but it's still a draft:
    Save puts it on, Cancel drops it. Editing the same sound raises its window."""
    m = window.meta("s0")
    d = window.edit("s0")
    assert d.isVisible() and not d.isModal() and qapp.activeModalWidget() is None
    assert window.edit("s0") is d                        # the same sound: the same window
    other = window.edit("s1")
    assert other is not d
    d.name.setText("Renamed")
    d.done(QDialog.Rejected)                              # Cancel: nothing changes
    qapp.processEvents()
    assert m.name == "Boom" and "s0" not in window._editors
    d = window.edit("s0")                                 # a new draft after closing
    d.name.setText("Renamed")
    d.done(QDialog.Accepted)                              # Save
    qapp.processEvents()
    assert m.name == "Renamed"
    other.done(QDialog.Rejected)
    qapp.processEvents()
    assert window._editors == {}
    assert window.findChildren(main.EditDialog) == []     # each one freed


def test_removing_a_sound_closes_its_edit_window_unsaved(window, qapp):
    d = window.edit("s0")
    d.name.setText("Never saved")
    window.remove_sound("s0")
    qapp.processEvents()
    assert "s0" not in window._editors
    window.undo_remove()                                  # back as it was
    assert window.meta("s0").name == "Boom"


def test_saving_after_undo_puts_the_draft_on_the_sound_now_there(window, qapp):
    """The sound's SoundMeta can be swapped for a new object while its window is open
    (a reload): Save goes on the one in the list now, not the stale one."""
    d = window.edit("s0")
    old = window.meta("s0")
    import copy
    fresh = copy.copy(old)
    window.cfg.sounds[window.cfg.sounds.index(old)] = fresh
    window._index()
    d.name.setText("On the new one")
    d.done(QDialog.Accepted)
    qapp.processEvents()
    assert window.meta("s0") is fresh and fresh.name == "On the new one"


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
