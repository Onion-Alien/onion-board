"""Browser tab: the WebSocket audio sink on its own, then the whole tap path end to
end inside a headless QtWebEngine (AudioWorklet -> socket -> engine), including an
embedded player in an iframe and the pause broadcast."""
import json
import time

import numpy as np
import pytest
import shiboken6
import soundfile as sf
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import QWidget

from soundboard import adblocker, browser
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


def test_broadcast_skips_a_socket_qt_already_destroyed(qapp, sink):
    s, got = sink
    a, b = Client(qapp, s.url), Client(qapp, s.url)
    a.ws.sendTextMessage(json.dumps({"on": 1, "off": 0}))
    b.ws.sendTextMessage(json.dumps({"on": 1, "off": 0}))
    assert process_events(qapp, lambda: got["status"] and got["status"][-1] == (2, 0), 3)
    dead = next(iter(s._conns))
    dead.blockSignals(True)   # its `disconnected` never reaches the sink, as when the
    dead.deleteLater()        # frame is torn down before the handler runs
    QCoreApplication.sendPostedEvents(dead, QEvent.DeferredDelete)
    assert not shiboken6.isValid(dead)
    s.broadcast("pause")      # used to raise "Internal C++ object ... already deleted"
    assert len(s._conns) == 1 and got["status"][-1] == (1, 0)
    s.set_rate(1.5, True)     # the same path for speed changes
    assert len(s._conns) == 1


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


@pytest.mark.parametrize("url, ok", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://youtu.be/abc", True),
    ("https://m.soundcloud.com/x", True),
    ("https://www.tiktok.com/@x/video/1", True),
    ("https://vm.tiktok.com/abc/", True),
    ("https://www.myinstants.com/en/index/us/", True),
    ("https://accounts.google.com/signin", True),
    ("about:blank", True),
    ("file:///C:/x/page.html", True),
    ("https://evil.example/", False),
    ("https://youtube.com.evil.example/", False),
    ("https://notyoutube.com/", False),
    ("https://www.google.com/search?q=x", False),
    ("http://localhost:8080/", False),
    ("javascript:alert(1)", False),
    ("ftp://soundcloud.com/", False),
])
def test_only_allowed_sites_open(url, ok):
    assert browser.site_allowed(QUrl(url)) is ok


# ---------------------------------------------------------------- end to end

class FakeEngine:
    def __init__(self):
        self.chunks = []
        self.level_browser = 0.0
        self.browser_live = self.browser_monitor = True
        self.browser_vol = 1.0

    def feed_browser(self, x):
        self.chunks.append(x)


def tone_page(folder, name="page.html", iframe_of=None, tag="audio"):
    """A page playing a looping 440 Hz tone: in an <audio> or <video>, from an iframe,
    or (tag="detached") from a `new Audio()` that's never put in the page."""
    t = np.arange(SR) / SR
    sf.write(folder / "tone.wav", np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.5, SR)
    if iframe_of:
        body = f'<iframe src="{iframe_of}" width=300 height=100></iframe>'
    elif tag == "detached":
        body = "<script>const s = new Audio('tone.wav'); s.loop = true; s.play();</script>"
    else:
        body = f'<{tag} id=a src="tone.wav" autoplay loop></{tag}>'
    p = folder / name
    p.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return p


class FakeMeter(QWidget):
    def set_level(self, _level):
        pass


@pytest.fixture
def tab(qapp, app_dir, monkeypatch):
    monkeypatch.setattr(browser, "APP_DIR", app_dir)   # the persistent web profile
    monkeypatch.setattr(adblocker, "FILTER_LISTS", ())    # no list downloads in tests
    eng = FakeEngine()
    cfg = Config(browser_url="about:blank")
    host = QWidget()
    t = BrowserTab(eng, cfg, lambda: None, FakeMeter)
    t.setParent(host)
    host.resize(800, 600)
    host.show()                                        # offscreen: creates the web view
    assert process_events(qapp, lambda: t.view is not None, 5)
    loaded = []
    t.view.page().loadFinished.connect(loaded.append)
    assert process_events(qapp, lambda: loaded, 10)     # the first about:blank is done
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


def test_lite_watchdog_wakes_a_stalled_player(qapp, tab, monkeypatch):
    t, _ = tab
    now = [1000.0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: now[0])
    kicks = []
    monkeypatch.setattr(t, "_mini_js", kicks.append)
    t._status = (1, 0)                       # a player is tapped
    t._set_collapsed(True)
    assert not t.view.isVisible()
    for _ in range(5):                       # playing normally: the position moves
        now[0] += 1
        t._watch_stall(now[0] - 990, False)
    assert not t._unsticking
    t._watch_stall(10.0, True)               # paused for a long time: not a stall
    now[0] += 30
    t._watch_stall(10.0, True)
    assert not t._unsticking
    t._watch_stall(10.0, False)              # "playing" but stuck at 10s
    now[0] += browser.STALL_S + 0.5
    t._watch_stall(10.0, False)
    assert t._unsticking
    assert t.view.isVisible() and t.view.maximumHeight() == 2   # woken, 2 px tall
    assert process_events(qapp, lambda: browser.MINI_KICK_JS in kicks, 3)
    t._end_unstick()
    assert not t.view.isVisible() and t.view.maximumHeight() > 1000
    t._set_collapsed(False)
    assert t.view.isVisible()

    t._set_collapsed(True)                   # a player that hasn't loaded (no duration)
    now[0] += 1                              # is never "stalled"
    t._watch_stall(0.0, True)
    now[0] += 30
    t._watch_stall(0.0, True)
    assert not t._unsticking


def test_navigating_away_in_lite_shows_the_new_page(qapp, tab, app_dir):
    """Lite hid the page while something played; clicking another site (a quick link)
    must bring the page back instead of leaving an unresponsive, blank tab."""
    t, _ = tab
    t.cfg.browser_lite = True
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, tag="video"))).toString())
    assert process_events(qapp, lambda: t._collapsed, 15), "Lite didn't collapse"
    assert not t.view.isVisible()
    t._unsticking = True                     # even mid-wake-up
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, "other.html"))).toString())
    assert process_events(qapp, lambda: not t._collapsed, 5)
    assert t.view.isVisible() and t.view.maximumHeight() > 1000
    assert not t._unsticking
    t._end_unstick()                         # a wake-up that was pending doesn't re-hide it
    assert t.view.isVisible()


def test_links_off_the_allowed_sites_are_refused(qapp, tab):
    t, _ = tab
    refused = []
    t.view.page().refused.connect(refused.append)
    t.load("https://evil.example/")
    assert process_events(qapp, lambda: refused, 5)
    assert refused[0].host() == "evil.example"
    assert t.view.url().toString() == "about:blank"
    assert "evil.example" in t.info.text()


def test_audio_played_off_the_page_is_captured(qapp, tab, app_dir):
    """Sound-button sites play through a `new Audio()` that's never in the page."""
    t, eng = tab
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, tag="detached"))).toString())
    assert process_events(qapp, lambda: len(eng.chunks) >= 20, 15), "no audio arrived"
    assert 0.25 < rms(eng.chunks[-10:]) < 0.45
    assert t._status == (1, 0)


def test_lite_leaves_sound_button_pages_alone(qapp, tab, app_dir):
    """Lite hides the page for video only: a page of sound buttons has to stay usable."""
    t, _ = tab
    t.cfg.browser_lite = True
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, tag="detached"))).toString())
    assert process_events(qapp, lambda: t._status == (1, 0), 15)
    process_events(qapp, lambda: False, 0.5)
    assert not t._collapsed and t.view.isVisible()


def test_pausing_in_lite_keeps_the_mini_player(qapp, tab, app_dir):
    """Pause (the mini-player's button, Stop all, the hotkey) must not bring the page
    back: it did, and pressing play again then flashed it up before hiding it."""
    t, _ = tab
    t.cfg.browser_lite = True
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, tag="video"))).toString())
    assert process_events(qapp, lambda: t._collapsed, 15), "Lite didn't collapse"
    t.pause_media()
    assert process_events(qapp, lambda: t._status == (0, 0), 5)
    process_events(qapp, lambda: False, 1.0)            # a few mini-player polls
    assert t._collapsed and not t.view.isVisible()
    t.toggle_play()                                      # and play resumes from there
    assert process_events(qapp, lambda: t._status == (1, 0), 5)
    assert t._collapsed and not t.view.isVisible()


def test_lite_shows_the_page_when_the_player_goes_away(qapp, tab, app_dir):
    t, _ = tab
    t.cfg.browser_lite = True
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, tag="video"))).toString())
    assert process_events(qapp, lambda: t._collapsed, 15)
    t.view.page().runJavaScript("document.getElementById('a').remove()")
    assert process_events(qapp, lambda: not t._collapsed, 5), "left a blank tab"
    assert t.view.isVisible()


def test_lite_opens_a_video_straight_into_the_mini_player(qapp, tab, app_dir, monkeypatch):
    """A YouTube video opened in Lite never shows the page first: it's 2 px tall (still
    'visible', so it autoplays) until it plays, then hidden."""
    t, _ = tab
    monkeypatch.setattr(t, "_update_thumb", lambda: None)   # no thumbnail download
    t.cfg.browser_lite = True
    heights = []
    t.view.page().loadStarted.connect(
        lambda: heights.append((t._collapsed, t.view.maximumHeight())))
    t._expect(QUrl("https://www.youtube.com/watch?v=abc123"))
    page = tone_page(app_dir, tag="video")          # stands in for the video
    t.view.setUrl(QUrl.fromLocalFile(str(page)))
    assert process_events(qapp, lambda: heights, 10)
    assert heights[0] == (True, 2) and t.mini_title.text() == "Loading…"
    assert process_events(qapp, lambda: t._status == (1, 0), 15)
    assert t._collapsed and not t._peeking and not t.view.isVisible()


def test_lite_shows_the_page_if_the_video_never_starts(qapp, tab, app_dir, monkeypatch):
    t, _ = tab
    monkeypatch.setattr(t, "_update_thumb", lambda: None)
    monkeypatch.setattr(browser, "PEEK_WAIT_S", 0.3)
    t.cfg.browser_lite = True
    silent = app_dir / "silent.html"
    silent.write_text("<html><body>consent page</body></html>", encoding="utf-8")
    t._expect(QUrl("https://youtu.be/abc123"))
    t.view.setUrl(QUrl.fromLocalFile(str(silent)))
    assert process_events(qapp, lambda: t._peeking, 10)
    assert process_events(qapp, lambda: not t._collapsed, 5)
    assert t.view.isVisible() and t.view.maximumHeight() > 1000


def test_opening_other_pages_in_lite_shows_them(qapp, tab, app_dir):
    t, _ = tab
    t.cfg.browser_lite = True
    t._expect(QUrl("https://www.youtube.com/"))          # not a video: no mini-player
    assert t._expect_until == 0.0
    t.cfg.browser_lite = False
    t._expect(QUrl("https://www.youtube.com/watch?v=abc123"))   # Lite off
    assert t._expect_until == 0.0


def test_mini_player_helpers():
    assert browser.youtube_id(QUrl("https://www.youtube.com/watch?v=abc123&t=4")) == "abc123"
    assert browser.youtube_id(QUrl("https://youtu.be/xyz")) == "xyz"
    assert browser.youtube_id(QUrl("https://www.youtube.com/shorts/sh0rt")) == "sh0rt"
    assert browser.youtube_id(QUrl("https://soundcloud.com/a/b")) == ""
    assert browser.fmt_time(75) == "1:15" and browser.fmt_time(3725) == "1:02:05"


# ---------------------------------------------------------------- live speed / pitch

def test_rate_message_format_and_clamp():
    assert browser.rate_message(1.5, True) == "rate 1.5 1"
    assert browser.rate_message(0.1, False) == "rate 0.25 0"
    assert browser.rate_message(9, True) == "rate 4 1"


def test_sink_rate_is_broadcast_and_sent_to_frames_that_connect_later(qapp, sink):
    s, _ = sink
    a = Client(qapp, s.url)
    s.set_rate(1.0, True)                    # already normal: nothing to say
    process_events(qapp, lambda: False, 0.2)
    assert a.texts == []
    s.set_rate(1.5, False)
    assert process_events(qapp, lambda: a.texts == ["rate 1.5 0"], 3)
    late = Client(qapp, s.url)               # a frame / page that opens afterwards
    assert process_events(qapp, lambda: late.texts == ["rate 1.5 0"], 3)
    s.set_rate(1.0, True)                    # back to normal: told once, then not sticky
    assert process_events(qapp, lambda: a.texts[-1] == "rate 1 1" == late.texts[-1], 3)
    later = Client(qapp, s.url)
    process_events(qapp, lambda: False, 0.3)
    assert later.texts == []


def media_state(qapp, t):
    got = []
    t.view.page().runJavaScript(
        "(()=>{const m=document.querySelector('audio');"
        "return m?JSON.stringify([m.playbackRate,m.preservesPitch]):''})()",
        browser.WORLD, got.append)
    assert process_events(qapp, lambda: got, 3)
    return json.loads(got[0]) if got[0] else None


def test_speed_button_sets_page_rate_and_engine_pitch(qapp, tab, app_dir):
    t, eng = tab
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir))).toString())
    assert process_events(qapp, lambda: t._status == (1, 0), 15)
    t.btn_speed.set_values(1.5, -3, False)   # as if moved in the popup
    assert eng.browser_pitch == -3
    assert process_events(qapp, lambda: media_state(qapp, t) == [1.5, False], 5)
    # a page loaded afterwards picks the speed up as soon as it plays
    loaded = []
    t.view.page().loadFinished.connect(loaded.append)
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir, "next.html"))).toString())
    assert process_events(qapp, lambda: loaded, 10)
    assert process_events(qapp, lambda: media_state(qapp, t) == [1.5, False], 15)
    t.btn_speed.reset()
    assert eng.browser_pitch == 0
    assert process_events(qapp, lambda: media_state(qapp, t)[0] == 1.0, 5)


def test_recorder_keeps_what_the_engine_returns(qapp, tab):
    t, eng = tab
    x = np.full((1024, 2), 0.1, np.float32)
    t._on_audio(x)                           # an engine that returns nothing: the raw chunk
    assert np.allclose(t.recorder.last()[-1024:], x)
    eng.feed_browser = lambda c: c * 2       # one that returns the pitched chunk
    t._on_audio(x)
    assert np.allclose(t.recorder.last()[-1024:], x * 2)


def test_live_starts_off_even_if_it_was_left_on(qapp, app_dir, monkeypatch):
    monkeypatch.setattr(browser, "APP_DIR", app_dir)
    eng = FakeEngine()
    cfg = Config(browser_url="about:blank", browser_live=True)   # quit while live
    t = BrowserTab(eng, cfg, lambda: None, FakeMeter)
    assert not t.btn_live.isChecked() and not eng.browser_live and not cfg.browser_live
    t.btn_live.click()
    assert eng.browser_live and cfg.browser_live
    assert Config().browser_live is False


def test_page_audio_keeps_flowing_while_the_ui_thread_is_busy(qapp, tab, app_dir):
    """Resizing the window keeps the UI thread busy re-laying out the page; the audio
    must not wait for it (it used to, and the browser rings ran dry: a stutter)."""
    t, eng = tab
    t.load(QUrl.fromLocalFile(str(tone_page(app_dir))).toString())
    assert process_events(qapp, lambda: len(eng.chunks) >= 20, 15), "no audio arrived"
    n = len(eng.chunks)
    time.sleep(0.6)                                     # the UI thread handles nothing
    got = len(eng.chunks) - n
    assert got * browser.BLOCK >= 0.3 * browser.SR, f"only {got} chunks while the UI was busy"
