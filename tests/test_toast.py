"""Toasts (ui/toast.py), the import's summary and See why (ui/importreport.py), and the
drop veil (ui/dropveil.py)."""
import numpy as np
import pytest
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



def test_a_card_that_stays_isnt_pushed_out_by_newer_ones(qapp):
    """Damaged settings at start-up: the start's other notices came after the card and
    pushed it out before anyone read it."""
    w = _host(qapp)
    note = busy.toast(w, "Settings were restored", "warn", 0)
    for i in range(5):
        busy.toast(w, f"Notice {i}")
    up = toast.shown(w)
    assert note in up and [t.text() for t in up if t is not note] == ["Notice 3", "Notice 4"]
    assert not note._timer.isActive()   # no countdown: it goes when it's closed
    note.card.btn_close.click()
    assert note not in toast.shown(w)
    w.close()

def test_problems_can_be_copied(qapp):
    w = _host(qapp)
    t = busy.toast(w, "Couldn't open <b>x.wav</b>", "error")
    assert t.card.btn_copy.isVisibleTo(t) and t.card.btn_copy.accessibleName() == "Copy"
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
        assert b.accessibleName() and not b.toolTip()   # copy and ✕ say it
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


def test_duplicates_are_not_counted_as_failed_files():
    dupe = importreport.Skipped("a.wav", "already", "dupe")
    empty = importreport.Skipped("empty.mp3", "empty", "not_sound")
    locked = importreport.Skipped("locked.wav", "denied", "unreadable")
    assert importreport.summary(0, [dupe] * 5 + [empty]) == (
        "5 sounds are already in your library · 1 skipped", "warn")
    assert importreport.summary(0, [dupe, empty, locked]) == (
        "That sound is already in your library · 2 skipped", "warn")
    assert importreport.summary(0, [empty, locked]) == ("Couldn't add 2 files", "error")


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
    w.impctl.import_files([str(good), str(bad), str(good)])   # the 2nd one: already in
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
    t = next(x for x in toast.shown(w) if x.key == "import")
    assert t.text() == "Added 1 sound · 2 skipped" and t.kind == "warn"
    assert t.card.action.text() == "See why"
    t.card.action.click()
    d = w.findChildren(importreport.SkippedDialog)[-1]
    assert not d.isModal() and {s.group for s in d.skipped} == {"dupe", "not_sound"}
    d.close()
    w.impctl.import_files([str(good), str(bad)])
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
    repeated = next(x for x in toast.shown(w) if x.key == "import")
    assert repeated.text() == "That sound is already in your library · 1 skipped"
    assert repeated.kind == "warn" and repeated.card.action.text() == "See why"


def test_undo_takes_the_new_sounds_off_again(main_window, qapp, tmp_path):  # noqa: F811
    w = main_window
    t = np.arange(SR // 10) / SR
    files = []
    for i, hz in enumerate((500, 900)):
        p = tmp_path / f"New {i}.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * hz * t)] * 2, 1) * 0.3, SR)
        files.append(str(p))
    before = len(w.cfg.sounds)
    w.impctl.import_files(files)
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
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
    w.impctl.import_files([str(short)])
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
    cards = toast.shown(w)
    result = next(t for t in cards if t.key == "import")
    assert result.kind == "ok" and result.card.action.text() == "Undo"
    warning = next(t for t in cards if "very short" in t.text())
    assert warning.kind == "warn"
    assert not w.impctl._imported_short
    warning.card.btn_close.click()
    w.impctl.import_files([str(long)])
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
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


@pytest.mark.windows
def test_see_why_text_is_level_with_the_warning_icon(qapp):
    """Check the painted baseline with the Windows font the app ships with."""
    import os
    from pathlib import Path
    from PySide6.QtGui import QColor, QFont, QFontDatabase
    from soundboard import theme

    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"))

    def ink_middle(widget, colour):
        image = widget.grab().toImage()
        target = QColor(colour)
        rows = [y for y in range(image.height()) for x in range(image.width())
                if max(abs(image.pixelColor(x, y).red() - target.red()),
                       abs(image.pixelColor(x, y).green() - target.green()),
                       abs(image.pixelColor(x, y).blue() - target.blue())) < 20]
        assert rows
        return widget.y() + (min(rows) + max(rows)) / 2

    old = theme.current_name
    w = _host(qapp)
    try:
        for name in ("Dark", "Light"):
            theme.apply(qapp, name)
            t = busy.toast(w, "5 sounds are already in your library · 1 skipped", "warn",
                           key="import", action=("See why", lambda: None))
            t.card.action.setFont(QFont("Segoe UI", 10))
            qapp.processEvents()
            assert t.card.action.height() == toast.LINE
            assert abs(ink_middle(t.card.action, theme.T["accent_link"])
                       - ink_middle(t.card.icon, theme.T["warn_text"])) <= 1
    finally:
        w.close()
        theme.apply(qapp, old)


def test_the_mini_player_shows_icons_on_top_or_none(main_window, qapp):  # noqa: F811
    """Too small to read cards: icons over the pads (clicking one makes the window
    bigger and closes nothing); none at all at its smallest; cards again once it grows."""
    w = main_window
    w.show()
    w.resize(300, 260)
    qapp.processEvents()
    assert w.fitctl.is_mini() and w._pads_scroll.isVisible()
    ok = busy.toast(w, "Saved a clip", "ok")
    err = busy.toast(w, "That station isn't working", "error")
    s = toast._stack_for(w)
    assert s.mode == "icons" and not ok.isVisible() and not err.isVisible()
    dots = [d for d in s.dots if d.isVisible()]
    assert len(dots) == 2 and dots[0].y() < 20               # on top, newest in the corner
    assert dots[0].accessibleName() == "That station isn't working"
    w.resize(260, 120)
    qapp.processEvents()
    assert s.mode == "hidden" and not any(d.isVisible() for d in s.dots)
    s.mode = "icons"
    w.resize(300, 260)
    qapp.processEvents()
    [d for d in s.dots if d.isVisible()][0].click()          # the window grows
    qapp.processEvents()
    assert not w.fitctl.is_mini() and s.mode == "cards"
    assert err.isVisible() and toast.shown(w) == [ok, err]   # nothing was closed


def test_a_big_import_shows_bun_and_closing_it_only_hides_it(main_window, qapp, tmp_path,  # noqa: F811
                                                             monkeypatch):
    """Several files: a card with Bun, the count and a bar. ✕ hides it while the rest go
    on; each sound is on the board (playable) before the import ends; the finished card
    with Undo still comes."""
    import threading
    from soundboard.ui import importcontrol
    w = main_window
    t = np.arange(SR // 10) / SR
    files = []
    for i in range(4):
        p = tmp_path / f"Big {i}.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * (300 + 90 * i) * t)] * 2, 1) * 0.3, SR)
        files.append(str(p))
    go, real = threading.Event(), importcontrol.import_file
    calls = []

    def slow(f, *a, **k):   # the first file goes in, the rest wait
        calls.append(f)
        if len(calls) > 1:
            go.wait(10)
        return real(f, *a, **k)
    monkeypatch.setattr(importcontrol, "import_file", slow)
    w.impctl.import_files(files)
    card = next(x for x in toast.shown(w) if x.key == "import")
    assert card.kind == "busy" and card.card.progress == (0, 4)
    assert card.card.icon.pixmap() is not None and card.card.icon.width() > 30   # Bun
    assert process_events(qapp, lambda: w.impctl._pending_imports == 3)
    first = w.impctl._import_ids[0]
    assert process_events(qapp, lambda: first in w.pads)   # on the board already
    card.card.btn_close.click()
    assert process_events(qapp, lambda: not any(x.key == "import" for x in toast.shown(w)))
    go.set()
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
    done = next(x for x in toast.shown(w) if x.key == "import")
    assert done.kind == "ok" and done.card.action.text() == "Undo"
    assert done.card.icon.width() == 18 and not w.impctl._import_card_shut   # next: card again


def test_stop_on_a_big_import_keeps_whats_in_and_skips_the_rest(main_window, qapp, tmp_path,  # noqa: F811
                                                                 monkeypatch):
    import threading
    from soundboard.ui import importcontrol
    w = main_window
    t = np.arange(SR // 10) / SR
    files = []
    for i in range(6):
        p = tmp_path / f"Oops {i}.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * (300 + 70 * i) * t)] * 2, 1) * 0.3, SR)
        files.append(str(p))
    go, real, calls = threading.Event(), importcontrol.import_file, []

    def slow(f, *a, **k):   # two go in, the third waits
        calls.append(f)
        if len(calls) == 3:
            go.wait(10)
        return real(f, *a, **k)
    monkeypatch.setattr(importcontrol, "import_file", slow)
    before = len(w.cfg.sounds)
    w.impctl.import_files(files)
    assert process_events(qapp, lambda: w.impctl._pending_imports == 4 and len(calls) == 3)
    card = next(x for x in toast.shown(w) if x.key == "import")
    assert card.card.action.text() == "Stop"
    card.card.action.click()
    go.set()
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
    assert len(calls) == 3 and len(w.cfg.sounds) == before + 3   # the one being read finished
    done = next(x for x in toast.shown(w) if x.key == "import")
    assert done.card.action.text() == "Undo" and not w.impctl._import_stop.is_set()
    done.card.action.click()
    assert len(w.cfg.sounds) == before


def test_one_slow_file_keeps_its_busy_card_until_its_in(main_window, qapp, tmp_path,  # noqa: F811
                                                       monkeypatch):
    """A long file can take longer to read than a notice stays up: its card waits."""
    import threading
    from soundboard.ui import importcontrol
    w = main_window
    p = tmp_path / "Hour.wav"
    sf.write(p, np.zeros((SR // 10, 2)), SR)
    go, real = threading.Event(), importcontrol.import_file
    monkeypatch.setattr(importcontrol, "import_file", lambda f, *a, **k: (go.wait(10),
                                                                      real(f, *a, **k))[1])
    w.impctl.import_files([str(p)])
    card = next(x for x in toast.shown(w) if x.key == "import")
    assert card.kind == "busy" and card.card.progress is None
    # a busy card's own long wait (minutes), not a notice's few seconds
    assert card._timer.remainingTime() > 60_000
    go.set()
    assert process_events(qapp, lambda: not w.impctl._pending_imports)


def test_a_long_path_wraps_but_copies_whole(qapp):
    """A folder path or file name longer than the card's line could only be cut off."""
    w = _host(qapp)
    path = "D:/Games/Stuff/AppData/Roaming/OnionBoard/config.json.broken-20261013-101500"
    t = busy.toast(w, toast.titled("Settings were restored", f"It was kept as {path}."), "warn", 0)
    assert "\u200b" in t._text   # somewhere to wrap
    t.copy()
    assert QApplication.clipboard().text() == f"Settings were restored\nIt was kept as {path}."
    w.close()


def test_a_cards_buttons_are_the_windows_last_tab_stops(main_window, qapp):  # noqa: F811
    """The window's Tab order is a ring from the rail through the page; a notice's Undo
    and ✕ come last, one Shift+Tab from the first stop, not among the page's controls."""
    from PySide6.QtCore import Qt
    w = main_window
    w.show()
    t = toast.show(w, "Added Boom", "ok", ms=0, action=("Undo", lambda: None))
    qapp.processEvents()
    stops, x = [], w.nextInFocusChain()
    while x is not w:
        if ((x.focusPolicy() & Qt.FocusPolicy.TabFocus) == Qt.FocusPolicy.TabFocus
                and x.isEnabled() and x.isVisibleTo(w)):
            stops.append(x)
        x = x.nextInFocusChain()
    assert stops[-2:] == [t.card.action, t.card.btn_close]
