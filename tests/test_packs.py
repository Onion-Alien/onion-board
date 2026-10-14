"""Free sound packs (soundboard.packs, the Free packs window): the list, the checked
download, its switch, and a pack landing on the board. No real network: net.urlopen
is a stand-in."""
import hashlib
import io
import json
import threading
import urllib.request
import zipfile

import pytest

from soundboard import backup, net, packs, updates
from soundboard.ui import packsdialog
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen
from test_radio import wav_bytes


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self):
        return "https://objects.githubusercontent.com/x"


def make_pack(names=("Door", "Dragon")) -> bytes:
    """A pack zip the way Export this category writes one (backup format)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        sounds = []
        for i, n in enumerate(names):
            folder = f"sounds/{i:03d} {n}"
            z.writestr(f"{folder}/sound.wav", wav_bytes())
            z.writestr(f"{folder}/sound.json", json.dumps({"name": n, "audio": "sound.wav",
                                                           "tags": ["Horror"]}))
            sounds.append(folder)
        z.writestr("onionboard.json", json.dumps({
            "format": "onionboard-board", "format_version": 1, "categories": ["Horror"],
            "sounds": sounds}))
    return buf.getvalue()


def entry(data: bytes, **kw) -> dict:
    d = {"id": "horror", "name": "Horror night", "description": "Creaks.",
         "url": f"{updates.DOWNLOADS}pack-horror/horror.zip",
         "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "sounds": 2}
    d.update(kw)
    return d


@pytest.fixture
def served(monkeypatch, app_dir):
    """net.urlopen serves `served.files[url]` and records the calls."""
    class Served:
        files: dict = {}
        calls: list = []

    def fake_urlopen(req, timeout=30, feature=None, direct=False):
        assert feature == packs.FEATURE
        net.check(feature)   # switched off: refused, as the real one is
        url = req.full_url
        Served.calls.append(url)
        if url not in Served.files:
            raise OSError("no such file")
        return Response(Served.files[url])
    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    # conftest keeps updates offline; the packs' downloads go through its fetch()
    monkeypatch.setattr(updates, "_open", lambda url, feature: fake_urlopen(
        urllib.request.Request(url), feature=feature))
    yield Served
    net.configure_features()


def test_the_built_in_list_has_our_packs_from_our_own_releases():
    built = packs.built_in()
    assert [(p.id, p.sounds) for p in built] == [("gm-starter", 67), ("esports", 51),
                                                 ("podcast", 51)]
    for p in built:
        assert p.url.startswith(updates.DOWNLOADS) and len(p.sha256) == 64


def test_the_repo_catalog_matches_what_the_app_ships():
    from pathlib import Path
    raw = json.loads((Path(__file__).parents[1] / "packs" / "catalog.json")
                     .read_text(encoding="utf-8"))
    assert [p.id for p in packs.parse(raw)] == [p.id for p in packs.built_in()]
    assert packs.parse(raw) == packs.built_in()


def test_parse_keeps_only_packs_from_our_releases_with_a_checksum():
    good = entry(b"x")
    bad = [entry(b"x", id="evil", url="https://evil.example/pack.zip"),
           entry(b"x", id="nosum", sha256="abc"),
           entry(b"x", id="Bad ID"),
           entry(b"x", id="huge", size=packs.MAX_SIZE + 1),
           {"id": "broken"},
           "not a dict",
           entry(b"x")]   # the same id twice: the first one stands
    assert [p.id for p in packs.parse({"packs": [good, *bad]})] == ["horror"]
    assert packs.parse({"packs": "nope"}) == [] and packs.parse(None) == []


def test_catalog_reads_the_list_online(served):
    data = make_pack()
    served.files[packs.CATALOG_URL] = json.dumps({"packs": [entry(data)]}).encode()
    assert [p.name for p in packs.catalog()] == ["Horror night"]
    served.files[packs.CATALOG_URL] = b'{"packs": []}'
    with pytest.raises(ValueError):
        packs.catalog()


def test_download_checks_the_sha256_and_keeps_nothing_wrong(served):
    data = make_pack()
    p, = packs.parse([entry(data)])
    served.files[p.url] = data[:-1] + b"!"   # swapped after it was checked
    with pytest.raises(updates.UpdateError, match="checksum"):
        packs.download(p)
    assert not p.downloaded() and not list(p.path.parent.glob("*"))
    served.files[p.url] = data
    assert packs.download(p) == p.path and p.downloaded()
    assert p.path.read_bytes() == data


def test_switched_off_nothing_is_fetched(served):
    data = make_pack()
    p, = packs.parse([entry(data)])
    served.files[p.url] = data
    net.configure_features(off=[packs.FEATURE])
    with pytest.raises(updates.UpdateError):
        packs.download(p)
    with pytest.raises(net.FeatureOff):
        packs.catalog()


def test_dialog_lists_downloads_and_hands_the_zip_over(qapp, served):
    data = make_pack()
    served.files[packs.CATALOG_URL] = json.dumps({"packs": [entry(data)]}).encode()
    served.files[entry(data)["url"]] = data
    got = []
    dlg = packsdialog.PacksDialog(got.append)
    try:
        assert process_events(qapp, lambda: [c.pack.id for c in dlg.cards] == ["horror"], 5)
        card = dlg.cards[0]
        assert card.btn.text() == "Add to my board"
        assert "2 sounds" in card.meta.text() and "CC0" in card.meta.text()
        dlg.add(card)
        assert process_events(qapp, lambda: got, 5)
        assert got[0].read_bytes() == data
        assert card.pack.downloaded()
    finally:
        dlg.done(0)


def test_dialog_keeps_the_built_in_list_when_offline(qapp, served):
    net.configure_features(offline=True)
    dlg = packsdialog.PacksDialog(lambda p: None)
    try:
        assert [c.pack.id for c in dlg.cards] == ["gm-starter", "esports", "podcast"]
        assert dlg.note.isVisibleTo(dlg) and dlg.note.text()
        assert served.calls == []
    finally:
        dlg.done(0)


def test_closing_the_dialog_before_the_list_arrives_is_quiet(qapp, monkeypatch):
    """Closed while a slow connection is still reading the list: the late result is
    dropped, nothing escapes the worker as a crash report."""
    from soundboard.ui.crashdialog import free_dialog
    escaped = []
    monkeypatch.setattr(threading, "excepthook", lambda a: escaped.append(a.exc_value))
    monkeypatch.setattr(net, "allowed", lambda feature: True)
    gate = threading.Event()

    def slow_catalog():
        gate.wait(5)
        return packs.built_in()
    monkeypatch.setattr(packs, "catalog", slow_catalog)
    dlg = packsdialog.PacksDialog(lambda p: None, None)
    t = next(t for t in threading.enumerate() if t.name == "pack-list")
    free_dialog(dlg)
    qapp.processEvents()
    gate.set()
    t.join(5)
    qapp.processEvents()
    assert not t.is_alive()
    assert escaped == []


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_a_downloaded_pack_lands_on_the_board(window, qapp, served):
    data = make_pack()
    p, = packs.parse([entry(data)])
    served.files[p.url] = data
    path = packs.download(p)
    before = len(window.cfg.sounds)
    window.import_files([str(path)])
    assert process_events(qapp, lambda: len(window.cfg.sounds) == before + 2, 10)
    added = window.cfg.sounds[before:]
    assert [m.name for m in added] == ["Door", "Dragon"]
    assert all("Horror" in m.tags for m in added) and "Horror" in window.cfg.categories
    # kept once: the download became the kept pack, not a second copy beside it
    assert [z.name for z in backup.packs_dir().glob("*.zip")] == [f"{added[0].pack}.zip"]


def _install(p: packs.Pack) -> str:
    """Add a downloaded pack the way the window's import does: keep it, then install."""
    pkg = backup.read(packs.download(p))
    pid = backup.keep_pack(pkg)
    res = backup.install(pkg, set())
    assert [m.name for m in res.sounds] == ["Door", "Dragon"] and not res.failed
    return pid


def test_a_free_pack_is_stored_once_and_removing_it_leaves_none(served):
    data = make_pack()
    p, = packs.parse([entry(data)])
    served.files[p.url] = data
    pid = _install(p)
    assert pid and [z.name for z in backup.packs_dir().glob("*.zip")] == [f"{pid}.zip"]
    assert backup.packs() == {pid: "horror"}
    # Add again: the kept pack is reused, not downloaded or stored again
    assert p.downloaded()
    served.calls.clear()
    assert _install(p) == pid and served.calls == []
    assert [z.name for z in backup.packs_dir().glob("*.zip")] == [f"{pid}.zip"]
    backup.forget_pack(pid)
    assert list(backup.packs_dir().glob("*.zip")) == [] and not p.downloaded()


def test_free_packs_an_older_version_stored_twice_are_cleaned_up(served):
    import shutil
    data, other = make_pack(), make_pack(("Ghost",))
    p, q = packs.parse([entry(data), entry(other, id="ghosts")])
    d = backup.packs_dir()
    d.mkdir(parents=True)
    # how an older version left them: the download, and keep_pack's copy of it
    p.path.write_bytes(data)
    pid = backup._pack_id(p.path)
    shutil.copyfile(p.path, d / f"{pid}.zip")
    (d / f"{pid}.json").write_text(json.dumps({"name": "horror"}), "utf-8")
    q.path.write_bytes(other)   # downloaded but never added: stays for Add again
    assert backup.drop_duplicate_packs() == 1
    assert sorted(z.name for z in d.glob("*.zip")) == sorted([f"{pid}.zip", "ghosts.zip"])
    assert backup.packs() == {pid: "horror"} and p.downloaded() and q.downloaded()
    assert backup.drop_duplicate_packs() == 0


def test_free_packs_hands_a_download_to_the_windows_import(window, monkeypatch, tmp_path):
    got = []
    monkeypatch.setattr(window, "import_files", got.append)

    def fake_exec(dlg):
        dlg._add(tmp_path / "horror.zip")   # as a finished download does
        return 0
    monkeypatch.setattr(packsdialog.PacksDialog, "exec", fake_exec)
    monkeypatch.setattr(net, "allowed", lambda f: False)   # no list fetch
    window.show_packs()
    assert got == [[str(tmp_path / "horror.zip")]]
