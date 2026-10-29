"""Picking a theme in Settings restyles every widget in the app: in 1.7.2 that froze the
window for 5-6 s (the freeze reports). These keep it quick on the real main window
with every Settings page built."""
import os
import time

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

from soundboard.core import hangwatch
from soundboard.ui.kit import theme
from soundboard.sounds.library import SoundMeta
from soundboard.ui.settings.settings import SettingsDialog
import pytest

# ~0.5 s on a real PC. Hosted CI runners take 1.2-2.5 s for the same unchanged code
# (shared cores, three other test workers beside it), so there the budget is the
# point the app itself calls a freeze and reports it (hangwatch.HANG_S).
BUDGET_S = hangwatch.HANG_S if os.environ.get("CI") else 2.0


@pytest.fixture
def settings(main_window, app_dir):  # noqa: F811
    first = main_window.cfg.sounds[0]   # a full board: 60 pads
    main_window.cfg.sounds += [SoundMeta(id=f"x{i}", name=f"Sound {i}", file=first.file)
                               for i in range(58)]
    main_window._rebuild_pads()
    main_window.resize(1280, 760)
    main_window.show()
    dlg = SettingsDialog(main_window, "appearance", lazy=False)
    dlg.show()
    QApplication.processEvents()
    yield dlg
    dlg.close()


def _other(name: str) -> str:
    return next(n for n in theme.THEMES if n != name)


def test_a_theme_switch_stays_under_budget(settings):
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        settings.appearance._pick_theme(_other(theme.current_name))
        QApplication.processEvents()
        times.append(time.perf_counter() - t0)
    assert min(times) < BUDGET_S, times


def test_no_python_filter_on_the_whole_app(main_window):  # noqa: F811
    """A Python filter on the app is called for every event of every widget: ~20,000
    in a restyle, an eighth of building Settings, a fifth of each resize step. Space
    and the drop veil watch the main window's own QWindow instead (winwatch.py), the
    click focus and the quiet boxes ride the app style's polish."""
    assert not hasattr(theme, "app_filter")
    watched = main_window._window_watch._by_type
    assert QEvent.Type.KeyPress in watched and QEvent.Type.DragEnter in watched


def test_a_switch_shows_a_still_with_bun_then_fades_to_the_new_theme(settings, main_window):  # noqa: F811
    """Never a half-styled frame: the window is covered by a picture of itself while
    every widget restyles, then that fades. A quick second click never stacks two."""
    from soundboard.ui.window.themecover import ThemeCover
    seen = []
    real = main_window.themectl._apply_theme

    def during(name):
        seen.extend(c for c in main_window.findChildren(ThemeCover) if c.isVisible())
        real(name)
    main_window.themectl._apply_theme = during
    try:
        main_window.themectl.apply_theme(_other(theme.current_name))
        main_window.themectl.apply_theme(_other(theme.current_name))
    finally:
        del main_window.themectl._apply_theme
    assert len(seen) == 2 and seen[1].geometry() == main_window.rect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    covers = main_window.findChildren(ThemeCover)
    assert len(covers) == 1   # the first went as the second came
    end = time.monotonic() + 3
    while main_window.findChildren(ThemeCover) and time.monotonic() < end:
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not main_window.findChildren(ThemeCover)


def test_the_cover_shows_bun_in_the_theme_being_switched_to(main_window):  # noqa: F811
    """Bun and the dimming on the cover were drawn in the theme being left (his
    headphones in its accent): they're the new theme's, and the current one stays."""
    from soundboard.ui.bun.bunny import bunny_image
    from soundboard.ui.window.themecover import BUNNY_H, ThemeCover
    old, new = "Dark", "Royal"   # different accents and bg, and Royal dresses Bun up
    theme.set_current(old)
    main_window.show()   # covers only go over a window on screen
    cover = ThemeCover(main_window, new)
    try:
        assert theme.current_name == old and theme.T == theme.tokens(old)
        assert cover.scrim.rgb() == QColor(theme.tokens(new)["bg"]).rgb()
        assert cover.scrim.alpha() == 150
        with theme.previewing(new):
            want = bunny_image(BUNNY_H, dpr=1.0)
        assert cover.bunny.toImage().convertToFormat(want.format()) == want
        assert cover.bunny.toImage().convertToFormat(want.format()) != bunny_image(
            BUNNY_H, dpr=1.0)
    finally:
        cover.deleteLater()


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_a_hovered_menu_row_shows_in_every_theme(name):
    """The hovered row of a menu or dropdown was 1.07-1.5:1 against the menu (no
    visible change in Flashbang, Blood Moon, Lava): now it stands out, words readable."""
    t = theme.THEMES[name]
    assert theme._contrast(t["item_hover"], t["card"]) >= 1.6
    assert theme._contrast(t["item_hover"], t["text_hi"]) >= 4.5


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_the_settings_page_youre_on_shows_in_every_theme(name):
    """The Settings list's current page was 1.03:1 against the window in the light
    themes (Paper, Light, Mint: no visible mark); the rail's current tab 1.07:1 in
    Flashbang. Both stand out now, their words readable."""
    import re
    t = theme.tokens(name)
    css = theme.stylesheet(name)
    sel = re.search(r"#settingscategories::item:selected \{ background:(#\w+)", css)[1]
    assert theme._contrast(sel, t["bg"]) >= 1.6   # (1.5 as drawn, on the finish)
    assert theme._contrast(sel, t["text_hi"]) >= 4.5
    with theme.previewing(name):
        colour, alpha = theme.rail_tint()
        base = theme.rail_bg(theme.T, name in theme.OUTLINED)
    assert theme._contrast(theme._mix(base, colour, alpha), base) >= 1.3


def test_the_cover_fades_in_instead_of_dimming_in_one_frame(main_window):  # noqa: F811
    """It goes up as the window is (nothing changes on screen), then the dimming and
    Bun come in over a few frames; a highlight colour change is a plain blend."""
    from soundboard.style import cover as kit
    from soundboard.ui.window import themecover
    main_window.show()
    ks = []
    real = kit.Cover.repaint
    kit.Cover.repaint = lambda self: (ks.append(self.k), real(self))[1]
    try:
        with themecover.covered(main_window, "Light") as covers:
            assert len(covers) == 1
        with themecover.blended(main_window) as plain:
            assert plain[0].scrim is None and plain[0].mascot is None
    finally:
        kit.Cover.repaint = real
    assert ks[0] == 0.0 and ks[-2] == 1.0          # up first as it is, then faded in
    assert max(b - a for a, b in zip(ks[:-1], ks[1:-1])) < 0.7   # never one jump
    assert ks[-1] == 0.0                           # the blend: no dimming at all


def _closed_window(owner):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QComboBox, QDialog, QLabel, QPushButton, QVBoxLayout,
                                   QWidget)
    d = QDialog(owner)
    lay = QVBoxLayout(d)
    for w in (QLabel("Edit voice"), QPushButton("Randomize"), QComboBox()):
        lay.addWidget(w)
    b = QPushButton("Save")
    b.setObjectName("primary")
    lay.addWidget(b)
    for w in d.findChildren(QWidget):   # no focus ring on the one shown last
        w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    d.resize(240, 160)
    return d


def test_a_closed_window_sits_out_the_restyle_and_opens_in_the_new_theme(main_window):  # noqa: F811
    """The closed windows the app keeps (Edit voice, Live controls: ~700 widgets) were
    restyled on every switch, a third of its wait. They're left for their next show,
    which styles them in the theme of the day: it looks the same as one made in it."""
    from PySide6.QtCore import Qt
    app = QApplication.instance()
    start = theme.current_name
    other = "Light" if start != "Light" else "Dark"
    kept = _closed_window(main_window)
    kept.ensurePolished()   # styled once in the first theme, like a window made ahead
    theme.apply(app, other)
    polished = Qt.WidgetAttribute.WA_WState_Polished
    assert not any(w.testAttribute(polished) for w in (kept, *kept.findChildren(QObject))
                   if hasattr(w, "testAttribute"))
    fresh = _closed_window(main_window)
    try:
        for d in (kept, fresh):
            d.show()
            QApplication.processEvents()
        assert kept.grab().toImage() == fresh.grab().toImage()
    finally:
        for d in (kept, fresh):
            d.close()
            d.deleteLater()
        theme.apply(app, start)


def _closed_window_with_own_sheet(owner):
    """Like Live controls: its sliders and boxes sit in a column with a sheet of its
    own (a transparent background)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QCheckBox, QDialog, QPushButton, QSlider, QVBoxLayout, QWidget
    d = QDialog(owner)
    col = QWidget()
    col.setObjectName("spcol")
    col.setStyleSheet("QWidget#spcol { background:transparent; }")
    lay = QVBoxLayout(col)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setValue(50)
    check = QCheckBox("Keep pitch")
    check.setChecked(True)
    b = QPushButton("1.5x")
    b.setObjectName("small")
    for w in (slider, check, b):
        lay.addWidget(w)
    QVBoxLayout(d).addWidget(col)
    for w in d.findChildren(QWidget):
        w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    d.resize(240, 140)
    return d


def test_a_closed_window_with_its_own_sheets_opens_in_the_theme_not_bare(main_window):  # noqa: F811
    """Live controls opened with bare Windows sliders, ticks and buttons after any
    restyle while it was closed (a theme switch, a page built): the parts under a sheet
    of their own kept the plain style the restyle clears to, until a change re-set
    its button's sheet. They're made anew from the new theme now."""
    app = QApplication.instance()
    start = theme.current_name
    other = "Light" if start != "Light" else "Dark"
    kept = _closed_window_with_own_sheet(main_window)
    kept.show()   # opened once in the first theme, then closed
    QApplication.processEvents()
    kept.hide()
    theme.apply(app, other)
    fresh = _closed_window_with_own_sheet(main_window)
    try:
        for d in (kept, fresh):
            d.show()
            QApplication.processEvents()
        assert kept.grab().toImage() == fresh.grab().toImage()
    finally:
        for d in (kept, fresh):
            d.close()
            d.deleteLater()
        theme.apply(app, start)


def test_the_main_window_still_restyles_while_hidden(main_window):  # noqa: F811
    """In the tray (no owner): restyled with the rest, as before."""
    from PySide6.QtCore import Qt
    main_window.hide()
    main_window.ensurePolished()
    start = theme.current_name
    try:
        theme.apply(QApplication.instance(), "Light" if start != "Light" else "Dark")
        assert main_window.testAttribute(Qt.WidgetAttribute.WA_WState_Polished)
    finally:
        theme.apply(QApplication.instance(), start)


def test_the_fade_out_paints_the_board_once_not_every_frame(settings, main_window):  # noqa: F811
    """The cover fades out as two pictures, old over new, and stays opaque. A
    see-through cover (an opacity effect) made Qt paint every widget under it on each
    frame of the fade: ~18 paints of every pad per switch."""
    from soundboard.ui.window.themecover import ThemeCover
    from soundboard.ui.kit.widgets import Pad

    class Paints(QObject):
        n = 0

        def eventFilter(self, obj, ev):  # noqa: N802 - Qt API
            if ev.type() == QEvent.Type.Paint and isinstance(obj, Pad):
                self.n += 1
            return False
    main_window.tabs.setCurrentIndex(0)   # the Sounds tab
    QApplication.processEvents()
    pads = len([p for p in main_window.findChildren(Pad) if p.isVisible()])
    assert pads > 10
    count = Paints()
    app = QApplication.instance()
    start = theme.current_name
    app.installEventFilter(count)
    try:
        main_window.themectl.apply_theme(_other(start))
        end = time.monotonic() + 3
        while main_window.findChildren(ThemeCover) and time.monotonic() < end:
            QApplication.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        assert not main_window.findChildren(ThemeCover)
    finally:
        app.removeEventFilter(count)
        main_window.themectl.apply_theme(start)
    assert count.n <= 3 * pads


def test_the_fade_out_is_the_dimmed_picture_crossfading_to_the_new_look(qapp):
    """Half way, the old picture (dimming included) and the restyled window count
    half each: the dimming fades with the picture, it doesn't tint the new look."""
    from PySide6.QtWidgets import QWidget
    from soundboard.style import cover
    host = QWidget()
    host.resize(80, 60)
    host.setStyleSheet("background: #ff0000;")
    host.show()
    QApplication.processEvents()
    c = cover.Cover(host, QColor("#000000"))
    cover._fade_in([c])            # red, dimmed by black at SCRIM_ALPHA
    host.setStyleSheet("background: #0000ff;")   # the restyle
    c.uncover()
    c._fade.pause()
    c._fade.setCurrentTime(cover.FADE_MS // 2)   # InOutQuad: half way at half time
    QApplication.processEvents()
    px = c.grab().toImage().pixelColor(40, 30)
    dim = 1 - cover.SCRIM_ALPHA / 255
    assert abs(px.red() - 0.5 * 255 * dim) <= 3
    assert abs(px.blue() - 0.5 * 255) <= 3
    c._fade.stop()
    host.close()
    host.deleteLater()


def test_the_fade_out_starts_from_the_window_as_it_settles(main_window, monkeypatch):  # noqa: F811
    """The restyled window's picture is taken after the layouts the restyle queued:
    taken before, the theme cards in it sat a few pixels to the side, so the fade
    showed them jump sideways and back on every switch."""
    from soundboard.style import cover as kit
    main_window.resize(1400, 900)
    main_window.show()
    main_window.setctl.open_settings("appearance")
    for _ in range(5):
        QApplication.processEvents()
    cards = main_window.setctl._settings_dlg.theme_cards
    fresh = []
    real = kit.Cover.uncover

    def spy(self):
        real(self)
        fresh.append(self.fresh.toImage())
    monkeypatch.setattr(kit.Cover, "uncover", spy)
    start = theme.current_name
    try:
        picked = next(c for c in cards if c.name == _other(start))
        picked.click()
        for _ in range(10):
            QApplication.processEvents()
        for c in main_window.findChildren(kit.Cover):
            c.hide()
        QApplication.processEvents()
        now = main_window.grab().toImage()
        assert len(fresh) == 1
        dpr = now.devicePixelRatio()
        checked = 0
        for card in cards:
            at = card.mapTo(main_window, card.rect().topLeft())
            x0, y0 = round(at.x() * dpr), round(at.y() * dpr)
            w, h = round(card.width() * dpr), round(40 * dpr)
            if card is picked:   # (its focus ring comes a moment later: colour only)
                continue
            if not card.isVisible() or y0 < 0 or y0 + h > now.height() or x0 + w > now.width():
                continue   # (scrolled out of sight)
            checked += 1
            assert fresh[0].copy(x0, y0, w, h) == now.copy(x0, y0, w, h), card.name
        assert checked >= 5
    finally:
        main_window.themectl.apply_theme(start)


def _page(owner):
    """A part of the window: shown once, then hidden (another tab, a closed panel)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget
    page = QWidget(owner)
    lay = QVBoxLayout(page)
    for w in (QLabel("Sounds"), QPushButton("Add"), QComboBox()):
        lay.addWidget(w)
    b = QPushButton("Save")
    b.setObjectName("primary")
    lay.addWidget(b)
    for w in page.findChildren(QWidget):
        w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    page.setGeometry(0, 0, 240, 160)
    return page


def _hidden_page(main_window):  # noqa: F811
    main_window.resize(900, 600)
    main_window.show()
    page = _page(main_window)
    page.show()
    QApplication.processEvents()
    page.hide()
    return page


def _done_later():
    end = time.monotonic() + 5
    while theme._later is not None and theme._later.todo and time.monotonic() < end:
        QApplication.processEvents()
    assert not theme._later.todo


@pytest.mark.parametrize("show_at_once", [False, True])
def test_a_hidden_part_sits_out_the_switch_and_shows_in_the_new_theme(main_window, show_at_once):  # noqa: F811
    """Qt told every widget of the window the style changed, and each worked its look out
    again from the whole sheet: ~0.5 s of a switch, 1-1.7 s on a busy PC, for the hidden
    tabs and pages nobody could see. They're styled after it, a few at a time, and one
    shown before its turn is styled as it shows: it looks the same as one made in the
    new theme either way."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    class Told(QObject):
        n = 0

        def eventFilter(self, obj, ev):  # noqa: N802 - Qt API
            if ev.type() == QEvent.Type.StyleChange and obj in parts:
                self.n += 1
            return False
    app = QApplication.instance()
    start = theme.current_name
    other = "Light" if start != "Light" else "Dark"
    kept = _hidden_page(main_window)
    parts = {kept, *kept.findChildren(QWidget)}
    polished = Qt.WidgetAttribute.WA_WState_Polished
    styled = [w for w in parts if w.testAttribute(polished)
              and w.window() is main_window]   # (its drop-down's list: a closed window)
    assert len(styled) >= 5
    told = Told()
    app.installEventFilter(told)
    try:
        theme.apply(app, other)
    finally:
        app.removeEventFilter(told)
    fresh = None
    try:
        assert told.n == 0   # nothing worked out for it during the switch
        assert not any(w.testAttribute(polished) for w in styled)
        if not show_at_once:
            _done_later()
            assert all(w.testAttribute(polished) for w in styled)
        fresh = _page(main_window)
        for p in (kept, fresh):
            p.show()
            QApplication.processEvents()
        assert kept.grab().toImage() == fresh.grab().toImage()
    finally:
        for p in (kept, fresh):
            if p is not None:
                p.deleteLater()
        theme.apply(app, start)
        _done_later()


def test_a_part_left_for_later_loses_what_the_old_sheet_set(qapp):
    """Left out of Qt's restyle, a hidden widget kept the old sheet's colour where the
    new sheet had no rule for it (Qt's record of its own colour went with the old
    sheet): undone when it's styled now, as Qt's restyle would."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    app = QApplication.instance()
    before = app.styleSheet()
    plain = QLabel("x").palette().color(QPalette.ColorRole.WindowText)
    try:
        app.setStyleSheet("QLabel { color: #ff0000; }")
        host = QWidget()
        page = QWidget(host)
        QVBoxLayout(page).addWidget(label := QLabel("x"))
        host.show()
        QApplication.processEvents()
        page.hide()
        later = theme._Later()
        with later.holding_back(app):
            theme._restyle(app, "QPushButton { color: #0000ff; }", later)
        assert later.todo   # (left for later)
        while later.todo:
            QApplication.processEvents()
        page.show()
        QApplication.processEvents()
        assert label.palette().color(QPalette.ColorRole.WindowText) == plain
    finally:
        app.setStyleSheet(before)
        host.close()
        host.deleteLater()
