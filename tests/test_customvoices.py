"""Custom voices: a local TTS server, a TTS program, Piper packs, next to Windows'."""
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest
import soundfile as sf
from conftest import closed_port

from soundboard import library
from soundboard.speech import customvoices, tts
from soundboard.speech.customvoices import CustomVoice, VoiceSet
from test_mainwindow import window  # noqa: F401  (the real MainWindow)


def wav_bytes(n=2400, rate=24000, channels=1) -> bytes:
    buf = io.BytesIO()
    x = np.full((n, channels), 0.25, np.float32)
    sf.write(buf, x, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@pytest.fixture
def vdir(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    return customvoices.ensure_folder()


@pytest.fixture
def server():
    """A pretend TTS server on 127.0.0.1: records requests, answers a stereo WAV."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _answer(self, body=b""):
            seen.append((self.command, self.path, dict(self.headers), body))
            if "fail" in self.path:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"model not loaded")
                return
            data = wav_bytes(channels=2)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._answer()

        def do_POST(self):
            self._answer(self.rfile.read(int(self.headers["Content-Length"])))

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", seen
    srv.shutdown()
    srv.server_close()


def test_folder_gets_a_readme_and_load_reads_every_kind(vdir, monkeypatch):
    monkeypatch.setattr(customvoices.shutil, "which", lambda name: None)  # no piper on PATH
    assert (vdir / "README.txt").exists()
    (vdir / "kokoro.json").write_text(json.dumps(
        {"name": "Kokoro", "url": "http://127.0.0.1:8880/v1/audio/speech",
         "voice": "af_bella", "language": "en-US"}), encoding="utf-8")
    (vdir / "prog.json").write_text(json.dumps({"command": "tts.exe"}), encoding="utf-8")
    (vdir / "bad.json").write_text("{nope", encoding="utf-8")
    (vdir / "empty.json").write_text("{}", encoding="utf-8")
    (vdir / "ftp.json").write_text(json.dumps({"url": "file:///c:/x"}), encoding="utf-8")
    (vdir / "en_US-amy.onnx").write_bytes(b"x")
    (vdir / "en_US-amy.onnx.json").write_text(
        json.dumps({"language": {"code": "en_US"}}), encoding="utf-8")
    voices, problems = customvoices.load()
    by = {v.name: v for v in voices}
    assert set(by) == {"Kokoro", "prog"}
    assert by["Kokoro"].voice == "af_bella" and by["Kokoro"].language == "en-US"
    assert by["prog"].command == ["tts.exe"]
    joined = " ".join(problems)
    assert "bad.json" in joined and "empty.json" in joined and "ftp.json" in joined
    assert "piper.exe" in joined               # a pack with nothing to run it is reported
    (vdir / "piper").mkdir()
    (vdir / "piper" / "piper.exe").write_bytes(b"")
    voices, _ = customvoices.load()
    amy = next(v for v in voices if v.name == "en_US-amy")
    assert amy.language == "en-US" and amy.command[0].endswith("piper.exe")
    assert "{out}" in amy.command and "{length_scale}" in amy.command


def test_openai_style_server_is_posted_the_line(server):
    url, seen = server
    v = CustomVoice("K", url=url + "/v1/audio/speech", voice="af_bella", model="kokoro",
                    api_key="k123")
    mono, sr = v.synth("héllo there", rate=10)
    assert sr == 24000 and mono.shape == (2400,) and mono.dtype == np.float32
    method, path, headers, body = seen[0]
    assert method == "POST" and path == "/v1/audio/speech"
    req = json.loads(body)
    assert req["input"] == "héllo there" and req["voice"] == "af_bella"
    assert req["model"] == "kokoro" and req["response_format"] == "wav"
    assert req["speed"] == 2.0
    assert headers["Authorization"] == "Bearer k123"


def test_text_in_the_address_server_is_fetched(server):
    url, seen = server
    v = CustomVoice("G", url=url + "/api/tts?text={text}&speaker={voice}", voice="p 1")
    v.synth("a&b c")
    assert seen[0][0] == "GET" and seen[0][1] == "/api/tts?text=a%26b%20c&speaker=p%201"


def test_server_errors_say_what_happened(server):
    url, _ = server
    with pytest.raises(RuntimeError, match="500 model not loaded"):
        CustomVoice("S", url=url + "/fail").synth("hi")
    with pytest.raises(RuntimeError, match="Is the server running"):
        CustomVoice("S", url=f"http://127.0.0.1:{closed_port()}/v1/audio/speech").synth("hi")


def test_a_program_voice_writes_its_wav(tmp_path):
    out = tmp_path / "src.wav"
    out.write_bytes(wav_bytes(1000, 16000))
    script = ("import shutil, sys; t = sys.stdin.read(); "
              f"assert t == 'say this', t; shutil.copy({str(out)!r}, sys.argv[1])")
    v = CustomVoice("P", command=[sys.executable, "-c", script, "{out}"])
    mono, sr = v.synth("say this")
    assert sr == 16000 and len(mono) == 1000
    with pytest.raises(RuntimeError, match="the program failed"):
        CustomVoice("P", command=[sys.executable, "-c", "raise SystemExit(3)"]).synth("x")


def test_voice_set_lists_and_routes_custom_voices(vdir, server, monkeypatch):
    url, seen = server
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    win = []
    monkeypatch.setattr(tts.SapiTTS, "synth",
                        lambda self, text, voice="", rate=0: (win.append(voice),
                                                              (np.zeros(5, np.float32), 22050))[1])
    customvoices.save_server("Kokoro", url + "/v1/audio/speech", "af_bella")
    (vdir / "de.json").write_text(json.dumps({"name": "Hans", "url": url, "language": "de"}),
                                  encoding="utf-8")
    s = VoiceSet()
    assert s.warm_up() == ["Microsoft Zira Desktop", "custom:Hans", "custom:Kokoro"]
    assert s.voice_for("de") == "custom:Hans"
    mono, sr = s.synth("hello", "custom:Kokoro")
    assert sr == 24000 and len(mono) == 2400 and len(seen) == 1
    s.synth("hello", "Microsoft Zira Desktop")
    assert win == ["Microsoft Zira Desktop"]
    with pytest.raises(RuntimeError, match="isn't in the voices folder"):
        s.synth("hello", "custom:Gone")
    assert customvoices.label("custom:Hans") == "Hans (custom)"
    assert customvoices.label("Microsoft Zira Desktop") == "Zira"


def test_voice_tab_lists_custom_voices_and_bad_files(vdir, qapp, monkeypatch):
    from tests.conftest import process_events
    from tests.test_voicepanel import FakeEngine
    from soundboard.ui.voicepanel import VoicePanel
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    customvoices.save_server("Kokoro", "http://127.0.0.1:8880/v1/audio/speech", "af_bella")
    (vdir / "broken.json").write_text("{nope", encoding="utf-8")
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "custom:Kokoro"})
    try:
        s = p.speech
        assert process_events(qapp, lambda: not s._loading())
        items = [s.cb_voice.itemText(i) for i in range(s.cb_voice.count())]
        assert items == ["Windows default", "Zira", "Kokoro (custom)"]
        assert s.cb_voice.currentData() == "custom:Kokoro"
        assert s.ctl.speaker.voice == "custom:Kokoro"
        assert "broken.json" in s.lbl_custom.text()
    finally:
        p.shutdown()
        p.deleteLater()


def test_custom_voices_are_found_from_the_voice_list_and_from_settings(window):  # noqa: F811
    """Custom voices are their own card on the Voice tab, under Speak another language.
    Add voices… beside the Voice list, and Settings → Audio's card, both open it (even
    when it was folded away)."""
    from PySide6.QtWidgets import QPushButton
    from soundboard.settings import SettingsDialog
    w = window
    s = w.voice.speech
    head = w.voice._heads["custom"]
    assert not head.is_open() and s.custom_box.isHidden()   # the tab opens folded
    assert not s.isAncestorOf(s.custom_box)          # its own card, not inside Speak
    s.b_add_voices.click()
    assert not s.custom_box.isHidden() and not s.btn_opts.isChecked() and head.is_open()
    head.arrow.toggle()
    dlg = SettingsDialog(w, "audio")
    try:
        buttons = {b.text(): b for b in dlg.findChildren(QPushButton)}
        assert {"Add a voice server…", "Open voices folder"} <= set(buttons)
        buttons["Show on the Voice tab"].click()
        assert w.tabs.currentWidget() is w.voice and not s.custom_box.isHidden()
    finally:
        dlg.deleteLater()
