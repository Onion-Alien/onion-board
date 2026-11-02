"""The store's catalog (/v1/catalog): every list's first page got as the app starts and
kept on disk, so the Community tab and its categories show at once, with this install's
own votes on top. Against a fake store: no test goes online."""
import gzip
import io
import time

from conftest import process_events
from test_store import FakeStore, _sound

from soundboard.online import net, store
from soundboard.sounds.library import Config
from soundboard.ui.store import storetab


def _catalog(sounds, lists, cats=(("games", 2),), built=None):
    return {"built": int(time.time()) if built is None else built, "page": 50,
            "categories": {"categories": [{"cat": c, "n": n} for c, n in cats],
                           "total": sum(n for _c, n in cats)},
            "sounds": {s["id"]: s for s in sounds},
            "lists": {k: {"ids": [s["id"] for s in v], "more": False} for k, v in lists.items()}}


def _setup(monkeypatch):
    a, b, c = (_sound(1, name="Air horn", up=4, cat="games"), _sound(2, name="Bruh", cat="games"),
               _sound(3, name="Live only"))
    f = FakeStore([c])
    f.cats = [("games", 2)]
    f.catalog = _catalog([a, b], {"trending:": [a, b], "top:": [b, a], "top:games": [b, a],
                                  "trending:games": [a, b]})
    monkeypatch.setattr(store, "_request", f)
    return f


def _tab(qapp):
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.resize(900, 700)
    return t


def _names(t):
    return [r.sound.name for r in t._rows]


def test_the_tab_and_its_categories_show_from_the_catalog(qapp, monkeypatch, app_dir):
    f = _setup(monkeypatch)
    t = _tab(qapp)
    assert process_events(qapp, lambda: t._catalog is not None)
    t.show()
    assert process_events(qapp, lambda: _names(t) == ["Air horn", "Bruh"])
    # the list and the categories came from the catalog: the store wasn't asked for them
    assert f.calls == []
    assert t.cat_pick.findData("games") >= 0
    # an order and a category in it: at once, still nothing asked
    t.set_sort("top")
    assert _names(t) == ["Bruh", "Air horn"]
    t.set_cat("games")
    assert _names(t) == ["Bruh", "Air horn"] and f.calls == []
    # one that isn't in it (Newest) and a search ask the store, as before
    t.set_sort("new")
    assert process_events(qapp, lambda: _names(t) == ["Live only"])
    assert "sort=new" in f.calls[-1][1]
    t.set_sort("top")
    assert _names(t) == ["Bruh", "Air horn"]
    t.search.setText("live")
    t.reload()
    assert process_events(qapp, lambda: "q=live" in f.calls[-1][1])
    t.search.clear()
    t.reload()
    assert _names(t) == ["Bruh", "Air horn"]
    # Refresh asks the store for the list itself
    asked = len(f.calls)
    t.btn_reload.click()
    assert process_events(qapp, lambda: len(f.calls) > asked and _names(t) == ["Live only"])
    t.shutdown()


def test_the_catalog_is_kept_for_the_next_launch(qapp, monkeypatch, app_dir):
    f = _setup(monkeypatch)
    t = _tab(qapp)
    assert process_events(qapp, lambda: t._catalog is not None)
    t.shutdown()
    assert (app_dir / "store" / "catalog.json").is_file()
    # next launch, the store can't be reached: the copy on disk shows at once
    f.catalog = None
    f.fail = "down"
    t = _tab(qapp)
    t.show()
    assert process_events(qapp, lambda: _names(t) == ["Air horn", "Bruh"])
    assert f.catalog_calls == 2
    t.shutdown()


def test_switched_off_the_catalog_isnt_asked_for(qapp, monkeypatch, app_dir):
    f = _setup(monkeypatch)
    monkeypatch.setattr(net, "allowed", lambda feature: False)
    t = _tab(qapp)
    process_events(qapp, lambda: False, timeout=0.3)
    assert f.catalog_calls == 0 and t._catalog is None
    t.shutdown()


def test_your_own_votes_show_on_the_catalogs_cards(qapp, monkeypatch, app_dir):
    f = _setup(monkeypatch)
    cat = f.catalog
    assert cat is not None
    f.sounds["000000000001"] = dict(cat["sounds"]["000000000001"])   # (votes go to it)
    t = _tab(qapp)
    assert process_events(qapp, lambda: t._catalog is not None)
    t.show()
    assert process_events(qapp, lambda: _names(t) == ["Air horn", "Bruh"])
    row = t._rows[0]
    t.vote(row, 1)
    assert process_events(qapp, lambda: ("000000000001", "vote") not in t._busy)
    assert (row.sound.up, row.sound.mine) == (5, 1)
    t.shutdown()
    # the catalog was built before the vote: the card shows the vote and its count anyway
    t = _tab(qapp)
    t.show()
    assert process_events(qapp, lambda: _names(t) == ["Air horn", "Bruh"])
    assert (t._rows[0].sound.up, t._rows[0].sound.mine) == (5, 1)
    assert t._rows[1].sound.mine == 0
    t.shutdown()
    # a newer catalog has the vote counted in itself; yours still shows as yours
    cat["built"] = int(time.time()) + 60
    cat["sounds"]["000000000001"]["up"] = 9
    t = _tab(qapp)
    t.show()
    assert process_events(qapp, lambda: t._catalog is not None
                          and t._catalog.built == cat["built"])
    t.reload()
    assert (t._rows[0].sound.up, t._rows[0].sound.mine) == (9, 1)
    t.shutdown()


def test_odd_catalogs_are_left_out():
    assert store.parse_catalog(b"not json") is None
    assert store.parse_catalog(b'{"sounds": [], "lists": {}}') is None
    good = _sound(1)
    got = store.parse_catalog(_json({"sounds": {good["id"]: good, "x": {"id": "nope"}},
                                     "lists": {"top:": {"ids": [good["id"], "x", 5]},
                                               "weird:": {"ids": [good["id"]]},
                                               "top:nosuchcat": {"ids": [good["id"]]}}}))
    assert got is not None and list(got.lists) == [("top", "")]
    assert [s.id for s in got.lists[("top", "")][0]] == [good["id"]]


def test_the_catalog_comes_gzipped(monkeypatch, app_dir):
    body = _json(_catalog([_sound(1)], {"trending:": [_sound(1)]}))

    class Answer(io.BytesIO):
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    asked = []

    def opened(req, timeout=0, feature=None):
        asked.append(req.headers)
        return Answer(gzip.compress(body))
    monkeypatch.setattr(net, "urlopen", opened)
    got = store.fetch_catalog()
    assert [s.id for s in got.lists[("trending", "")][0]] == ["000000000001"]
    assert asked[0].get("Accept-encoding") == "gzip"
    assert "X-onion-install" not in asked[0]   # (the same for everyone: no install id)
    assert (app_dir / "store" / "catalog.json").read_bytes() == body


def _json(d) -> bytes:
    import json
    return json.dumps(d).encode()
