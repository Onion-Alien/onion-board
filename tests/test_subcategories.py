"""Subcategories: a category with groups inside it (chips under the tabs), and a free pack
landing as one tab with its own categories as subcategories."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from soundboard.sounds import library
from soundboard.sounds.library import SUB_SEP, Config, SoundMeta
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_tag_helpers_keep_subcategories_in_one_tag():
    assert library.sub_tag("Memes", "Vine") == f"Memes{SUB_SEP}Vine"
    assert library.split_tag("Memes / Vine") == ("Memes", "Vine")
    assert library.split_tag("AC/DC") == ("AC/DC", "")
    long = "x" * 40
    assert library.clean_tags([f"{long} / {long}"]) == [f"{'x' * 30} / {'x' * 30}"]
    assert library.plain_name("a / b") == "a - b"   # can't be typed into a sub tag


def test_in_view_matches_the_category_then_its_subcategory():
    tags = ["Memes", "Memes / Vine"]
    assert library.in_view(tags, "")
    assert library.in_view(tags, "Memes") and library.in_view(tags, "Memes", "Vine")
    assert not library.in_view(["Memes"], "Memes", "Vine")


def test_merge_tags_makes_no_tab_for_a_subcategory():
    cats, subs = ["Memes"], {}
    out = library.merge_tags(["memes / Vine", "Music"], cats, subs)
    assert out == ["Memes", "Memes / Vine", "Music"]
    assert cats == ["Memes", "Music"] and subs == {"Memes": ["Vine"]}


def test_a_saved_board_finds_its_subcategories_again():
    cfg = Config.from_raw({"categories": ["Memes"], "category": "Memes",
                           "subcategory": "Vine", "subcategories": {"Memes": ["Vine"]},
                           "sounds": []})
    assert cfg.subcategories == {"Memes": ["Vine"]} and cfg.subcategory == "Vine"
    gone = Config.from_raw({"categories": ["Memes"], "category": "Memes",
                            "subcategory": "Nope", "sounds": []})
    assert gone.subcategory == "" and gone.subcategories == {}


def test_a_sub_tab_an_older_version_saved_is_a_subcategory_again():
    cfg = Config.from_raw({"categories": ["Memes", "Memes / Vine", "Music"],
                           "subcategories": {"Memes": ["Vine"]},
                           "sounds": [{"id": "a", "name": "a", "path": "a.wav",
                                       "tags": ["Memes", "Memes / Vine"]}]})
    assert cfg.categories == ["Memes", "Music"]
    assert cfg.subcategories == {"Memes": ["Vine"]}


def test_a_pack_becomes_one_tab_with_its_categories_inside():
    sounds = [SimpleNamespace(tags=["Tavern"]), SimpleNamespace(tags=["Combat", "Mine"])]
    assert library.group_pack_tags(sounds, "GM starter pack")
    assert sounds[0].tags == ["GM starter pack", "GM starter pack / Tavern"]
    assert sounds[1].tags == ["GM starter pack", "GM starter pack / Combat",
                              "GM starter pack / Mine"]


def test_tidying_only_moves_the_packs_own_categories():
    s = SimpleNamespace(tags=["Tavern", "Favourites"])
    assert library.group_pack_tags([s], "GM", own={"tavern"})
    assert s.tags == ["GM", "GM / Tavern", "Favourites"]
    again = SimpleNamespace(tags=["GM", "GM / Tavern"])
    assert not library.group_pack_tags([again], "GM", own={"tavern"})


def test_add_filter_rename_and_delete_a_subcategory(window, monkeypatch):
    w = window
    monkeypatch.setattr("soundboard.ui.window.mainwindow.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    w.catctl.new_category(name="Memes")
    w.meta("s0").tags = ["Memes"]
    w.meta("s1").tags = ["Memes"]
    w.catctl.set_category("Memes")
    assert w.catctl.new_subcategory("Memes", "s0", "Vine") == "Vine"
    assert w.meta("s0").tags == ["Memes", "Memes / Vine"]
    assert "Vine" not in w.cfg.categories               # no tab of its own
    assert not w.catctl._sub_row.isHidden() or not w.isVisible()
    w.catctl.set_subcategory("Vine")
    assert [m.id for m in w.catctl.category_sounds()] == ["s0"]
    assert w.pads["s1"].property("filtered") and not w.pads["s0"].property("filtered")
    w.catctl.rename_subcategory("Vine", "Clips")
    assert w.cfg.subcategories == {"Memes": ["Clips"]} and w.cfg.subcategory == "Clips"
    assert w.meta("s0").tags == ["Memes", "Memes / Clips"]
    w.catctl.rename_category("Memes", "Funny")
    assert w.cfg.subcategories == {"Funny": ["Clips"]}
    assert w.meta("s0").tags == ["Funny", "Funny / Clips"]
    w.catctl.set_category("Funny")
    w.catctl.delete_subcategory("Clips")                         # asks only when it has sounds
    assert w.cfg.subcategories == {} and w.meta("s0").tags == ["Funny"]


def test_plus_subcategory_opens_a_name_box_in_the_chip_row(window):
    """"+ Subcategory" swaps itself for a box where the new chip goes: Enter adds
    it, Esc doesn't. No pop-up."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    w = window
    w.tabs.setCurrentWidget(w.sounds_page)
    w.show()
    w.catctl.new_category(name="Memes")
    w.catctl.new_subcategory("Memes", "s0", "Vine")
    box = w.catctl.sub_name_box
    size, pad_y = box.button.size(), w.pads["s0"].y()
    box.button.click()
    QApplication.processEvents()
    assert box.isVisible() and not box.button.isVisible()
    assert box.size() == size and w.pads["s0"].y() == pad_y   # nothing moves
    QTest.keyClicks(box, "Old")
    QTest.keyClick(box, Qt.Key.Key_Escape)
    assert w.cfg.subcategories == {"Memes": ["Vine"]} and box.button.isVisible()
    box.button.click()
    QTest.keyClicks(box, "Clips")
    QTest.keyClick(box, Qt.Key.Key_Return)
    assert w.cfg.subcategories == {"Memes": ["Vine", "Clips"]}
    assert w.cfg.subcategory == "Clips"


def test_switching_tab_leaves_the_subcategory_and_all_shows_everything(window):
    w = window
    w.catctl.new_category(name="Memes")
    w.catctl.new_category(name="Music")
    w.meta("s0").tags = ["Memes"]
    w.catctl.new_subcategory("Memes", "s0", "Vine")
    w.catctl.set_category("Memes")
    w.catctl.set_subcategory("Vine")
    w.catctl.set_category("Music")
    assert w.cfg.subcategory == ""
    w.catctl.set_category("Memes")
    assert w.cfg.subcategory == ""
    assert not w.pads["s0"].property("filtered")


def test_taking_a_sound_out_of_a_category_takes_it_out_of_its_subcategories(window):
    w = window
    w.catctl.new_category(name="Memes")
    w.meta("s0").tags = ["Memes"]
    w.catctl.new_subcategory("Memes", "s0", "Vine")
    w.catctl.toggle_tag("s0", "Memes / Vine")                   # out of the subcategory only
    assert w.meta("s0").tags == ["Memes"]
    w.catctl.toggle_tag("s0", "Memes / Vine")
    w.catctl.toggle_tag("s0", "Memes")
    assert w.meta("s0").tags == []


def test_deleting_a_category_takes_its_subcategories_with_it(window, monkeypatch):
    w = window
    w.catctl.new_category(name="Memes")
    w.meta("s0").tags = ["Memes"]
    w.catctl.new_subcategory("Memes", "s0", "Vine")
    monkeypatch.setattr("soundboard.ui.window.mainwindow.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    w.catctl.delete_category("Memes")
    assert w.cfg.subcategories == {} and w.meta("s0").tags == []
    assert isinstance(w.meta("s0"), SoundMeta)


def test_the_window_starts_on_a_category_with_subcategories(qapp, app_dir, monkeypatch):
    """The category bar is built before the pads: starting on a tab with chips once tried
    to line the toolbar up with a grid that wasn't there yet (2.1.0 start-up crash)."""
    from soundboard.audio import engine
    from soundboard.control import winkeys
    from soundboard.ui.window import mainwindow as main
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config.from_raw({"categories": ["Memes"], "category": "Memes",
                     "subcategories": {"Memes": ["Vine"]}, "sounds": []}).save()
    w = main.MainWindow()
    try:
        w.soundctl._load_thread.join(15)
        assert w.catctl._sub_flow.count() > 0   # the chips are there
    finally:
        w.close()
        w.soundctl._load_thread.join(15)
        w.deleteLater()
