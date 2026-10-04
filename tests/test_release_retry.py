"""A gateway failure can be cached; a bounded retry still follows network policy."""
import io
import json
import urllib.error

import pytest

from soundboard import net, updates, watchaddon

REAL_GET = updates._get


@pytest.fixture(autouse=True)
def real_get(monkeypatch):
    monkeypatch.setattr(updates, "_get", REAL_GET)


def test_release_lookup_retries_a_gateway_error_with_the_same_feature(monkeypatch):
    calls = []

    def open_(req, timeout, feature):
        calls.append((req.full_url, feature, req.get_header("User-agent")))
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 504, "Gateway Timeout", {}, None)
        return io.BytesIO(json.dumps({"tag_name": "v1.2.3"}).encode())

    monkeypatch.setattr(net, "urlopen", open_)
    assert updates._get(watchaddon.API, "addons") == {"tag_name": "v1.2.3"}
    assert [(url, feature) for url, feature, _ua in calls] == [
        (watchaddon.API, "addons"), (watchaddon.API + "?retry=1", "addons")]
    assert all(ua == "OnionBoard (update check)" for _url, _feature, ua in calls)


@pytest.mark.parametrize("code,count", [(502, 2), (503, 2), (504, 2), (403, 1), (404, 1)])
def test_retry_is_bounded_and_does_not_retry_permanent_errors(monkeypatch, code, count):
    calls = []

    def open_(req, **kw):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, code, "Failure", {}, None)

    monkeypatch.setattr(net, "urlopen", open_)
    with pytest.raises(urllib.error.HTTPError):
        updates._get(watchaddon.API)
    assert len(calls) == count


def test_switching_addons_off_during_retry_prevents_another_connection(monkeypatch):
    calls = []
    real_open = net.urlopen

    def open_(req, **kw):
        if calls:
            return real_open(req, **kw)
        calls.append(req.full_url)
        net.configure_features(["addons"])
        raise urllib.error.HTTPError(req.full_url, 504, "Gateway Timeout", {}, None)

    monkeypatch.setattr(net, "urlopen", open_)
    monkeypatch.setattr(net.socket, "create_connection", lambda *a, **k: pytest.fail("connected"))
    with pytest.raises(net.FeatureOff):
        updates._get(watchaddon.API, "addons")
    assert calls == [watchaddon.API]


def test_cancel_during_a_gateway_error_stops_before_the_retry(monkeypatch):
    calls, cancel = [], []

    def open_(req, **kw):
        calls.append(req.full_url)
        cancel.append(True)   # the user presses Cancel while the first answer is awaited
        raise urllib.error.HTTPError(req.full_url, 504, "Gateway Timeout", {}, None)

    monkeypatch.setattr(net, "urlopen", open_)
    monkeypatch.setattr(watchaddon, "local_zip", lambda: None)
    with pytest.raises(updates.UpdateError, match="cancelled"):
        watchaddon.latest(lambda: bool(cancel))
    assert calls == [watchaddon.API]


def test_addon_gateway_error_does_not_blame_the_users_connection():
    err = urllib.error.HTTPError(watchaddon.API, 504, "Gateway Timeout", {}, None)
    assert "temporarily unavailable" in watchaddon.friendly(err)
    off = net.FeatureOff("Getting and updating add-ons is switched off.")
    assert watchaddon.friendly(off) == str(off)
