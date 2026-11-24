"""The picked mic is another app's virtual one: the box names the app, and each way on
runs (the real mic, again, anyway, the cable)."""
import pytest
from PySide6.QtWidgets import QLabel

from soundboard.mic import directmic as dm
from soundboard.ui.setup import virtualmicbox
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

VIRTUAL, REAL = "Microphone (Voicemod)", "Microphone (USB Mic)"
OTHER = "Headset (Blue)"


def _endpoint(guid, name, enum, active=True):
    return {"guid": guid, "name": name, "active": active, "out": not active,
            "device": name.partition("(")[2].rstrip(")"), "bt": False, "enum": enum}


@pytest.fixture
def mics(monkeypatch, tmp_path):
    ends = [_endpoint("v", VIRTUAL, "ROOT"), _endpoint("r", REAL, "USB"),
            _endpoint("o", OTHER, "BTHENUM"), _endpoint("s", "Mic (Sonar)", "ROOT"),
            _endpoint("x", "Mic (Unplugged)", "USB", active=False)]
    monkeypatch.setattr(dm, "capture_endpoints", lambda: ends)
    monkeypatch.setattr(dm, "endpoint_for", lambda n: next(
        (e["guid"] for e in ends if e["name"] == n and e["active"]), None))
    dll = tmp_path / "obmic.dll"
    dll.write_bytes(b"dll")
    monkeypatch.setattr(dm, "bundled_dll", lambda: dll)
    return ends


def _ask(real, done):
    return virtualmicbox.ask(
        None, "Voicemod", VIRTUAL, real, use_mic=done.append,
        again=lambda: done.append("again"), anyway=lambda: done.append("anyway"),
        cable=lambda: done.append("cable"))


def test_the_box_names_the_app_and_runs_only_what_was_picked(qapp):
    done = []
    d = _ask([REAL], done)
    said = " ".join(lbl.text() for lbl in d.findChildren(QLabel))
    assert "Voicemod's mic" in said and d.mic_box.currentData() == REAL
    assert d.mic_button.isDefault()
    d.mic_button.click()
    for name in ("again", "anyway", "cable"):
        getattr(_ask([REAL], done), name + "_button").click()
    _ask([REAL], done).reject()
    assert done == [REAL, "again", "anyway", "cable"]


def test_several_real_mics_are_picked_from_and_none_hides_the_button(qapp):
    done = []
    d = _ask([REAL, OTHER], done)
    d.mic_box.setCurrentIndex(1)
    d.mic_button.click()
    assert done == [OTHER]
    d = _ask([], done)
    assert d.mic_button is None and d.again_button.isDefault()
    d.reject()


def test_the_real_mics_leave_out_virtual_and_unplugged_ones(mics):
    assert dm.real_mics(e["name"] for e in mics) == [REAL, OTHER]


def test_try_anyway_runs_the_set_up(mics, monkeypatch):
    ran = []
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: ran.append(a) or 0)
    err = dm.install(VIRTUAL)
    assert err is not None and dm.fail_kind(err) == "virtual-mic"
    assert "Voicemod" in err and not ran
    assert dm.install(VIRTUAL, force=True) is None and len(ran) == 1
    # it didn't work, as it usually doesn't: the app is named again
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: dm.EFFECT_NOT_STARTED)
    err = dm.install(VIRTUAL, force=True)
    assert dm.fail_kind(err) == "code-8" and "Voicemod" in err


def _failed(w, **kw):
    """The set-up on the picked mic, its worker and answer run here."""
    w.micctl._mic_attached(*w.micctl._attach_mic_work(
        VIRTUAL, names=(VIRTUAL, REAL, OTHER), **kw))


def test_the_set_up_opens_the_box_and_the_repair_by_itself_doesnt(window, mics,  # noqa: F811
                                                                   monkeypatch):
    w, opened, attached = window, [], []
    monkeypatch.setattr(virtualmicbox, "ask", lambda *a, **k: opened.append((a, k)))
    _failed(w)
    (args, ways), = opened
    assert args[1:] == ("Voicemod", VIRTUAL, [REAL, OTHER])
    assert w.micctl._blocked is None   # used once
    monkeypatch.setattr(w.micctl, "attach_mic", lambda **k: attached.append(k))
    ways["again"]()
    ways["anyway"]()
    assert attached == [{"again": True}, {"force": True}]
    w.micctl._autofixing = True
    _failed(w, auto=True)
    assert len(opened) == 1


def test_again_with_the_apps_mic_gone_sets_up_windows_default(window, mics,  # noqa: F811
                                                               monkeypatch):
    """They turned the app off and its mic went with it: no dead end about a mic that's off."""
    ran = []
    mics[0]["active"] = False
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: ran.append(a) or 0)
    monkeypatch.setattr(dm, "mic_lookup", lambda n: (None, "off"))
    monkeypatch.setattr(dm, "fallback_mic", lambda n: REAL)
    monkeypatch.setattr(dm, "installed_on", lambda: [])
    mic, err = window.micctl._attach_mic_work(VIRTUAL)
    assert mic == VIRTUAL and err and not ran   # (a plain set-up keeps the picked mic)
    mic, err = window.micctl._attach_mic_work(VIRTUAL, again=True)
    assert (mic, err) == (REAL, "") and len(ran) == 1


def test_use_my_real_mic_picks_it_and_sets_it_up(window, monkeypatch):  # noqa: F811
    w, attached = window, []
    monkeypatch.setattr(w.micctl, "attach_mic", lambda **k: attached.append(w.cfg.mic_device))
    monkeypatch.setattr(dm, "status", lambda *a, **k: "missing")
    monkeypatch.setattr(w.devctl, "_device_job", lambda *a, **k: None)
    w.routectl._fill_combo(w.cb_mic, [VIRTUAL, REAL], VIRTUAL)
    w.cfg.mic_device = VIRTUAL
    w.routectl.use_real_mic(REAL)
    assert attached == [REAL] and w.cb_mic.currentData() == REAL
    # on it already: no set-up, the sounds just go there
    routes, picks = [], []
    monkeypatch.setattr(dm, "status", lambda *a, **k: "ready")
    monkeypatch.setattr(w.routectl, "set_route", lambda r, **k: routes.append(r))
    w.routectl.use_real_mic(REAL)
    assert routes == ["mic"] and attached == [REAL]
    # unplugged meanwhile: the mic box, and nothing changed
    monkeypatch.setattr(w.micctl, "_pick_mic", lambda: picks.append(1))
    w.routectl.use_real_mic("gone")
    assert picks == [1] and w.cfg.mic_device == REAL
