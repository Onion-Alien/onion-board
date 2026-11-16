"""A voice signal that runs while the Voice tab is still being built (the loading
screen runs queued signals during its imports) must not crash the start."""
from soundboard.speech import tts
from soundboard.ui.voice import voicepanel
from test_voicepanel import FakeEngine


def _build(monkeypatch, engine):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    real = voicepanel.VoicePanel._follow_offline

    def early(self):
        # what the Windows voices arriving mid-build do: lang_changed -> _emit_active,
        # before the warning's panel is made
        assert getattr(self, "oops", None) is None
        self._emit_active()
        real(self)

    monkeypatch.setattr(voicepanel.VoicePanel, "_follow_offline", early)
    return voicepanel.VoicePanel(engine, {"enabled": False, "effects": {}},
                                 {"voice": "Microsoft Zira Desktop"})


def test_early_flip_does_not_crash(qapp, monkeypatch):
    p = _build(monkeypatch, FakeEngine())
    try:
        assert p._oops_for == ""
        assert not p.oops.isVisibleTo(p)
    finally:
        p.shutdown()
        p.deleteLater()


def test_warning_that_applies_at_start_still_shows(qapp, monkeypatch):
    eng = FakeEngine()
    eng.errors = {"mic": "busy"}
    monkeypatch.setattr(voicepanel.VoicePanel, "is_active", lambda self: True)
    p = _build(monkeypatch, eng)
    try:
        assert "busy" in p._oops_for
        assert p.oops.isVisibleTo(p)
    finally:
        p.shutdown()
        p.deleteLater()
