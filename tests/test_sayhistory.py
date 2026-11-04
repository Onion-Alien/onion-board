"""The Say bar's extras, offscreen: the history pop-up, Up / Down in the box, the
long-text box, the quick box and saying what's copied."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from soundboard.speech import tts
from soundboard.ui.voice import saybig, sayhistory
from soundboard.ui.window.upnext import _Name
from tests.conftest import process_events
from test_voicepanel import FakeEngine


@pytest.fixture
def sp(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {"voice": ""})
    monkeypatch.setattr(p.speech.ctl, "start_live", lambda *a, **k: None)
    said = []
    monkeypatch.setattr(p.speech.ctl, "say", said.append)
    p.speech.said = said
    p.resize(1200, 800)
    p.show()
    yield p.speech
    for w in (p.speech._history_pop, p.speech._big_pop, p.speech._quick):
        if w is not None:
            w.close()
    p.shutdown()
    p.deleteLater()


def key(w, k):
    QApplication.sendEvent(w, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


def test_lines_said_are_kept_newest_last_and_saved_in_the_settings(sp):
    saved = []
    sp.changed.connect(saved.append)
    for t in ("one", "two"):
        sp.ed.setText(t)
        sp.b_say.click()
    sp.say_line("from a deck", "api")
    assert [e["text"] for e in sp.history] == ["one", "two", "from a deck"]
    assert sp.history[-1]["src"] == "api"
    assert saved[-1][sayhistory.HISTORY_KEY] == sp.history


def test_the_history_survives_a_restart_and_bad_entries_are_dropped():
    raw = [{"t": 1, "text": "ok", "src": "chat"}, {"text": ""}, "junk", {"t": True, "text": "x",
                                                                        "src": "evil"}]
    assert sayhistory.clean_history(raw) == [{"t": 1.0, "text": "ok", "src": "chat"},
                                             {"t": 0.0, "text": "x", "src": "typed"}]
    many = [{"t": i, "text": str(i)} for i in range(sayhistory.HISTORY_MAX + 50)]
    assert len(sayhistory.clean_history(many)) == sayhistory.HISTORY_MAX


def test_up_and_down_in_the_box_bring_back_the_lines_said(sp):
    for t in ("first", "second"):
        sp.say_line(t)
    key(sp.ed, Qt.Key.Key_Up)
    assert sp.ed.text() == "second"
    key(sp.ed, Qt.Key.Key_Up)
    key(sp.ed, Qt.Key.Key_Up)   # stays at the oldest
    assert sp.ed.text() == "first"
    key(sp.ed, Qt.Key.Key_Down)
    assert sp.ed.text() == "second"
    key(sp.ed, Qt.Key.Key_Down)   # past the newest: a new line
    assert sp.ed.text() == ""


def test_history_rows_say_copy_edit_and_say_picked_in_order(sp, qapp):
    for t in ("a", "b", "c"):
        sp.say_line(t)
    sp.said.clear()
    sp.act_history.trigger()
    pop = sp._history_pop
    assert pop.isVisible() and pop.count.text() == "3"
    rows = [pop.rows_v.itemAt(i).widget() for i in range(3)]   # newest first
    assert [r.findChild(_Name).full for r in rows] == ["c", "b", "a"]
    btn = {b.accessibleName(): b for b in rows[2].findChildren(QPushButton)}
    btn["Copy it"].click()
    assert QGuiApplication.clipboard().text() == "a"
    for _ in range(3):
        btn["Say it again"].click()
    # said again, but no new rows: the line is in the list already
    assert sp.said == ["a", "a", "a"]
    assert [e["text"] for e in sp.history] == ["a", "b", "c"]
    assert pop.count.text() == "3"
    # tick a and c: said in the order they were said, not the order ticked
    rows[2].findChild(QCheckBox).setChecked(True)   # "a"
    rows[0].findChild(QCheckBox).setChecked(True)   # "c"
    assert pop.b_picked.text() == "Say picked (2)"
    sp.said.clear()
    pop.b_picked.click()
    assert sp.said == ["a", "c"]
    assert [e["text"] for e in sp.history] == ["a", "b", "c"]
    process_events(qapp, lambda: False, timeout=0.2)
    # the list refills once per line said: its old rows never pop up as windows of
    # their own, which closed the pop-up
    assert pop.isVisible()
    assert not [t for t in QApplication.topLevelWidgets()
                if t.isVisible() and t.objectName() == "chip"]
    pop.search.setText("zzz")
    assert pop.empty.isVisible() and not pop.list_area.isVisible()


def test_say_again_says_the_last_line_said_not_the_last_row(sp):
    for t in ("a", "b", "c"):
        sp.say_line(t)
    sp.open_history()
    rows = [sp._history_pop.rows_v.itemAt(i).widget() for i in range(3)]   # newest first
    btn = {b.accessibleName(): b for b in rows[2].findChildren(QPushButton)}
    btn["Say it again"].click()                                            # "a": no new row
    sp.said.clear()
    assert sp.say_again() == "a" and sp.said == ["a"]
    assert [e["text"] for e in sp.history] == ["a", "b", "c"]
    sp.say_line("d")
    assert sp.say_again() == "d"


def test_say_again_after_a_restart_says_the_newest_row(sp):
    sp.say_line("a")
    sp.say_line("b")
    sp._last_said = ""                  # nothing said yet in this run
    assert sp.say_again() == "b"


def test_say_again_after_clearing_the_history_says_nothing(sp):
    sp.say_line("secret")
    sp._clear_history()
    sp.said.clear()
    assert sp.say_again() == "" and sp.said == []


def test_say_picked_with_nothing_ticked_says_what_to_do(sp):
    sp.say_line("x")
    sp.open_history()
    sp._history_pop.b_picked.click()
    assert sp._history_pop.b_picked.text() == "Tick some lines first"


def test_clear_forgets_the_history(sp):
    sp.say_line("secret")
    sp.open_history()
    sp._history_pop.b_clear.click()
    assert sp.history == [] and sp.s[sayhistory.HISTORY_KEY] == []


def test_the_long_text_box_says_each_line_and_the_selection(sp):
    sp.ed.setText("carried over")
    sp.act_big.trigger()
    big = sp._big_pop
    assert big.isVisible() and big.box.toPlainText() == "carried over" and not sp.ed.text()
    big.box.setPlainText("  hello   there \n\n second line\n")
    big.b_all.click()
    assert sp.said == ["hello there", "second line"]
    cur = big.box.textCursor()
    cur.setPosition(2)
    cur.setPosition(7, cur.MoveMode.KeepAnchor)
    big.box.setTextCursor(cur)
    sp.said.clear()
    big.b_sel.click()
    assert sp.said == ["hello"]
    big.box.clear()
    big.b_all.click()
    assert big.b_all.text() == "Type a line first"


def test_say_what_i_copied_says_it_a_line_at_a_time(sp):
    QGuiApplication.clipboard().setText("line one\r\nline two")
    assert sp.say_clipboard() == "line one\nline two"
    assert sp.said == ["line one", "line two"] and sp.history[-1]["src"] == "clipboard"
    QGuiApplication.clipboard().setText("   ")
    assert sp.say_clipboard() == ""


def test_the_quick_box_says_the_line_and_gives_the_keyboard_back(sp, monkeypatch, qapp):
    fronted = []
    from soundboard.control import winkeys
    monkeypatch.setattr(winkeys, "to_front", fronted.append)
    monkeypatch.setattr(winkeys, "front_window", lambda: 4242)
    sp.open_quick()
    q = sp._quick
    assert q.isVisible()
    q.ed.setText("  gg   wp ")
    key(q.ed, Qt.Key.Key_Return)
    process_events(qapp, lambda: 4242 in fronted)
    assert sp.said == ["gg wp"] and sp.history[-1]["src"] == "quick"
    assert not q.isVisible() and fronted[-1] == 4242
    sp.open_quick()
    key(q, Qt.Key.Key_Escape)
    assert not q.isVisible() and sp.said == ["gg wp"]


def test_lines_of_drops_blank_lines_and_extra_spaces():
    assert saybig.lines_of(" a  b \n\n\t\nc") == ["a b", "c"]
