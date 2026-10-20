"""The Apps tab's clip editor, with the Windows capture faked: it's off and
unbuilt until a card's Clip editor is opened, opening it listens (and closing it
stops), and the waveform's mouse and keys pick, play, cut up and save a bit."""
import json

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from soundboard.audio import appaudio
from soundboard.audio.appaudio import App
from soundboard.sounds.clipedit import BIN
from soundboard.audio.engine import SR, Engine
from soundboard.sounds.library import Config
from soundboard.ui.apps import clipeditor
from soundboard.ui.apps.appspanel import AppsTab
from soundboard.ui.apps.clipeditor import ClipEditor, columns
from soundboard.ui.kit.widgets import Meter
from tests.test_appspanel import FakeCapture, music


class FakeEngine(Engine):
    """Plays nothing: remembers what it was asked to play."""

    def __init__(self):
        super().__init__()
        self.played = []
        self.live = set()

    def play(self, sid, data, gain, **kw):
        self.played.append((sid, len(data), kw))
        self.live.add(sid)
        return object()

    def stop(self, sid):
        self.live.discard(sid)

    def state(self, sid):
        return (0.5, False) if sid in self.live else None


@pytest.fixture
def tab(qapp, monkeypatch):
    monkeypatch.setattr(appaudio, "AppCapture", FakeCapture)
    running = []   # what the tab's own refreshes see running
    monkeypatch.setattr(appaudio, "list_apps", lambda **kw: list(running))
    monkeypatch.setattr(clipeditor, "clipboard", None)
    FakeCapture.made = []
    FakeCapture.fail = FakeCapture.slow = False
    t = AppsTab(FakeEngine(), Config(app_clip_group="newest"), lambda: None, Meter)
    t.clips = []
    t.running = running
    t.clip_ready.connect(lambda data, name: t.clips.append((data, name)))
    t.resize(900, 700)
    t.show()
    for _ in range(200):   # its first look (nothing running) lands before the test's own
        qapp.processEvents()
        if not t.lister._busy:
            break
        QTest.qWait(10)
    qapp.processEvents()
    yield t
    t.shutdown()
    t.deleteLater()


def tone(seconds, level=0.5, freq=440):
    n = int(seconds * SR)
    x = (level * np.sin(2 * np.pi * freq * np.arange(n) / SR)).astype(np.float32)
    return np.stack([x, x], 1)


def run(tab, *apps):
    tab.running[:] = apps
    tab._on_apps(list(apps))


def opened(tab, qapp):
    run(tab, music())
    row = tab.rows["music.exe"]
    row.btn_clip.click()
    qapp.processEvents()
    return row



def said(w, words: str) -> bool:
    """A corner card on ``w``'s window says ``words``."""
    from soundboard.ui.kit import toast
    return any(words in t.text() for t in toast.shown(w))

def test_folded_away_nothing_is_built_or_listening(tab, qapp):
    run(tab, music())
    qapp.processEvents()
    row = tab.rows["music.exe"]
    assert row.btn_clip.isVisible() and not row.btn_clip.isChecked()
    assert row.editor is None and row.listen is None and row.capture is None
    assert not FakeCapture.made


def test_opening_listens_and_closing_stops(tab, qapp):
    row = opened(tab, qapp)
    assert row.editor is not None and row.editor.isVisible()
    assert row.listen is not None and row.capture is not None and row.capture.started
    assert not row.btn_forget.isVisible()   # no ✕ while it listens
    row.capture.sink(tone(2.0))
    assert row.listen.seconds == pytest.approx(2.0, abs=BIN / SR)
    assert row.editor.timer.isActive()      # live and on screen: it redraws
    cap = row.capture
    row.btn_clip.click()
    assert row.listen is None and row.capture is None and cap.stopped
    assert not row.editor.isVisible() and not row.editor.timer.isActive()
    assert row.btn_forget.isVisible()


def test_closing_while_sending_keeps_the_send(tab, qapp):
    row = opened(tab, qapp)
    row.btn_send.click()
    cap = row.capture
    row.btn_clip.click()
    assert row.capture is cap and not cap.stopped and row.sending
    row.btn_send.click()
    assert cap.stopped


def test_capture_failing_leaves_it_quiet(tab, qapp):
    FakeCapture.fail = True
    row = opened(tab, qapp)
    assert row.listen is None and row.capture is None
    assert row.editor.buf is None and not row.editor.timer.isActive()


def test_drag_selects_and_save_adds_just_that_bit(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(4.0))
    qapp.processEvents()
    w = ed.wave
    y = w.height() // 2
    # live, the last minute fills the width with "now" on the right: 4 s is the right end
    ed.peaks()   # sets the live view
    x_a = int(w.x_of(ed.view[1] - 3 * SR))
    x_b = int(w.x_of(ed.view[1] - 1 * SR))
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, QPoint(x_a, y))
    assert ed.take is not None   # the press froze it
    QTest.mouseMove(w, QPoint(x_b, y))
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(x_b, y))
    t = ed.take
    assert t.has_selection and (t.b - t.a) / SR == pytest.approx(2.0, abs=0.15)
    assert not ed.timer.isActive()   # frozen and quiet: no redraws
    QTest.keyClick(w, Qt.Key_Return)
    assert not tab.clips   # not straight into Sounds: into Saved clips, under the cards
    (c,) = tab.shelf.shelf.clips
    assert len(c.audio()) == t.b - t.a and c.name.startswith(c.src) and c.src
    assert said(ed, "Saved clips") and tab.shelf.isVisible()


def test_saving_the_whole_take_trims_dead_air(tab, qapp):
    row = opened(tab, qapp)
    row.capture.sink(np.concatenate([np.zeros((SR, 2), np.float32), tone(1.0),
                                     np.zeros((SR, 2), np.float32)]))
    row.editor.save()
    data = tab.shelf.shelf.clips[0].audio()
    # the silence before it was never kept; after it, the pad trim_silence leaves
    assert len(data) / SR == pytest.approx(1.05, abs=0.02)


def test_saving_again_with_nothing_new_says_so(tab, qapp):
    """Save to clips, again with nothing heard since: it kept a second copy, no word."""
    row = opened(tab, qapp)
    row.capture.sink(tone(1.0))
    row.editor.save()
    row.editor.save()
    assert len(tab.shelf.shelf.clips) == 1
    assert "Nothing new" in row.editor.info.text()
    row.capture.sink(tone(1.0, freq=660))   # something new: it saves
    row.editor.save()
    assert len(tab.shelf.shelf.clips) == 2


def test_the_program_closing_under_its_open_editor_says_so(tab, qapp):
    row = opened(tab, qapp)
    run(tab)   # it quit
    assert said(row.editor, "closed")


def test_preview_only_goes_to_headphones(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(3.0))
    ed.freeze()
    ed.take.select(SR, 2 * SR)
    ed.toggle_play()
    sid, n, kw = tab.engine.played[-1]
    assert sid.endswith(":preview") and kw["preview"] and n == SR
    assert ed.playhead() == pytest.approx(1.5 * SR)
    ed.toggle_play()   # again: stops
    assert ed._play is None and sid not in tab.engine.live
    assert not hasattr(ed, "btn_send")


def test_cut_and_paste_into_another_programs_editor(tab, qapp):
    run(tab, music(), App(200, "game.exe", r"C:\Games\game.exe", "Game", True, 0.3,
                          ["Speakers"]))
    a, b = tab.rows["music.exe"], tab.rows["game.exe"]
    a.btn_clip.click()
    b.btn_clip.click()
    a.capture.sink(tone(2.0, 0.5))
    b.capture.sink(tone(1.0, 0.2))
    ea, eb = a.editor, b.editor
    ea.freeze()
    ea.take.select(0, SR // 2)
    assert ea.cut() and len(ea.take) == pytest.approx(1.5 * SR, abs=BIN)
    eb.freeze()
    eb.take.select(len(eb.take), len(eb.take))
    assert eb.paste()
    assert len(eb.take) == pytest.approx(1.5 * SR, abs=BIN)
    eb.undo()
    assert len(eb.take) == pytest.approx(1.0 * SR, abs=BIN)


def test_edit_menu_actions_and_shortcuts_exist(qapp):   # a widget needs the app first
    ed = ClipEditor(FakeEngine(), Config())
    names = set(ed.actions_by_name)
    assert {"cut", "copy", "paste", "delete", "undo", "redo", "fade_in", "fade_out",
            "louder", "quieter", "reverse", "crop"} <= names
    assert ed.actions_by_name["copy"].shortcutContext() == Qt.WidgetWithChildrenShortcut
    ed._enable_actions()   # nothing held: nothing to do, and no crash
    assert not ed.actions_by_name["cut"].isEnabled()
    ed.shutdown()


def test_live_after_editing_can_be_undone(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(2.0))
    ed.freeze()
    ed.take.select(0, SR)
    ed._edit(lambda t: t.delete())
    edited = ed.take
    ed.go_live()
    assert ed.take is None and ed.timer.isActive()
    ed.undo()
    assert ed.take is edited


def test_closing_lets_an_unedited_take_go_but_keeps_an_edited_one(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(2.0))
    ed.freeze()
    row.btn_clip.click()
    assert ed.take is None
    row.btn_clip.click()
    row.capture.sink(tone(2.0))
    ed.freeze()
    ed.take.select(0, SR)
    ed._edit(lambda t: t.fade_in())
    row.btn_clip.click()
    assert ed.take is not None
    # the program quits: a card with an edit on it stays, though it isn't remembered
    run(tab)
    assert "music.exe" in tab.rows


def test_zoom_and_pan_stay_inside_the_take(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(10.0))
    ed.freeze()
    ed.fit()
    assert ed.view == (0.0, pytest.approx(len(ed.take)))
    for _ in range(40):
        ed.zoom(0.5)
    assert ed.view[1] - ed.view[0] == clipeditor.MIN_VIEW
    ed.pan(-10 * SR)
    assert ed.view[0] == 0
    ed.pan(100 * SR)
    assert ed.view[1] == pytest.approx(len(ed.take))


def test_columns_map_frames_to_pixels():
    peaks = np.array([0.1, 0.9, 0.2, 0.4], np.float32)
    n = len(peaks) * BIN
    assert np.allclose(columns(peaks, 0, n, 4), peaks)
    assert np.allclose(columns(peaks, 0, n, 2), [0.9, 0.4])
    # zoomed in past one column per pixel: each pixel shows its column
    assert np.allclose(columns(peaks, BIN, 2 * BIN, 3), 0.9)
    # a view running off either end is empty there
    out = columns(peaks, -n, n, 8)
    assert np.allclose(out[:4], 0) and np.allclose(out[4:], peaks)
    assert not columns(np.zeros(0, np.float32), 0, 10, 5).any()


def test_paints_in_every_state(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    ed.wave.grab()                      # live, nothing heard yet
    row.capture.sink(tone(2.0))
    ed.wave.grab()                      # live
    ed.freeze()
    ed.wave.grab()                      # cursor only
    ed.take.select(SR // 2, SR)
    ed.toggle_play()
    ed.wave.grab()                      # selection and playhead
    ed.resize(200, 200)                 # narrow: words remain, controls wrap
    assert ed.btn_play.text() == "Stop"


def test_live_view_shows_only_what_was_heard(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(2.0))
    ed.peaks()
    assert ed.view[1] - ed.view[0] == clipeditor.LIVE_MIN_S * SR   # short: at least 10 s
    row.capture.sink(tone(38.0))
    ed.peaks()
    assert ed.view[1] - ed.view[0] == pytest.approx(40 * SR, abs=BIN)   # no empty minute
    row.capture.sink(tone(50.0))
    ed.peaks()
    assert ed.view[1] - ed.view[0] == row.listen.cols * BIN            # full: the last minute


def test_buttons_wake_up_when_the_first_sound_arrives(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    assert not ed.btn_play.isEnabled() and not ed.btn_save.isEnabled()
    row.capture.sink(tone(1.0))
    ed._tick()
    assert ed.btn_play.isEnabled() and ed.btn_save.isEnabled()


# ---------------------------------------------------------------------- saved clips

def saved(tab, qapp, seconds=1.0):
    row = opened(tab, qapp)
    row.capture.sink(tone(seconds))
    row.editor.freeze()
    row.editor.select_all()
    row.editor.save()
    return row


def test_saved_clips_play_rename_add_and_delete_with_undo(tab, qapp):
    saved(tab, qapp)
    sh = tab.shelf
    assert sh.list.topLevelItemCount() == 1
    it = sh.list.topLevelItem(0)
    sh.list.setCurrentItem(it)
    sh.list.itemDoubleClicked.emit(it, 0)            # double-click: plays in the headphones
    assert tab.engine.played[-1][2].get("preview") and sh._playing is not None
    sh.list.itemDoubleClicked.emit(it, 0)            # again: stops
    assert sh._playing is None
    it.setText(0, "airhorn bit")                     # renamed in the list
    assert sh.shelf.clips[0].name == "airhorn bit"
    it.setText(0, "   ")                             # nothing: back to the old name
    assert it.text(0) == "airhorn bit" and sh.shelf.clips[0].name == "airhorn bit"
    sh.add_picked()                                  # right-click → Add to Sounds
    (data, name), = tab.clips
    assert name == "airhorn bit" and len(data) == SR
    sh.delete_picked()
    assert not sh.shelf.clips and sh.undo_bar.active()
    sh.undo_bar.undo()
    assert [c.name for c in sh.shelf.clips] == ["airhorn bit"]


def test_saved_clips_are_kept_for_next_time(tab, qapp):
    from soundboard.sounds.clipshelf import Shelf
    ed = saved(tab, qapp).editor
    ed.freeze()
    ed.take.select(0, SR // 2)
    ed.save()                                        # a second clip: half of it
    gone = tab.shelf.shelf.clips[0]
    assert gone.seconds == pytest.approx(0.5, abs=0.01)
    tab.shelf.list.setCurrentItem(tab.shelf._item(gone.id))
    tab.shelf.delete_picked()
    again = Shelf()                                  # the next start
    assert len(again.clips) == 1 and again.clips[0].id != gone.id
    assert not gone.path.exists()                    # a deleted one's file is tidied up


def test_copy_marks_the_clipboard_so_the_sounds_tab_can_paste_it(tab, qapp):
    from PySide6.QtWidgets import QApplication
    row = opened(tab, qapp)
    row.capture.sink(tone(1.0))
    row.editor.freeze()
    row.editor.select_all()
    row.editor.copy()
    got = clipeditor.pasted_clip()
    assert got is not None and len(got) == SR
    assert said(row.editor, "Sounds tab")
    QApplication.clipboard().setText("something else copied since")
    assert clipeditor.pasted_clip() is None          # the newer copy wins


def test_big_view_gives_one_card_the_tab(tab, qapp):
    other = App(200, "other.exe", r"C:\Programs\other.exe", "Other", True, 0.3, ["Speakers"])
    run(tab, music(), other)
    row, rest = tab.rows["music.exe"], tab.rows["other.exe"]
    row.btn_clip.click()
    qapp.processEvents()
    assert tab.big is row and not rest.isVisible()
    row.editor.btn_big.click()
    qapp.processEvents()
    h_rest = rest.height()
    assert h_rest < row.height()      # an open editor doesn't stretch the card next to it
    row.editor.btn_big.click()
    qapp.processEvents()
    assert tab.big is row and not rest.isVisible() and row.width() > tab.width() * 0.8
    assert row.editor.wave.minimumHeight() > clipeditor.WAVE_H
    row.btn_clip.click()              # closing the editor leaves the big view
    qapp.processEvents()
    assert tab.big is None and rest.isVisible() and not row.editor.btn_big.isChecked()
    assert row.editor.wave.minimumHeight() == clipeditor.WAVE_H


def test_click_copy_paste_with_real_keys_does_something(tab, qapp):
    """What a user does: a click (the hand wobbles a pixel), Ctrl+C, Ctrl+V. The
    click is a cursor, not a 0.1 s selection; the paste says what it did."""
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(4.0))
    qapp.processEvents()
    w = ed.wave
    y = w.height() // 2
    ed.peaks()   # sets the live view, as a paint would
    x = int(w.x_of(ed.view[1] - 2 * SR))   # 2 s back from now
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseMove(w, QPoint(x + 1, y))
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(x + 1, y))
    t = ed.take
    assert not t.has_selection and t.a > 0           # just a cursor
    n = len(t)
    QTest.keyClick(w, Qt.Key_C, Qt.ControlModifier)  # nothing picked: copies it all
    assert said(ed, "Copied all of it")
    QTest.keyClick(w, Qt.Key_V, Qt.ControlModifier)
    assert len(ed.take) == 2 * n and said(ed, "Pasted 0:04.00")
    QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier)
    assert len(ed.take) == n


def test_paste_over_what_was_just_copied_duplicates_it(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(4.0))
    ed.freeze()
    ed.take.select(SR, 2 * SR)
    w = ed.wave
    w.setFocus()
    QTest.keyClick(w, Qt.Key_C, Qt.ControlModifier)
    QTest.keyClick(w, Qt.Key_V, Qt.ControlModifier)
    t = ed.take
    assert len(t) == 5 * SR and (t.a, t.b) == (2 * SR, 3 * SR)   # a second copy, after it
    assert said(ed, "Pasted 0:01.00 at 0:02.00")


def test_a_paused_program_doesnt_fill_the_editor_with_silence(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    quiet = np.zeros((40 * SR, 2), np.float32)
    row.capture.sink(quiet)                          # nothing playing yet
    assert ed.length() == 0
    row.capture.sink(np.concatenate([tone(2.0), quiet, tone(1.0), quiet]))
    assert ed.length() / SR == pytest.approx(2.0 + 0.5 + 1.0 + 0.5, abs=0.02)


def test_save_returns_to_live_and_new_audio_appears_without_reopening(tab, qapp):
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(2.0))
    ed.freeze()
    ed.take.select(0, SR)
    row.capture.sink(tone(3.0))
    ed.save()
    assert ed.take is None and ed.timer.isActive()
    assert row.btn_clip.isChecked() and row.capture is not None
    row.capture.sink(tone(1.0))
    ed._tick()
    assert ed.length() == 6 * SR
    assert len(tab.shelf.shelf.clips[0].audio()) == SR
    ed.undo()
    assert ed.take is not None and ed.take.has_selection


def test_failed_save_preserves_the_edit(tab, qapp, monkeypatch):
    row = opened(tab, qapp)
    row.capture.sink(tone(2.0))
    ed = row.editor
    take = ed.freeze()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(tab.shelf, "add", fail)
    ed.save()
    assert ed.take is take


def test_editor_and_shelf_have_usable_targets_and_stay_together(tab, qapp):
    row = saved(tab, qapp)
    ed = row.editor
    assert not row.chk_hear.isVisible()
    for b in (ed.btn_live, ed.btn_play, ed.btn_save, ed.btn_edit, ed.btn_trim, ed.btn_undo):
        assert b.minimumHeight() >= 36 and b.accessibleName()
    assert ed.wave.minimumHeight() >= 180
    assert ed.btn_edit.menu().minimumWidth() >= 280
    assert tab.shelf.parentWidget() is tab.list
    assert tab.shelf.list.sizeHintForRow(0) >= 36
    assert tab.shelf.y() < row.geometry().bottom() + 80


def test_saved_clips_resize_with_mouse_and_keyboard_and_reset(tab, qapp):
    saved(tab, qapp)
    sh = tab.shelf
    handle = sh.resize_handle
    before = sh.list.height()
    pos = handle.rect().center()
    QTest.mousePress(handle, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.mouseMove(handle, pos + QPoint(0, 100))
    QTest.mouseRelease(handle, Qt.LeftButton, Qt.NoModifier, pos + QPoint(0, 100))
    assert sh.list.height() == before + 100
    assert tab.cfg.app_clip_height == before + 100
    QTest.keyClick(handle, Qt.Key_Down)
    assert sh.list.height() == before + 136
    sh.reload()
    assert sh.list.height() == before + 136
    QTest.mouseDClick(handle, Qt.LeftButton)
    assert sh.list.height() == before and tab.cfg.app_clip_height == 0
    sh.resize_clips(10000)
    assert sh.list.height() == 600
    sh.resize_clips(-100)
    assert sh.list.height() == 72


def test_empty_saved_clips_cannot_resize_and_undo_restores_height(tab, qapp):
    sh = tab.shelf
    assert not sh.isVisible() and not sh.resize_handle.isVisible()
    sh.resize_clips(400)
    assert tab.cfg.app_clip_height == 0
    saved(tab, qapp)
    sh.resize_clips(400)
    handle = sh.resize_handle
    QTest.mousePress(handle, Qt.LeftButton, Qt.NoModifier, handle.rect().center())
    assert handle._drag is not None
    sh.delete_picked()
    qapp.processEvents()
    assert sh.undo_bar.active()
    assert not sh.isVisible() and not handle.isVisible() and handle._drag is None
    assert sh.list.height() == sh._fit_height
    QTest.keyClick(handle, Qt.Key_Down)
    QTest.mouseDClick(handle, Qt.LeftButton)
    sh.resize_clips(500)
    assert tab.cfg.app_clip_height == 400
    sh.undo_bar.undo()
    qapp.processEvents()
    assert sh.isVisible() and handle.isVisible() and sh.list.height() == 400
    sh.delete_picked()
    sh.undo_bar.finish()
    assert not sh.isVisible()
    sh.add(tone(1), "New clip")
    qapp.processEvents()
    assert sh.isVisible() and handle.isVisible() and sh.list.height() == 400


def test_edit_menu_only_opens_when_an_action_is_available(tab, qapp, monkeypatch):
    row = opened(tab, qapp)
    ed = row.editor
    assert not any(a.isEnabled() for a in ed.actions_by_name.values())
    assert not ed.btn_edit.isEnabled()
    clipeditor.set_clipboard(tone(1))
    qapp.processEvents()
    assert ed.actions_by_name["paste"].isEnabled() and ed.btn_edit.isEnabled()
    monkeypatch.setattr(clipeditor, "clipboard", None)
    ed._enable_actions()
    assert not ed.btn_edit.isEnabled()
    row.capture.sink(tone(1))
    ed._tick()
    assert ed.btn_edit.isEnabled() and ed.actions_by_name["copy"].isEnabled()
    assert not ed.actions_by_name["cut"].isEnabled()


def test_large_shelf_groups_searches_and_cancels_stale_batches(tab, qapp):
    import time
    from dataclasses import replace
    sh = tab.shelf
    seed = sh.add(tone(0.1), "Example", "Music")
    now = time.time()
    sh.shelf.clips = [replace(seed, id=f"clip{i}", name=f"Clip {i}",
                              src="Music" if i % 2 == 0 else "Browser",
                              made=now - (i % 4) * 86400)
                      for i in range(2000)]
    sh.group_by.setCurrentIndex(sh.group_by.findData("app"))
    assert len(sh._items) <= 100 and sh._fill_timer.isActive()
    for _turn in range(100):
        qapp.processEvents()
        if not sh._fill_timer.isActive():
            break
    assert len(sh._items) == 2000 and sh.list.topLevelItemCount() == 2
    assert len(sh._groups) == 6  # two apps, two days within each app
    assert all(not sh.list.topLevelItem(i).isExpanded() for i in range(2))
    sh.list.setCurrentItem(sh._item("clip0"))
    sh.toggle_play()
    playing = sh._playing
    assert playing is not None
    sh.list.itemDoubleClicked.emit(sh.list.topLevelItem(0), 0)
    assert sh._playing == playing  # group expansion does not interrupt a preview
    sh.stop()
    sh.search.setText("Clip 1999")
    for _turn in range(100):
        qapp.processEvents()
        if not sh._fill_timer.isActive():
            break
    assert list(sh._items) == ["clip1999"]
    it = sh._item("clip1999")
    assert it is not None and it.text(3) == sh._created(sh.shelf.get("clip1999"))
    sh.search.setText("no match")
    for _turn in range(100):
        qapp.processEvents()
        if not sh._fill_timer.isActive():
            break
    assert sh.empty.isVisible() and not sh.resize_handle.isVisible()
    assert sh.list.height() == sh._fit_height
    before = tab.cfg.app_clip_height
    sh.resize_clips(500)
    assert tab.cfg.app_clip_height == before
    sh.search.clear()
    sh.group_by.setCurrentIndex(sh.group_by.findData("day"))
    sh.search.setText("Browser")  # cancels unfinished app/day filling
    for _turn in range(100):
        qapp.processEvents()
        if not sh._fill_timer.isActive():
            break
    assert len(sh._items) == 1000 and sh.list.topLevelItemCount() == 2
    assert all(sh.shelf.get(cid).src == "Browser" for cid in sh._items)


def test_background_cleanup_hides_last_clip_and_undo_restores_it(tab, qapp):
    from soundboard.sounds.clipshelf import DAY
    saved(tab, qapp)
    sh = tab.shelf
    c = sh.shelf.clips[0]
    sh.toggle_play()
    tab.engine.stop(sh._playing[0])  # preview finished naturally; the tuple may still exist
    c.last_used = DAY
    sh._maintain()
    sh._worker.join(5)
    qapp.processEvents()
    assert not sh.shelf.clips and sh.undo_bar.active() and not sh.isVisible()
    sh.undo_bar.undo()
    sh._worker.join(5)
    qapp.processEvents()
    assert sh.shelf.get(c.id) is not None and sh.isVisible()


def test_a_clip_whose_file_was_deleted_leaves_the_list_when_apps_is_opened_again(tab, qapp):
    saved(tab, qapp)
    sh = tab.shelf
    if sh._worker is not None:
        sh._worker.join(5)
    sh.shelf.clips[0].path.unlink()
    tab.hide()
    tab.show()
    sh._worker.join(5)
    qapp.processEvents()
    assert not sh.shelf.clips and not sh._items
    assert json.loads(sh.shelf._index().read_text("utf-8")) == []


def test_preview_and_copy_refresh_activity(tab, qapp):
    saved(tab, qapp)
    sh = tab.shelf
    c = sh.shelf.clips[0]
    c.last_used = 1
    sh.toggle_play()
    assert c.last_used > 1
    sh.stop()
    c.last_used = 1
    sh.copy_picked()
    assert c.last_used > 1
    c.last_used = 1
    sh.add_picked()
    assert c.last_used > 1


def test_saved_clips_fold_to_header_and_restore_search_and_height(tab, qapp):
    from soundboard.ui.apps.clipshelf import ClipShelf
    saved(tab, qapp)
    sh = tab.shelf
    sh.resize_clips(200)
    sh.search.setText("music")
    qapp.processEvents()
    expanded = sh.sizeHint().height()
    sh.title.click()
    qapp.processEvents()
    assert sh.isVisible() and not sh.body.isVisible() and not sh.hint.isVisible()
    assert not sh.resize_handle.isVisible() and not tab.cfg.app_clips_expanded
    tab.cfg.save()
    assert not Config.load().app_clips_expanded
    assert sh.sizeHint().height() < expanded and sh.sizeHint().height() <= 40
    sh.resize_clips(500)
    assert tab.cfg.app_clip_height == 200
    rebuilt = ClipShelf(tab.engine, tab.cfg)
    assert not rebuilt.title.isChecked()
    rebuilt.shutdown()
    rebuilt.deleteLater()
    sh.title.click()
    qapp.processEvents()
    assert sh.body.isVisible() and sh.hint.isVisible() and sh.resize_handle.isVisible()
    assert sh.search.text() == "music" and sh.list.height() == 200


def test_save_destination_is_explicit_and_show_clips_reveals_a_folded_shelf(tab, qapp):
    row = opened(tab, qapp)
    assert row.editor.btn_save.text() == "Save to clips"
    assert "Saved clips" in row.btn_rec.toolTip()
    tab.shelf.title.setChecked(False)
    row.capture.sink(tone(1))
    row.editor.save()
    assert not tab.shelf.body.isVisible() and len(tab.shelf.shelf.clips) == 1
    from soundboard.ui.kit import toast
    cards = [t for t in toast.shown(tab) if "Kept" in t.words()]
    assert cards and cards[-1].card.action.text() == "Show clips"
    cards[-1].card.action.click()
    qapp.processEvents()
    assert tab.shelf.body.isVisible() and tab.shelf.list.hasFocus()


def test_keyboard_paste_updates_when_another_editor_copies(tab, qapp):
    run(tab, music(), App(200, "game.exe", r"C:\Games\game.exe", "Game", True, 0.3,
                          ["Speakers"]))
    a, b = tab.rows["music.exe"], tab.rows["game.exe"]
    a.btn_clip.click()
    a.capture.sink(tone(1))
    b.btn_clip.click()
    b.capture.sink(tone(1))
    b.editor.freeze()
    assert not b.editor.actions_by_name["paste"].isEnabled()
    a.editor.copy()
    assert b.editor.actions_by_name["paste"].isEnabled()
    qapp.processEvents()
    b.editor.wave.setFocus()
    qapp.processEvents()
    QTest.keyClick(b.editor.wave, Qt.Key_V, Qt.ControlModifier)
    assert len(b.editor.take) == 2 * SR


@pytest.mark.parametrize("width", [240, 360, 480])
def test_card_sizes_wrap_readable_controls_without_overlap(tab, qapp, width):
    row = opened(tab, qapp)
    tab._set_big(row, False)
    tab.resize(1700, 900)
    tab.card_size.setValue(width)
    qapp.processEvents()
    ed = row.editor
    buttons = [ed.btn_save, ed.btn_live, ed.btn_play, ed.btn_edit, ed.btn_trim, ed.btn_undo]
    for b in buttons:
        assert b.text() and b.width() >= b.minimumSizeHint().width()
        assert ed.rect().contains(b.geometry())
    for i, a in enumerate(buttons):
        assert all(not a.geometry().intersects(b.geometry()) for b in buttons[i + 1:])


def test_the_waveform_is_drawn_on_a_fixed_scale():
    # not stretched to the loudest bit in view: Louder / Quieter show, near-silence
    # stays small, and nothing jumps as a loud bit scrolls out of a live view
    from soundboard.ui.apps.clipeditor import heights
    h = heights(np.array([0.001, 0.1, 0.5, 1.0, 2.0], np.float32), 50.0)
    assert h[0] < 2 and h[1] < h[2] < h[3] == h[4] == 50.0
    assert h[1] > 50.0 / 4                       # -20 dB is still easy to see
    assert heights(np.array([0.1], np.float32), 50.0)[0] == h[1]   # same alone or not
    louder = heights(np.array([0.5 * 10 ** (clipeditor.STEP_DB / 20)], np.float32), 50.0)
    assert louder[0] > h[2] + 5                  # Louder visibly grows it


def test_the_clip_editor_button_says_what_it_opens(tab, qapp):
    run(tab, music())
    row = tab.rows["music.exe"]
    assert "last minute" in row.btn_clip.toolTip() and "Freeze" not in row.btn_clip.toolTip()


def test_trim_shows_all_of_what_is_left(tab, qapp):
    row = opened(tab, qapp)
    row.capture.sink(tone(6.0))
    ed = row.editor
    ed.freeze()
    ed.take.select(SR, 2 * SR)
    ed._sync()
    ed.btn_trim.click()
    assert len(ed.take) == SR
    assert ed.view == (0.0, float(SR))   # not a sliver at the left of a 6 s view


def test_after_pause_the_waveform_takes_the_keys(tab, qapp):
    """Pause left the focus on its own button, so Home, Ctrl+Right and Shift+End went
    to a button that takes none of them."""
    row = opened(tab, qapp)
    ed = row.editor
    row.capture.sink(tone(4.0))
    qapp.processEvents()
    tab.activateWindow()
    qapp.processEvents()
    QTest.mouseClick(ed.btn_live, Qt.LeftButton)
    qapp.processEvents()
    assert ed.take is not None and ed.wave.hasFocus()
    win = tab.windowHandle()
    QTest.keyClick(win, Qt.Key_Home)
    assert (ed.take.a, ed.take.b) == (0, 0)
    QTest.keyClick(win, Qt.Key_Right, Qt.ControlModifier)
    a = ed.take.a
    assert a > 0 and ed.take.b == a
    QTest.keyClick(win, Qt.Key_End, Qt.ShiftModifier)
    assert (ed.take.a, ed.take.b) == (a, len(ed.take))
