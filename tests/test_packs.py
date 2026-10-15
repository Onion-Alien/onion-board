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
    assert [(p.id, p.sounds) for p in built] == [("streamer", 57), ("esports", 51),
                                                 ("podcast", 51), ("halloween", 49),
                                                 ("gm-starter", 67)]
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


def test_a_damaged_pack_zip_with_a_matching_checksum_isnt_kept(served):
    """A broken upload whose checksum the list matched was kept: its import failed,
    and the card then said "Add again" though nothing was added."""
    bad = b"PK" + bytes(900)
    p, = packs.parse([entry(bad)])
    served.files[p.url] = bad
    with pytest.raises(updates.UpdateError, match="damaged"):
        packs.download(p)
    assert not p.downloaded() and not p.path.exists()


def test_add_with_offline_mode_on_answers_the_press(qapp, served, monkeypatch):
    toasts = []
    monkeypatch.setattr(packsdialog.busy, "toast", lambda _w, text, *a, **k: toasts.append(text))
    net.configure_features(offline=True)
    dlg = packsdialog.PacksDialog(lambda p: None)
    try:
        dlg.add(dlg.cards[0])
        assert toasts and "Offline mode" in toasts[0]
        assert dlg.cards[0].btn.text() == "Add to my board" and served.calls == []
    finally:
        dlg.done(0)


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
        assert process_events(qapp, lambda: len(dlg.cards) == 5, 5)
        assert [c.pack.id for c in dlg.cards] == ["streamer", "esports", "podcast",
                                                "halloween", "gm-starter"]
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
    window.impctl.import_files([str(path)])
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
    monkeypatch.setattr(window.impctl, "import_files", got.append)

    def fake_exec(dlg):
        dlg._add(tmp_path / "horror.zip")   # as a finished download does
        return 0
    monkeypatch.setattr(packsdialog.PacksDialog, "exec", fake_exec)
    monkeypatch.setattr(net, "allowed", lambda f: False)   # no list fetch
    window.impctl.show_packs()
    assert got == [[str(tmp_path / "horror.zip")]]


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


def test_the_window_plays_a_sample_to_the_headphones_and_stops_it(qapp, served):
    data, preview = make_pack(), make_preview()
    p = with_preview(data, preview)
    served.files[p["preview"]["url"]] = preview
    played = []
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: played.append(d is not None) or True)
    try:
        dlg._show(packs.parse([p]), "")
        card = dlg.cards[0]
        assert process_events(
            qapp, lambda: card.samples[0].sample is not None and not dlg._fills, 5)
        assert [b.isVisibleTo(dlg) for b in card.samples].count(True) == 2
        assert card.samples[0].isEnabled() and card.samples[1].text() == "Dragon"
        card.samples[0].click()
        assert process_events(qapp, lambda: played == [True], 5)
        assert card.samples[0].isChecked()
        card.samples[1].click()   # another one: the first stops, this one plays
        assert process_events(qapp, lambda: played == [True, False, True], 5)
        assert not card.samples[0].isChecked() and card.samples[1].isChecked()
        card.samples[1].click()   # pressed again: stopped
        assert played[-1] is False and not card.samples[1].isChecked()
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
        card = dlg.cards[0]
        assert process_events(
            qapp, lambda: card.samples[0].sample is not None and not dlg._fills, 5)
        card.samples[0].click()
        assert process_events(qapp, lambda: dlg.note.isVisibleTo(dlg), 5)
        assert "headphones" in dlg.note.text() and not card.samples[0].isChecked()
    finally:
        dlg.done(0)


def test_samples_that_cant_be_fetched_take_their_row_away(qapp, served):
    p = with_preview(make_pack(), make_preview())   # nothing served: the fetch fails
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: True)
    try:
        dlg._show(packs.parse([p]), "")
        card = dlg.cards[0]
        assert card.listen.isVisibleTo(dlg)   # placeholders while it's fetched
        assert process_events(qapp, lambda: not card.listen.isVisibleTo(dlg), 5)
    finally:
        dlg.done(0)


def test_samples_still_land_when_the_online_list_remakes_the_cards(qapp, served, monkeypatch):
    """The online list arriving mid-fetch remakes the cards: the samples land on the new
    ones, from one fetch (two at once wrote the same .part file and broke both)."""
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
        dlg._show(packs.parse([p]), "")   # the online list, while it's still fetching
        gate.set()
        card = dlg.cards[0]
        assert process_events(
            qapp, lambda: card.samples[0].sample is not None and not dlg._fills, 5)
        assert card.listen.isVisibleTo(dlg) and fetched.count("horror") == 1
        dlg._show(packs.parse([p]), "")   # once more: shown at once, not fetched again
        assert dlg.cards[0].samples[0].sample is not None and fetched.count("horror") == 1
    finally:
        dlg.done(0)


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
        assert process_events(qapp, lambda: len(dlg.cards) == 5, 5)
        before = list(dlg.cards)
        dlg._show(packs.built_in(), "")
        assert dlg.cards == before and all(a is b for a, b in zip(dlg.cards, before))
        changed = packs.built_in()
        changed[1].description = "Something new"
        dlg._show(changed, "")
        assert process_events(qapp, lambda: len(dlg.cards) == 5, 5)
        assert [c.pack for c in dlg.cards] == changed
        assert dlg.cards[1] is not before[1]
        assert all(dlg.cards[i] is before[i] for i in (0, 2, 3, 4))
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


def test_the_window_is_filled_a_piece_at_a_time(qapp, served):
    """Built in one go (every card, then every sample's tile) it was ~80 ms of Qt work
    back to back, and the sound playing came 10 ms late (a skip): the audio threads
    wait on the UI thread. One card at once, then a card or a tile a step, with a rest
    between for the audio."""
    preview = make_preview(("Door", "Dragon"))
    served.files[with_preview(b"x", preview)["preview"]["url"]] = preview
    shown = [with_preview(make_pack(), preview, id=f"p{i}", name=f"Pack {i}")
             for i in range(3)]
    dlg = packsdialog.PacksDialog(lambda path: None, fetch_list=False,
                                  play=lambda d, g: True)
    try:
        dlg._show(packs.parse(shown), "")
        assert len(dlg.cards) == 1   # the rest wait their turn: the window isn't empty
        steps = []
        real = dlg._step

        def step():
            before = (len(dlg.cards), sum(b.sample is not None
                                          for c in dlg.cards for b in c.samples))
            real()
            after = (len(dlg.cards), sum(b.sample is not None
                                         for c in dlg.cards for b in c.samples))
            steps.append((after[0] - before[0]) + (after[1] - before[1]))
        dlg._stepper.timeout.disconnect()
        dlg._stepper.timeout.connect(step)
        assert process_events(qapp, lambda: len(dlg.cards) == 3 and all(
            c.samples[1].sample is not None for c in dlg.cards), 5)
        assert [c.pack.id for c in dlg.cards] == ["p0", "p1", "p2"]
        assert [dlg.list.itemAt(i).widget() for i in range(3)] == dlg.cards
        assert steps and max(steps) == 1   # one card or one tile a step, never more
    finally:
        dlg.done(0)
