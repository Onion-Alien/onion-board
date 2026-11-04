"""The mic part's update: the Setup tab's banner and its Update now. Nothing pops up by
itself; Windows is only asked after the click, and only if it's still needed then."""
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialog, QFrame

from soundboard.mic import directmic as dm
from test_mainwindow import window  # noqa: F401  (fixture)


@pytest.fixture
def outdated(window, monkeypatch):  # noqa: F811
    """On the mic, with an older mic part: the update is due. Records attach_mic
    (Windows' admin prompt) and toasts instead of running them."""
    w = window
    w.cfg.route, w.cfg.mic_device = "mic", "My mic"
    state = {"status": "outdated", "tried": [], "toasts": []}
    monkeypatch.setattr(dm, "status", lambda name=None: state["status"])
    monkeypatch.setattr(w.cfg, "save", lambda: True)
    monkeypatch.setattr(w.micctl, "attach_mic", lambda clean=False: state["tried"].append(
        (w.cfg.mic_device, clean)))
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **kw: state["toasts"].append(
        (text, kind)))
    monkeypatch.setattr(w, "isVisible", lambda: True)
    return w, state


@pytest.mark.parametrize("change", ["route", "fixed", "mic"])
def test_rechecked_when_accepted(outdated, change):
    """The settings can change after the banner was drawn: Update now checks again first."""
    w, state = outdated
    if change == "route":
        w.cfg.route = "cable"
    elif change == "fixed":
        state["status"] = "ready"
    else:
        w.cfg.mic_device = ""
    w.btn_micupdate.click()
    assert state["tried"] == [] and not w.micctl._mic_updating
    assert state["toasts"]


def test_cancel_and_failure_and_success_feedback(outdated, monkeypatch):
    w, state = outdated
    monkeypatch.setattr(w.routectl, "set_route",
                        lambda route, *a, **k: setattr(w.cfg, "route", route))
    w.micctl._mic_updating = True
    w.micctl._mic_attached("My mic", dm.declined())   # No in Windows' prompt: a note, no error
    assert state["toasts"][-1][1] == "warn" and "cancelled" in state["toasts"][-1][0]
    assert all(kind != "error" for _t, kind in state["toasts"])
    w.micctl._mic_updating = True
    w.micctl._mic_attached("My mic", "Installing failed (code 5).")   # a real failure: an error
    assert state["toasts"][-1][1] == "error" and "code 5" in state["toasts"][-1][0]
    w.micctl._mic_updating = True
    w.micctl._mic_attached("My mic", "")
    assert not w.micctl._mic_updating
    assert state["toasts"][-1][1] == "error"   # not "updated" while Windows still loads it
    monkeypatch.setattr(w.engine, "main_stream", object())   # ...it runs now
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    w.statusctl._update_flow()
    assert state["toasts"][-1] == ("Mic updated: games, calls and browsers hear your "
                                   "sounds.", "ok")


def test_setup_card_says_update_and_does_the_same_update(outdated, monkeypatch):
    """The Setup tab's mic card says the part needs updating (not "nothing to set"), and
    its Update now runs the clean update."""
    w, state = outdated
    e = w.engine
    for k in ("mic_stream", "main_stream"):
        monkeypatch.setattr(e, k, object(), raising=False)
    monkeypatch.setattr(e, "effect_alive", lambda: True, raising=False)
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    w.statusctl._update_status()
    assert not w.mic_update_note.isHidden() and w.step_lbl.isHidden()
    assert "Update your mic part" in w.mic_update_text.text()
    assert w.btn_install.isHidden()   # one button: the banner's
    w.btn_micupdate.click()
    assert state["tried"] == [("My mic", True)]
    state["status"] = "ready"   # updated: the card is back to normal
    w.statusctl._update_status()
    assert w.mic_update_note.isHidden()
    assert w.mic_line.text() == "Your sounds go into your mic"


def test_an_old_mic_part_never_pops_anything_up_by_itself(outdated):
    """A card over the window at every start until it was updated: gone. Setup's banner
    keeps it one click away, and Windows is never asked by itself."""
    w, state = outdated
    w.show()
    for _ in range(5):
        QCoreApplication.processEvents()
    assert not hasattr(w.micctl, "_offer_mic_update")
    assert not [d for d in w.findChildren(QDialog) if d.isVisible()]
    assert not [f for f in w.findChildren(QFrame) if f.objectName() == "micupdate"]
    assert state["tried"] == []
