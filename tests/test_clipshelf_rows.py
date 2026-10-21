"""The saved clips / Recordings list's painted rows: waveform pictures, the round
play button, the hovered row's buttons, keys, Live, and the narrow layout."""
from datetime import date, datetime

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from test_mainwindow import window  # noqa: F401

from soundboard.sounds import clipshelf
from soundboard.audio.engine import SR
from soundboard.ui.apps.clipshelf import length_text, when_text


def _recs(window, monkeypatch):  # noqa: F811
    recs = window.voice.recordings
    played = []
    monkeypatch.setattr(window.engine, "play", lambda sid, data, gain, mode="", preview=False:
                        played.append((sid, preview)) or object())
    monkeypatch.setattr(window.engine, "state", lambda sid: (0.5, False))
    return recs, played


def test_peaks_are_a_small_picture_of_the_loudness():
    quiet_then_loud = np.concatenate([np.full((SR, 2), 0.01, np.float32),
                                      np.full((SR, 2), 0.5, np.float32)])
    p = clipshelf.peaks_of(quiet_then_loud)
    assert len(p) == clipshelf.PEAKS and max(p) == 1.0
    assert p[0] < 0.2 and p[-1] == 1.0          # the quiet half shows small, not missing
    assert clipshelf.peaks_of(np.zeros((0, 2), np.float32)) == []
    assert clipshelf.peaks_of(np.zeros((100, 2), np.float32)) == [0.0] * clipshelf.PEAKS


def test_saving_draws_the_waveform_and_older_clips_get_one_later(tmp_path, monkeypatch):
    monkeypatch.setattr(clipshelf.library, "APP_DIR", tmp_path)
    sh = clipshelf.Shelf()
    c = sh.add(np.full((SR // 2, 2), 0.3, np.float32), "Take")
    assert len(c.peaks) == clipshelf.PEAKS
    c.peaks = []                                   # as saved by an older version
    sh.save()
    sh = clipshelf.Shelf()
    assert sh.clips[0].peaks == []
    assert sh.fill_peaks() == 1 and len(sh.clips[0].peaks) == clipshelf.PEAKS
    assert sh.fill_peaks() == 0                    # nothing left to draw


def test_lengths_and_dates_read_like_people_say_them():
    assert length_text(3.0) == "0:03" and length_text(71.4) == "1:11"
    today = date(2026, 10, 18)
    assert when_text(datetime(2026, 10, 18, 14, 2).timestamp(), today).startswith("Today")
    assert when_text(datetime(2026, 10, 17, 9, 0).timestamp(), today) == "Yesterday"
    assert "2026" not in when_text(datetime(2026, 3, 1).timestamp(), today)
    assert "2025" in when_text(datetime(2025, 3, 1).timestamp(), today)


def test_the_round_button_plays_and_keys_play_send_and_stop(window, monkeypatch):  # noqa: F811
    recs, played = _recs(window, monkeypatch)
    c = recs.add(np.full((SR // 2, 2), 0.2, np.float32), "Take", "My voice")
    window.resize(1200, 800)
    window.show()
    window.tabs.setCurrentWidget(window.voice)
    recs.title.setChecked(True)
    QTest.qWait(10)
    it = recs._items[c.id]
    rect = recs.list.visualItemRect(it)
    button = recs.row_layout(rect).play.center()
    QTest.mouseClick(recs.list.viewport(), Qt.MouseButton.LeftButton, pos=button)
    assert played == [("voiceclips:preview", True)]
    assert recs._playing == ("voiceclips:preview", c.id)
    recs.list.setFocus()
    recs.list.setCurrentItem(it)
    QTest.keyClick(recs.list, Qt.Key.Key_Escape)
    assert recs._playing is None
    QTest.keyClick(recs.list, Qt.Key.Key_Return)            # Enter: through the mic
    assert played[-1] == ("voiceclips-send", False)
    recs._tick_play()
    assert recs._progress == 0.5
    mic = recs.row_actions.buttons["mic"]
    assert recs.row_actions.isVisible() and mic.toolTip() == "Stop sending"
    QTest.keyClick(recs.list, Qt.Key.Key_Space)             # Space: for me (stops sending)
    assert played[-1] == ("voiceclips:preview", True)
    recs.stop()
    assert mic.toolTip() == "Play through mic"


def _double_click(widget, pos):
    """A real mouse's double-click: press, release, double-click, release (QTest's
    mouseDClick sends the double-click event alone)."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    left, p = Qt.MouseButton.LeftButton, QPointF(pos)
    for kind, held in ((QEvent.Type.MouseButtonPress, left),
                       (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
                       (QEvent.Type.MouseButtonDblClick, left),
                       (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QApplication.sendEvent(widget, QMouseEvent(kind, p, widget.mapToGlobal(p), left, held,
                                                   Qt.KeyboardModifier.NoModifier))


def test_a_double_click_on_the_play_button_plays_once(window, monkeypatch):  # noqa: F811
    recs, played = _recs(window, monkeypatch)
    c = recs.add(np.full((SR // 2, 2), 0.2, np.float32), "Take", "My voice")
    window.resize(1200, 800)
    window.show()
    window.tabs.setCurrentWidget(window.voice)
    recs.title.setChecked(True)
    QTest.qWait(10)
    L = recs.row_layout(recs.list.visualItemRect(recs._items[c.id]))
    _double_click(recs.list.viewport(), L.play.center())
    assert played == [("voiceclips:preview", True)]          # not play, stop, play again
    assert recs._playing == ("voiceclips:preview", c.id)
    QTest.mouseClick(recs.list.viewport(), Qt.MouseButton.LeftButton, pos=L.play.center())
    assert recs._playing is None                              # the next click stops it
    _double_click(recs.list.viewport(), L.name.center())      # the row itself: plays too
    assert len(played) == 2 and recs._playing == ("voiceclips:preview", c.id)


def test_row_buttons_follow_the_hovered_row_and_the_waveform_gives_way(window, monkeypatch):  # noqa: F811
    recs, _played = _recs(window, monkeypatch)
    a = recs.add(np.full((SR, 2), 0.2, np.float32), "One", "My voice")
    b = recs.add(np.full((SR, 2), 0.2, np.float32), "Two", "My voice")
    window.resize(1200, 800)
    window.show()
    window.tabs.setCurrentWidget(window.voice)
    recs.title.setChecked(True)
    QTest.qWait(10)
    for c in (a, b):
        recs._entered(recs.list.indexFromItem(recs._items[c.id]))
        assert recs._actions_item is recs._items[c.id]
        rect = recs.list.visualItemRect(recs._items[c.id])
        assert rect.contains(recs.row_actions.geometry().center())
    wide = recs.row_layout(QRect(0, 0, 760, 44))
    narrow = recs.row_layout(QRect(0, 0, 440, 44))
    assert wide.wave is not None and narrow.wave is None
    for L in (wide, narrow):                       # nothing overlaps, nothing spills out
        parts = [L.play, L.name, L.length, L.actions] + ([L.wave] if L.wave else [])
        assert all(QRect(0, 0, 760 if L is wide else 440, 44).contains(q) for q in parts)
        assert not any(p.intersects(q) for i, p in enumerate(parts) for q in parts[i + 1:])
    recs.list.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    rtl = recs.row_layout(QRect(0, 0, 760, 44))
    assert rtl.play.right() == 760 - 1 - wide.play.left()   # mirrored
    recs.list.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    recs._hover = None
    recs.list.clearSelection()
    recs._place_actions()
    assert not recs.row_actions.isVisible()
