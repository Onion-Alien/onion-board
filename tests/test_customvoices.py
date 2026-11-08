"""Custom voices: a local TTS server, a TTS program, Piper packs, next to Windows'."""
import io
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest
import soundfile as sf
from conftest import closed_port

from soundboard.sounds import library
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


def test_a_program_voice_gets_the_line_as_a_file_or_one_plain_argument(tmp_path):
    out = tmp_path / "src.wav"
    out.write_bytes(wav_bytes(1000, 16000))
    line = 'x" & calc & "'
    script = ("import shutil, sys; from pathlib import Path; "
              "t = Path(sys.argv[2]).read_text(encoding='utf-8'); "
              f"assert t == sys.argv[3] == {line!r}, (t, sys.argv[3]); "
              f"shutil.copy({str(out)!r}, sys.argv[1])")
    v = CustomVoice("P", command=[sys.executable, "-c", script, "{out}", "{text_file}",
                                  "{text}"])
    mono, sr = v.synth(line)   # a program (not a script) gets it as one argument, as is
    assert sr == 16000 and len(mono) == 1000
    opt = ("import shutil, sys; assert sys.argv[2] == 'help', sys.argv[2]; "
           f"shutil.copy({str(out)!r}, sys.argv[1])")
    CustomVoice("P", command=[sys.executable, "-c", opt, "{out}", "{text}"]).synth("--help")


@pytest.mark.parametrize("program", ["C:/tools/say.bat", "say.cmd", "cmd", "powershell.exe",
                                     "C:/Windows/System32/WindowsPowerShell/v1.0/powershell"])
def test_chat_text_never_goes_into_a_scripts_command_line(program):
    """Lines come from Twitch chat: on a .bat's command line `x" & calc & "` runs calc
    (cmd.exe has its own quoting), so {text} is refused there before anything runs."""
    v = CustomVoice("P", command=[program, "/c", "say", "{text}"])
    with pytest.raises(RuntimeError, match="text_file"):
        v.synth('x" & calc & "')


@pytest.mark.windows   # Windows sorts file names whatever their case
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


FAKE_READER = r'''
import json, sys, wave
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if "fail" in req["text"]:
        print(json.dumps({"error": "can't read that"}), flush=True)
        continue
    with wave.open(req["out"], "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x10" * int(2205 * len(req["text"]) * float(req["speed"])))
    print(json.dumps({"ok": True}), flush=True)
'''


def _language_voice(lang: str, dataset: str):
    from soundboard.speech import translation
    d = translation.base_dir() / lang / "voice"
    d.mkdir(parents=True)
    (d / translation.VOICE_FILE).write_bytes(b"x")
    (d / (translation.VOICE_FILE + ".json")).write_text(json.dumps({"dataset": dataset}),
                                                        encoding="utf-8")


def test_a_language_is_read_by_its_own_voice_never_the_say_voice(vdir, tmp_path, monkeypatch):
    """The bug: Chinese turned on, and David (an English Windows voice) read it out.
    A downloaded language's voice is in the list as `piper:xx`, is the one voice_for
    gives, and reads through the AI voices add-on's reader."""
    import sys
    from soundboard.speech import piper
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft David Desktop"])
    monkeypatch.setattr(tts.SapiTTS, "voice_for", lambda self, lang, prefer="": "")
    _language_voice("zh", "huayan")
    script = tmp_path / "reader.py"
    script.write_text(FAKE_READER, encoding="utf-8")
    s = VoiceSet()
    s.reader = piper.PiperReader(lambda: ([sys.executable, str(script)], tmp_path))
    try:
        assert s.warm_up() == ["Microsoft David Desktop", "piper:zh"]
        assert s.voice_for("zh") == s.voice_for("zh-TW") == "piper:zh"
        assert s.voice_for("de") == ""            # not downloaded: no stand-in voice
        assert customvoices.label("piper:zh") == "Huayan (Chinese)"
        mono, sr = s.synth("你好", "piper:zh")
        assert sr == 22050 and len(mono) == 2 * 2205
        with pytest.raises(RuntimeError, match="can't read that"):
            s.synth("fail", "piper:zh")
        mono, _sr = s.synth("hi", "piper:zh", rate=10)      # faster: twice the speed
        assert len(mono) == 2 * 2 * 2205
        _language_voice("de", "thorsten")                    # downloaded since
        assert len(s.synth("hallo", "piper:de")[0])
    finally:
        s.reader.close()


def test_language_voices_need_ai_voices():
    from soundboard.speech import piper
    r = piper.PiperReader(lambda: None)
    with pytest.raises(RuntimeError, match="install AI voices"):
        r.synth("hola", Path("es.onnx"))


def test_the_reader_answers_each_line_and_survives_a_bad_one(tmp_path, monkeypatch):
    """modules/ai-voices/reader.py's own loop, with Piper stood in for."""
    import importlib.util
    import io
    spec = importlib.util.spec_from_file_location(
        "ai_reader", Path(__file__).parents[1] / "modules" / "ai-voices" / "reader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    said = []

    class Fake:
        def say(self, text, model, out, speed=1.0):
            if model == "bad.onnx":
                raise FileNotFoundError("no voice file bad.onnx")
            said.append((text, model, speed))

    monkeypatch.setattr(mod, "Reader", Fake)
    out = io.StringIO()
    lines = [json.dumps({"text": "hej", "model": "da.onnx", "out": "a.wav", "speed": 1.5}),
             json.dumps({"text": "x", "model": "bad.onnx", "out": "b.wav"}), "not json"]
    assert mod.serve(io.StringIO("\n".join(lines) + "\n"), out) == 0
    answers = [json.loads(a) for a in out.getvalue().splitlines()]
    assert answers[0] == {"ready": True} and answers[1] == {"ok": True}
    assert "bad.onnx" in answers[2]["error"] and "error" in answers[3]
    assert said == [("hej", "da.onnx", 1.5)]

    def no_piper():
        raise ImportError("piper")
    monkeypatch.setattr(mod, "Reader", no_piper)
    out = io.StringIO()
    assert mod.serve(io.StringIO(""), out) == 1
    assert "press Update" in json.loads(out.getvalue())["error"]


def test_voice_tab_lists_custom_voices_and_bad_files(vdir, qapp, monkeypatch):
    from tests.conftest import process_events
    from tests.test_voicepanel import FakeEngine
    from soundboard.ui.voice.voicepanel import VoicePanel
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    customvoices.save_server("Kokoro", "http://127.0.0.1:8880/v1/audio/speech", "af_bella")
    (vdir / "broken.json").write_text("{nope", encoding="utf-8")
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "custom:Kokoro"})
    try:
        s = p.speech
        assert process_events(qapp, lambda: not s.installs._loading())
        items = [s.cb_voice.itemText(i) for i in range(s.cb_voice.count())]
        assert items == ["Windows default", "Kokoro (custom)"]   # never Windows' own voices
        assert s.cb_voice.currentData() == "custom:Kokoro"
        assert s.ctl.speaker.voice == "custom:Kokoro"
        assert "broken.json" in s.lbl_custom.text()
    finally:
        p.shutdown()
        p.deleteLater()


def test_answers_and_update_server(vdir, server):
    """A server counts as online when anything answers at its address (a 404 too);
    saving its settings keeps what else its file says."""
    url, _seen = server
    assert customvoices.answers(url + "/v1/audio/speech")
    assert customvoices.answers(url + "/api/tts?text={text}")
    assert not customvoices.answers(f"http://127.0.0.1:{closed_port()}/v1/audio/speech")
    assert not customvoices.answers("not an address")
    path = vdir / "hans.json"
    path.write_text(json.dumps({"name": "Hans", "url": url, "voice": "a", "language": "de"}),
                    encoding="utf-8")
    customvoices.update_server(path, url + "/v2", model="m")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "name": "Hans", "url": url + "/v2", "model": "m", "language": "de"}
    assert customvoices.load()[0][0].file == path


def test_voice_servers_list_switches_and_removes(vdir, server, qapp, monkeypatch):
    """Add-ons lists each voice server: online or not, its switch makes it the computer
    voice (one at a time), Settings saves its address, Remove has Undo."""
    from tests.conftest import process_events
    from tests.test_voicepanel import FakeEngine
    from soundboard.ui.kit import busy
    from soundboard.ui.voice.voicepanel import VoicePanel
    url, _seen = server
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    customvoices.save_server("Kokoro", url + "/v1/audio/speech", "af_bella")
    customvoices.save_server("Gone", f"http://127.0.0.1:{closed_port()}/v1/audio/speech")
    (vdir / "prog.json").write_text(json.dumps({"command": "tts.exe"}), encoding="utf-8")
    toasts = []
    monkeypatch.setattr(busy, "toast", lambda w, text, kind="", *a, **k: toasts.append(
        (text, k.get("action"))))
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {"voice": ""})
    try:
        s = p.speech
        assert process_events(qapp, lambda: not s.installs._loading())
        rows = s.servers.rows
        assert list(rows) == ["custom:Gone", "custom:Kokoro"]   # not the program voice
        assert s.lbl_custom.text() == "1 custom voice loaded."
        assert process_events(qapp, lambda: all(r.online is not None for r in rows.values()))
        k, g = rows["custom:Kokoro"], rows["custom:Gone"]
        assert k.online and k.pill.text() == "Online" and k.pill.property("tone") == "ok"
        assert k.state.text() == ""
        assert not g.online and g.pill.text() == "Offline"
        assert g.state.text().startswith("Nothing answers at 127.0.0.1:")
        # asked once, then only when Custom voices is opened: never on a timer
        asked = []
        real = customvoices.answers
        monkeypatch.setattr(customvoices, "answers", lambda url: (asked.append(url), real(url))[1])
        p.show()
        p.show_tab("ai")
        process_events(qapp, lambda: False, timeout=1.5)
        assert asked == []
        p.b_custom.click()
        assert process_events(qapp, lambda: len(asked) == 2)
        p.custom.reject()
        k.switch.click()
        assert s.cb_voice.currentData() == "custom:Kokoro" == s.ctl.speaker.voice
        assert k.state.text() == "Speaks your typed lines"
        g.switch.click()                                   # one at a time
        assert s.ctl.speaker.voice == "custom:Gone"
        assert not k.switch.isChecked() and g.switch.isChecked()
        g.switch.click()                                   # off: Windows' voice
        assert s.cb_voice.currentData() == "" and not g.switch.isChecked()
        s.cb_voice.setCurrentIndex(s.cb_voice.findData("custom:Kokoro"))   # the Voice list
        assert k.switch.isChecked()
        # Settings: a bad address is refused, a good one saved
        k.fold.click()
        assert k.ed_url.isVisibleTo(k)
        k.ed_url.setText("127.0.0.1/x")
        k.b_save.click()
        assert not k.err.isHidden()
        k.ed_url.setText(url + "/v1/speech")
        k.b_save.click()
        assert json.loads((vdir / "Kokoro.json").read_text("utf-8"))["url"] == url + "/v1/speech"
        assert process_events(qapp, lambda: s.ctl.tts.custom["custom:Kokoro"].url.endswith(
            "/v1/speech") and not s.installs._loading())
        # Remove, then Undo: back, and switched on again
        s.servers.rows["custom:Kokoro"].b_remove.click()
        assert not (vdir / "Kokoro.json").exists() and s.ctl.speaker.voice == ""
        text, (label, undo) = toasts[-1]
        assert "Kokoro" in text and label == "Undo"
        assert process_events(qapp, lambda: "custom:Kokoro" not in s.servers.rows
                              and not s.installs._loading())
        undo()
        assert process_events(qapp, lambda: "custom:Kokoro" in s.servers.rows
                              and not s.installs._loading())
        assert s.ctl.speaker.voice == "custom:Kokoro"
        assert s.servers.rows["custom:Kokoro"].switch.isChecked()
    finally:
        p.shutdown()
        p.deleteLater()


def test_voice_server_picture(vdir, qapp, monkeypatch):
    """A server's picture: one of the app's voice pictures, or one from a link (kept
    beside its .json as a square PNG); both saved at once, and Remove picture clears it."""
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QInputDialog
    from tests.conftest import process_events
    from soundboard.sounds import thumbs
    from soundboard.ui.voice import voiceservers
    path = customvoices.save_server("Kokoro", "http://127.0.0.1:8880/v1/audio/speech")
    cv = customvoices.load()[0][0]
    row = voiceservers.ServerRow(cv)
    try:
        assert voiceservers.picture_pixmap(cv, 30) is None
        assert row.b_pic_clear.isHidden()
        assert "voice-robot" in voiceservers.app_pictures()
        assert "voice-random" not in voiceservers.app_pictures()

        def pick(dlg):
            dlg._pick("voice-robot")
            return dlg.result()
        monkeypatch.setattr(voiceservers.PicturePicker, "exec", pick)
        row.b_pic_ours.click()
        assert json.loads(path.read_text("utf-8"))["picture"] == "voice-robot"
        assert cv.picture == "voice-robot" and not row.b_pic_clear.isHidden()
        assert voiceservers.picture_pixmap(cv, 30) is not None

        img = QImage(400, 200, QImage.Format.Format_RGB32)
        img.fill(QColor("orange"))
        monkeypatch.setattr(thumbs, "fetch", lambda url: img)
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("https://example.com/a.png", True)))
        row.b_pic_link.click()
        assert process_events(qapp, lambda: cv.picture == "Kokoro.png")
        kept = QImage(str(vdir / "Kokoro.png"))
        assert (kept.width(), kept.height()) == (256, 256)
        assert customvoices.load()[0][0].picture == "Kokoro.png"

        row.b_pic_clear.click()   # its file from the link goes too
        assert "picture" not in json.loads(path.read_text("utf-8"))
        assert not (vdir / "Kokoro.png").exists() and row.b_pic_clear.isHidden()
    finally:
        row.deleteLater()


def test_custom_voices_are_found_from_ai_voices_and_from_settings(window):  # noqa: F811
    """Custom voices are a dialog (no tab of their own), opened from the button at the
    end of AI voices' head, from Add voices beside the Voice list and from Settings →
    Audio's card (from any other tab): each shows AI voices with the dialog under it."""
    from PySide6.QtWidgets import QPushButton
    from soundboard.ui.settings.settings import SettingsDialog
    w = window
    s = w.voice.speech
    vp = w.voice
    assert "custom" not in vp._tabs and "addons" not in vp._tabs
    assert vp.custom.isAncestorOf(s.custom_box) and not s.isAncestorOf(s.custom_box)
    assert vp._ai_card.isAncestorOf(vp.b_custom) and not vp.custom.isVisible()
    vp.b_custom.click()
    assert vp.custom.isVisible() and s.custom_box.isVisibleTo(vp.custom)
    vp.custom.reject()
    vp.show_tab("fx")
    s.b_add_voices.click()
    assert vp.current_tab() == "ai" and vp.custom.isVisible()
    assert not s.btn_opts.isChecked()
    vp.custom.reject()
    vp.show_tab("fx")
    dlg = SettingsDialog(w, "audio")
    try:
        buttons = {b.text(): b for b in dlg.findChildren(QPushButton)}
        assert {"Add a voice server", "Open voices folder"} <= set(buttons)
        buttons["Show on the Voice tab"].click()
        assert w.tabs.currentWidget() is w.voice and vp.current_tab() == "ai"
        assert vp.custom.isVisible()
    finally:
        vp.custom.reject()
        dlg.deleteLater()


def test_custom_voices_dialog_layout(window):  # noqa: F811
    """The dialog opens with its title in the title style, every button as wide as its
    words (a fixed width once cut them off), the two ways to add voices with their
    buttons level, and Done at the bottom right."""
    from PySide6.QtWidgets import QPushButton
    vp = window.voice
    s = vp.speech
    vp.b_custom.click()
    try:
        assert vp.custom.isVisible()
        assert s.custom_title.font().bold() and s.custom_title.objectName() == "helptitle"
        for b in vp.custom.findChildren(QPushButton):
            if b.isVisibleTo(vp.custom):
                assert b.width() >= b.sizeHint().width(), b.text()
        assert s.b_add_server.objectName() == "primary"
        done = next(b for b in vp.custom.findChildren(QPushButton) if b.text() == "Done")
        right = vp.custom.width() - vp.custom.layout().contentsMargins().right()
        assert abs(done.geometry().right() + 1 - right) <= 1
        # the two cards' buttons sit level
        a, b = s.b_add_server, s.b_voices_folder
        assert a.height() == b.height()
        top = vp.custom
        assert a.mapTo(top, a.rect().topLeft()).y() == b.mapTo(top, b.rect().topLeft()).y()
    finally:
        vp.custom.reject()


def test_voice_servers_are_cards_on_ai_voices(vdir, server, qapp, monkeypatch):
    """Each voice server is a card at the top of AI voices (even with AI voices not
    installed): a click makes it read your typed lines, as its switch does, and they
    agree both ways; with no server, no Custom voices group."""
    from tests.conftest import process_events
    from tests.test_voicepanel import FakeEngine
    from soundboard.ui.voice.voicepanel import VoicePanel
    url, _seen = server
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {"voice": "", "tab": "ai"})
    try:
        s, ai = p.speech, p.ai
        assert process_events(qapp, lambda: not s.installs._loading())
        assert ai.server_box.isHidden() and not ai._server_tiles
        customvoices.save_server("Kokoro", url + "/v1/audio/speech", "af_bella")
        s.installs._recheck_voices_asked()
        assert process_events(qapp, lambda: "custom:Kokoro" in ai._server_tiles)
        p.resize(900, 700)
        p.show()
        card = ai._server_tiles["custom:Kokoro"]
        assert card.isVisibleTo(p) and card.star.isHidden() and not card.isChecked()
        assert process_events(qapp, lambda: card.detail == "Online")
        card.click()
        assert s.ctl.speaker.voice == "custom:Kokoro" and card.isChecked()
        assert s.servers.rows["custom:Kokoro"].switch.isChecked()
        assert card.toolTip() == "Speaks your typed lines"
        card.click()                                   # again: off, Windows' voice
        assert s.cb_voice.currentData() == "" and not card.isChecked()
        s.servers.rows["custom:Kokoro"].switch.click()  # the dialog's switch lights it
        assert card.isChecked()
    finally:
        p.shutdown()
        p.deleteLater()


def test_custom_voices_button_goes_down_to_its_icon_when_narrow(qapp):
    """On a narrow window the button at the end of AI voices' head is just its icon (its
    words cut off read "Custom voice"); wide again, its name comes back."""
    from soundboard.ui.voice.voicepanel import VoicePanel
    from tests.conftest import process_events
    from tests.test_voicepanel import FakeEngine
    vp = VoicePanel(FakeEngine(), None, {"tab": "ai"})
    try:
        b = vp.b_custom
        vp.resize(1200, 700)
        vp.show()
        process_events(qapp, lambda: b.text() == "Custom voices")
        vp.resize(330, 700)
        assert process_events(qapp, lambda: b.text() == "")
        assert b.toolTip() and b.accessibleName() == "Custom voices" and not b.icon().isNull()
        vp.resize(1200, 700)
        assert process_events(qapp, lambda: b.text() == "Custom voices")
    finally:
        vp.shutdown()
        vp.deleteLater()


@pytest.mark.parametrize("old", ["custom", "addons"])
def test_a_saved_custom_or_addons_tab_opens_ai_voices(qapp, old):
    """Someone who last had the old Custom or Add-ons tab open lands on AI voices, where
    custom voices went."""
    from soundboard.ui.voice.voicepanel import VoicePanel
    from tests.test_voicepanel import FakeEngine
    vp = VoicePanel(FakeEngine(), None, {"tab": old})
    try:
        assert vp.current_tab() == "ai"
    finally:
        vp.deleteLater()


def test_language_voice_lines_are_as_loud_as_windows_ones():
    """Piper's lines come out at full scale (up to 7 dB louder than a Windows voice's);
    they're levelled to about -20 dBFS, with the peaks kept under 0.9."""
    import numpy as np
    from soundboard.speech import piper
    t = np.arange(22050) / 22050
    loud = (0.999 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    y = piper.level(loud)
    assert abs(20 * np.log10(np.sqrt(np.mean(y ** 2))) + 20) < 0.5
    assert np.abs(y).max() <= 0.9 + 1e-6
    spiky = np.zeros(22050, np.float32)
    spiky[100] = 1.0
    assert np.abs(piper.level(spiky)).max() <= 0.9 + 1e-6       # a peak never clips
    assert not piper.level(np.zeros(10, np.float32)).any()


# ---------------------------------------------------------------- Add a voice server

@pytest.fixture
def kokoro():
    """A pretend Kokoro-FastAPI: its voice list at /v1/audio/voices (`voices`: what it
    answers there, a 404 when None)."""
    state = {"voices": {"voices": ["af_bella", "am_adam", "af_bella", "bf_emma"]}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/v1/audio/voices" and state["voices"] is not None:
                body = json.dumps(state["voices"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", state
    srv.shutdown()
    srv.server_close()


def test_a_servers_address_however_its_typed():
    assert customvoices.base_url("localhost:8880") == "http://localhost:8880"
    assert customvoices.base_url("http://127.0.0.1:8880/v1/audio/speech/") == \
        "http://127.0.0.1:8880"
    assert customvoices.base_url("https://x.example.com/tts/v1") == "https://x.example.com/tts"
    assert customvoices.speech_url("127.0.0.1:7851") == "http://127.0.0.1:7851/v1/audio/speech"
    assert customvoices.speech_url("http://h:1/say?t={text}") == "http://h:1/say?t={text}"


def test_list_voices_reads_kokoros_list_and_others(kokoro):
    url, state = kokoro
    assert customvoices.list_voices(url) == ["af_bella", "am_adam", "bf_emma"]   # no repeats
    state["voices"] = {"voices": [{"id": "a"}, {"name": "b"}, {"x": 1}, " c "]}
    assert customvoices.list_voices(url + "/v1/audio/speech") == ["a", "b", "c"]
    state["voices"] = ["solo"]
    assert customvoices.list_voices(url) == ["solo"]
    state["voices"] = {"voices": []}
    with pytest.raises(ValueError):
        customvoices.list_voices(url)
    state["voices"] = None                                   # no list there: a 404
    with pytest.raises(OSError):
        customvoices.list_voices(url)
    with pytest.raises(OSError):
        customvoices.list_voices(f"http://127.0.0.1:{closed_port()}")


def _find(dlg, qapp):
    from tests.conftest import process_events
    dlg.b_find.click()
    assert process_events(qapp, lambda: dlg.b_find.isEnabled(), 10)


def test_add_kokoro_ticks_its_voices_and_saves_one_card_each(vdir, kokoro, qapp):
    """Kokoro: Find voices lists what it has, none ticked; two ticked are two server
    voices on the same address. The same voice again isn't added twice."""
    from PySide6.QtWidgets import QWidget
    from soundboard.ui.voice.voiceaddserver import AddServerDialog
    url, _state = kokoro
    host = QWidget()
    dlg = AddServerDialog(host)
    try:
        assert dlg.preset()[0] == "kokoro" and dlg.ed_url.text() == "http://127.0.0.1:8880"
        assert dlg.ed_model.text() == "kokoro" and dlg.b_add.isHidden()   # nothing found yet
        dlg.ed_url.setText(url)
        _find(dlg, qapp)
        assert [c.text() for c in dlg._ticks] == ["af_bella", "am_adam", "bf_emma"]
        assert dlg.voices.isVisibleTo(dlg) and dlg.voice_row.isHidden()
        assert not dlg.b_add.isEnabled() and dlg.b_add.text() == "Add voices (0)"
        for i in (0, 2):
            dlg._ticks[i].setChecked(True)
        assert dlg.b_add.text() == "Add voices (2)" and dlg.b_add.isEnabled()
        dlg.b_add.click()
        assert dlg.result() == dlg.DialogCode.Accepted and dlg.saved == ["af_bella", "bf_emma"]
        got = {cv.name: cv for cv in customvoices.load()[0]}
        assert got["af_bella"].url == got["bf_emma"].url == url + "/v1/audio/speech"
        assert (got["af_bella"].voice, got["bf_emma"].voice) == ("af_bella", "bf_emma")
        again = AddServerDialog(host)
        again.ed_url.setText(url)
        _find(again, qapp)
        again._ticks[0].setChecked(True)
        again.b_add.click()
        assert again.saved == [] and len(customvoices.load()[0]) == 2
    finally:
        host.deleteLater()


def test_add_alltalk_offers_its_six_names_or_says_nothing_answers(vdir, server, qapp):
    from PySide6.QtWidgets import QWidget
    from soundboard.ui.voice.voiceaddserver import AddServerDialog
    url, _seen = server
    host = QWidget()
    dlg = AddServerDialog(host)
    try:
        alltalk = next(b for b, p in dlg._kind.items() if p[0] == "alltalk")
        alltalk.click()
        assert dlg.ed_url.text() == "http://127.0.0.1:7851" and dlg.ed_model.text() == ""
        dlg.ed_url.setText(f"http://127.0.0.1:{closed_port()}")
        _find(dlg, qapp)
        assert dlg.lbl.text().startswith("Nothing answers at") and dlg.voices.isHidden()
        dlg.ed_url.setText(url)
        _find(dlg, qapp)
        assert [c.text() for c in dlg._ticks] == list(customvoices.OPENAI_VOICES)
    finally:
        host.deleteLater()


def test_add_other_without_a_list_types_the_voice(vdir, server, qapp):
    """Other: a server that answers but lists nothing takes a typed voice name; a voice
    called like one already in from another server gets the server's name after it."""
    from PySide6.QtWidgets import QWidget
    from soundboard.ui.voice.voiceaddserver import AddServerDialog
    url, _seen = server
    customvoices.save_server("nova", "http://127.0.0.1:1/v1/audio/speech", "nova")
    host = QWidget()
    dlg = AddServerDialog(host)
    try:
        other = next(b for b, p in dlg._kind.items() if p[0] == "other")
        other.click()
        assert dlg.ed_url.text() == ""
        dlg.ed_url.setText("not an address")
        dlg.b_find.click()
        assert dlg.err.text() == "The address starts with http:// or https://"
        dlg.ed_url.setText(url)
        _find(dlg, qapp)
        assert dlg.voice_row.isVisibleTo(dlg) and dlg.voices.isHidden()
        assert dlg.lbl.text() == "No voice list at this address: type the voice's name."
        dlg.ed_voice.setText("nova")
        assert dlg.b_add.text() == "Add voices (1)"
        dlg.b_add.click()
        label = url.split("//")[1]
        assert dlg.saved == [f"nova ({label})"]
        assert {cv.name for cv in customvoices.load()[0]} == {"nova", f"nova ({label})"}
    finally:
        host.deleteLater()
