"""The board features in the real MainWindow (offscreen, no devices or hotkeys):
categories, undo after Remove, export / import, the trim control, the tray."""
from pathlib import Path

from conftest import process_events
from soundboard import backup
from soundboard.ui.dialogs import EditDialog
import pytest
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def _visible(w):
    return [m.id for m in w.cfg.sounds if not w.pads[m.id].property("filtered")]


def test_categories_filter_the_pads_and_the_overlay(window):
    assert window.new_category(name="Memes") == "Memes"
    assert window.cfg.category == "Memes" and _visible(window) == []   # new, empty page
    window.toggle_tag("s1", "Memes")
    assert _visible(window) == ["s1"] and window.overlay.sounds()[0].id == "s1"
    window.set_category("")
    assert _visible(window) == ["s0", "s1"] and len(window.overlay.sounds()) == 2
    window.search.setText("mem")                   # the search box finds categories too
    assert _visible(window) == ["s1"]
    window.search.setText("")
    # the overlay's category key walks All -> Memes -> All, and the tab follows
    window.overlay.next_category()
    assert window.cfg.category == "Memes" and window.cat_tabs.currentIndex() == 1
    window.overlay.next_category()
    assert window.cfg.category == "" and window.cat_tabs.currentIndex() == 0


def test_web_results_put_a_back_button_in_place_of_the_category_tabs(window, monkeypatch):
    """The category tabs pick pads, so they step aside while web results take the
    pads' place; the results' own back button brings both back. The new-category
    button is a "+" right after the last tab, not across the window."""
    window.new_category(name="Memes")
    window.tabs.setCurrentWidget(window.sounds_page)
    window.show()
    assert window.btn_cat_add.text() == "" and window.btn_cat_add.toolTip()
    assert window.btn_cat_add.x() < window.cat_tabs.geometry().right() + 40
    last = window.cat_tabs.tabRect(window.cat_tabs.count() - 1)
    assert window.btn_cat_add.x() - (window.cat_tabs.x() + last.right()) < 16   # no gap
    monkeypatch.setattr(window.ytresults, "available", lambda: True)
    monkeypatch.setattr(window.ytresults, "search", lambda q: window.ytresults.show() or True)
    window.search.setText("test tone")
    window.search_youtube()
    assert not window._cat_row.isVisibleTo(window) and window.ytresults.isVisibleTo(window)
    window.ytresults.btn_back.click()
    assert window._cat_row.isVisibleTo(window) and window._pads_scroll.isVisibleTo(window)
    assert window.ytresults.isHidden()


def test_my_sounds_shows_all_the_pads_not_the_ones_matching_the_web_search(
        window, monkeypatch):
    """The search box filters the pads too: back from a web search, the query still in
    it hid every pad that didn't match it."""
    window.tabs.setCurrentWidget(window.sounds_page)
    window.show()
    shown = lambda: sum(p.isVisibleTo(window) for p in window.grid.pads)  # noqa: E731
    everything = shown()
    assert everything
    monkeypatch.setattr(window.ytresults, "available", lambda: True)

    def search(q):
        window.ytresults.query = q
        window.ytresults.show()
        return True
    monkeypatch.setattr(window.ytresults, "search", search)
    window.search.setText("cat meow")
    window.search_youtube()
    window.ytresults.btn_back.click()
    assert window.search.text() == "" and shown() == everything
    window.search.setText("cat meow")
    window.search_youtube()
    window.search.setText("boom")            # typed something else since: it stays
    window.ytresults.btn_back.click()
    assert window.search.text() == "boom"


def test_rename_and_delete_category_keep_the_sounds(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.new_category("s0", name="Game")
    assert window.meta("s0").tags == ["Game"] and window.cfg.category == ""
    window.set_category("Game")
    window.rename_category("Game", "Game 1")
    assert window.meta("s0").tags == ["Game 1"] and window.cfg.category == "Game 1"
    assert window.cat_tabs.tabText(1) == "Game 1"
    window.delete_category("Game 1")
    assert window.cfg.categories == [] and window.meta("s0").tags == []
    assert window.cfg.category == "" and len(window.cfg.sounds) == 2


def test_new_sounds_land_in_the_category_on_show(window):
    from soundboard.library import SoundMeta
    window.new_category(name="Clips")
    m = SoundMeta(id="n1", name="new", file="x.wav")
    window._pending_imports = 1
    window.on_imported(m, None, "")
    assert m.tags == ["Clips"] and "n1" in _visible(window)


def _loaded(window, qapp):
    assert process_events(qapp, lambda: all(m.id in window.audio for m in window.cfg.sounds))


def test_remove_can_be_undone_then_goes_for_good(window, qapp):
    _loaded(window, qapp)
    m1 = window.meta("s1")
    data = window.audio["s1"]
    window.remove_sound("s1")
    assert window.meta("s1") is None and (not window.undo_bar.isHidden())
    assert Path(m1.file).exists()                  # nothing deleted yet
    window.undo_remove()
    assert [m.id for m in window.cfg.sounds] == ["s0", "s1"]
    assert window.audio["s1"] is data and not (not window.undo_bar.isHidden())
    window.remove_sound("s0")
    window.remove_sound("s1")                      # the first removal is final now
    assert len(window._removed) == 1 and window.cfg.sounds == []
    window._finish_removals()
    assert window._removed == [] and not (not window.undo_bar.isHidden())


def test_remove_is_finished_on_close(window):
    window.remove_sound("s0")
    window.close()
    assert window._removed == []


def test_export_then_import_through_the_window(window, qapp, tmp_path):
    _loaded(window, qapp)   # loading fills in the fingerprints the import compares
    out = tmp_path / "pack.zip"
    window._export(str(out), list(window.cfg.sounds), with_settings=False)
    assert process_events(qapp, lambda: "Exported" in window.status.text())
    assert len(backup.read(out).sounds) == 2
    window.import_package(str(out))                # all already here: nothing added
    assert process_events(qapp, lambda: "Imported" in window.status.text())
    assert "2 already" in window.status.text() and len(window.cfg.sounds) == 2
    for sid in ("s0", "s1"):
        window.remove_sound(sid)
    window._finish_removals()
    window.status.setText("")
    window.import_package(str(out))
    assert process_events(qapp, lambda: "Imported" in window.status.text())
    assert [m.name for m in window.cfg.sounds] == ["Boom", "Airhorn"]
    _loaded(window, qapp)


def test_zip_files_go_to_the_importer(window, monkeypatch, tmp_path):
    got = []
    monkeypatch.setattr(window, "import_package", got.append)
    window.import_files([str(tmp_path / "board.zip")])
    assert got == [str(tmp_path / "board.zip")]


def _wav_bytes(tmp_path, freq):
    import numpy as np
    import soundfile as sf
    from soundboard.library import SR
    t = np.arange(SR // 10) / SR
    p = tmp_path / f"{freq}.wav"
    sf.write(p, np.stack([np.sin(2 * np.pi * freq * t)] * 2, 1) * 0.3, SR)
    return p.read_bytes()


def test_a_zip_of_sounds_imports_like_dropped_files(window, qapp, tmp_path):
    import zipfile
    z = tmp_path / "memes.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Bruh.wav", _wav_bytes(tmp_path, 300))
        f.writestr("more/Vine boom.wav", _wav_bytes(tmp_path, 500))
        f.writestr("readme.txt", "hi")
    loose = tmp_path / "Oof.wav"
    loose.write_bytes(_wav_bytes(tmp_path, 700))
    window.import_files([str(z), str(loose)])     # a multi-select: a zip and a file
    assert process_events(qapp, lambda: not window._pending_imports
                          and len(window.cfg.sounds) == 5)
    assert [m.name for m in window.cfg.sounds[2:]] == ["Oof", "Bruh", "Vine boom"]
    assert all(Path(m.file).is_file() and m.duration > 0 for m in window.cfg.sounds[2:])
    assert not window._import_errors


def test_dropped_folders_open_up_into_sounds_and_zips(tmp_path):
    from soundboard.ui.widgets import expand_dropped
    d = tmp_path / "pack"
    (d / "sub").mkdir(parents=True)
    for n in ("a.mp3", "sub/b.wav", "c.zip", "notes.txt"):
        (d / n).write_bytes(b"x")
    got = expand_dropped([str(d), str(tmp_path / "x.wav")])
    assert [Path(f).name for f in got] == ["a.mp3", "c.zip", "b.wav", "x.wav"]


def test_effects_tab_has_the_trim(window):
    d = EditDialog(window.meta("s0"), window.hotkeys, lambda *a: None, window, tab="effects")
    tp = d.effects.trim
    assert not tp.isHidden() and abs(tp.length - 0.1) < 1e-3
    tp.set_values(0.02, 0.08, emit=True)
    fx = d.effects.fx()
    assert fx["start"] == 0.02 and fx["end"] == 0.08
    d.effects.preset.setCurrentText("Nightcore")   # a preset keeps the trim
    assert d.effects.fx()["start"] == 0.02 and d.effects.preset.currentText() == "Nightcore"
    d.reject()


def test_without_a_tray_close_quits_and_never_starts_hidden(window):
    if window.tray is None:
        assert not window.can_hide()
    window.cfg.setup_done = False
    assert not window.can_hide()


def test_the_tray_menu_offers_the_discord_and_feedback(window, monkeypatch):
    """Near the bottom, above Quit; both only open a page in the browser."""
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from soundboard import __version__, feedback
    from soundboard.ui import busy
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    old, quits = window.tray, QApplication.instance().quitOnLastWindowClosed()
    try:
        window._init_tray()
        acts = [a for a in window.tray.contextMenu().actions()]
        texts = [a.text() for a in acts if not a.isSeparator()]
        assert texts[-3:] == ["Join the Discord", "Send feedback", "Quit"]
        next(a for a in acts if a.text() == "Join the Discord").trigger()
        next(a for a in acts if a.text() == "Send feedback").trigger()
        assert opened == [feedback.DISCORD_URL, feedback.feedback_url(__version__)]
    finally:
        window.tray.hide()
        window.tray = old
        QApplication.instance().setQuitOnLastWindowClosed(quits)


def test_a_sound_on_the_undo_bar_isnt_taken_back_in_as_a_loose_file(window, qapp):
    """Its file is still in the sounds folder while Undo is up: the folder scan
    (set off by anything changing that folder, e.g. Recently deleted bringing one
    back) imported it again as a new sound, without its hotkey, and the bin's entry
    for it then pointed at a file that was gone."""
    import numpy as np
    import soundfile as sf

    from soundboard import library
    from soundboard.library import SR
    _loaded(window, qapp)
    m = window.meta("s1")
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    plain = library.SOUNDS_DIR / "Airhorn.wav"   # a plain name: an older or hand-put one
    t = np.arange(SR // 10) / SR   # its own sound: not a twin of Boom's
    sf.write(plain, np.stack([np.sin(2 * np.pi * 660 * t)] * 2, 1) * 0.3, SR)
    m.file, m.hotkey = str(plain), "ctrl+alt+2"
    window.remove_sound("s1")
    for _ in range(3):   # two looks at the same size = "done copying in"
        window._loose_timer.stop()
        window._take_loose()
    # an import runs on a thread: give one the time to land
    assert not process_events(qapp, lambda: len(window.cfg.sounds) > 1, timeout=3)
    assert [s.name for s in window.cfg.sounds] == ["Boom"]
    window.undo_remove()
    assert [(s.name, s.hotkey) for s in window.cfg.sounds] == [("Boom", ""),
                                                               ("Airhorn", "ctrl+alt+2")]
