"""Radio tab: station parsing, the directory client, the stream player and the tab.

A local HTTP server on 127.0.0.1 stands in for Radio Browser and for a radio
station (a synthesized tone served as a WAV stream), so nothing here touches the
internet and nothing plays out loud (the player only hands audio to the engine).
"""
import base64
import hashlib
import http.server
import io
import json
import threading
import time

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QWidget

from conftest import closed_port, process_events
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


def test_station_plays_over_https_when_the_directory_lists_it():
    https = Station.from_api(api_station(1, url="https://example.com/live.mp3"))
    assert https.url == "https://example.com/live.mp3"   # the network can't see which station
    playlist = Station.from_api(api_station(1, url="https://example.com/live.pls"))
    assert playlist.url == "http://example.com/1.mp3"    # FFmpeg can't play a playlist
    both = Station.from_api(api_station(1, url="https://a.example.com/x",
                                        url_resolved="https://b.example.com/x.mp3"))
    assert both.url == "https://b.example.com/x.mp3"     # resolved still wins when it's https


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


def _outline_file(**changes):
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"NAME": "Square"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]}},
        {"type": "Feature", "properties": {"NAME": "Two"},
         "geometry": {"type": "MultiPolygon", "coordinates": [
             [[[20, 20], [30, 20], [30, 30], [20, 20]]], [[[40, 40], [50, 40], [50, 50]]]]}}]}
    geo.update(changes)
    return json.dumps(geo).encode()


def test_map_outlines_must_be_the_pinned_file(monkeypatch):
    import base64
    import hashlib
    raw = _outline_file()
    assert radio.outline_rings(raw) == []          # not the pinned file: refused
    monkeypatch.setattr(radio, "COUNTRIES_SRI",
                        "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode())
    rings = radio.outline_rings(raw)
    assert len(rings) == 3 and rings[0][1] == (10.0, 0.0)
    assert radio.outline_rings(raw + b" ") == [] and radio.outline_rings("text") == []


def test_map_names_sit_on_each_countrys_biggest_land(monkeypatch):
    import base64
    import hashlib
    raw = _outline_file()
    assert radio.outline_labels(raw) == []          # not the pinned file: no names either
    monkeypatch.setattr(radio, "COUNTRIES_SRI",
                        "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode())
    labels = {n: (lon, lat, w) for n, lon, lat, w in radio.outline_labels(raw)}
    lon, lat, w = labels["Square"]
    assert (round(lon, 2), round(lat, 2), w) == (6.67, 3.33, 10)   # the triangle's centroid
    assert labels["Two"][0] == pytest.approx(26.67, abs=0.01)     # the first of equal pieces
    assert "Hawaii" in labels                       # and the places the outlines leave out


def test_flat_map_fills_its_area_and_wraps_round_the_world(qapp):
    from soundboard.ui.flatmap import LAT_BOTTOM, LAT_TOP, FlatMap
    m = FlatMap()
    m.resize(800, 600)                    # taller than the world at its width
    m.set_land([[(0, 0), (10, 0), (10, 10)]], [("Square", 6.7, 3.3, 10)])
    m.grab()
    s = m._scale()
    assert (LAT_TOP - LAT_BOTTOM) * s >= m.height() and 360 * s >= m.width()   # no bands
    m.set_points(radio.globe_points([Station.from_api(api_station(1, geo_lat=0,
                                                                  geo_long=-170))]))
    m.cx = 175.0                          # the dateline in the middle
    m.grab()
    x, _y = m._screen()
    assert abs(x[0] - (m.width() / 2 + 15 * s)) < 1   # -170 is just east of 175
    m.cx = 190.0
    m._clamp()
    assert m.cx == -170.0


def test_a_tile_dropped_half_drawn_leaves_its_painter_balanced(qapp):
    """Switching stations / zooming drops a tile mid-draw (_drop_build closes its steps
    at a yield): the painter was ended with its save()s still open, and Qt warned
    "QPainter::end: Painter ended with 2 saved states"."""
    from PySide6.QtCore import qInstallMessageHandler
    from soundboard.ui.flatmap import FlatMap
    m = FlatMap()
    m.resize(800, 600)
    m.set_land([[(x, 0), (x + 5, 0), (x + 5, 5)] for x in range(-170, 170, 10)])
    warned = []
    old = qInstallMessageHandler(lambda _kind, _ctx, msg: warned.append(msg))
    try:
        total = sum(1 for _ in m._tile_steps(m._level(), 0, 0)[1])
        assert total >= 2
        for steps_in in range(1, total + 1):   # dropped at every step it can stop at
            _pm, steps = m._tile_steps(m._level(), 0, 0)
            for _ in range(steps_in):
                next(steps, None)
            steps.close()
    finally:
        qInstallMessageHandler(old)
    assert not [w for w in warned if "saved states" in w], warned


def test_flat_map_hovers_clicks_and_follows_the_playing_station(qapp):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from soundboard.ui.flatmap import ZOOM_MAX, FlatMap
    m = FlatMap()
    m.resize(720, 284)          # 2 px per degree
    pts = radio.globe_points([Station.from_api(api_station(i, geo_lat=10 * i, geo_long=20 * i,
                                                           name=f"<b>S{i}</b>"))
                              for i in range(1, 4)])
    m.set_points(pts)
    m.set_land([[(0, 0), (10, 0), (10, 10)]])
    m.grab()                    # paints (land, dots) without a window
    x, y = m._screen()
    i = [d["id"] for d in m._points].index("uuid-2")
    at = QPointF(x[i] + 2, y[i] - 1)
    assert m._hit(at) == i and m._hit(QPointF(5, 5)) == -1
    assert "&lt;b&gt;S2&lt;/b&gt;" in m._tip(m._points[i])        # names are text
    got = []
    m.clicked.connect(got.append)
    for kind in (QMouseEvent.MouseButtonPress, QMouseEvent.MouseButtonRelease):
        QApplication.sendEvent(m, QMouseEvent(kind, at, at, Qt.LeftButton, Qt.LeftButton,
                                              Qt.NoModifier))
    assert got == ["uuid-2"]
    extra = radio.globe_points([Station.from_api(api_station(9, geo_lat=-20, geo_long=-60))])[0]
    m.select(extra, go=True)    # one found by search joins the map, which turns to it
    assert len(m._points) == 4 and m.zoom > 1 and (m.cx, m.cy) == (-60, -20)
    m.grab()
    m._zoom_by(1000)
    assert m.zoom == pytest.approx(ZOOM_MAX)
    m.mouseDoubleClickEvent(QMouseEvent(QMouseEvent.MouseButtonDblClick, QPointF(1, 1),
                                        QPointF(1, 1), Qt.LeftButton, Qt.LeftButton,
                                        Qt.NoModifier))
    assert m.zoom == 1



def test_flat_map_fans_out_stations_on_the_same_spot(qapp):
    """A whole city's stations listed at its centre come apart zoomed in, each its own
    dot to click; zoomed out they stay one dot, and dots alone don't move."""
    pts = [{"id": f"s{i}", "la": 50.0, "lo": 10.0, "k": i} for i in range(20)]
    pts.append({"id": "alone", "la": 40.0, "lo": 0.0, "k": 5})
    from soundboard.ui.flatmap import FlatMap
    m = FlatMap()
    m.resize(400, 300)
    m.set_points(pts)
    alone = [d["id"] for d in m._points].index("alone")
    xs, ys = m._screen()
    assert len({(round(x), round(y)) for x, y in zip(xs, ys)}) == 2
    m.zoom, m.cx, m.cy = 50.0, 10.0, 50.0
    xs, ys = m._screen()
    spots = {(round(x), round(y)) for x, y in zip(xs, ys)}
    assert len(spots) == 21
    gap = min(np.hypot(xs[i] - xs[j], ys[i] - ys[j])
              for i in range(21) for j in range(i) if alone not in (i, j))
    assert gap >= 4                                   # far enough apart to tell apart
    assert m._fan[alone].tolist() == [0, 0]
    middle = [d["id"] for d, f in zip(m._points, m._fan) if not f.any()]
    assert sorted(middle) == ["alone", "s19"]        # the busiest keeps the middle
    m.grab()


def test_maps_ship_with_the_app_and_fetch_nothing():
    """No CDN learns who opened the Radio tab: the outlines the map draws are in
    ASSET_DIR, exactly the pinned version. The 3D globe's script and Earth pictures
    went with it (build.ps1 ships the whole folder)."""
    raw = (radio.ASSET_DIR / radio.COUNTRIES).read_bytes()
    digest = "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode()
    assert digest == radio.COUNTRIES_SRI
    assert sorted(p.name for p in radio.ASSET_DIR.iterdir()) == sorted(
        [radio.COUNTRIES, "LICENSE.txt"])


def test_plays_are_counted_only_when_allowed(tab, monkeypatch):
    counted = []
    monkeypatch.setattr(tab.player, "play", lambda s: None)
    monkeypatch.setattr(tab.dir, "count_click", counted.append)
    s = tab._stations["uuid-0"]
    tab.play(s)
    assert counted == []                       # off by default (Settings > Privacy)
    tab.cfg.radio["count_plays"] = True
    tab.play(s)
    assert counted == ["uuid-0"]


def test_flat_map_outlines_come_from_the_app(qapp):
    d = RadioDirectory(cache_dir=None)
    got = []
    d.outlines_ready.connect(lambda rings, labels: got.append((rings, labels)))
    d.load_outlines()
    assert process_events(qapp, lambda: got)
    rings, labels = got[0]
    assert len(rings) > 200 and any(n == "Japan" for n, *_ in labels)


def test_reading_the_map_outlines_never_holds_up_the_window(qapp, monkeypatch):
    """A 1.8.0 freeze: the outlines were read on the UI thread (5 s on a busy disk)."""
    import threading
    import time
    gate, real = threading.Event(), radio.outline_rings
    monkeypatch.setattr(radio, "outline_rings", lambda raw: gate.wait(5) and real(raw))
    d = RadioDirectory(cache_dir=None)
    got = []
    d.outlines_ready.connect(lambda rings, labels: got.append(rings))
    start = time.monotonic()
    d.load_outlines()
    assert time.monotonic() - start < 0.5 and not got
    gate.set()
    assert process_events(qapp, lambda: got) and len(got[0]) > 200


def test_map_names_islands_the_outlines_leave_out():
    names = [p[0] for p in radio.PLACES]
    assert len(names) == len(set(names))
    for name, lat, lon, width in radio.PLACES:
        assert -90 <= lat <= 90 and -180 <= lon <= 180 and 0 < width < 10, name
        assert name.isascii() and "<" not in name, name


def _town(i, place, lat, lon, **kw):
    return Station.from_api(api_station(i, state=place, geo_lat=lat, geo_long=lon, **kw))


def test_town_names_come_from_where_the_stations_are():
    pts = radio.globe_points([
        _town(1, "Accra", 5.6, -0.2, country="Ghana", countrycode="GH"),
        _town(2, "accra ", 5.62, -0.18, country="Ghana", countrycode="GH"),
        _town(3, "Accra", 5.58, -0.22, country="Ghana", countrycode="GH"),
        _town(4, "Kumasi", 6.7, -1.6, country="Ghana", countrycode="GH"),
        _town(5, "Ghana", 7.0, -1.0, country="Ghana", countrycode="GH"),   # the country
        _town(6, "Nowhere", 10, 10), _town(7, "Nowhere", -30, 100),       # scattered
        _town(8, "", 1, 1), _town(9, "123", 2, 2)])
    towns = radio.town_labels(pts)
    assert [t["n"] for t in towns] == ["Accra", "Kumasi"]   # most stations first
    assert towns[0]["k"] == 3 and (towns[0]["la"], towns[0]["lo"]) == (5.6, -0.2)
    assert radio.town_labels(pts, limit=1) == towns[:1]
    assert _town(1, "Accra", 5.6, -0.2).matches(["accra"])   # search finds the place


def test_search_ignores_accents_and_case():
    for place, typed in (("Zürich", "zurich"), ("İstanbul", "istanbul"),
                         ("São Paulo", "sao paulo"), ("Kraków", "KRAKOW")):
        assert _town(1, place, 0, 0).matches(radio.fold(typed).split()), place
    assert not _town(1, "Zürich", 0, 0).matches(["bern"])


def test_a_place_on_the_180_line_is_one_place():
    pts = radio.globe_points([_town(1, "Taveuni", -16.8, 179.95, countrycode="FJ"),
                              _town(2, "Taveuni", -16.9, -179.98, countrycode="FJ"),
                              _town(3, "Taveuni", -16.85, 179.9, countrycode="FJ")])
    [t] = radio.town_labels(pts)
    assert t["k"] == 3 and 179 < abs(t["lo"]) <= 180


def test_a_tie_between_spellings_picks_the_capitalised_one():
    pts = radio.globe_points([_town(1, "accra", 5.6, -0.2), _town(2, "Accra", 5.6, -0.2)])
    assert [t["n"] for t in radio.town_labels(pts)] == ["Accra"]


def test_flat_map_names_towns_only_zoomed_in_and_only_in_view(qapp, monkeypatch):
    from soundboard.ui import flatmap
    from soundboard.ui.flatmap import FlatMap
    m = FlatMap()
    m.resize(720, 284)
    towns = [{"n": f"Town {i}", "la": 0.0, "lo": i * 3.0, "k": 100 - i} for i in range(60)]
    towns.append({"n": "Far", "la": 0.0, "lo": -120.0, "k": 1})
    m.set_towns(towns)
    drawn = []
    real = m._town_pixmap
    monkeypatch.setattr(m, "_town_pixmap", lambda n, dpr: drawn.append(n) or real(n, dpr))
    m.grab()
    assert drawn == []                      # zoomed out: no names, nothing even looked at
    m.zoom, m.cx, m.cy = 6.0, 10.0, 0.0
    m.grab()
    assert drawn and "Far" not in drawn     # only the places in view
    assert "Town 0" in drawn and len(drawn) <= 60
    pm = flatmap.QPixmap(720, 284)
    p = flatmap.QPainter(pm)
    shown = m._paint_towns(p, 1.0)
    p.end()
    assert 0 < shown <= flatmap.TOWNS_IN_VIEW      # never more than a handful at once


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
    return f"http://127.0.0.1:{closed_port()}"


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


def test_a_day_old_station_list_shows_at_once_and_is_refreshed_behind_it(
        qapp, server, tmp_path, monkeypatch):
    """Over a day old, the saved list used to wait for the directory (seconds on an
    empty map, longer over Tor). Now it shows straight away and the fresh list
    replaces it when it comes; if the directory can't be reached, it just stays."""
    d = RadioDirectory(tmp_path, bases=(server.base,))
    d._write_cache([Station.from_api(api_station(1))])
    monkeypatch.setattr(radio, "CACHE_S", -1)                   # every list is old
    got = []
    d.globe_ready.connect(got.append)
    d.load_globe()
    assert process_events(qapp, lambda: len(got) == 2)
    assert [s.uuid for s in got[0]] == ["uuid-1"]               # the saved one, at once
    assert len(got[1]) == 5                                     # then the fresh one
    dead = RadioDirectory(tmp_path / "x", bases=(dead_base(),))
    dead._write_cache([Station.from_api(api_station(1))])
    got, fails = [], []
    dead.globe_ready.connect(got.append)
    dead.failed.connect(lambda kind, msg: fails.append(kind))
    dead.load_globe()
    assert process_events(qapp, lambda: dead.globe_stale)
    assert len(got) == 1 and not fails                          # no error over a list


def test_a_directory_let_go_while_its_thread_ends_is_freed_on_the_ui_thread(
        qapp, tmp_path, monkeypatch):
    """The worker thread holds the directory; under load it could end after the
    result was handled and every other reference had gone, and the directory (a
    QObject) was then destroyed on that thread."""
    import threading
    import types
    from PySide6.QtCore import Qt

    class SlowEnd(threading.Thread):        # preempted just after handing over
        def run(self):
            try:
                self._target(*self._args, **self._kwargs)
                time.sleep(0.2)
            finally:
                del self._target, self._args, self._kwargs
    monkeypatch.setattr(radio, "threading", types.SimpleNamespace(Thread=SlowEnd))
    where, ran = [], []
    d = RadioDirectory(tmp_path, bases=(dead_base(),))
    d.destroyed.connect(lambda *_: where.append(threading.current_thread().name),
                        Qt.DirectConnection)
    d._off_thread(lambda: 1, ran.append, lambda: None)
    del d
    assert process_events(qapp, lambda: where, timeout=3)
    assert ran == [1] and where == ["MainThread"]


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
    assert any("state=rock" in h for h in server.hits)   # cities and regions too


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


def test_radio_keeps_flowing_while_the_window_is_busy(qapp, server):
    """The chunks come straight from Qt's decoding thread: a window busy for a second
    used to hold them all back, and the radio ran dry (it skipped)."""
    from PySide6.QtCore import Qt
    p = RadioPlayer()
    got, lock = [], threading.Lock()

    def sink(x):
        with lock:
            got.append((time.monotonic(), threading.get_ident(), len(x)))

    p.audio.connect(sink, Qt.DirectConnection)
    p.play(Station(uuid="u", name="Tone FM", url=server.base + "/stream.wav"))
    try:
        assert process_events(qapp, lambda: p.status == "playing", timeout=15)
        t0 = time.monotonic()
        time.sleep(1.0)                    # the window, busy: no events handled
        with lock:
            during = [g for g in got if t0 < g[0] < t0 + 1.0]
        assert sum(n for *_, n in during) > SR // 2
        assert all(tid != threading.get_ident() for _, tid, _ in during)
    finally:
        p.stop()


def test_first_audio_is_sent_once_however_long_the_window_takes(qapp, server):
    from PySide6.QtCore import Qt
    p = RadioPlayer()
    sent = []
    p._first_audio.connect(sent.append, Qt.DirectConnection)
    p.play(Station(uuid="u", name="Tone FM", url=server.base + "/stream.wav"))
    try:
        t0 = time.monotonic()
        while not sent and time.monotonic() - t0 < 15:
            qapp.processEvents()
            time.sleep(0.01)
        time.sleep(0.5)                    # busy: many more buffers, the first not seen
        assert len(sent) == 1
        assert process_events(qapp, lambda: p.status == "playing", timeout=5)
    finally:
        p.stop()


def test_shutdown_waits_out_a_buffer_being_handed_over(qapp):
    """Qt's decoding thread mid-way through a buffer when the player shuts down (its tab
    going): shutdown waits for it, and a buffer after that isn't taken. Freed while
    that thread still used it, the player crashed."""
    p = RadioPlayer()
    inside, release, took = threading.Event(), threading.Event(), []

    def slow(buf):
        inside.set()
        release.wait(5)
        took.append(buf)
    p._take_buffer = slow
    t = threading.Thread(target=p._on_buffer, args=("first",))
    t.start()
    assert inside.wait(5)
    threading.Timer(0.2, release.set).start()
    t0 = time.monotonic()
    p.shutdown()
    assert time.monotonic() - t0 > 0.15 and took == ["first"]
    p._on_buffer("later")
    t.join(5)
    assert took == ["first"]
    p.shutdown()                                  # twice (the window, then the tab): fine


def test_player_reports_a_dead_station(qapp, monkeypatch):
    monkeypatch.setattr(radio, "CONNECT_S", 1.5)   # FFmpeg alone can wait for minutes
    p = RadioPlayer()
    errors = []
    p.error.connect(errors.append)
    p.play(Station(uuid="u", name="Gone", url=dead_base() + "/nothing"))
    assert process_events(qapp, lambda: errors, timeout=15)
    assert p.station is None and p.status == "error"


def test_a_station_name_that_leads_into_the_home_network_isnt_played(qapp, monkeypatch):
    addrs = {"lan.example.com": "169.254.10.20", "fm.example.com": "93.184.216.34"}
    monkeypatch.setattr(radio.socket, "getaddrinfo", lambda host, *_a, **_k: [
        (2, 1, 6, "", (addrs[host], 0))])
    p = RadioPlayer()
    opens, errors = [], []
    p._open = lambda: opens.append(p.station.url)
    p.error.connect(errors.append)
    p.play(Station(uuid="u", name="Router FM", url="http://lan.example.com/admin"))
    assert process_events(qapp, lambda: errors, timeout=5)
    assert opens == [] and p.station is None and p.status == "error"
    p.play(Station(uuid="v", name="Real FM", url="http://fm.example.com/live"))
    assert process_events(qapp, lambda: opens, timeout=5)
    assert opens == ["http://fm.example.com/live"]


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
    assert process_events(qapp, lambda: t._globe_list, timeout=20)   # slow when the PC is busy
    yield t
    t.shutdown()


def test_tab_lists_popular_stations_and_starts_off_air(tab):
    assert tab.list.count() == 5
    assert tab.engine.radio_live is False and not tab.btn_live.isChecked()
    assert tab.engine.radio_vol == pytest.approx(0.5)


@pytest.mark.parametrize("old", [{"map": "globe"}, {"globe_hd": True}, {}])
def test_the_map_is_the_only_view_and_the_3d_globe_setting_moves_to_it(
        qapp, app_dir, server, monkeypatch, old):
    """The HD (3D globe) button is gone. Someone who had the globe on gets the map, and
    the setting says "flat", which every older version reads as the map too."""
    from PySide6.QtWidgets import QPushButton

    from soundboard.ui.flatmap import FlatMap
    from soundboard.ui.radiopanel import RadioTab
    d = RadioDirectory(app_dir / "radio", bases=(server.base,))
    monkeypatch.setattr(d, "load_outlines", lambda: d.outlines_ready.emit([], []))   # offline
    cfg = Config()
    cfg.radio = dict(old)
    saved = []
    t = RadioTab(FakeEngine(), cfg, lambda: saved.append(dict(cfg.radio)), FakeMeter,
                 directory=d, globe=True)
    if old.get("map") == "globe":
        assert cfg.radio["map"] == "flat" and saved   # moved over, and saved at once
    else:
        # nothing to move: left alone (other settings may still save)
        assert cfg.radio.get("map") is None and not any("map" in s for s in saved)
    t.start()
    assert process_events(qapp, lambda: t.flat is not None and t._globe_list)
    assert isinstance(t.flat, FlatMap) and not hasattr(t, "view")
    assert len(t.flat._points) == 5               # the map takes every station
    assert [b.text() for b in t.flat.findChildren(QPushButton)] == ["+", "−"]   # no HD
    t.shutdown()


def test_the_decoder_preloads_when_the_tab_first_opens_not_at_start_up(
        qapp, app_dir, server, monkeypatch):
    """Loading Qt's FFmpeg DLLs on a thread stops a hitch as the first station starts,
    but costs ~22 MB: only once the radio is used."""
    from soundboard.ui.radiopanel import RadioTab
    calls = []
    monkeypatch.setattr(radio, "preload_decoder", lambda: calls.append(1))
    d = RadioDirectory(app_dir / "radio", bases=(server.base,))
    cfg = Config()
    t = RadioTab(FakeEngine(), cfg, lambda: None, FakeMeter, directory=d, globe=False)
    RadioPlayer().shutdown()
    assert calls == []                            # built (at every start-up): nothing yet
    t.start()
    t.start()                                     # the tab shown again
    assert calls == [1]
    assert process_events(qapp, lambda: t._globe_list, timeout=20)
    t.shutdown()


def test_tab_search_shows_local_matches_then_the_directory(qapp, tab, server):
    tab.search.setText("japan")                     # known locally (country)
    tab.flush_typing()
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
    # Radio Browser isn't told what you play unless Settings > Privacy says it may be
    assert not any(h.startswith("/json/url/") for h in server.hits)
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


def test_tab_search_failure_says_so_and_can_be_retried(qapp, tab):
    tab.search.setText("nothing like this")
    tab._on_failed("search", "timed out")
    assert tab._results == []
    assert "Search failed" in tab.list.item(0).text() and "Enter" in tab.info.text()
    tab._search_now()                            # Enter: back to searching
    assert tab._results is None and "Searching" in tab.list.item(0).text()


def test_tab_search_lists_after_a_typing_pause_without_refolding(qapp, tab, monkeypatch):
    """Typing doesn't rebuild the list on every key, and each station's search text is
    folded once, not once per keystroke (3000 stations: ~20 ms a pass)."""
    folds = []
    real = radio.fold
    for s in tab._globe_list:
        s.matches(["warm the cache"])
    monkeypatch.setattr(radio, "fold", lambda text: folds.append(text) or real(text))
    monkeypatch.setattr(tab.dir, "search", lambda text: None)   # no directory answers
    tab.search.setText("sta")
    tab.search.setText("station 3")
    assert tab.list.count() == 5 and folds == []     # nothing yet: still typing
    assert process_events(qapp, lambda: tab.list.count() == 1)   # the pause: listed
    assert folds == ["station 3"]                    # the words, not every station
    tab.search.setText("station 4")
    tab._search_now()                                # Enter: at once, no pause
    assert tab.list.count() == 1 and "Station 4" in tab.list.item(0).text()
    tab.search.setText("")                           # clearing is at once too
    assert tab.list.count() == 5


def test_station_search_and_map_data_follow_changed_fields():
    s = Station.from_api(api_station(1, name="Zürich FM"))
    assert s.matches(["zurich"]) and radio.globe_points([s])[0]["n"] == "Zürich FM"
    s.name, s.tags = "Bern FM", ["rock"]
    assert s.matches(["bern"]) and not s.matches(["zurich"])
    assert s.genre_hay == "rock" and radio.globe_points([s])[0]["n"] == "Bern FM"


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


def test_tab_map_keeps_towns_per_filter_until_new_stations(tab, monkeypatch):
    calls = []
    real = radio.town_labels
    monkeypatch.setattr(radio, "town_labels", lambda pts: calls.append(1) or real(pts))
    tab._globe_list[0].tags = ["rock"]
    tab.set_genre("Rock")
    tab.set_genre("")                                 # shown before: not worked out again
    tab.set_genre("Rock")
    assert len(calls) == 1
    tab._on_globe_stations(list(tab._globe_list))     # a new list: new points and towns
    assert len(calls) == 2


def test_tab_filter_change_goes_through_the_stations_once(tab, monkeypatch):
    """The list, the country menu and the map share one genre/quality pass over the
    popular stations (3000 of them: ~3 ms a pass), and a country menu with the same
    counts isn't filled again."""
    passes, fills = [], []
    real = tab._filtered
    monkeypatch.setattr(tab, "_filtered", lambda *a, **k: passes.append(1) or real(*a, **k))
    monkeypatch.setattr(tab.cmb_country, "clear", lambda: fills.append(1))
    tab._globe_list[0].tags = ["rock"]
    tab.set_genre("Rock")
    assert len(passes) == 1 and tab.list.count() == 1 and len(fills) == 1
    tab.set_genre("")
    tab.set_genre("Rock")                       # both chosen before: no new pass
    assert len(passes) == 1 and tab.list.count() == 1
    fills.clear()
    tab.set_country(tab._globe_list[0].country)   # the same counts: menu kept
    assert len(passes) == 1 and fills == [] and tab.list.count() == 1


def test_tab_play_stop_and_star_relabel_rows_without_rebuilding(tab, monkeypatch):
    from PySide6.QtCore import Qt
    tab.player.play = lambda s: setattr(tab.player, "station", s)
    tab.player.stop = lambda: setattr(tab.player, "station", None)
    tab.list.item(0).setData(Qt.UserRole + 1, "same row")
    kept = lambda: tab.list.item(0).data(Qt.UserRole + 1) == "same row"   # noqa: E731
    tab.play(tab._stations["uuid-0"])
    row = tab.list.item(0)
    assert kept() and row.text().startswith("▶ Station 0") and row.font().bold()
    tab._toggle_fav("uuid-0")
    assert kept() and tab.list.item(0).text().startswith("▶ ★ Station 0")
    tab.stop()
    row = tab.list.item(0)
    assert kept() and row.text().startswith("★ Station 0") and not row.font().bold()
    tab.btn_favs.click()                              # Favorites: starring changes the rows
    tab._toggle_fav("uuid-0")
    assert "No favorites" in tab.list.item(0).text()


def test_station_rows_paint_without_making_fonts_each_time(tab, monkeypatch):
    from soundboard.ui import radiopanel
    tab.list.resize(400, 300)
    tab.list.grab()
    made = []
    real = radiopanel.QFont
    monkeypatch.setattr(radiopanel, "QFont", lambda *a: made.append(1) or real(*a))
    assert not tab.list.grab().isNull()
    assert made == []


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
        assert process_events(qapp, lambda: t._globe_list, timeout=20)   # slow when the PC is busy
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


def test_filter_boxes_wrap_instead_of_cutting_their_words(qapp):
    """A narrow panel (beside the map): "All countries" / "Any quality" / "Default
    order" in full on more rows, not "All coun" / "Any qua" in one."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QComboBox

    from soundboard.ui.radiopanel import QUALITIES, SORTS, _FilterRow
    boxes = [QComboBox(), QComboBox(), QComboBox()]
    boxes[0].addItem("All countries")
    for label, _ in QUALITIES:
        boxes[1].addItem(label)
    for label, _ in SORTS:
        boxes[2].addItem(label)
    row = _FilterRow(boxes)

    def lay_out(width):   # what a resize to `width` does, without a window to resize
        row._arrange(row.rows_for(width))
        row.layout().activate()
        row.layout().setGeometry(QRect(0, 0, width, row.layout().sizeHint().height()))
        return row.rows

    seen = {w: lay_out(w) for w in (900, 520, 420, 300, 230)}
    for width in seen:
        lay_out(width)
        for c in boxes:
            if width >= row.needs(c):   # it fits on a row of its own at least
                assert c.width() >= row.needs(c), (width, row.rows, c.currentText(), c.width())
    assert seen[900] == 1 and seen[230] == 3 and len(set(seen.values())) == 3, seen
    boxes[0].addItem("Bosnia and Herzegovina")   # a long country picked: more room
    boxes[0].setCurrentIndex(1)
    lay_out(520)
    assert boxes[0].width() >= row.needs(boxes[0])


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


def test_the_dice_plays_any_popular_station_whatever_the_filters(tab, monkeypatch):
    """The dice ignores the list showing and every filter: a genre that hides most
    stations, an empty Favorites list, it still picks from all popular stations."""
    played = []
    monkeypatch.setattr(tab, "play", played.append)
    popular = {s.uuid for s in tab._globe_list}
    tab.set_genre("Rock")
    tab.favorites = []
    tab.btn_favs.click()
    assert not tab.visible_stations()
    for _ in range(40):
        tab.btn_random.click()
    assert played and all(s.uuid in popular for s in played)
    assert {s.uuid for s in played} - {s.uuid for s in tab._filtered(tab._globe_list)}


def test_loads_gently_reads_what_json_loads_reads():
    """The directory's answers are decoded an element at a time (one json.loads of
    the station list held the GIL long enough to stutter the audio)."""
    from soundboard.radio import loads_gently
    big = json.dumps([api_station(i) for i in range(50)])
    for text in (big, "[]", "{}", ' [1, 2 ,3] ', '{"a": [1, {"b": [2]}], "c": "x"}',
                 '"s"', "3.5", "null", '[{"k": [1,2]}, [], {}]', '{"time": 1.0, "stations": []}'):
        assert loads_gently(text) == json.loads(text)
        assert loads_gently(text.encode()) == json.loads(text)
    for bad in ("[1,]", "[1 2]", '{"a" 1}', "[1] x", "", '{"a": 1,}', "<html>", "{1: 2}"):
        with pytest.raises(ValueError):
            loads_gently(bad)


def test_saved_station_list_is_still_plain_json(tmp_path):
    """Written a station at a time, but the same file: older versions read it too."""
    d = RadioDirectory(tmp_path)
    stations = [Station.from_api(api_station(i)) for i in range(3)]
    d._write_cache(stations)
    raw = json.loads(d.cache_path.read_text(encoding="utf-8"))
    assert [s["uuid"] for s in raw["stations"]] == [s.uuid for s in stations]
    assert abs(raw["time"] - time.time()) < 60
    assert [s.uuid for s in d._read_cache()[1]] == [s.uuid for s in stations]


def test_phone_remote_lists_searches_and_drives_the_radio(qapp, tab, server, monkeypatch):
    """soundboard.remote's radio actions, on the tab itself: what a phone sees and does."""
    from types import SimpleNamespace

    from soundboard import remote
    played = []
    monkeypatch.setattr(tab.player, "play", lambda s: (played.append(s.uuid),
                                                      setattr(tab.player, "station", s)))
    monkeypatch.setattr(tab.player, "stop", lambda: setattr(tab.player, "station", None))
    mw = SimpleNamespace(radio=tab, engine=tab.engine)
    d = lambda action, **p: remote.dispatch_radio(mw, action, p)   # noqa: E731

    st, body = d("stations", list="popular")
    assert st == 200 and len(body["stations"]) == 5 and not body["loading"]
    assert d("stations", list="favorites")[1]["stations"] == []
    assert d("stations", list="sideways")[0] == 400
    assert remote.radio_state(mw)["on"] is False
    assert d("radio")[0] == 404                       # nothing has played yet

    st, state = d("radio", id="uuid-2")
    assert st == 200 and played == ["uuid-2"] and state["station"]["id"] == "uuid-2"
    assert d("radio", id="nope")[0] == 404
    assert d("stations", list="recent")[1]["stations"][0]["playing"] is True
    assert d("radio_star") == (200, {"id": "uuid-2", "fav": True})   # the one playing
    assert d("radio_star", on="1")[1]["fav"] is True                 # already: stays
    assert [s["id"] for s in d("stations", list="favorites")[1]["stations"]] == ["uuid-2"]
    assert tab.cfg.radio["favorites"][0]["uuid"] == "uuid-2"

    assert d("radio", on="0")[1]["on"] is False
    assert d("radio", on="1")[1]["station"]["id"] == "uuid-2"         # the last one again
    assert d("radio", on="maybe")[0] == 400
    assert d("radio_random", list="favorites")[0] == 404              # only the one playing
    assert d("radio_random", list="popular")[1]["station"]["id"] != "uuid-2"

    assert d("radio_live", on="1")[1]["live"] is True and tab.btn_live.isChecked()
    assert d("radio_hear", on="0")[1]["hear"] is False and tab.engine.radio_monitor is False
    assert d("radio_volume", set="30")[1]["volume"] == 30
    assert tab.engine.radio_vol == pytest.approx(0.3)
    assert d("radio_volume", step="up")[1]["volume"] == 40

    st, body = d("stations", list="search", q="japan")     # known here: at once
    assert len(body["stations"]) == 5 and body["loading"]
    st, body = d("stations", list="search", q="rock")
    assert body["loading"] and body["stations"] == []
    assert process_events(qapp, lambda: not d("stations", list="search",
                                              q="rock")[1]["loading"])
    assert [s["name"] for s in d("stations", list="search", q="rock")[1]["stations"]] == \
        ["Rock Radio"]
    assert tab._results is None and tab.search.text() == ""   # the tab's own search untouched
    assert d("radio", id="uuid-9")[0] == 200                   # a station found that way plays

    assert remote.dispatch_radio(SimpleNamespace(radio=object(), engine=tab.engine),
                                 "radio", {}) == (409, remote.RADIO_OFF)


def _drawn(qapp, m):
    """Paint, then let the tiles finish their slices."""
    m.grab()
    end = time.monotonic() + 5
    while m.busy() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.001)
    m.grab()


def test_the_flat_map_keeps_its_picture_while_tabs_flick_and_lets_it_go_later(qapp):
    """1.8.0 let the drawn map go the moment the map hid and drew all of it again
    on the UI thread as it came back: flicking Sounds <-> Radio froze the app every
    time. Now the tiles are kept for FORGET_MS, and a redraw is a slice at a time."""
    from soundboard.ui.flatmap import FlatMap
    m = FlatMap()
    m.resize(400, 300)
    m.set_points([{"id": "a", "la": 50.0, "lo": 10.0, "k": 1}])
    m.show()
    m.grab()
    assert not m._tiles and m.busy()                   # never all at once, even the first
    _drawn(qapp, m)
    tiles = dict(m._tiles)
    assert tiles
    for _ in range(5):                                 # flicking tabs: nothing redrawn
        m.hide()
        qapp.processEvents()
        m.show()
        m.grab()
        assert all(m._tiles.get(k) is pm for k, pm in tiles.items()) and not m.busy()
    m.hide()
    assert m._tiles and m._forget.isActive()
    m._forget.timeout.emit()                           # hidden a while
    # tens of MB, while nobody sees it; just the whole world's land is kept (to show
    # the moment it's back)
    assert {key[0][3:] for key in m._tiles} == {("land",)} and not m.busy()
    m.show()
    _drawn(qapp, m)
    assert m._tiles                                    # drawn again when it shows
    m.close()


def test_a_click_on_a_station_plays_it_and_the_bar_shows_what_plays(qapp, tab, server):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    for s in tab._stations.values():
        s.url = server.base + "/stream.wav"
    assert tab.now.name == "" and tab.btn_live.text() == "Send"
    tab.list.resize(400, 400)
    it = tab.list.item(1)
    at = tab.list.visualItemRect(it).center()     # the row's name, not its badge
    QTest.mouseClick(tab.list.viewport(), Qt.LeftButton, pos=at)
    uuid = it.data(Qt.UserRole)
    assert process_events(qapp, lambda: tab.player.station is not None)
    assert tab.player.station.uuid == uuid and tab.now.name == tab.player.station.name
    playing = tab.player
    QTest.mouseClick(tab.list.viewport(), Qt.LeftButton, pos=at)
    process_events(qapp, lambda: False, timeout=0.1)
    assert tab.player is playing and tab.player.station.uuid == uuid   # not restarted
    tab.btn_live.click()
    assert tab.btn_live.text() == "Sending" and tab.engine.radio_live
    tab.toggle_play()                                # Space / the Stop button
    assert tab.player.station is None and tab.now.name == ""
