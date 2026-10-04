"""With a proxy set (Settings > Privacy > Connection), every part of the app that goes
online goes through it and nothing leaks around it.

The sites are local test servers reached under made-up *.test names that only the
fake SOCKS5 proxy (tests/fakeproxy.py) knows, so a request that skipped the proxy
couldn't find them. Python-side connections and DNS lookups that leave 127.0.0.1 fail
the test outright (fakeproxy.no_leaks); Qt and FFmpeg connect from C++, so for them the
proof is the proxy's log plus the fact that the .test name worked at all."""
import http.server
import io
import json
import threading
import types

import numpy as np
import pytest
import soundfile as sf

from conftest import process_events
from fakeproxy import Socks5, no_leaks
from soundboard import net, updates
from soundboard.engine import SR
from test_radio import FakeEngine, FakeMeter, wav_bytes


class Sites:
    """One local HTTP server standing in for every site (GitHub, PyPI, Myinstants,
    Radio Browser, a station, an HLS CDN, thumbnails), told apart by path."""

    def __init__(self):
        self.hits: list[tuple[str, str]] = []    # (Host header, path)
        self.routes: dict[str, tuple[bytes, str]] = {}
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_):
                pass

            def do_GET(self):
                srv.hits.append((self.headers.get("Host", ""), self.path))
                hit = srv.routes.get(self.path.split("?")[0])
                if hit is None:
                    self.send_error(404)
                    return
                body, kind = hit
                if kind == "redirect":   # body: where to
                    self.send_response(302)
                    self.send_header("Location", body.decode())
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            do_HEAD = do_GET

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, host: str, path: str) -> str:
        return f"http://{host}.test:{self.port}{path}"

    def paths(self) -> list[str]:
        return [p for _h, p in self.hits]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# the real ones: conftest swaps them for stubs in every test, these tests put them back
REAL_GET, REAL_OPEN = updates._get, updates._open

NAMES = ("api.github", "pypi", "myinstants", "radio", "station", "cdn", "thumbs",
         "models", "media")


@pytest.fixture
def sites():
    s = Sites()
    yield s
    s.close()


@pytest.fixture
def socks(sites):
    p = Socks5({f"{n}.test": ("127.0.0.1", sites.port) for n in NAMES})
    net.configure(net.PROXY, p.url())
    yield p
    net.configure(net.DIRECT)
    p.close()


@pytest.fixture
def guard(monkeypatch):
    with no_leaks(monkeypatch) as leaks:
        yield leaks
    assert leaks == []


# ---------------------------------------------------------------- urllib users

def test_update_check_and_download(sites, socks, guard, monkeypatch):
    monkeypatch.setattr(updates, "_get", REAL_GET)
    monkeypatch.setattr(updates, "_open", REAL_OPEN)
    sites.routes["/releases/latest"] = (json.dumps({"tag_name": "v9.9.9"}).encode(),
                                        "application/json")
    sites.routes["/OnionBoardSetup.exe"] = (b"MZ" * 100, "application/octet-stream")
    assert updates._get(sites.url("api.github", "/releases/latest"))["tag_name"] == "v9.9.9"
    with updates._open(sites.url("api.github", "/OnionBoardSetup.exe")) as r:
        assert r.read() == b"MZ" * 100
    assert socks.hosts_asked() == {"api.github.test"}


def test_add_on_release_check(sites, socks, guard, monkeypatch, app_dir):
    from soundboard import watchaddon
    monkeypatch.setattr(updates, "_get", REAL_GET)
    sites.routes["/watch/latest"] = (json.dumps({"tag_name": "v1.0.0", "assets": []}).encode(),
                                     "application/json")
    monkeypatch.setattr(watchaddon, "API", sites.url("api.github", "/watch/latest"))
    try:
        watchaddon.latest()
    except Exception:  # noqa: BLE001 - no asset to offer: only the request matters here
        pass
    assert ("api.github.test" in socks.hosts_asked()
            and "/watch/latest" in sites.paths())


def test_ytdlp_updater_and_myinstants(sites, socks, guard, monkeypatch, app_dir):
    from soundboard import ytdl
    sites.routes["/pypi/yt-dlp/json"] = (b'{"info": {"version": "1"}}', "application/json")
    assert ytdl._get(sites.url("pypi", "/pypi/yt-dlp/json"), 1000).startswith(b"{")
    page = ("<button onclick=\"play('/media/sounds/bruh.mp3', 'x')\"></button>"
            '<a href="/en/instant/bruh/" class="instant-link link-secondary">Bruh</a>')
    sites.routes["/en/search/"] = (page.encode(), "text/html")
    sites.routes["/media/sounds/bruh.mp3"] = (b"ID3" + bytes(500), "audio/mpeg")
    monkeypatch.setattr(ytdl, "MYINSTANTS", f"http://myinstants.test:{sites.port}")
    hits = ytdl.search("bruh", source="myinstants")
    assert [h.title for h in hits] == ["Bruh"]
    path, _title = ytdl.download_audio(hits[0].url)
    assert path.read_bytes().startswith(b"ID3")
    assert socks.hosts_asked() == {"pypi.test", "myinstants.test"}


def test_translation_model_download(sites, socks, guard, monkeypatch, app_dir):
    from soundboard.speech import translation
    sites.routes["/model.argosmodel"] = (b"not really a model", "application/zip")
    info = types.SimpleNamespace(language="xx", download={
        "url": sites.url("models", "/model.argosmodel"), "sha256": "0" * 64, "bytes": 18})
    with pytest.raises(RuntimeError, match="checksum"):   # fetched, then rejected
        translation.download(info)
    assert "/model.argosmodel" in sites.paths() and socks.hosts_asked() == {"models.test"}


def test_a_custom_voice_server_on_this_pc_stays_direct(sites, socks, guard):
    from soundboard.speech import customvoices
    buf = io.BytesIO()
    sf.write(buf, np.zeros(2400, np.float32), 24000, format="WAV")
    sites.routes["/tts"] = (buf.getvalue(), "audio/wav")
    v = customvoices.CustomVoice(name="Local", url=f"http://127.0.0.1:{sites.port}/tts?t={{text}}")
    data, rate = v.synth("hi")
    assert rate == 24000 and socks.asked == []


# ---------------------------------------------------------------- yt-dlp (the real one)

def test_ytdlp_probes_and_downloads_through_the_proxy(sites, socks, guard, app_dir):
    from soundboard import ytdl
    sites.routes["/clip.wav"] = (wav_bytes(1.0), "audio/wav")
    url = sites.url("media", "/clip.wav")
    title, _secs = ytdl.probe(url)
    assert title
    path, _ = ytdl.download_audio(url, auto_update=False)
    assert path.read_bytes()[:4] == b"RIFF"
    assert socks.hosts_asked() == {"media.test"}


def test_ytdlp_search_goes_to_the_proxy_even_when_it_fails(socks, guard, app_dir):
    from soundboard import ytdl
    with pytest.raises(ytdl.DownloadError):
        ytdl.search("what is love", count=3)        # the fake proxy can't reach YouTube
    assert any("youtube" in h for h in socks.hosts_asked())


# ---------------------------------------------------------------- Qt

def test_radio_directory_through_the_proxy(qapp, sites, socks, tmp_path):
    from soundboard.radio import RadioDirectory
    from test_radio import api_station
    sites.routes["/json/stations/search"] = (json.dumps([api_station(1)]).encode(),
                                             "application/json")
    d = RadioDirectory(tmp_path, bases=(f"http://radio.test:{sites.port}",))
    got = []
    d.globe_ready.connect(got.append)
    d.load_globe()
    assert process_events(qapp, lambda: got, timeout=15)
    assert got[0][0].uuid == "uuid-1" and socks.hosts_asked() == {"radio.test"}


def test_search_thumbnails_through_the_proxy(qapp, sites, socks, monkeypatch):
    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QImage

    from soundboard import ytdl
    from soundboard.ui.ytsearch import ResultRow, SearchResults
    shown = []
    monkeypatch.setattr(ResultRow, "set_thumb", lambda row, pm: shown.append(pm.size().toTuple()))
    img = QImage(32, 18, QImage.Format_RGB32)
    img.fill(0x3366CC)
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QBuffer.WriteOnly)
    img.save(b, "PNG")
    sites.routes["/t.png"] = (bytes(ba), "image/png")
    hit = ytdl.Result(id="x", title="T", channel="c", seconds=1, source="soundcloud",
                      art=sites.url("thumbs", "/t.png"))
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": [hit])
    panel = SearchResults()
    panel.search("t")
    assert process_events(qapp, lambda: shown, timeout=15)
    assert shown == [(32, 18)]
    assert socks.hosts_asked() == {"thumbs.test"}


def play(qapp, url, timeout=20):
    from soundboard.radio import RadioPlayer, Station
    p = RadioPlayer()
    chunks, errors = [], []
    p.audio.connect(chunks.append)
    p.error.connect(errors.append)
    p.play(Station(uuid="u", name="Test FM", url=url))
    process_events(qapp, lambda: sum(map(len, chunks)) > SR // 2 or errors, timeout=timeout)
    return p, chunks, errors


def test_radio_stream_through_the_proxy(qapp, sites, socks, guard):
    # the guard also catches the home-network check looking the station's name up on
    # this PC, which would tell its DNS server which station it is
    sites.routes["/stream.wav"] = (wav_bytes(), "audio/wav")
    p, chunks, errors = play(qapp, sites.url("station", "/stream.wav"))
    p.stop()
    assert not errors and sum(map(len, chunks)) > SR // 2
    assert socks.hosts_asked() == {"station.test"}


def test_hls_playlists_and_segments_go_through_the_proxy(qapp, sites, socks):
    for i in range(3):
        buf = io.BytesIO()
        t = np.arange(SR * 2) / SR
        x = (np.sin(2 * np.pi * 440 * t) * 0.4).astype(np.float32)
        sf.write(buf, np.stack([x, x], 1), SR, format="MP3")
        sites.routes[f"/seg{i}.mp3"] = (buf.getvalue(), "audio/mpeg")
    playlist = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
    for i in range(3):   # the segments sit on another host, by absolute URL
        playlist += f"#EXTINF:2.0,\n{sites.url('cdn', f'/seg{i}.mp3')}\n"
    sites.routes["/live.m3u8"] = ((playlist + "#EXT-X-ENDLIST\n").encode(),
                                  "application/vnd.apple.mpegurl")
    p, chunks, errors = play(qapp, sites.url("station", "/live.m3u8"))
    p.stop()
    assert not errors and sum(map(len, chunks)) > SR // 2
    assert socks.hosts_asked() == {"station.test", "cdn.test"}


def test_radio_fails_closed_with_a_readable_reason(qapp, sites, monkeypatch):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    # Windows takes ~2 s to refuse a connection to a closed port, even on 127.0.0.1:
    # with FFmpeg slow to start on a busy machine, a 3 s watchdog said "the station
    # didn't answer" before the relay knew why. The answer still comes after ~2 s.
    monkeypatch.setattr("soundboard.radio.CONNECT_S", 12.0)
    net.configure(net.PROXY, f"socks5h://127.0.0.1:{dead}")
    try:
        sites.routes["/stream.wav"] = (wav_bytes(), "audio/wav")
        p, chunks, errors = play(qapp, sites.url("station", "/stream.wav"))
        p.stop()
    finally:
        net.configure(net.DIRECT)
    assert not chunks and errors and "Couldn't reach the proxy" in errors[0]
    assert sites.hits == []          # and never went direct


def test_a_stream_sent_into_the_home_network_is_refused(qapp, sites, socks, monkeypatch):
    monkeypatch.setattr("soundboard.radio.CONNECT_S", 12.0)   # the refusal says why first
    p, chunks, errors = play(qapp, f"http://127.0.0.2:{sites.port}/stream.wav")
    p.stop()
    assert not chunks and errors and "home network" in errors[0]
    assert sites.hits == [] and socks.asked == []


def test_a_playing_station_follows_a_change_of_proxy(qapp, sites, socks):
    sites.routes["/stream.wav"] = (wav_bytes(30.0), "audio/wav")
    p, chunks, errors = play(qapp, sites.url("station", "/stream.wav"))
    assert not errors and chunks
    other = Socks5({"station.test": ("127.0.0.1", sites.port)})
    try:
        chunks.clear()
        net.configure(net.PROXY, other.url())
        assert process_events(qapp, lambda: sum(map(len, chunks)) > SR // 2, timeout=20)
        assert other.hosts_asked() == {"station.test"}
    finally:
        p.stop()
        other.close()


def test_the_globe_page_cant_reach_the_network(qapp, app_dir, sites):
    from soundboard.radio import RadioDirectory
    from soundboard.ui.radiopanel import RadioTab
    from soundboard.library import Config
    from test_radio import api_station
    sites.routes["/json/stations/search"] = (json.dumps([api_station(1)]).encode(),
                                             "application/json")
    d = RadioDirectory(app_dir / "radio", bases=(f"http://127.0.0.1:{sites.port}",))
    cfg = Config()
    cfg.radio = {"map": "globe"}
    t = RadioTab(FakeEngine(), cfg, lambda: None, FakeMeter, directory=d, globe=True)
    t.start()
    assert process_events(qapp, lambda: t._globe_loaded, timeout=20)
    leak = f"http://127.0.0.1:{sites.port}/leak"
    t.view.page().runJavaScript(f"fetch('{leak}').catch(()=>0); new Image().src='{leak}2'")
    process_events(qapp, lambda: False, timeout=1.5)
    assert not any(p.startswith("/leak") for p in sites.paths())
    t.shutdown()
