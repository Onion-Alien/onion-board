"""The sound store (soundboard/online/store.py) and the Store tab (ui/store/storetab.py), against a
fake store: no test goes online."""
import io
import json
import re
import time
import wave

import numpy as np
import pytest
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

from soundboard.online import net, store
from soundboard.sounds.library import Config
from soundboard.ui.store import storetab
from soundboard.ui.window.tabcontrol import TAB_KEYS, rail_order


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
        self.catalog = None     # /v1/catalog's answer (a dict); None: an older store without
        self.catalog_calls = 0

    def __call__(self, method, path, install="", body=None, ctype="", limit=0, timeout=0, **kw):
        if path == "/v1/catalog":   # (asked as the tab is made: not in `calls`)
            self.catalog_calls += 1
            if self.catalog is None:
                raise store.StoreError("not found")
            return json.dumps(self.catalog).encode()
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
    # the file's own name stays on this PC
    mine = tmp_path / "My Name mic take.wav"
    mine.write_bytes(_wav() + b"x")
    store.upload("id-1234567890abcdef", str(mine), "Horn 2")
    body = fake.calls[-1][3]
    assert b'filename="sound.wav"' in body and b"My" not in body.replace(b"Horn", b"")


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
    """`played`: what went to the player, (key, now); `t.states`: the player's state of
    a key (link_state)."""
    states: dict[str, str] = {}
    t = storetab.StoreTab(Config(), added.append, lambda data, gain: True, lambda: None,
                          link_state=lambda key: states.get(key, ""),
                          play_file=lambda data, gain, name, key, now:
                          played.append((key, now)) or True)
    t.states = states
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
    a.btn_play.click()   # an upload plays in the player, as a pad does
    assert a.btn_play.isChecked()   # (loading)
    assert _wait(qapp, lambda: played == [("community:000000000001", True)])
    assert ("000000000001", "now") not in t._busy
    t.states["community:000000000001"] = "playing"
    assert _wait(qapp, lambda: a.btn_play.text() == "Pause" and a.btn_stop.isVisibleTo(a))
    t.hide()   # another tab: it plays on
    assert played == [("community:000000000001", True)]
    t.shutdown()


def test_an_upload_card_pauses_stops_and_queues_as_a_link_does(qapp, fake):
    """An upload's card has the link's Play next and Stop, and its Pause / Stop go to
    the player by its key."""
    links, played = [], []
    states: dict[str, str] = {}
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None,
                          link=lambda key, name, kind: links.append((key, kind)),
                          link_state=lambda key: states.get(key, ""),
                          play_file=lambda d, g, name, key, now: played.append((key, now)))
    t.resize(560, 700)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 2)
    r = t._rows[0]
    key = "community:000000000001"
    assert r.btn_queue.isVisibleTo(r) and r.btn_play.toolTip() == "Play it now"
    r.btn_queue.click()
    assert _wait(qapp, lambda: played == [(key, False)])
    states[key] = "playing"
    assert _wait(qapp, lambda: r.btn_stop.isVisibleTo(r))
    r.btn_play.click()
    assert links[-1] == (key, "pause")
    r.btn_stop.click()
    assert links[-1] == (key, "stop")
    t.shutdown()


def test_a_failed_list_says_why_and_retries(qapp, fake):
    fake.fail = "The sound store had a problem. Try again in a bit."
    t = _tab(qapp, [], [])
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.oops_page
                 and t.oops.btn_retry.isVisibleTo(t))
    assert fake.fail in t.oops.line.text() and t.failed
    fake.fail = ""
    t.oops.btn_retry.click()
    assert _wait(qapp, lambda: len(t._rows) == 2)
    t.shutdown()


def test_store_down_shows_the_sad_bun_card_then_the_list(qapp, fake, monkeypatch):
    # the server answers with an error of its own: the store's down, not the user's fault
    down = store.StoreDown()
    plain = store._request

    def broken(method, path, *a, **kw):
        if path.startswith("/v1/sounds?"):
            raise down
        return plain(method, path, *a, **kw)
    monkeypatch.setattr(store, "_request", broken)
    t = _tab(qapp, [], [])
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.oops_page
                 and t.oops.btn_retry.isVisibleTo(t))
    assert t.failed and t.oops.title.text() == storetab._("Sorry, the store's down")
    assert "working on" in t.oops.line.text() and t.oops.property("tone") == "error"
    assert t.oops.bun.isVisibleTo(t) and t.oops.bun.sulk
    # nothing the user can fix: no "close Onion Board and open it again", no Report
    assert not t.oops.btn_report.isVisibleTo(t) and not t.oops.what.isVisibleTo(t)
    t.resize(800, 260)                # no room for him: the words stay
    assert _wait(qapp, lambda: not t.oops.bun.isVisibleTo(t))
    assert t.oops.title.isVisibleTo(t)
    t.resize(800, 600)
    assert _wait(qapp, lambda: t.oops.bun.isVisibleTo(t))
    monkeypatch.setattr(store, "_request", plain)
    t.oops.btn_retry.click()
    assert _wait(qapp, lambda: len(t._rows) == 2)
    assert not t.failed and t.stack.currentWidget() is not t.oops_page
    assert t.bun.isVisibleTo(t)
    t.shutdown()


def test_server_errors_mean_the_store_is_down(monkeypatch):
    import urllib.error

    def answer(code, err):
        def urlopen(req, timeout=0, feature=""):
            raise urllib.error.HTTPError("u", code, "x", {},
                                         io.BytesIO(json.dumps({"error": err}).encode()))
        monkeypatch.setattr(net, "urlopen", urlopen)
        with pytest.raises(store.StoreError) as e:
            store._request("GET", "/v1/sounds")
        return e.value
    assert isinstance(answer(500, "server"), store.StoreDown)
    assert isinstance(answer(502, ""), store.StoreDown)
    assert not isinstance(answer(503, "queue full"), store.StoreDown)   # its own message
    assert not isinstance(answer(404, "not found"), store.StoreDown)
    assert answer(500, "server").back == 0


def test_the_free_plans_limit_used_up_is_maintenance_with_how_long(monkeypatch):
    import urllib.error

    def urlopen(req, timeout=0, feature=""):
        raise urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(
            json.dumps({"error": "maintenance", "in": 5 * 3600 + 600}).encode()))
    monkeypatch.setattr(net, "urlopen", urlopen)
    with pytest.raises(store.StoreDown) as e:
        store._request("GET", "/v1/sounds")
    assert store.is_down() and e.value.back > 0
    title, line = store.down_words(e.value.back)
    assert title == "The store's down for maintenance"
    assert line == "It'll be back in about 5 hours."
    assert str(e.value) == f"{title}. {line}"
    assert store.down_words(store.time.time() + 600)[1] == "It'll be back in under an hour."
    assert store.down_words(0)[0] == "Sorry, the store's down"


def test_maintenance_card_says_how_long_and_nothing_to_fix(qapp, fake, monkeypatch):
    plain = store._request
    back = store.time.time() + 3 * 3600

    def broken(method, path, *a, **kw):
        if path.startswith("/v1/sounds?"):
            raise store.StoreDown(back)
        return plain(method, path, *a, **kw)
    monkeypatch.setattr(store, "_request", broken)
    t = _tab(qapp, [], [])
    assert _wait(qapp, lambda: t.stack.currentWidget() is t.oops_page
                 and t.oops.btn_retry.isVisibleTo(t))
    assert t.oops.title.text() == "The store's down for maintenance"
    assert "about 3 hours" in t.oops.line.text()
    assert not t.oops.btn_report.isVisibleTo(t) and not t.oops.what.isVisibleTo(t)
    t.shutdown()


@pytest.fixture(autouse=True)
def _store_up():
    store._failing.clear()   # (a 500 in one test would grey Share out in the next)
    yield
    store._failing.clear()


def test_a_500_turns_sharing_off_until_that_call_works(monkeypatch):
    import urllib.error
    ok = {"/v1/categories": False}

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def urlopen(req, timeout=0, feature=""):
        path = req.full_url.removeprefix(store.BASE).split("?")[0]
        if not ok.get(path, True):
            raise urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b'{"error": "server"}'))
        return Answer(b'{"sounds": [], "more": false}')
    monkeypatch.setattr(net, "urlopen", urlopen)
    assert not store.is_down()
    with pytest.raises(store.StoreDown):
        store._request("GET", "/v1/categories")
    assert store.is_down()
    store._request("GET", "/v1/sounds?sort=top")   # another call working isn't enough
    assert store.is_down()
    ok["/v1/categories"] = True
    store._request("GET", "/v1/categories")
    assert not store.is_down()


def test_share_is_greyed_out_while_the_store_is_down(qapp, fake, monkeypatch):
    plain = store._request

    def broken(method, path, *a, **kw):
        if path == "/v1/categories":
            store._failing.add(path)
            raise store.StoreDown()
        return plain(method, path, *a, **kw)
    monkeypatch.setattr(store, "_request", broken)
    t = _tab(qapp, [], [])
    assert _wait(qapp, lambda: len(t._rows) == 2 and not t.btn_share.isEnabled())
    assert t.btn_share.toolTip() == store.down_share()
    opened = []
    monkeypatch.setattr(storetab, "ShareDialog", lambda *a, **k: opened.append(a))
    t.share("https://youtu.be/xyz", "Bruh")   # a pad's "Share to the store…" too
    assert not opened

    def fixed(*a, **k):
        store._failing.clear()   # (the categories answer again)
        return plain(*a, **k)
    monkeypatch.setattr(store, "_request", fixed)
    t.reload(fresh=True)
    assert _wait(qapp, lambda: t.btn_share.isEnabled())
    assert t.btn_share.toolTip() == ""
    t.shutdown()


def test_bun_kicks_back_then_out_then_rests():
    from soundboard.ui.bun.bunnywidget import SULK_EVERY, sulk_kick
    ks = [sulk_kick(SULK_EVERY * i / 100)[0] for i in range(100)]
    assert min(ks) < -0.5 and max(ks) > 0.95 and ks[-1] == 0.0
    assert ks.index(min(ks)) < ks.index(max(ks))   # draws back, then kicks


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


def test_switched_off_in_settings_while_loading_says_off(qapp, fake, monkeypatch):
    # the switch in Settings > Privacy while the list is on its way, with no reload: the
    # cut connection's late failure said "Couldn't open the store" over "The store is off"
    import threading
    go, asked = threading.Event(), threading.Event()
    plain = store._request

    def slow(method, path, *a, **kw):
        if path.startswith("/v1/sounds?"):
            asked.set()
            go.wait(5)
            raise store.StoreError("Couldn't reach the sound store. Check your internet.")
        return plain(method, path, *a, **kw)
    monkeypatch.setattr(store, "_request", slow)
    t = _tab(qapp, [], [])
    assert _wait(qapp, asked.is_set)
    net.configure_features(off=[store.FEATURE])
    go.set()
    _wait(qapp, lambda: False, n=30)
    assert t.msg_title.text() == storetab._("The store is off") and t.msg_btn.isVisibleTo(t)
    monkeypatch.setattr(store, "_request", plain)
    net.configure_features()   # back on: the list comes again
    assert _wait(qapp, lambda: len(t._rows) == 2)
    t.shutdown()


def test_a_late_answer_after_shutdown_is_dropped(qapp, fake):
    t = _tab(qapp, [], [])
    t.shutdown()
    _wait(qapp, lambda: False, n=20)
    assert not t._rows


def test_share_needs_a_file_a_name_and_the_tick(qapp, fake, tmp_path):
    from soundboard.ui.kit import busy
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
    from soundboard.ui.window.tabcontrol import TAB_INDEX
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


def _chip_name(window) -> str:
    from PySide6.QtWidgets import QPushButton

    from soundboard.ui.sounds.linkbar import PLAY_ID
    chip = window._chips.get(PLAY_ID)
    return chip.findChild(QPushButton, "chipname").text() if chip is not None else ""


def test_community_play_plays_as_a_pad_in_the_window(window, qapp, monkeypatch):
    """An upload's Play in the real window: the pad playing stops (as a pad's press
    stops it), the player bar and its Now playing chip show the sound, and another
    Play swaps it, chip and all."""
    from soundboard.audio.engine import SR
    from soundboard.ui.sounds.linkbar import PLAY_ID
    from soundboard.ui.window.tabcontrol import TAB_INDEX
    from test_space_and_playing import FakePlayer
    monkeypatch.setattr(store, "_request", FakeStore([_sound(1, name="Air horn"),
                                                      _sound(2, name="Gasp")]))
    player = FakePlayer(window, monkeypatch)
    plain = window.engine.play

    def play(sid, *a, **k):   # (solo: the other pads stop, as the engine does)
        if k.get("mode") == "solo":
            for s in [s for s in player.voices if s != sid and not s.startswith("__")]:
                player.voices.pop(s)
        return plain(sid, *a, **k)
    monkeypatch.setattr(window.engine, "play", play)
    sid = window.cfg.sounds[0].id
    window.audio[sid] = np.zeros((SR * 5, 2), dtype=np.float32)
    window.playctl.play(sid)
    assert sid in player.voices
    window.show()
    window.tabs.setCurrentIndex(TAB_INDEX["store"])
    t = window.store
    assert process_events(qapp, lambda: len(t._rows) == 2, timeout=10)
    a, b = t._rows
    a.btn_play.click()
    assert process_events(qapp, lambda: PLAY_ID in player.voices, timeout=10)
    assert sid not in player.voices and window.meta(PLAY_ID).name == "Air horn"
    assert process_events(qapp, lambda: window.transport.isVisible()
                          and a.btn_play.text() == "Pause", timeout=5)
    assert process_events(qapp, lambda: _chip_name(window).startswith("Air horn"), timeout=5)
    b.btn_play.click()
    assert process_events(qapp, lambda: window.meta(PLAY_ID).name == "Gasp", timeout=10)
    assert process_events(qapp, lambda: _chip_name(window).startswith("Gasp")
                          and a.btn_play.text() == "Play", timeout=5)


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
    assert links == [("https://youtube.com/watch?v=abc", "Clip", "now"),
                     ("https://youtube.com/watch?v=abc", "Clip", "add")]
    assert not r.btn_play.isChecked()   # (nothing plays in the tab itself)
    assert not any(c[1].endswith("/file") for c in fake.calls)
    t.shutdown()


def test_share_window_on_a_link(qapp, fake):
    from soundboard.ui.kit import busy
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
    from soundboard.ui.sounds.ytsearch import ClampLabel, plain_tip
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
    pick = t.cat_pick
    assert _wait(qapp, lambda: len(t._rows) == 2 and pick.count() == 7)
    # Trending (picked), Most liked and Newest: every sound; Community uploads; a line under
    # them (an order read as one more category beside "Games (3)"); then the categories
    assert [pick.itemText(i) for i in range(7)] == ["Trending", "Most liked", "Newest",
                                                    "Community uploads", "",
                                                    "Games (3)", "Memes (1)"]
    assert pick.currentIndex() == 0
    # it opens on Trending: what's popular right now
    assert "sort=trending" in next(c[1] for c in fake.calls if c[1].startswith("/v1/sounds"))
    pick.activated.emit(pick.findData("games"))
    assert _wait(qapp, lambda: "cat=games" in fake.calls[-1][1])
    assert pick.currentData() == "games"
    # the order and the words keep the category
    t.set_sort("new")
    assert _wait(qapp, lambda: "sort=new" in fake.calls[-1][1]
                 and "cat=games" in fake.calls[-1][1])
    assert sum(c[1] == "/v1/categories" for c in fake.calls) == 1   # asked once
    # an empty category: a way back to All
    fake.sounds = {}
    t.set_cat("memes")
    assert _wait(qapp, lambda: t.msg_btn.isVisibleTo(t) and t.msg_btn.text() == "All")
    t.msg_btn.click()
    assert _wait(qapp, lambda: "cat=" not in fake.calls[-1][1])
    # every sound, newest first: the box says Newest
    assert pick.currentData() == "@new"
    # Trending was had when the tab opened: shown again as it was, the store not asked
    asked = len(fake.calls)
    pick.activated.emit(pick.findData("@trending"))
    assert _wait(qapp, lambda: len(t._rows) == 2)
    assert len(fake.calls) == asked and pick.currentData() == "@trending"
    # Most liked: every sound by votes, not had yet
    pick.activated.emit(pick.findData("@top"))
    assert _wait(qapp, lambda: "sort=top" in fake.calls[-1][1] and "cat=" not in fake.calls[-1][1])
    # Refresh asks for the list and the categories again
    asked = len(fake.calls)
    t.btn_reload.click()
    assert _wait(qapp, lambda: sum(c[1] == "/v1/categories" for c in fake.calls) == 2
                 and any("sort=top" in c[1] for c in fake.calls[asked:]))
    t.shutdown()


def test_the_list_is_not_a_tab_stop(qapp, fake):
    """Tab went to the list itself first: a stop with no name a screen reader could say."""
    from PySide6.QtCore import Qt
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.show()
    assert _wait(qapp, lambda: t._rows)
    assert t.list_area.focusPolicy() == Qt.FocusPolicy.NoFocus
    t.shutdown()


def test_switched_back_on_the_store_says_so(qapp, fake):
    """Community off and on again in Privacy: the list just reloaded, no word why."""
    from conftest import said
    from soundboard.online import net, store
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.show()
    assert _wait(qapp, lambda: t._rows)
    try:
        net.configure_features([store.FEATURE])
        t._follow_switch()
        assert t._off
        net.configure_features()
        t._follow_switch()
        assert "on again" in said(t)
    finally:
        net.configure_features()
        t.shutdown()


def test_community_uploads_lists_the_stores_own_sounds(qapp, fake):
    # up with the orders, not among the categories; picking it asks for the store's own
    # sounds only, and the box shows it picked
    fake.cats = [("onionboard", 2), ("games", 3)]
    fake.sounds["000000000002"]["cat"] = "onionboard"   # never a sound's own category
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.show()
    pick = t.cat_pick
    assert _wait(qapp, lambda: len(t._rows) == 2 and pick.count() == 6)
    assert pick.itemText(3) == "Community uploads" and pick.itemData(3) == "onionboard"
    assert [pick.itemText(i) for i in range(5, 6)] == ["Games (3)"]
    pick.activated.emit(pick.findData("onionboard"))
    assert _wait(qapp, lambda: "cat=onionboard" in fake.calls[-1][1])
    assert pick.currentText() == "Community uploads"
    assert _wait(qapp, lambda: len(t._rows) == 2)
    assert [s.cat for s in store.parse({"sounds": list(fake.sounds.values())})[0]] == ["", ""]
    t.shutdown()


def test_no_categories_only_all(qapp, fake):
    fake.fail_cats = True
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 2)
    qapp.processEvents()
    assert t.cat_pick.count() == 4 and t.cat_pick.currentData() == "@trending"
    t.shutdown()


def test_cards_fill_the_tab_as_many_a_row_as_fit(qapp, fake):
    fake.sounds = {f"{i:012x}": _sound(i, cat="games", created=int(time.time()) - 3 * 86400)
                   for i in range(1, 7)}
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    t.resize(1800, 700)   # a wide window: the cards use its whole width, 3 or more a row
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 6 and t.stack.currentWidget() is t.list_area)
    process_events(qapp, lambda: False, timeout=0.3)
    row = [r for r in t._rows if r.y() == t._rows[0].y()]
    assert 3 <= len(row) < 6 and t._rows[5].y() > t._rows[0].y()
    assert row[-1].geometry().right() > 1600
    t.resize(1150, 700)
    process_events(qapp, lambda: False, timeout=0.3)
    a, b, c = t._rows[:3]
    assert a.where.text() == "Games · 3 days ago"
    assert a.y() == b.y() and b.x() > a.x() and c.y() > a.y()   # two a row
    assert a.btn_play.text() and a.btn_add.text()
    t.resize(560, 700)
    process_events(qapp, lambda: False, timeout=0.3)
    assert a.x() == b.x() and b.y() > a.y()   # one a row
    # every width down to the smallest window's tab: a card never wider than the list,
    # its buttons' words going (their pictures stay) before Report would be cut off
    for width in range(1900, 419, -20):
        t.resize(width, 700)
        process_events(qapp, lambda: False, timeout=0.05)
        room = t.list_area.viewport().width() - storetab.LIST_GAP
        for r in t._rows:
            assert r.geometry().right() < room, width
            assert r.btn_report.mapTo(r, r.btn_report.rect().topRight()).x() < r.width(), width
    t.shutdown()


def test_cards_fit_by_the_widest_card_not_the_first(qapp, fake):
    # the first card a plain file (no Play next) with a short second line; the rest links
    # with a longer one, one playing (Pause and Stop): none past the list's edge, and
    # LIST_GAP left between the cards and the scroll bar
    url = "https://www.myinstants.com/en/instant/bruh/"
    fake.sounds = {f"{1:012x}": _sound(1, cat="games", created=int(time.time()) - 86400)}
    for i in range(2, 30):
        fake.sounds[f"{i:012x}"] = _sound(i, ext="link", link=url if i == 2 else f"{url}{i}/",
                                          cat="reactions",
                                          created=int(time.time()) - 33 * 86400)
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None,
                          link=lambda u, name, kind: None,
                          link_state=lambda u: "playing" if u == url else "")
    t.resize(1900, 700)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 29 and t.stack.currentWidget() is t.list_area)
    assert _wait(qapp, lambda: t._rows[1].btn_stop.isVisibleTo(t._rows[1]))
    for width in range(1900, 419, -15):
        t.resize(width, 700)
        process_events(qapp, lambda: False, timeout=0.05)
        room = t.list_area.viewport().width() - storetab.LIST_GAP
        for r in t._rows:
            assert r.geometry().right() < room, width
            assert r.btn_report.mapTo(r, r.btn_report.rect().topRight()).x() < r.width(), width
    t.shutdown()


def test_playing_a_link_never_moves_the_cards(qapp, fake):
    # Pause and Stop coming out on one card: no column grows, no card moves
    url = "https://www.myinstants.com/en/instant/bruh/"
    fake.sounds = {f"{i:012x}": _sound(i, ext="link", link=f"{url}{i}/", cat="reactions",
                                       name="Michael Jackson Hee Hee" if i == 11 else f"S{i}",
                                       created=int(time.time()) - 33 * 86400)
                   for i in range(1, 25)}
    state = {"now": ""}
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None,
                          link=lambda u, name, kind: None,
                          link_state=lambda u: state["now"] if u == f"{url}11/" else "")
    t.resize(1900, 700)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 24 and t.stack.currentWidget() is t.list_area)
    r = t._rows[10]
    for width in (1900, 1600, 1250, 900, 640, 440):
        t.resize(width, 700)
        state["now"] = ""
        assert _wait(qapp, lambda: not r.btn_stop.isVisibleTo(r))
        process_events(qapp, lambda: False, timeout=0.1)
        before = [c.geometry() for c in t._rows]
        state["now"] = "playing"
        assert _wait(qapp, lambda: r.btn_stop.isVisibleTo(r))
        process_events(qapp, lambda: False, timeout=0.1)
        assert [c.geometry() for c in t._rows] == before, width
    t.shutdown()


def test_a_link_card_plays_now_pauses_stops_and_queues(qapp, fake):
    """Play plays a link now (over one that's playing), then turns Pause, Resume while
    it's paused, with Stop beside it; Play next waits for what's playing. The card follows
    the player, which the bottom strip stops and pauses too."""
    url = "https://www.myinstants.com/en/instant/bruh/"
    fake.sounds = {f"{9:012x}": _sound(9, ext="link", link=url, name="BRUH")}
    links, state = [], {"now": ""}
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None,
                          link=lambda u, name, kind: links.append(kind),
                          link_state=lambda u: state["now"] if u == url else "")
    t.resize(560, 700)   # (one card a row, room for its buttons' words)
    t.show()
    assert _wait(qapp, lambda: len(t._rows) == 1)
    r = t._rows[0]
    assert r.btn_queue.isVisibleTo(r) and not r.btn_stop.isVisibleTo(r)
    r.btn_play.click()
    assert links == ["now"] and not r.btn_play.isChecked()
    state["now"] = "loading"
    assert _wait(qapp, lambda: r.btn_play.isChecked())
    r.btn_play.click()   # (still downloading: nothing more)
    assert links == ["now"]
    state["now"] = "playing"
    assert _wait(qapp, lambda: r.btn_stop.isVisibleTo(r))
    assert r.btn_play.text() == "Pause" and r.tile.playing
    r.btn_play.click()
    assert links[-1] == "pause"
    state["now"] = "paused"
    assert _wait(qapp, lambda: r.btn_play.text() == "Resume")
    assert not r.tile.playing
    r.btn_stop.click()
    assert links[-1] == "stop"
    state["now"] = ""   # (stopped, or ended)
    assert _wait(qapp, lambda: not r.btn_stop.isVisibleTo(r))
    assert r.btn_play.text() == "Play" and not r.btn_play.isChecked()
    r.btn_queue.click()
    assert links[-1] == "play"
    t.shutdown()


def test_rows_keep_clear_of_the_scroll_bar(qapp, fake):
    from uicheck import assert_breathing_room
    fake.sounds = {f"{i:012x}": _sound(i) for i in range(1, 21)}   # enough to scroll
    t = storetab.StoreTab(Config(), [].append, lambda d, g: True, lambda: None)
    for width in (800, 620, 420):
        t.resize(width, 500)
        t.show()
        assert _wait(qapp, lambda: len(t._rows) == 20)
        process_events(qapp, lambda: False, timeout=0.2)
        assert t.list_area.verticalScrollBar().isVisible()
        assert_breathing_room(t.list_area, edge=0)   # 8 px between every row and the bar
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
    assert r.meta.full == "From Myinstants" and r.where.text().startswith("Memes")
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


def test_a_file_that_isnt_the_sound_it_says_is_not_kept(fake, monkeypatch):
    """The server walks every file it takes; the app still keeps only what starts like the
    sound it was told about (never a program or a page saved as "x.wav")."""
    s = store.parse({"sounds": [_sound(7, name="tricky")]})[0][0]
    assert store.looks_like(_wav(), "wav") and not store.looks_like(_wav(), "mp3")
    for junk in (b"MZ\x90\x00" + bytes(100), b"<html><script>alert(1)</script></html>",
                 b"#!/bin/sh\nrm -rf ~\n" * 4, b"", b"RIFF"):
        monkeypatch.setattr(store, "_request", lambda *a, j=junk, **k: j)
        with pytest.raises(store.StoreError):
            store.fetch(s)
        assert not s.path.exists() and not s.path.with_name(s.path.name + ".part").exists()
    monkeypatch.setattr(store, "_request", fake)
    assert store.fetch(s).read_bytes() == _wav()


def test_a_store_name_never_leaves_the_store_folder_or_hides_its_type(fake):
    root = (store.library.APP_DIR / "store").resolve()
    for name in ("../../../evil", r"..\..\Startup\x", r"C:\Windows\x", "con", "a\u202e3pm.exe",
                 "x\u200b\u2066.bat", "<script>"):
        s = store.Sound(id="0123456789ab", name=name, ext="wav")
        p = s.path.resolve()
        assert p.is_relative_to(root) and p.parent.name == "0123456789ab", name
        assert p.suffix == ".wav"
        assert not re.search("[\u200b-\u200f\u202a-\u202e\u2066-\u2069<>]", p.name), name


def test_every_sound_gets_a_picture_from_its_name_tags_or_category():
    """The Store rows' tiles: a word in the name first, then the tags, then the category's
    picture, else a speaker; the same sound always gets the same colour."""
    from soundboard.ui.store import storelook

    def snd(**kw):
        return store.Sound(**{"id": "000000000001", "name": "Xyz", "ext": "wav", **kw})
    assert storelook.sound_emoji(snd(name="Air horn (stadium)")) == "📢"
    assert storelook.sound_emoji(snd(name="Tavern crowd chatter")) == "🍺"
    assert storelook.sound_emoji(snd(tags=["horror"])) == "👻"
    assert storelook.sound_emoji(snd(cat="games")) == "🎮"
    assert storelook.sound_emoji(snd(name="Whatever")) == storelook.FALLBACK
    # whole words only: "Window" isn't "win", "Alright" isn't "right"
    assert storelook.sound_emoji(snd(name="Window")) == storelook.FALLBACK
    assert storelook.sound_emoji(snd(name="Alright")) == storelook.FALLBACK
    assert storelook.tile_hue(snd(id="abc")) == storelook.tile_hue(snd(id="abc"))


def test_a_row_plays_from_its_picture_and_shows_it_playing(qapp, fake):
    """A click on a card's picture is its play; while it plays the picture's bars
    bounce."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    added, played = [], []
    t = _tab(qapp, added, played)
    assert _wait(qapp, lambda: len(t._rows) == 2)
    r = t._rows[0]
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    r.tile.mousePressEvent(press)
    assert r.btn_play.isChecked()
    assert _wait(qapp, lambda: played)
    t.states["community:000000000001"] = "playing"
    assert _wait(qapp, lambda: r.tile.playing)
    t.states.clear()   # (it ended)
    assert _wait(qapp, lambda: not r.tile.playing and not r.btn_play.isChecked())
    t.shutdown()


def test_a_refused_name_or_tags_says_so():
    # the server refuses a link or a blocked word in a shared name or its tags
    said = store._why(422, "not allowed")
    assert "name" in said and "links" in said
    assert said != store._why(500, "")


def test_playing_a_link_keeps_the_rows_where_they_are(window, qapp, monkeypatch):
    """The download bar opening over the tabs for a played link pushed the list down: the
    row just clicked slid ~130 px away. The list scrolls by as much, so it stays put."""
    from soundboard.ui.window.tabcontrol import TAB_INDEX
    sounds = [_sound(i, ext="link", link=f"https://www.myinstants.com/en/instant/s{i}/")
              for i in range(1, 40)]
    monkeypatch.setattr(store, "_request", FakeStore(sounds))
    w = window
    w.show()
    w.resize(1400, 900)
    w.tabs.setCurrentIndex(TAB_INDEX["store"])
    st = w.store
    st.reload()
    assert _wait(qapp, lambda: len(st._rows) > 20)
    process_events(qapp, lambda: False, 0.3)
    sb = st.list_area.verticalScrollBar()
    sb.setValue(sb.maximum() // 2)
    process_events(qapp, lambda: False, 0.2)
    rows = [r for r in st._rows if r.visibleRegion().boundingRect().height() > 30]
    row = rows[len(rows) // 2]
    y = row.mapTo(w, row.rect().topLeft()).y()
    row.btn_play.click()
    assert _wait(qapp, lambda: w.download_bar.isVisible())
    process_events(qapp, lambda: False, 0.5)
    assert abs(row.mapTo(w, row.rect().topLeft()).y() - y) <= 2


def test_names_and_tags_with_links_are_caught_before_sending():
    assert store.check_words("Air horn", "meme, horn") == ""
    assert store.check_words("Mr. Bean", "e.g. funny") == ""
    for name, tags in [("get it at example.com", ""), ("horn", "www.spam"),
                       ("join discord.gg/abc", ""), ("horn", "https://x.y")]:
        assert store.check_words(name, tags), (name, tags)
    with pytest.raises(store.StoreError):
        store.share_link("i", "https://www.youtube.com/watch?v=abc", "see example.com")
