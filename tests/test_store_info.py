"""A Store line's facts (storeinfo.InfoLabel): where it's from, music or a sound effect,
how long and when it came, in columns that line up and thin out as the line narrows."""
import time

from conftest import process_events
from test_store import FakeStore, _sound, _wait

from soundboard.online import store
from soundboard.sounds.library import Config
from soundboard.ui.kit.iconshapes import SHAPES
from soundboard.ui.store import storeinfo, storetab

YT = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
MI = "https://www.myinstants.com/en/instant/bruh-2/"


def _one(**kw) -> store.Sound:
    found, _more = store.parse({"sounds": [_sound(1, **kw)]})
    return found[0]


def test_a_length_from_the_server_is_kept_and_an_odd_one_dropped():
    assert _one(secs=2.4).secs == 2.4 and _one(secs=212).secs == 212
    for odd in (None, "12", -3, 0, True, float("nan"), float("inf"), 10 ** 9, [3]):
        assert _one(secs=odd).secs == 0, odd
    assert _one().secs == 0   # (a server that sends none)


def test_length_reads_short():
    said = [storeinfo.length_text(n) for n in (0.2, 5, 35.4, 60, 121, 3600, 3840)]
    assert said == ["1s", "5s", "35s", "1m", "2m 1s", "1h 0m", "1h 4m"]


def test_music_is_its_category_or_a_long_sound():
    assert storeinfo.kind_of(_one(cat="music", secs=3)) == ("music", "Music")
    assert storeinfo.kind_of(_one(cat="memes", secs=31)) == ("music", "Music")
    assert storeinfo.kind_of(_one(cat="memes", secs=30)) == ("wave", "Sound effect")
    assert storeinfo.kind_of(_one()) == ("wave", "Sound effect")   # (no length, no category)


def test_where_its_from_has_a_picture_and_a_word():
    cases = ((dict(), ("person", "Player")),
             (dict(author="Onion Board"), ("onion", "Onion Board")),
             (dict(ext="link", link=YT), ("youtube", "YouTube link")),
             (dict(ext="link", link=MI, source="myinstants"), ("myinstants", "Myinstants")))
    for kw, want in cases:
        got = storeinfo.source_of(_one(**kw))
        assert got == want and got[0] in SHAPES
    assert {"clock", "person", "music", "wave"} <= set(SHAPES)


def _tab(qapp, fake, sounds, width=1600):   # (room for every column, whatever the fonts)
    fake.sounds = {s["id"]: s for s in sounds}
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.resize(width, 600)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == len(sounds)
                 and t.stack.currentWidget() is t.list_area)
    process_events(qapp, lambda: False, timeout=0.3)
    return t


def _fake(monkeypatch):
    fake = FakeStore([])
    monkeypatch.setattr(store, "_request", fake)
    return fake


def test_a_line_says_all_of_it_and_thins_out_when_narrow(qapp, monkeypatch, app_dir):
    now = int(time.time())
    t = _tab(qapp, _fake(monkeypatch), [
        _sound(1, cat="memes", created=now - 3 * 86400, secs=25, tags=[]),
        _sound(2, cat="music", created=now - 86400, secs=212, ext="link", link=MI,
               source="myinstants")])
    a, b = t._rows
    assert a.meta.full == "Shared by a player · Memes · Sound effect · 25s · 3 days ago"
    assert b.meta.full == "From Myinstants · Music · 3m 32s · 1 day ago"   # (Music said once)
    assert a.meta.accessibleName() == a.meta.full and "25s" in a.meta.toolTip()
    levels = a.meta._levels()
    assert [w for w, _show in levels] == sorted((w for w, _show in levels), reverse=True)
    assert levels[-1][0] == storeinfo.LEAST == a.meta.minimumWidth()
    assert a.meta.width() == b.meta.width() == a.meta.full_width()   # the same columns
    assert a.meta.x() == b.meta.x()
    seen = set()
    for width in range(1600, 419, -20):   # each look in turn, never wider than its room
        t.resize(width, 600)
        process_events(qapp, lambda: False, timeout=0.05)
        if not a.meta.maximumWidth():   # (only the narrowest tab's rows have no room)
            assert width < 460, width
            continue
        assert a.meta.width() == b.meta.width()
        assert a.meta.width() in [w for w, _show in levels], width
        assert a.name.width() >= 40
        seen.add(a.meta.width())
    assert len(seen) >= 4
    t.shutdown()


def test_no_length_column_when_no_line_has_one(qapp, monkeypatch, app_dir):
    fake = _fake(monkeypatch)
    t = _tab(qapp, fake, [_sound(1), _sound(2, ext="link", link=YT)])
    a = t._rows[0]
    assert not a.meta.with_len
    bare = a.meta.full_width()
    t.shutdown()
    t = _tab(qapp, fake, [_sound(1, secs=4), _sound(2, ext="link", link=YT)])
    a, b = t._rows
    assert a.meta.with_len and b.meta.with_len   # (b's stays empty: the columns line up)
    assert a.meta.full_width() == b.meta.full_width() > bare
    t.shutdown()
