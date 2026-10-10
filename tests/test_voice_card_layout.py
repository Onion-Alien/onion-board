"""Card actions stay above their choices; square fold arrows have usable content boxes."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QStyleOptionButton

from soundboard import theme
from soundboard import modules
from soundboard.speech.aivoice import AiVoiceController
from soundboard.speech import tts
from soundboard.ui.aivoicepanel import AiVoicePanel
from soundboard.ui.voicepanel import VoicePanel
from soundboard.voicefx import VoiceChain
from tests.test_voicepanel import FakeEngine


@pytest.mark.parametrize("name", ["Dark", "Light", "High Contrast", "Retro 98"])
def test_all_voice_card_arrows_keep_centered_content(qapp, monkeypatch, name):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    old = theme.current_name
    theme.apply(qapp, name)
    panel = VoicePanel(FakeEngine(), {}, {})
    try:
        buttons = [head.arrow for head in panel._heads.values()]
        buttons += [row.arrow for row in panel.fx.rows.values()]
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
def test_ai_action_precedes_choices_and_status_wraps(qapp, monkeypatch, tmp_path, width):
    monkeypatch.setattr("soundboard.ui.aivoicepanel.model_downloaded", lambda m: True)
    monkeypatch.setattr("soundboard.ui.aivoicepanel.read_voices", lambda m: [
        {"id": "bear", "name": "Bear", "description": "A deep voice."}])
    module = modules.ModuleInfo("ai-voices", "AI voices", "1", "", "service", tmp_path)
    panel = AiVoicePanel(AiVoiceController(VoiceChain(), lambda ev: None), {}, [module])
    try:
        panel.setFixedWidth(width)
        panel._set_ui(True, "Starting: a built-in voice covers you until the AI voice is ready.")
        panel.show()
        qapp.processEvents()
        assert panel.b_start.geometry().bottom() < panel.cb_voice.geometry().top()
        assert panel.ready_box.rect().contains(panel.lbl_state.geometry())
        assert panel.ready_box.rect().contains(panel.cb_voice.geometry())
        panel._set_ui(False, "Ready")
        assert not panel.b_start.isChecked()
        assert panel.lbl_state.text() == "Ready"
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
