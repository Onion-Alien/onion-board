"""Lite mode (ui/settings/lite.py): the setting, and that each thing it turns off really stops."""
import pytest

from PySide6.QtCore import QAbstractAnimation

from conftest import said, unsay
from soundboard.ui.kit import appstate
from soundboard.sounds import library
from soundboard.ui.kit import theme
from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.settings import lite
from soundboard.ui.kit import toast
from test_bunnywidget import _Clock
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


@pytest.fixture(autouse=True)
def lite_off():
    lite.set_on(False)
    yield
    lite.set_on(False)


# ------------------------------------------------------------------ the setting

def test_off_by_default_and_old_settings_load_without_it():
    assert library.Config().lite_mode is False
    old = library.Config.from_raw({"version": 1, "theme": "Dark"})   # (an old file)
    assert old.lite_mode is False and old.lite_hint_done is False
    assert library.Config.from_raw({"lite_mode": True}).lite_mode is True
    assert library.Config.from_raw({"lite_mode": "yes"}).lite_mode is False   # (hand-edited)


def test_it_stays_on_this_pc_in_a_settings_export():
    from soundboard.core import backup
    assert {"lite_mode", "lite_hint_done"} <= backup.LOCAL_SETTINGS


def test_animations_on_follows_it(monkeypatch):
    monkeypatch.setattr(toast, "ANIMATE", True)
    assert toast.animations_on()
    lite.set_on(True)
    assert not toast.animations_on()   # (lite wins, even over a forced on)


def test_rest_s():
    assert lite.rest_s(None) is None and lite.rest_s(30.0) == 30.0
    lite.set_on(True)
    assert lite.rest_s(None) == lite.REST_S and lite.rest_s(30.0) == lite.REST_S
    assert lite.rest_s(0.5) == lite.REST_S == 0.0   # (a still picture)


def test_slow_pc():
    assert lite.slow_pc(cores=4, ram=32.0)
    assert lite.slow_pc(cores=16, ram=4.0)
    assert not lite.slow_pc(cores=16, ram=32.0)
    assert lite.ram_gb() is None or lite.ram_gb() > 0


# ------------------------------------------------------------------ Settings

def test_settings_switch_applies_at_once_and_keeps_textured(window, qapp):  # noqa: F811
    window.themectl.apply_theme("Amber Terminal")
    assert window.cfg.theme_texture and theme.textures_on
    d = SettingsDialog(window, "general")
    assert not d.lite_check.isChecked()
    d.lite_check.click()
    assert window.cfg.lite_mode is True and lite.on()
    assert not theme.textures_on and "/tex-" not in qapp.styleSheet()
    assert window.cfg.theme_texture is True   # (Textured is kept for later)
    assert not window.logo._timer.isActive()
    d.texture_off.click()   # picking Theme style meanwhile: saved, still Plain
    assert window.cfg.theme_texture is False and not theme.textures_on
    d.texture_on.click()
    assert window.cfg.theme_texture is True and not theme.textures_on
    d.lite_check.click()
    assert window.cfg.lite_mode is False and not lite.on()
    assert theme.textures_on and "/tex-" in qapp.styleSheet()
    d.close()


def test_a_slower_pc_is_told_once_and_never_switched_on_by_itself(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(lite, "slow_pc", lambda: True)
    window.cfg.setup_done = True
    window.cfg.lite_mode = window.cfg.lite_hint_done = False
    unsay(window)
    window.themectl.suggest_lite()
    assert "Lite mode" in said(window) and window.cfg.lite_hint_done
    assert not window.cfg.lite_mode and not lite.on()
    card = next(t for t in toast.shown(window) if "Lite mode" in t.text())
    unsay(window)
    window.themectl.suggest_lite()   # (once only)
    assert "Lite mode" not in said(window)
    card._act()   # its Turn on
    assert window.cfg.lite_mode and lite.on()


def test_a_fast_pc_is_not_told(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(lite, "slow_pc", lambda: False)
    window.cfg.setup_done = True
    window.cfg.lite_hint_done = False
    unsay(window)
    window.themectl.suggest_lite()
    assert "Lite mode" not in said(window) and not window.cfg.lite_hint_done


# ------------------------------------------------------------------ what stops

def test_the_logo_holds_still(qapp, monkeypatch):
    from soundboard.ui.bun import logowidget
    monkeypatch.setattr(logowidget.appstate, "active", lambda: True)
    w = logowidget.LogoWidget()
    w.show()
    qapp.processEvents()
    assert w._timer.isActive()
    lite.set_on(True)
    w.lite_changed()
    assert not w._timer.isActive() and not w.embers
    w._resume()   # (what a click or coming back to the front calls)
    assert not w._timer.isActive()
    assert not w.grab().isNull()   # (painting still works: a still glow)
    lite.set_on(False)
    w.lite_changed()
    assert w._timer.isActive()
    w.close()


def _bun(qapp, monkeypatch, **kw):
    from soundboard.ui.bun import bunnywidget as bw
    clock = _Clock()
    monkeypatch.setattr(bw, "time", clock)
    monkeypatch.setattr(bw, "local_hour", lambda: 12)
    monkeypatch.setattr(bw.appstate, "active", lambda: True)
    b = bw.BunnyWidget(height=80, pad=10, **kw)
    b.clock = clock
    b.resize(b.sizeHint())
    b.show()
    qapp.processEvents()
    return b


def _run(b, secs):
    for _ in range(round(secs / 0.035)):
        if b.resting:
            return
        b.clock.now += 0.035
        b._last = b.clock.now - 0.035
        b._step()


def test_bun_who_never_rests_holds_still_in_lite_mode(qapp, monkeypatch):
    b = _bun(qapp, monkeypatch)   # (no rest_after_s: moves forever normally)
    _run(b, 8)
    assert not b.resting
    lite.set_on(True)
    b.lite_changed()
    _run(b, 10)
    assert b.resting and not b._timer.isActive()
    b.set_level(1.0)   # the mic and a sound don't move him...
    b.set_groove(object())
    assert b.resting and not b._timer.isActive() and b.groove is None
    b.stir()   # ...a click still does...
    _run(b, 10)
    assert b.resting   # ...then he settles again
    lite.set_on(False)
    b.lite_changed()   # lite off: back to moving
    assert not b.resting and b._timer.isActive()
    b.close()


def test_pad_hover_has_no_fade(qapp):
    from soundboard.sounds.library import SoundMeta
    from soundboard.ui.kit.widgets import Pad
    pad = Pad(SoundMeta(id="a", name="a", file="a.wav"), 150)
    lite.set_on(True)
    pad._fade_hover(True)
    assert pad._hover_k == 1.0
    assert pad._hover_anim.state() != QAbstractAnimation.State.Running
    pad._fade_hover(False)
    assert pad._hover_k == 0.0


def test_the_theme_cover_does_not_fade(qapp):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget
    from soundboard.style import cover
    from soundboard.ui.window import themecover  # noqa: F401  (plugs lite mode in)
    lite.set_on(True)
    assert not cover.animate()
    host = QWidget()
    host.resize(200, 100)
    host.show()   # (as the window is: the cover is made hidden, then put up)
    c = cover.Cover(host, QColor("#000"))
    cover._fade_in([c])
    assert c.k == 1.0   # (dimmed at once)
    c.uncover()
    assert c._fade is None and not c.isVisible()   # (gone at once)
    host.close()
    lite.set_on(False)
    assert cover.animate()


def test_overlay_shows_and_goes_at_once(qapp):
    from soundboard.ui.sounds import overlay
    from types import SimpleNamespace
    win = overlay.OverlayWindow(SimpleNamespace(s=SimpleNamespace(scale=100)))
    lite.set_on(True)
    win.show()
    win._animate(1.0, 120)
    assert win.windowOpacity() == pytest.approx(1.0)
    assert win._fade.state() != QAbstractAnimation.State.Running
    win._animate(0.0, 140)
    assert not win.isVisible()
    assert win._fade.state() != QAbstractAnimation.State.Running
    win.deleteLater()


def test_switching_skips_a_bun_qt_already_freed(qapp):
    from PySide6.QtWidgets import QWidget
    from soundboard.ui.bun.bunnywidget import BunnyWidget
    host = QWidget()
    b = BunnyWidget(height=60, pad=6, parent=host)
    host.deleteLater()   # (his page closed: Qt frees him, the wrapper stays in `alive`)
    qapp.sendPostedEvents(None, 0)
    lite.set_on(True)
    BunnyWidget.lite_changed()   # no "already deleted"
    lite.set_on(False)
    BunnyWidget.lite_changed()
    del b


# ------------------------------------------------------------------ Use less CPU (voice)

def test_use_less_cpu_is_auto_by_default_and_stays_on_this_pc():
    from soundboard.core import backup
    assert library.Config().light_voice == "auto"
    assert library.Config.from_raw({"light_voice": "on"}).light_voice == "on"
    assert library.Config.from_raw({"light_voice": "maybe"}).light_voice == "auto"
    assert "light_voice" in backup.LOCAL_SETTINGS


def test_use_less_cpu_follows_lite_mode_until_switched_by_hand(window):  # noqa: F811
    from soundboard import voicefx
    try:
        box = window.voice.chk_light   # on the Voice tab itself, for every voice
        assert not window.voice.fx.isAncestorOf(box)
        assert not voicefx.light() and not box.isChecked()
        window.themectl.set_lite_mode(True)
        assert voicefx.light() and box.isChecked()
        box.setChecked(False)          # by hand: kept, whatever lite mode does
        assert window.cfg.light_voice == "off" and not voicefx.light()
        window.themectl.set_lite_mode(False)
        window.themectl.set_lite_mode(True)
        assert not voicefx.light() and not box.isChecked()
        box.setChecked(True)
        window.themectl.set_lite_mode(False)
        assert window.cfg.light_voice == "on" and voicefx.light()
    finally:
        voicefx.set_light(False)


def test_the_mic_alone_keeps_the_tick_quiet_in_lite_mode(window, monkeypatch):  # noqa: F811
    """Most mics hear the room above the meters' floor: that kept the window's tick at
    full pace for as long as it was open. Now the room's level ticks at the quiet pace
    and only a voice gets the full pace; in lite mode the mic meters follow at the lite
    quiet pace (5 a second) even then, and a sound playing gets lite's busy pace (15 a
    second, not 24)."""
    from soundboard.ui.window import tickcontrol
    e = window.engine
    playing = {}
    monkeypatch.setattr(e, "playing", lambda: dict(playing))
    monkeypatch.setattr(appstate, "active", lambda: True)
    monkeypatch.setattr(window, "isVisible", lambda: True)
    monkeypatch.setattr(e, "mic_stream", object())
    window._ui_live = True

    def tick_with_room_noise():
        e.level_play = 0.0
        e.level_mic = e.level_main = 0.01   # -40 dB: a quiet room, nobody talking
        window.tickctl.tick()
        return window.timer.interval()

    assert tick_with_room_noise() == tickcontrol.TICK_QUIET_MS      # lite mode off
    e.level_mic = e.level_main = 0.1                                 # -20 dB: someone talking
    window.tickctl.tick()
    assert window.timer.interval() == tickcontrol.TICK_MS
    lite.set_on(True)
    e.level_mic = e.level_main = 0.1                                 # (lite: not even a voice)
    window.tickctl.tick()
    assert window.timer.interval() == tickcontrol.TICK_LITE_QUIET_MS
    assert tick_with_room_noise() == tickcontrol.TICK_LITE_QUIET_MS  # 5 a second
    assert window.mic_meter.level == pytest.approx(0.01)             # (still followed)
    playing["s0"] = (0.5, False)                                     # a sound plays
    assert tick_with_room_noise() == tickcontrol.TICK_LITE_MS
    playing.clear()
    e.level_play = 0.5                                               # ...its tail
    window.tickctl.tick()
    assert window.timer.interval() == tickcontrol.TICK_LITE_MS
    lite.set_on(False)
    assert tick_with_room_noise() == tickcontrol.TICK_QUIET_MS
    assert tickcontrol.TICK_LITE_QUIET_MS > tickcontrol.TICK_QUIET_MS
    assert tickcontrol.TICK_LITE_MS > tickcontrol.TICK_MS


def test_the_audio_runs_in_bigger_blocks_in_lite_mode(window, monkeypatch):  # noqa: F811
    """Lite mode: every stream reopens with 20 ms blocks (half the audio callbacks), and
    back to the driver's own when it's switched off."""
    from conftest import devices_done
    from soundboard.audio.engineparts import LITE_BLOCK_S
    w = window
    devices_done(w)
    reopened = []
    monkeypatch.setattr(w.engine, "reopen_all", lambda: reopened.append(w.engine.block_s))
    assert w.engine.block_s == 0.0
    w.themectl.set_lite_mode(True)
    devices_done(w)
    assert reopened == [LITE_BLOCK_S] and w.engine.ring_main.est_scale == 2.0
    w.themectl.set_lite_mode(False)
    devices_done(w)
    assert reopened == [LITE_BLOCK_S, 0.0] and w.engine.ring_main.est_scale == 1.0


def test_on_air_card_says_lite_mode(window):  # noqa: F811
    assert not any(line.words == "Lite mode" for line in window.netctl.card_lines())
    window.themectl.set_lite_mode(True)
    line = next(line for line in window.netctl.card_lines() if line.words == "Lite mode")
    assert line.icon == "leaf" and line.page == "general"
    window.themectl.set_lite_mode(False)
    assert not any(line.words == "Lite mode" for line in window.netctl.card_lines())


def test_hoot_holds_still_and_ignores_the_mouse_and_music(qapp, monkeypatch):
    from soundboard.style import owl
    monkeypatch.setattr(owl.appstate, "active", lambda: True)
    lite.set_on(True)
    h = owl.OwlWidget(80)   # (no rest_after_s: moves forever normally)
    h.show()
    qapp.processEvents()
    for _ in range(200):
        if h.resting:
            break
        h._tick()
    assert h.resting and not h._timer.isActive()
    h.set_groove(object())
    h._peek_mouse()
    assert h.groove is None and h.resting
    h.close()


def test_the_download_scroll_is_a_still_picture(qapp):
    from soundboard.ui.bun.scribebun import ScribeBunny
    lite.set_on(True)
    s = ScribeBunny()
    s.show()
    s.set_progress(0.5)
    assert not s._timer.isActive() and s._shown_prog == 0.5
    assert not s.grab().isNull()
    s.close()
