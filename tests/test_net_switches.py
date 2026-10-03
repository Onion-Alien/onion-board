"""Settings > Privacy & security's switches: a feature switched off makes no
connection and no DNS lookup at all, in Direct and proxy mode, with a readable
message, while the other features keep working. Offline mode: nothing at all.

Python-side traffic is caught by fakeproxy.no_leaks (any connection or lookup off
this PC fails the test), the fake SOCKS proxy's log and the test site's hit log.
FFmpeg (radio) and Qt (the station directory, thumbnails) connect from C++, so in
Direct mode their proof is a test site on 127.0.0.2: not in no_proxy, so they can only
reach it through the relay, whose log (net.relay_seen) says what it let through."""
import http.server
import json
import threading
import types

import pytest

from conftest import process_events
from fakeproxy import Socks5, no_leaks
from soundboard import modules, net, updates
from soundboard.engine import SR
from test_net_leaks import REAL_GET, REAL_OPEN, NAMES, Sites
from test_radio import wav_bytes

MODES = (net.DIRECT, net.PROXY)


@pytest.fixture
def sites():
    s = Sites()
    yield s
    s.close()


@pytest.fixture
def socks(sites):
    p = Socks5({f"{n}.test": ("127.0.0.1", sites.port) for n in NAMES})
    yield p
    net.configure(net.DIRECT)
    p.close()


@pytest.fixture
def real_updates(monkeypatch):
    monkeypatch.setattr(updates, "_get", REAL_GET)
    monkeypatch.setattr(updates, "_open", REAL_OPEN)


def url(sites, mode, name, path):
    """The test site by a made-up name only the fake proxy resolves: in Direct mode a
    request that weren't refused would look it up on this PC, which no_leaks fails."""
    return sites.url(name, path)


def reachable(sites, mode, name, path):
    """The test site as a request that's allowed can reach it in this mode."""
    if mode == net.PROXY:
        return sites.url(name, path)
    return f"http://127.0.0.1:{sites.port}{path}"


# ---------------------------------------------------------------- each feature, off

def try_sounds_web(sites, mode, monkeypatch):
    from soundboard import ytdl
    monkeypatch.setattr(ytdl, "MYINSTANTS", url(sites, mode, "myinstants", "").rstrip("/"))
    with pytest.raises(ytdl.SwitchedOff, match="sounds online is switched off"):
        ytdl.search("bruh", source="myinstants")
    with pytest.raises(ytdl.SwitchedOff, match="sounds online is switched off"):
        ytdl.download_audio(url(sites, mode, "media", "/clip.wav"), auto_update=False)
    with pytest.raises(ytdl.SwitchedOff, match="sounds online is switched off"):
        ytdl.probe("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


def try_ytdlp_update(sites, mode, monkeypatch):
    from soundboard import ytdl
    with pytest.raises(ytdl.SwitchedOff, match="yt-dlp"):
        ytdl.update()
    with pytest.raises(ytdl.SwitchedOff, match="yt-dlp"):
        ytdl.reset()
    with pytest.raises(net.FeatureOff, match="yt-dlp"):
        ytdl._get(url(sites, mode, "pypi", "/pypi/yt-dlp/json"), 1000)
    ytdl.auto_update(True)            # the daily check skips itself, silently


def try_app_update(sites, mode, monkeypatch):
    cfg = types.SimpleNamespace(update_check=True, update_checked=0.0, update_skip="")
    assert updates.check(cfg) is None                    # the daily one: silently skipped
    with pytest.raises(net.FeatureOff, match="Onion Board updates"):
        updates.check(cfg, force=True)
    with pytest.raises(net.FeatureOff, match="Onion Board updates"):
        updates._open(url(sites, mode, "api.github", "/OnionBoardSetup.exe"))


def try_addons(sites, mode, monkeypatch):
    from soundboard import watchaddon
    monkeypatch.setattr(watchaddon, "API", url(sites, mode, "api.github", "/watch/latest"))
    monkeypatch.setattr(watchaddon, "installed", lambda dirs=None: types.SimpleNamespace(
        version="0.1.0"))
    assert watchaddon.check_update() is None             # skipped, silently
    with pytest.raises(net.FeatureOff, match="add-ons"):
        watchaddon.latest()
    lines = []
    info = modules.ModuleInfo(id="x", name="x", version="1", description="", kind="service",
                              path=sites_dir(), install_steps=[["{python}", "-c", "0"]])
    monkeypatch.setattr(modules.subprocess, "Popen", lambda *a, **k: pytest.fail("ran pip"))
    assert modules.install(info, lines.append) is False and "add-ons" in lines[-1]


def sites_dir():
    import tempfile
    from pathlib import Path
    return Path(tempfile.gettempdir())


def try_voices(sites, mode, monkeypatch):
    from soundboard.speech import translation, winvoices
    info = types.SimpleNamespace(language="xx", download={
        "url": url(sites, mode, "models", "/model.argosmodel"), "sha256": "0" * 64,
        "bytes": 18})
    with pytest.raises(RuntimeError, match="voices and speech models"):
        translation.download(info)
    monkeypatch.setattr(winvoices.subprocess, "run", lambda *a, **k: pytest.fail("ran it"))
    with pytest.raises(RuntimeError, match="voices and speech models"):
        winvoices.install("de")


def try_voice_servers(sites, mode, monkeypatch):
    from soundboard.speech import customvoices
    v = customvoices.CustomVoice(name="Far", url=url(sites, mode, "media", "/tts?t={text}"))
    with pytest.raises(RuntimeError, match="Custom voice servers are switched off"):
        v.synth("hi")


TRIES = {"sounds_web": try_sounds_web, "ytdlp_update": try_ytdlp_update,
         "app_update": try_app_update, "addons": try_addons, "voices": try_voices,
         "voice_servers": try_voice_servers}


def others_still_work(sites, mode, off: str):
    """A request for a feature that's still on gets through."""
    on = "app_update" if off != "app_update" else "addons"
    sites.routes["/still"] = (b'{"ok": true}', "application/json")
    assert REAL_GET(reachable(sites, mode, "api.github", "/still"), on) == {"ok": True}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("feature", sorted(TRIES))
def test_a_switched_off_feature_makes_no_connection(feature, mode, sites, socks,
                                                    real_updates, monkeypatch, app_dir):
    net.configure(mode, socks.url())
    net.configure_features([feature])
    net._relay_start().seen.clear()   # only what this test asks for
    with no_leaks(monkeypatch) as leaks:
        TRIES[feature](sites, mode, monkeypatch)
    assert leaks == [] and socks.asked == [] and sites.hits == []
    assert not [s for s in net.relay_seen() if s[2] == "ok"]
    with no_leaks(monkeypatch) as leaks:
        others_still_work(sites, mode, feature)
    assert leaks == [] and [p for p in sites.paths()] == ["/still"]


@pytest.mark.parametrize("mode", MODES)
def test_a_switched_off_site_is_refused_and_the_others_still_search(mode, sites, socks,
                                                                     monkeypatch, app_dir):
    from soundboard import ytdl
    net.configure(mode, socks.url())
    net.configure_features(["sounds_web.youtube", "sounds_web.other"])
    with no_leaks(monkeypatch) as leaks:
        for source in ("youtube", "ytmusic", "tiktok"):
            with pytest.raises(ytdl.SwitchedOff, match="from YouTube is switched off"):
                ytdl.search("what is love", source=source)
        with pytest.raises(ytdl.SwitchedOff, match="Other pasted links"):
            ytdl.probe("https://example.com/clip.mp3")
    assert leaks == [] and socks.asked == []
    page = ("<button onclick=\"play('/media/sounds/bruh.mp3', 'x')\"></button>"
            '<a href="/en/instant/bruh/" class="instant-link link-secondary">Bruh</a>')
    sites.routes["/en/search/"] = (page.encode(), "text/html")
    monkeypatch.setattr(ytdl, "MYINSTANTS", reachable(sites, mode, "myinstants", "").rstrip("/"))
    assert [h.title for h in ytdl.search("bruh", source="myinstants")] == ["Bruh"]


def test_setup_downloads_off_never_starts_the_cable_installer(monkeypatch):
    from soundboard.ui import setupwizard
    net.configure_features(["setup_downloads"])
    monkeypatch.setattr(setupwizard.subprocess, "Popen", lambda *a, **k: pytest.fail("ran"))
    told = []
    fake = types.SimpleNamespace(cable_status=types.SimpleNamespace(setText=told.append),
                                 _proc=None)
    setupwizard.SetupWizard.install_cable(fake)
    assert told and "vb-audio.com" in told[0]


# ---------------------------------------------------------------- C++: Qt and FFmpeg

class Local2:
    """A test site on 127.0.0.2: FFmpeg's no_proxy doesn't cover it, and Qt always
    goes through the relay, so they can only reach it through the relay."""

    def __init__(self):
        self.hits = []
        self.routes = {}
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_):
                pass

            def do_GET(self):
                srv.hits.append(self.path)
                body, kind = srv.routes.get(self.path.split("?")[0], (b"", ""))
                if not kind:
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

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.2", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path):
        return f"http://127.0.0.2:{self.port}{path}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def local2():
    s = Local2()
    yield s
    s.close()


def qt_get(qapp, feature, u):
    from PySide6.QtCore import QUrl
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
    nam = QNetworkAccessManager()
    net.apply_qt(nam, feature)
    reply = nam.get(QNetworkRequest(QUrl(u)))
    process_events(qapp, reply.isFinished, timeout=15)
    ok = reply.error() == QNetworkReply.NoError
    return ok, bytes(reply.readAll())


@pytest.mark.parametrize("feature", ["radio", "sounds_web"])
def test_qt_in_direct_mode_goes_nowhere_while_its_feature_is_off(feature, qapp, local2):
    net.configure(net.DIRECT)
    local2.routes["/x"] = (b"hello", "text/plain")
    net.configure_features([feature])
    ok, _ = qt_get(qapp, feature, local2.url("/x"))
    assert not ok and local2.hits == []
    assert (feature, "127.0.0.2", "off") in net.relay_seen()
    net.configure_features()
    ok, body = qt_get(qapp, feature, local2.url("/x"))     # on: through the relay
    assert ok and body == b"hello" and local2.hits == ["/x"]
    assert (feature, "127.0.0.2", "ok") in net.relay_seen()


def play(qapp, u, timeout=15):
    from soundboard.radio import RadioPlayer, Station
    p = RadioPlayer()
    chunks, errors = [], []
    p.audio.connect(chunks.append)
    p.error.connect(errors.append)
    p.play(Station(uuid="u", name="Test FM", url=u))
    process_events(qapp, lambda: sum(map(len, chunks)) > SR // 2 or errors, timeout=timeout)
    return p, chunks, errors


@pytest.mark.parametrize("mode", MODES)
def test_radio_off_plays_nothing_and_looks_nothing_up(mode, qapp, sites, socks, local2,
                                                      monkeypatch):
    net.configure(mode, socks.url())
    net.configure_features(["radio"])
    local2.routes["/s.wav"] = (wav_bytes(), "audio/wav")
    with no_leaks(monkeypatch) as leaks:
        p, chunks, errors = play(qapp, sites.url("station", "/s.wav"))
        p.stop()
    assert not chunks and errors and "Radio is switched off" in errors[0]
    assert leaks == [] and socks.asked == [] and sites.hits == []


def test_ffmpeg_in_direct_mode_only_reaches_a_station_through_the_relay(qapp, local2):
    """The C++ proof for the radio in Direct mode: with the switch on, FFmpeg's
    stream from 127.0.0.2 shows in the relay's log; off, a stream already playing
    stops and the relay lets nothing more through."""
    net.configure(net.DIRECT)
    local2.routes["/s.wav"] = (wav_bytes(30.0), "audio/wav")
    p, chunks, errors = play(qapp, local2.url("/s.wav"))
    try:
        assert not errors and chunks
        assert ("radio", "127.0.0.2", "ok") in net.relay_seen()
        hits = len(local2.hits)
        net.configure_features(["radio"])
        assert process_events(qapp, lambda: errors, timeout=10)
        assert "Radio was switched off" in errors[0] and p.station is None
        process_events(qapp, lambda: False, timeout=1.5)
        assert len(local2.hits) == hits                    # nothing reopened it
    finally:
        p.stop()


def test_the_radio_directory_asks_nobody_while_off(qapp, sites, tmp_path):
    from soundboard.radio import RadioDirectory
    net.configure_features(["radio"])
    d = RadioDirectory(tmp_path, bases=(f"http://radio.test:{sites.port}",))
    failed = []
    d.failed.connect(lambda kind, msg: failed.append(msg))
    d.load_globe()
    assert process_events(qapp, lambda: failed, timeout=10)
    assert "Radio is switched off" in failed[0] and sites.hits == []


# ---------------------------------------------------------------- Offline mode

def test_offline_mode_goes_nowhere_at_all(qapp, sites, socks, local2, real_updates,
                                          monkeypatch, app_dir):
    net.configure(net.PROXY, socks.url())
    net.configure_features([], offline=True)
    with no_leaks(monkeypatch) as leaks:
        for name, fn in TRIES.items():
            try:
                fn(sites, net.PROXY, monkeypatch)
            except AssertionError as e:   # the messages say Offline mode instead
                assert "Offline mode" in str(e) or "Regex" in str(e), name
            except Exception as e:  # noqa: BLE001 - each is refused, one way or another
                assert "Offline mode" in str(e), (name, e)
        p, chunks, errors = play(qapp, sites.url("station", "/s.wav"))
        p.stop()
        assert errors and "Offline mode" in errors[0]
    for feature in ("radio", "sounds_web"):
        ok, _ = qt_get(qapp, feature, local2.url("/x"))
        assert not ok
    with pytest.raises(net.FeatureOff, match="Offline"):
        net.test(socks.url(), ("radio.test", sites.port), timeout=5)
    assert leaks == [] and socks.asked == [] and sites.hits == [] and local2.hits == []
    assert not [s for s in net.relay_seen() if s[2] == "ok" and s[1] == "127.0.0.2"
                and len(local2.hits)]


# ---------------------------------------------------------------- child processes

def test_pip_gets_the_add_ons_login(monkeypatch, tmp_path):
    seen = {}

    class P:
        returncode = 0
        stdout = iter(())

        def __init__(self, argv, **kw):
            seen.update(kw.get("env") or {})

        def wait(self):
            return 0

        def poll(self):
            return 0
    monkeypatch.setattr(modules.subprocess, "Popen", P)
    info = modules.ModuleInfo(id="x", name="x", version="1", description="", kind="service",
                              path=tmp_path, install_steps=[["{python}", "-m", "pip"]])
    assert modules.install(info, lambda _l: None)
    assert seen["http_proxy"] == net.relay_url("addons")


@pytest.mark.parametrize("off", [False, True])
def test_the_live_voice_helper_gets_the_voices_login(off, monkeypatch, tmp_path):
    from soundboard.speech import live, service
    started = {}
    monkeypatch.setattr(service.ServiceHost, "start",
                        lambda self: started.update(self.env or {"none": "1"}))
    net.configure_features(["voices"] if off else [])
    ctl = live.SpeechController.__new__(live.SpeechController)
    ctl.host, ctl.chain = None, types.SimpleNamespace(tap=None, replace=False)
    ctl.mute_real_voice, ctl._ready = True, False
    info = modules.ModuleInfo(id="live-voice", name="x", version="1", description="",
                              kind="service", path=tmp_path, command=["helper"])
    ctl.start_live(info)
    assert started["http_proxy"] == net.relay_url("voices")
    assert (started.get("HF_HUB_OFFLINE") == "1") is off   # off: only the model it has


def test_saved_switches_survive_load_and_unknown_keys_are_kept(app_dir):
    from soundboard.library import Config
    cfg = Config()
    cfg.net_off = ["radio", "a-newer-versions-switch"]
    cfg.net_offline = True
    cfg.save()
    back = Config.load()
    assert back.net_off == ["radio", "a-newer-versions-switch"] and back.net_offline
    net.configure_from(back)
    assert net.offline() and not net.allowed("radio")
    _ = json   # (json is used by test_net_leaks' helpers this module imports)
