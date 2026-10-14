"""Which language the live voice listens for, and which model hears it."""
import pytest

from soundboard import i18n
from soundboard.speech import spoken


def test_every_app_language_is_heard():
    """Speech recognition hears each language the app ships in (else no Languages tab)."""
    assert [c for c in i18n.codes() if spoken.whisper_code(c) is None] == []


@pytest.mark.parametrize("code, want", [
    ("en", "en"), ("pt-BR", "pt"), ("zh-TW", "zh"), ("es-419", "es"), ("fil", "tl"),
    ("nb", "no"), ("uk", "uk"), ("tlh", None), ("", None), (None, None)])
def test_whisper_code(code, want):
    assert spoken.whisper_code(code) == want


@pytest.mark.parametrize("settings, app, want", [
    ({}, "es", "es"),                                  # nothing typed: the app's language
    ({"language": "en"}, "de", "de"),                  # the old default follows it too
    ({"language": "fr"}, "de", "fr"),                  # an old one typed in is kept
    ({"spoken": "en"}, "de", "en"),                    # English typed in on purpose
    ({"spoken": ""}, "zh-CN", "zh"),
    ({"spoken": "auto"}, "de", "auto"),
    ({"spoken": "xx"}, "ja", "ja"),                    # nonsense: the app's language
    ({}, "tlh", "en"),                                 # an app language it can't hear
])
def test_spoken(monkeypatch, settings, app, want):
    monkeypatch.setattr(i18n, "current", lambda: app)
    assert spoken.spoken(settings) == want


def test_heard(monkeypatch):
    monkeypatch.setattr(i18n, "current", lambda: "ko")
    assert spoken.heard()
    monkeypatch.setattr(i18n, "current", lambda: "tlh")
    assert not spoken.heard()


def test_model_for():
    assert spoken.model_for("base.en", "en") == "base.en"
    assert spoken.model_for("base.en", "es") == "small"    # the default: the accurate one
    assert spoken.model_for("tiny.en", "auto") == "base"   # Fastest stays fast
    assert spoken.model_for("small.en", "ja") == "small"
    assert spoken.model_for("base", "ja") == "base"        # picked by hand: kept


def test_same():
    assert spoken.same("pt-br", "pt") and spoken.same("zh-tw", "zh")
    assert spoken.same("fil", "tl")
    assert not spoken.same("zh", "es")
