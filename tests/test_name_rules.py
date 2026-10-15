"""Typed names (categories, subcategories, sounds) follow one set of rules and say so
when a name can't be used as typed; a restored backup brings back a removed pad that
shared its audio with one still here; the other-soundboard question says where the
sounds go."""
import pytest
from PySide6.QtWidgets import QMessageBox

from soundboard import backup, library
from soundboard.otherboards import Entry, soundpad
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    main_window.said = said = []
    monkeypatch.setattr(main_window, "toast", lambda msg, *a, **k: said.append(msg))
    return main_window


def test_one_line_names():
    assert library.one_line("  a\tb\n\nc  ") == "a b c"
    assert library.plain_name("a\t/\tb") == "a - b"


@pytest.mark.parametrize("typed", ["", "   ", "\t\n"])
def test_an_empty_category_name_says_so(window, typed):
    assert window.catctl.new_category(name=typed) == ""
    assert window.said == ["Type a name first."]
    assert window.cfg.categories == []


def test_a_cancelled_box_says_nothing(window, monkeypatch):
    from soundboard.ui import categorycontrol
    monkeypatch.setattr(categorycontrol.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("", False)))
    assert window.catctl.new_category() == ""
    window.soundctl.rename_sound("s0")
    assert window.said == []


def test_a_long_category_name_is_cut_and_says_so(window):
    name = window.catctl.new_category(name="M" * 60)
    assert name == "M" * library.CATEGORY_MAX and window.cfg.categories == [name]
    assert window.said == [f"Names can be up to 30 characters, so it's “{name}”."]
    window.said.clear()
    window.catctl.rename_category(name, "Short")
    assert window.said == ["✓ Renamed to “Short”"]


def test_tabs_and_line_breaks_in_a_category_name_are_spaces(window):
    assert window.catctl.new_category(name="a\tb\nc") == "a b c"
    window.catctl.rename_category("a b c", "   ")
    assert window.cfg.categories == ["a b c"] and window.said == ["Type a name first."]


def test_a_subcategory_cant_have_its_categorys_name(window):
    window.catctl.new_category(name="Memes")
    window.said.clear()
    assert window.catctl.new_subcategory("Memes", name="memes") == ""
    assert window.said == ["There's already a “Memes”."]
    assert window.catctl.new_subcategory("Memes", name="Vine") == "Vine"
    window.said.clear()
    window.catctl.rename_subcategory("Vine", "Memes")
    assert window.cfg.subcategories == {"Memes": ["Vine"]}
    assert window.said == ["There's already a “Memes”."]


def test_sound_rename_rules(window):
    rename = window.soundctl.rename_sound
    rename("s0", "N" * 60)
    assert window.meta("s0").name == "N" * library.SOUND_NAME_MAX
    assert window.said[-1].startswith("Names can be up to 40 characters")
    rename("s0", "   ")
    assert window.meta("s0").name == "N" * 40 and window.said[-1] == "Type a name first."
    rename("s0", "a\tb")
    assert window.meta("s0").name == "a b" and window.said[-1] == "✓ Renamed to “a b”"
    rename("s0", "airhorn")   # s1 is "Airhorn": allowed, but said
    assert window.meta("s0").name == "airhorn"
    assert window.said[-1] == "✓ Renamed to “airhorn”. Another sound has that name too."


def test_a_removed_pad_sharing_audio_comes_back_from_its_backup(window, tmp_path):
    # the fixture's Boom and Airhorn are the same tone, like "Save as new sound" pads
    for m in window.cfg.sounds:
        m.fingerprint = library.fingerprint(m.file)
    out = tmp_path / "b.zip"
    backup.export(out, window.cfg.sounds, None, window.cfg.categories)
    boom = [m for m in window.cfg.sounds if m.name == "Boom"]
    known = {m.fingerprint: {m.name.lower()} for m in boom}
    res = backup.install(backup.read(out), known)
    assert [m.name for m in res.sounds] == ["Airhorn"] and res.skipped == ["Boom"]
    # a plain set of fingerprints still skips every sound with one
    assert backup.install(backup.read(out), set(known)).skipped == ["Boom", "Airhorn"]


def test_the_import_question_says_which_category_they_go_in(window, monkeypatch):
    asked = []
    no = QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question",
                        lambda _w, _t, text, *a: asked.append(text) or no)
    entry = Entry(name="x", path="C:/x.wav", exists=True)
    window.impctl._board_read(soundpad.SOURCE, "C:/b.spl", True, ([entry], [], [entry]))
    assert "They go in a category called “Soundpad”." in asked[0]
