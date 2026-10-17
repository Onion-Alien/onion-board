"""The update card in the real MainWindow (offscreen): found → Update now → downloaded
→ Restart to update → installer started and the app quits; and the note on the next
start. No network and no installer run: updates.download / start_install are faked."""
import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import process_events
from soundboard.ui import toast
from soundboard import __version__, updates
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


@pytest.fixture
def boxes(monkeypatch):
    """Answer every QMessageBox(...).exec() with the button named in `boxes.answers`
    (title -> button text); `boxes.shown` lists (title, [button texts])."""
    class Boxes:
        answers: dict[str, str] = {}
        shown: list[tuple[str, list[str]]] = []
    b = Boxes()
    b.answers, b.shown = {}, []

    def exec_(box):
        texts = [x.text() for x in box.buttons()]
        b.shown.append((box.windowTitle(), texts))
        want = b.answers.get(box.windowTitle())
        box.setProperty("picked", texts.index(want) if want in texts else -1)
        return 0

    def clicked(box):
        i = box.property("picked")
        return box.buttons()[i] if i is not None and i >= 0 else None
    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "clickedButton", clicked)
    return b


def _rel():
    return updates.Release("99.0.0", "https://github.com/x", "Fixes.",
                           updates.DOWNLOADS + "v99.0.0/OnionBoardSetup.exe", "a" * 64, 10)


def test_update_now_downloads_then_restarts_into_the_installer(window, boxes, qapp,
                                                               monkeypatch, tmp_path):
    setup = tmp_path / "OnionBoardSetup-99.0.0.exe"
    setup.write_bytes(b"MZ")

    def download(rel, progress, cancelled):
        progress(5, 10)
        return setup
    started, quit_ = [], []
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", download)
    monkeypatch.setattr(updates, "start_install", started.append)
    monkeypatch.setattr(window, "quit_app", lambda: quit_.append(1))
    boxes.answers = {"Update available": "Update now", "Install the update": "Restart now"}

    window.updctl._on_update(_rel(), "", True)    # "Check now" found it: the dialog opens
    assert boxes.shown[0][0] == "Update available" and "Release page" in boxes.shown[0][1]
    assert process_events(qapp, lambda: quit_)
    assert started == [setup] and quit_ == [1]
    assert window.btn_update.accessibleName() == "Restart to update"
    assert window.cfg.update_pending == "99.0.0"


def _launch_check(window, qapp, monkeypatch, rel):
    """The check as the app starts (check_updates(launch=True)) finding `rel`."""
    from soundboard import watchaddon
    monkeypatch.setattr(updates, "check", lambda cfg, force=False, launch=False: rel)
    monkeypatch.setattr(watchaddon, "check_update", lambda: None)
    window.updctl.check_updates(launch=True)
    assert process_events(qapp, lambda: window.updctl.release is not None)


@pytest.fixture
def installer(window, monkeypatch, tmp_path):
    """A faked download and installer: `installer.started` lists the installers run,
    `installer.got` the downloads."""
    setup = tmp_path / "OnionBoardSetup-99.0.0.exe"
    setup.write_bytes(b"MZ")

    class Fake:
        started: list = []
        got: list = []
    f = Fake()
    f.started, f.got = [], []
    f.setup = setup
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", lambda rel, p, c: f.got.append(rel) or setup)
    monkeypatch.setattr(updates, "start_install", f.started.append)
    monkeypatch.setattr(window, "quit_app", lambda: None)
    window.show()
    return f


def test_found_as_the_app_starts_it_installs_itself(window, boxes, qapp, monkeypatch,
                                                   installer):
    _launch_check(window, qapp, monkeypatch, _rel())
    assert process_events(qapp, lambda: installer.started)
    assert boxes.shown == []                     # no question: it just restarts into it
    assert "downloading it now" in toast.shown(window)[-1].text()
    assert window.cfg.update_pending == "99.0.0" and window.cfg.update_auto_tried == "99.0.0"


def test_a_version_that_already_tried_waits_for_a_click(window, boxes, qapp, monkeypatch,
                                                       installer):
    window.cfg.update_auto_tried = "99.0.0"      # it didn't work last time: no loop
    _launch_check(window, qapp, monkeypatch, _rel())
    process_events(qapp, lambda: False, timeout=0.3)
    assert installer.got == [] and installer.started == []
    assert window.btn_update.accessibleName() == "Update to 99.0.0"


def test_unticked_or_found_later_it_only_offers(window, boxes, qapp, monkeypatch, installer):
    window.cfg.update_auto = False
    _launch_check(window, qapp, monkeypatch, _rel())
    window.cfg.update_auto = True
    window.updctl.release = None
    window.updctl._on_update(_rel(), "", False)  # the hourly check: the card only
    process_events(qapp, lambda: False, timeout=0.3)
    assert installer.got == [] and installer.started == []


def test_found_behind_the_loading_screen_it_installs_before_the_window(
        window, boxes, qapp, monkeypatch, installer):
    from soundboard.ui import splash
    said = []
    monkeypatch.setattr(splash, "set_status", lambda text="", progress=None:
                        said.append((text, progress)))
    monkeypatch.setattr(updates, "check", lambda cfg, force=False, launch=False: _rel())

    def download(rel, progress, cancelled):
        progress(5, 10)
        return installer.setup
    monkeypatch.setattr(updates, "download", download)
    assert window.updctl.update_at_start() is True
    assert installer.started == [installer.setup] and boxes.shown == []
    assert said[0] == ("Checking for updates…", None)
    assert ("Updating to 99.0.0… 50%", 0.5) in said
    assert said[-1] == ("Installing Onion Board 99.0.0…", 1.0)
    assert window.cfg.update_pending == "99.0.0" and window.cfg.update_auto_tried == "99.0.0"


def _closing_marks(monkeypatch):
    """exitwatch's "an installer closes the app" mark, as calls: "closing" / "staying"."""
    from soundboard import exitwatch
    marks = []
    monkeypatch.setattr(exitwatch, "closed_by_windows", lambda: marks.append("closing"))
    monkeypatch.setattr(exitwatch, "staying", lambda: marks.append("staying"), raising=False)
    return marks


def test_a_slow_installer_start_never_freezes_the_window(window, boxes, qapp, monkeypatch,
                                                        installer):
    """Windows checking the downloaded installer held start_install for good: the window
    froze until it was ended, and that was counted as a freeze and an unclean exit."""
    import threading
    import time
    marks = _closing_marks(monkeypatch)
    held, quit_ = threading.Event(), []
    seen = []

    def slow(path):
        seen.append(list(marks))   # what exitwatch was told before it started
        held.wait(3)
    monkeypatch.setattr(updates, "start_install", slow)
    monkeypatch.setattr(window, "quit_app", lambda: quit_.append(1))
    t0 = time.monotonic()
    window.updctl._start_install(_rel(), installer.setup)
    assert time.monotonic() - t0 < 1.0          # back at once: the window keeps going
    window.updctl._start_install(_rel(), installer.setup)   # a second click: nothing more
    assert process_events(qapp, lambda: seen)
    assert seen == [["closing"]] and quit_ == []
    held.set()
    assert process_events(qapp, lambda: quit_)
    assert quit_ == [1] and marks == ["closing"]


def test_an_installer_that_wont_start_says_so_and_stays(window, boxes, qapp, monkeypatch,
                                                       installer):
    marks = _closing_marks(monkeypatch)
    quit_ = []

    def fail(path):
        raise OSError("blocked")
    monkeypatch.setattr(updates, "start_install", fail)
    monkeypatch.setattr(window, "quit_app", lambda: quit_.append(1))
    window.updctl._start_install(_rel(), installer.setup)
    assert process_events(qapp, lambda: window.updctl._update_err)
    assert window.updctl._update_err and quit_ == []
    assert marks == ["closing", "staying"] and window.cfg.update_pending == ""
    window.updctl._start_install(_rel(), installer.setup)   # clicked again: it tries again
    assert process_events(qapp, lambda: window.updctl._update_fails == 2)


def test_behind_the_loading_screen_the_mark_comes_first(window, boxes, qapp, monkeypatch,
                                                         installer):
    marks = _closing_marks(monkeypatch)
    seen = []
    monkeypatch.setattr(updates, "check", lambda cfg, force=False, launch=False: _rel())
    monkeypatch.setattr(updates, "start_install", lambda path: seen.append(list(marks)))
    assert window.updctl.update_at_start() is True
    assert seen == [["closing"]]


def test_nothing_new_or_slow_the_app_opens_as_usual(window, qapp, monkeypatch, installer):
    import threading
    from soundboard.ui import splash, updatecontrol
    said = []
    monkeypatch.setattr(splash, "set_status", lambda text="", progress=None:
                        said.append(text))
    monkeypatch.setattr(updates, "check", lambda cfg, force=False, launch=False: None)
    assert window.updctl.update_at_start() is False and said[-1] == ""
    assert window.updctl.start_checked   # (the check after the window is up skips)
    hold = threading.Event()
    monkeypatch.setattr(updates, "check", lambda cfg, force=False, launch=False: hold.wait(5))
    monkeypatch.setattr(updatecontrol, "START_CHECK_S", 0.2)
    window.updctl.start_checked = False
    assert window.updctl.update_at_start() is False and not window.updctl.start_checked
    hold.set()
    assert installer.started == []


def test_a_failed_download_at_start_opens_the_app_with_the_card(window, qapp, monkeypatch,
                                                                installer):
    monkeypatch.setattr(updates, "check", lambda cfg, force=False, launch=False: _rel())

    def fail(rel, progress, cancelled):
        raise updates.UpdateError("nope")
    monkeypatch.setattr(updates, "download", fail)
    assert window.updctl.update_at_start() is False
    assert process_events(qapp, lambda: window.updctl.release is not None)
    assert installer.started == [] and window.btn_update.isVisible()


def test_unticked_nothing_is_asked_at_start(window, monkeypatch, installer):
    asked = []
    monkeypatch.setattr(updates, "check", lambda *a, **k: asked.append(1))
    window.cfg.update_auto = False
    assert window.updctl.update_at_start() is False and asked == []


def test_the_loading_screen_says_updated_after_an_update():
    from soundboard.ui import splash
    splash._updated(__version__)
    assert splash._status == f"Updated to {__version__}"
    splash.set_status()
    splash._updated("0.0.1")   # (an update that didn't land: Starting…)
    assert splash._status == ""


def test_a_sound_playing_asks_first(window, boxes, qapp, monkeypatch, installer):
    monkeypatch.setattr(window.engine, "playing", lambda: {"x": (0.5, False)})
    boxes.answers = {"Install the update": "Later"}
    _launch_check(window, qapp, monkeypatch, _rel())
    assert process_events(qapp, lambda: boxes.shown)
    assert boxes.shown[0][0] == "Install the update" and installer.started == []


def test_later_keeps_the_download_for_the_pill(window, boxes, qapp, monkeypatch, tmp_path):
    setup = tmp_path / "OnionBoardSetup-99.0.0.exe"
    setup.write_bytes(b"MZ")
    started = []
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", lambda rel, p, c: setup)
    monkeypatch.setattr(updates, "start_install", started.append)
    monkeypatch.setattr(window, "quit_app", lambda: None)
    boxes.answers = {"Update available": "Update now", "Install the update": "Later"}
    window.updctl._on_update(_rel(), "", True)
    assert process_events(qapp, lambda: window.updctl._update_file is not None)
    assert started == [] and window.cfg.update_pending == ""
    boxes.answers["Install the update"] = "Restart now"
    window.btn_update.click()              # the pill: straight to the restart question
    assert started == [setup] and window.cfg.update_pending == "99.0.0"


def test_a_failed_download_says_so_and_tries_again(window, boxes, qapp, monkeypatch):
    calls = []

    def download(rel, progress, cancelled):
        calls.append(1)
        progress(50 * 1024 * 1024, 180 * 1024 * 1024)
        raise updates.UpdateError("the downloaded file isn't the one GitHub lists")
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", download)
    boxes.answers = {"Update available": "Update now"}
    window.updctl._on_update(_rel(), "", True)
    assert process_events(qapp, lambda: not window.updctl._downloading)
    t = toast.shown(window)[-1]
    assert "Couldn't update" in t.text() and t.card.action.text() == "Open the download page"
    card = window.btn_update
    # never stuck at a percent: the warn state, the reason in its tip
    assert card.state == "failed" and card.pct is None
    assert card.accessibleName() == "Couldn't update" and card.hint == "Click to try again"
    assert "isn't the one GitHub lists" in card.toolTip()
    assert window.updctl._update_file is None
    assert card.copy.isHidden()                      # one failure: no Copy error yet
    card.click()                                     # "Click to try again"
    assert process_events(qapp, lambda: len(calls) == 2 and not window.updctl._downloading)
    assert card.state == "failed" and not card.copy.isHidden()   # twice: Copy error
    card.copy.click()
    report = qapp.clipboard().text()
    assert "isn't the one GitHub lists" in report and _rel().asset_url in report
    assert "try 2" in report and "Traceback" in report


def test_progress_fills_the_card_the_banner_and_settings(window, boxes, qapp):
    rel = _rel()
    rel.urgent = "sounds cut out after an hour"
    window.updctl._on_update(rel, "", False)
    window.updctl._downloading = True                       # (as download_update sets it)
    mb = 1024 * 1024
    window.updctl._on_update_progress(76 * mb, 180 * mb)
    card = window.btn_update
    assert card.state == "downloading" and card.pct == 42
    assert card.title == "Downloading 42%" and card.hint == "76 of 180 MB"
    assert window.urgent_prog.isVisibleTo(window.urgent_bar) and window.urgent_prog.value() == 42
    assert "76 of 180 MB" in window.urgent_sub.text() and window.urgent_btn.text() == "Cancel"
    assert window.updctl.update_status() == "Downloading 42% · 76 of 180 MB"
    window.updctl._on_update_progress(180 * mb, 180 * mb)
    assert card.pct == 100 and window.urgent_prog.value() == 100
    window.updctl._downloading = False


def test_cancel_stops_the_download(window, boxes, qapp, monkeypatch):
    import time
    started = []

    def download(rel, progress, cancelled):
        progress(1, 10)
        started.append(1)
        end = time.monotonic() + 5
        while not cancelled() and time.monotonic() < end:
            time.sleep(0.01)
        raise updates.UpdateError("cancelled")
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", download)
    window.updctl._on_update(_rel(), "", False)
    window.updctl.download_update()
    assert process_events(qapp, lambda: started)
    boxes.answers = {"Downloading the update": "Cancel download"}
    window.btn_update.click()                        # what's going on, and Cancel
    assert boxes.shown[-1][0] == "Downloading the update"
    assert process_events(qapp, lambda: not window.updctl._downloading)
    card = window.btn_update
    assert card.state == "available" and card.accessibleName() == "Update to 99.0.0"
    assert not any("Couldn't update" in t.text() for t in toast.shown(window))
    assert window.updctl._update_err == "" and window.updctl._update_fails == 0


def test_shut_the_update_is_one_rail_button(window, boxes):
    from soundboard.ui import sidebar
    window.resize(1180, 720)
    window.show()
    window.updctl._on_update(_rel(), "", False)
    window.rail.set_open(False)
    card = window.btn_update
    assert not card.isHidden() and not card.is_card()
    assert card.width() == sidebar.BUTTON_W and "Update to 99.0.0" in card.toolTip()
    window.rail.set_open(True)
    assert card.is_card() and card.width() == window.rail.output.width()


def test_from_source_it_only_opens_the_page(window, boxes, monkeypatch):
    monkeypatch.setattr(updates, "can_install", lambda: False)
    window.updctl._on_update(_rel(), "", True)
    assert "Open the download page" in boxes.shown[0][1]
    assert "Update now" not in boxes.shown[0][1]


def test_next_start_says_whether_the_update_worked(window, boxes):
    window.cfg.setup_done = True
    window.cfg.whats_new_seen = __version__   # What's new seen: the plain note
    window.show()
    window.cfg.update_pending = __version__
    window.updctl.after_update()
    t = toast.shown(window)[-1]
    assert "up to date" in t.text() and t.card.action.text() == "What's new"
    assert window.cfg.update_pending == ""
    window.cfg.update_pending = "99.0.0"
    window.updctl.after_update()
    assert boxes.shown[-1][0] == "The update didn't finish" and window.cfg.update_pending == ""
    n = len(boxes.shown)
    window.updctl.after_update()                  # nothing pending: nothing to say
    assert len(boxes.shown) == n


# --------------------------------------------------------------------------- urgent fixes

def _urgent():
    rel = _rel()
    rel.urgent = "sounds cut out after an hour"
    return rel


def test_a_normal_update_has_no_banner(window, boxes):
    window.updctl._on_update(_rel(), "", False)
    assert window.urgent_bar.isHidden() and not window.btn_update.isHidden()


def test_an_urgent_fix_gets_a_banner_and_no_skip(window, boxes, qapp, monkeypatch, tmp_path):
    setup = tmp_path / "OnionBoardSetup-99.0.0.exe"
    setup.write_bytes(b"MZ")
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", lambda rel, p, c: setup)
    monkeypatch.setattr(window, "quit_app", lambda: None)
    window.updctl._on_update(_urgent(), "", False)          # the timed check found it
    assert not window.urgent_bar.isHidden()
    assert "sounds cut out after an hour" in window.urgent_lbl.text()
    assert window.urgent_btn.text() == "Update now"

    window.btn_update.click()                        # the pill's dialog: no Skip
    title, buttons = boxes.shown[-1]
    assert title == "Important fix available" and "Skip this version" not in buttons

    boxes.answers = {"Install the update": "Later"}
    window.urgent_btn.click()                        # the banner's Update now
    assert process_events(qapp, lambda: window.updctl._update_file is not None)
    assert not window.urgent_bar.isHidden()
    assert window.urgent_btn.text() == "Restart to update"


def test_hiding_the_banner_lasts_until_the_next_start(window, boxes):
    window.updctl._on_update(_urgent(), "", False)
    window.urgent_bar.findChild(type(window.urgent_btn), "urgenthide").click()
    assert window.urgent_bar.isHidden()
    window.updctl._on_update(_urgent(), "", False)          # found again 6 hours later
    assert window.urgent_bar.isHidden()
    assert not window.btn_update.isHidden()          # the pill stays


def test_an_urgent_onion_watch_fix_gets_the_banner_on_its_tab_only(window, monkeypatch):
    from soundboard import watchaddon
    calls = []
    monkeypatch.setattr(window.triggers, "offer_update", lambda o: calls.append(o))
    window.tabs.setCurrentIndex(0)                   # the Sounds tab
    window.updctl._on_watch_update(watchaddon.Offer("9.9.9", notes="Fixes."))
    assert window.urgent_bar.isHidden() and len(calls) == 1   # a normal one: the tab only
    window.updctl._on_watch_update(watchaddon.Offer("9.9.9", urgent="triggers stop firing"))
    assert window.urgent_bar.isHidden() and len(calls) == 2   # not on the Sounds tab
    window.tabs.setCurrentWidget(window.triggers)
    assert not window.urgent_bar.isHidden()
    assert "Onion Watch 9.9.9" in window.urgent_lbl.text()
    assert window.urgent_btn.text() == "Update Onion Watch"
    window.tabs.setCurrentIndex(0)                   # and gone again off it
    assert window.urgent_bar.isHidden()
    window.tabs.setCurrentWidget(window.triggers)
    window.urgent_btn.click()                        # updates there, banner gone
    assert window.tabs.currentWidget() is window.triggers
    assert window.urgent_bar.isHidden()
