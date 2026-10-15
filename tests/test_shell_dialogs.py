"""The main window's shell: closed dialogs are freed, the live-tab warning survives
the icons-only tab bar, and status colours are readable on every theme."""
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest

from soundboard import engine, settings, theme, winkeys
from soundboard.ui import fitcontrol, settingscontrol, setupwizard
from soundboard.ui import mainwindow as main
from soundboard.ui.livedot import set_tab_live
from soundboard.ui.tabcontrol import TAB_INDEX


@pytest.fixture
def win(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(setupwizard, "resume_after_restart", lambda on: None)
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    yield w
    w._quitting = True
    w.close()
    w.soundctl._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_closed_settings_and_setup_dialogs_are_freed(qapp, win, monkeypatch):
    """Parented to the window and never freed, every closed copy stayed alive and
    each theme change restyled all of them."""
    monkeypatch.setattr(setupwizard.SetupWizard, "exec", lambda self: 0)
    for _ in range(3):
        win.setctl.open_settings().done(0)   # Settings, a page in the window: Done closes it
        qapp.processEvents()          # (freed just after its finished signal)
        win.run_setup()
    # (one closed Settings is kept to open again quickly: never one per opening)
    assert len(win.findChildren(settings.SettingsDialog)) <= 1
    assert win.findChildren(setupwizard.SetupWizard) == []


def test_settings_opened_again_is_the_kept_one_unless_its_config_changed(qapp, win):
    """Building Settings took 100-300 ms on every click of the cog: closed, it's kept,
    and opened again as it was. Config it shows changed meanwhile: built fresh."""
    d = win.setctl.open_settings("audio")
    d.accept()
    qapp.processEvents()
    assert win.setctl._settings_dlg is None and not win.setctl.settings_open()
    again = win.setctl.open_settings("appearance")
    assert again is d and win.setctl.settings_open()
    assert d._page_keys[d.tabs.currentIndex()] == "appearance"
    again.accept()
    qapp.processEvents()
    win.cfg.always_on_top = not win.cfg.always_on_top   # changed outside Settings
    fresh = win.setctl.open_settings("general")
    assert fresh is not d and win.setctl.settings_open()
    fresh.accept()
    qapp.processEvents()
    d2 = win.setctl.open_settings("updates")   # shows live state: never kept
    d2.accept()
    qapp.processEvents()
    assert win.setctl.open_settings() is not d2


def test_settings_open_as_a_page_in_place_of_the_tabs(qapp, win):
    """Settings apply as they change, so they don't hold up the board: a page in
    the window where the tabs show, the rail still there with its cog selected. Asked
    for again: the same page, switched to the page named."""
    win.resize(1180, 720)
    win.show()
    win.tabs.setCurrentWidget(win.radio_page)
    d = win.setctl.open_settings("audio")
    assert win.setctl.settings_open() and not d.isWindow() and d.isVisible()
    assert win._content.currentWidget() is d and not win._tabs_area.isVisible()
    assert win.rail.isVisible() and win.mixer.isVisible()
    assert win.gear.isChecked() and not any(b.isChecked() for b in win.rail.buttons)
    assert win.isEnabled() and qapp.activeModalWidget() is None
    assert win.setctl.open_settings("hotkeys") is d
    assert d._page_keys[d.tabs.currentIndex()] == "hotkeys"
    assert win.setctl.open_settings() is d                          # the cog: stays on its page
    assert d._page_keys[d.tabs.currentIndex()] == "hotkeys"
    d.search_box.setText("zzzz-nothing")
    d._apply_search("zzzz-nothing")
    win.setctl.open_settings("audio")                        # a page asked for: search cleared
    assert d.search_box.text() == "" and d._page_keys[d.tabs.currentIndex()] == "audio"
    assert d.back_btn.accessibleName() == "Back"   # no Done row: a back arrow
    assert d.back_btn.toolTip() == ""   # the arrow says it
    d.back_btn.click()                                       # back to the tab you were on
    qapp.processEvents()
    assert not win.setctl.settings_open() and win.setctl._settings_dlg is None
    assert win._tabs_area.isVisible() and win.tabs.currentWidget() is win.radio_page
    assert not win.gear.isChecked()
    assert win.rail.buttons[win.tabs.indexOf(win.radio_page)].isChecked()
    assert win.findChildren(settings.SettingsDialog) == []
    again = win.setctl.open_settings()                              # a new one after closing
    assert again.isVisible()
    again.done(0)
    qapp.processEvents()


def test_escape_and_any_rail_tab_leave_settings(qapp, win):
    win.resize(1180, 720)
    win.show()
    win.tabs.setCurrentWidget(win.sounds_page)
    d = win.setctl.open_settings("appearance")
    assert d.isAncestorOf(win.focusWidget())                 # so Escape reaches it
    QTest.keyClick(win.focusWidget(), Qt.Key_Escape)         # Escape = Done
    qapp.processEvents()
    assert not win.setctl.settings_open() and win.tabs.currentWidget() is win.sounds_page
    sounds = win.rail.buttons[win.tabs.indexOf(win.sounds_page)]
    win.setctl.open_settings()
    sounds.click()                                           # the tab you were on
    qapp.processEvents()
    assert not win.setctl.settings_open() and sounds.isChecked() and not win.gear.isChecked()
    win.setctl.open_settings()
    setup = win.rail.buttons[win.tabs.indexOf(win.setup_page)]
    setup.click()                                            # another tab: that one
    qapp.processEvents()
    assert not win.setctl.settings_open() and win.tabs.currentWidget() is win.setup_page
    win.setctl.open_settings()
    win.tabctl._go_tab(0, absolute=True)                            # Ctrl+1
    qapp.processEvents()
    assert not win.setctl.settings_open()


def test_switching_the_open_tab_off_in_settings_keeps_settings_up(qapp, win):
    """Settings > Tabs switching off the tab underneath moves the tabs to the first,
    and Settings stays where it is."""
    win.tabctl.set_tab_on("voice", True)
    win.tabs.setCurrentWidget(win.voice)
    d = win.setctl.open_settings("tabs")
    win.tabctl.set_tab_on("voice", False)
    qapp.processEvents()
    assert win.setctl.settings_open() and win.setctl._settings_dlg is d
    assert win.tabs.currentIndex() == 0
    d.done(0)
    qapp.processEvents()


@pytest.mark.parametrize("width", [440, 800, 1180, 1920])
def test_the_settings_page_fits_every_width(qapp, win, width):
    """440 to 1920 wide with no sideways scroll: narrow, the categories go to an icon
    column (their names as tips) and the search box over the page."""
    win.show()
    win.resize(width, 720)
    d = win.setctl.open_settings("appearance")
    for _ in range(3):
        qapp.processEvents()
    assert win.width() <= max(width, win.minimumWidth()) and win.minimumWidth() <= 440
    assert d.geometry().right() <= win._content.width()
    narrow = d.width() < d.NARROW_W
    item = d.categories.item(0)
    assert (item.text() == "") == narrow
    assert item.toolTip() == ("Audio" if narrow else "")
    assert d.categories.width() == (48 if narrow else 196)
    page = d.tabs.currentWidget()
    from PySide6.QtGui import QFontDatabase
    if "Segoe UI" in QFontDatabase.families():   # (offscreen without its fonts: wide boxes)
        assert page.widget().width() <= page.viewport().width()   # nothing cut off
    d.done(0)
    qapp.processEvents()


def test_too_small_closes_settings_and_the_mini_player_grows_for_them(qapp, win):
    """Made too small for Settings: they close and the mini player shows. Asked for
    from the mini player: the window grows to the smallest size that shows them."""
    win.show()
    win.resize(800, 600)
    win.setctl.open_settings("appearance")
    qapp.processEvents()
    win.resize(320, 300)
    qapp.processEvents()
    assert not win.setctl.settings_open() and win.fitctl.is_mini()
    assert win.setctl._settings_dlg is None
    d = win.setctl.open_settings("audio")
    qapp.processEvents()
    assert win.setctl.settings_open() and not win.fitctl.is_mini() and d.isVisible()
    size = win._pages.size()
    assert size.width() >= settingscontrol.SETTINGS_ROOM.width() - 1
    assert size.height() >= min(settingscontrol.SETTINGS_ROOM.height(),
                                win.screen().availableGeometry().height() - 40)
    d.done(0)
    qapp.processEvents()
    assert not win.setctl.settings_open()


def test_a_crash_report_open_over_a_dialog_outlives_it(qapp, win):
    from soundboard import applog
    from soundboard.ui.crashdialog import CrashDialog
    dlg = win.setctl.open_settings()
    kept = CrashDialog(applog.Report(title="E: x", text="t"), None, dlg)
    dlg.done(0)
    qapp.processEvents()
    assert kept.parentWidget() is win
    kept.done(0)


def test_live_tab_warning_shows_on_the_rail(qapp, win):
    vi = win.tabs.indexOf(win.voice)
    b = win.rail.buttons[vi]
    plain = b.icon().cacheKey()
    set_tab_live(win.tabs, vi, True, "● ON: others hear your changed voice", "voice")
    for is_open in (False, True):   # the "● ON" line is for a screen reader, never a tip
        win.rail.set_open(is_open)
        assert "ON" not in b.toolTip() and b.accessibleDescription().startswith("● ON")
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
    win.tabctl.set_tab_on("voice", True)
    set_tab_live(tabs, vi, True, "● ON", "voice")
    same("start")
    try:
        win.themectl.apply_theme("Light")
        same("theme")
        win.themectl.set_live_color("#3399ff")
        same("highlight colour")
        set_tab_live(tabs, vi, False)
        win.tabctl.set_tab_on("radio", True)
        tabs.setCurrentIndex(TAB_INDEX["radio"])
        win.tabctl.set_tab_on("radio", False)
        same("current tab switched off")
        win.tabctl.set_tab_on("radio", True)
        win.tabctl.set_tab_on("voice", False)
        win.tabctl.set_tab_on("voice", True)
        same("tab swapped")
        monkeypatch.setattr(net, "offline", lambda: True)
        win.netctl._offline_follow()
        same("offline")
        monkeypatch.setattr(net, "offline", lambda: False)
        win.netctl._offline_follow()
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
        monkeypatch.setattr(win.tabctl, "tab_menu", lambda i: asked.append(i) or Menu())
        for b in shown:
            b.customContextMenuRequested.emit(QPoint(5, 5))
        assert asked == [b.index for b in shown]
    finally:
        win.themectl.set_live_color("")
        win.themectl.apply_theme("Dark")


@pytest.mark.parametrize("green", [False, True])
def test_the_rail_mirrors_right_to_left(qapp, win, green):
    """Arabic: the rail on the right, its live bar and border on its outer / inner edge,
    and the narrow window's tight gap beside it."""
    from PySide6.QtGui import QColor
    win.themectl.set_live_tab_tint(green)
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
        assert bar_at() == ([0] if green else [])
        qapp.setLayoutDirection(Qt.RightToLeft)
        qapp.processEvents()
        assert rail.property("rtl") is True
        assert rail.mapTo(win, QPoint(0, 0)).x() + rail.width() == win.width()
        assert bar_at() == ([rail.width() - 1] if green else [])
        win.fitctl._squeeze_rail(True)
        m = win._body_lay.contentsMargins()
        assert (m.left(), m.right()) == (fitcontrol.BODY_SIDE, fitcontrol.BODY_SIDE_TIGHT)
        win.fitctl._squeeze_rail(False)
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

    from soundboard.ui.radiolist import StationList
    try:
        for name in theme.THEMES:
            theme.apply(qapp, name)
            f = QFrame()
            f.setObjectName(box)
            if box == "stations":
                f.setStyleSheet(StationList._PANEL_STYLE.substitute(theme.T))
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


@pytest.mark.parametrize("name", theme.THEMES)
def test_every_theme_builds_a_clean_stylesheet(qapp, name):
    css = theme.stylesheet(name)
    font = theme.THEMES[name].get("font", theme.FONT)
    assert f"font-family:'{font}'" in css
    assert "/tex-" not in css   # Plain (the default): no theme draws a texture
    assert "$" not in css
    theme.textures_on = True   # Textured: each theme with a pattern draws it
    try:
        assert ("/tex-" in theme.stylesheet(name)) == bool(theme.THEMES[name].get("texture"))
    finally:
        theme.textures_on = False


def test_setup_tab_uses_the_themes_status_colours(qapp, win):
    win.themectl.apply_theme("Light")
    try:
        text = win.flow_mic.text() + win.flow_out.text() + win.step_lbl.text()
        assert "#13ce66" not in text and "#ffb020" not in text and "#ff4d4f" not in text
    finally:
        win.themectl.apply_theme("Dark")


def test_clicking_the_theme_already_on_does_nothing(qapp, win, monkeypatch):
    """Restyling every widget for the same theme froze the app: a click that only
    ticks its card again."""
    win.themectl.apply_theme("Dark")
    d = settings.SettingsDialog(win, "appearance")
    calls = []
    monkeypatch.setattr(win.themectl, "apply_theme", calls.append)
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

    win.themectl.apply_theme("Dark")
    red, amber = theme.status("error"), theme.status("warn")
    lbl = QLabel(f"<span style='color:{red}'>Oops</span>", win)
    lbl.setStyleSheet(f"color:{amber}; background:{red};")
    win.themectl.apply_theme("Mint")
    try:
        assert theme.status("error") in lbl.text() and red not in lbl.text()
        assert lbl.styleSheet() == f"color:{theme.status('warn')}; background:{red};"
        old = {theme.THEMES["Dark"][k].lower() for k in ("ok_text", "warn_text", "error_text")}
        for w in qapp.allWidgets():
            text = w.text() if isinstance(w, QLabel) else ""
            for c in old:
                assert f"color:{c}" not in (text + w.styleSheet()).lower(), (w, c)
    finally:
        win.themectl.apply_theme("Dark")



def test_switching_pages_hands_no_button_the_focus(qapp, win):
    """Going to Settings (or another tab) with the focus on the page left: Qt gave it to
    the new page's first button, the ⓘ beside "Your mic", ringed though no key was
    pressed. The page (or Settings' list) takes it instead."""
    win.resize(1180, 720)
    win.show()
    win.tabs.setCurrentWidget(win.sounds_page)
    win.search.setFocus(Qt.FocusReason.MouseFocusReason)
    for _ in range(2):   # the one made ahead (what the cog opens), then opened again
        win.setctl._prebuild_settings()
        win.setctl.warm_settings()
        win.search.setFocus(Qt.FocusReason.MouseFocusReason)
        d = win.setctl.open_settings("audio")
        qapp.processEvents()
        assert win.focusWidget() is d.categories
        d.done(0)
        qapp.processEvents()
        assert win.focusWidget() in (win.sounds_page, win.tabs.currentWidget())
    win.search.setFocus(Qt.FocusReason.MouseFocusReason)
    win.tabs.setCurrentWidget(win.setup_page)
    qapp.processEvents()
    assert win.focusWidget() is win.setup_page


def test_a_click_leaves_no_focus_ring(qapp, win):
    """A click on a button, a drag of a slider or a pick from a drop-down left that
    control ringed until something else was clicked. The ring is for the Tab key."""
    from PySide6.QtWidgets import QComboBox, QPushButton, QSlider, QVBoxLayout, QWidget

    from soundboard.ui.widgets import install_click_focus
    install_click_focus(qapp)
    page = QWidget(win)
    lay = QVBoxLayout(page)
    btn, slider, combo = QPushButton("Go"), QSlider(Qt.Orientation.Horizontal), QComboBox()
    combo.addItems(["a", "b"])
    for w in (btn, slider, combo):
        lay.addWidget(w)
    page.resize(300, 200)
    win.show()
    page.show()
    qapp.processEvents()
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=slider.rect().center())
    combo.setFocus(Qt.FocusReason.PopupFocusReason)   # (its list just closed)
    for w in (btn, slider, combo):
        if w is not combo:
            w.setFocus(Qt.FocusReason.MouseFocusReason)
        qapp.processEvents()
        assert not w.hasFocus(), w
    slider.setFocus(Qt.FocusReason.TabFocusReason)   # Tab: ringed, as it should be
    qapp.processEvents()
    assert slider.hasFocus()
    page.deleteLater()
