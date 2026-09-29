"""The main window's shell: closed dialogs are freed, the live-tab warning survives
the icons-only tab bar, and status colours are readable on every theme."""
import pytest
from PySide6.QtCore import QEvent

from soundboard import engine, settings, theme, winkeys
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard
from soundboard.ui.livedot import set_tab_live


@pytest.fixture
def win(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(setupwizard, "resume_after_restart", lambda on: None)
    w = main.MainWindow()
    w._load_thread.join(15)
    yield w
    w._quitting = True
    w.close()
    w._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_closed_settings_and_setup_dialogs_are_freed(qapp, win, monkeypatch):
    """Parented to the window and never freed, every closed copy stayed alive and
    each theme change restyled all of them."""
    monkeypatch.setattr(settings.SettingsDialog, "exec", lambda self: 0)
    monkeypatch.setattr(setupwizard.SetupWizard, "exec", lambda self: 0)
    for _ in range(3):
        win.open_settings()
        win.run_setup()
    assert win.findChildren(settings.SettingsDialog) == []
    assert win.findChildren(setupwizard.SetupWizard) == []


def test_a_crash_report_open_over_a_dialog_outlives_it(qapp, win, monkeypatch):
    from soundboard import applog
    from soundboard.ui.crashdialog import CrashDialog
    kept = []

    def exec_(dlg):
        kept.append(CrashDialog(applog.Report(title="E: x", text="t"), None, dlg))
        return 0
    monkeypatch.setattr(settings.SettingsDialog, "exec", exec_)
    win.open_settings()
    assert kept[0].parentWidget() is win
    kept[0].done(0)


def test_live_tab_warning_survives_the_icons_only_tab_bar(qapp, win):
    vi = win.tabs.indexOf(win.voice)
    set_tab_live(win.tabs, vi, True, "● ON: others hear your changed voice", "voice")
    for compact in (True, False):
        win._tab_icons_only(compact)
        tip = win.tabs.tabToolTip(vi)
        assert tip.startswith("● ON"), tip
        assert ("Voice:" in tip) == compact
    set_tab_live(win.tabs, vi, False)
    assert not win.tabs.tabToolTip(vi).startswith("●")   # the right plain tip is back
    other = win.tabs.indexOf(win.setup_page)
    win._tab_icons_only(True)
    assert not win.tabs.tabToolTip(other).startswith("●")


def _contrast(a: str, b: str) -> float:
    def lum(h):
        r, g, b_ = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b_)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_every_theme_is_complete_and_readable(name):
    """Every theme has every colour, and its text, inline ok / warn / error messages
    and accent buttons can be read — the meme ones too. (The light themes get the
    full 4.5:1; the dark ones' red on a button is a shade under that, as Dark always was.)"""
    t = theme.THEMES[name]
    assert set(theme.THEMES["Dark"]) - {"texture"} <= set(t)
    need = 4.5 if theme.is_light(name) else 4.0
    for kind in ("ok", "warn", "error"):
        for bg in ("bg", "panel", "card", "btn"):
            assert _contrast(t[f"{kind}_text"], t[bg]) >= need, (kind, bg)
    for fg, bg in (("text", "bg"), ("text", "card"), ("muted", "panel"),
                   ("on_accent", "accent"), ("danger_text", "danger_bg")):
        assert _contrast(t[fg], t[bg]) >= 3.0, (fg, bg)
    assert t.get("texture", "carbon") in theme.TEXTURE_TILE


def test_every_theme_is_in_one_settings_group():
    grouped = [n for _, names in theme.GROUPS for n in names]
    assert sorted(grouped) == sorted(theme.THEMES)
    assert theme.is_light("Light") and theme.is_light("Flashbang")
    assert not theme.is_light("Dark") and not theme.is_light("Midnight")


@pytest.mark.parametrize("name", [n for n, t in theme.THEMES.items() if t.get("texture")
                                  or t.get("font")])
def test_textured_and_font_themes_build_their_stylesheet(qapp, name):
    css = theme.stylesheet(name)
    font = theme.THEMES[name].get("font", theme.FONT)
    assert f"font-family:'{font}'" in css
    if theme.THEMES[name].get("texture"):
        assert "background-image:url(" in css


def test_setup_tab_uses_the_themes_status_colours(qapp, win):
    win.apply_theme("Light")
    try:
        text = win.flow_mic.text() + win.flow_out.text() + win.step_lbl.text()
        assert "#13ce66" not in text and "#ffb020" not in text and "#ff4d4f" not in text
    finally:
        win.apply_theme("Dark")
