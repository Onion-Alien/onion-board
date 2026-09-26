"""Ad blocking: the request filter (adblock engine + interceptor mapping), list
caching, and the YouTube script that strips ads out of player responses, run in a
headless QtWebEngine page."""
import json

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript

from conftest import process_events
from soundboard import adblocker
from soundboard.adblocker import YOUTUBE_JS, AdBlocker

pytest.importorskip("adblock")


def test_builtin_list_blocks_ad_servers_but_not_videos(qapp, tmp_path):
    b = AdBlocker(tmp_path, update=False)
    yt = "https://www.youtube.com/watch?v=x"
    assert b.should_block("https://googleads.g.doubleclick.net/pagead/id", yt, "script")
    assert b.should_block("https://www.youtube.com/pagead/viewthroughconversion/1", yt, "image")
    assert b.should_block("https://www.youtube.com/api/stats/ads?ver=2", yt, "xmlhttprequest")
    assert not b.should_block("https://rr1---sn-x.googlevideo.com/videoplayback?id=1", yt,
                              "xmlhttprequest")
    assert not b.should_block("https://www.youtube.com/watch?v=x", yt, "subdocument")
    assert not b.should_block("data:text/plain,hi", yt, "image")


def test_lists_are_compiled_cached_and_reused_offline(qapp, tmp_path, monkeypatch):
    lst = tmp_path / "list.txt"
    lst.write_text("||ads.example.com^\nexample.org##.banner-ad\n")
    monkeypatch.setattr(adblocker, "FILTER_LISTS", (("test", lst.as_uri()),))
    b = AdBlocker(tmp_path / "store", update=False)
    b._load()
    assert (tmp_path / "store" / adblocker.ENGINE_FILE).exists()
    assert b.should_block("https://ads.example.com/x.js", "https://example.org/", "script")
    assert ".banner-ad" in b.hide_css("https://example.org/page")

    lst.unlink()   # offline now: the cached engine still works
    b2 = AdBlocker(tmp_path / "store", update=False)
    b2._load()
    assert b2.should_block("https://ads.example.com/x.js", "https://example.org/", "script")


PAGE = """<html><body><script>
window.a = JSON.parse('{"adPlacements":[1],"playerAds":[2],"streamingData":{"ok":1}}');
window.b = JSON.parse('[{"playerResponse":{"adSlots":[1],"videoDetails":{"id":"x"}}}]');
var ytInitialPlayerResponse = {"adPlacements": [1], "videoDetails": {"id": "y"}};
</script></body></html>"""


def run_js(qapp, page, js):
    out = []
    page.runJavaScript(js, QWebEngineScript.MainWorld, out.append)
    assert process_events(qapp, lambda: out, 5)
    return json.loads(out[0])


@pytest.mark.parametrize("host,pruned", [("www.youtube.com", True), ("example.com", False)])
def test_youtube_script_strips_ads_from_player_data(qapp, host, pruned):
    profile = QWebEngineProfile()
    page = QWebEnginePage(profile)
    sc = QWebEngineScript()
    sc.setSourceCode(YOUTUBE_JS)
    sc.setWorldId(QWebEngineScript.MainWorld)
    sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
    page.scripts().insert(sc)
    loaded = []
    page.loadFinished.connect(loaded.append)
    page.setHtml(PAGE, QUrl(f"https://{host}/watch"))
    assert process_events(qapp, lambda: loaded, 10)
    r = run_js(qapp, page, "JSON.stringify([a, b, window.ytInitialPlayerResponse])")
    a, b, ipr = r
    assert a["streamingData"] == {"ok": 1} and b[0]["playerResponse"]["videoDetails"]
    assert ipr["videoDetails"]["id"] == "y"
    assert ("adPlacements" not in a and "playerAds" not in a) == pruned
    assert ("adSlots" not in b[0]["playerResponse"]) == pruned
    assert ("adPlacements" not in ipr) == pruned
    del page
