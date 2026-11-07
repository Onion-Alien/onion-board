"""Setup tab: the EQ folds while off, Set up your voice apps waits for a chat to connect,
and the cards are always open."""
from test_mainwindow import window  # noqa: F401

from soundboard.mic import directmic as dm
from soundboard.audio import engine as eng
from soundboard.ui.kit.panel import EqPanel


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


def test_the_guide_is_always_in_connect_your_chat_and_only_there(window, monkeypatch):  # noqa: F811
    """Nothing set up yet, or Nobody: Set up your voice apps holds just the guide. Once sounds
    reach a mic its other buttons are back. Never a second guide in the mic card."""
    w = window
    _cable_missing(w, monkeypatch)
    w.routectl._show_route()
    w.statusctl._update_status()
    guides = [b for b in w.setup_page.findChildren(type(w.btn_guide))
              if b.text() == w.btn_guide.text()]
    assert guides == [w.btn_guide] and w.btn_guide.parentWidget() is w.helpcard
    assert not w.helpcard.isHidden() and not w.btn_guide.isHidden()
    assert not w.discord_card.wanted and w.chat_hint.isHidden()
    w.cfg.route = "off"
    w.statusctl._update_status()
    assert not w.helpcard.isHidden() and not w.discord_card.wanted
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(w.engine, "main_stream", _Stream())
    w.cfg.route = "mic"
    w.routectl._show_route()
    w.statusctl._update_status()
    assert not w.btn_guide.isHidden() and w.discord_card.wanted and not w.chat_hint.isHidden()


def test_setup_cards_are_all_open(window):  # noqa: F811
    """Devices, Set up your voice apps and Equalizer and volume are plain cards, always open:
    they fit the screen, so nothing folds away behind a click."""
    w = window
    for card in (w.dev_card, w.helpcard, w.eq_card):
        assert card.heading_title is not None
    assert w.eq.parentWidget() is w.eq_card
    assert w.chk_level.parentWidget() is w.eq_card
    assert w.cb_mon.parentWidget() is w.dev_card
    assert w.cb_mic.parentWidget() is w.how_home.card   # the only place it's picked on the tab
