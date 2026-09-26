"""Browser tab: the WebSocket audio sink on its own, then the whole tap path end to
end inside a headless QtWebEngine (AudioWorklet -> socket -> engine), including an
embedded player in an iframe and the pause broadcast."""
import json
import time

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QUrl
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import QWidget

from soundboard import browser
from soundboard.browser import AudioSink, BrowserTab
from conftest import process_events
from soundboard.engine import SR
from soundboard.library import Config


# ---------------------------------------------------------------- sink

class Client:
    def __init__(self, qapp, url):
        self.ws = QWebSocket()
        self.opened = False
        self.closed = False
        self.texts = []
        self.ws.connected.connect(lambda: setattr(self, "opened", True))
        self.ws.disconnected.connect(lambda: setattr(self, "closed", True))
        self.ws.textMessageReceived.connect(self.texts.append)
        self.ws.open(QUrl(url))
        process_events(qapp, lambda: self.opened or self.closed, 5)


def pcm(value=0.25, frames=1024):
    x = np.full((frames, 2), value * 32767, np.int16)
    return x.tobytes()


@pytest.fixture
def sink(qapp):
    s = AudioSink()
    assert s.port > 0
    got = {"audio": [], "status": []}
    s.audio.connect(got["audio"].append)
    s.status.connect(lambda a, b: got["status"].append((a, b)))
    yield s, got
    s.close()


def test_sink_accepts_only_the_secret_path(qapp, sink):
    s, got = sink
    bad = Client(qapp, f"ws://127.0.0.1:{s.port}/wrong")
    process_events(qapp, lambda: bad.closed, 3)
    assert bad.closed and not s._conns
    good = Client(qapp, s.url)
    assert good.opened and len(s._conns) == 1


def test_sink_turns_binary_frames_into_float_audio(qapp, sink):
    s, got = sink
    c = Client(qapp, s.url)
    c.ws.sendBinaryMessage(pcm(0.25))
    assert process_events(qapp, lambda: got["audio"], 3)
    x = got["audio"][0]
    assert x.shape == (1024, 2) and x.dtype == np.float32
    assert abs(float(x[0, 0]) - 0.25) < 1e-3
    c.ws.sendBinaryMessage(b"\x01\x02\x03")       # odd length: dropped, not crashed
    process_events(qapp, lambda: False, 0.3)
    assert len(got["audio"]) == 1


def test_sink_sums_status_across_frames_and_forgets_closed_ones(qapp, sink):
    s, got = sink
    a, b = Client(qapp, s.url), Client(qapp, s.url)
    a.ws.sendTextMessage(json.dumps({"on": 1, "off": 0}))
    b.ws.sendTextMessage(json.dumps({"on": 0, "off": 1}))
    assert process_events(qapp, lambda: (1, 1) in got["status"], 3)
    b.ws.sendTextMessage("not json")
    b.ws.close()
    assert process_events(qapp, lambda: got["status"][-1] == (1, 0), 3)


def test_first_playing_frame_owns_the_mic_until_it_goes_quiet(qapp, sink, monkeypatch):
    s, got = sink
    monkeypatch.setattr(browser, "HANDOVER_S", 0.3)
    a, b = Client(qapp, s.url), Client(qapp, s.url)
    a.ws.sendBinaryMessage(pcm(0.1))
    assert process_events(qapp, lambda: got["audio"], 3)
    b.ws.sendBinaryMessage(pcm(0.9))               # b talks while a owns the mic
    process_events(qapp, lambda: False, 0.2)
    assert len(got["audio"]) == 1
    time.sleep(0.35)                                # a has been quiet long enough
    b.ws.sendBinaryMessage(pcm(0.9))
    assert process_events(qapp, lambda: len(got["audio"]) == 2, 3)
    assert abs(float(got["audio"][1][0, 0]) - 0.9) < 1e-3


def test_broadcast_reaches_every_frame(qapp, sink):
    s, _ = sink
    a, b = Client(qapp, s.url), Client(qapp, s.url)
    s.broadcast("pause")
    assert process_events(qapp, lambda: a.texts == ["pause"] and b.texts == ["pause"], 3)


# ---------------------------------------------------------------- address bar

@pytest.mark.parametrize("text, expect", [
    ("youtube.com", "https://youtube.com"),
    ("https://a.b/c?d=1", "https://a.b/c?d=1"),
    ("localhost:8080/x", "http://localhost:8080/x"),
    ("http://x.y:81", "http://x.y:81"),
])
def test_address_bar_addresses(text, expect):
    assert BrowserTab.url_for(text).toString().rstrip("/") == expect.rstrip("/")


@pytest.mark.parametrize("text", ["lofi beats", "airhorn", "what is 2.5 + 2"])
def test_address_bar_searches(text):
    u = BrowserTab.url_for(text)
    assert u.host() == "www.youtube.com" and "search_query=" in u.query()


# ---------------------------------------------------------------- end to end

class FakeEngine:
    def __init__(self):
        self.chunks = []
        self.level_browser = 0.0
        self.browser_live = self.browser_monitor = True
        self.browser_vol = 1.0

    def feed_browser(self, x):
        self.chunks.append(x)


def tone_page(folder, name="page.html", iframe_of=None):
    t = np.arange(SR) / SR
    sf.write(folder / "tone.wav", np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.5, SR)
    if iframe_of:
        body = f'<iframe src="{iframe_of}" width=300 height=100></iframe>'
    else:
        body = '<audio id=a src="tone.wav" autoplay loop></audio>'
    p = folder / name
    p.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return p


@pytest.fixture
def tab(qapp, app_dir, monkeypatch):
    monkeypatch.setattr(browser, "APP_DIR", app_dir)   # the persistent web profile
    eng = FakeEngine()
    cfg = Config(browser_url="about:blank")
    host = QWidget()
    t = BrowserTab(eng, cfg, lambda: None, lambda: QWidget())
    t.setParent(host)
    host.resize(800, 600)
    host.show()                                        # offscreen: creates the web view
    assert process_events(qapp, lambda: t.view is not None, 5)
    yield t, eng
    t.shutdown()
    host.close()


def rms(chunks):
    x = np.concatenate(chunks)
    return float(np.sqrt((x ** 2).mean()))


def test_page_audio_reaches_the_engine_through_the_worklet(qapp, tab, app_dir):
    t, eng = tab
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir))).toString())
    assert process_events(qapp, lambda: len(eng.chunks) >= 40, 15), "no audio arrived"
    assert eng.chunks[0].shape == (browser.BLOCK, 2)
    assert 0.25 < rms(eng.chunks[-20:]) < 0.45          # a 0.5-amplitude sine (rms 0.354)
    assert t._status == (1, 0)                          # reported as tapped and playing
    assert len(t.recorder.last()) >= 40 * browser.BLOCK  # the replay buffer saw it too


def test_embedded_player_in_an_iframe_is_captured(qapp, tab, app_dir):
    t, eng = tab
    inner = tone_page(app_dir, "inner.html")
    outer = tone_page(app_dir, "outer.html", iframe_of=inner.name)
    t.load(QUrl.fromLocalFile(str(outer)).toString())
    assert process_events(qapp, lambda: len(eng.chunks) >= 20, 15), "iframe audio not captured"
    assert 0.25 < rms(eng.chunks[-10:]) < 0.45
    assert t._status == (1, 0)


def test_stop_all_pauses_media_in_every_frame(qapp, tab, app_dir):
    t, eng = tab
    inner = tone_page(app_dir, "inner.html")
    outer = tone_page(app_dir, "outer.html", iframe_of=inner.name)
    t.load(QUrl.fromLocalFile(str(outer)).toString())
    assert process_events(qapp, lambda: t._status == (1, 0), 15)
    t.pause_media()
    assert process_events(qapp, lambda: t._status == (0, 0), 5), "iframe media kept playing"
    n = len(eng.chunks)
    process_events(qapp, lambda: False, 0.5)
    assert len(eng.chunks) - n <= 2                     # nothing streams while paused
