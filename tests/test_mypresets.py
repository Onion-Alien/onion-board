"""Your own presets (audio/mypresets.py): saved under a name in Live controls or Edit
sound → Effects, and put back with one click."""
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from soundboard.audio import mypresets


def _pump():
    for _ in range(4):
        QApplication.processEvents()


def test_saved_presets_keep_their_order_names_and_values(tmp_path):
    assert mypresets.load("live") == {}
    assert mypresets.put("live", "  Party   mode ", {"speed": 1.2, "keep": False,
                                                    "bass": 6, "volume": 150}) == "Party mode"
    assert mypresets.put("live", "Radio host", {"pitch": -2}) == "Radio host"
    assert list(mypresets.load("live")) == ["Party mode", "Radio host"]
    assert mypresets.load("live")["Party mode"] == {"speed": 1.2, "pitch": 0.0, "keep": 0,
                                                   "bass": 6.0, "volume": 150.0}
    # the same name in another case replaces it, in its place
    mypresets.put("live", "party MODE", {"bass": 3})
    assert list(mypresets.load("live")) == ["party MODE", "Radio host"]
    # a sound's presets are a list of their own, without the trim or voice (Live
    # controls' knobs stay: Edit sound's Advanced view sets them)
    mypresets.put("sound", "Echoey", {"start": 1.0, "pitch": 3, "voice": {"fx": "Robot"},
                                      "live": [{"bass": 4}]})
    f = mypresets.load("sound")["Echoey"]
    assert f["pitch"] == 3 and f["start"] == 0 and f["voice"] == {}
    assert f["live"] == [{"bass": 4.0}]
    assert "Echoey" not in mypresets.load("live")


def test_delete_gives_back_what_undo_needs(tmp_path):
    for n in ("A", "B", "C"):
        mypresets.put("live", n, {"bass": 1})
    at, p = mypresets.remove("live", "B")
    assert list(mypresets.load("live")) == ["A", "C"]
    mypresets.put("live", "B", p, at)
    assert list(mypresets.load("live")) == ["A", "B", "C"]
    assert mypresets.rename("live", "B", "c") == ""       # another one's name
    assert mypresets.rename("live", "B", "Bee") == "Bee"
    assert list(mypresets.load("live")) == ["A", "Bee", "C"]


def test_an_unreadable_file_is_never_written_over(tmp_path):
    mypresets.path().parent.mkdir(parents=True, exist_ok=True)
    mypresets.path().write_text("{not json", encoding="utf-8")
    assert mypresets.load("live") == {}
    assert mypresets.put("live", "New", {"bass": 2}) == ""
    assert mypresets.path().read_text(encoding="utf-8") == "{not json"


def test_live_controls_save_one_and_put_it_back(qapp, monkeypatch):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    b = SpeedPitchButton("sounds")
    try:
        b.show()
        b.set_values(1.25, 2, True)
        b.set_fx({"reverb": 0.4, "volume": 150})
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Big room", True))
        b.save_preset()                     # the header's Save preset
        _pump()
        assert b.pop.isVisible()            # back open once it's named
        assert list(b.my_chips) == ["Big room"] and b.my_chips["Big room"].isChecked()
        b.reset()
        assert not b.my_chips["Big room"].isChecked()
        b.my_chips["Big room"].click()      # one click puts it all back
        assert b.values() == (1.25, 2, True)
        assert b.fx_values() == {"reverb": 0.4, "volume": 150}
        b.my_chips["Big room"].click()      # again: back to how it was
        assert b.values() == (1.0, 0.0, True) and b.fx_values() == {}
    finally:
        b.pop.close()
        b.deleteLater()


def test_a_changed_preset_can_be_updated_or_reset(qapp):
    """Your preset picked and then changed: Save preset turns into Update "name" (with
    its ▾ menu), which saves the change into it; Reset puts the saved one back."""
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    mypresets.put("live", "Loud", {"bass": 6, "treble": 5})
    b = SpeedPitchButton("sounds")
    try:
        b.show()
        b._open()
        _pump()
        assert b.save_preset_btn.accessibleName() == "Save preset"
        b.my_chips["Loud"].click()
        assert b.my_chips["Loud"].isChecked() and not b.preset_menu_btn.isVisibleTo(b.pop)
        b.set_fx({"bass": 9, "treble": 5})                     # moved Bass
        assert b.edited_preset() == "Loud"
        assert b.save_preset_btn.accessibleName() == "Update “Loud”"
        assert b.preset_menu_btn.isVisibleTo(b.pop)
        assert b.my_chips["Loud"].text().endswith("•")
        b.apply_preset("Loud")                                 # the ▾ menu's Reset
        assert b.fx_values() == {"bass": 6, "treble": 5} and b.edited_preset() == ""
        b.set_fx({"bass": 9, "treble": 5})
        b.save_preset_btn.click()                              # Update "Loud"
        assert mypresets.load("live")["Loud"]["bass"] == 9
        assert b.my_chips["Loud"].isChecked()
        assert b.save_preset_btn.accessibleName() == "Save preset"
        assert not b.preset_menu_btn.isVisibleTo(b.pop)
        b.reset()                                              # the header's Reset: not
        b.set_fx({"bass": 2})                                  # about Loud any more
        assert b.edited_preset() == "" and mypresets.load("live")["Loud"]["bass"] == 9
    finally:
        b.pop.close()
        b.deleteLater()


def test_a_built_in_name_is_refused(qapp, monkeypatch):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    b = SpeedPitchButton("sounds")
    try:
        names = iter([("nightcore", True), ("", False)])
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(names))
        told = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a))
        b.save_preset()
        assert told and mypresets.load("live") == {}
    finally:
        b.pop.close()
        b.deleteLater()


def test_a_hundred_presets_stay_on_one_line(qapp):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    for i in range(100):
        mypresets.put("live", f"Preset {i}", {"bass": i % 30 - 12, "pitch": i // 30 + 1})
    b = SpeedPitchButton("sounds")
    try:
        b.show()
        b._open()
        _pump()
        shown = list(b.my_chips)
        assert 0 < len(shown) < 100 and b.more_btn.isVisibleTo(b.pop)
        assert b.more_btn.text().startswith(f"More ({100 - len(shown)})")
        chips = [*b.my_chips.values(), b.more_btn]
        assert len({c.y() for c in chips}) == 1                       # one line
        assert max(c.geometry().right() for c in chips) < b.mine_box.width()
        # the one that's on, under More: More is lit
        b._preset_clicked("Preset 99", True)
        assert b.more_btn.isChecked() and not any(c.isChecked() for c in b.my_chips.values())
    finally:
        b.pop.close()
        b.deleteLater()


def test_delete_and_undo_while_open(qapp):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    for n in ("A", "B"):
        mypresets.put("live", n, {"bass": 2})
    b = SpeedPitchButton("sounds")
    try:
        b.show()
        b._open()
        _pump()
        b.delete_preset("A")
        assert list(b.my_chips) == ["B"] and b.undo_row.isVisible()
        b.undo_btn.click()
        assert list(b.my_chips) == ["A", "B"] and not b.undo_row.isVisible()
        b.delete_preset("B")
        b.pop.hide()                        # Undo is only while it's open
        assert not b.undo_row.isVisibleTo(b.pop) and list(mypresets.load("live")) == ["A"]
    finally:
        b.pop.close()
        b.deleteLater()


def test_edit_sound_saves_a_preset_for_every_sound(qapp, monkeypatch):
    from soundboard.ui.sounds.dialogs import MINE, EffectsPanel

    p = EffectsPanel({"pitch": 4, "gain_db": 2, "start": 1.0})
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("High", True))
    p._save_preset()
    assert p.preset.currentData() == MINE + "High" and p.delete_preset.isVisibleTo(p.fx_page)
    assert mypresets.load("sound")["High"]["start"] == 0          # never the trim

    other = EffectsPanel({"speed": 1.5})                            # another sound
    other.preset.setCurrentIndex(other.preset.findData(MINE + "High"))
    assert other.fx()["pitch"] == 4 and other.fx()["speed"] == 1.0  # the preset's, whole
    other._delete_preset()
    assert mypresets.load("sound") == {} and other.preset.findData(MINE + "High") < 0
    other._undo_delete()
    assert "High" in mypresets.load("sound")


def test_one_live_controls_can_play_is_in_both_lists(qapp, monkeypatch):
    """Edit sound's preset of only a speed, pitch and knobs is saved as Live controls'
    (it shows in its My presets too), and Live controls' show in Edit sound's box."""
    from soundboard.ui.sounds.dialogs import MINE, EffectsPanel

    p = EffectsPanel({"speed": 1.2, "tape": True, "live": [{"bass": 6}]})
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Party", True))
    p._save_preset()
    assert mypresets.load("live")["Party"] == {"speed": 1.2, "pitch": 0.0, "keep": 0,
                                               "bass": 6.0}
    assert "Party" not in mypresets.load("sound")
    mypresets.put("live", "Radio host", {"pitch": -2, "treble": 4})
    other = EffectsPanel({})
    other.preset.setCurrentIndex(other.preset.findData(MINE + "Radio host"))
    assert other.fx()["pitch"] == -2 and other.fx()["live"] == [{"treble": 4.0}]
    other._delete_preset()                                          # from Live's list
    assert "Radio host" not in mypresets.load("live")
    other._undo_delete()
    assert "Radio host" in mypresets.load("live")


def test_a_reused_edit_window_starts_clean(qapp, monkeypatch):
    """Edit sound is reused for the next sound: the last one's "Deleted … Undo" row
    went with it, and presets saved in another window since weren't in the list."""
    from soundboard.sounds.library import SoundMeta
    from soundboard.ui.sounds.dialogs import MINE, EffectsPanel

    mypresets.put("sound", "Gone", {"pitch": 2})
    p = EffectsPanel({"pitch": 2})
    p._delete_preset()
    assert not p.undo_row.isHidden()
    other = EffectsPanel({})                      # another window, open meanwhile
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("New", True))
    other._save_preset()
    p.set_sound(SoundMeta(id="x", name="x", file="", fx={"speed": 1.5}))
    assert p.undo_row.isHidden() and p._deleted is None
    assert p.preset.findData(MINE + "New") >= 0 and p.preset.findData(MINE + "Gone") < 0
