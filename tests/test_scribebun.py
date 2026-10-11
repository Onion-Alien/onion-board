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
