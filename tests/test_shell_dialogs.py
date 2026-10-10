"""The main window's shell: closed dialogs are freed, the live-tab warning survives
the icons-only tab bar, and status colours are readable on every theme."""
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt

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


def test_live_tab_warning_shows_on_the_rail(qapp, win):
    vi = win.tabs.indexOf(win.voice)
    b = win.rail.buttons[vi]
    plain = b.icon().cacheKey()
    set_tab_live(win.tabs, vi, True, "● ON: others hear your changed voice", "voice")
    for is_open in (False, True):   # no hover tips on the tabs: it's for a screen reader
        win.rail.set_open(is_open)
        assert b.toolTip() == "" and b.accessibleDescription().startswith("● ON")
    assert b.icon().cacheKey() != plain   # the live icon came across
    set_tab_live(win.tabs, vi, False)
    assert not b.accessibleDescription().startswith("●")
    win.rail.set_open(False)
    setup = win.rail.buttons[win.tabs.indexOf(win.setup_page)]
    assert not setup.accessibleDescription().startswith("●")


def test_the_rail_keeps_up_with_the_tabs(qapp, win, monkeypatch):
    """Everything that changed a tab on the old top bar shows on the rail: a theme or
    highlight colour change, a tab switched off / on / swapped, offline mode, Ctrl+Tab."""
    from PySide6.QtTest import QTest
    from soundboard import net
    tabs, rail = win.tabs, win.rail
    win.show()

    def same(why):
        for b in rail.buttons:
            i = b.index
            assert b.isVisibleTo(rail) == tabs.isTabVisible(i), (why, i)
            assert b.icon().cacheKey() == tabs.tabBar().tabIcon(i).cacheKey(), (why, i)
            assert b.isChecked() == (i == tabs.currentIndex()), (why, i)
            assert b.accessibleName() == tabs.tabText(i).replace("&&", "&"), (why, i)

    vi = tabs.indexOf(win.voice)
    win.set_tab_on("voice", True)
    set_tab_live(tabs, vi, True, "● ON", "voice")
    same("start")
    try:
        win.apply_theme("Light")
        same("theme")
        win.set_live_color("#3399ff")
        same("highlight colour")
        set_tab_live(tabs, vi, False)
        win.set_tab_on("radio", True)
        tabs.setCurrentIndex(main.TAB_INDEX["radio"])
        win.set_tab_on("radio", False)
        same("current tab switched off")
        win.set_tab_on("radio", True)
        win.set_tab_on("voice", False)
        win.set_tab_on("voice", True)
        same("tab swapped")
        monkeypatch.setattr(net, "offline", lambda: True)
        win._offline_follow()
        same("offline")
        monkeypatch.setattr(net, "offline", lambda: False)
        win._offline_follow()
        tabs.setCurrentIndex(0)
        QTest.keyClick(tabs, Qt.Key_Tab, Qt.ControlModifier)
        assert tabs.currentIndex() != 0
        same("Ctrl+Tab")
        shown = [b for b in rail.buttons if b.isVisible()]
        shown[0].click()
        QTest.keyClick(shown[0], Qt.Key_Down)   # the arrows, as on the old bar
        assert tabs.currentIndex() == shown[1].index and win.focusWidget() is shown[1]
        QTest.keyClick(shown[1], Qt.Key_Up)     # onto Sounds: the focus stays on the rail
        assert win.focusWidget() is shown[0]
        QTest.keyClick(shown[0], Qt.Key_Up)     # round to the last one
        assert tabs.currentIndex() == shown[-1].index
        same("arrows")
        asked = []   # right-click: that tab's own menu (Hide this tab), as on the old bar

        class Menu:
            def exec(self, _pos):
                pass
        monkeypatch.setattr(win, "tab_menu", lambda i: asked.append(i) or Menu())
        for b in shown:
            b.customContextMenuRequested.emit(QPoint(5, 5))
        assert asked == [b.index for b in shown]
    finally:
        win.set_live_color("")
        win.apply_theme("Dark")


def test_the_rail_mirrors_right_to_left(qapp, win):
    """Arabic: the rail on the right, its live bar and border on its outer / inner edge,
    and the narrow window's tight gap beside it."""
    from PySide6.QtGui import QColor
    vi = win.tabs.indexOf(win.voice)
    win.tabs.setTabVisible(vi, True)
    set_tab_live(win.tabs, vi, True, "● ON", "voice")
    win.resize(1000, 700)
    win.show()
    rail, b = win.rail, win.rail.buttons[vi]

    def bar_at():   # which edge the live bar is painted on
        img, y = rail.grab().toImage(), b.geometry().center().y()
        live = QColor(theme.T["live_text"]).name()
        return [x for x in (0, rail.width() - 1) if QColor(img.pixel(x, y)).name() == live]

    try:
        assert bar_at() == [0]
        qapp.setLayoutDirection(Qt.RightToLeft)
        qapp.processEvents()
        assert rail.property("rtl") is True
        assert rail.mapTo(win, QPoint(0, 0)).x() + rail.width() == win.width()
        assert bar_at() == [rail.width() - 1]
        win._squeeze_rail(True)
        m = win._body_lay.contentsMargins()
        assert (m.left(), m.right()) == (main.BODY_SIDE, main.BODY_SIDE_TIGHT)
        win._squeeze_rail(False)
    finally:
        qapp.setLayoutDirection(Qt.LeftToRight)
        set_tab_live(win.tabs, vi, False)
    qapp.processEvents()
    assert rail.property("rtl") is False


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
                   ("on_accent", "accent"), ("danger_text", "danger_bg"),
                   ("section", "panel"), ("on_accent", "accent_hi"),
                   ("accent_hi", "panel")):   # the radio's playing station / Clear link
        assert _contrast(t[fg], t[bg]) >= 3.0, (fg, bg)
    # the selected row of every dropdown, checked buttons, primary buttons
    assert _contrast(t["on_accent"], t["accent"]) >= 4.3
    assert t.get("texture", "carbon") in theme.TEXTURE_TILE


@pytest.mark.parametrize("box", ["card", "setcard", "stations", ""])
def test_popups_inside_cards_keep_the_themes_background(qapp, box):
    """A dropdown list or menu is a child of the widget that opens it, so a card's
    "QWidget { background:transparent }" used to reach it and the popup drew black --
    unreadable on every light theme."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QComboBox, QFrame, QMenu, QVBoxLayout

    from soundboard.ui.radiopanel import RadioTab
    try:
        for name in theme.THEMES:
            theme.apply(qapp, name)
            f = QFrame()
            f.setObjectName(box)
            if box == "stations":
                f.setStyleSheet(RadioTab._PANEL_STYLE.substitute(theme.T))
            cb = QComboBox()
            cb.addItems(["Off", "Discord", "Vivox"])
            QVBoxLayout(f).addWidget(cb)
            f.show()
            cb.showPopup()
            menu = QMenu(cb)
            menu.addAction("Item")
            menu.popup(f.mapToGlobal(f.rect().center()))
            qapp.processEvents()
            want = QColor(theme.T["card"])
            pop = cb.view().window().grab().toImage()
            vp = cb.view().viewport()
            for img, x, y in ((pop, pop.width() - 3, pop.height() - 3),
                              (vp.grab().toImage(), 3, vp.height() - 3),
                              (menu.grab().toImage(), menu.width() // 2, menu.height() - 3)):
                got = QColor(img.pixel(x, y))
                diff = sum(abs(a - b) for a, b in zip(got.getRgb()[:3], want.getRgb()[:3]))
                assert diff < 30, (name, got.name(), want.name())
            menu.close()
            cb.hidePopup()
            f.close()
            f.deleteLater()
    finally:
        theme.apply(qapp, theme.DEFAULT)


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


def test_clicking_the_theme_already_on_does_nothing(qapp, win, monkeypatch):
    """Restyling every widget for the same theme froze the app: a click that only
    ticks its card again."""
    win.apply_theme("Dark")
    d = settings.SettingsDialog(win, "appearance")
    calls = []
    monkeypatch.setattr(win, "apply_theme", calls.append)
    card = next(c for c in d.theme_cards if c.name == "Dark")
    card.click()   # a checkable card: this unticks it
    assert calls == [] and card.isChecked()
    other = next(c for c in d.theme_cards if c.name != "Dark")
    other.click()
    assert calls == [other.name]
    d.close()


def test_a_live_theme_switch_leaves_no_old_text_colours(qapp, win):
    """Colours written into a label's text or a widget's own stylesheet when it was
    built (a warning, a red error, the over-100% volume) follow a live theme switch,
    not only a restart."""
    from PySide6.QtWidgets import QLabel

    win.apply_theme("Dark")
    red, amber = theme.status("error"), theme.status("warn")
    lbl = QLabel(f"<span style='color:{red}'>Oops</span>", win)
    lbl.setStyleSheet(f"color:{amber}; background:{red};")
    win.apply_theme("Mint")
    try:
        assert theme.status("error") in lbl.text() and red not in lbl.text()
        assert lbl.styleSheet() == f"color:{theme.status('warn')}; background:{red};"
        old = {theme.THEMES["Dark"][k].lower() for k in ("ok_text", "warn_text", "error_text")}
        for w in qapp.allWidgets():
            text = w.text() if isinstance(w, QLabel) else ""
            for c in old:
                assert f"color:{c}" not in (text + w.styleSheet()).lower(), (w, c)
    finally:
        win.apply_theme("Dark")
