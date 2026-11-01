"""Bun mode (soundboard/ui/bun/bunmode.py): the mini player as a floating Bun."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from soundboard.ui.bun import bunmode
from soundboard.ui.window.fitcontrol import MINI_SIZE
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def _mini(window):
    window.show()
    window.resize(300, 200)
    window.fitctl._refit()
    assert window.fitctl.is_mini() and window.mini_bun.isVisibleTo(window)


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
    assert not bun.isVisible() and window.isVisible() and window.fitctl.is_mini()
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
    assert not bun.isVisible() and window.isVisible() and not window.fitctl.is_mini()
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


def test_bun_lands_centred_on_the_window_he_came_from(window, qapp):
    """Even after he was dragged somewhere else last time: right where the window was."""
    _mini(window)
    room = window.screen().availableGeometry()
    window.move(room.center() - window.rect().center() + QPoint(30, -20))   # off the middle
    qapp.processEvents()
    window.cfg.bun["pos"] = [0, 0]
    was = window.frameGeometry().center()
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    body = bun._bun_rect().translated(bun.pos()).center()
    assert abs(body.x() - was.x()) <= 1 and abs(body.y() - was.y()) <= 1


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


def test_buttons_show_as_he_lands_then_go(window, qapp):
    # the buttons (and Back to the board) only ever came with a hover, so someone who
    # didn't know to hover saw no way back
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    assert bun.icons.isVisible() and not bun.b_back.isHidden()
    bun._first_look_over()
    assert not bun.icons.isVisible()
    bun.enterEvent(None)          # the mouse on him by then: they stay
    bun._first_look_over()
    assert bun.icons.isVisible()


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
    assert window.isVisible() and window.fitctl.is_mini() and window.geometry() == was
    window.bunctl.enter_bun_mode()
    window.bunctl.bun_mode.full.emit()   # the right-click menu: the full board
    assert not window.fitctl.is_mini() and window.width() > was.width()


def test_tray_item_brings_the_window_back_while_bun_is_up(window, qapp):
    from PySide6.QtTest import QTest
    _mini(window)
    window.activateWindow()
    window.mini_bun.setFocus(Qt.FocusReason.MouseFocusReason)   # as a click leaves it
    window.mini_bun.click()
    assert window.bunctl.bun_up()
    assert window.focusWidget() is not window.mini_bun
    if getattr(window, "_tray_bun", None) is not None:   # (no tray on some desktops)
        window._name_tray_bun()
        assert window._tray_bun.text() == "Back to the board"
    window.bunctl.tray_bun()                             # the tray item, Bun up
    assert not window.bunctl.bun_up() and window.isVisible()
    if getattr(window, "_tray_bun", None) is not None:
        window._name_tray_bun()
        assert window._tray_bun.text() == "Turn into Bun"
    window.tabs.setCurrentWidget(window.sounds_page)   # the mini player's pads
    window.current = None                                # nothing loaded to play
    window.mini_bun.setFocus(Qt.FocusReason.MouseFocusReason)
    QTest.keyClick(window.windowHandle(), Qt.Key.Key_Space)   # Space: not a press of Bun's
    assert not window.bunctl.bun_up() and window.isVisible()
    window.bunctl.tray_bun()                             # Bun not up: turns into him
    assert window.bunctl.bun_up()
    window.bunctl.leave_bun_mode()


def test_he_dances_to_whats_playing_and_gets_sad_when_nothing_does(window, qapp):
    import numpy as np
    _mini(window)
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    state = dict(paused=False, level=0.3, sending=False, mic=True, downloading=False,
                 failed=0)
    song = np.zeros((48000 * 10, 2), np.int16)
    bun.tick(live=True, song=(song, 0.5), **state)
    assert bun.bun.groove is bun.groove and bun.groove._pos > 0   # listening to it
    bun.tick(live=False, song=None, **state)
    assert bun.bun.groove is None
    # the moods: fine, bored, then sad; music again and he hops for joy
    bun._quiet_since = None
    assert bun._mood(0.0, False, False) == 0.0
    assert bun._mood(bunmode.BORED_S + 1, False, False) == bunmode.BORED
    assert bun._mood(bunmode.SAD_S + 1, False, False) == bunmode.LONELY
    bun.bun._joy_at = -1.0
    assert bun._mood(bunmode.SAD_S + 2, True, False) == 0.0
    assert bun.bun._joy_at > 0
    assert bun._mood(bunmode.SAD_S + 3, False, True) == 0.0   # busy (downloading): fine


def test_mascots_on_screen_dance_to_the_radio(qapp):
    """The tick hands what plays to every dancing mascot on screen: here the radio,
    read through the engine's tap only while one of them is up."""
    from types import SimpleNamespace

    import numpy as np

    from soundboard.audio.groove import SR, Groove
    from soundboard.ui.bun.bunnywidget import BunnyWidget
    from soundboard.ui.window.tickcontrol import TickControl
    on = [True]
    eng = SimpleNamespace(radio_tap=None)
    mw = SimpleNamespace(engine=eng, radio=SimpleNamespace(is_active=lambda: on[0]),
                         audio={}, _meta={})
    tc = SimpleNamespace(mw=mw, groove=Groove())
    bun = BunnyWidget(height=80, sad=0.9, dances=True)
    bun.show()
    beat = np.zeros(int(SR * 60 / 120), np.float32)
    t = np.arange(int(0.12 * SR)) / SR
    beat[:len(t)] = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 18) * 0.5
    stream = np.repeat(np.tile(beat, 16)[:, None], 2, axis=1)
    step, now = int(SR / 30), 0.0
    for pos in range(0, len(stream) - step, step):
        TickControl._dance(tc, {}, now)
        assert eng.radio_tap is not None
        eng.radio_tap.append(stream[pos:pos + step])
        now += 1 / 30
    assert bun.groove is tc.groove and tc.groove.bpm > 0
    on[0] = False                   # the radio stops: no more tap, no more dance
    TickControl._dance(tc, {}, now)
    assert eng.radio_tap is None and bun.groove is None
    bun.hide()
    on[0] = True                    # nobody on screen: the radio isn't read at all
    TickControl._dance(tc, {}, now)
    assert eng.radio_tap is None
    bun.deleteLater()


def test_settings_asked_for_from_bun_bring_the_window_back(window, qapp):
    """In Bun mode Settings couldn't be opened: the page opened in the hidden window."""
    _mini(window)
    window.bunctl.enter_bun_mode()
    assert not window.isVisible()
    window.setctl.open_settings("appearance")
    assert window.isVisible() and not window.bunctl.bun_up()
    assert window._content.currentWidget() is window.setctl._settings_dlg


def test_buttons_sit_close_under_his_feet(window, qapp):
    window.bunctl.enter_bun_mode()
    bun = window.bunctl.bun_mode
    for h in (130, 220):
        bun.set_size(h)
        feet = bun._bun_rect().bottom()
        gap = bun.icons.y() + bun.b_play.y() - feet
        assert 0 < gap <= round(h * 0.1) + 6, (h, gap)   # (it was 25 px at 130)
