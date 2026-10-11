"""Setup tab: the EQ folds while off, and Connect your chat waits for a chat to connect."""
from test_mainwindow import window  # noqa: F401

from soundboard import directmic as dm
from soundboard import engine as eng
from soundboard.ui.panel import EqPanel


class _Stream:
    def stop(self):
        pass
    close = stop


def test_setup_eq_folds_to_its_header_while_off(window):  # noqa: F811
    eq = window.eq
    eq.chk_on.setChecked(False)
    assert eq.body.isHidden()
    assert not eq.chk_on.isHidden() and not eq.cb_target.isHidden()   # the header row stays
    eq.chk_on.setChecked(True)
    assert not eq.body.isHidden()
    eq.chk_on.setChecked(False)
    eq.cb_preset.setCurrentIndex(1)   # picking a preset turns it on, and opens it
    assert eq.chk_on.isChecked() and not eq.body.isHidden()
    eq.cb_preset.setCurrentIndex(eq.cb_preset.findData("Flat (off)"))   # off again
    assert not eq.chk_on.isChecked() and eq.body.isHidden()


def test_other_eq_panels_dont_fold(qapp):
    p = EqPanel(False, "sounds", "Flat (off)", [0.0] * 7)   # (a sound's own EQ)
    assert not p.body.isHidden()


def _cable_missing(w, monkeypatch):
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    w.cfg.route = "cable"
    w.cfg.main_device = None


def test_chat_card_waits_for_a_chat_to_connect(window, monkeypatch):  # noqa: F811
    """Nothing set up yet, or Nobody: Connect your chat held only the guide, so it's
    hidden and the guide is in the mic card. Once sounds reach a mic it's back."""
    w = window
    _cable_missing(w, monkeypatch)
    w._show_route()
    w._update_status()
    assert w.helpcard.isHidden()
    assert not w.btn_guide.isHidden()
    w.cfg.route = "off"
    w._update_status()
    assert w.helpcard.isHidden() and not w.btn_guide.isHidden()
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)
    monkeypatch.setattr(w.engine, "main_stream", _Stream())
    w.cfg.route = "mic"
    w._show_route()
    w._update_status()
    assert not w.helpcard.isHidden()
    assert w.btn_guide.isHidden()
    assert not w.btn_chat.isHidden()
