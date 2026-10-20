"""The Voice tab's tabs; card actions stay above their choices; square fold arrows
have usable content boxes."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QStyle, QStyleOptionButton

from soundboard.ui.kit import theme
from soundboard.addons import modules
from soundboard.speech.aivoice import AiVoiceController
from soundboard.speech import tts
from soundboard.ui.voice.aivoicepanel import AiVoicePanel
from soundboard.ui.voice.voicepanel import VoicePanel
from soundboard.voicefx import VoiceChain
from tests.test_voicepanel import FakeEngine


def at(w, ancestor):
    """`w`'s rectangle in `ancestor`'s coordinates (it may sit in a box inside it)."""
    return w.geometry().translated(w.parentWidget().mapTo(ancestor, QPoint(0, 0)))


def test_tabs_show_one_card_and_the_tab_is_remembered(qapp, monkeypatch):
    """One card at a time under the row of tabs; the tab you pick opens next time."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    panel = VoicePanel(FakeEngine(), {}, {"folded": ["ai", "fx.echo"]})   # an old save
    saved = []
    panel.speech_changed.connect(saved.append)
    try:
        panel.resize(1000, 800)
        panel.show()
        qapp.processEvents()
        assert panel.current_tab() == "fx" and panel._tabs["fx"].isChecked()
        assert [k for k, c in panel._cards.items() if c.isVisibleTo(panel)] == ["fx"]
        panel._tabs["speak"].click()
        qapp.processEvents()
        assert [k for k, c in panel._cards.items() if c.isVisibleTo(panel)] == ["speak"]
        assert panel.speech.isVisibleTo(panel) and saved[-1]["tab"] == "speak"
        assert saved[-1]["folded"] == ["ai", "fx.echo"]   # left as an older version wrote it
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
    again = VoicePanel(FakeEngine(), {}, saved[-1])
    try:
        assert again.current_tab() == "speak" and again._tabs["speak"].isChecked()
    finally:
        again.shutdown()
        again.deleteLater()
    junk = VoicePanel(FakeEngine(), {}, {"tab": 7})   # a damaged setting: the first tab
    try:
        assert junk.current_tab() == "fx"
    finally:
        junk.shutdown()
        junk.deleteLater()


@pytest.mark.parametrize("name", ["Dark", "Light", "High Contrast", "Retro 98"])
def test_all_voice_card_arrows_keep_centered_content(qapp, monkeypatch, name):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    old = theme.current_name
    theme.apply(qapp, name)
    panel = VoicePanel(FakeEngine(), {}, {})
    try:
        buttons = [row.arrow for row in panel.fx.rows.values()]
        for button in buttons:
            button.ensurePolished()
            for focused in (False, True):
                option = QStyleOptionButton()
                button.initStyleOption(option)
                if focused:
                    option.state |= QStyle.State_HasFocus
                else:
                    option.state &= ~QStyle.State_HasFocus
                content = button.style().subElementRect(QStyle.SE_PushButtonContents,
                                                        option, button)
                assert button.rect().contains(content)
                assert content.center() == button.rect().center()
                assert content.width() >= button.iconSize().width()
                assert content.height() >= button.iconSize().height()
                assert button.focusPolicy() == Qt.TabFocus
    finally:
        panel.shutdown()
        panel.deleteLater()
        theme.apply(qapp, old)


@pytest.mark.parametrize("width", [340, 580])
def test_ai_status_sits_over_the_voices_and_wraps(qapp, monkeypatch, tmp_path, width):
    """The AI voices card's status (its switch is in the card's head, as the voice
    changer's): one line under the card's words, wrapping inside the card and above
    the voices; switched off, it goes."""
    monkeypatch.setattr("soundboard.ui.voice.aivoicepanel.model_downloaded", lambda m: True)
    monkeypatch.setattr("soundboard.ui.voice.aivoicepanel.read_voices", lambda m: [
        {"id": "bear", "name": "Bear", "description": "A deep voice."}])
    module = modules.ModuleInfo("ai-voices", "AI voices", "1", "", "service", tmp_path)
    panel = AiVoicePanel(AiVoiceController(VoiceChain(), lambda ev: None), {}, [module])
    try:
        panel.setFixedWidth(width)
        panel._set_ui(True, "Starting: a built-in voice covers you until the AI voice is ready.")
        panel.show()
        qapp.processEvents()
        state = at(panel.lbl_state, panel)
        assert panel.rect().contains(state)
        assert state.height() >= panel.lbl_state.heightForWidth(state.width())
        assert state.bottom() < at(panel._tile["bear"], panel).top()
        assert panel.rect().contains(at(panel._tile["bear"], panel))
        panel._set_ui(False, "")
        assert not panel.b_start.isChecked() and panel.b_start.text() == "Off"
        assert panel.lbl_state.isHidden()
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()


def test_no_empty_language_frame_before_speech_recognition_is_in(qapp, monkeypatch):
    """Not installed yet: the language cards are hidden, and so is the frame under them
    (alone it was an empty box under Install speech recognition). Installed: the cards,
    and the frame only once a language is on."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    panel = VoicePanel(FakeEngine(), {}, {"tab": "speak"})
    speech = panel.speech
    try:
        panel.show()
        qapp.processEvents()
        assert speech.installs.missing.isVisibleTo(speech)
        assert not speech.lang_box.isVisibleTo(speech)
        assert not speech.settings_box.isVisibleTo(speech)
        assert not speech.cards.isVisibleTo(speech)
        speech.show_lang_box(True)
        assert speech.cards.isVisibleTo(speech)
        assert not speech.settings_box.isVisibleTo(speech)   # no language on: no box
        speech.cb_lang.setCurrentIndex(speech.cb_lang.findData("de"))
        assert speech.settings_box.isVisibleTo(speech)
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()


def test_languages_card_has_no_gap_while_the_state_says_nothing(qapp, monkeypatch):
    """Installed and idle: the cards sit one spacing under the intro, like AI voices'
    (an empty state row left a tall gap); a state line opens the row again."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    panel = VoicePanel(FakeEngine(), {}, {"tab": "speak"})
    speech = panel.speech
    live = speech.livevoice
    try:
        live.set_installed(True)
        speech.show_lang_box(True)
        live.lbl_state.setText("")
        panel.resize(1000, 800)
        panel.show()
        qapp.processEvents()
        assert not live.start_box.isVisibleTo(speech)
        gap = at(speech.cards, speech).top() - at(speech.lbl_intro, speech).bottom() - 1
        assert gap == speech.layout().spacing()
        live.lbl_state.setText("● listening")
        qapp.processEvents()
        assert live.start_box.isVisibleTo(speech)
        assert at(speech.lbl_intro, speech).bottom() < at(live.start_box, speech).top()
        live.set_installed(False)
        assert not live.start_box.isVisibleTo(speech)
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()


@pytest.mark.parametrize("name", ["Dark", "Light"])
@pytest.mark.parametrize("width", [340, 580])
def test_languages_card_reads_cards_then_who_says_it(qapp, monkeypatch, tmp_path,
                                                   name, width):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    old = theme.current_name
    theme.apply(qapp, name)
    panel = VoicePanel(FakeEngine(), {}, {})
    speech = panel.speech
    try:
        speech.setParent(None)
        speech.title.show()
        speech.livevoice.set_installed(True)
        speech.show_lang_box(True)
        speech.cb_lang.setCurrentIndex(speech.cb_lang.findData("de"))
        speech.setFixedWidth(width)
        live = speech.livevoice
        live.lbl_state.setText("Starting: the computer voice is getting ready to speak "
                               "your words in the selected language.")
        speech.show()
        qapp.processEvents()
        # as AI voices: the words, how it's doing, the cards, then who says it
        assert at(speech.lbl_intro, speech).bottom() < at(live.start_box, speech).top()
        assert at(live.start_box, speech).bottom() < at(speech.cards, speech).top()
        assert at(speech.cards, speech).bottom() < at(speech.settings_box, speech).top()
        assert live.start_box.rect().contains(live.lbl_state.geometry())
        assert live.lbl_state.wordWrap()
        # the computer voice's own Start: under More options, not a big button
        assert live.b_live.parentWidget() is speech.opts
        assert speech.cb_lang.isHidden() and speech.lbl_lang.isHidden()
        speech.grab().save(str(tmp_path / f"computer-voice-{name}-{width}.png"))
    finally:
        speech.close()
        speech.setParent(panel)
        panel.shutdown()
        panel.deleteLater()
        theme.apply(qapp, old)


def test_voice_changer_switch_heads_the_card_and_picked_bar_holds_actions(qapp):
    from soundboard.ui.voice.voicepanel import VoiceFxPanel
    panel = VoiceFxPanel({})
    try:
        # the switch goes in the card's title row (VoicePanel puts `head` there); the
        # description comes first in the panel, the picked voice's bar last
        assert panel.btn_power.parentWidget() is panel.head
        layout = panel.layout()
        assert isinstance(layout.itemAt(1).widget(), QLabel)
        assert layout.itemAt(1).widget().wordWrap()
        assert panel.btn_tweak.parentWidget() is panel.picked
        assert not hasattr(panel, "btn_hear")   # hearing it: the mixer's one switch
        assert layout.itemAt(layout.count() - 1).widget() is panel.picked
    finally:
        panel.close()
        panel.deleteLater()


def test_a_short_window_scrolls_the_picked_voice_bar_with_the_voices(qapp, monkeypatch):
    """Pinned under the voices; in a short window (the fitter's step) it goes to the end
    of the voice changer's card instead, still there, and comes back when there's room."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    panel = VoicePanel(FakeEngine(), {}, {})
    try:
        picked = panel.fx.picked
        step = next(fn for _p, axis, fn in panel.fit_steps() if axis == "h")
        assert picked.parentWidget() is panel and picked.property("pinned")
        step(True)
        assert picked.parentWidget() is panel.fx and not picked.property("pinned")
        lay = panel.fx.layout()
        assert lay.itemAt(lay.count() - 1).widget() is picked
        step(False)
        assert picked.parentWidget() is panel and picked.property("pinned")
        panel.show_tab("ai")
        assert not picked.isVisibleTo(panel)
    finally:
        panel.shutdown()
        panel.deleteLater()
