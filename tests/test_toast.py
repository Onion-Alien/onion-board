"""Toasts (ui/toast.py), the import's summary and See why (ui/importreport.py), and the
drop veil (ui/dropveil.py)."""
import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from conftest import process_events
from soundboard.library import SR
from soundboard.ui import busy, importreport, toast
from soundboard.ui.dropveil import label_for
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


def _host(qapp):
    w = QWidget()
    w.resize(700, 500)
    w.show()
    qapp.processEvents()
    return w


def test_a_tick_means_ok_and_dots_mean_working(qapp):
    w = _host(qapp)
    t = busy.toast(w, "✓ Added 3 sounds")
    assert t.kind == "ok" and t.text() == "Added 3 sounds"   # the icon says ✓ now
    t2 = busy.toast(w, "Exporting 4 sounds…")
    assert t2.kind == "busy" and t2.card.spinner.isVisibleTo(t2)
    w.close()


def test_working_turns_into_its_result_in_place(qapp):
    w = _host(qapp)
    t = busy.toast(w, "Exporting 4 sounds…")
    done = busy.toast(w, "✓ Exported 4 sounds")
    assert done is t and t.kind == "ok" and toast.shown(w) == [t]
    w.close()


def test_a_key_updates_its_own_card(qapp):
    w = _host(qapp)
    a = busy.toast(w, "Adding 12 sounds…", "busy", key="import", progress=(0, 12))
    busy.toast(w, "Something else")
    b = busy.toast(w, "Adding 5 of 12…", "busy", key="import", progress=(5, 12))
    assert a is b and a.card.progress == (5, 12) and len(toast.shown(w)) == 2
    w.close()


def test_the_same_notice_counts_up_right_after_its_words(qapp):
    w = _host(qapp)
    busy.toast(w, "✓ Link copied")
    t = busy.toast(w, "✓ Link copied")
    busy.toast(w, "✓ Link copied")
    assert toast.shown(w) == [t] and "×3" in t.card.label.text()
    w.close()


def test_at_most_three_and_the_newest_is_lowest(qapp):
    w = _host(qapp)
    for i in range(6):
        busy.toast(w, f"Notice {i}")
    up = toast.shown(w)
    assert [t.text() for t in up] == ["Notice 3", "Notice 4", "Notice 5"]
    assert up[0].y() < up[1].y() < up[2].y()
    for a, b in zip(up, up[1:]):
        assert a.geometry().bottom() < b.geometry().top() + 1   # no overlap
    w.close()


def test_errors_stay_and_others_go(qapp):
    w = _host(qapp)
    err = busy.toast(w, "Couldn't save", "error", ms=30)
    ok = busy.toast(w, "Saved", "ok", ms=30)
    process_events(qapp, lambda: ok not in toast.shown(w))
    assert toast.shown(w) == [err] and not err._timer.isActive()
    err.card.btn_close.click()
    assert toast.shown(w) == []
    w.close()


def test_problems_can_be_copied(qapp):
    w = _host(qapp)
    t = busy.toast(w, "Couldn't open <b>x.wav</b>", "error")
    assert t.card.btn_copy.isVisibleTo(t) and t.card.btn_copy.toolTip() == "Copy"
    t.card.btn_copy.click()
    assert QApplication.clipboard().text() == "Couldn't open x.wav"
    ok = busy.toast(w, "Saved", "ok")
    assert not ok.card.btn_copy.isVisibleTo(ok)
    w.close()


def test_the_button_runs_and_closes(qapp):
    w = _host(qapp)
    ran = []
    t = busy.toast(w, "Deleted “Boom”", action=("Undo", lambda: ran.append(1)))
    assert t.card.action.text() == "Undo"
    t.card.action.click()
    assert ran == [1] and toast.shown(w) == []
    w.close()


def test_hovering_pauses_the_countdown(qapp):
    w = _host(qapp)
    t = busy.toast(w, "Saved", "ok", ms=5000)
    QApplication.sendEvent(t, QEvent(QEvent.Enter))
    assert not t._timer.isActive()
    QApplication.sendEvent(t, QEvent(QEvent.Leave))
    assert t._timer.isActive() and t._timer.remainingTime() >= 1400
    w.close()


def test_icon_buttons_say_what_they_do(qapp):
    w = _host(qapp)
    t = busy.toast(w, "Couldn't save", "error")
    for b in (t.card.btn_copy, t.card.btn_close):
        assert b.toolTip() and b.accessibleName()
    w.close()


def test_toasts_stay_above_dialog_buttons(qapp):
    dlg = QDialog()
    dlg.resize(600, 500)
    dlg.show()
    btn = QPushButton("Next", dlg)
    btn.resize(100, 40)
    btn.move(450, 440)
    btn.show()
    t = busy.toast(dlg, "Notice message")
    assert t.geometry().bottom() < btn.y()
    dlg.close()


def test_toasts_never_lie_over_the_player(main_window, qapp):  # noqa: F811
    w = main_window
    w.resize(900, 700)
    w.show()
    qapp.processEvents()
    for text in ("One", "Two that is long enough to wrap onto a second line in a narrow "
                 "window like this one", "Three"):
        w.toast(text)
    floor = w.toast_floor()
    for size in ((900, 700), (480, 600), (1400, 800)):
        w.resize(*size)
        qapp.processEvents()
        floor = w.toast_floor()
        for t in toast.shown(w):
            g = t.geometry()   # the whole widget, its see-through shadow edge too
            assert g.bottom() < floor and g.left() >= 0 and g.right() < w.width(), size


def test_reasons_are_sorted_into_plain_groups(tmp_path):
    there = tmp_path / "x.mp3"
    there.write_bytes(b"x")
    assert importreport.classify(str(there), importreport.AlreadyAdded("Boom")).group == "dupe"
    gone = importreport.classify(str(tmp_path / "gone.wav"), RuntimeError("[in#0] Error ..."))
    assert gone.group == "unreadable" and "isn't there" in gone.reason
    locked = importreport.classify(str(there), PermissionError("denied"))
    assert locked.group == "unreadable"
    noisy = importreport.classify(str(there), RuntimeError("Error opening input " * 20))
    assert noisy.group == "not_sound" and len(noisy.reason) < importreport.LONG


def test_the_summary_says_how_it_went():
    dupe = importreport.Skipped("a.wav", "already", "dupe")
    bad = importreport.Skipped("b.mp3", "damaged", "not_sound")
    assert importreport.summary(3, []) == ("✓ Added 3 sounds", "ok")
    assert importreport.summary(3, [bad]) == ("Added 3 sounds · 1 skipped", "warn")
    assert importreport.summary(3, [dupe])[1] == ""   # nothing went wrong
    assert importreport.summary(0, [dupe, dupe])[0] == "2 sounds are already in your library"
    assert importreport.summary(0, [bad]) == ("Couldn't add 1 file", "error")


def test_the_see_why_list_copies_everything(qapp):
    sk = [importreport.Skipped("b.mp3", "damaged", "not_sound"),
          importreport.Skipped("a.wav", "already", "dupe")]
    d = importreport.SkippedDialog(sk)
    assert d.btn_copy.accessibleName()
    d.copy()
    text = QApplication.clipboard().text()
    assert text.index("Already in your library") < text.index("Not a sound we can play")
    assert "b.mp3: damaged" in text
    d.close()


def test_a_mixed_drop_ends_in_one_toast_with_see_why(main_window, qapp, tmp_path):  # noqa: F811
    w = main_window
    t = np.arange(SR // 10) / SR
    good = tmp_path / "Bruh.wav"
    sf.write(good, np.stack([np.sin(2 * np.pi * 700 * t)] * 2, 1) * 0.3, SR)
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio" * 50)
    w.import_files([str(good), str(bad), str(good)])   # the 2nd one: already in
    assert process_events(qapp, lambda: not w._pending_imports)
    t = next(x for x in toast.shown(w) if x.key == "import")
    assert t.text() == "Added 1 sound · 2 skipped" and t.kind == "warn"
    assert t.card.action.text() == "See why"
    t.card.action.click()
    d = w.findChildren(importreport.SkippedDialog)[-1]
    assert not d.isModal() and {s.group for s in d.skipped} == {"dupe", "not_sound"}
    d.close()


def test_undo_takes_the_new_sounds_off_again(main_window, qapp, tmp_path):  # noqa: F811
    w = main_window
    t = np.arange(SR // 10) / SR
    files = []
    for i, hz in enumerate((500, 900)):
        p = tmp_path / f"New {i}.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * hz * t)] * 2, 1) * 0.3, SR)
        files.append(str(p))
    before = len(w.cfg.sounds)
    w.import_files(files)
    assert process_events(qapp, lambda: not w._pending_imports)
    assert len(w.cfg.sounds) == before + 2
    t = next(x for x in toast.shown(w) if x.key == "import")
    assert t.kind == "ok" and t.card.action.text() == "Undo"
    t.card.action.click()
    assert len(w.cfg.sounds) == before   # undo-able too
    assert any(x.key == "undo-sounds" for x in toast.shown(w))


def test_the_veil_says_what_a_drop_does():
    assert label_for(["a.mp3", "b.wav"]) == "Drop to add 2 files"
    assert label_for(["one.ogg"]) == "Drop to add 1 file"
    assert label_for(["C:/Sounds/memes"]) == "Drop to add sounds"   # a folder
    assert label_for(["cover.png"]) is None   # a picture for a pad
    assert label_for([]) is None


def test_on_close_runs_unless_the_button_was_clicked(qapp):
    w = _host(qapp)
    closed = []
    t = busy.toast(w, "Removed “Boom”", "", 50, key="undo",
                   action=("Undo", lambda: closed.append("undo")),
                   on_close=lambda: closed.append("gone"))
    t.card.action.click()
    assert closed == ["undo"]                  # undone: not "too late now"
    busy.toast(w, "Removed “Boom”", "", 5000, key="undo", on_close=lambda: closed.append(1))
    busy.toast(w, "Removed “Bruh”", "", 5000, key="undo", on_close=lambda: closed.append(2))
    assert closed == ["undo", 1]               # replaced: the first one's time is up
    toast.shown(w)[0].card.btn_close.click()
    assert closed == ["undo", 1, 2]
    busy.toast(w, "Removed “Airhorn”", "", 50, on_close=lambda: closed.append(3))
    assert process_events(qapp, lambda: 3 in closed)   # timed out
    w.close()


def test_short_sound_warning_keeps_import_actions_and_resets(main_window, qapp, tmp_path):  # noqa: F811
    w = main_window
    short = tmp_path / "short.wav"
    long = tmp_path / "long.wav"
    sf.write(short, np.zeros((SR // 10, 2)), SR)
    sf.write(long, np.zeros((SR, 2)), SR)
    w.import_files([str(short)])
    assert process_events(qapp, lambda: not w._pending_imports)
    cards = toast.shown(w)
    result = next(t for t in cards if t.key == "import")
    assert result.kind == "ok" and result.card.action.text() == "Undo"
    warning = next(t for t in cards if "very short" in t.text())
    assert warning.kind == "warn"
    assert not w._imported_short
    warning.card.btn_close.click()
    w.import_files([str(long)])
    assert process_events(qapp, lambda: not w._pending_imports)
    assert not any("very short" in t.text() for t in toast.shown(w))
    assert next(t for t in toast.shown(w) if t.key == "import").card.action.text() == "Undo"


def test_a_long_button_goes_under_the_text(qapp):
    w = _host(qapp)
    t = busy.toast(w, "Couldn't update", "error", action=("Open the download page", lambda: None))
    short = busy.toast(w, "Removed it", "ok", action=("Undo", lambda: None))
    assert t.card._under.indexOf(t.card.action) >= 0
    assert short.card._row.indexOf(short.card.action) >= 0
    w.close()


def test_a_cards_parts_line_up(qapp):
    """The long button's words start where the message does; the icon, copy and ✕
    sit in the middle of the first line."""
    from PySide6.QtCore import QPoint
    w = _host(qapp)
    t = busy.toast(w, "<b>Couldn't update</b><br>It couldn't be downloaded.", "error",
                   action=("Open the download page", lambda: None))
    qapp.processEvents()
    c = t.card

    def left_of_words(widget, words):
        inset = (widget.width() - widget.fontMetrics().horizontalAdvance(words)) // 2 \
            if widget is c.action else widget.contentsMargins().left()
        return widget.mapTo(c, QPoint(0, 0)).x() + inset

    assert abs(left_of_words(c.action, c.action.text()) - left_of_words(c.label, "")) <= 1
    first = c.label.mapTo(c, QPoint(0, 0)).y() + c.label.contentsMargins().top() \
        + c.label.fontMetrics().height() / 2
    for part in (c.icon, c.btn_copy, c.btn_close):
        middle = part.mapTo(c, QPoint(0, 0)).y() + part.height() / 2
        assert abs(middle - first) <= 2, part
    w.close()
