"""Bun mode (soundboard/ui/bunmode.py): the mini player as a floating Bun."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from soundboard.ui import bunmode
from soundboard.ui.mainwindow import MINI_SIZE
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def _mini(window):
    window.show()
    window.resize(300, 200)
    window._refit()
    assert window.is_mini() and window.mini_bun.isVisibleTo(window)


def _click(w, pos: QPoint, button=Qt.MouseButton.LeftButton):
    g = QPointF(w.mapToGlobal(pos))
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        w.event(QMouseEvent(kind, QPointF(pos), g, button, button, Qt.KeyboardModifier.NoModifier))


def _wheel(w, notches: int):
    pos = QPointF(w.rect().center())
    w.wheelEvent(QWheelEvent(pos, QPointF(w.mapToGlobal(pos.toPoint())), QPoint(),
                             QPoint(0, 120 * notches), Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))


def test_mini_player_turns_into_bun_and_a_click_brings_it_back(window, qapp):
    _mini(window)
    window.mini_bun.click()
    bun = window.bunctl.bun_mode
    assert bun.isVisible() and not window.isVisible() and window.cfg.bun["on"]
    flags = bun.windowFlags()
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus   # never takes a game's keys
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    _click(bun, bun._bun_rect().center())   # a click on him: a hop, nothing else
    _click(bun, bun._bun_rect().center())   # (a mouse's stray double click too)
    assert bun.isVisible() and not window.isVisible()
    bun.enterEvent(None)
    bun.b_back.click()                      # the button switches back
    assert not bun.isVisible() and window.isVisible() and window.is_mini()
    assert not window.cfg.bun["on"]


def test_bun_resizes_freely_and_only_the_menu_opens_the_full_board(window, qapp):
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    _wheel(bun, -60)
    assert bun.bun_h == bunmode.MIN_H and bun.isVisible()   # stops at tiny...
    _wheel(bun, 60)
    assert bun.bun_h == bun.max_h() and bun.isVisible()     # ...and at the screen's
    room = bun.screen().availableGeometry()
    assert bun.height() <= room.height() and bun.width() <= room.width()
    _wheel(bun, 5)
    assert bun.isVisible() and not window.isVisible()       # never a trapdoor
    bun.full.emit()                                         # right-click: full board
    assert not bun.isVisible() and window.isVisible() and not window.is_mini()
    assert window.width() >= MINI_SIZE.width() and window.cfg.bun["size"] == bun.max_h()


def test_bun_says_toasts_and_shows_errors_and_downloads(window, qapp):
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    window.toast("Couldn't play <b>Airhorn</b>: the file is gone.", "error")
    assert bun.text == "Couldn't play Airhorn : the file is gone." and bun.kind == "error"
    assert bun.bun.sad == bunmode.SAD_ERROR
    window.toast("✓ Added 3 sounds")
    assert bun.text == "Added 3 sounds" and bun.kind == "ok"
    state = dict(live=False, paused=False, level=0.0, sending=True, mic=True, failed=0)
    bun.tick(downloading=True, **state)
    assert bun.bun.building
    bun.tick(downloading=False, **state)
    assert not bun.bun.building and bun.bun.prop == "star"   # done: the star
    bun._settled()
    bun.tick(downloading=False, **dict(state, live=True, level=0.3))
    assert bun.bun.prop == "headphones" and not bun.bun.naps   # singing along, awake


def test_tray_open_puts_bun_away_and_quit_as_bun_starts_as_bun(window, qapp):
    _mini(window)
    window.bunctl.enter_bun_mode()
    window.show_from_tray()
    assert not window.bunctl.bun_mode.isVisible() and window.isVisible()
    window.cfg.bun["on"] = True
    window.cfg.setup_done = True
    window.hide()
    bun = window.bunctl
    assert bun.start_as_bun() and bun.bun_mode.isVisible() and not window.isVisible()


def test_bun_keeps_his_size_and_stays_on_screen(window, qapp):
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    bun.set_size(180)
    bun._remember()
    bun.hide()
    window.cfg.bun["pos"] = [-99999, -99999]   # a monitor that's gone
    bun.present()
    assert bun.bun_h == 180 and bun._on_a_screen(bun.pos())


def test_hover_shows_the_buttons_and_paints_the_grip(window, qapp):
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    bun.enterEvent(None)
    assert bun.icons.isVisible()
    row = bun.icons
    assert row.height() >= row.sizeHint().height() and row.geometry().bottom() < bun.height()
    for b in (bun.b_play, bun.b_stop, bun.b_air, bun.b_mic, bun.b_back):   # whole, with room under
        assert b.geometry().bottom() <= row.height() - 4 and b.y() >= 4
        # on the 4 px grid: whole screen pixels at 125 / 150 / 175 % (sharp icons)
        assert not (b.x() % 4 or b.y() % 4 or b.width() % 4 or b.iconSize().width() % 4)
    assert not (row.x() % 4 or row.y() % 4 or row.width() % 4 or row.height() % 4)
    bun.say("Hotkeys are off: <b>F9</b> turns them back on.", "warn")
    assert not bun.grab().isNull()   # paints the grip and the bubble
    bun._icons_off()
    assert not bun.icons.isVisible()


def test_dragging_his_corner_only_resizes_him(window, qapp):
    """Grip drags, fast and erratic ones too, change his size and nothing else: his
    top-left corner stays put and the button row stays out of the way until the drop."""
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    bun.set_size(120)
    bun.enterEvent(None)
    corner, h0 = bun._bun_corner(), bun.bun_h
    start = bun._grip().center()

    def mouse(kind, pos, buttons):
        bun.event(QMouseEvent(kind, QPointF(pos), QPointF(bun.mapToGlobal(pos)),
                              Qt.MouseButton.LeftButton, buttons,
                              Qt.KeyboardModifier.NoModifier))
    left = Qt.MouseButton.LeftButton
    mouse(QEvent.Type.MouseButtonPress, start, left)
    g0 = bun.mapToGlobal(start)
    for dx, dy in ((10, 10), (40, 35), (400, -300), (-500, 600), (30, 30), (-60, -60)):
        target = g0 + QPoint(dx, dy)
        mouse(QEvent.Type.MouseMove, bun.mapFromGlobal(target), left)
        assert (bun._bun_corner() - corner).manhattanLength() <= 1, (dx, dy)
        assert not bun.icons.isVisible()
    assert bun.bun_h != h0
    mouse(QEvent.Type.MouseButtonRelease, bun.mapFromGlobal(g0 + QPoint(-60, -60)),
          Qt.MouseButton.NoButton)
    assert bun.icons.isVisible() and bun.isVisible() and not window.isVisible()


def test_a_tabs_right_click_menu_turns_the_full_board_into_bun_and_back(window, qapp):
    window.show()
    window.resize(1180, 720)
    window._refit()
    assert not window.is_mini()
    menu = window.tab_menu(0)
    act = next(a for a in menu.actions() if a.text() == "Turn into Bun")
    act.trigger()
    bun = window.bunctl.bun_mode
    assert bun.isVisible() and not window.isVisible()
    bun.enterEvent(None)
    bun.b_back.click()
    assert window.isVisible() and not window.is_mini() and window.width() == 1180


def test_his_resize_corner_shrinks_with_him(window, qapp):
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    bun.set_size(bunmode.MIN_H)
    small = bun._grip().width()
    bun.set_size(200)
    assert small < bun._grip().width() and small <= bunmode.GRIP_MIN + 4


def test_back_returns_the_window_as_it_was_even_after_a_restart(window, qapp):
    """Back gives the window its size and place from before Bun, also when the app
    started as Bun (the window never shown); only the menu opens the full board."""
    _mini(window)
    window.move(120, 90)
    was = window.geometry()
    window.bunctl.enter_bun_mode()
    assert window.cfg.bun["from"][:4] == [was.x(), was.y(), was.width(), was.height()]
    window.resize(1180, 720)   # what a fresh start has, the window never shown
    window.bunctl.bun_mode.back.emit()
    assert window.isVisible() and window.is_mini() and window.geometry() == was
    window.bunctl.enter_bun_mode()
    window.bunctl.bun_mode.full.emit()   # the right-click menu: the full board
    assert not window.is_mini() and window.width() > was.width()
