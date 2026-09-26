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
