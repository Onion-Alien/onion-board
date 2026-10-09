"""UI fixes from an audit pass, offscreen: voice list stand-ins keep the saved voice,
a voice reload asked for mid-load still runs, double-clicks on a radio row's badge /
star, a failed capture reopen ends a recording, pad drops in the gaps, the setup
guide's buttons, overlay flash / hover, theme recolouring, and the EQ's off state."""
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QLabel, QListWidget, QPushButton, QStackedWidget,
                               QStyleOptionViewItem)

from soundboard import theme
from soundboard.speech import tts
from soundboard.ui import appspanel, busy, setupwizard
from tests.conftest import process_events
from tests.test_appspanel import FakeCapture, music, tab  # noqa: F401  (fixture)
from tests.test_overlay import make  # noqa: F401  (fixture)
from tests.test_voicepanel import FakeEngine


# ---- voice panel
@pytest.fixture
def speech(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {}, {"voice": "Microsoft Zira Desktop"})
    yield p.speech
    p.shutdown()
    p.deleteLater()


def test_settings_changed_while_the_voice_list_loads_keep_the_saved_voice(speech, qapp):
    s = speech
    if not s.cb_voice.isEnabled():               # still "Loading voices…"
        s.sl_rate.setValue(4)
        assert s.s["voice"] == "Microsoft Zira Desktop"
    assert process_events(qapp, lambda: s.cb_voice.isEnabled())
    s._fill_voices([], "speech failed")          # only "Windows default" listed
    s.sl_rate.setValue(5)
    assert s.s["voice"] == "Microsoft Zira Desktop" and s.s["rate"] == 5
    s._fill_voices(["Microsoft Zira Desktop"], "")   # back: still the one picked
    assert s.cb_voice.currentData() == "Microsoft Zira Desktop"
    s.cb_voice.setCurrentIndex(0)                # picking the default yourself does count
    assert s.s["voice"] == ""


def test_a_reload_asked_for_mid_load_runs_after_it(speech, qapp, monkeypatch):
    s = speech
    assert process_events(qapp, lambda: not s._loading())
    s._loading_since = time.monotonic()          # a load in flight
    s._recheck_voices()                          # e.g. a voice server was just added
    calls = []
    monkeypatch.setattr(s, "_recheck_voices", lambda: calls.append(1))
    s._fill_voices(["Microsoft Zira Desktop"], "")   # the first load answers
    assert process_events(qapp, lambda: calls)
    s._fill_voices(["Microsoft Zira Desktop"], "")   # and only once
    qapp.processEvents()
    assert calls == [1]


# ---- radio
def test_double_click_on_the_station_badge_plays_and_on_the_star_stars(qapp):
    from soundboard.ui.radiopanel import ROW_H, _StationDelegate
    calls = []
    lst = QListWidget()
    fake = SimpleNamespace(list=lst, _play_or_stop=lambda u: calls.append(("play", u)),
                           _toggle_fav=lambda u: calls.append(("fav", u)))
    d = _StationDelegate(fake)
    model = QStandardItemModel()
    it = QStandardItem()
    it.setData("u1", Qt.UserRole)
    model.appendRow(it)
    idx = model.index(0, 0)
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 400, ROW_H)
    _card, avatar, star = d._rects(opt.rect)

    def double_click(pos):
        p = QPointF(pos)
        seq = [(QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton),
               (QEvent.MouseButtonDblClick, Qt.LeftButton),
               (QEvent.MouseButtonRelease, Qt.NoButton)]
        eaten = [d.editorEvent(QMouseEvent(t, p, p, Qt.LeftButton, held, Qt.NoModifier),
                               model, opt, idx) for t, held in seq]
        qapp.processEvents()
        return eaten

    eaten = double_click(avatar.center())
    assert calls == [("play", "u1")]
    assert eaten[2]                              # no "activated" play on top of it
    calls.clear()
    double_click(star.center())
    assert calls == [("fav", "u1")]
    lst.deleteLater()


# ---- apps
def test_restart_with_a_failed_reopen_ends_the_recording(tab, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(appspanel.library, "APP_DIR", tmp_path)
    tab._on_apps([music()])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    row.btn_rec.setChecked(True)
    row.capture.sink(np.full((4800, 2), 0.3, np.float32))
    row.capture.ended = True                     # the program restarted…
    FakeCapture.fail = True                      # …and can't be captured again
    tab._on_apps([music(pid=101)])
    assert not row.sending and row.capture is None
    assert row.rec is None and not row.btn_rec.isChecked()


# ---- pad grid
def test_a_pad_dropped_in_a_gap_goes_to_the_nearest_pad():
    from PySide6.QtCore import QPoint

    from soundboard.ui.widgets import PadGrid

    class P:
        def __init__(self, r, shown=True):
            self.r, self.shown = r, shown

        def geometry(self):
            return self.r

        def isVisible(self):
            return self.shown
    # two rows of three 100x100 pads, 10 px apart; one hidden by a filter
    pads = [P(QRect(10 + 110 * (i % 3), 10 + 110 * (i // 3), 100, 100)) for i in range(6)]
    pads.append(P(QRect(0, 0, 1, 1), shown=False))
    g = SimpleNamespace(pads=pads)
    assert PadGrid._drop_target(g, QPoint(50, 50)) == 0          # on a pad
    assert PadGrid._drop_target(g, QPoint(117, 50)) == 1         # gap, nearer pad 1
    assert PadGrid._drop_target(g, QPoint(2, 160)) == 3          # left margin, row 2
    assert PadGrid._drop_target(g, QPoint(200, 400)) == len(pads) - 1   # below: the end


# ---- setup guide
def test_installing_greys_the_guide_buttons_without_disabling_them(qapp):
    stack = QStackedWidget()
    for _ in range(4):
        stack.addWidget(QLabel())
    stack.setCurrentIndex(2)
    went = []
    fake = SimpleNamespace(stack=stack, btn_next=QPushButton(), btn_back=QPushButton(),
                           _proc=object(), PAGES=4, route_ok=lambda: False,
                           go=went.append, finish=lambda: went.append("finish"))
    setupwizard.SetupWizard._update_next(fake)
    assert fake.btn_next.isEnabled() and busy.is_busy(fake.btn_next)
    assert busy.is_busy(fake.btn_back)
    setupwizard.SetupWizard.next_clicked(fake)
    setupwizard.SetupWizard.back_clicked(fake)
    assert went == []                            # Enter on the dialog can't leave either
    fake._proc = None
    setupwizard.SetupWizard._update_next(fake)
    assert not busy.is_busy(fake.btn_next) and not busy.is_busy(fake.btn_back)
    setupwizard.SetupWizard.next_clicked(fake)
    assert went == [3]


def test_steam_guide_escapes_the_mic_name(qapp):
    g = setupwizard.SteamGuide(None, "Mic <b>x</b> & co")
    text = " ".join(lbl.text() for lbl in g.findChildren(QLabel))
    assert "Mic &lt;b&gt;x&lt;/b&gt; &amp; co" in text
    g.deleteLater()


# ---- overlay
def test_overlay_flash_is_cleared_once_over(make, qapp):  # noqa: F811
    ov = make({"close_after_play": False})
    ov.open()
    ov.flash = (0, time.monotonic() - 1)         # a flash that ended
    ov.window.grab()
    assert ov.flash is None
    ov.close()


def test_hovering_the_overlay_pushes_auto_hide_back(make, monkeypatch):  # noqa: F811
    ov = make({"autohide": 2})
    ov.open()
    touched = []
    monkeypatch.setattr(ov, "_touch", lambda: touched.append(1))
    p = QPointF(30, 30)
    ov.window.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p, p, Qt.NoButton, Qt.NoButton,
                                         Qt.NoModifier))
    assert touched
    ov.close()


# ---- theme
def test_recolour_inline_with_tokens_sharing_a_hex(qapp, monkeypatch):
    lbl = QLabel("<span style='color:#111111'>a</span><span style='color:#222222'>b</span>")
    # #111111 was text, muted and faint; the new theme splits them 1 : 2
    old = {"text": "#111111", "muted": "#111111", "faint": "#111111", "accent": "#222222",
           "text_hi": "#222222"}
    monkeypatch.setattr(theme, "T", {"text": "#aaaaaa", "muted": "#bbbbbb",
                                     "faint": "#bbbbbb", "accent": "#cccccc",
                                     "text_hi": "#dddddd"})
    theme._recolour_inline([lbl], old)
    # most tokens agree on #bbbbbb; a 1 : 1 tie goes to the earlier key (text_hi)
    assert "color:#bbbbbb" in lbl.text() and "color:#dddddd" in lbl.text()


# ---- EQ
def test_flat_preset_and_curve_reset_turn_the_eq_off(qapp):
    from soundboard.ui.panel import EQ_PRESETS, EqPanel
    eq = EqPanel(False, "sounds", "Flat (off)", [0.0] * 7)
    other = next(n for n in EQ_PRESETS if n != "Flat (off)")
    seen = []
    eq.changed.connect(lambda *a: seen.append(a[1]))
    eq.cb_preset.setCurrentIndex(eq.cb_preset.findData(other))   # shown without the dash
    assert eq.chk_on.isChecked() and not eq.sliders[0].property("dim")
    eq.cb_preset.setCurrentText("Flat (off)")
    assert not eq.chk_on.isChecked() and seen[-1] is False
    assert eq.sliders[0].property("dim") and eq.cb_target.property("dim")
    eq.chk_on.setChecked(True)                   # on, still flat: double-click resets
    eq.curve.reset.emit()
    assert not eq.chk_on.isChecked() and eq.cb_preset.currentData() == "Flat (off)"
    eq.deleteLater()


def test_dim_has_a_style_rule(qapp):
    assert 'QSlider[dim="true"]' in theme.stylesheet()
