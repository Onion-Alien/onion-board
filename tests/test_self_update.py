"""The update pill in the real MainWindow (offscreen): found → Update now → downloaded
→ Restart to update → installer started and the app quits; and the note on the next
start. No network and no installer run: updates.download / start_install are faked."""
import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import process_events
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

    window._on_update(_rel(), "", True)    # "Check now" found it: the dialog opens
    assert boxes.shown[0][0] == "Update available" and "Release page" in boxes.shown[0][1]
    assert process_events(qapp, lambda: started)
    assert started == [setup] and quit_ == [1]
    assert window.btn_update.text() == "Restart to update"
    assert window.cfg.update_pending == "99.0.0"


def test_later_keeps_the_download_for_the_pill(window, boxes, qapp, monkeypatch, tmp_path):
    setup = tmp_path / "OnionBoardSetup-99.0.0.exe"
    setup.write_bytes(b"MZ")
    started = []
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", lambda rel, p, c: setup)
    monkeypatch.setattr(updates, "start_install", started.append)
    monkeypatch.setattr(window, "quit_app", lambda: None)
    boxes.answers = {"Update available": "Update now", "Install the update": "Later"}
    window._on_update(_rel(), "", True)
    assert process_events(qapp, lambda: window._update_file is not None)
    assert started == [] and window.cfg.update_pending == ""
    boxes.answers["Install the update"] = "Restart now"
    window.btn_update.click()              # the pill: straight to the restart question
    assert started == [setup] and window.cfg.update_pending == "99.0.0"


def test_a_failed_download_puts_the_pill_back(window, boxes, qapp, monkeypatch):
    def download(rel, progress, cancelled):
        raise updates.UpdateError("the downloaded file isn't the one GitHub lists")
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", download)
    boxes.answers = {"Update available": "Update now"}
    window._on_update(_rel(), "", True)
    assert process_events(qapp, lambda: not window._downloading)
    assert boxes.shown[-1][0] == "Couldn't update"
    assert window.btn_update.text() == "Update: 99.0.0" and window.btn_update.isEnabled()
    assert window._update_file is None


def test_from_source_it_only_opens_the_page(window, boxes, monkeypatch):
    monkeypatch.setattr(updates, "can_install", lambda: False)
    window._on_update(_rel(), "", True)
    assert "Open the download page" in boxes.shown[0][1]
    assert "Update now" not in boxes.shown[0][1]


def test_next_start_says_whether_the_update_worked(window, boxes):
    window.cfg.setup_done = True
    window.cfg.whats_new_seen = __version__   # What's new seen: the plain note
    window.show()
    window.cfg.update_pending = __version__
    window.after_update()
    assert boxes.shown[-1][0] == "Updated" and window.cfg.update_pending == ""
    window.cfg.update_pending = "99.0.0"
    window.after_update()
    assert boxes.shown[-1][0] == "The update didn't finish" and window.cfg.update_pending == ""
    n = len(boxes.shown)
    window.after_update()                  # nothing pending: nothing to say
    assert len(boxes.shown) == n


# --------------------------------------------------------------------------- urgent fixes

def _urgent():
    rel = _rel()
    rel.urgent = "sounds cut out after an hour"
    return rel


def test_a_normal_update_has_no_banner(window, boxes):
    window._on_update(_rel(), "", False)
    assert window.urgent_bar.isHidden() and not window.btn_update.isHidden()


def test_an_urgent_fix_gets_a_banner_and_no_skip(window, boxes, qapp, monkeypatch, tmp_path):
    setup = tmp_path / "OnionBoardSetup-99.0.0.exe"
    setup.write_bytes(b"MZ")
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download", lambda rel, p, c: setup)
    monkeypatch.setattr(window, "quit_app", lambda: None)
    window._on_update(_urgent(), "", False)          # the timed check found it
    assert not window.urgent_bar.isHidden()
    assert "sounds cut out after an hour" in window.urgent_lbl.text()
    assert window.urgent_btn.text() == "Update now"

    window.btn_update.click()                        # the pill's dialog: no Skip
    title, buttons = boxes.shown[-1]
    assert title == "Important fix available" and "Skip this version" not in buttons

    boxes.answers = {"Install the update": "Later"}
    window.urgent_btn.click()                        # the banner's Update now
    assert process_events(qapp, lambda: window._update_file is not None)
    assert not window.urgent_bar.isHidden()
    assert window.urgent_btn.text() == "Restart to update"


def test_hiding_the_banner_lasts_until_the_next_start(window, boxes):
    window._on_update(_urgent(), "", False)
    window.urgent_bar.findChild(type(window.urgent_btn), "urgenthide").click()
    assert window.urgent_bar.isHidden()
    window._on_update(_urgent(), "", False)          # found again 6 hours later
    assert window.urgent_bar.isHidden()
    assert not window.btn_update.isHidden()          # the pill stays


def test_an_urgent_onion_watch_fix_gets_the_banner_too(window, monkeypatch):
    from soundboard import watchaddon
    calls = []
    monkeypatch.setattr(window.triggers, "offer_update", lambda o: calls.append(o))
    window._on_watch_update(watchaddon.Offer("9.9.9", notes="Fixes."))
    assert window.urgent_bar.isHidden() and len(calls) == 1   # a normal one: the tab only
    window._on_watch_update(watchaddon.Offer("9.9.9", urgent="triggers stop firing"))
    assert not window.urgent_bar.isHidden() and len(calls) == 2
    assert "Onion Watch 9.9.9" in window.urgent_lbl.text()
    assert window.urgent_btn.text() == "Update Onion Watch"
    window.urgent_btn.click()                        # off to its tab, banner gone
    assert window.tabs.currentWidget() is window.triggers
    assert window.urgent_bar.isHidden()
