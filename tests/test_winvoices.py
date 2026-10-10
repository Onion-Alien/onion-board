"""Installing Windows voices: what the elevated scripts' answers mean (nothing runs)."""
import pytest

from soundboard.speech import winvoices


def test_locale_for_a_language():
    assert winvoices.locale_for("zh") == "zh-CN"
    assert winvoices.locale_for("pt") == "pt-BR"
    assert winvoices.locale_for("zh-TW") == "zh-TW"
    assert winvoices.locale_for("xx") == "xx-XX"


def test_voice_tokens_are_matched_to_their_language():
    tokens = frozenset({"MSTTS_V110_enUS_ZiraM", "TTS_MS_ZH-CN_HUIHUI_11.0"})
    assert winvoices.has_language(tokens, "zh")
    assert winvoices.has_language(frozenset({"MSTTS_V110_zhCN_YaoyaoM"}), "zh")
    assert winvoices.has_language(tokens, "en")
    assert not winvoices.has_language(tokens, "de")
    assert not winvoices.has_language(tokens, "zh-TW")     # a country wants its own voice
    assert winvoices.has_language(frozenset({"MSTTS_V110_zhTW_HanHanM"}), "zh-TW")
    assert winvoices.has_language(frozenset({"MSTTS_V110_ptBR_MariaM"}), "pt-BR")


def test_installer_answers():
    assert winvoices.outcome(0, "", "OK Language.TextToSpeech~~~zh-CN~0.0.1.0") == "ok"
    assert winvoices.outcome(0, "", "RESTART x  ") == "restart"
    assert winvoices.outcome(0, "", "ALREADY x") == "already"
    with pytest.raises(RuntimeError, match="0x800f0954"):
        winvoices.outcome(1, "", "ERR Add-WindowsCapability failed. 0x800f0954")
    with pytest.raises(winvoices.Cancelled):
        winvoices.outcome(1223, "The operation was canceled by the user.", "")
    with pytest.raises(RuntimeError, match="without saying why"):
        winvoices.outcome(5, "", "")


def test_a_uac_no_is_known_by_its_code_not_its_words():
    with pytest.raises(winvoices.Cancelled):              # a German Windows
        winvoices.outcome(1223, "Der Vorgang wurde vom Benutzer abgebrochen.", "")
    with pytest.raises(RuntimeError, match="not found"):  # any other failure to start
        winvoices.outcome(1, "powershell.exe was not found", "")
    assert "NativeErrorCode -eq 1223" in winvoices._OUTER


def test_paths_with_an_apostrophe_stay_inside_their_quotes():
    assert winvoices._ps_quote(r"D:\Sounds\O'Brien\x.txt") == r"D:\Sounds\O''Brien\x.txt"
    assert "'\"__OUT__\"'" in winvoices._OUTER and "'\"__SCRIPT__\"'" in winvoices._OUTER


def test_fingerprint_is_a_set_of_names():
    fp = winvoices.fingerprint()
    assert isinstance(fp, frozenset) and all(isinstance(n, str) for n in fp)
