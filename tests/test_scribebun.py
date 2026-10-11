"""Bun the scribe's music: real, well-known pieces written out like sheet music, a
different one each download."""
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
