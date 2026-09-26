"""Add-on modules, the service-module link, the live-voice helper and text-to-speech."""
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from soundboard import modules, voicefx
from soundboard.speech import protocol
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


def test_service_that_exits_early_is_reported():
    events = []
    h = ServiceHost([sys.executable, "-c", "import sys; sys.exit(3)"], events.append, name="x")
    h.start()
    assert wait_for(lambda: any(e["type"] == "stopped" for e in events))
    assert "code 3" in events[-1]["text"]
    h.stop()


def test_feed_never_blocks_and_drops_oldest_when_nobody_reads():
    h = ServiceHost(["unused"], lambda e: None)
    h.connected = True                   # pretend: a module that stopped reading
    t0 = time.perf_counter()
    for _ in range(5000):
        h.feed(np.zeros(480, np.float32), 48000)
    assert time.perf_counter() - t0 < 0.5
    assert len(h._q) == h._q.maxlen and h.dropped > 0


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

    def stop(self, sid):
        self.stopped.append(sid)


def controller(events=None):
    eng = FakeEngine()
    c = SpeechController(eng, VoiceChain(), (events if events is not None else []).append)
    c.tts = c.speaker.tts = FakeTTS()
    return c, eng


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


def test_helper_refuses_to_run_without_the_app():
    r = subprocess.run([sys.executable, str(LIVE / "helper.py")], capture_output=True,
                       timeout=30)
    assert r.returncode != 0 and b"--port" in r.stderr
