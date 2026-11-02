"""Free sound packs (soundboard.sounds.packs, the Free packs page): the list, the checked
download, its switch, and a pack landing on the board. No real network: net.urlopen
is a stand-in."""
import hashlib
import io
import json
import threading
import urllib.request
import zipfile

import pytest

from soundboard.core import backup, updates
from soundboard.sounds import packs
from soundboard.online import net
from soundboard.ui.sounds import packsdialog
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen
from test_radio import wav_bytes


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self):
        return "https://objects.githubusercontent.com/x"


def make_pack(names=("Door", "Dragon"), tags=None) -> bytes:
    """A pack zip the way Export this category writes one (backup format); `tags`, one
    category per sound (default: all "Horror")."""
    tags = tags or ["Horror"] * len(names)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        sounds = []
        for i, n in enumerate(names):
            folder = f"sounds/{i:03d} {n}"
            z.writestr(f"{folder}/sound.wav", wav_bytes())
            z.writestr(f"{folder}/sound.json", json.dumps({"name": n, "audio": "sound.wav",
                                                           "tags": [tags[i]]}))
            sounds.append(folder)
        z.writestr("onionboard.json", json.dumps({
            "format": "onionboard-board", "format_version": 1,
            "categories": list(dict.fromkeys(tags)),
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
    monkeypatch.setattr(packs, "_listed", {})   # (no pack names left from another test's list)
    # conftest keeps updates offline; the packs' downloads go through its fetch()
    monkeypatch.setattr(updates, "_open", lambda url, feature: fake_urlopen(
        urllib.request.Request(url), feature=feature))
    yield Served
    net.configure_features()


def test_the_built_in_list_has_our_packs_from_our_own_releases():
    built = packs.built_in()
    assert [(p.id, p.sounds) for p in built] == [("memes", 87), ("gaming", 69),
                                                 ("tv-movies", 71), ("anime", 38),
                                                 ("sports", 40), ("streamer", 57),
                                                 ("esports", 51), ("general", 483),
                                                 ("podcast", 51), ("halloween", 49),
                                                 ("gm-starter", 67)]
    for p in built:
        assert p.links or (p.url.startswith(updates.DOWNLOADS) and len(p.sha256) == 64)


def test_the_links_packs_are_all_myinstants_links():
    built = {p.id: p for p in packs.built_in()}
    seen = set()
    for pid in ("memes", "gaming", "tv-movies", "anime", "sports"):
        p = built[pid]
        assert p.links and not p.url
        assert len({k.url for k in p.links}) == len({k.name for k in p.links}) == p.sounds
        assert all(k.category for k in p.links)
        assert set(p.categories) == {k.category for k in p.links}
        # short file names: a long one went past Windows' path limit in the temp folder
        assert max(len(k.url.rsplit("/", 1)[1]) for k in p.links) <= 60
        # no sound in two packs: adding both doesn't give it twice
        assert not seen & {k.url for k in p.links}
        seen |= {k.url for k in p.links}
    assert built["memes"].sounds == 87


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


def test_a_damaged_pack_zip_with_a_matching_checksum_isnt_kept(served):
    """A broken upload whose checksum the list matched was kept: its import failed,
    and the card then said "Add again" though nothing was added."""
    bad = b"PK" + bytes(900)
    p, = packs.parse([entry(bad)])
    served.files[p.url] = bad
    with pytest.raises(updates.UpdateError, match="damaged"):
        packs.download(p)
    assert not p.downloaded() and not p.path.exists()


def test_switched_off_nothing_is_fetched(served):
    data = make_pack()
    p, = packs.parse([entry(data)])
    served.files[p.url] = data
    net.configure_features(off=[packs.FEATURE])
    with pytest.raises(updates.UpdateError):
        packs.download(p)
    with pytest.raises(net.FeatureOff):
        packs.catalog()


def test_dialog_keeps_the_built_in_list_when_offline(qapp, served):
    net.configure_features(offline=True)
    dlg = packsdialog.PacksDialog(lambda p: None)
    try:
        assert process_events(qapp, lambda: len(dlg.cards) == 11, 5)
        assert [c.pack.id for c in dlg.cards] == ["memes", "gaming", "tv-movies", "anime",
                                                "sports", "streamer", "esports", "general",
                                                "podcast", "halloween", "gm-starter"]
        assert dlg.note.isVisibleTo(dlg) and dlg.note.text()
        assert served.calls == []
    finally:
        dlg.done(0)


def test_closing_the_dialog_before_the_list_arrives_is_quiet(qapp, monkeypatch):
    """Closed while a slow connection is still reading the list: the late result is
    dropped, nothing escapes the worker as a crash report."""
    from soundboard.ui.kit.crashdialog import free_dialog
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
    window.impctl.import_files([str(path)])
    assert process_events(qapp, lambda: len(window.cfg.sounds) == before + 2, 10)
    added = window.cfg.sounds[before:]
    assert [m.name for m in added] == ["Door", "Dragon"]
    assert all("Horror" in m.tags for m in added) and "Horror" in window.cfg.categories
    # kept once: the download became the kept pack, not a second copy beside it
    assert [z.name for z in backup.packs_dir().glob("*.zip")] == [f"{added[0].pack}.zip"]



def test_a_pack_with_categories_is_one_tab_named_after_it(window, qapp, served):
    """The Streamer pack once landed in a "streamer" tab plus an empty tab for each of
    its categories: its category list was added as tabs after its sounds were grouped."""
    data = make_pack(("Hype", "Bonk"), tags=["Alerts", "Fails"])
    p, = packs.parse([entry(data, id="streamer", name="Streamer pack")])
    served.files[p.url] = data
    tabs = list(window.cfg.categories)
    before = len(window.cfg.sounds)
    window.impctl.import_files([str(packs.download(p))])
    assert process_events(qapp, lambda: len(window.cfg.sounds) == before + 2, 10)
    assert window.cfg.categories == tabs + ["Streamer"]
    assert window.cfg.subcategories["Streamer"] == ["Alerts", "Fails"]
    assert [m.tags for m in window.cfg.sounds[before:]] == [
        ["Streamer", "Streamer / Alerts"], ["Streamer", "Streamer / Fails"]]
    assert list(backup.packs().values()) == ["Streamer pack"]


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


# ---------------------------------------------------------------- hear it first

def png_bytes() -> bytes:
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QImage
    img = QImage(8, 8, QImage.Format.Format_ARGB32)
    img.fill(QColor("#b71c1c"))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data().data())


def make_preview(names=("Door", "Dragon")) -> bytes:
    """A pack's preview: a few of its sounds with their pictures (backup format)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        folders = []
        for i, n in enumerate(names):
            folder = f"sounds/{i:03d} {n}"
            z.writestr(f"{folder}/sound.wav", wav_bytes())
            z.writestr(f"{folder}/picture.png", png_bytes())
            z.writestr(f"{folder}/sound.json", json.dumps(
                {"name": n, "audio": "sound.wav", "picture": "picture.png"}))
            folders.append(folder)
        z.writestr("onionboard.json", json.dumps({
            "format": "onionboard-board", "format_version": 1, "sounds": folders}))
    return buf.getvalue()


def with_preview(data: bytes, preview: bytes, **kw) -> dict:
    return entry(data, preview={"url": f"{updates.DOWNLOADS}pack-horror/horror-preview.zip",
                                "sha256": hashlib.sha256(preview).hexdigest(),
                                "size": len(preview)}, **kw)


def test_our_packs_each_have_a_preview_on_their_own_release():
    for p in packs.built_in():
        if p.links:   # its preview is its first links
            continue
        assert p.preview_url.startswith(p.url.rsplit("/", 1)[0] + "/")
        assert len(p.preview_sha256) == 64 and 0 < p.preview_size <= packs.PREVIEW_MAX


def test_a_bad_preview_is_dropped_but_its_pack_stays():
    good = with_preview(b"x", b"y")
    p, = packs.parse([good])
    assert p.preview_url.endswith("horror-preview.zip") and p.preview_size == 1
    for bad in ({"url": "https://evil.example/p.zip", "sha256": "0" * 64},
                {"url": good["preview"]["url"], "sha256": "abc"},
                {**good["preview"], "size": packs.PREVIEW_MAX + 1},
                "not a dict", None):
        p, = packs.parse([entry(b"x", preview=bad)])
        assert p.preview_url == "" and p.id == "horror"


def test_samples_are_fetched_once_checked_and_unpacked(served):
    preview = make_preview(("Door creak", "Dragon"))
    p, = packs.parse([with_preview(b"x", preview)])
    served.files[p.preview_url] = preview[:-1] + b"!"   # swapped after it was checked
    with pytest.raises(updates.UpdateError, match="checksum"):
        packs.samples(p)
    served.files[p.preview_url] = preview
    found = packs.samples(p)
    assert [s.name for s in found] == ["Door creak", "Dragon"]
    assert all(s.audio.is_file() and s.picture.startswith(b"\x89PNG") for s in found)
    calls = len(served.calls)
    assert [s.name for s in packs.samples(p)] == ["Door creak", "Dragon"]
    assert len(served.calls) == calls   # kept: not fetched again
    assert packs.samples(packs.parse([entry(b"x")])[0]) == []   # a pack with none


def test_two_fetches_of_one_preview_at_once_both_get_its_samples(served):
    preview = make_preview(("Door", "Dragon"))
    p, = packs.parse([with_preview(b"x", preview)])
    served.files[p.preview_url] = preview
    got = []
    ts = [threading.Thread(target=lambda: got.append(packs.samples(p))) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert len(got) == 4 and all([s.name for s in g] == ["Door", "Dragon"] for g in got)


def test_the_online_list_keeps_the_cards_of_packs_that_didnt_change(qapp):
    """The online list arriving (about a second after the window opens) remade every
    card: ~250 ms of Qt work in one go, and the sound playing skipped. Unchanged packs
    keep their cards now; only a new or changed pack gets a new one."""
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False)
    try:
        assert process_events(qapp, lambda: len(dlg.cards) == 11, 5)
        before = list(dlg.cards)
        dlg._show(packs.built_in(), "")
        assert dlg.cards == before and all(a is b for a, b in zip(dlg.cards, before))
        changed = packs.built_in()
        changed[1].description = "Something new"
        dlg._show(changed, "")
        assert process_events(qapp, lambda: len(dlg.cards) == 11, 5)
        assert [c.pack for c in dlg.cards] == changed
        assert dlg.cards[1] is not before[1]
        assert all(dlg.cards[i] is before[i] for i in (0, *range(2, 11)))
        assert [dlg.list.itemAt(i).widget() for i in range(len(changed))] == dlg.cards
    finally:
        dlg.done(0)


def test_a_pack_card_never_shows_a_window_of_its_own(qapp):
    """Its samples row was shown before it was put in the card: for a moment a window of
    its own, made and pulled back in (~30 ms a card the audio threads waited on)."""
    from PySide6.QtCore import QEvent, QObject

    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow():
                shown.append(type(obj).__name__)
            return False
    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        cards = [packsdialog.PackCard(p) for p in packs.built_in()]
    finally:
        qapp.removeEventFilter(spy)
    assert any(c.pack.preview_url for c in cards)
    assert shown == []


def test_add_with_offline_mode_on_answers_the_press(qapp, served, monkeypatch):
    toasts = []
    monkeypatch.setattr(packsdialog.busy, "toast", lambda _w, text, *a, **k: toasts.append(text))
    net.configure_features(offline=True)
    dlg = packsdialog.PacksDialog(lambda p: None)
    try:
        dlg.add(dlg.cards[0])
        assert toasts and "Offline mode" in toasts[0]
        assert dlg.cards[0].btn.text() == "Add" and served.calls == []
    finally:
        dlg.done(0)


def test_dialog_lists_downloads_and_hands_the_zip_over(qapp, served):
    data = make_pack()
    served.files[packs.CATALOG_URL] = json.dumps({"packs": [entry(data)]}).encode()
    served.files[entry(data)["url"]] = data
    got = []
    dlg = packsdialog.PacksDialog(got.append)
    try:
        assert process_events(qapp, lambda: [c.pack.id for c in dlg.cards] == ["horror"], 5)
        card = dlg.cards[0]
        assert card.btn.text() == "Add" and card.btn_preview.text() == "Preview"
        assert "2 sounds" in card.meta.text()
        dlg.add(card)
        assert process_events(qapp, lambda: got, 5)
        assert got[0].read_bytes() == data
        assert card.pack.downloaded() and card.btn.text() in ("✓ Added", "Add again")
    finally:
        dlg.done(0)


def test_free_packs_is_a_page_on_the_sounds_tab(window, qapp, monkeypatch, tmp_path):
    """Free packs takes the tabs' place (as Settings does) with the Sounds tab lit: a
    finished download goes to the window's own import, and Back, a tab on the rail or
    Settings go back to the board."""
    got = []
    monkeypatch.setattr(window.impctl, "import_files", got.append)
    monkeypatch.setattr(net, "allowed", lambda f: False)   # no list fetch
    window.tabs.setCurrentWidget(window.setup_page)
    dlg = window.impctl.show_packs()
    assert window._content.currentWidget() is dlg and window.impctl.packs_open()
    assert window.tabs.currentWidget() is window.sounds_page
    dlg._add(tmp_path / "horror.zip")   # as a finished download does
    assert got == [[str(tmp_path / "horror.zip")]]
    dlg.btn_done.click()
    assert process_events(qapp, lambda: not window.impctl.packs_open(), 5)
    assert window._content.currentWidget() is window._tabs_area
    window.impctl.show_packs()
    window.tabs.setCurrentWidget(window.radio_page)   # a tab picked on the rail
    assert process_events(qapp, lambda: not window.impctl.packs_open(), 5)
    window.impctl.show_packs()
    window.setctl.open_settings("audio")
    assert process_events(qapp, lambda: not window.impctl.packs_open(), 5)
    assert window.setctl.settings_open()
    window.setctl.close_settings()


# ---------------------------------------------------------------- search and filters

def test_search_and_chips_filter_the_cards(qapp, monkeypatch):
    dlg = packsdialog.PacksDialog(lambda p: None, fetch_list=False)
    try:
        dlg._show(packs.parse([links_entry(id="test-links")]) + packs.built_in(), "")
        assert process_events(qapp, lambda: len(dlg.cards) == 12, 5)
        shown = lambda: [c.pack.id for c in dlg.cards if not c.isHidden()]  # noqa: E731
        assert list(dlg.chip_btns) == ["", "Memes", "Gaming", "Streaming", "Anime",
                                       "Everyday", "Music", "Podcast", "Spooky", "Sports",
                                       "Tabletop", "TV & movies", packsdialog.MINE]
        # a lone & would be a shortcut marker: the chip read "TV _movies"
        assert dlg.chip_btns["TV & movies"].text() == "TV && movies"
        dlg.search.setText("bruh")   # a links pack's sound names are searched too
        assert shown() == ["test-links", "memes", "general"]
        dlg.search.setText("")
        dlg.set_filter("Streaming")
        assert shown() == ["streamer", "esports"]
        dlg.search.setText("arena crowd")   # every word, anywhere in the pack
        assert shown() == ["esports"]
        dlg.search.setText("zzzz")
        assert dlg.views.currentWidget() is dlg.empty and "zzzz" in dlg.empty_title.text()
        dlg.btn_clear.click()
        assert dlg.search.text() == "" and dlg._filter == packsdialog.ALL
        assert dlg.views.currentIndex() == 0 and len(shown()) == 12
        dlg.set_filter(packsdialog.MINE)   # nothing added yet
        assert shown() == [] and dlg.views.currentWidget() is dlg.empty
    finally:
        dlg.done(0)


# ---------------------------------------------------------------- links packs

def links_entry(n: int = 3, **kw) -> dict:
    d = {"id": "memes", "name": "Meme sounds", "tags": ["Memes"],
         "description": "Meme sounds.",
         "links": [{"name": ["Vine boom", "Bruh", "Oh no"][i % 3] + ("" if i < 3 else f" {i}"),
                    "category": "Memes",
                    "url": f"https://www.myinstants.com/media/sounds/s{i}.mp3"}
                   for i in range(n)]}
    d.update(kw)
    return d


def test_a_links_pack_keeps_only_myinstants_mp3s():
    mi = "https://www.myinstants.com/media/sounds/"
    good = {"name": "Bruh", "url": mi + "bruh.mp3", "category": "Memes"}
    bad = [{"name": "Evil", "url": "https://evil.example/media/sounds/x.mp3"},
           {"name": "Page", "url": "https://www.myinstants.com/en/instant/bruh/"},
           {"name": "Query", "url": mi + "x.mp3?a=1"},
           {"name": "Up", "url": mi + "..%2f..%2fx.mp3"},
           {"name": "Deep", "url": mi + "a/b.mp3"},
           {"name": "Stream", "url": mi + "x.mp3:evil"},
           {"name": "", "url": mi + "noname.mp3"},
           {"url": mi + "missing-name.mp3"}, "not a dict",
           good]   # twice: kept once
    p, = packs.parse([links_entry(0, links=[good, *bad])])
    assert [(k.name, k.url) for k in p.links] == [("Bruh", mi + "bruh.mp3")]
    assert p.sounds == 1 and p.categories == ["Memes"] and p.url == "" and p.sha256 == ""
    # no links that count and no zip: not a pack
    assert packs.parse([links_entry(0, links=bad[:3])]) == []


def test_older_versions_skip_a_links_pack():
    """An older version reads "url" and "sha256" straight off each entry: a links pack
    has neither, so it was left out there (not shown broken)."""
    raw = links_entry()
    assert "url" not in raw and "sha256" not in raw


@pytest.fixture
def myinstants(monkeypatch):
    """ytdl.download_audio stands in for Myinstants: links whose leaf is in `gone`
    fail, the rest come back as a small MP3. Records every link fetched."""
    from soundboard.online import ytdl

    class Site:
        gone: set = set()
        fetched: list = []
        slept: list = []   # every wait, on a fake clock: the tests don't really wait
        started: list = []   # the clock at each fetch
        now = 1000.0

    class Clock:
        @staticmethod
        def monotonic():
            return Site.now

        @staticmethod
        def sleep(s):
            Site.slept.append(s)
            Site.now += s

    def fake(url, dest=None, progress=None, auto_update=True, direct=False, video=False,
             thumbnail=True):
        Site.fetched.append(url)
        Site.started.append(Site.now)
        leaf = url.rsplit("/", 1)[-1]
        if leaf in Site.gone:
            raise ytdl.DownloadError("Not found")
        path = dest / leaf
        path.write_bytes(b"ID3" + bytes(200))
        return path, leaf
    monkeypatch.setattr(ytdl, "download_audio", fake)
    monkeypatch.setattr(packs, "time", Clock)
    yield Site
    Site.gone.clear()
    Site.fetched.clear()
    Site.slept.clear()
    Site.started.clear()


def test_a_links_pack_is_fetched_into_a_pack_zip_and_gone_links_are_skipped(
        app_dir, myinstants):
    p, = packs.parse([links_entry(4)])
    myinstants.gone = {"s1.mp3"}
    seen = []
    path, skipped, later = packs.download_links(p, lambda done, total: seen.append((done, total)))
    assert path == p.path and skipped == 1 and later == 0   # gone: not asked for again
    assert seen[-1] == (4, 4) and len(seen) == 4
    pkg = backup.read(path)
    assert [ps.entry["name"] for ps in pkg.sounds] == ["Vine boom", "Oh no", "Vine boom 3"]
    assert all(ps.entry["tags"] == ["Memes"] for ps in pkg.sounds)
    assert not list(path.parent.glob("*.part"))


def test_a_links_pack_with_no_link_left_says_so_and_keeps_nothing(app_dir, myinstants):
    p, = packs.parse([links_entry(2)])
    myinstants.gone = {"s0.mp3", "s1.mp3"}
    with pytest.raises(updates.UpdateError, match="Not found"):
        packs.download_links(p)
    assert not p.path.exists() and not p.downloaded()



def failing(monkeypatch, myinstants, errors: dict):
    """download_audio raising, for each leaf, the errors listed (one per try, then fine),
    each from `cause` like the real one (its HTTP status kept on __cause__)."""
    from soundboard.online import ytdl
    real = ytdl.download_audio

    def fake(url, dest=None, **kw):
        todo = errors.get(url.rsplit("/", 1)[-1])
        if todo:
            cause = todo.pop(0)
            myinstants.fetched.append(url)
            raise ytdl.DownloadError(f"Download failed ({cause})") from cause
        return real(url, dest, **kw)
    monkeypatch.setattr(ytdl, "download_audio", fake)


def http(code: int, retry_after: str | None = None):
    import email.message
    import urllib.error
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://www.myinstants.com/x.mp3", code, "x", h, None)


def test_a_links_packs_downloads_are_spaced_out(app_dir, myinstants):
    p, = packs.parse([links_entry(6)])
    packs.download_links(p)
    assert len(myinstants.fetched) == 6
    # six starts, each at least LINK_GAP after the one before, whichever worker took it
    at = sorted(myinstants.started)
    assert all(b - a >= packs.LINK_GAP - 1e-9 for a, b in zip(at, at[1:]))
    assert packs.LINK_WORKERS <= 2


def test_a_link_that_failed_for_now_is_tried_again_each_wait_longer(
        app_dir, myinstants, monkeypatch):
    import urllib.error
    p, = packs.parse([links_entry(1)])
    failing(monkeypatch, myinstants, {"s0.mp3": [urllib.error.URLError("reset"),
                                                 http(503), TimeoutError("slow")]})
    path, skipped, later = packs.download_links(p)
    assert skipped == 0 and len(myinstants.fetched) == 4
    # 2, 5 and 15 s (waited in short steps, so Cancel works meanwhile)
    assert sum(myinstants.slept) == pytest.approx(sum(packs.LINK_RETRY_WAITS))


def test_a_link_that_failed_for_now_gets_one_more_round_at_the_end(app_dir, myinstants,
                                                                   monkeypatch):
    """Nobody presses Add again for a few missing sounds: after the rest, the links that
    failed for now are tried once more, by themselves."""
    import urllib.error
    p, = packs.parse([links_entry(2)])
    tries = len(packs.LINK_RETRY_WAITS) + 1
    failing(monkeypatch, myinstants, {"s0.mp3": [urllib.error.URLError("reset")] * tries})
    path, skipped, later = packs.download_links(p)
    assert skipped == 0
    s0 = "https://www.myinstants.com/media/sounds/s0.mp3"
    assert myinstants.fetched.count(s0) == tries + 1 and myinstants.fetched[-1] == s0
    assert packs.LINK_LAST_ROUND <= sum(myinstants.slept)


def test_a_link_that_keeps_failing_is_skipped_after_both_rounds(app_dir, myinstants,
                                                                monkeypatch):
    import urllib.error
    p, = packs.parse([links_entry(2)])
    tries = len(packs.LINK_RETRY_WAITS) + 1
    failing(monkeypatch, myinstants,
            {"s0.mp3": [urllib.error.URLError("reset")] * (2 * tries)})
    path, skipped, later = packs.download_links(p)
    assert skipped == 1 and later == 1   # failed for now: asked for again much later
    assert myinstants.fetched.count("https://www.myinstants.com/media/sounds/s0.mp3") == 8


def test_a_pack_that_cant_reach_myinstants_is_tried_again_later(app_dir, myinstants,
                                                                 monkeypatch):
    """No connection all through both rounds: it gives up with TryLater (the window asks
    again LINK_TRY_LATER after), keeps nothing, and a later try with the site back
    fetches it even though nothing's kept."""
    import urllib.error
    p, = packs.parse([links_entry(2)])
    tries = 2 * (len(packs.LINK_RETRY_WAITS) + 1)
    failing(monkeypatch, myinstants, {f"s{i}.mp3": [urllib.error.URLError("no route")] * tries
                                      for i in range(2)})
    with pytest.raises(packs.TryLater, match="tries again by itself in 2 hours"):
        packs.download_links(p)
    assert not p.downloaded()
    path, skipped, later = packs.download_links(p, again=True)   # the site's back
    assert path == p.path and skipped == later == 0


def test_a_kept_links_pack_is_fetched_again_only_when_asked(app_dir, myinstants,
                                                             monkeypatch):
    p, = packs.parse([links_entry(2)])
    kept = app_dir / "kept.zip"
    kept.write_bytes(b"x")
    monkeypatch.setattr(packs.backup, "kept_free_pack", lambda pid: kept)
    assert packs.download_links(p) == (kept, 0, 0) and not myinstants.fetched
    path, skipped, later = packs.download_links(p, again=True)   # its missing sounds
    assert path == p.path and len(myinstants.fetched) == 2


def test_a_gone_link_is_not_asked_for_again(app_dir, myinstants, monkeypatch):
    p, = packs.parse([links_entry(2)])
    failing(monkeypatch, myinstants, {"s0.mp3": [http(404)]})
    path, skipped, later = packs.download_links(p)
    assert skipped == 1 and len(myinstants.fetched) == 2
    assert sum(myinstants.slept) == pytest.approx(packs.LINK_GAP)   # no retry wait


def test_too_many_requests_holds_every_link_as_long_as_the_site_asks(
        app_dir, myinstants, monkeypatch):
    p, = packs.parse([links_entry(1)])
    failing(monkeypatch, myinstants, {"s0.mp3": [http(429, "40")]})
    packs.download_links(p)
    assert len(myinstants.fetched) == 2 and sum(myinstants.slept) == pytest.approx(40)
    # a silly Retry-After is capped, a date or nonsense falls back to our own waits
    assert packs._try_again(DownloadErrorFrom(http(429, "99999"))) == (packs.LINK_MAX_WAIT,
                                                                       True)
    assert packs._try_again(DownloadErrorFrom(http(429, "Wed, 21 Oct"))) == (0.0, True)


def test_too_many_requests_never_makes_a_link_give_up(app_dir, myinstants, monkeypatch):
    """Each "too many requests" waits longer (15 s, 30 s, 1, 2, then 5 minutes) and the
    link is asked for again: more times than its own tries, and it comes."""
    monkeypatch.setattr(packs, "LINK_WORKERS", 1)
    p, = packs.parse([links_entry(2)])
    failing(monkeypatch, myinstants, {"s0.mp3": [http(429)] * 6})
    path, skipped, later = packs.download_links(p)
    assert skipped == 0
    assert myinstants.fetched.count("https://www.myinstants.com/media/sounds/s0.mp3") == 7
    held = sum(packs.LINK_BUSY_WAITS) + packs.LINK_BUSY_WAITS[-1]
    assert sum(myinstants.slept) == pytest.approx(held, abs=2)


def test_a_link_coming_through_starts_the_waits_over(app_dir, myinstants, monkeypatch):
    monkeypatch.setattr(packs, "LINK_WORKERS", 1)   # one at a time: the waits add up
    p, = packs.parse([links_entry(2)])
    failing(monkeypatch, myinstants, {"s0.mp3": [http(429)] * 3, "s1.mp3": [http(429)]})
    packs.download_links(p)
    # s0: 15 + 30 + 60, then it came; s1's one "too many" waits 15 s again, not 120
    assert sum(myinstants.slept) == pytest.approx(15 + 30 + 60 + 15, abs=2)


def DownloadErrorFrom(cause):
    from soundboard.online import ytdl
    try:
        raise ytdl.DownloadError("Download failed") from cause
    except ytdl.DownloadError as e:
        return e


def test_only_half_an_hour_of_too_many_requests_stops_it(app_dir, myinstants,
                                                         monkeypatch):
    """A site still saying "too many requests" after LINK_BUSY_LIMIT is blocking us:
    then (and only then) the links stop being asked for."""
    monkeypatch.setattr(packs, "LINK_WORKERS", 1)
    p, = packs.parse([links_entry(3)])
    failing(monkeypatch, myinstants, {f"s{i}.mp3": [http(429)] * 1000 for i in range(3)})
    with pytest.raises(updates.UpdateError):
        packs.download_links(p)
    assert packs.LINK_BUSY_LIMIT <= sum(myinstants.slept)
    most = packs.LINK_BUSY_LIMIT + 2 * packs.LINK_MAX_WAIT + packs.LINK_LAST_ROUND + 60
    assert sum(myinstants.slept) <= most
    assert len(myinstants.fetched) < 60


def test_switched_off_or_turned_away_over_tor_isnt_tried_again():
    from soundboard.online import ytsites
    assert packs._try_again(ytsites.SwitchedOff("off")) is None
    assert packs._try_again(ytsites.TorBlocked("no")) is None
    assert packs._try_again(ytsites.DownloadError("That isn't a Myinstants sound link.")) is None

def test_a_links_pack_lands_on_the_board_as_one_pack(window, qapp, myinstants):
    p, = packs.parse([links_entry(3)])
    path = packs.download(p)
    before = len(window.cfg.sounds)
    window.impctl.import_files([str(path)])
    assert process_events(qapp, lambda: len(window.cfg.sounds) == before + 3, 10)
    added = window.cfg.sounds[before:]
    assert [m.name for m in added] == ["Vine boom", "Bruh", "Oh no"]
    assert len({m.pack for m in added}) == 1 and added[0].pack
    assert "Memes" in window.cfg.categories


def test_a_links_packs_samples_are_its_first_links_fetched_once(app_dir, myinstants):
    p, = packs.parse([links_entry(packs.SAMPLES + 3)])
    found = packs.samples(p)
    assert [s.name for s in found] == [k.name for k in p.links[:packs.SAMPLES]]
    assert all(s.audio.is_file() and s.picture == b"" for s in found)
    assert len(myinstants.fetched) == packs.SAMPLES
    assert [s.name for s in packs.samples(p)] == [s.name for s in found]
    assert len(myinstants.fetched) == packs.SAMPLES   # kept: not fetched again


def test_the_page_shows_a_links_packs_progress_and_skipped_count(qapp, app_dir, myinstants,
                                                               monkeypatch):
    toasts, got = [], []
    monkeypatch.setattr(packsdialog.busy, "toast", lambda _w, text, *a, **k: toasts.append(text))
    monkeypatch.setattr(net, "allowed", lambda f: True)
    myinstants.gone = {"s2.mp3"}
    dlg = packsdialog.PacksDialog(got.append, fetch_list=False)
    try:
        dlg._show(packs.parse([links_entry(3)]), "")
        card = dlg.cards[0]
        texts = []
        real = dlg._show_progress
        monkeypatch.setattr(dlg, "_show_progress",
                            lambda pid: (real(pid), texts.append(card.btn.text())))
        dlg.add(card)
        assert process_events(qapp, lambda: got, 5)
        assert "3 of 3" in texts
        assert any("1 sound is gone from Myinstants" in t for t in toasts)
    finally:
        dlg.done(0)


def test_a_download_goes_on_with_the_page_closed_and_shows_when_it_opens_again(
        qapp, app_dir, myinstants, monkeypatch):
    """Back to my sounds (or another tab) mid-download: it isn't stopped, its sounds
    still go on the board, and the page opened again shows it still going."""
    monkeypatch.setattr(packsdialog.busy, "toast", lambda *a, **k: None)
    monkeypatch.setattr(net, "allowed", lambda f: True)
    go, got = threading.Event(), []
    real = packs._fetch_link

    def slow(*a, **k):
        assert go.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(packs, "_fetch_link", slow)
    dlg = packsdialog.PacksDialog(got.append, fetch_list=False)
    dlg._show(packs.parse([links_entry(3)]), "")
    dlg.add(dlg.cards[0])
    dlg.done(0)   # left the page
    again = packsdialog.PacksDialog(lambda path: None, fetch_list=False)
    try:
        again._show(packs.parse([links_entry(3)]), "")
        process_events(qapp, lambda: again.cards and again.cards[0].btn.text() != "Add", 2)
        assert busy_btn(again.cards[0].btn)   # still downloading
        again.add(again.cards[0])   # pressed again meanwhile: not a second download
        go.set()
        assert process_events(qapp, lambda: got, 5)
        assert got == [packs.parse([links_entry(3)])[0].path]
        assert not packsdialog.downloads().words
    finally:
        go.set()
        again.done(0)


def busy_btn(b) -> bool:
    return packsdialog.busy.is_busy(b)


def test_the_page_hands_a_pack_that_failed_for_now_to_the_window(qapp, app_dir, myinstants,
                                                                 monkeypatch):
    import urllib.error
    toasts, later = [], []
    monkeypatch.setattr(packsdialog.busy, "toast", lambda _w, text, *a, **k: toasts.append(text))
    monkeypatch.setattr(net, "allowed", lambda f: True)
    tries = 2 * (len(packs.LINK_RETRY_WAITS) + 1)
    failing(monkeypatch, myinstants, {f"s{i}.mp3": [urllib.error.URLError("no route")] * tries
                                      for i in range(2)})
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False, try_later=later.append)
    try:
        dlg._show(packs.parse([links_entry(2)]), "")
        dlg.add(dlg.cards[0])
        assert process_events(qapp, lambda: later, 5)
        assert later[0].id == "memes"
        assert any("tries again by itself in 2 hours" in t for t in toasts)
    finally:
        dlg.done(0)


def test_a_links_packs_sounds_go_on_the_board_as_they_come_and_stay_one_pack(
        window, qapp, myinstants, monkeypatch):
    """Each sound is on the board once it came, not after all of them; the whole pack's
    import then adds no second copy, makes them its own (one Remove takes them all) and
    says once how many came."""
    from conftest import said
    monkeypatch.setattr(net, "allowed", lambda f: True)
    monkeypatch.setattr(packsdialog, "CAME_GAP_MS", 0)
    gate, real = threading.Semaphore(0), packs._fetch_link

    def slow(*a, **k):   # (the page's samples aren't held back)
        if threading.current_thread().name.startswith("pack-link"):
            assert gate.acquire(timeout=10)
        return real(*a, **k)
    monkeypatch.setattr(packs, "_fetch_link", slow)
    links = links_entry(6)
    for i, k in enumerate(links["links"]):
        k["category"] = ["Memes", "Gaming"][i % 2]   # two categories: one tab for the pack
    p, = packs.parse([links])
    before = len(window.cfg.sounds)

    def mine():
        return [m for m in window.cfg.sounds[before:]]
    dlg = window.impctl.show_packs()
    try:
        dlg._show([p], "")
        process_events(qapp, lambda: dlg.cards, 3)
        dlg.add(dlg.cards[0])
        gate.release()
        gate.release()
        assert process_events(qapp, lambda: len(mine()) == 2, 5)   # two came: on the board
        assert all(not m.pack for m in mine())
        from soundboard.ui.window.importpacks import pack_tab_name
        assert all(pack_tab_name(p.name) in m.tags for m in mine()), [m.tags for m in mine()]
        for _ in range(4):
            gate.release()
        assert process_events(qapp, lambda: "Imported 6 sounds" in said(window), 10)
        got = mine()
        assert len(got) == 6   # none twice
        assert [m.name for m in got] == [k.name for k in p.links]   # in the pack's order
        pid, = {m.pack for m in got}
        assert pid and sorted(m.pack_item for m in got) == [packs.link_folder(i)
                                                            for i in range(6)]
        assert "already" not in said(window)
        window.impctl.remove_pack(pid, ask=False)
        assert len(window.cfg.sounds) == before
    finally:
        for _ in range(6):
            gate.release()
        window.impctl.close_packs()


def test_the_window_asks_for_a_pack_again_later_and_adds_it(window, qapp, myinstants,
                                                            monkeypatch):
    """Two hours after a links pack failed for now, the window asks for it again by
    itself (once per pack), adds what came, and waits again while it still fails."""
    import types
    import urllib.error

    from soundboard.ui.window import importpacks
    timers = []
    monkeypatch.setattr(importpacks, "QTimer", types.SimpleNamespace(
        singleShot=lambda ms, ctx, fn: timers.append((ms, fn))))
    monkeypatch.setattr(net, "allowed", lambda f: True)
    ctl = window.impctl
    p, = packs.parse([links_entry(3)])
    ctl._pack_try_later(p)
    ctl._pack_try_later(p)
    assert [ms for ms, _fn in timers] == [packs.LINK_TRY_LATER * 1000]   # once a pack
    before = len(window.cfg.sounds)
    timers[0][1]()                                     # two hours later: the site's back
    assert process_events(qapp, lambda: len(window.cfg.sounds) == before + 3, 10)
    assert not ctl._pack_retries
    q, = packs.parse([links_entry(2, id="other", name="Other")])
    tries = 2 * (len(packs.LINK_RETRY_WAITS) + 1)
    failing(monkeypatch, myinstants, {f"s{i}.mp3": [urllib.error.URLError("no route")] * tries
                                      for i in range(2)})
    ctl._pack_retry(q)                                 # still no connection: later again
    assert process_events(qapp, lambda: len(timers) == 2, 10)
    assert "other" in ctl._pack_retries and len(window.cfg.sounds) == before + 3


# ---------------------------------------------------------------- the preview


def _preview_ready(qapp, dlg):
    return process_events(qapp, lambda: dlg.preview is not None
                          and dlg.preview.samples[0].sample is not None and not dlg._fills, 5)


def test_the_preview_plays_a_sample_to_the_headphones_and_stops_it(qapp, served):
    data, preview = make_pack(), make_preview()
    p = with_preview(data, preview)
    served.files[p["preview"]["url"]] = preview
    played = []
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: played.append(d is not None) or True)
    try:
        dlg._show(packs.parse([p]), "")
        dlg.cards[0].btn_preview.click()
        assert _preview_ready(qapp, dlg)
        pads = dlg.preview.samples
        assert [b.isVisibleTo(dlg.preview) for b in pads].count(True) == 2
        assert pads[0].isEnabled() and pads[1].text() == "Dragon"
        pads[0].click()
        assert process_events(qapp, lambda: played == [True], 5)
        assert pads[0].isChecked()
        pads[1].click()   # another one: the first stops, this one plays
        assert process_events(qapp, lambda: played == [True, False, True], 5)
        assert not pads[0].isChecked() and pads[1].isChecked()
        pads[1].click()   # pressed again: stopped
        assert played[-1] is False and not pads[1].isChecked()
        pads[0].click()
        assert process_events(qapp, lambda: played[-1] is True, 5)
        dlg.preview.btn_close.click()   # closed while one plays: it stops
        assert dlg.preview is None and played[-1] is False
    finally:
        dlg.done(0)


def test_the_preview_adds_the_pack(qapp, served):
    data = make_pack()
    served.files[entry(data)["url"]] = data
    got = []
    dlg = packsdialog.PacksDialog(got.append, fetch_list=False)
    try:
        dlg._show(packs.parse([entry(data)]), "")
        dlg.open_pack(dlg.cards[0].pack)
        assert dlg.preview.btn.text() == "Add to my board"
        dlg.preview.btn.click()
        assert process_events(qapp, lambda: got, 5)
        assert dlg.preview is None   # added: the board's import reports it from here
        assert dlg.cards[0].btn.text() in ("✓ Added", "Add again")
    finally:
        dlg.done(0)


def test_no_headphones_says_where_to_set_them(qapp, served):
    preview = make_preview()
    p = with_preview(make_pack(), preview)
    served.files[p["preview"]["url"]] = preview
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: d is None)   # nowhere to play it
    try:
        dlg._show(packs.parse([p]), "")
        dlg.open_pack(dlg.cards[0].pack)
        assert _preview_ready(qapp, dlg)
        dlg.preview.samples[0].click()
        assert process_events(qapp, lambda: dlg.note.isVisibleTo(dlg), 5)
        assert "headphones" in dlg.note.text() and not dlg.preview.samples[0].isChecked()
    finally:
        dlg.done(0)


def test_samples_that_cant_be_fetched_say_so_and_add_still_works(qapp, served):
    p = with_preview(make_pack(), make_preview())   # nothing served: the fetch fails
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: True)
    try:
        dlg._show(packs.parse([p]), "")
        dlg.open_pack(dlg.cards[0].pack)
        pads = dlg.preview.samples
        assert pads[0].isVisibleTo(dlg.preview)   # placeholders while it's fetched
        assert process_events(qapp, lambda: not pads[0].isVisibleTo(dlg.preview), 5)
        assert "Couldn't load" in dlg.preview.listen_hint.text()
        assert dlg.preview.btn.isEnabled()
    finally:
        dlg.done(0)


def test_every_packs_samples_are_preloaded_one_pack_at_a_time(qapp, monkeypatch):
    """The page fetches each pack's samples in the background as soon as it's up (one
    pack at a time): a preview opened later has its pads at once, nothing fetched."""
    fetched, at_once, busy_now = [], [], [0]
    gate = threading.Lock()

    def slow(pack, cancelled=None):
        with gate:
            busy_now[0] += 1
            at_once.append(busy_now[0])
        fetched.append(pack.id)
        threading.Event().wait(0.02)
        with gate:
            busy_now[0] -= 1
        return [packs.Sample("Door", b"", packs.previews_dir() / "x.wav")]
    monkeypatch.setattr(packs, "samples", slow)
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: True)
    try:
        dlg._show(packs.parse([links_entry(id="test-links")]) + packs.built_in(), "")
        assert process_events(qapp, lambda: len(fetched) == 12 and not dlg._sampling
                              and len(dlg.cards) == 12, 5)
        assert sorted(fetched) == sorted(p.id for p in dlg.shown()) and max(at_once) == 1
        dlg.open_pack(dlg.cards[2].pack)
        assert _preview_ready(qapp, dlg) and len(fetched) == 12
        assert dlg.preview.samples[0].text() == "Door"
    finally:
        dlg.done(0)


def test_samples_still_land_when_the_online_list_remakes_the_cards(qapp, served, monkeypatch):
    """The online list arriving mid-fetch remakes the cards: the samples still land on
    the open preview, from one fetch (two at once wrote the same .part file and broke
    both)."""
    preview = make_preview()
    p = with_preview(make_pack(), preview)
    served.files[p["preview"]["url"]] = preview
    gate, real = threading.Event(), packs.samples
    fetched = []

    def slow(pack, cancelled=None):
        fetched.append(pack.id)
        gate.wait(5)
        return real(pack, cancelled)
    monkeypatch.setattr(packs, "samples", slow)
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: True)
    try:
        dlg._show(packs.parse([p]), "")
        dlg.open_pack(dlg.cards[0].pack)
        changed = packs.parse([p])
        changed[0].description = "New words"
        dlg._show(changed, "")   # the online list, while it's still fetching
        gate.set()
        assert _preview_ready(qapp, dlg) and fetched.count("horror") == 1
        dlg.close_pack()
        dlg.open_pack(dlg.cards[0].pack)   # again: at once, not fetched again
        assert _preview_ready(qapp, dlg) and fetched.count("horror") == 1
    finally:
        dlg.done(0)


def test_escape_closes_the_preview_first_then_the_page(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False)
    try:
        dlg.open_pack(dlg.cards[0].pack)
        assert dlg.preview is not None
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg.preview is None and not dlg._closed
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg._closed
    finally:
        dlg.done(0)


def test_the_page_is_filled_a_piece_at_a_time(qapp, served):
    """Built in one go (every card, then every pad) it was ~80 ms of Qt work back to
    back, and the sound playing came 10 ms late (a skip): the audio threads wait on
    the UI thread. One card at once, then a card or a pad a step, with a rest between
    for the audio."""
    preview = make_preview(("Door", "Dragon"))
    served.files[with_preview(b"x", preview)["preview"]["url"]] = preview
    shown = [with_preview(make_pack(), preview, id=f"p{i}", name=f"Pack {i}")
             for i in range(3)]
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: True)
    try:
        dlg._show(packs.parse(shown), "")
        assert len(dlg.cards) == 1   # the rest wait their turn: the page isn't empty
        dlg.open_pack(packs.parse(shown)[0])
        steps = []
        real = dlg._step

        def count():
            pads = dlg.preview.samples if dlg.preview else []
            return len(dlg.cards) + sum(b.sample is not None for b in pads)

        def step():
            before = count()
            real()
            steps.append(count() - before)
        dlg._stepper.timeout.disconnect()
        dlg._stepper.timeout.connect(step)
        assert process_events(qapp, lambda: len(dlg.cards) == 3
                              and dlg.preview.samples[1].sample is not None, 5)
        assert [c.pack.id for c in dlg.cards] == ["p0", "p1", "p2"]
        assert [dlg.list.itemAt(i).widget() for i in range(3)] == dlg.cards
        assert steps and max(steps) == 1   # one card or one pad a step, never more
    finally:
        dlg.done(0)


def test_the_pack_cards_keep_clear_of_the_scroll_bar(qapp):
    dlg = packsdialog.PacksDialog(lambda p: None, fetch_list=False)
    try:
        dlg.resize(780, 500)
        dlg.show()
        bar = dlg.scroll_area.verticalScrollBar()
        assert process_events(qapp, lambda: bar.maximum() > 0, 5)
        assert dlg.body.layout().contentsMargins().right() == 10
        dlg.resize(780, 4000)   # everything fits: no bar, cards to the page's edge
        assert process_events(qapp, lambda: bar.maximum() == 0, 5)
        assert dlg.body.layout().contentsMargins().right() == 0
    finally:
        dlg.close()


def test_a_cards_buttons_split_its_row_evenly(qapp):
    dlg = packsdialog.PacksDialog(lambda p: None, fetch_list=False)
    try:
        dlg.resize(1000, 700)
        dlg.show()
        assert process_events(qapp, lambda: len(dlg.cards) == 11 and not dlg._stepper.isActive(), 5)
        qapp.processEvents()
        for c in dlg.cards:
            assert abs(c.btn.width() - c.btn_preview.width()) <= 1
            assert c.btn.x() < c.btn_preview.x()
    finally:
        dlg.close()
