"""The language drop-down: a row per language, search in any name, Enter or a click
picks, Esc picks nothing, ↑/↓ walk the list."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from soundboard import i18n
from soundboard.ui.langpick import ROW_H, LanguageDialog, glyph


def test_a_tile_per_language_english_first_the_one_showing_ticked(qapp):
    d = LanguageDialog(current="en")
    codes = [t.code for t in d.tiles]
    assert codes[0] == "en" and set(codes) == set(i18n.codes())
    assert [t.code for t in d.tiles if t.isChecked()] == ["en"]
    de = next(t for t in d.tiles if t.code == "de")
    assert (de.own, de.other, de.mark) == ("Deutsch", "German", "ß")


def test_search_finds_a_language_by_any_of_its_names(qapp):
    d = LanguageDialog()

    def find(text):
        d.search.setText(text)
        return [t.code for t in d.visible_tiles()]
    assert find("deutsch") == ["de"] and find("GERMAN") == ["de"]
    assert find("日本") == ["ja"] and find("japanese") == ["ja"]
    assert set(find("espanol")) == {"es-419", "es"}           # without the accent
    assert set(find("portug")) == {"pt-BR", "pt-PT"}
    assert d.scroll.height() == 2 * (ROW_H + 2)               # shrinks to the two rows
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


def test_every_language_has_its_own_letter():
    marks = [glyph(c, own) for c, own in i18n.available()]
    assert len(set(marks)) == len(marks)                 # no two coins alike
    assert glyph("ar", "العربية") == "ع" and glyph("ja", "日本語") == "あ"
    # one added later without a letter: its name's first letters, as one sign
    assert glyph("xx", "हिन्दी") == "हि"           # the vowel sign stays on its letter


def test_the_drop_down_stays_narrow_and_opens_under_its_button(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QPushButton
    b = QPushButton("English")
    b.resize(160, 40)
    b.show()
    d = LanguageDialog(current="en")
    d.open_under(b)
    try:
        assert d.width() <= 620 and d.isVisible()
        top = b.mapToGlobal(QPoint(0, 0)).y()
        assert d.y() >= top + b.height() or d.y() + d.height() <= top   # never over it
    finally:
        d.close()
        b.close()


def test_arrow_keys_walk_the_list_and_enter_picks(qapp):
    d = LanguageDialog(current="en")
    d.show()
    d.search.setText("port")
    QTest.keyClick(d.search, Qt.Key_Down)
    rows = d.visible_tiles()
    assert rows[0].hasFocus()
    QTest.keyClick(rows[0], Qt.Key_Down)
    QTest.keyClick(rows[1], Qt.Key_Return)
    assert d.picked == rows[1].code
