"""Lite mode (ui/lite.py): the setting, and that each thing it turns off really stops."""
import pytest

from PySide6.QtCore import QAbstractAnimation

from conftest import said, unsay
from soundboard import library, theme
from soundboard.settings import SettingsDialog
from soundboard.ui import lite, toast
from test_bunnywidget import _Clock
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


@pytest.fixture(autouse=True)
def lite_off():
    lite.set_on(False)
    yield
    lite.set_on(False)


@pytest.fixture
def win(window):  # noqa: F811
    """The window, its saved settings back to lite mode off afterwards (the next test's
    window loads them)."""
    yield window
    window._save_timer.stop()
    window.cfg.lite_mode = window.cfg.lite_hint_done = False
    window.cfg.theme_texture = True
    window.cfg.save()


# ------------------------------------------------------------------ the setting

def test_off_by_default_and_old_settings_load_without_it():
    assert library.Config().lite_mode is False
    old = library.Config.from_raw({"version": 1, "theme": "Dark"})   # (an old file)
    assert old.lite_mode is False and old.lite_hint_done is False
    assert library.Config.from_raw({"lite_mode": True}).lite_mode is True
    assert library.Config.from_raw({"lite_mode": "yes"}).lite_mode is False   # (hand-edited)


def test_it_stays_on_this_pc_in_a_settings_export():
    from soundboard import backup
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
    assert lite.rest_s(0.5) == 0.5


def test_slow_pc():
    assert lite.slow_pc(cores=4, ram=32.0)
    assert lite.slow_pc(cores=16, ram=4.0)
    assert not lite.slow_pc(cores=16, ram=32.0)
    assert lite.ram_gb() is None or lite.ram_gb() > 0


# ------------------------------------------------------------------ Settings

def test_settings_switch_applies_at_once_and_keeps_textured(win, qapp):
    window = win
    window.themectl.apply_theme("Amber Terminal")
    assert window.cfg.theme_texture and theme.textures_on
    d = SettingsDialog(window, "appearance")
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


def test_a_slower_pc_is_told_once_and_never_switched_on_by_itself(win, monkeypatch):
    window = win
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


def test_a_fast_pc_is_not_told(win, monkeypatch):
    window = win
    monkeypatch.setattr(lite, "slow_pc", lambda: False)
    window.cfg.setup_done = True
    window.cfg.lite_hint_done = False
    unsay(window)
    window.themectl.suggest_lite()
    assert "Lite mode" not in said(window) and not window.cfg.lite_hint_done


# ------------------------------------------------------------------ what stops

def test_the_logo_holds_still(qapp, monkeypatch):
    from soundboard.ui import logowidget
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
    from soundboard.ui import bunnywidget as bw
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
    b.stir()   # a sound or a click still moves him...
    assert not b.resting and b._timer.isActive()
    _run(b, 10)
    assert b.resting   # ...then he settles again
    lite.set_on(False)
    b.lite_changed()   # lite off: back to moving
    assert not b.resting and b._timer.isActive()
    b.close()


def test_pad_hover_has_no_fade(qapp):
    from soundboard.library import SoundMeta
    from soundboard.ui.widgets import Pad
    pad = Pad(SoundMeta(id="a", name="a", file="a.wav"), 150)
    lite.set_on(True)
    pad._fade_hover(True)
    assert pad._hover_k == 1.0
    assert pad._hover_anim.state() != QAbstractAnimation.State.Running
    pad._fade_hover(False)
    assert pad._hover_k == 0.0


def test_mic_banner_does_not_pulse(qapp):
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget
    from soundboard.ui.windowbuild import Pulse
    host = QWidget()
    fx = QGraphicsOpacityEffect(host)
    p = Pulse(fx, host)
    lite.set_on(True)
    p.set_on(True)
    assert not p.running()
    lite.set_on(False)
    p.set_live(True)
    assert p.running()
    p.set_on(False)


def test_the_theme_cover_does_not_fade(qapp):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget
    from soundboard.style import cover
    from soundboard.ui import themecover  # noqa: F401  (plugs lite mode in)
    lite.set_on(True)
    assert not cover.animate()
    host = QWidget()
    host.resize(200, 100)
    host.show()   # (as the window is: the cover is made hidden, then put up)
    c = cover.Cover(host, QColor("#000"))
    cover._fade_in([c])
    assert c.k == 1.0   # (dimmed at once)
    c.uncover()
    assert c._fade is None
    host.close()
    lite.set_on(False)
    assert cover.animate()


def test_overlay_shows_and_goes_at_once(qapp):
    from soundboard.ui import overlay
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
    from soundboard.ui.bunnywidget import BunnyWidget
    host = QWidget()
    b = BunnyWidget(height=60, pad=6, parent=host)
    host.deleteLater()   # (his page closed: Qt frees him, the wrapper stays in `alive`)
    qapp.sendPostedEvents(None, 0)
    lite.set_on(True)
    BunnyWidget.lite_changed()   # no "already deleted"
    lite.set_on(False)
    BunnyWidget.lite_changed()
    del b
