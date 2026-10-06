"""The Apps tab's clip editor, with the Windows capture faked: it's off and
unbuilt until a card's Clip editor is opened, opening it listens (and closing it
stops), and the waveform's mouse and keys pick, play, cut up and save a bit."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from soundboard import appaudio
from soundboard.appaudio import App
from soundboard.clipedit import BIN
from soundboard.engine import SR, Engine
from soundboard.library import Config
from soundboard.ui import clipeditor
from soundboard.ui.appspanel import AppsTab
from soundboard.ui.clipeditor import ClipEditor, columns
from soundboard.ui.widgets import Meter
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
    monkeypatch.setattr(appaudio, "list_apps", lambda: list(running))
    monkeypatch.setattr(clipeditor, "clipboard", None)
    FakeCapture.made = []
    FakeCapture.fail = FakeCapture.slow = False
    t = AppsTab(FakeEngine(), Config(), lambda: None, Meter)
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
    assert "Saved clips" in ed.info.text() and tab.shelf.isVisible()


def test_saving_the_whole_take_trims_dead_air(tab, qapp):
    row = opened(tab, qapp)
    row.capture.sink(np.concatenate([np.zeros((SR, 2), np.float32), tone(1.0),
                                     np.zeros((SR, 2), np.float32)]))
    row.editor.save()
    data = tab.shelf.shelf.clips[0].audio()
    assert len(data) / SR == pytest.approx(1.1, abs=0.05)


def test_play_and_send_go_to_the_right_place(tab, qapp):
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
    ed.toggle_send()
    sid, n, kw = tab.engine.played[-1]
    assert not sid.endswith(":preview") and not kw.get("preview") and n == SR
    assert ed.btn_send.property("full_text") == "Stop"


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
    ed.resize(200, 200)                 # narrow: icons only
    assert ed.btn_play.text() == ""


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
    assert ed.btn_play.isEnabled() and ed.btn_save.isEnabled() and ed.btn_send.isEnabled()


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
    assert not sh.shelf.clips and sh.undo_bar.isVisible()
    sh.undo_bar.undo()
    assert [c.name for c in sh.shelf.clips] == ["airhorn bit"]


def test_saved_clips_are_kept_for_next_time(tab, qapp):
    from soundboard.clipshelf import Shelf
    ed = saved(tab, qapp).editor
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
    assert "Sounds tab" in row.editor.info.text() and row.editor.info.wordWrap()
    QApplication.clipboard().setText("something else copied since")
    assert clipeditor.pasted_clip() is None          # the newer copy wins


def test_big_view_gives_one_card_the_tab(tab, qapp):
    other = App(200, "other.exe", r"C:\Programs\other.exe", "Other", True, 0.3, ["Speakers"])
    run(tab, music(), other)
    row, rest = tab.rows["music.exe"], tab.rows["other.exe"]
    row.btn_clip.click()
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
