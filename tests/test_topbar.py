"""The one look of the bars across the top of the window (ui/kit/topbar.py)."""
from PySide6.QtWidgets import QApplication

from soundboard.ui.kit.topbar import TopBar, split_heading


def test_the_first_sentence_is_the_heading():
    assert split_heading("FFmpeg is missing. Videos can't be saved.") == (
        "FFmpeg is missing.", "Videos can't be saved.")
    assert split_heading("Important fix in Onion Board 2.3.1: sounds stopped.") == (
        "Important fix in Onion Board 2.3.1:", "sounds stopped.")   # not at "2.3"
    assert split_heading("ずっと使える。設定で変更できます。") == (
        "ずっと使える。", "設定で変更できます。")
    assert split_heading("One sentence only.") == ("", "One sentence only.")
    assert split_heading("Getting FFmpeg… 42%") == ("", "Getting FFmpeg… 42%")


def test_text_is_plain_and_kept_whole(qapp):
    bar = TopBar()
    bar.set_message("It's <b>not</b> HTML. Shown as typed.")
    assert bar.text() == "It's <b>not</b> HTML. Shown as typed."
    assert "&lt;b&gt;" in bar.words.text() and "It's" in bar.words.text()
    bar.set_message("Using <b>Discord</b>. Set up?", rich=True)
    assert "<b>Discord</b>" in bar.words.text()


def test_icon_buttons_and_close_stay_centred_when_the_words_wrap(qapp):
    bar = TopBar("warn", "warn")
    bar.add_button("Not now")
    bar.add_button("Fix it", primary=True)
    bar.resize(600, 10)
    bar.show()
    heights = []
    for words in ("Short. One line.", "A long reason. " + "It keeps going on and on. " * 12):
        bar.set_message(words)
        bar.resize(600, bar.layout().totalHeightForWidth(600))
        QApplication.processEvents()
        mid = bar.height() / 2
        for w in (bar.icon, bar.close_btn, *(bar.buttons.itemAt(i).widget()
                                     for i in range(bar.buttons.count()))):
            assert abs(w.geometry().center().y() + 0.5 - mid) <= 1.0, w
        heights.append(bar.height())
    assert heights[1] > heights[0] * 1.8   # the long one really wrapped
    bar.close()


def test_tone_colours_the_stripe(qapp):
    bar = TopBar()
    for tone in ("info", "warn", "ok"):
        bar.set_tone(tone)
        assert bar.property("tone") == tone
    bar.set_tone("nonsense")
    assert bar.property("tone") == "info"
