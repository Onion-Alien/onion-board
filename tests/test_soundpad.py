"""Import from Soundpad: reading its sound list, and bringing the sounds into the board."""
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from conftest import process_events
from soundboard import library, otherboards, soundpad
from soundboard.library import SR
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


def _wav(path: Path, freq: float) -> Path:
    t = np.arange(SR // 10) / SR
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.stack([np.sin(2 * np.pi * freq * t)] * 2, 1) * 0.3, SR)
    return path


def _board(tmp_path) -> Path:
    """A Soundpad list like the ones it saves: one absolute path, the rest relative to
    `rel`, one file gone, nested categories and the hidden built-in list."""
    sounds = tmp_path / "My sounds"
    _wav(sounds / "bruh.wav", 300)
    _wav(sounds / "sub" / "vine boom.wav", 500)
    other = _wav(tmp_path / "elsewhere" / "airhorn.wav", 700)
    spl = tmp_path / "Leppsoft" / "soundlist.spl"
    spl.parent.mkdir()
    spl.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Soundlist rel="{sounds}">
  <Sound hash="1" url="bruh.wav" artist="" title="Bruh" duration="0:01" addedOn="2024-01-01"
         keyModifiers="2" key="49"/>
  <Sound hash="2" url="sub\\vine boom.wav" artist="Vine" title="Boom" keyModifiers="5" key="112"/>
  <Sound hash="3" url="{other}" title="" key="0"/>
  <Sound hash="4" url="gone.mp3" title="Gone"/>
  <Categories>
    <Category name="My Sounds" recordings="true" icon="stock_icon_cat_home">
      <Sound id="0"/><Sound id="1"/><Sound id="2"/><Sound id="3"/>
    </Category>
    <Category type="1" icon="stock_icon_cat_list" hidden="true"><Sound id="0"/></Category>
    <Category name="Memes">
      <Sound id="0"/><Sound id="1"/><Sound id="9"/>
      <Category name="Loud"><Sound id="2"/><Sound id="1"/></Category>
    </Category>
  </Categories>
</Soundlist>""", encoding="utf-8")
    return spl


@pytest.mark.windows   # Windows paths
def test_reads_names_paths_categories_and_hotkeys(tmp_path):
    entries = soundpad.read(_board(tmp_path))
    assert [e.name for e in entries] == ["Bruh", "Vine - Boom", "airhorn", "Gone"]
    assert [e.exists for e in entries] == [True, True, True, False]
    assert Path(entries[1].path) == tmp_path / "My sounds" / "sub" / "vine boom.wav"
    assert [e.tags for e in entries] == [["Memes"], ["Memes", "Loud"], ["Loud"], []]
    # keyModifiers are RegisterHotKey's: 2 = ctrl, 5 = alt + shift; key 0 = none
    assert [e.hotkey for e in entries] == ["ctrl+1", "alt+shift+f1", "", ""]
    ok, bad = otherboards.importable(entries)
    assert len(ok) == 3 and [e.name for e in bad] == ["Gone"]


# keyModifiers checked against Soundpad 4.0.35 itself (its Hotkey column): 1 Alt, 2 Ctrl,
# 4 Shift, 8 Win, 6 Ctrl+Shift
@pytest.mark.parametrize("key,mods,want", [
    ("49", "1", "alt+1"), ("50", "2", "ctrl+2"), ("51", "4", "shift+3"),
    ("52", "8", "windows+4"), ("53", "6", "ctrl+shift+5"), ("13", "0", "enter"),
    ("96", "8", "windows+num 0"), ("16", "0", ""),   # bare shift
    ("1", "0", ""), ("x", "0", ""), (None, None, "")])                    # mouse, junk
def test_hotkeys(key, mods, want):
    assert soundpad.hotkey(key, mods) == want


def test_not_a_sound_list(tmp_path):
    p = tmp_path / "x.spl"
    p.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError):
        soundpad.read(p)
    p.write_text("not xml at all", encoding="utf-8")
    with pytest.raises(ValueError):
        soundpad.read(p)


def test_finds_soundpads_list_only_when_its_there(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert soundpad.default_list() is None
    spl = _board(tmp_path)
    assert soundpad.default_list() == spl


@pytest.mark.windows   # Windows paths
def test_import_brings_the_board_over(main_window, qapp, tmp_path, monkeypatch):  # noqa: F811
    w = main_window
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _board(tmp_path)
    w.cfg.sounds[0].hotkey = "alt+shift+f1"    # already used here: left off the import
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda _p, _t, text, *a: asked.append(text) or QMessageBox.Yes)
    w.impctl.import_other(soundpad.SOURCE)
    assert process_events(qapp, lambda: asked)               # read on a thread
    assert "<b>3</b> sounds" in asked[0] and "3 categories" in asked[0]   # + "Soundpad"
    assert "2 hotkeys" in asked[0] and "Gone" in asked[0]
    assert process_events(qapp, lambda: not w.impctl._pending_imports and len(w.cfg.sounds) == 5)
    new = {m.name: m for m in w.cfg.sounds[2:]}
    assert set(new) == {"Bruh", "Vine - Boom", "airhorn"}
    assert new["Bruh"].hotkey == "ctrl+1" and new["Vine - Boom"].hotkey == ""
    # each in a "Soundpad" category too, so they're easy to find, as well as its own
    assert new["Vine - Boom"].tags == ["Soundpad", "Memes", "Loud"]
    assert all(m.tags[0] == "Soundpad" for m in new.values())
    assert {"Soundpad", "Memes", "Loud"} <= set(w.cfg.categories)
    assert {n: Path(m.file) for n, m in new.items()} == {   # linked to Soundpad's files
        "Bruh": tmp_path / "My sounds" / "bruh.wav",
        "Vine - Boom": tmp_path / "My sounds" / "sub" / "vine boom.wav",
        "airhorn": tmp_path / "elsewhere" / "airhorn.wav"}
    assert not any(library.SOUNDS_DIR in Path(m.file).parents for m in new.values())
    assert (tmp_path / "My sounds" / "bruh.wav").is_file()   # Soundpad's own stay put
    assert not w.impctl._import_errors

    w.impctl.import_other(soundpad.SOURCE)                   # again: nothing doubled, no error list
    assert process_events(qapp, lambda: not w.impctl._pending_imports)
    assert len(w.cfg.sounds) == 5 and not w.impctl._import_errors


def test_reading_the_board_doesnt_block_the_window(
        main_window, qapp, tmp_path, monkeypatch):  # noqa: F811
    """The board file can be tens of MB and its sounds on a network drive that's gone
    (seconds a file): import_other returns at once, the entries come back through a
    signal, and only the question and the import run on the UI thread."""
    w = main_window
    wav = _wav(tmp_path / "far" / "bruh.wav", 300)
    release, threads = threading.Event(), []

    def slow_read(_path):
        threads.append(threading.current_thread())
        release.wait(3)
        return [otherboards.Entry(name="Bruh", path=str(wav), exists=True)]
    src = otherboards.Source("slow", "Slowpad", (".slow",), lambda: None, slow_read)
    got, asked = [], []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda _p, _t, text, *a: asked.append(text) or QMessageBox.Yes)
    start = time.monotonic()
    w.impctl.import_other(src, str(tmp_path / "board.slow"))
    assert time.monotonic() - start < 1 and not asked   # didn't wait for the read
    w.board_read.connect(lambda *a: got.append(a))   # it comes back through this
    release.set()
    assert process_events(qapp, lambda: not w.impctl._pending_imports and len(w.cfg.sounds) == 3)
    assert threads and threads[0] is not threading.main_thread()
    assert len(got) == 1 and "<b>1</b> sound in Slowpad" in asked[0]
    assert w.cfg.sounds[-1].name == "Bruh"


def test_a_board_read_after_the_window_closed_is_dropped(main_window, monkeypatch):  # noqa: F811
    w = main_window
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("asked"))
    monkeypatch.setattr(w, "_shut_down", True)
    entry = otherboards.Entry(name="x", path="C:/x.wav", exists=True)
    w.impctl._board_read(soundpad.SOURCE, "C:/b.spl", True, ([entry], [], [entry]))
    assert len(w.cfg.sounds) == 2


def test_a_dropped_spl_goes_to_the_soundpad_import(main_window, monkeypatch):  # noqa: F811
    got = []
    monkeypatch.setattr(main_window.impctl, "import_other", lambda src, f: got.append((src.key, f)))
    main_window.impctl.import_files(["C:/x/list.SPL"])
    assert got == [("soundpad", "C:/x/list.SPL")]


@pytest.mark.windows   # Windows paths
@pytest.mark.parametrize("answer, kept", [("Keep", 5), ("Remove", 2), (None, 5)])
def test_the_installers_box_imports_on_first_start_then_asks_to_keep(
        main_window, qapp, tmp_path, monkeypatch, answer, kept):  # noqa: F811
    """Ticked in the installer, it leaves a note; the first start does the import with
    no question first (the tick was the yes), and only once. Once they're in, one box
    asks whether to keep them: Remove takes them all off again, closing it keeps them."""
    w = main_window
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _board(tmp_path)
    note = library.APP_DIR / otherboards.QUEUED_NAME
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("soundpad", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("asked"))
    asked = []

    def answer_box(box):
        asked.append(box.text())
        if answer is None:
            QTest.keyClick(box, Qt.Key_Escape)   # closed with Esc
            return 0
        next(b for b in box.buttons() if b.text() == answer).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", answer_box)
    w.impctl.import_queued()
    assert not note.exists()
    assert process_events(qapp, lambda: not w.impctl._pending_imports and asked)
    assert "<b>3</b> sounds from Soundpad" in asked[0]
    assert len(w.cfg.sounds) == kept
    w.impctl.import_queued()                            # no note: nothing happens
    assert not w.impctl._pending_imports and len(w.cfg.sounds) == kept and len(asked) == 1


@pytest.mark.windows   # Windows paths
def test_an_import_from_the_menu_is_not_asked_again(
        main_window, qapp, tmp_path, monkeypatch):  # noqa: F811
    w = main_window
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _board(tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: pytest.fail("asked to keep"))
    w.impctl.import_other(soundpad.SOURCE)
    assert process_events(qapp, lambda: not w.impctl._pending_imports and len(w.cfg.sounds) == 5)


@pytest.mark.windows   # Windows paths
def test_the_installers_box_waits_for_the_setup_guide_and_says_where_from(
        main_window, qapp, tmp_path, monkeypatch):  # noqa: F811
    """The first start opens the setup guide: the import only starts once it's closed
    (its card was stuck over the guide), and the card names the other soundboard."""
    from soundboard.ui import setupwizard
    w = main_window
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _board(tmp_path)
    note = library.APP_DIR / otherboards.QUEUED_NAME
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("soundpad", encoding="utf-8")
    during = []
    monkeypatch.setattr(setupwizard.SetupWizard, "exec",
                        lambda self: during.append(note.exists() and not w.impctl._pending_imports))
    monkeypatch.setattr(QMessageBox, "exec", lambda box: 0)
    texts = []
    real_toast = w.toast
    monkeypatch.setattr(w, "toast", lambda text, *a, **k: (texts.append(text),
                                                         real_toast(text, *a, **k))[1])
    w.run_setup()
    assert during == [True] and note.exists()     # nothing started while it was up
    assert process_events(qapp, lambda: not note.exists() and not w.impctl._pending_imports
                          and len(w.cfg.sounds) == 5)
    assert any("Bringing your sounds over from Soundpad" in t for t in texts)


def test_a_queued_import_with_soundpad_gone_does_nothing(
        main_window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("APPDATA", str(tmp_path))
    note = library.APP_DIR / otherboards.QUEUED_NAME
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("soundpad", encoding="utf-8")
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                        lambda *a, **k: pytest.fail("opened a file picker"))
    main_window.impctl.import_queued()
    assert not note.exists() and len(main_window.cfg.sounds) == 2


def test_the_installer_offers_it_only_when_soundpad_is_there():
    iss = (Path(__file__).parent.parent / "installer" / "OnionBoard.iss").read_text("utf-8")
    assert "if Preview or HasSoundpad then" in iss
    assert r"Leppsoft\soundlist.spl" in iss and otherboards.QUEUED_NAME in iss
