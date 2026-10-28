"""The "Didn't work? Send us a report" form address (core/feedback.py micfail_url)."""
from urllib.parse import parse_qs, urlsplit

from soundboard import __version__
from soundboard.core import feedback


def test_the_error_code_keeps_only_numbers():
    text = ("Error opening InputStream: Unanticipated host error [PaErrorCode -9999]: "
            "'Access denied.' [Windows WASAPI error -2147024891] X:/audio/mic")
    assert feedback.mic_error("mic-open", text) == "mic-open-9999-80070005"
    assert feedback.mic_error("mic-open", "no numbers here, Headset (Someone's)") == "mic-open"
    assert len(feedback.mic_error("x" * 80, text)) <= 60


def test_the_form_gets_what_the_uninstall_form_gets(monkeypatch):
    monkeypatch.setattr(feedback, "windows_version", lambda: "10-19045")
    url = feedback.micfail_url(__version__, mic="Headset Mic (USB)", mode="cable",
                               err="attach-code-6")
    assert url.startswith(feedback.FORM_URL + "?")
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert q == {"version": __version__, "from": "micfail", "win": "10-19045",
                 "mic": "Headset Mic (USB)", "mode": "cable", "mictest": "fail",
                 "err": "attach-code-6"}


def test_windows_version_is_major_and_build(monkeypatch):
    class V:
        build = 22631
    monkeypatch.setattr(feedback.sys, "getwindowsversion", lambda: V, raising=False)
    assert feedback.windows_version() == "11-22631"
    V.build = 19045
    assert feedback.windows_version() == "10-19045"
