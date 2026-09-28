"""Radio tab: station parsing, the directory client, the stream player and the tab.

A local HTTP server on 127.0.0.1 stands in for Radio Browser and for a radio
station (a synthesized tone served as a WAV stream), so nothing here touches the
internet and nothing plays out loud (the player only hands audio to the engine).
"""
import http.server
import io
import json
import threading
import time

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QWidget

from conftest import process_events
from soundboard import radio
from soundboard.engine import SR, Engine
from soundboard.library import Config
from soundboard.radio import RadioDirectory, RadioPlayer, Station


def api_station(i, **kw):
    d = {"stationuuid": f"uuid-{i}", "name": f"Station {i}",
         "url": f"http://example.com/{i}", "url_resolved": f"http://example.com/{i}.mp3",
         "country": "Japan", "countrycode": "JP", "tags": "jazz,lofi", "codec": "MP3",
         "bitrate": 128, "geo_lat": 35.0 + i / 100, "geo_long": 139.0, "clickcount": 100 - i,
         "votes": 5, "homepage": "https://example.com/"}
    d.update(kw)
    return d


# ---------------------------------------------------------------- parsing

def test_station_from_api_keeps_the_useful_fields():
    s = Station.from_api(api_station(1))
    assert s.uuid == "uuid-1" and s.url == "http://example.com/1.mp3"   # resolved url wins
    assert s.cc == "JP" and s.tags == ["jazz", "lofi"] and s.bitrate == 128
    assert s.lat == pytest.approx(35.01) and s.lon == 139.0
    assert "Japan" in s.subtitle() and "128 kbps MP3" in s.subtitle()


@pytest.mark.parametrize("bad", [
    {"url": "javascript:alert(1)", "url_resolved": ""},
    {"url": "file:///C:/Windows/win.ini", "url_resolved": "ftp://x/"},
    {"name": "   "},
    {"stationuuid": ""},
    # this PC / the home network written the ways Qt and FFmpeg still read as an address
    {"url": "http://127.1:8000/x", "url_resolved": ""},
    {"url": "http://2130706433/", "url_resolved": ""},
    {"url": "http://0x7f000001/", "url_resolved": ""},
    {"url": "http://017700000001/", "url_resolved": ""},
    {"url": "http://192.168.1/", "url_resolved": ""},
    {"url": "http://[::ffff:127.0.0.1]/", "url_resolved": ""},
])
def test_unplayable_or_nameless_stations_are_dropped(bad):
    assert Station.from_api(api_station(1, **bad)) is None


def test_station_stats_for_the_hover_card():
    s = Station.from_api(api_station(1, state="Tokyo", language="japanese", clicktrend=-4,
                                     hls=1, lastcheckoktime_iso8601="2026-09-26T08:00:00Z",
                                     lastchangetime_iso8601="<script>"))
    assert (s.state, s.language, s.trend, s.hls) == ("Tokyo", "japanese", -4, True)
    assert s.checked == "2026-09-26T08:00:00Z" and s.changed == ""   # not a date: dropped
    p = radio.globe_points([s])[0]
    assert p["s"] == "Tokyo" and p["tr"] == -4 and p["t"] == ["jazz", "lofi"] and p["h"]


def test_globe_page_escapes_the_card_and_zooms_itself():
    page = radio.globe_html("", "#000000", "#111111", "#222222", "#333333")
    assert "esc(d.n)" in page and "esc(t)" in page and "esc(d.l" in page
    assert "passive: false" in page and "c.enableZoom = false" in page


def test_bad_coordinates_and_numbers_are_cleaned():
    s = Station.from_api(api_station(1, geo_lat=0, geo_long=0, bitrate="x", countrycode="J1"))
    assert s.lat is None and s.lon is None and s.bitrate == 0 and s.cc == ""
    s = Station.from_api(api_station(1, geo_lat=95, geo_long=10))
    assert s.lat is None
    s = Station.from_api(api_station(1, name="  <b>Hot</b>\n FM  "))
    assert s.name == "<b>Hot</b> FM"            # kept as text; escaped wherever it's shown


def test_parse_stations_dedupes_and_survives_junk():
    raw = json.dumps([api_station(1), api_station(1), "junk", api_station(2, url="x",
                                                                         url_resolved="")])
    assert [s.uuid for s in radio.parse_stations(raw)] == ["uuid-1"]
    assert radio.parse_stations(b"not json") == []
    assert radio.parse_stations(b'{"a": 1}') == []


def test_saved_stations_round_trip():
    s = Station.from_api(api_station(3))
    assert Station.from_saved(s.to_saved()) == s
    assert Station.from_saved({"uuid": "x", "name": "y", "url": "javascript:1"}) is None
    assert Station.from_saved({"nonsense": 1}) is None


def test_search_matching_covers_name_country_and_tags():
    s = Station.from_api(api_station(1))
    assert s.matches(["japan"]) and s.matches(["jazz", "station"]) and not s.matches(["rock"])


def test_globe_page_is_pinned_and_colours_cant_inject():
    page = radio.globe_html("/*channel*/", "#000000;</style><script>x()</script>", "#123456",
                            "red", "#eeeeee")
    assert radio.GLOBE_SRI in page and 'integrity="sha384-' in page
    assert "Content-Security-Policy" in page and "default-src &#x27;none&#x27;" in page
    assert "x()" not in page and "#15171f" in page and "#123456" in page


# ---------------------------------------------------------------- engine

class FakeStream:
    def close(self):
        pass


def test_engine_radio_goes_to_headphones_and_to_others_only_when_live():
    e = Engine()
    e.main_stream = e.mon_stream = FakeStream()
    x = np.full((SR // 5, 2), 0.25, np.float32)
    out = np.zeros((480, 2), np.float32)
    e.radio_live = False
    e.feed_radio(x)
    e._main(out, 480)
    assert np.abs(out).max() == 0                 # not live: others hear nothing
    e._mon(out, 480)
    assert np.abs(out).max() > 0.05               # ...but you do
    assert not e.radio_on_air()
    e.radio_live = True
    e.feed_radio(x)
    e._main(out, 480)
    assert np.abs(out).max() > 0.1
    assert e.radio_on_air() and e.level_radio > 0.2
    e.radio_vol = 0.0
    assert not e.radio_on_air()


# ---------------------------------------------------------------- a local "internet"

def wav_bytes(seconds=6.0, freq=440.0):
    t = np.arange(int(SR * seconds)) / SR
    x = (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.stack([x, x], 1), SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class Server:
    """Radio Browser's endpoints plus one station stream, on 127.0.0.1."""

    def __init__(self):
        self.hits: list[str] = []
        self.stations = [api_station(i) for i in range(5)]
        self.stations.append(api_station(9, name="Rock Radio", tags="rock",
                                         country="Brazil", geo_lat=None, geo_long=None))
        self.audio = wav_bytes()
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                srv.hits.append(self.path)
                if self.path.startswith("/stream.wav"):
                    body, kind = srv.audio, "audio/wav"
                elif self.path.startswith("/json/stations/search"):
                    q = self.path
                    if "has_geo_info" in q:
                        found = [s for s in srv.stations if s["geo_lat"] is not None]
                    elif "name=rock" in q.lower() or "tag=rock" in q.lower():
                        found = [s for s in srv.stations if "rock" in s["tags"]]
                    else:
                        found = []
                    body, kind = json.dumps(found).encode(), "application/json"
                elif self.path.startswith("/json/url/"):
                    body, kind = b"{}", "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = Server()
    yield s
    s.close()


def dead_base():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def test_directory_loads_the_globe_caches_it_and_fails_over(qapp, server, tmp_path):
    d = RadioDirectory(tmp_path, bases=(dead_base(), server.base))   # first mirror is down
    got = []
    d.globe_ready.connect(got.append)
    d.load_globe()
    assert process_events(qapp, lambda: got)
    assert [s.uuid for s in got[0]] == [f"uuid-{i}" for i in range(5)]   # located ones only
    assert (tmp_path / "stations.json").exists()
    n = len(server.hits)
    d2 = RadioDirectory(tmp_path, bases=(server.base,))
    got2 = []
    d2.globe_ready.connect(got2.append)
    d2.load_globe()
    assert process_events(qapp, lambda: got2)
    assert len(got2[0]) == 5 and len(server.hits) == n   # served from the cache


def test_directory_falls_back_to_a_stale_cache_then_reports(qapp, tmp_path):
    d = RadioDirectory(tmp_path, bases=(dead_base(),))
    fails = []
    d.failed.connect(lambda kind, msg: fails.append(kind))
    d.load_globe()
    assert process_events(qapp, lambda: fails) and fails == ["globe"]
    d._write_cache([Station.from_api(api_station(1))])
    got = []
    d.globe_ready.connect(got.append)
    d.load_globe(force=True)
    assert process_events(qapp, lambda: got) and got[0][0].uuid == "uuid-1"


def test_search_merges_name_and_tag_and_drops_stale_answers(qapp, server, tmp_path):
    d = RadioDirectory(tmp_path, bases=(server.base,))
    res = []
    d.results.connect(lambda q, st: res.append((q, [s.uuid for s in st])))
    d.search("jazz")
    d.search("rock")            # supersedes "jazz" before it answers
    assert process_events(qapp, lambda: res)
    process_events(qapp, lambda: False, timeout=0.3)
    assert res == [("rock", ["uuid-9"])]
    assert any("name=rock" in h for h in server.hits) and any("tag=rock" in h
                                                               for h in server.hits)


# ---------------------------------------------------------------- player

def dominant_hz(x):
    mono = x[:, 0] - x[:, 0].mean()
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    return np.fft.rfftfreq(len(mono), 1 / SR)[int(np.argmax(spec))]


def test_player_decodes_a_stream_into_48k_stereo(qapp, server):
    p = RadioPlayer()
    chunks, states = [], []
    p.audio.connect(chunks.append)
    p.state.connect(states.append)
    st = Station(uuid="u", name="Tone FM", url=server.base + "/stream.wav")
    p.play(st)
    assert process_events(qapp, lambda: sum(map(len, chunks)) > SR, timeout=15)
    x = np.concatenate(chunks)
    assert x.dtype == np.float32 and x.shape[1] == 2
    assert abs(dominant_hz(x[-SR // 2:]) - 440) < 5
    assert states[:2] == ["connecting", "playing"]
    p.stop()
    assert states[-1] == "stopped" and p.station is None


def test_player_reports_a_dead_station(qapp, monkeypatch):
    monkeypatch.setattr(radio, "CONNECT_S", 1.5)   # FFmpeg alone can wait for minutes
    p = RadioPlayer()
    errors = []
    p.error.connect(errors.append)
    p.play(Station(uuid="u", name="Gone", url=dead_base() + "/nothing"))
    assert process_events(qapp, lambda: errors, timeout=15)
    assert p.station is None and p.status == "error"


def later(monkeypatch) -> list:
    """Collect the player's QTimer.singleShot calls instead of running them."""
    scheduled = []

    class Timer:
        @staticmethod
        def singleShot(_ms, fn):
            scheduled.append(fn)
    monkeypatch.setattr(radio, "QTimer", Timer)   # not QTimer itself: Qt's class stays intact
    return scheduled


def test_player_reopens_a_dropped_stream_retries_times_and_never_twice_at_once(
        qapp, monkeypatch):
    p = RadioPlayer()
    scheduled = later(monkeypatch)
    opens, errors = [], []
    p.error.connect(errors.append)
    p._open = lambda: (opens.append(1), setattr(p, "_got_audio", False))
    p.station, p._got_audio, p._last_audio = Station(uuid="u", name="S", url="http://x"), True, 0
    p._retry("the station stopped sending")      # a stream that played drops
    p._check()                                   # the watchdog, the error and the status
    p._on_error(None, "network")                 # all notice it: still one reopen
    p._on_status(radio.QMediaPlayer.EndOfMedia)
    assert len(scheduled) == 1
    for _ in range(radio.RETRIES - 1):           # each reopen that doesn't get audio back
        scheduled.pop()()
        p._retry("the station didn't answer")    # ... is tried again, up to RETRIES
        assert len(scheduled) == 1 and not errors
    scheduled.pop()()
    p._retry("the station didn't answer")
    assert len(opens) == radio.RETRIES and not scheduled
    assert errors and p.station is None and p.status == "error"


def test_a_reopen_scheduled_before_stop_does_nothing(qapp, monkeypatch):
    p = RadioPlayer()
    scheduled = later(monkeypatch)
    opens = []
    p._open = lambda: opens.append(1)
    st = Station(uuid="u", name="S", url="http://x")
    p.station, p._got_audio = st, True
    p._retry("dropped")
    p.stop()
    p.station = st                               # the same station picked again
    scheduled.pop()()
    assert opens == []


# ---------------------------------------------------------------- the tab

class FakeEngine:
    def __init__(self):
        self.chunks = []
        self.level_radio = 0.0
        self.radio_live = False
        self.radio_monitor = True
        self.radio_vol = 1.0

    def feed_radio(self, x):
        self.chunks.append(x)


class FakeMeter(QWidget):
    def set_level(self, _level):
        pass


@pytest.fixture
def tab(qapp, app_dir, server):
    from soundboard.ui.radiopanel import RadioTab
    cfg = Config()
    cfg.radio = {"vol": 0.5}
    eng = FakeEngine()
    d = RadioDirectory(app_dir / "radio", bases=(server.base,))
    t = RadioTab(eng, cfg, lambda: None, FakeMeter, directory=d, globe=False)
    t.start()
    assert process_events(qapp, lambda: t._globe_list)
    yield t
    t.shutdown()


def test_tab_lists_popular_stations_and_starts_off_air(tab):
    assert tab.list.count() == 5
    assert tab.engine.radio_live is False and not tab.btn_live.isChecked()
    assert tab.engine.radio_vol == pytest.approx(0.5)


def test_tab_search_shows_local_matches_then_the_directory(qapp, tab, server):
    tab.search.setText("japan")                     # known locally (country)
    assert tab.list.count() == 5
    tab.search.setText("rock")
    tab._search_now()
    assert process_events(qapp, lambda: tab._results is not None)
    assert [s.name for s in tab.visible_stations()] == ["Rock Radio"]
    tab.search.setText("")
    assert tab.list.count() == 5


def test_tab_plays_into_the_engine_and_clips_to_sounds(qapp, tab, server):
    s = tab._stations["uuid-0"]
    s.url = server.base + "/stream.wav"
    clips = []
    tab.clip_ready.connect(lambda data, name: clips.append((data, name)))
    tab.play(s)
    assert process_events(qapp, lambda: sum(map(len, tab.engine.chunks)) > SR, timeout=15)
    assert tab.btn_play.text() == "Stop" and "Station 0" in tab.info.text()
    assert any(h.startswith("/json/url/uuid-0") for h in server.hits)   # counted a click
    assert tab.cfg.radio["last"]["uuid"] == "uuid-0"
    assert tab.clip_last() and clips[0][1].startswith("Station 0")
    tab.btn_live.click()
    assert tab.engine.radio_live
    tab.stop()
    assert tab.player.station is None and tab.btn_play.text() == "Play"


def test_tab_reports_a_playing_station_for_the_live_dot(tab, server):
    s = tab._stations["uuid-0"]
    s.url = server.base + "/stream.wav"
    seen = []
    tab.active_changed.connect(seen.append)
    assert not tab.is_active()
    tab.play(s)
    assert seen == [True] and tab.is_active() and "only you" in tab.live_tip()
    tab.btn_live.click()                          # said again: the tip changes
    assert seen == [True, True] and "others hear" in tab.live_tip()
    tab.stop()
    assert seen == [True, True, False] and not tab.is_active()
    tab.stop()                                    # already stopped: nothing new
    assert seen == [True, True, False]
    tab.play(s)
    tab.player._retry("the station didn't answer")   # the player gives the station up
    assert seen[-2:] == [True, False] and not tab.is_active()


def test_tab_favorites_are_saved(tab):
    tab.list.setCurrentRow(1)
    tab._toggle_fav()
    assert [f["uuid"] for f in tab.cfg.radio["favorites"]] == ["uuid-1"]
    tab.btn_favs.click()
    assert tab.list.count() == 1 and "★" in tab.list.item(0).text()
    tab.list.setCurrentRow(0)
    tab._toggle_fav()
    assert tab.cfg.radio["favorites"] == []


def test_globe_click_reaches_the_tab_without_the_internet(qapp, app_dir, server, monkeypatch):
    """The globe page loads (its CDN script blocked here, so it shows the fallback
    message), and a click reported over the web channel plays that station."""
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

    from soundboard.ui.radiopanel import RadioTab

    class Offline(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            if info.requestUrl().scheme() in ("http", "https"):
                info.block(True)

    eng = FakeEngine()
    d = RadioDirectory(app_dir / "radio", bases=(server.base,))
    t = RadioTab(eng, Config(), lambda: None, FakeMeter, directory=d, globe=True)
    played = []
    monkeypatch.setattr(t, "play", played.append)
    t._make_globe_orig = t._make_globe
    blocker = Offline()

    def make():
        t._make_globe_orig()
        t.profile.setUrlRequestInterceptor(blocker)
    t._make_globe = make
    t.start()
    assert process_events(qapp, lambda: t._globe_loaded and t._globe_list, timeout=20)
    page = t.view.page()
    out = []
    page.runJavaScript("document.getElementById('msg').textContent", 0, out.append)
    assert process_events(qapp, lambda: out) and "couldn't load" in out[0]
    page.runJavaScript("bridge && bridge.play('uuid-2')")
    assert process_events(qapp, lambda: played, timeout=5)
    assert played[0].uuid == "uuid-2"
    # a link in the page can't take it anywhere
    page.runJavaScript("location.href = 'https://example.com/'")
    process_events(qapp, lambda: False, timeout=0.5)
    assert t.view.url().scheme() != "https"
    t.shutdown()
    time.sleep(0)


def test_tab_search_failure_says_so_and_can_be_retried(qapp, tab):
    tab.search.setText("nothing like this")
    tab._on_failed("search", "timed out")
    assert tab._results == []
    assert "Search failed" in tab.list.item(0).text() and "Enter" in tab.info.text()
    tab._search_now()                            # Enter: back to searching
    assert tab._results is None and "Searching" in tab.list.item(0).text()


def test_tab_takes_results_for_a_query_cut_to_the_search_limit(tab):
    long = "rock " * 30
    tab.search.setText(long)
    s = Station(uuid="r", name="Rock Radio", url="http://example.com/r")
    tab._on_results(radio.search_text(long), [s])
    assert tab._results and tab._results[0].uuid == "r"


def test_tab_keeps_a_directory_failure_up_until_a_reload_works(tab):
    stations = tab._globe_list
    tab._globe_list = []
    tab._on_failed("globe", "no route")
    assert "press ↻" in tab.list.item(0).text() and "press ↻" in tab.info.text()
    tab._flash_until = 0.0
    tab._refresh_info()                          # later refreshes keep saying so
    assert "press ↻" in tab.info.text() and "Finding" not in tab.info.text()
    tab._on_globe_stations(stations)
    assert "press ↻" not in tab.info.text() and tab.list.count() == 5


def test_tab_filters_by_genre_country_and_quality(tab):
    from soundboard.ui.radiopanel import in_genre
    a, b, c = tab._globe_list[:3]
    b.tags, b.country, b.bitrate = ["deep house", "chillout"], "Germany", 256
    c.tags, c.bitrate = ["Classic Rock"], 320
    assert in_genre(b, "Dance") and in_genre(b, "Chill") and not in_genre(a, "Dance")
    tab.set_genre("Rock")
    assert [s.uuid for s in tab.visible_stations()] == [c.uuid]
    assert "1 of 5" in tab.count_label.text() and tab.btn_clear.isVisibleTo(tab)
    tab.set_genre("")
    tab.set_country("Germany")
    assert [s.uuid for s in tab.visible_stations()] == [b.uuid]
    assert tab.cmb_country.findData("Japan") > 0      # the other countries stay pickable
    tab.set_country("")
    tab.cmb_quality.setCurrentIndex(3)                # 256 kbps +
    tab._on_filter()
    assert {s.uuid for s in tab.visible_stations()} == {b.uuid, c.uuid}
    tab.cmb_sort.setCurrentIndex(5)                   # best quality first
    assert [s.uuid for s in tab.visible_stations()] == [c.uuid, b.uuid]
    tab.set_genre("Latin")
    assert tab.list.count() == 1 and "No stations match" in tab.list.item(0).text()
    tab.clear_filters()
    assert tab.list.count() == 5 and not tab.btn_clear.isVisibleTo(tab)


def test_tab_remembers_recently_played_stations(tab):
    tab.player.play = lambda s: None                  # no stream needed
    for uuid in ("uuid-1", "uuid-3", "uuid-1"):
        tab.play(tab._stations[uuid])
    assert [r["uuid"] for r in tab.cfg.radio["recent"]] == ["uuid-1", "uuid-3"]
    tab.btn_recent.click()
    assert [tab.list.item(i).data(0x0100) for i in range(tab.list.count())] == ["uuid-1",
                                                                                 "uuid-3"]


def test_tab_star_toggles_by_uuid_and_rows_paint(tab):
    tab._toggle_fav("uuid-2")
    assert tab._fav_ids == {"uuid-2"}
    tab.list.setCurrentRow(2)
    tab.list.resize(400, 300)
    assert not tab.list.grab().isNull()               # the delegate paints without errors
    tab._toggle_fav("uuid-2")
    assert tab.cfg.radio["favorites"] == []


class _JunkMirror:
    """A mirror answering 200 with an HTML page (maintenance, a captive portal)."""

    def __init__(self):
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = b"<html>maintenance</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_directory_fails_over_from_a_mirror_answering_junk(qapp, server, tmp_path):
    junk = _JunkMirror()
    try:
        d = RadioDirectory(tmp_path, bases=(junk.base, server.base))
        got, fails, res = [], [], []
        d.globe_ready.connect(got.append)
        d.failed.connect(lambda k, m: fails.append((k, m)))
        d.results.connect(lambda q, st: res.append(len(st)))
        d.load_globe()
        process_events(qapp, lambda: got or fails)
        d.search("rock")
        process_events(qapp, lambda: res or len(fails) > 1)
    finally:
        junk.close()
    assert got and not fails and res == [1]


def test_tab_plays_fresh_directory_data_over_a_saved_favourite(qapp, app_dir, server):
    from soundboard.ui.radiopanel import RadioTab
    old = Station.from_api(api_station(1, url_resolved="http://example.com/OLD.mp3"))
    cfg = Config()
    cfg.radio = {"favorites": [old.to_saved()]}
    d = RadioDirectory(app_dir / "radio", bases=(server.base,))
    t = RadioTab(FakeEngine(), cfg, lambda: None, FakeMeter, directory=d, globe=False)
    t.start()
    try:
        assert process_events(qapp, lambda: t._globe_list)
        played = []
        t.player.play = played.append
        t._on_globe_click("uuid-1")
        assert [s.url for s in played] == ["http://example.com/1.mp3"]
        assert cfg.radio["favorites"][0]["url"] == "http://example.com/1.mp3"   # saved too
    finally:
        t.shutdown()


def test_tab_reload_updates_stations_already_known(qapp, tab, server):
    server.stations[2]["url_resolved"] = "http://example.com/NEW.mp3"
    first = tab._globe_list
    tab._reload()
    assert process_events(qapp, lambda: tab._globe_list is not first)
    played = []
    tab.player.play = played.append
    tab._play_or_stop("uuid-2")
    assert played[0].url == "http://example.com/NEW.mp3"


def test_tab_radio_volume_zero_is_remembered(qapp, app_dir, server):
    from soundboard.ui.radiopanel import RadioTab
    cfg = Config()
    d = RadioDirectory(app_dir / "radio", bases=(server.base,))
    t = RadioTab(FakeEngine(), cfg, lambda: None, FakeMeter, directory=d, globe=False)
    t.vol.spin.setValue(0)
    t.shutdown()
    t2 = RadioTab(FakeEngine(), cfg, lambda: None, FakeMeter, directory=d, globe=False)
    try:
        assert t2.engine.radio_vol == 0.0
    finally:
        t2.shutdown()


def test_last_15s_holds_only_the_station_that_played(qapp, tab, server):
    a, b = tab._stations["uuid-0"], tab._stations["uuid-3"]
    a.url = b.url = server.base + "/stream.wav"
    names = []
    tab.clip_ready.connect(lambda data, name: names.append(name))
    tab.play(a)
    assert process_events(qapp, lambda: sum(map(len, tab.engine.chunks)) > SR, 15)
    tab.stop()
    tab.list.setCurrentRow(3)            # browsing to another station afterwards
    assert tab.clip_last() and names[-1].startswith(a.name)
    tab.play(b)                          # a different station: its own 15 seconds
    assert len(tab.recorder.last()) < SR // 2
    tab.stop()
