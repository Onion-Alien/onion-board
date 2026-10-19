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
