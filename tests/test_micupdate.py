"""The mic part's update offer (ui/micupdate.py, MainWindow._offer_mic_update): shown
a moment after the window opens, never from the tray, once per version; Windows is
only asked after Install update, and only if the update is still needed then."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from soundboard import directmic as dm
from soundboard.ui import mainwindow as main
from soundboard.ui import micupdate
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
    monkeypatch.setattr(w, "attach_mic", lambda clean=False: state["tried"].append(
        (w.cfg.mic_device, clean)))
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **kw: state["toasts"].append(
        (text, kind)))
    monkeypatch.setattr(w, "isVisible", lambda: True)
    return w, state


def test_offered_not_installed(outdated):
    w, state = outdated
    w._offer_mic_update()
    offer = w._mic_offer
    assert isinstance(offer, micupdate.MicUpdateOffer) and not offer.isHidden()
    assert state["tried"] == []   # asking isn't installing
    assert not offer.btn_install.icon().isNull()   # the admin shield
    assert offer.btn_install.objectName() == "primary"


@pytest.mark.parametrize("how", ["not now", "escape", "closed"])
def test_dismissing_never_installs(outdated, qapp, how):
    w, state = outdated
    w._offer_mic_update()
    offer = w._mic_offer
    if how == "not now":
        offer.btn_later.click()
    elif how == "escape":
        QTest.keyClick(offer.btn_install, Qt.Key.Key_Escape)
    else:
        offer.dismiss()
    qapp.processEvents()
    assert state["tried"] == [] and w._mic_offer is None
    w._offer_mic_update()   # offered this start: not again until the next one
    assert w._mic_offer is None


def test_install_asks_windows_once(outdated, qapp):
    w, state = outdated
    w._offer_mic_update()
    offer = w._mic_offer
    offer.btn_install.click()
    offer.btn_install.click()   # a double click doesn't ask twice
    qapp.processEvents()
    # the old part comes off completely first, then the new one goes on
    assert state["tried"] == [("My mic", True)] and w._mic_offer is None
    assert w._mic_updating


def test_offered_again_each_start(outdated):
    """An old part may not reach every app: the offer comes back every start until
    it's updated (once per start)."""
    w, state = outdated
    w._offer_mic_update()
    first = w._mic_offer
    w._offer_mic_update()   # while it's up: the same one
    assert w._mic_offer is first
    first.dismiss()
    w._offer_mic_update()
    assert w._mic_offer is None   # not twice in one start
    w._mic_offered = False        # the next start
    w._offer_mic_update()
    assert w._mic_offer is not None and w._mic_offer is not first


def test_never_from_the_tray(outdated, monkeypatch):
    w, state = outdated
    monkeypatch.setattr(w, "isVisible", lambda: False)
    w._offer_mic_update()
    assert w._mic_offer is None and not w._mic_offered


def test_shown_a_second_after_the_window_opens(outdated, qapp, monkeypatch):
    w, state = outdated
    monkeypatch.delattr(w, "isVisible")   # the real one: hidden until shown
    w._offer_mic_update()
    assert w._mic_offer is None   # still hidden (in the tray)
    w.show()
    qapp.processEvents()
    assert w._mic_offer is None   # not at once
    QTest.qWait(main.MIC_OFFER_MS + 400)
    assert w._mic_offer is not None and not w._mic_offer.isHidden()
    assert state["tried"] == []
    w._mic_offer.dismiss()


@pytest.mark.parametrize("change", ["route", "fixed", "mic"])
def test_rechecked_when_accepted(outdated, change):
    """The settings can change while the offer is up: Install checks again first."""
    w, state = outdated
    w._offer_mic_update()
    offer = w._mic_offer
    if change == "route":
        w.cfg.route = "cable"
    elif change == "fixed":
        state["status"] = "ready"
    else:
        w.cfg.mic_device = ""
    offer.btn_install.click()
    assert state["tried"] == [] and not w._mic_updating
    assert state["toasts"]


def test_not_offered_when_not_needed(outdated):
    w, state = outdated
    for route, status in (("cable", "outdated"), ("mic", "ready"), ("mic", "missing")):
        w.cfg.route = route
        state["status"] = status
        w._offer_mic_update()
        assert w._mic_offer is None
    assert not w._mic_offered   # not used up: offered once it's due


def test_cancel_and_failure_and_success_feedback(outdated, monkeypatch):
    w, state = outdated
    monkeypatch.setattr(w.routectl, "set_route",
                        lambda route, *a, **k: setattr(w.cfg, "route", route))
    w._mic_updating = True
    w._mic_attached("My mic", dm.declined())   # No in Windows' prompt: a note, no error
    assert state["toasts"][-1][1] == "warn" and "cancelled" in state["toasts"][-1][0]
    assert all(kind != "error" for _t, kind in state["toasts"])
    w._mic_updating = True
    w._mic_attached("My mic", "Installing failed (code 5).")   # a real failure: an error
    assert state["toasts"][-1][1] == "error" and "code 5" in state["toasts"][-1][0]
    w._mic_updating = True
    w._mic_attached("My mic", "")
    assert not w._mic_updating
    assert state["toasts"][-1][1] == "error"   # not "updated" while Windows still loads it
    monkeypatch.setattr(w.engine, "main_stream", object())   # ...it runs now
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)
    w._update_flow()
    assert state["toasts"][-1] == ("Mic updated: games, calls and browsers hear your "
                                   "sounds.", "ok")


def test_prompt_note_names_what_windows_asks_for():
    assert "Python" in micupdate.prompt_note(frozen=False)
    assert "OnionBoard.exe" in micupdate.prompt_note(frozen=True)


def test_setup_card_says_update_and_does_the_same_update(outdated, monkeypatch):
    """Said no to the offer: the Setup tab's mic card says the part needs updating (not
    "nothing to set"), and its Update now runs the same clean update as the offer."""
    w, state = outdated
    e = w.engine
    for k in ("mic_stream", "main_stream"):
        monkeypatch.setattr(e, k, object(), raising=False)
    monkeypatch.setattr(e, "effect_alive", lambda: True, raising=False)
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)
    w._update_status()
    assert not w.mic_update_note.isHidden() and w.step_lbl.isHidden()
    assert "Update your mic part" in w.mic_update_text.text()
    assert w.btn_install.isHidden()   # one button: the banner's
    w.btn_micupdate.click()
    assert state["tried"] == [("My mic", True)]
    state["status"] = "ready"   # updated: the card is back to normal
    w._update_status()
    assert w.mic_update_note.isHidden()
    assert w.mic_line.text() == "Your sounds go into your mic"
