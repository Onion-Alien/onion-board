"""Getting Onion Watch (soundboard.watchaddon): its release is only trusted from its
own GitHub releases with a checksum, the download must match it, a local zip can
stand in for GitHub, and updates are only looked for once it's installed. No
network: GitHub's answers and the download are made up."""
import hashlib
import io
import zipfile

import pytest

from soundboard import updates, watchaddon
from test_triggers_module import make_module, zip_of

ZIP_URL = watchaddon.DOWNLOADS + "v0.2.0/OnionWatch-module.zip"


def module_zip(tmp_path, version="0.2.0", name="src") -> bytes:
    src = make_module(tmp_path / name / "onion-watch", package="fakewatch_dl", version=version)
    return zip_of(src, tmp_path / f"{name}.zip").read_bytes()


def release_json(data: bytes, **asset):
    a = {"name": "OnionWatch-module.zip", "browser_download_url": ZIP_URL,
         "digest": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data)}
    a.update(asset)
    return {"tag_name": "v0.2.0", "html_url": watchaddon.PAGE + "/releases/tag/v0.2.0",
            "body": "**Faster** matching.", "assets": [{"name": "OnionWatch.exe"}, a]}


class Response(io.BytesIO):
    def __init__(self, data, url=ZIP_URL):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url


@pytest.fixture(autouse=True)
def no_local_zip(monkeypatch):
    monkeypatch.delenv(watchaddon.LOCAL_ENV, raising=False)


def test_the_latest_release_is_asked_of_onion_watchs_own_repo(monkeypatch, tmp_path):
    data = module_zip(tmp_path)
    asked = []
    monkeypatch.setattr(updates, "_get", lambda url, *_f: asked.append(url) or release_json(data))
    offer = watchaddon.latest()
    assert asked == ["https://api.github.com/repos/Onion-Alien/onion-watch/releases/latest"]
    assert (offer.version, offer.url, offer.size) == ("0.2.0", ZIP_URL, len(data))
    assert offer.sha256 == hashlib.sha256(data).hexdigest() and offer.notes == "Faster matching."


@pytest.mark.parametrize("asset", [
    {"browser_download_url": "https://evil.example.com/OnionWatch-module.zip"},
    {"browser_download_url": "https://github.com/Onion-Alien/onion-board/releases/download/"
                             "v0.2.0/OnionWatch-module.zip"},     # not Onion Watch's own
    {"digest": None},
    {"name": "OnionWatch-module-old.zip"},
])
def test_a_release_without_a_zip_it_can_trust_offers_nothing(monkeypatch, tmp_path, asset):
    data = module_zip(tmp_path)
    monkeypatch.setattr(updates, "_get", lambda url, *_f: release_json(data, **asset))
    assert watchaddon.latest() is None


def test_the_release_page_link_stays_on_github(monkeypatch, tmp_path):
    data = release_json(module_zip(tmp_path))
    data["html_url"] = "https://evil.example.com/"
    monkeypatch.setattr(updates, "_get", lambda url, *_f: data)
    assert watchaddon.latest().page == watchaddon.RELEASES


def test_get_downloads_checks_and_installs_it(monkeypatch, tmp_path):
    data = module_zip(tmp_path)
    monkeypatch.setattr(updates, "_get", lambda url, *_f: release_json(data))
    opened = []
    monkeypatch.setattr(updates, "_open", lambda url, *_f: opened.append(url) or Response(data))
    offer = watchaddon.latest()
    path = watchaddon.fetch(offer)
    assert opened == [ZIP_URL] and path.parent == updates.UPDATES_DIR
    base = tmp_path / "modules"
    info = watchaddon.install(path, base)
    assert (info.id, info.version, info.kind) == ("onion-watch", "0.2.0", "triggers")
    assert not path.exists()                     # the download is tidied away
    assert watchaddon.installed([base]).version == "0.2.0"


def test_a_download_that_does_not_match_is_thrown_away(monkeypatch, tmp_path):
    data = module_zip(tmp_path)
    monkeypatch.setattr(updates, "_get", lambda url, *_f: release_json(data))
    monkeypatch.setattr(updates, "_open", lambda url, *_f: Response(data + b"tampered"))
    with pytest.raises(updates.UpdateError, match="checksum"):
        watchaddon.fetch(watchaddon.latest())
    assert not list(updates.UPDATES_DIR.glob("OnionWatch*"))


def test_a_local_zip_stands_in_for_github(monkeypatch, tmp_path):
    z = tmp_path / "OnionWatch-module.zip"
    z.write_bytes(module_zip(tmp_path, "0.3.0"))
    monkeypatch.setenv(watchaddon.LOCAL_ENV, f'"{z}"')
    monkeypatch.setattr(updates, "_get", lambda url, *_f: pytest.fail("asked GitHub"))
    monkeypatch.setattr(updates, "_open", lambda url, *_f: pytest.fail("downloaded"))
    offer = watchaddon.latest()
    assert offer.version == "0.3.0" and offer.local == z
    assert watchaddon.fetch(offer) == z
    info = watchaddon.install(z, tmp_path / "modules")
    assert info.version == "0.3.0" and z.exists()     # the developer's zip is kept


def test_updates_are_only_looked_for_once_it_is_installed(monkeypatch, tmp_path):
    base = tmp_path / "modules"
    asked = []
    new = module_zip(tmp_path, "0.2.0")
    monkeypatch.setattr(updates, "_get", lambda url, *_f: asked.append(url) or release_json(new))
    assert watchaddon.check_update([base]) is None and asked == []   # not installed: no request
    old = tmp_path / "old.zip"
    old.write_bytes(module_zip(tmp_path, "0.1.0", "old"))
    watchaddon.install(old, base)
    assert watchaddon.check_update([base]).version == "0.2.0"
    watchaddon.install(zip_of(tmp_path / "src" / "onion-watch", tmp_path / "same.zip"), base)
    assert watchaddon.check_update([base]) is None                   # up to date


def test_an_update_check_that_fails_is_quiet(monkeypatch, tmp_path):
    base = tmp_path / "modules"
    z = tmp_path / "a.zip"
    z.write_bytes(module_zip(tmp_path))
    watchaddon.install(z, base)

    def boom(url, *_feature):
        raise OSError("HTTP Error 404: Not Found")
    monkeypatch.setattr(updates, "_get", boom)
    assert watchaddon.check_update([base]) is None


def test_errors_read_as_sentences():
    assert "isn't available to download yet" in watchaddon.friendly(
        OSError("HTTP Error 404: Not Found"))
    assert "internet connection" in watchaddon.friendly(OSError("timed out"))
    assert watchaddon.friendly(updates.UpdateError("cancelled")) == "Cancelled"


def test_a_zip_with_nothing_readable_says_so(tmp_path):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("readme.txt", "hi")
    assert watchaddon._zip_version(bad) == "?"
