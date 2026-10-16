"""The chat client (soundboard/chat.py), against a fake server: no test goes online."""
import io
import json
import urllib.error

import pytest

from soundboard import chat, net
from soundboard.library import Config


def _m(i, **kw):
    d = {"id": i, "t": 1000 + i, "u": "ab12cd34", "name": "SoggyGoblin42", "text": f"hi {i}"}
    d.update(kw)
    return d


class Fake:
    def __init__(self):
        self.calls = []
        self.answer = {}

    def __call__(self, method, path, install, body=None, timeout=15):
        self.calls.append((method, path, install, body))
        return json.dumps(self.answer).encode()


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(chat, "_request", f)
    return f


def test_install_id_is_made_once_and_shared_with_the_store():
    cfg = Config()
    first = chat.install_id(cfg)
    assert len(first) == 36 and chat.install_id(cfg) == first and cfg.store_id == first


def test_parse_drops_odd_entries():
    raw = {"messages": [_m(1), {"id": "x"}, _m(0), _m(2, text=""), _m(3, name=" "),
                        _m(4, text="x" * 500), "junk"], "last": 9, "off": 1}
    msgs, last, off = chat.parse(raw)
    assert [m.id for m in msgs] == [1, 4] and last == 9 and off
    assert len(msgs[1].text) == chat.MAX_LEN
    assert chat.parse("nope") == ([], 0, False)


def test_poll_asks_for_what_is_new(fake):
    fake.answer = {"messages": [_m(5)], "last": 5}
    msgs, last, off = chat.poll("inst", 4)
    assert fake.calls[0][:3] == ("GET", "/v1/chat?after=4&wait=1", "inst")
    assert [m.text for m in msgs] == ["hi 5"] and last == 5 and not off
    chat.poll("inst", -3, wait=False)
    assert fake.calls[1][1] == "/v1/chat?after=0"


def test_say_tidies_and_checks_before_sending(fake):
    fake.answer = {"message": _m(7, text="a b")}
    assert chat.say("inst", "  a \n b ").id == 7
    assert json.loads(fake.calls[0][3]) == {"text": "a b"}
    for bad in ("   ", "x" * (chat.MAX_LEN + 1)):
        with pytest.raises(chat.ChatError):
            chat.say("inst", bad)
    assert len(fake.calls) == 1
    fake.answer = {}
    with pytest.raises(chat.ChatError):
        chat.say("inst", "hello")


def test_report_names_the_message(fake):
    chat.report("inst", 12)
    assert fake.calls[0][:3] == ("POST", "/v1/chat/12/report", "inst")


def test_server_errors_become_plain_words(monkeypatch):
    def boom(code, err):
        def urlopen(req, timeout=0, feature=None):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(
                json.dumps({"error": err}).encode()))
        return urlopen
    for code, err, word in ((429, "slow down", "Slow down"), (403, "muted", "muted"),
                            (400, "no links", "links"), (503, "off", "off")):
        monkeypatch.setattr(net, "urlopen", boom(code, err))
        with pytest.raises(chat.ChatError, match=word):
            chat.say("inst", "hello")

    def down(req, timeout=0, feature=None):
        raise OSError("no route")
    monkeypatch.setattr(net, "urlopen", down)
    with pytest.raises(chat.ChatError, match="reach chat"):
        chat.poll("inst", 0)


def test_switched_off_feature_is_refused_not_sent(monkeypatch):
    assert net.known("chat")
    monkeypatch.setattr(net, "_offline", True)
    with pytest.raises(net.ProxyError):
        chat.poll("inst", 0, wait=False)
