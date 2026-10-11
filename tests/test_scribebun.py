"""Bun the scribe's music: real, well-known pieces written out like sheet music, a
different one each download."""
import pytest

from soundboard.ui import scribebun as sb


def test_enough_pieces_and_all_parse_and_fit():
    assert len(sb.TUNES) >= 20
    for name, (bar, text) in sb.TUNES.items():
        notes, bars = sb.lay_out(sb.parse_tune(text), bar)
        assert len(notes) >= 10, name
        assert bars, name
        for n in notes:
            assert all(sb.LOW <= s <= sb.HIGH for s, _ in n.heads), name
            assert sb.NOTE_X0 <= n.x <= sb.ROW_END, name


def test_pieces_use_more_than_plain_notes():
    kinds = set()
    for bar, text in sb.TUNES.values():
        for n in sb.lay_out(sb.parse_tune(text), bar)[0]:
            kinds.add(n.length)
            kinds |= {"chord"} if len(n.heads) > 1 else set()
            kinds |= {"rest"} if n.rest else set()
            kinds |= {"dot"} if n.dot else set()
            kinds |= {"beam"} if n.beamed else set()
            kinds |= {a for _, a in n.heads if a}
    assert {1, 2, 4, 8, 12, 16, "chord", "rest", "dot", "beam", "#", "_"} <= kinds


def test_never_the_same_piece_twice_running():
    picks = []
    for _ in range(40):
        sb.random_tune()
        picks.append(sb._last_tune[0])
    assert all(a != b for a, b in zip(picks, picks[1:]))
    assert len(set(picks)) > 10


def test_stems_stay_in_their_row():
    for bar, text in sb.TUNES.values():
        for n in sb.lay_out(sb.parse_tune(text), bar)[0]:
            if n.heads:
                bottom = sb.ROW_BOTTOMS[n.row]
                assert bottom - 4 * sb.GAP - 0.75 <= n.stem_end <= bottom + 0.75


def test_bad_note_is_refused():
    try:
        sb.parse_tune("C4 X9")
    except ValueError:
        return
    raise AssertionError("a bad note was accepted")


def test_frames_reuse_the_kept_pictures(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap
    bun = sb.ScribeBunny()
    bun.reset()
    bun.set_progress(0.5)
    bun._shown_prog = 0.5
    pm = QPixmap(bun.size())
    bun.render(pm, QPoint(0, 0))
    kept = dict(bun._layers)
    assert kept
    bun._shown_prog = 0.5001   # the next note a little further along: same pictures
    bun.render(pm, QPoint(0, 0))
    assert bun._layers.keys() == kept.keys()


def test_download_bar_first_line_lines_up(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFontMetricsF

    from soundboard.ui.downloadbar import DownloadBar
    for mini in (False, True):
        bar = DownloadBar()
        bar.set_mini(mini)
        bar.resize(900, 80)
        bar.set_active("https://www.youtube.com/watch?v=a", "Some song", "add", None, "Someone", 90)
        for _ in range(3):
            qapp.processEvents()

        def top(w, bar=bar):
            return w.mapTo(bar, QPoint(0, 0)).y()

        def baseline(w, top=top):
            fm = QFontMetricsF(w.font())
            return top(w) + (w.height() - fm.height()) / 2 + fm.ascent()

        base = baseline(bar.lbl_title)
        for w in (bar.lbl_src, bar.lbl_meta):
            if w.isVisibleTo(bar):   # the mini player shows only the site's logo
                assert abs(baseline(w) - base) <= 1, (mini, w.objectName())
        mid = base - QFontMetricsF(bar.lbl_title.font()).capHeight() / 2
        for w in (bar.pill, bar.src_icon):
            assert abs(top(w) + w.height() / 2 - mid) <= 1, (mini, w.objectName())
        # Cancel sits on the progress line, centred with the bar
        bar_mid = top(bar.bar) + bar.bar.height() / 2
        assert abs(top(bar.btn_cancel) + bar.btn_cancel.height() / 2 - bar_mid) <= 1
        bar.close()


def _fail(bar, url, kind="add"):
    bar.set_failed(url, kind)
    bar.set_done(url, kind, False)


def _flash_over(bar):
    bar._hold.stop()
    bar._release()


def test_download_bar_gradient_follows_how_it_ended(qapp):
    """The banner's gradient: tinted green when added, red when it failed, back to the
    accent for the next pick; the outlined theme keeps it flat."""
    from soundboard import theme
    from soundboard.ui.downloadbar import DownloadBar
    was = theme.current_name
    try:
        theme.apply(qapp, "Dark")
        bar = DownloadBar()
        bar.resize(900, 80)
        a, b = "https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=b"
        assert "qlineargradient" in bar.styleSheet()
        bar.set_active(a, "One", "add", None)
        assert bar.property("ended") == ""
        bar.set_done(a, "add", True)
        assert bar.property("ended") == "ok"
        _flash_over(bar)
        bar.set_active(b, "Two", "add", None)
        assert bar.property("ended") == ""
        _fail(bar, b)
        assert bar.property("ended") == "failed"
        bar.close()
        theme.apply(qapp, "High Contrast")
        flat = DownloadBar()
        assert "qlineargradient" not in flat.styleSheet()
        flat.close()
    finally:
        theme.apply(qapp, was)


def test_download_bar_flags_how_it_ended(qapp):
    from soundboard.ui.downloadbar import DownloadBar
    bar = DownloadBar()
    bar.resize(900, 80)
    for ok in (True, False):
        bar.set_active("https://www.youtube.com/watch?v=a", "Some song", "add", None)
        for _ in range(3):
            qapp.processEvents()
        if ok:
            bar.set_done(bar.url, "add", True)
        else:
            _fail(bar, bar.url)
        assert bar.outcome.isVisible() and bar.outcome.ok is ok
        assert not bar.outcome.spot.isEmpty()   # over Bun (no thumbnail here)
        bar.outcome._anim.setCurrentTime(bar.outcome.SHOW_MS)   # a second later: gone
        assert not bar.outcome.isVisible()
        _flash_over(bar)
    mini = DownloadBar()
    mini.set_mini(True)
    mini.set_active("https://www.youtube.com/watch?v=b", "Some song", "add", None)
    mini.set_done(mini.url, "add", True)
    assert not mini.outcome.isVisible()       # no picture to mark, nothing to glow about
    _flash_over(mini)
    mini.set_active("https://www.youtube.com/watch?v=c", "Some song", "add", None)
    _fail(mini, mini.url)
    assert mini.outcome.isVisible() and mini.outcome.spot.isEmpty()   # just the red glow
    bar.close()
    mini.close()


def test_download_bar_waits_for_the_flash_then_moves_up(qapp):
    from soundboard.ui.downloadbar import DownloadBar
    bar = DownloadBar()
    bar.resize(900, 80)
    a, b, c = (f"https://www.youtube.com/watch?v={x}" for x in "abc")
    bar.set_active(a, "One", "add", None)
    bar.set_queue([{"url": b, "title": "Two", "kind": "add"},
                   {"url": c, "title": "Three", "kind": "add"}])
    bar.set_done(a, "add", True)
    # the next one starts at once, but the card shows the tick for a second first
    bar.set_queue([{"url": c, "title": "Three", "kind": "add"}])
    bar.set_active(b, "Two", "add", None)
    bar.set_progress(b, 0.5)
    assert bar.url == a and bar.queue_badge.text() == "+2 queued"
    _flash_over(bar)
    assert bar.url == b and bar.lbl_status.text() == "50%"
    assert bar.queue_badge.text() == "+1 queued"
    bar.close()


@pytest.mark.parametrize("ok", [True, False])
def test_download_bar_last_pick_stays_ended_after_a_late_update(qapp, ok):
    """The last of three picks: once it shows ✓ (or ✗), a late "processing" or
    progress for it can't put it back to busy, and the banner still goes away."""
    from soundboard.ui.downloadbar import DownloadBar
    bar = DownloadBar()
    bar.resize(900, 80)
    a, b, c = (f"https://www.youtube.com/watch?v={x}" for x in "abc")
    bar.set_active(a, "One", "add", None)
    bar.set_queue([{"url": b, "title": "Two", "kind": "add"},
                   {"url": c, "title": "Three", "kind": "add"}])
    for url, left in ((a, [c]), (b, [])):
        bar.set_done(url, "add", True)
        _flash_over(bar)
        nxt = b if url == a else c
        bar.set_queue([{"url": u, "title": "x", "kind": "add"} for u in left])
        bar.set_active(nxt, "Next", "add", None)
    bar.set_progress(c, 0.4)
    bar.set_progress(c, "processing")
    if ok:
        bar.set_done(c, "add", True)
    else:
        _fail(bar, c)
    ended = bar.lbl_status.text()
    for late in ("processing", -1, 0.9, "parsing"):   # during the flash, then after it
        bar.set_progress(c, late)
    _flash_over(bar)
    for late in ("processing", -1, 0.9, "parsing"):
        bar.set_progress(c, late)
    assert bar.url == c and bar.stage == "done" and bar.lbl_status.text() == ended
    assert ended == ("✓ Added to your sounds" if ok else "Couldn't download")
    assert bar._auto_hide.isActive() == ok   # a failed one waits for Retry or ✕
    # picked again: it's a new download, so its progress shows once more
    bar.set_active(c, "Three", "add", None)
    bar.set_progress(c, "processing")
    assert bar.stage == "processing" and bar.lbl_status.text() == "Processing audio…"
    bar.close()


def test_download_bar_failures_wait_for_retry(qapp):
    from soundboard.ui.downloadbar import DownloadBar
    bar = DownloadBar()
    bar.resize(900, 80)
    asked = []
    bar.retry_requested.connect(asked.append)
    a, b = "https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=b"
    # fails with another waiting: the next moves up, the failed one keeps a Retry row
    bar.set_active(a, "One", "add", None, "", 61)
    bar.set_queue([{"url": b, "title": "Two", "kind": "add"}])
    _fail(bar, a)
    assert bar.btn_retry.isVisibleTo(bar) and not bar.btn_cancel.isVisibleTo(bar)
    assert not bar._auto_hide.isActive()   # waits for Retry or ✕
    bar.set_queue([])
    bar.set_active(b, "Two", "add", None)
    _flash_over(bar)
    assert bar.url == b and not bar.btn_retry.isVisibleTo(bar)
    assert bar.queue_badge.text() == "1 failed"
    bar.queue_badge.setChecked(True)
    assert bar.panel.isVisibleTo(bar)
    # minimised: the song, how far, what's left
    bar.set_progress(b, 0.6)
    bar.set_collapsed(True)
    assert bar.s_text.text() == "Two · 60%" and "1 failed" in bar.s_failed.text()
    bar.set_collapsed(False)
    # a finish doesn't hide the bar while a failed one waits
    bar.set_done(b, "add", True)
    assert not bar._auto_hide.isActive()
    bar._retry(a)
    assert asked == [{"url": a, "title": "One", "kind": "add", "seconds": 61}]
    assert not bar._failed and not bar.queue_badge.isVisibleTo(bar)
    bar.close()


def test_download_bar_cancel_is_not_a_failure(qapp):
    from soundboard.ui.downloadbar import DownloadBar
    bar = DownloadBar()
    bar.resize(900, 80)
    a = "https://www.youtube.com/watch?v=a"
    bar.set_active(a, "One", "add", None)
    bar.show()
    bar.cancel_requested.connect(lambda url: bar.set_done(url, "add", False))
    bar._on_cancel()
    assert not bar._failed and not bar.outcome.isVisible() and bar.isHidden()
    # a newer pick taking over (no error first): no flash, no Retry either
    bar.set_active(a, "One", "play", None)
    bar.set_done(a, "play", False)
    assert not bar._failed and not bar.outcome.isVisible()
    bar.close()


def test_download_bar_in_a_narrow_window_drops_what_it_can(qapp):
    from soundboard.ui.downloadbar import BAR_MIN_W, DownloadBar
    bar = DownloadBar()
    links = [f"https://www.youtube.com/watch?v={c}" for c in "abc"]
    bar.set_active(links[0], "A song with a long name", "add", None, "Someone", 90)
    bar.set_queue([{"url": u, "title": "x", "kind": "add"} for u in links[1:]])
    bar.show()
    bar.resize(1000, 80)
    qapp.processEvents()
    assert bar.queue_badge.text() == "+2 queued" and bar.btn_stop_all.isVisibleTo(bar)
    assert bar.lbl_src.isVisibleTo(bar)
    bar.setFixedWidth(360)   # the smallest window before the mini player
    qapp.processEvents()
    assert bar.queue_badge.text() == "+2" and not bar.btn_stop_all.isVisibleTo(bar)
    assert not bar.lbl_src.isVisibleTo(bar) and bar.src_icon.isVisibleTo(bar)
    assert bar.bar.width() >= BAR_MIN_W
    bar.queue_badge.setChecked(True)
    assert bar.btn_panel_stop.isVisibleTo(bar)   # Stop all, in the list
    bar.setFixedWidth(1000)
    qapp.processEvents()
    assert bar.queue_badge.text() == "+2 queued" and bar.btn_stop_all.isVisibleTo(bar)
    bar.close()


def test_tab_leaves_the_network_activity_table(qapp):
    """With rows in it, Tab used to step through every cell and never get out."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QTableWidgetItem, QVBoxLayout, QWidget

    from soundboard.ui.netactivity import ActivityTable
    host = QWidget()
    lay = QVBoxLayout(host)
    table = ActivityTable(["a", "b", "c", "d", "e", "f"], 1)
    after = QLineEdit()
    lay.addWidget(table)
    lay.addWidget(after)
    table.setRowCount(3)
    for r in range(3):
        for c in range(6):
            table.setItem(r, c, QTableWidgetItem("x"))
    host.show()
    host.activateWindow()
    table.setFocus()
    qapp.processEvents()
    QTest.keyClick(table, Qt.Key_Tab)
    assert after.hasFocus()
    host.close()
