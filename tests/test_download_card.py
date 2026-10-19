"""The download card in the page's bottom-right corner (ui/window/downloadbar.py): where
it sits, its pill, how it winds down, ▶ and Show on what was added, and the toasts
standing on it."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest

from soundboard.ui.window import downloadbar as db
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)



@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


LINKS = [f"https://www.youtube.com/watch?v={c}" for c in "abcd"]


def _added(bar, url: str, title: str = "Added one"):
    bar.set_active(url, title, "add", None, "Someone", 60)
    bar.set_done(url, "add", True)
    QTest.qWait(db.Outcome.SHOW_MS + 100)   # the flash holds what comes next


def test_card_sits_in_the_corner_and_folds_to_a_pill(window, qapp, monkeypatch):
    """Over the page's bottom-right corner above the player, never pushing the page
    down; minimised, a round pill as wide as its summary line, still in the corner;
    opened again, the card."""
    window.resize(1200, 800)
    window.show()
    bar = window.download_bar
    box = window._tabs_box
    QTest.qWait(50)   # laid out
    top_before = window.sounds_toolbar.mapTo(window, window.sounds_toolbar.rect().topLeft())
    bar.set_active(LINKS[0], "One", "add", None, "Someone", 90)
    bar.set_queue([{"url": u, "title": "x", "kind": "add"} for u in LINKS[1:]])
    QTest.qWait(50)
    host = bar.parentWidget()   # holds the page, the Now playing row and the player
    assert bar.isVisibleTo(window) and host.isAncestorOf(box)
    assert host.isAncestorOf(window.transport)
    page = bar._in_host(box)
    # the page under it didn't move
    assert window.sounds_toolbar.mapTo(window, window.sounds_toolbar.rect().topLeft()) == top_before
    g = bar.geometry()
    assert g.width() == db.CARD_W
    assert g.right() == page.right() - db.CARD_MARGIN
    # standing on the player (or what's over it), which can overlap the page's foot
    floor = bar._floor(g.left(), g.right() + 1)
    for under in (window.playing_row, window.transport, window.mixer):
        if under.isVisible():
            assert floor <= bar._in_host(under).top()
    assert floor <= host.height() and g.bottom() == floor - 1 - db.CARD_GAP
    open_h = g.height()

    bar.btn_min.click()
    QTest.qWait(50)
    g = bar.geometry()
    assert bar.property("pill") and not bar.panel.isVisibleTo(bar)
    assert g.height() < open_h   # as wide as its line needs (the fonts decide)
    assert g.width() == min(db.CARD_W, bar.summary.sizeHint().width() + 20)
    assert g.right() == page.right() - db.CARD_MARGIN   # still in the corner
    assert bar.s_bar.isVisibleTo(bar)                      # how far it's got, still

    bar.btn_min.click()
    QTest.qWait(50)
    assert not bar.property("pill") and bar.geometry().height() == open_h

    # a sound playing shows Now playing over the player, its chips on the left: the
    # card stays down on the player beside them...
    window.playctl._update_chips({window.cfg.sounds[0].id})
    # (nothing really plays: the app's tick would take the row down again)
    monkeypatch.setattr(window.playctl, "_update_chips", lambda *a, **k: None)
    QTest.qWait(50)
    row = window.playing_row
    assert row.isVisible()
    row_top = bar._in_host(row).top()
    chips_right = bar._in_host(row).left() + row.childrenRect().right()
    assert chips_right < bar.x()
    lowest = min([host.height()] + [bar._in_host(u).top()
                                    for u in (window.transport, window.mixer) if u.isVisible()])
    assert bar.geometry().bottom() == lowest - 1 - db.CARD_GAP   # down beside the chips
    # ...and stands on the row where its chips reach under it (a narrow window)
    window.resize(560, 800)
    QTest.qWait(100)
    row_top = bar._in_host(row).top()
    assert bar._in_host(row).left() + row.childrenRect().right() >= bar.x()
    assert bar.geometry().bottom() < row_top
    bar._clear_and_hide()


def test_toasts_stand_on_the_card(window, qapp):
    window.resize(1200, 800)
    window.show()
    bar = window.download_bar
    QTest.qWait(50)   # laid out
    floor = window.toast_floor()
    bar.set_active(LINKS[0], "One", "add", None, "Someone", 90)
    QTest.qWait(50)
    top = bar.mapTo(window, bar.rect().topLeft()).y()
    assert window.toast_floor() == top - 4 < floor
    bar._clear_and_hide()
    QTest.qWait(10)
    assert window.toast_floor() == floor


def test_when_all_added_it_folds_then_goes(window, qapp, monkeypatch):
    """Everything added: the card folds to its pill (how it ended stays in view), then
    goes. The mouse on it holds it."""
    fold = db.Outcome.SHOW_MS + 400   # counted from the end, under the flash
    monkeypatch.setattr(db, "FOLD_MS", fold)
    monkeypatch.setattr(db, "FOLDED_MS", 300)
    window.resize(1200, 800)
    window.show()
    bar = window.download_bar
    _added(bar, LINKS[0])   # (waits out the flash)
    assert bar.isVisible() and not bar._collapsed
    QTest.qWait(500)
    assert bar.isVisible() and bar._collapsed and bar.property("pill")
    assert bar.h_text.text() == "Added 1 sound"
    QTest.qWait(500)
    assert not bar.isVisible()

    _added(bar, LINKS[1])
    bar.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))   # the mouse on it
    QTest.qWait(800)
    assert bar.isVisible() and not bar._collapsed
    bar.leaveEvent(QEvent(QEvent.Type.Leave))
    assert bar._auto_fold.remainingTime() >= 2000   # what was left, at least 2.5 s
    bar._clear_and_hide()


def test_a_failure_keeps_the_pill_red_and_up(window, qapp, monkeypatch):
    """A pick that failed waits for Retry: no folding away, and minimised the pill still
    says how many failed."""
    monkeypatch.setattr(db, "FOLD_MS", 100)
    window.resize(1200, 800)
    window.show()
    bar = window.download_bar
    bar.set_active(LINKS[0], "Cut off", "add", None, "Someone", 60)
    bar.set_failed(LINKS[0], "add")
    bar.set_done(LINKS[0], "add", False)
    QTest.qWait(db.Outcome.SHOW_MS + 300)
    assert bar.isVisible() and not bar._collapsed and bar.btn_retry.isVisibleTo(bar)
    bar.btn_min.click()
    QTest.qWait(50)
    assert bar.property("pill") and bar.h_failed.isVisibleTo(bar)
    assert bar.h_failed.text() == "1 failed"
    QTest.qWait(300)
    assert bar.isVisible()
    bar._clear_and_hide()


def test_added_rows_play_and_show_their_pad(window, qapp):
    """What was added gets ▶ (plays its pad's sound) and Show (the Sounds tab, the pad
    picked); a pick that isn't a pad (any more) gets neither."""
    window.resize(1200, 800)
    window.show()
    bar = window.download_bar
    sid = window.cfg.sounds[0].id if window.cfg.sounds else None
    assert sid, "the window fixture has sounds"
    window.linkbar.added_ids[LINKS[0]] = sid
    played, shown = [], []
    bar.play_sound.connect(played.append)
    bar.show_sound.connect(shown.append)
    _added(bar, LINKS[0])
    assert bar.btn_play.isVisibleTo(bar) and bar.btn_show.isVisibleTo(bar)
    bar.btn_play.click()
    bar.btn_show.click()
    assert played == shown == [sid]

    _added(bar, LINKS[1])   # not a pad: no buttons for it on its row
    assert not bar.btn_play.isVisibleTo(bar)
    rows = [bar.rows.itemAt(i).widget() for i in range(bar.rows.count())]
    row = next(r for r in rows if r is not None)   # LINKS[0], added already
    shows = [b for b in row.findChildren(db.QPushButton) if b.text() == "Show"]
    assert len(shows) == 1
    window.tabs.setCurrentIndex(1)
    shows[0].click()
    assert window.tabs.currentWidget() is window.sounds_page and window.current == sid
    bar._clear_and_hide()
