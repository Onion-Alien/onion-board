"""The sound store (soundboard/store.py) and the Store tab (ui/storetab.py), against a
fake store: no test goes online."""
import io
import json
import re
import wave
from pathlib import Path

import numpy as np
import pytest
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

from soundboard import net, store
from soundboard.library import Config
from soundboard.ui import storetab
from soundboard.ui.tabcontrol import TAB_KEYS, rail_order


def _sound(i, **kw):
    d = {"id": f"{i:012x}", "name": f"Sound {i}", "ext": "wav", "size": 100, "up": 0,
         "down": 0, "author": "", "created": i, "mine": 0, "tags": ["meme"]}
    d.update(kw)
    return d


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((np.sin(np.arange(4800) / 10) * 8000).astype("<i2").tobytes())
    return buf.getvalue()


class FakeStore:
    """Stands in for store._request: answers like the server, and keeps what was asked."""

    def __init__(self, sounds):
        self.sounds = {s["id"]: s for s in sounds}
        self.calls = []
        self.fail = ""
        self.cats = []          # [(category, how many)] for /v1/categories
        self.fail_cats = False

    def __call__(self, method, path, install="", body=None, ctype="", limit=0, timeout=0):
        self.calls.append((method, path, install, body))
        if self.fail:
            raise store.StoreError(self.fail)
        if path == "/v1/categories":
            if self.fail_cats:
                raise store.StoreError("down")
            return json.dumps({"categories": [{"cat": c, "n": n} for c, n in self.cats],
                               "total": sum(n for _c, n in self.cats)}).encode()
        if path.startswith("/v1/sounds?"):
            return json.dumps({"sounds": list(self.sounds.values()), "more": False}).encode()
        sid = path.split("/")[3] if path.count("/") >= 3 else ""
        if path.endswith("/file"):
            return _wav()
        if path.endswith("/vote"):
            s = self.sounds[sid]
            v = json.loads(body)["value"]
            s["up"] += (v == 1) - (s["mine"] == 1)   # this install's vote moves
            s["down"] += (v == -1) - (s["mine"] == -1)
            s["mine"] = v
            return json.dumps({"up": s["up"], "down": s["down"], "mine": v}).encode()
        if path.endswith("/report"):
            return b'{"reported": true}'
        if path in ("/v1/sounds", "/v1/links"):
            return b'{"id": "abcdefabcdef", "status": "pending"}'
        raise AssertionError(path)


@pytest.fixture
def fake(monkeypatch, app_dir):
    f = FakeStore([_sound(1, up=5, author="Onion Board"), _sound(2, down=1, mine=-1)])
    monkeypatch.setattr(store, "_request", f)
    return f


def _wait(qapp, cond, n=300):
    return process_events(qapp, cond, timeout=n / 100)


def test_parse_leaves_out_odd_entries():
    good = _sound(1)
    found, more = store.parse({"sounds": [good, {**good, "id": "zz"}, {**good, "ext": "exe"},
                                          {**good, "id": f"{3:012x}", "name": ""},
                                          {"name": "no id"}, "junk"], "more": True})
    assert [s.id for s in found] == [good["id"]] and more


def test_install_id_is_made_once():
    cfg = Config()
    a = store.install_id(cfg)
    assert len(a) == 36 and store.install_id(cfg) == a == cfg.store_id


def test_check_file(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(_wav())
    assert store.check_file(str(p)) == ""
    (tmp_path / "b.exe").write_bytes(b"x")
    assert store.check_file(str(tmp_path / "b.exe"))
    big = tmp_path / "big.mp3"
    big.write_bytes(b"\0" * (store.MAX_BYTES + 1))
    assert store.check_file(str(big))


def test_upload_sends_the_agreement(fake, tmp_path):
    p = tmp_path / "horn.wav"
    p.write_bytes(_wav())
    assert store.upload("id-1234567890abcdef", str(p), "Horn", "meme") == "abcdefabcdef"
    method, path, install, body = fake.calls[-1]
    assert method == "POST" and path == "/v1/sounds" and install == "id-1234567890abcdef"
    assert store.AGREEMENT.encode() in body and b"Horn" in body


def test_rail_shows_store_before_setup():
    assert TAB_KEYS[-1] == "store"   # older configs' saved tab numbers still fit
    assert rail_order([]) == ["sounds", "radio", "apps", "triggers", "voice", "store", "setup"]
    dragged = ["voice", "sounds", "setup", "radio", "apps", "triggers"]
    assert rail_order(dragged) == ["voice", "sounds", "store", "setup", "radio", "apps",
                                   "triggers"]
    # an order saved by 2.3.0 / 2.3.1, with the Chat tab that's gone now
    assert "chat" not in rail_order([*dragged[:2], "store", "chat", *dragged[2:]])
    assert rail_order([*dragged, "store", "gone"])[-1] == "store"   # dragged last: kept


def _tab(qapp, added, played):
    t = storetab.StoreTab(Config(), added.append,
                          lambda data, gain: played.append(data) or True, lambda: None)
    t.resize(800, 600)
    t.show()
    return t


def test_tab_lists_votes_and_adds(qapp, fake):
    added, played = [], []
    t = _tab(qapp, added, played)
    assert _wait(qapp, lambda: len(t._rows) == 2)
    assert all(c[2] for c in fake.calls)   # the install id goes with every call
    a, b = t._rows
    assert a.btn_up.text() == "5" and b.btn_down.isChecked()
    assert a.meta.full.startswith("by Onion Board")
    a.btn_up.click()   # shown at once...
    assert a.btn_up.isChecked() and a.btn_up.text() == "6"
    assert _wait(qapp, lambda: ("000000000001", "vote") not in t._busy)
    assert a.btn_up.text() == "6"   # ...and the store's own count agrees
    b.btn_down.click()   # the same thumb again takes the vote back
    assert _wait(qapp, lambda: ("000000000002", "vote") not in t._busy)
    assert not b.btn_down.isChecked()
    a.btn_add.click()
    assert _wait(qapp, lambda: added)
    assert added[0].endswith("Sound 1.wav")
    a.btn_play.click()
    assert _wait(qapp, lambda: played and played[0] is not None)
    t.hide()   # another tab: the sample stops
    assert played[-1] is None
    t.shutdown()


def test_a_failed_list_says_why_and_retries(qapp, fake):
    fake.fail = "The sound store had a problem. Try again in a bit."
    t = _tab(qapp, [], [])
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.message
                 and t.msg_btn.isVisibleTo(t))
    assert fake.fail in t.msg_text.text()
    fake.fail = ""
    t.msg_btn.click()
    assert _wait(qapp, lambda: len(t._rows) == 2)
    t.shutdown()


def test_switched_off_contacts_nobody(qapp, fake, monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: f != store.FEATURE)
    t = _tab(qapp, [], [])
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.message)
    assert not fake.calls and "off" in t.msg_title.text().lower()
    t.shutdown()


def test_switched_off_while_loading_keeps_saying_off(qapp, fake, monkeypatch):
    # the list still on its way when the store is switched off: its late refusal
    # mustn't replace "The store is off" (and its way to Settings) with "Couldn't open"
    import threading
    go, asked = threading.Event(), threading.Event()
    plain = store._request

    def slow(method, path, *a, **kw):
        if path.startswith("/v1/sounds?"):
            asked.set()
            go.wait(5)
            raise store.StoreError("The sound store is switched off.")
        return plain(method, path, *a, **kw)
    monkeypatch.setattr(store, "_request", slow)
    t = _tab(qapp, [], [])
    assert _wait(qapp, asked.is_set)
    monkeypatch.setattr(net, "allowed", lambda f: f != store.FEATURE)
    t.reload()
    assert "off" in t.msg_title.text().lower()
    go.set()
    _wait(qapp, lambda: False, n=30)
    assert t.msg_title.text() == storetab._("The store is off") and t.msg_btn.isVisibleTo(t)
    t.shutdown()


def test_a_late_answer_after_shutdown_is_dropped(qapp, fake):
    t = _tab(qapp, [], [])
    t.shutdown()
    _wait(qapp, lambda: False, n=20)
    assert not t._rows


def test_share_needs_a_file_a_name_and_the_tick(qapp, fake, tmp_path):
    from soundboard.ui import busy
    p = tmp_path / "my horn.wav"
    p.write_bytes(_wav())
    d = storetab.ShareDialog("id-1234567890abcdef")
    assert busy.is_busy(d.btn_send)
    d.set_file(str(p))
    assert d.name.text() == "my horn" and busy.is_busy(d.btn_send)
    d.agree.setChecked(True)
    assert not busy.is_busy(d.btn_send)
    d.btn_send.click()
    assert _wait(qapp, lambda: d.sent)
    assert fake.calls[-1][1] == "/v1/sounds"
    d.close()


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_store_tab_in_the_window(window, qapp, tmp_path):
    from soundboard.ui.tabcontrol import TAB_INDEX
    i = TAB_INDEX["store"]
    assert isinstance(window.store, storetab.StoreTab) and window.tabs.isTabVisible(i)
    order = [b.index for b in window.rail.buttons]
    assert order.index(i) == order.index(TAB_INDEX["setup"]) - 1   # right before Setup
    window.tabctl.set_tab_on("store", False)
    assert not isinstance(window.store, storetab.StoreTab)
    window.tabctl.set_tab_on("store", True)
    assert isinstance(window.store, storetab.StoreTab)
    # the tab's "Add" goes through the window's own importer (a file dropped on it)
    f = tmp_path / "Store horn.wav"
    f.write_bytes(_wav())
    n = len(window.cfg.sounds)
    window.store._add_file(str(f))
    assert process_events(qapp, lambda: len(window.cfg.sounds) == n + 1, timeout=15)
    assert window.cfg.sounds[-1].name == "Store horn"


def test_links_parse_only_known_sites():
    ok = _sound(7, ext="link", link="https://youtube.com/watch?v=abc")
    bad = [_sound(8, ext="link", link="https://evil.example.com/a.mp3"),
           _sound(9, ext="link", link="http://youtube.com/watch?v=abc"),
           _sound(10, ext="link", link="")]
    found, _more = store.parse({"sounds": [ok, *bad]})
    assert [s.id for s in found] == [ok["id"]] and found[0].is_link
    assert storetab.meta_line(found[0]).startswith("YouTube link")


def test_share_link_sends_only_the_link(fake):
    fake_ok = b'{"id": "abcdefabcdef", "status": "pending"}'
    calls = []

    def answer(method, path, install="", body=None, *a, **k):
        calls.append((path, json.loads(body)))
        return fake_ok
    store._request = answer   # (fake's monkeypatch puts it back)
    assert store.share_link("id-1234567890abcdef", "https://youtu.be/xyz", "Clip") == \
        "abcdefabcdef"
    path, sent = calls[-1]
    assert path == "/v1/links" and sent["agree"] == store.LINK_AGREEMENT
    assert sent["link"] == "https://youtu.be/xyz" and "file" not in sent
    with pytest.raises(store.StoreError):
        store.share_link("id-1234567890abcdef", "https://example.com/x", "x")


def test_a_link_row_goes_through_the_link_downloader(qapp, fake):
    fake.sounds = {f"{7:012x}": _sound(7, ext="link", link="https://youtube.com/watch?v=abc",
                                       name="Clip")}
    links = []
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None,
                          link=lambda url, name, kind: links.append((url, name, kind)))
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 1)
    r = t._rows[0]
    r.btn_play.click()
    r.btn_add.click()
    assert links == [("https://youtube.com/watch?v=abc", "Clip", "play"),
                     ("https://youtube.com/watch?v=abc", "Clip", "add")]
    assert not r.btn_play.isChecked()   # (nothing plays in the tab itself)
    assert not any(c[1].endswith("/file") for c in fake.calls)
    t.shutdown()


def test_share_window_on_a_link(qapp, fake):
    from soundboard.ui import busy
    d = storetab.ShareDialog("id-1234567890abcdef", None, "https://youtu.be/xyz", "Bruh")
    assert d.mode == "link" and d.name.text() == "Bruh" and not d.agree.isVisibleTo(d)
    assert not busy.is_busy(d.btn_send)   # a link needs no tick
    d.link.setText("https://example.com/not-a-video")
    assert busy.is_busy(d.btn_send)
    d.link.setText("https://youtu.be/xyz")
    d.btn_send.click()
    assert _wait(qapp, lambda: d.sent)
    assert fake.calls[-1][1] == "/v1/links"
    d.close()


def test_card_tooltips_never_read_html(qapp):
    from soundboard.ui.ytsearch import ClampLabel, plain_tip
    lbl = ClampLabel('<img src="x"><b>Loud</b> & proud')
    assert lbl.toolTip() == plain_tip('<img src="x"><b>Loud</b> & proud')
    assert "<img" not in lbl.toolTip() and "&lt;img" in lbl.toolTip()
    lbl.set_full("a", "<b>b</b>")
    assert lbl.toolTip() == "<p>&lt;b&gt;b&lt;/b&gt;</p>"
    assert plain_tip("") == ""


def test_categories_filter_the_list(qapp, fake):
    fake.cats = [("games", 3), ("memes", 1)]
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 2 and len(t.cat_btns) == 3)
    assert t.cats_box.isVisibleTo(t)
    assert [b.text() for b in t.cat_btns.values()] == ["All  4", "Games  3", "Memes  1"]
    assert t.cat_btns[""].isChecked()
    t.cat_btns["games"].click()
    assert _wait(qapp, lambda: "cat=games" in fake.calls[-1][1])
    assert t.cat_btns["games"].isChecked() and not t.cat_btns[""].isChecked()
    # the order and the words keep the category
    t.sort_btns[storetab.TRENDING].click()
    assert _wait(qapp, lambda: "sort=trending" in fake.calls[-1][1]
                 and "cat=games" in fake.calls[-1][1])
    assert sum(c[1] == "/v1/categories" for c in fake.calls) == 1   # asked once
    # an empty category: a way back to All (the chips are in the list)
    fake.sounds = {}
    t.set_cat("memes")
    assert _wait(qapp, lambda: t.msg_btn.isVisibleTo(t) and t.msg_btn.text() == "All")
    t.msg_btn.click()
    assert _wait(qapp, lambda: "cat=" not in fake.calls[-1][1])
    t.shutdown()


def test_no_categories_no_chips(qapp, fake):
    fake.fail_cats = True
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 2)
    qapp.processEvents()
    assert not t.cats_box.isVisibleTo(t)
    t.shutdown()


def test_a_sound_from_myinstants_is_voted_on_and_comes_from_the_site(qapp, fake):
    fake.sounds = {f"{8:012x}": _sound(8, ext="link", name="Vine boom", up=3, tags=["memes"],
                                       link="https://myinstants.com/media/sounds/vine-boom.mp3",
                                       author="Myinstants", source="myinstants", cat="memes")}
    links = []
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None,
                          link=lambda url, name, kind: links.append((url, name, kind)))
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 1)
    r = t._rows[0]
    assert r.meta.full == "From Myinstants · Memes"
    assert r.btn_up.isVisibleTo(r) and r.btn_report.isVisibleTo(r)
    r.btn_up.click()
    assert _wait(qapp, lambda: any(c[1].endswith("/vote") for c in fake.calls))
    r.btn_add.click()
    assert links == [("https://myinstants.com/media/sounds/vine-boom.mp3", "Vine boom", "add")]
    assert not any(c[1].endswith("/file") for c in fake.calls)
    t.shutdown()


def test_parse_keeps_known_categories_only():
    found, _more = store.parse({"sounds": [_sound(1, cat="games", source="myinstants"),
                                           _sound(2, cat="bogus")]})
    assert [(s.cat, s.source) for s in found] == [("games", "myinstants"), ("", "")]
    assert store.cat_name("tv") == "TV" and store.cat_name("bogus") == ""
    # the same list as the server's (server/store/src/index.js)
    server = (Path(__file__).parent.parent / "server" / "store" / "src" / "index.js"
              ).read_text("utf-8")
    m = re.search(r"export const CATS = \[(.*?)\];", server, re.S)
    assert m and re.findall(r'"([a-z]+)"', m.group(1)) == list(store.CATS)
