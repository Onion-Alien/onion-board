"""The language picker window: a tile per language, search in any name, Enter or a
click picks, ✕ / Esc picks nothing."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from soundboard import i18n
from soundboard.ui.langpick import LanguageDialog, glyph


def test_a_tile_per_language_english_first_the_one_showing_ticked(qapp):
    d = LanguageDialog(current="en")
    codes = [t.code for t in d.tiles]
    assert codes[0] == "en" and set(codes) == set(i18n.codes())
    assert [t.code for t in d.tiles if t.isChecked()] == ["en"]
    de = next(t for t in d.tiles if t.code == "de")
    assert (de.own, de.other, de.mark) == ("Deutsch", "German", "De")


def test_search_finds_a_language_by_any_of_its_names(qapp):
    d = LanguageDialog()

    def find(text):
        d.search.setText(text)
        return [t.code for t in d.visible_tiles()]
    assert find("deutsch") == ["de"] and find("GERMAN") == ["de"]
    assert find("日本") == ["ja"] and find("japanese") == ["ja"]
    assert set(find("espanol")) == {"es-419", "es"}           # without the accent
    assert set(find("portug")) == {"pt-BR", "pt-PT"}
    assert find("zz-nothing") == [] and d.none.isVisibleTo(d)
    assert len(find("")) == len(d.tiles) and not d.none.isVisibleTo(d)


def test_a_click_or_enter_picks_and_esc_picks_nothing(qapp):
    d = LanguageDialog()
    got = []
    d.chosen.connect(got.append)
    next(t for t in d.tiles if t.code == "ko").click()
    assert got == ["ko"] and d.picked == "ko" and d.result() == QDialog.Accepted
    d = LanguageDialog()
    d.search.setText("svenska")
    QTest.keyClick(d.search, Qt.Key_Return)
    assert d.picked == "sv"
    d = LanguageDialog()
    d.show()
    QTest.keyClick(d, Qt.Key_Escape)
    assert d.picked == "" and d.result() == QDialog.Rejected


def test_marks_read_as_one_sign_in_each_script():
    assert glyph("hi", "हिन्दी") == "हि"           # the vowel sign stays on its letter
    assert glyph("ar", "العربية") == "ع"
    assert glyph("ja", "日本語") == "日本"
    assert glyph("id", "Bahasa Indonesia") != glyph("ms", "Bahasa Melayu")


def test_the_window_stays_narrow(qapp):
    d = LanguageDialog()
    assert d.width() <= 620
