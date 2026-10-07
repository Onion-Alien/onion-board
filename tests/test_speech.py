"""Add-on modules, the service-module link, the live-voice helper and text-to-speech."""
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard import modules, voicefx
from soundboard.speech import protocol, service
from soundboard.speech.live import SpeechController
from soundboard.speech.service import ServiceHost
from soundboard.voicefx import VoiceChain

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "modules" / "live-voice"


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    return cond()


def speechlike(rng, plan, rate=48000):
    """Blocks of noise: (seconds, amplitude) pairs, loud = 'talking'."""
    for sec, amp in plan:
        x = (rng.standard_normal(int(sec * rate)) * amp).astype(np.float32)
        for i in range(0, len(x), 480):
            yield x[i:i + 480]


# ---------------------------------------------------------------- protocol

def test_protocol_round_trip():
    a, b = socket.socketpair()
    with a, b:
        protocol.send_json(a, {"type": "final", "text": "héllo"})
        protocol.send(a, protocol.AUDIO, b"\x01\x02" * 100)
        protocol.send(a, protocol.AUDIO, b"")
        k, p = protocol.recv(b)
        assert k == protocol.JSON and protocol.decode_json(p)["text"] == "héllo"
        assert protocol.recv(b) == (protocol.AUDIO, b"\x01\x02" * 100)
        assert protocol.recv(b) == (protocol.AUDIO, b"")
        a.close()
        assert protocol.recv(b) is None


def test_modules_ship_the_same_protocol():
    app = (ROOT / "soundboard" / "speech" / "protocol.py").read_bytes()
    assert (LIVE / "protocol.py").read_bytes() == app


# ---------------------------------------------------------------- modules

def write_module(folder: Path, **manifest):
    folder.mkdir(parents=True)
    (folder / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_discover_reads_manifests_and_reports_bad_ones(tmp_path):
    write_module(tmp_path / "a", id="a", name="A", kind="service", command=["x"])
    write_module(tmp_path / "b", id="b", kind="effects", entry="missing.py")
    write_module(tmp_path / "c", id="c", kind="weird")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "module.json").write_text("{nope", encoding="utf-8")
    (tmp_path / "not-a-module").mkdir()
    got = {m.id: m for m in modules.discover([tmp_path])}
    assert set(got) == {"a", "b", "c", "d"}
    assert got["a"].error == "" and got["a"].name == "A"
    assert "not found" in got["b"].error
    assert "unknown kind" in got["c"].error
    assert "bad module.json" in got["d"].error


def test_manifest_with_a_bom_is_read_and_string_commands_are_refused(tmp_path):
    (tmp_path / "bom").mkdir()
    (tmp_path / "bom" / "module.json").write_text(      # Notepad / PowerShell style
        json.dumps({"id": "bom", "kind": "service", "command": ["x"]}), encoding="utf-8-sig")
    write_module(tmp_path / "cmd", id="cmd", kind="service", command="python helper.py")
    write_module(tmp_path / "inst", id="inst", kind="service", command=["x"],
                 install="pip install x")
    write_module(tmp_path / "step", id="step", kind="service", command=["x"],
                 install=["pip install x"])
    write_module(tmp_path / "list", id="list", kind="service", command=["x", 1])
    (tmp_path / "arr").mkdir()
    (tmp_path / "arr" / "module.json").write_text("[]", encoding="utf-8")
    got = {m.id: m for m in modules.discover([tmp_path])}
    assert got["bom"].error == "" and got["bom"].command == ["x"]
    for mid in ("cmd", "inst", "step", "list"):
        assert "bad module.json" in got[mid].error, mid
        assert got[mid].command == [] and got[mid].install_steps == []
    assert "bad module.json" in got["arr"].error


def test_first_folder_wins_for_the_same_id(tmp_path):
    write_module(tmp_path / "user" / "m", id="m", version="2", kind="service", command=["x"])
    write_module(tmp_path / "app" / "m", id="m", version="1", kind="service", command=["x"])
    (m,) = modules.discover([tmp_path / "user", tmp_path / "app"])
    assert m.version == "2"


def test_effects_module_registers_and_a_broken_one_is_contained(tmp_path, monkeypatch):
    monkeypatch.setattr(voicefx, "REGISTRY", dict(voicefx.REGISTRY))
    good = write_module(tmp_path / "good", id="good", kind="effects", entry="fx.py")
    (good / "fx.py").write_text(
        "def register(api):\n"
        "    class Mute(api.Effect):\n"
        "        type, name = 'good.mute', 'Mute'\n"
        "        params = (api.Param('x', 'X', 0, 1, 0.5),)\n"
        "        def run(self, x, rate):\n"
        "            return x * 0\n"
        "    api.register_effect(Mute)\n", encoding="utf-8")
    bad = write_module(tmp_path / "bad", id="bad", kind="effects", entry="fx.py")
    (bad / "fx.py").write_text("raise ImportError('needs torch')\n", encoding="utf-8")
    infos = modules.discover([tmp_path])
    modules.load_effects(infos)
    by = {m.id: m for m in infos}
    assert by["good"].loaded and by["good"].provides == ["good.mute"]
    assert "needs torch" in by["bad"].error and not by["bad"].loaded
    c = VoiceChain()
    c.configure({"enabled": True, "effects": {"good.mute": {"on": True}}})
    assert not c.process(np.ones((8, 2), np.float32), 48000).any()


def test_repo_modules_are_valid():
    infos = {m.id: m for m in modules.discover([ROOT / "modules"])}
    assert {"live-voice", "retro-fx"} <= set(infos)
    assert not any(m.error for m in infos.values())
    modules.load_effects(list(infos.values()))
    assert "retro.bitcrush" in voicefx.REGISTRY


def test_service_command_uses_the_modules_own_python(tmp_path):
    m = write_module(tmp_path / "s", id="s", kind="service",
                     command=["{python}", "{dir}/run.py"])
    (info,) = modules.discover([tmp_path])
    assert info.resolved_command(["--x"])[0] == "python" and not info.installed
    venv_py = m / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"")
    assert info.resolved_command()[0] == str(venv_py) and info.installed
    assert info.resolved_command()[1] == f"{m}/run.py"


# ---------------------------------------------------------------- live-voice helper

@pytest.fixture
def helper_segmenter():
    sys.path.insert(0, str(LIVE))
    try:
        import helper
        yield helper
    finally:
        sys.path.remove(str(LIVE))
        sys.modules.pop("helper", None)
        sys.modules.pop("protocol", None)


def test_segmenter_finds_sentences_and_ignores_blips(helper_segmenter):
    h = helper_segmenter
    rng = np.random.default_rng(1)
    seg = h.Segmenter()
    plan = [(1.0, 0.002), (1.2, 0.2), (1.0, 0.002), (0.1, 0.3), (1.0, 0.002),
            (0.9, 0.15), (1.0, 0.002)]
    utts = []
    for sec, amp in plan:
        x = (rng.standard_normal(int(sec * h.RATE)) * amp).astype(np.float32)
        for i in range(0, len(x), 160):
            utts += seg.feed(x[i:i + 160])
    lens = [len(u) / h.RATE for u in utts]
    assert len(lens) == 2                         # the 0.1 s blip isn't a sentence
    assert 1.2 < lens[0] < 2.4 and 0.9 < lens[1] < 2.0


def test_segmenter_cuts_very_long_speech(helper_segmenter):
    seg = helper_segmenter.Segmenter(max_s=2.0)
    x = (np.random.default_rng(2).standard_normal(16000 * 5) * 0.2).astype(np.float32)
    assert len(seg.feed(x)) == 2


def fake_live(events):
    return ServiceHost([sys.executable, str(LIVE / "helper.py"), "--fake"], events.append,
                       name="live-voice")


def test_service_round_trip_with_the_real_helper_process():
    events = []
    h = fake_live(events)
    h.start()
    try:
        assert wait_for(lambda: any(e["type"] == "ready" for e in events))
        assert events[0]["type"] == "hello"
        rng = np.random.default_rng(0)
        for b in speechlike(rng, [(0.8, 0.002), (1.0, 0.2), (1.0, 0.002)]):
            h.feed(b, 48000)
            time.sleep(0.0005)
        assert wait_for(lambda: any(e["type"] == "final" for e in events))
        final = next(e for e in events if e["type"] == "final")
        assert final["text"].startswith("utterance 1")
        assert {"type": "vad", "speaking": True} in events
    finally:
        h.stop()
    assert not h.running


def test_service_rejects_a_wrong_token():
    events = []
    impostor = ("import json,socket,struct,sys\n"
                "p=int(sys.argv[sys.argv.index('--port')+1])\n"
                "s=socket.create_connection(('127.0.0.1',p))\n"
                "b=json.dumps({'type':'hello','token':'guess'}).encode()\n"
                "s.sendall(b'J'+struct.pack('<I',len(b))+b)\n"
                "s.recv(1)\n")
    h = ServiceHost([sys.executable, "-c", impostor], events.append, name="impostor")
    h.start()
    assert wait_for(lambda: any(e["type"] == "stopped" for e in events))
    assert "handshake" in events[-1]["text"] and not h.connected
    h.stop()


def test_service_ignores_strangers_who_connect_first(monkeypatch):
    # other local processes get to the port before the module: a wrong token, a huge
    # frame header and a silent caller are dropped, and the module still connects
    from soundboard.speech import service
    monkeypatch.setattr(service, "HELLO_TIMEOUT_S", 0.5)
    events = []
    module = ("import json,socket,struct,sys\n"
              "a=sys.argv; p=int(a[a.index('--port')+1]); t=a[a.index('--token')+1]\n"
              "def hello(tok):\n"
              "    b=json.dumps({'type':'hello','token':tok}).encode()\n"
              "    return b'J'+struct.pack('<I',len(b))+b\n"
              "bad=[socket.create_connection(('127.0.0.1',p)) for _ in range(3)]\n"
              "bad[0].sendall(hello('guess'))\n"
              "bad[1].sendall(b'J'+struct.pack('<I',16<<20))\n"
              "s=socket.create_connection(('127.0.0.1',p))\n"
              "s.sendall(hello(t))\n"
              "s.recv(1)\n")
    h = ServiceHost([sys.executable, "-c", module], events.append, name="module")
    h.start()
    try:
        assert wait_for(lambda: h.connected, timeout=20)
        assert events[0]["type"] == "hello"
        assert not any(e["type"] == "stopped" for e in events)
    finally:
        h.stop()


def test_handshake_caps_the_first_frame():
    from soundboard.speech import service
    a, b = socket.socketpair()
    try:
        a.sendall(b"J" + (service.HELLO_MAX + 1).to_bytes(4, "little"))
        assert service._handshake(b, "tok", 1.0) is None
        a.sendall(b"J" + (5).to_bytes(4, "little") + b"nope}")
        assert service._handshake(b, "tok", 1.0) is None
        msg = json.dumps({"type": "hello", "token": "toké"}).encode()
        a.sendall(b"J" + len(msg).to_bytes(4, "little") + msg)
        assert service._handshake(b, "tok", 1.0) is None       # non-ASCII: no TypeError
        msg = json.dumps({"type": "hello", "token": "tok"}).encode()
        a.sendall(b"J" + len(msg).to_bytes(4, "little") + msg)
        assert service._handshake(b, "tok", 1.0)["type"] == "hello"
    finally:
        a.close()
        b.close()


def test_service_that_exits_early_is_reported():
    events = []
    h = ServiceHost([sys.executable, "-c", "import sys; sys.exit(3)"], events.append, name="x")
    h.start()
    assert wait_for(lambda: any(e["type"] == "stopped" for e in events))
    assert "code 3" in events[-1]["text"]
    h.stop()


def test_a_message_that_breaks_the_reader_still_reports_stopped():
    # JSON nested too deep raises RecursionError: the UI must not stay on "listening"
    mod = ("import json,socket,struct,sys,time\n"
           "a=sys.argv; p=int(a[a.index('--port')+1]); t=a[a.index('--token')+1]\n"
           "s=socket.create_connection(('127.0.0.1',p))\n"
           "def fr(b): s.sendall(b'J'+struct.pack('<I',len(b))+b)\n"
           "fr(json.dumps({'type':'hello','token':t}).encode())\n"
           "fr(b'{\"type\":\"ready\"}')\n"
           "fr(b'['*100000 + b']'*100000)\n"
           "time.sleep(5)\n")
    events = []
    h = ServiceHost([sys.executable, "-c", mod], events.append, name="deep")
    h.start()
    try:
        assert wait_for(lambda: any(e["type"] == "stopped" for e in events))
        assert "recursion" in events[-1]["text"] and not h.connected
    finally:
        h.stop()


def test_feed_never_blocks_and_drops_oldest_when_nobody_reads():
    h = ServiceHost(["unused"], lambda e: None)
    h.connected = True                   # pretend: a module that stopped reading
    t0 = time.perf_counter()
    for _ in range(5000):
        h.feed(np.zeros(480, np.float32), 48000)
    assert time.perf_counter() - t0 < 0.5
    assert h._q.qsize() == service.QUEUE_BLOCKS and h.dropped > 0


# ---------------------------------------------------------------- controller

class FakeTTS:
    voices, error = ["Robo"], ""

    def __init__(self):
        self.said = []

    def warm_up(self):
        return self.voices

    def synth(self, text, voice="", rate=0):
        self.said.append((text, voice, rate))
        return np.full(2205, 0.1, np.float32), 22050

    def close(self):
        pass


class FakeEngine:
    def __init__(self):
        self.played = []
        self.stopped = []

    def play(self, sid, data, gain, mode="restart", src_rate=48000, **kw):
        self.played.append((sid, data.shape, gain, mode, src_rate))
        return object()                  # a Voice: something was open to play it on

    def stop(self, sid):
        self.stopped.append(sid)


_controllers: list[SpeechController] = []


@pytest.fixture(autouse=True)
def _shut_controllers_down():
    """Each controller's speaker runs a thread: end it with the test, not the run."""
    yield
    while _controllers:
        _controllers.pop().shutdown()


def controller(events=None):
    eng = FakeEngine()
    c = SpeechController(eng, VoiceChain(), (events if events is not None else []).append)
    c.tts = c.speaker.tts = FakeTTS()
    _controllers.append(c)
    return c, eng


def speaker_threads() -> int:
    return sum(t.name == "tts-speaker" for t in threading.enumerate())


def test_shutting_the_controller_down_ends_its_speaker_thread():
    before = speaker_threads()
    c, eng = controller()
    assert speaker_threads() == before + 1
    c.say("one")
    assert wait_for(lambda: len(eng.played) == 1)
    c.say("two")                    # still waiting out "one" when the shutdown comes
    c.shutdown()
    assert speaker_threads() == before
    assert not c.speaker._thread.is_alive()
    c.say("three")                  # a late line after the shutdown is just dropped
    time.sleep(0.1)
    assert len(eng.played) == 1


def test_typed_text_is_spoken_in_order_as_a_sound():
    c, eng = controller()
    c.speaker.voice = "Robo"
    c.gain = 0.5
    c.say("one")
    c.say("two")
    assert wait_for(lambda: len(eng.played) == 2)
    assert [s[0] for s in c.tts.said] == ["one", "two"]
    assert c.tts.said[0][1] == "Robo"
    assert eng.played[0] == ("tts", (2205, 2), 0.5, "overlap", 22050)
    c.stop_speaking()
    assert eng.stopped == ["tts"]


def test_live_voice_speaks_what_the_module_heard(tmp_path, monkeypatch):
    from soundboard import library
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    events = []
    c, eng = controller(events)
    mod = shutil.copytree(LIVE, tmp_path / "live-voice", ignore=shutil.ignore_patterns(".venv"))
    info = next(m for m in modules.discover([tmp_path]) if m.id == "live-voice")
    info.command = [sys.executable, "{dir}/helper.py", "--fake"]
    c.start_live(info)
    try:
        assert c.chain.tap is not None and c.chain.replace       # real voice muted
        assert wait_for(lambda: any(e["type"] == "ready" for e in events))
        for b in speechlike(np.random.default_rng(3), [(0.5, 0.002), (1.0, 0.2), (1.0, 0.002)]):
            c.chain.process(np.stack([b, b], 1), 48000)
            time.sleep(0.0005)
        assert wait_for(lambda: len(eng.played) == 1)
        assert c.tts.said[0][0].startswith("utterance 1")
        assert (tmp_path / "module-live-voice.log").exists()
    finally:
        c.stop_live()
    assert c.chain.tap is None and not c.chain.replace and not c.live
    del mod


def test_stopping_live_voice_silences_the_queued_backlog():
    c, eng = controller()
    gate = threading.Event()
    synth = c.tts.synth
    c.tts.synth = lambda *a: (gate.wait(5), synth(*a))[1]     # hold line 1 mid-synth
    for i in range(5):
        c.say(f"line {i}")
    assert wait_for(lambda: len(c.speaker._q) == 4)          # line 0 is being synthesized
    c.host = object.__new__(ServiceHost)                      # pretend live is on
    c.host.stop = lambda: None
    c.stop_live()
    gate.set()
    time.sleep(0.3)
    assert eng.played == []            # the line mid-synth and the queued ones are dropped
    assert eng.stopped == ["tts"]      # and whatever was already playing is cut


def test_real_voice_comes_back_if_the_module_dies():
    events = []
    c, _ = controller(events)
    info = modules.ModuleInfo(id="dies", name="dies", version="1", description="",
                              kind="service", path=ROOT,
                              command=[sys.executable, "-c", "import sys; sys.exit(1)"])
    c.start_live(info)
    assert c.chain.replace
    assert wait_for(lambda: any(e["type"] == "stopped" for e in events))
    assert not c.chain.replace and c.chain.tap is None and not c.live


# a module that connects, says `events` and then just hangs (ignores "quit")
HANGING_MODULE = ("import json,socket,struct,sys,time\n"
                  "a=sys.argv\n"
                  "s=socket.create_connection(('127.0.0.1',int(a[a.index('--port')+1])))\n"
                  "def j(o):\n"
                  "    b=json.dumps(o).encode(); s.sendall(b'J'+struct.pack('<I',len(b))+b)\n"
                  "j({'type':'hello','token':a[a.index('--token')+1]})\n"
                  "for e in json.loads(a[1]): j(e)\n"
                  "time.sleep(60)\n")


def hanging(events):
    return modules.ModuleInfo(id="hangs", name="hangs", version="1", description="",
                              kind="service", path=ROOT,
                              command=[sys.executable, "-c", HANGING_MODULE,
                                       json.dumps(events)])


def test_a_module_that_cant_load_gives_the_real_voice_back():
    events = []
    c, _ = controller(events)
    c.start_live(hanging([{"type": "error", "text": "no model"}]))
    assert wait_for(lambda: any(e["type"] == "stopped" for e in events))
    assert not c.chain.replace and c.chain.tap is None and not c.live
    assert events[-1] == {"type": "stopped", "text": "no model"}


def test_an_error_after_ready_keeps_live_voice_on():
    events = []
    c, _ = controller(events)
    c.start_live(hanging([{"type": "ready"}, {"type": "error", "text": "one line failed"}]))
    try:
        assert wait_for(lambda: any(e["type"] == "error" for e in events))
        time.sleep(0.1)
        assert c.live and c.chain.replace
    finally:
        c.stop_live()


def test_stop_never_waits_on_a_stuck_sender():
    h = ServiceHost(["unused"], lambda e: None)
    a, b = socket.socketpair()
    try:
        h._sock = a
        h._send_lock.acquire()                # the sender is stuck inside a send
        t0 = time.monotonic()
        h.stop()
        assert time.monotonic() - t0 < 1.0
    finally:
        h._send_lock.release()
        b.close()


def test_stop_still_says_quit_whole_then_hangs_up():
    h = ServiceHost(["unused"], lambda e: None)
    a, b = socket.socketpair()
    try:
        h._sock, h.connected = a, True
        h._send_lock.acquire()                # the sender is finishing a frame
        h.stop()                              # returns at once ...
        assert not h.connected and h._sock is None
        h._send_lock.release()                # ... and "quit" follows that frame
        b.settimeout(5)
        kind, payload = protocol.recv(b)
        assert kind == protocol.JSON and protocol.decode_json(payload) == {"type": "quit"}
        assert protocol.recv(b) is None       # then the link is closed
    finally:
        b.close()


def test_helper_exits_when_its_model_cant_load():
    try:
        import faster_whisper  # noqa: F401
        pytest.skip("speech recognition is installed here, so the model would load")
    except ImportError:
        pass
    events = []
    h = ServiceHost([sys.executable, str(LIVE / "helper.py")], events.append, name="live-voice")
    h.start()
    try:
        assert wait_for(lambda: any(e["type"] == "stopped" for e in events), 20)
        err = next(e for e in events if e["type"] == "error")
        assert "Update speech recognition" in err["text"]
        assert wait_for(lambda: h._proc is None or h._proc.poll() is not None)
    finally:
        h.stop()


def test_a_line_that_cant_be_played_is_reported_and_the_next_still_plays():
    events = []
    c, eng = controller(events)
    real, calls = eng.play, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("device went away")
        return real(*a, **k)

    eng.play = flaky
    c.say("one")
    c.say("two")
    assert wait_for(lambda: len(eng.played) == 1)
    assert {"type": "tts_error", "text": "device went away"} in events


def test_a_line_the_voice_cant_read_is_reported():
    # an English voice given Chinese or Arabic text makes no sound at all
    events = []
    c, eng = controller(events)
    c.tts.synth = lambda text, voice="", rate=0: (np.zeros(0, np.float32), 22050)
    c.say("你好世界")
    assert wait_for(lambda: events)
    assert events == [{"type": "tts_error", "text": "this voice can't read that text"}]
    assert eng.played == []


def test_no_open_device_says_so():
    events = []
    c, eng = controller(events)
    eng.play = lambda *a, **k: None       # what Engine.play returns with no output open
    c.say("hello")
    assert wait_for(lambda: any(e["type"] == "tts_error" for e in events))
    assert "No audio device" in events[0]["text"]


def test_windows_speech_that_stops_answering_is_restarted():
    import queue

    from soundboard.speech.tts import SapiTTS

    class Proc:
        killed = False

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):   # it's waited for so it lets go of its .wav
            assert self.killed
            return 1

    t, proc = SapiTTS(), Proc()
    t._proc, t._out = proc, queue.Queue()
    with pytest.raises(RuntimeError, match="stopped answering"):
        t._readline(0.05)
    assert proc.killed and t._proc is None


def test_windows_speech_output_that_isnt_utf8_cant_kill_the_reader(monkeypatch):
    import io

    from soundboard.speech import tts

    # the script switches its stdout to UTF-8 before it says anything
    assert tts._SCRIPT.index("[Console]::SetOut(") < tts._SCRIPT.index("WriteLine(")
    assert "UTF8Encoding $false" in tts._SCRIPT            # no BOM ahead of "READY"

    class Proc:
        def __init__(self, args, **kw):
            # a voice name and an error in the OEM code page (cp437), not UTF-8
            raw = "READY René\ten-US\nERR Zugriff verweigert ä\n".encode("cp437")
            self.stdout = io.TextIOWrapper(io.BytesIO(raw), encoding=kw["encoding"],
                                           errors=kw.get("errors", "strict"))
            self.stdin = io.StringIO()

        def poll(self):
            return None

    monkeypatch.setattr(tts.subprocess, "Popen", Proc)
    t = tts.SapiTTS()
    assert t.warm_up() == ["Ren�"] and t.error == ""
    with pytest.raises(RuntimeError, match="Zugriff verweigert"):
        t.synth("hello")                                  # an answer, not "stopped"
    t._proc = None


def test_windows_speech_unused_for_a_while_is_closed_and_comes_back(monkeypatch):
    """The hidden PowerShell holds ~85 MB: it's let go after IDLE_CLOSE_S without a
    line, and the next line starts it again without the caller noticing."""
    import base64
    import queue

    import soundfile as sf

    from soundboard.speech import tts
    started = []

    class Proc:
        def __init__(self, args, **kw):
            started.append(self)
            self.lines = queue.Queue()
            self.lines.put("READY Zira\ten-US\n")
            self.stdout = iter(self.lines.get, None)
            self.closed = False
            proc = self

            class Stdin:
                def write(self, req):   # "- 0 <b64 path> <b64 text>": a short WAV, then OK
                    path = base64.b64decode(req.split()[2]).decode()
                    sf.write(path, np.full(220, 0.1, np.float32), tts.TTS_RATE)
                    proc.lines.put("OK\n")

                def flush(self):
                    pass

                def close(self):
                    proc.closed = True
                    proc.lines.put(None)
            self.stdin = Stdin()

        def poll(self):
            return 0 if self.closed else None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(tts.subprocess, "Popen", Proc)
    monkeypatch.setattr(tts, "IDLE_CHECK_S", 3600)   # the watcher thread stays out of it
    now = [1000.0]
    t = tts.SapiTTS()
    t._clock = lambda: now[0]
    assert t.warm_up() == ["Zira"] and len(started) == 1
    now[0] += tts.IDLE_CLOSE_S - 10
    assert len(t.synth("hello")[0]) == 220            # a line resets the idle time
    now[0] += tts.IDLE_CLOSE_S - 10
    assert not t.close_if_idle() and not started[0].closed
    now[0] += 20
    assert t.close_if_idle() and started[0].closed and t._proc is None
    assert t.voices == ["Zira"]                       # the list stays for the menus
    assert len(t.synth("again")[0]) == 220 and len(started) == 2   # started again
    t.close()


def test_an_install_step_that_hangs_is_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(modules, "INSTALL_STEP_TIMEOUT_S", 0.5)
    info = modules.ModuleInfo(id="slow", name="slow", version="1", description="",
                              kind="service", path=tmp_path,
                              install_steps=[["{base_python}", "-c",
                                              "import time; time.sleep(60)"]])
    lines = []
    t0 = time.monotonic()
    assert not modules.install(info, lines.append)
    assert time.monotonic() - t0 < 20
    assert "internet connection" in lines[-1]


def test_an_install_is_stopped_if_reporting_its_output_fails(tmp_path):
    info = modules.ModuleInfo(id="x", name="x", version="1", description="",
                              kind="service", path=tmp_path,
                              install_steps=[["{base_python}", "-c",
                                              "import time; print('hi', flush=True); "
                                              "time.sleep(60)"]])
    seen = []

    def on_line(line):
        seen.append(line)
        if len(seen) > 1:
            raise RuntimeError("the UI went away")

    t0 = time.monotonic()
    with pytest.raises(RuntimeError):
        modules.install(info, on_line)
    assert time.monotonic() - t0 < 20       # the child was killed, not waited on


# ---------------------------------------------------------------- Windows voices

@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell.exe"),
                    reason="needs Windows PowerShell")
def test_windows_tts_speaks_into_memory():
    from soundboard.speech.tts import SapiTTS
    t = SapiTTS()
    try:
        voices = t.warm_up()
        if not voices:
            pytest.skip("no Windows voices installed")
        audio, rate = t.synth("Testing, one two.", voices[0], 3)
        assert rate == 22050 and audio.dtype == np.float32
        assert 0.3 < len(audio) / rate < 5 and np.abs(audio).max() > 0.05
        with pytest.raises(RuntimeError):
            t.synth("x", "No Such Voice")
        assert len(t.synth("still works")[0])        # an error doesn't kill the engine
    finally:
        t.close()


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell.exe"),
                    reason="needs Windows PowerShell")
def test_windows_default_voice_comes_back_after_a_named_one():
    from soundboard.speech.tts import SapiTTS
    t = SapiTTS()
    try:
        voices = [v for v in t.warm_up() if v.endswith(" Desktop")]
        line = "The quick brown fox jumps over the lazy dog."
        default = t.synth(line)[0]
        other = next((v for v in voices if len(t.synth(line, v)[0]) != len(default)), None)
        if other is None:
            pytest.skip("needs two different Windows desktop voices")
        assert np.array_equal(t.synth(line)[0], default)   # not stuck on `other`
    finally:
        t.close()


def test_helper_refuses_to_run_without_the_app():
    r = subprocess.run([sys.executable, str(LIVE / "helper.py")], capture_output=True,
                       timeout=30)
    assert r.returncode != 0 and b"--port" in r.stderr


# ---------------------------------------------------------------- translation add-ons

LANGS = {"zh", "es", "fr", "de", "ru", "it", "pt-PT", "pt-BR", "nl", "pl", "cs", "sk", "sl",
         "hu", "ro", "bg", "el", "da", "sv", "nb", "fi", "ca", "ja", "ko", "zh-TW", "th",
         "vi", "id", "ms", "hi", "ar", "he", "tr"}


def test_repo_ships_the_translation_addons_not_downloaded():
    infos = [m for m in modules.discover([ROOT / "modules"]) if m.kind == "translation"]
    assert {m.language for m in infos} == LANGS
    for m in infos:
        assert not m.error and m.language_name and m.credits
        assert m.download["url"].startswith("https://") and m.download["bytes"] > 1e6
        assert not m.installed          # nothing is fetched until the user asks
    assert not list((ROOT / "modules").glob("translate-*/model"))


def test_every_speak_language_has_a_name_in_every_app_language():
    """langnames_data.py is current: rerun scripts/make_langnames.py when this fails."""
    from soundboard import i18n, langnames
    from soundboard.langnames_data import NAMES
    apps = {"en"} | {p.stem for p in (ROOT / "assets" / "lang").glob("*.json")}
    assert set(NAMES) == apps
    assert all(set(names) == LANGS and all(names.values()) for names in NAMES.values())
    try:
        i18n.set_language("de")
        assert langnames.name("ja") == "Japanisch"
        assert langnames.name("pt-BR") == "Portugiesisch (Brasilien)"
        dk, de = (SimpleNamespace(language=c, language_name="") for c in ("da", "de"))
        assert langnames.sort_key(dk) < langnames.sort_key(de)    # Dänisch, Deutsch
        assert langnames.name("xq", "Klingon") == "Klingon"     # not in the table yet
    finally:
        i18n.set_language("en")
    assert langnames.name("zh-TW") == "Traditional Chinese"


def test_translation_manifest_needs_https_and_a_checksum(tmp_path):
    good = {"url": "https://example.com/m.zip", "sha256": "a" * 64, "bytes": 5}
    write_module(tmp_path / "ok", id="ok", kind="translation", language="de", download=good)
    write_module(tmp_path / "tw", id="tw", kind="translation", language="zh-TW", download=good)
    write_module(tmp_path / "bad", id="bad", kind="translation", language="zh_tw", download=good)
    write_module(tmp_path / "http", id="http", kind="translation", language="de",
                 download={**good, "url": "http://example.com/m.zip"})
    write_module(tmp_path / "nosum", id="nosum", kind="translation", language="de",
                 download={"url": good["url"]})
    write_module(tmp_path / "nolang", id="nolang", kind="translation", download=good)
    got = {m.id: m for m in modules.discover([tmp_path])}
    assert got["ok"].error == "" and got["tw"].error == ""
    assert all(got[k].error for k in ("http", "nosum", "nolang", "bad"))


def model_package(path: Path, top="translate-en_xx-1_0") -> tuple[str, int]:
    """A tiny .argosmodel-shaped zip, plus files that must never be unpacked."""
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{top}/model/model.bin", b"weights")
        z.writestr(f"{top}/model/config.json", b"{}")
        z.writestr(f"{top}/sentencepiece.model", b"tokens")
        z.writestr(f"{top}/README.md", b"readme")
        z.writestr(f"{top}/stanza/en/tokenize.pt", b"x")
        z.writestr("../../escape.txt", b"nope")
        z.writestr(f"{top}/model/../../../escape2.txt", b"nope")
    import hashlib
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def translation_info(tmp_path, sha, size, lang="xx"):
    zip_path = tmp_path / "pkg.argosmodel"
    return modules.ModuleInfo(id=f"translate-{lang}", name="T", version="1", description="",
                              kind="translation", path=tmp_path, language=lang,
                              language_name="Test", download={"url": zip_path.as_uri(),
                                                              "sha256": sha, "bytes": size})


def test_download_checks_the_sum_and_unpacks_only_the_model(tmp_path):
    from soundboard.speech import translation
    sha, size = model_package(tmp_path / "pkg.argosmodel")
    info = translation_info(tmp_path, sha, size)
    seen = []
    translation.download(info, lambda done, total: seen.append((done, total)))
    d = translation.model_dir(info)
    assert info.installed and d.is_relative_to(translation.base_dir())
    files = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
    assert files == ["model/config.json", "model/model.bin", "sentencepiece.model"]
    assert seen[-1][0] == size
    assert not list(tmp_path.rglob("escape*.txt"))
    assert not list(translation.base_dir().glob("*.part"))
    translation.remove(info)
    assert not info.installed


def test_download_with_the_wrong_sum_is_thrown_away(tmp_path):
    from soundboard.speech import translation
    _, size = model_package(tmp_path / "pkg.argosmodel")
    info = translation_info(tmp_path, "0" * 64, size)
    with pytest.raises(RuntimeError, match="checksum"):
        translation.download(info)
    assert not info.installed and not list(translation.base_dir().glob("*"))


def test_download_can_be_cancelled(tmp_path):
    from soundboard.speech import translation
    sha, size = model_package(tmp_path / "pkg.argosmodel")
    info = translation_info(tmp_path, sha, size)
    with pytest.raises(translation.Cancelled):
        translation.download(info, cancelled=lambda: True)
    assert not info.installed and not list(translation.base_dir().glob("*"))


def test_live_voice_speaks_the_translation_in_the_languages_voice(tmp_path, monkeypatch):
    from soundboard import library
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    events = []
    c, eng = controller(events)
    shutil.copytree(LIVE, tmp_path / "live-voice", ignore=shutil.ignore_patterns(".venv"))
    info = next(m for m in modules.discover([tmp_path]) if m.id == "live-voice")
    info.command = [sys.executable, "{dir}/helper.py", "--fake"]
    c.live_voice = "Katja"
    c.start_live(info, ["--translate", str(tmp_path / "model")])
    try:
        assert wait_for(lambda: any(e["type"] == "ready" for e in events))
        for b in speechlike(np.random.default_rng(3), [(0.5, 0.002), (1.0, 0.2), (1.0, 0.002)]):
            c.chain.process(np.stack([b, b], 1), 48000)
            time.sleep(0.0005)
        assert wait_for(lambda: len(eng.played) == 1)
        final = next(e for e in events if e["type"] == "final")
        assert final["text"].startswith("[translated] utterance 1")
        assert final["original"].startswith("utterance 1")
        assert c.tts.said[0][:2] == (final["text"], "Katja")
    finally:
        c.stop_live()
    c.say("typed")                     # typed lines keep the chosen voice
    assert wait_for(lambda: len(c.tts.said) == 2)
    assert c.tts.said[1][:2] == ("typed", "")


def test_voice_listing_and_picking_a_voice_for_a_language():
    from soundboard.speech.tts import SapiTTS, parse_voices
    names, langs = parse_voices("Microsoft Zira Desktop\ten-US|Microsoft Katja\tde-DE|"
                                "Microsoft Stefan\tde-DE|Microsoft Huihui\tzh-CN|Old\t|")
    assert names == ["Microsoft Zira Desktop", "Microsoft Katja", "Microsoft Stefan",
                     "Microsoft Huihui", "Old"]
    t = SapiTTS()
    t.voices, t.voice_langs = names, langs
    assert t.voice_for("de") == "Microsoft Katja"
    assert t.voice_for("de", prefer="Microsoft Stefan") == "Microsoft Stefan"
    assert t.voice_for("de", prefer="Microsoft Zira Desktop") == "Microsoft Katja"
    assert t.voice_for("zh") == "Microsoft Huihui"
    assert t.voice_for("ru") == ""
    # a country: that country's voice first, else any voice of the language
    t.voices = names + ["Microsoft Hanhan"]
    t.voice_langs = {**langs, "Microsoft Hanhan": "zh-TW"}
    assert t.voice_for("zh-TW") == "Microsoft Hanhan"
    assert t.voice_for("zh-TW", prefer="Microsoft Huihui") == "Microsoft Hanhan"
    assert t.voice_for("zh") == "Microsoft Huihui"
    assert t.voice_for("de-AT") == "Microsoft Katja"
