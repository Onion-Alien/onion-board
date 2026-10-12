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


def test_setup_rows_shut_to_a_summary_that_follows_the_settings(window):  # noqa: F811
    """Devices, Connect your chat and Equalizer and volume start shut, each a line with
    a summary: the devices in use, and whether the EQ and levelling are on."""
    w = window
    for f in (w.dev_fold, w.helpcard, w.sound_fold):
        assert not f.is_open() and f.inner.isHidden()
    assert w.cb_mon.currentText() in w.dev_fold.summary.text()
    w.eq.chk_on.setChecked(True)
    assert w.sound_fold.summary.text().startswith("EQ on")
    w.eq.chk_on.setChecked(False)
    assert w.sound_fold.summary.text().startswith("EQ off")
    w.chk_level.setChecked(True)
    assert w.sound_fold.summary.text().endswith("Volumes levelled")
    w.chk_level.setChecked(False)
    assert w.sound_fold.summary.text().endswith("Volumes as they are")
    w.sound_fold.set_open(True)   # open, the card shows it instead: no summary
    assert not w.sound_fold.inner.isHidden() and w.sound_fold.summary.text() == ""
    w.chk_level.setChecked(True)
    assert w.sound_fold.summary.text() == ""
    w.sound_fold.set_open(False)
    assert w.sound_fold.summary.text().endswith("Volumes levelled")
    assert w.eq.parentWidget() is w.sound_fold.inner
    assert w.chk_level.parentWidget() is w.sound_fold.inner


def test_cable_fix_opens_the_devices_row(window, monkeypatch):  # noqa: F811
    """The cable's 48 kHz fix lives in Devices: when it's needed the row opens, once,
    so it's never hidden behind a shut row (shut again, it stays shut)."""
    w = window
    monkeypatch.setattr(eng, "virtual_mic_for", lambda name: "CABLE Output (fake)")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: ["CABLE Input (fake)"])
    monkeypatch.setattr(w.engine, "main_stream", _Stream())   # the cable route works
    w.cfg.route = "cable"
    from soundboard import cableformat
    w.cable_bad = [cableformat.CableEnd("CABLE Input", "render", "{id}", 44100, 16, 2)]
    w._show_route()
    w._update_status()
    assert not w.btn_cablefix.isHidden()
    assert w.dev_fold.is_open()
    w.dev_fold.set_open(False)
    w._update_status()
    assert not w.dev_fold.is_open()
