"""A category you made with the same name as one an import brings ("Memes" and a
Memes pack, a backup, another soundboard's board): one tab, in your spelling, with
nothing doubled or lost."""
import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import process_events
from soundboard.otherboards import soundpad
from soundboard.sounds import packs
from soundboard.sounds.config import Config
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen
from test_packs import entry, make_pack, served  # noqa: F401 - the fake downloads
from test_soundpad import _board


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def _mine(w, name: str):
    """A category the user made, with one of their own sounds in it."""
    w.cfg.categories.append(name)
    w.cfg.sounds[0].tags = [name]
    w.catctl._fill_categories()


def _add_pack(w, qapp, served, tags, name="Memes pack", pid="memes-test"):  # noqa: F811
    data = make_pack(("Bruh", "Vine boom"), tags=tags)
    p, = packs.parse([entry(data, id=pid, name=name)])
    served.files[p.url] = data
    before = len(w.cfg.sounds)
    w.impctl.import_files([str(packs.download(p))])
    assert process_events(qapp, lambda: len(w.cfg.sounds) == before + 2, 10)
    return w.cfg.sounds[before:]


@pytest.mark.parametrize("theirs", ["Memes", "memes", "MEMES", " Memes ", "Memes  "])
def test_a_pack_with_your_categorys_name_goes_into_yours(window, qapp, served, theirs):  # noqa: F811
    w = window
    _mine(w, "Memes")
    tabs = list(w.cfg.categories)
    added = _add_pack(w, qapp, served, [theirs, theirs])
    assert w.cfg.categories == tabs   # no second "Memes" / "memes" tab
    assert all(m.tags == ["Memes"] for m in added)
    assert w.cfg.sounds[0].tags == ["Memes"]   # yours is still in it
    assert sum("Memes" in m.tags for m in w.cfg.sounds) == 3


def test_a_near_name_is_a_tab_of_its_own(window, qapp, served):  # noqa: F811
    w = window
    _mine(w, "Memes")
    tabs = list(w.cfg.categories)
    added = _add_pack(w, qapp, served, ["Meme sounds", "Meme sounds"])
    assert w.cfg.categories == tabs + ["Meme sounds"]
    assert w.cfg.sounds[0].tags == ["Memes"]
    assert all(m.tags == ["Meme sounds"] for m in added)


def test_the_meme_packs_tab_joins_your_meme_sounds_tab(window, qapp, served):  # noqa: F811
    """The real Meme sounds pack has several categories: they go in one "Meme sounds"
    tab, which is yours if you made one (in your spelling), its categories inside."""
    w = window
    _mine(w, "meme sounds")
    w.cfg.subcategories["meme sounds"] = ["fails"]
    tabs = list(w.cfg.categories)
    added = _add_pack(w, qapp, served, ["Reactions", "Fails"], name="Meme sounds",
                      pid="memes")   # (its name comes from the built-in list)
    assert w.cfg.categories == tabs
    assert w.cfg.subcategories["meme sounds"] == ["fails", "Reactions"]
    assert [m.tags for m in added] == [["meme sounds", "meme sounds / Reactions"],
                                      ["meme sounds", "meme sounds / fails"]]
    assert w.cfg.sounds[0].tags == ["meme sounds"]


def test_the_same_pack_twice_adds_nothing_twice(window, qapp, served):  # noqa: F811
    w = window
    _mine(w, "Memes")
    _add_pack(w, qapp, served, ["Memes", "Memes"])
    n, tabs = len(w.cfg.sounds), list(w.cfg.categories)
    w.impctl.import_files([str(packs.download(packs.parse([entry(
        make_pack(("Bruh", "Vine boom"), tags=["Memes", "Memes"]),
        id="memes-test", name="Memes pack")])[0]))])
    assert not process_events(qapp, lambda: len(w.cfg.sounds) != n, 2)
    assert w.cfg.categories == tabs


@pytest.mark.windows   # Windows paths
def test_another_boards_categories_go_into_yours(window, qapp, tmp_path, monkeypatch):
    w = window
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _board(tmp_path)   # its sounds are in "Memes" (and "Loud")
    _mine(w, "memes")
    tabs = list(w.cfg.categories)
    w.impctl.import_other(soundpad.SOURCE)
    assert process_events(qapp, lambda: not w.impctl._pending_imports
                          and len(w.cfg.sounds) == 5)
    assert w.cfg.categories == tabs + ["Soundpad", "Loud"]
    new = {m.name: m for m in w.cfg.sounds[2:]}
    assert new["Vine - Boom"].tags == ["Soundpad", "memes", "Loud"]
    assert w.cfg.sounds[0].tags == ["memes"]


@pytest.mark.windows   # Windows paths
def test_your_empty_category_named_like_the_board_stays(window, qapp, tmp_path, monkeypatch):
    """Importing a board again with nothing new drops the board's tab it made, never
    one you made yourself with that name."""
    w = window
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _board(tmp_path)
    w.impctl.import_other(soundpad.SOURCE)
    assert process_events(qapp, lambda: not w.impctl._pending_imports
                          and "Soundpad" in w.cfg.categories)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    w.catctl.delete_category("Soundpad")
    w.cfg.categories.append("Soundpad")   # yours now: made by hand, empty
    toasts = []
    monkeypatch.setattr(w, "toast", lambda text, *a, **k: toasts.append(text))
    w.impctl.import_other(soundpad.SOURCE)   # all already here: nothing to add
    assert process_events(qapp, lambda: "Nothing new to add" in toasts)
    assert "Soundpad" in w.cfg.categories


def test_saved_settings_with_near_doubles_load_as_one(tmp_path):
    cfg = Config.from_raw({"categories": ["Memes", "memes ", " MEMES", "Memes"],
                           "sounds": []})
    assert cfg.categories == ["Memes"]
