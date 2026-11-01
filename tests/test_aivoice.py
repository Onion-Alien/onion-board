"""AI voices: the add-on's files, its signal code, the voice source in the mic chain,
the helper round trip (--fake: no model, no onnxruntime), getting and removing the
optional add-on, and the Voice tab card."""
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest

from soundboard.addons import aiaddon, modules
from soundboard import voicefx
from soundboard.speech import aivoice
from soundboard.speech.aivoice import AiVoiceController, TalkGate, VoiceSource
from soundboard.voicefx import VoiceChain
from tests.conftest import process_events

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "modules" / "ai-voices"
RATE = 48000
BLOCK = 480


@pytest.fixture
def addon_code():
    sys.path.insert(0, str(ADDON))
    try:
        import converter
        import helper
        yield converter, helper
    finally:
        sys.path.remove(str(ADDON))
        for m in ("converter", "helper", "protocol"):
            sys.modules.pop(m, None)


def noise(sec, amp, seed=0):
    return (np.random.default_rng(seed).standard_normal(int(sec * RATE)) * amp).astype(np.float32)


# ---------------------------------------------------------------- the add-on's files

def test_addon_ships_the_apps_protocol_and_valid_voices():
    app = (ROOT / "soundboard" / "speech" / "protocol.py").read_bytes()
    assert (ADDON / "protocol.py").read_bytes() == app
    (info,) = [m for m in modules.discover([ROOT / "modules"]) if m.id == "ai-voices"]
    assert not info.error and info.kind == "service" and "ai-voice" in info.provides
    data = json.loads((ADDON / "voices.json").read_text(encoding="utf-8"))
    ids = [v["id"] for v in data["voices"]]
    assert len(ids) == len(set(ids)) >= 3
    for v in data["voices"]:
        assert v["name"] and v["description"]
        assert v["mix"] and all(isinstance(s, int) and w > 0 for s, w in v["mix"])
        assert -2 <= v["formant"] <= 2 and 60 <= v["pitch_hz"] <= 400
    # every dependency pinned: install runs pip -r automatically
    reqs = [ln for ln in (ADDON / "requirements.txt").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    assert reqs and all("==" in ln for ln in reqs)


def test_the_helper_reads_your_own_voices_from_the_apps_file(addon_code, tmp_path,
                                                             monkeypatch):
    """A copy shipped with the app (the source tree's) isn't written to: the helper
    takes your voices from the file the app names (helper_env)."""
    _c, helper = addon_code
    built = [v["id"] for v in helper.load_voices()["voices"]]
    mine = tmp_path / "ai-voices.json"
    mine.write_text(json.dumps({"voices": [
        {"id": "my-robo", "name": "Robo", "mix": [[171, 1.0]], "formant": 0, "pitch_hz": 99},
        {"id": "bear", "name": "Not mine", "mix": [[5, 1.0]]},
        {"id": "my-empty", "name": "No mix"}]}), encoding="utf-8")
    monkeypatch.setenv("ONIONBOARD_MY_AI_VOICES", str(mine))
    voices = helper.load_voices()
    assert [v["id"] for v in voices["voices"]] == built + ["my-robo"]
    assert helper.pick(voices, "my-robo")["pitch_hz"] == 99
    monkeypatch.setenv("ONIONBOARD_MY_AI_VOICES", str(tmp_path / "gone.json"))
    assert [v["id"] for v in helper.load_voices()["voices"]] == built
    assert aivoice.helper_env({})["ONIONBOARD_MY_AI_VOICES"].endswith("ai-voices.json")


def test_the_addon_is_not_built_into_the_app():
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert 'Where-Object Name -ne "ai-voices"' in build


# ---------------------------------------------------------------- converter (numpy parts)

def test_synth_output_doesnt_depend_on_how_the_frames_are_chunked(addon_code):
    """The pulse train, noise and post filter carry state across calls: feeding the same
    frames 2 at a time or 6 at a time must give the same samples (a pitch mark on a
    chunk's last sample is the tricky case)."""
    conv, _h = addon_code
    rng = np.random.default_rng(3)
    n = 60
    amp = np.exp(rng.standard_normal((n, 257)) * 0.3) * 0.05
    ph = rng.uniform(-np.pi, np.pi, (n, 257))
    aper = np.abs(rng.standard_normal((n, 240))) * 0.01
    post = np.zeros((n, 512))
    post[:, 0] = 1.0
    post[:, 1:20] = rng.standard_normal((n, 19)) * 0.01
    hz = 90 + 150 * rng.random(n)
    win = np.hanning(512)
    outs = []
    for step in (2, 6):
        s = conv.Synth(win, np.random.default_rng(7))
        outs.append(np.concatenate([s.feed(amp[i:i + step], ph[i:i + step], aper[i:i + step],
                                           post[i:i + step], hz[i:i + step])
                                    for i in range(0, n, step)]))
    a, b = outs
    assert len(a) == len(b) == n * 240
    # (an impulse's very first sample on a chunk edge is the one allowed difference)
    assert np.abs(a - b).max() < 0.05 * np.abs(a).max()
    assert np.mean(np.abs(a - b) > 1e-6) < 0.01


def test_synth_makes_the_pitch_its_told(addon_code):
    conv, _h = addon_code
    n = 100
    amp = np.full((n, 257), 0.05)
    s = conv.Synth(np.hanning(512), np.random.default_rng(0))
    post = np.zeros((n, 512))
    post[:, 0] = 1.0
    y = s.feed(amp, np.zeros((n, 257)), np.zeros((n, 240)), post, np.full(n, 150.0))
    z = y[2400:] - y[2400:].mean()
    ac = np.correlate(z, z, "full")[len(z) - 1:]
    period = 80 + int(np.argmax(ac[80:400]))           # 60..300 Hz
    assert period == pytest.approx(24000 / 150, abs=1)


def test_pitch_features_match_a_whole_clip_done_at_once(addon_code):
    """Frame-by-frame features (with the previous frame's phase carried) equal the
    features of all frames in one call."""
    conv, _h = addon_code
    x = np.random.default_rng(1).standard_normal(160 * 40 + 600).astype(np.float32) * 0.1
    frames = np.stack([x[160 * k:160 * k + 560] for k in range(40)])
    whole = conv.PitchFeatures()(frames)
    pf = conv.PitchFeatures()
    parts = np.concatenate([pf(frames[i:i + 2]) for i in range(0, 40, 2)])
    assert whole.shape == (40, 449)
    np.testing.assert_allclose(parts, whole, atol=1e-5)


def test_pitch_tracker_finds_your_usual_pitch(addon_code):
    conv, _h = addon_code
    t = conv.PitchTracker()
    assert t.median_hz() is None
    for _ in range(30):
        t.add(np.array([110.0, 120.0, 400.0]), np.array([True, True, False]))
    assert 108 < t.median_hz() < 122


# ---------------------------------------------------------------- the voice source

def test_talk_gate_opens_when_you_talk_and_closes_after_a_pause():
    g = TalkGate(hang_s=0.3)
    for b in noise(1.0, 0.001).reshape(-1, BLOCK):
        assert not g.update(b, RATE)
    assert g.update(noise(0.01, 0.2), RATE)
    quiet = noise(0.5, 0.001).reshape(-1, BLOCK)
    states = [g.update(b, RATE) for b in quiet]
    assert states[0] and not states[-1]
    assert states.index(False) * BLOCK / RATE == pytest.approx(0.3, abs=0.02)


def make_source(**kw):
    fed, quiet = [], []
    src = VoiceSource(lambda m, r: fed.append(len(m)), lambda: quiet.append(1), **kw)
    src.ready = True
    return src, fed, quiet


def test_source_sends_only_while_talking_with_preroll_and_says_when_you_stop():
    src, fed, quiet = make_source()
    for b in noise(1.0, 0.001).reshape(-1, BLOCK):
        src.process(b, RATE)
    assert fed == []                                   # quiet: nothing goes to the helper
    src.process(noise(0.01, 0.2), RATE)
    assert sum(fed) / RATE == pytest.approx(aivoice.PREROLL_S + 0.01, abs=0.011)
    for b in noise(1.0, 0.001).reshape(-1, BLOCK):
        src.process(b, RATE)
    assert quiet == [1]


def test_speaking_another_language_sends_the_translated_lines_not_your_mic():
    """Dub mode: the AI voice gets the translated text-to-speech lines (at the mic's
    rate), and your loud real voice never reaches the helper."""
    got = []
    src = VoiceSource(lambda m, r: got.append(m.copy()), None)
    src.ready = True
    src.dub_on = True
    src.process(np.zeros(BLOCK, np.float32), RATE)          # learns the mic's rate
    line = np.full(int(0.5 * 24000), 0.3, np.float32)       # a 24 kHz "spoken" line
    src.dub(line, 24000)
    loud_mic = np.full(BLOCK, 0.9, np.float32)
    for _ in range(int(0.6 * RATE / BLOCK)):
        src.process(loud_mic, RATE)
    sent = np.concatenate(got)
    assert len(sent) / RATE >= 0.5                          # the whole line went
    assert sent.max() < 0.5                                  # the line, not the mic
    src.dub(line, 24000)
    src.clear_dub()                                          # Stop: queued lines go
    assert not src._dub and not len(src._dub_head)


def test_source_plays_what_comes_back_after_its_jitter_buffer():
    src, _fed, _q = make_source(backup="mute")
    src.process(np.zeros(BLOCK, np.float32), RATE)      # learns the rate
    tone = (0.3 * np.sin(np.arange(480) * 0.05)).astype(np.float32)
    pcm = np.rint(tone * 32767).astype("<i2").tobytes()
    out = []
    for _ in range(20):
        src.push(pcm)                                   # 20 ms at 24 kHz each
        out.append(src.process(noise(0.01, 0.2), RATE))
    y = np.concatenate(out)
    assert np.abs(y).max() > 0.2                        # the converted voice, not silence
    assert src.underruns == 0


def test_backup_takes_over_when_the_helper_goes_quiet_while_you_talk():
    src, _fed, _q = make_source(backup="mic")
    talk = noise(1.0, 0.2).reshape(-1, BLOCK)
    out = [src.process(b, RATE) for b in talk]          # nothing ever comes back
    first, last = out[0], out[-1]
    assert not first.any()                              # silence first (it may just be late)
    np.testing.assert_allclose(last, talk[-1])          # then the backup: here, the mic
    src.backup = "mute"
    assert not src.process(talk[0], RATE).any()


def test_a_dead_helper_leaves_the_backup_voice_not_the_real_one():
    src, _fed, _q = make_source()
    src.dead = True
    m = noise(0.01, 0.2)
    y = src.process(m, RATE)
    assert y.shape == m.shape and not np.allclose(y, m)     # the built-in preset


def test_chain_source_replaces_your_voice_and_a_broken_one_mutes_not_leaks():
    c = VoiceChain()

    class Half:
        def process(self, m, rate):
            return m * 0.5

        def latency(self):
            return 0.07

    c.source = Half()
    x = np.ones((BLOCK, 2), np.float32)
    assert c.active and np.allclose(c.process(x, RATE), 0.5)
    assert c.latency() == pytest.approx(0.07)

    class Broken:
        def process(self, m, rate):
            raise RuntimeError("boom")

    c.source = Broken()
    assert not c.process(x, RATE).any() and c.source is None
    assert "ai-voice" in c.errors


def test_settings_are_cleaned():
    assert aivoice.clean_settings(None) == {"voice": "", "auto_pitch": True, "pitch": 0.0,
                                            "backup": "voice"}
    s = aivoice.clean_settings({"voice": "nova", "auto_pitch": False, "pitch": 30,
                                "backup": "nope"})
    assert s == {"voice": "nova", "auto_pitch": False, "pitch": 12.0, "backup": "voice"}
    assert aivoice.clean_settings({"pitch": float("nan")})["pitch"] == 0.0


def test_the_jitter_buffer_follows_the_helpers_chunk():
    """The lighter model sends 40 ms at a time, each a little late now and then (its
    compute time). With the buffer sized for 20 ms chunks that ran dry ~80 times in 12 s
    and skipped ahead ~40 times; sized to the chunk, it plays through."""
    assert aivoice.buffer_limits(aivoice.CHUNK_S) == (
        aivoice.JITTER_S, aivoice.MAX_BUFFER_S, aivoice.TRIM_TO_S)
    src, _fed, _q = make_source(backup="mute")
    src.chunk_s = 0.04
    drops = []
    real_drop = src._drop
    src._drop = lambda k: drops.append(k) or real_drop(k)
    tone = (0.3 * np.sin(np.arange(960) * 0.05)).astype(np.float32)
    pcm = np.rint(tone * 32767).astype("<i2").tobytes()
    rng = np.random.default_rng(0)
    # chunk k is ready after its 40 ms are in, plus 0-30 ms of compute
    arrive = sorted(4 * k + 4 + int(rng.integers(0, 4)) for k in range(300))
    src.process(np.zeros(BLOCK, np.float32), RATE)       # learns the rate
    j = 0
    for b in range(1200):
        while j < len(arrive) and arrive[j] <= b:
            src.push(pcm)
            j += 1
        src.process(noise(0.01, 0.2, seed=b), RATE)
    assert src.underruns <= 3 and not drops
    assert src.latency() == pytest.approx(aivoice.LATENCY_S + 0.04)


def test_the_helpers_chunk_comes_from_its_ready_and_an_older_one_means_20_ms():
    ctl = AiVoiceController(VoiceChain(), lambda ev: seen.append(ev))
    seen = []
    host = ctl.host = object()
    for ready, want in (({}, 0.02), ({"chunk_s": 0.04}, 0.04), ({"chunk_s": "x"}, 0.02),
                        ({"chunk_s": float("nan")}, 0.02), ({"chunk_s": 9}, 0.1)):
        ctl.source, _f, _q = make_source()
        ctl._event({"type": "ready", **ready}, host)
        assert ctl.source.chunk_s == want
    ctl.source.chunk_s = 0.04
    ctl._event({"type": "stats", "cpu": 20}, host)
    assert seen[-1]["latency_s"] == pytest.approx(aivoice.LATENCY_S + 0.04)
    ctl.host = None


# ---------------------------------------------------------------- helper round trip

def fake_module() -> modules.ModuleInfo:
    return modules.ModuleInfo(id="ai-voices", name="AI voices", version="0", description="",
                              kind="service", path=ADDON,
                              command=[sys.executable, str(ADDON / "helper.py"), "--fake"])


@pytest.mark.parametrize("light", [False, True])
def test_your_voice_goes_to_the_helper_and_comes_back_converted(app_dir, light):
    """Use less CPU: the helper is told (ONIONBOARD_LESS_CPU) and converts 40 ms a call."""
    chain = VoiceChain()
    events = []
    ctl = AiVoiceController(chain, events.append)
    voicefx.set_light(light)
    try:
        ctl.start(fake_module(), "nova")
    finally:
        voicefx.set_light(False)
    try:
        assert chain.source is ctl.source
        end = time.monotonic() + 15
        while not ctl.source.ready and time.monotonic() < end:
            chain.process(np.zeros((BLOCK, 2), np.float32), RATE)
            time.sleep(0.01)
        assert ctl.source.ready
        assert any(e.get("type") == "ready" and e.get("rate") == 24000 for e in events)
        assert ctl.source.chunk_s == (0.04 if light else 0.02)
        x = noise(2.0, 0.2, seed=5)
        out = []
        for i in range(0, len(x), BLOCK):
            b = np.repeat(x[i:i + BLOCK, None], 2, axis=1)
            out.append(chain.process(b, RATE)[:, 0])
            time.sleep(0.009)                            # about real time
        y = np.concatenate(out)
        # the fake helper sends your voice back: after the delay, the output is loud.
        # (Not timed tightly: a busy test machine may starve it now and then.)
        assert np.abs(y[RATE // 2:]).mean() > 0.03
        assert ctl.source.underruns < 60
    finally:
        ctl.stop()
    assert chain.source is None


def test_helper_wont_run_without_the_app(addon_code):
    _c, helper = addon_code
    with pytest.raises(SystemExit):
        helper.main([])


def test_helper_download_needs_a_known_model(addon_code, tmp_path, monkeypatch, capsys):
    _c, helper = addon_code
    monkeypatch.setattr(helper, "HERE", tmp_path)
    (tmp_path / "voices.json").write_text(json.dumps({"model": {"url": "", "sha256": ""},
                                                      "voices": []}))
    assert helper.download() == 1
    assert "doesn't say where" in capsys.readouterr().out


# ---------------------------------------------------------------- getting the add-on

def addon_zip(tmp_path) -> Path:
    z = tmp_path / "AiVoices-module.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in ("module.json", "voices.json", "helper.py", "converter.py", "protocol.py",
                  "requirements.txt"):
            zf.write(ADDON / f, f"ai-voices/{f}")
        for f in ("stream.onnx", "speaker.onnx", "voices.npz"):
            zf.writestr(f"ai-voices/model/{f}", b"x")
    return z


def test_remove_a_copy_that_came_with_the_app_keeps_its_files(tmp_path):
    """Running from the app's own modules folder (not downloaded into %APPDATA%):
    Remove takes what its install added, the environment and the voice model, and
    leaves the add-on, so Install gets it back."""
    folder = tmp_path / "app" / aiaddon.MODULE_ID
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"x")
    (folder / "model").mkdir()
    (folder / "model" / "stream.onnx").write_bytes(b"x")
    (folder / "helper.py").write_text("")
    info = modules.ModuleInfo(id=aiaddon.MODULE_ID, name="AI voices", version="1",
                              description="", kind="service", path=folder)
    base = tmp_path / "appdata-modules"
    assert not aiaddon.removable(info, base)
    aiaddon.remove(info, base)
    assert not (folder / ".venv").exists() and not (folder / "model").exists()
    assert (folder / "helper.py").exists()
    assert sorted(p.name for p in folder.iterdir()) == ["helper.py"]


def test_get_and_remove_the_optional_addon(tmp_path, monkeypatch):
    monkeypatch.setenv(aiaddon.LOCAL_ENV, str(addon_zip(tmp_path)))
    base = tmp_path / "modules"
    offer = aiaddon.latest()
    info = aiaddon.install(aiaddon.fetch(offer), base)
    assert info.id == "ai-voices" and (base / "ai-voices" / "model" / "voices.npz").is_file()
    assert aiaddon.removable(info, base)
    aiaddon.remove(info, base)
    assert not (base / "ai-voices").exists()


# ---------------------------------------------------------------- the Voice tab card

def test_card_offers_the_download_when_the_addon_isnt_there(qapp):
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [])
    try:
        assert not p.b_get.isHidden() and p.ready_box.isHidden()
        assert "optional" in p.lbl_missing.text()
    finally:
        p.shutdown()
        p.deleteLater()


def test_card_lists_the_voices_once_installed(qapp, tmp_path, monkeypatch):
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for f in ("module.json", "voices.json"):
        (folder / f).write_bytes((ADDON / f).read_bytes())
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (folder / "model").mkdir()
    for f in ("stream.onnx", "speaker.onnx", "voices.npz"):
        (folder / "model" / f).write_bytes(b"x")
    (info,) = modules.discover([tmp_path])
    saved, starts, switches = [], [], []
    ctl = AiVoiceController(VoiceChain(), lambda e: None)

    def fake_start(module, voice, auto_pitch=True, pitch=0.0, args=()):
        starts.append(voice)
        ctl.host = object()          # running
    monkeypatch.setattr(ctl, "start", fake_start)
    monkeypatch.setattr(ctl, "stop", lambda: setattr(ctl, "host", None))
    monkeypatch.setattr(ctl, "set_voice", lambda vid, pitch: switches.append(vid))
    p = AiVoicePanel(ctl, {"voice": "pixie"}, [info])
    p.changed.connect(saved.append)
    try:
        assert not p.ready_box.isHidden() and p.b_get.isHidden()
        # off: no card lit up, even the saved one
        assert len(p._tile) >= 3 and not any(b.isChecked() for b in p._tile.values())
        assert not p.is_on()
        first, second = p.voices[0]["id"], p.voices[1]["id"]
        # clicking a card turns the AI voice on with that voice, like the voice changer
        p._tile[first].click()
        process_events(qapp, lambda: bool(saved))
        assert saved[-1]["voice"] == first
        assert p.is_on() and starts == [first] and p.b_start.text() == "On"
        # the voice changer's bar: the voice that's on, under the cards
        assert not p.picked.isHidden() and p.picked_name.text() == p.voices[0]["name"]
        # while it's on, another card switches voice without starting it again
        p._tile[second].click()
        assert starts == [first] and switches == [second] and p.is_on()
        # and a card clicked after Stop starts it again
        p.b_start.setChecked(False)
        p._tile[first].click()
        assert starts == [first, first] and p.is_on()
    finally:
        p.shutdown()
        p.deleteLater()


def test_your_own_voices_come_before_the_ready_made_ones(qapp, tmp_path):
    """Under All, the voices you recorded (Mine) are the first cards: under the long
    grid of ready-made ones they were out of sight."""
    from soundboard.speech import aivoicelist as avl
    from soundboard.ui.voice.aivoicepanel import MAKE, MINE, AiVoicePanel
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for f in ("module.json", "voices.json"):
        (folder / f).write_bytes((ADDON / f).read_bytes())
    (info,) = modules.discover([tmp_path])
    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [info])
    try:
        p.voices = [*p.voices, {"id": avl.MY_PREFIX + "gravel", "name": "Gravel",
                                "pitch_hz": 300}]
        p._fill_tiles()
        p.show_group("")   # All
        g = p._tile_grid

        def row(w):
            return g.getItemPosition(g.indexOf(w))[0]
        mine = row(p._tile[avl.MY_PREFIX + "gravel"])
        assert row(p._heads[MINE]) == 0 and mine == 1
        assert row(p.make_tile) == mine   # Make your own voice right after yours
        assert all(row(b) > mine for vid, b in p._tile.items()
                   if not avl.is_mine({"id": vid}) and vid != MAKE)
    finally:
        p.shutdown()
        p.deleteLater()


def test_card_tries_once_more_when_the_helper_never_calls_back(qapp, tmp_path, monkeypatch):
    """A helper that sat silent (no hello) gets one silent retry; a second silence,
    or one that connected and then failed, is shown."""
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for f in ("module.json", "voices.json"):
        (folder / f).write_bytes((ADDON / f).read_bytes())
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (info,) = modules.discover([tmp_path])
    ctl = AiVoiceController(VoiceChain(), lambda e: None)
    starts = []

    def fake_start(module, voice, auto_pitch=True, pitch=0.0, args=()):
        starts.append(voice)
        ctl.host = object()          # running
    monkeypatch.setattr(ctl, "start", fake_start)
    monkeypatch.setattr(ctl, "stop", lambda: setattr(ctl, "host", None))
    p = AiVoicePanel(ctl, {"voice": "pixie"}, [info])
    try:
        p.b_start.setChecked(True)
        assert len(starts) == 1
        p._on_event({"type": "stopped", "text": "ai-voices didn't connect"})
        assert len(starts) == 2 and "again" in p.lbl_state.text() and p.is_on()
        p._on_event({"type": "stopped", "text": "ai-voices didn't connect"})
        assert len(starts) == 2 and "didn't connect" in p.lbl_state.text()
        # a fresh Start gets its own retry; one that said hello first doesn't
        p.b_start.setChecked(False)
        p.b_start.setChecked(True)
        p._on_event({"type": "hello"})
        p._on_event({"type": "stopped", "text": "broke"})
        assert len(starts) == 3 and "broke" in p.lbl_state.text()
        # the helper's own reason stays when its link then just closes
        p.b_start.setChecked(False)
        p.b_start.setChecked(True)
        p._on_event({"type": "hello"})
        p._on_event({"type": "error", "text": "not enough free memory"})
        p._on_event({"type": "stopped", "text": ""})
        assert "not enough free memory" in p.lbl_state.text()
    finally:
        p.shutdown()
        p.deleteLater()


def test_card_gives_up_on_a_helper_that_never_gets_ready(qapp, tmp_path, monkeypatch):
    """A helper stuck loading gets one silent retry, then the card says it failed (the
    backup keeps covering you); cards picked meanwhile don't claim to switch."""
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for f in ("module.json", "voices.json"):
        (folder / f).write_bytes((ADDON / f).read_bytes())
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (info,) = modules.discover([tmp_path])
    ctl = AiVoiceController(VoiceChain(), lambda e: None)
    starts, sent, gave_up = [], [], []

    def fake_start(module, voice, auto_pitch=True, pitch=0.0, args=()):
        starts.append(voice)
        ctl.host = object()          # running
    monkeypatch.setattr(ctl, "start", fake_start)
    monkeypatch.setattr(ctl, "stop", lambda: setattr(ctl, "host", None))
    monkeypatch.setattr(ctl, "set_voice", lambda v, pitch=0.0: sent.append(v))
    monkeypatch.setattr(ctl, "give_up", lambda: gave_up.append(1))
    p = AiVoicePanel(ctl, {"voice": "duke"}, [info])
    try:
        p.b_start.setChecked(True)
        assert p._load_timer.isActive()
        p._on_event({"type": "hello"})
        p.pick("sage")                       # still loading: queued, no "switching to"
        assert sent == ["sage"] and "switching" not in p.lbl_state.text()
        assert p.voice_title() == "Sage" and p.status() == "starting"
        p._on_event({"type": "timeout"})
        assert starts == ["duke", "sage"] and p.status() == "starting" and not gave_up
        p._on_event({"type": "timeout"})
        assert gave_up and p.status() == "failed" and "⚠" in p.lbl_state.text()
        # one that gets ready in time: the timer stops, and a card says it switches
        p.b_start.setChecked(False)
        assert not p._load_timer.isActive()
        p.b_start.setChecked(True)
        p._on_event({"type": "ready"})
        assert not p._load_timer.isActive() and p.status() == "on"
        p.pick("bear")
        assert "switching" in p.lbl_state.text()
    finally:
        p.shutdown()
        p.deleteLater()


def test_ai_voice_and_the_computer_voice_take_turns(qapp, monkeypatch, app_dir):
    from soundboard.speech import tts
    from soundboard.ui.voice.voicepanel import VoicePanel
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])

    class Engine:
        voice_chain = None
        mic_stream = None
        level_mic = 0.0

    p = VoicePanel(Engine(), {}, {})
    try:
        started = []
        monkeypatch.setattr(p.ai, "stop", lambda: started.append("ai stopped"))
        p.speech.live_changed.emit(True)
        assert started == ["ai stopped"]
        assert voicefx.VoiceChain().source is None
    finally:
        p.shutdown()
        p.deleteLater()


def test_voice_settings_are_queued_with_the_audio_not_sent_from_the_ui_thread():
    import socket

    from soundboard.speech.service import ServiceHost
    c = AiVoiceController(VoiceChain(), lambda ev: None)
    h = ServiceHost(["unused"], lambda e: None)
    a, b = socket.socketpair()
    try:
        h._sock, h.connected = a, True
        c.host = h
        h._send_lock.acquire()                # the sender is stuck in a send
        h.feed(np.zeros(BLOCK, np.float32), RATE)
        t0 = time.monotonic()
        c.set_voice("nova", 2.0)
        c.set_auto_pitch(False)
        assert time.monotonic() - t0 < 0.1    # was 250 ms each, waiting on that lock
        queued = [h._q.get_nowait() for _ in range(h._q.qsize())]
        assert [x for x, rate in queued if rate < 0] == [
            {"type": "config", "voice": "nova", "pitch": 2.0},
            {"type": "config", "auto_pitch": False}]
        assert queued[0][1] == RATE           # in order, after the audio before them
    finally:
        h._send_lock.release()
        c.host = None
        h.stop()
        b.close()


def test_card_shows_robot_bunny_and_setup_stages_not_pip_output(qapp):
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel, install_step
    pip_msg = ("Successfully installed flatbuffers-25.12.19 numpy-2.5.3 "
               "onnxruntime-1.30.0 packaging-26.3 protobuf-7.36.2")
    assert install_step(pip_msg) is None            # pip's chatter: the stage stays up
    assert install_step("> -m venv C:/x/.venv") == "Getting Python ready…"
    assert "voice engine" in install_step("> -m pip install -r requirements.txt")
    assert install_step("> C:/x/helper.py --download") == "Downloading the voices…"
    assert install_step("Downloading the voice model: 42 %") == "Downloading the voices: 42%"

    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [])
    try:
        assert p.bun_robot.robot and not p.bun_robot.isHidden()
        assert p.loading_bar.isHidden()

        p._on_install_line("> -m pip install -r requirements.txt")
        p._on_install_line(pip_msg)
        assert "voice engine" in p.lbl_install.text()
        assert "flatbuffers" not in p.lbl_install.text()

        p.bun_robot.build()
        p.loading_bar.start()
        p._on_install_done(True)                     # done: he celebrates, the bar goes
        assert not p.bun_robot.building and p.bun_robot.celebrate
        assert not p.loading_bar.running()

        p.bun_robot.build()                          # failed: the real error shows
        p._on_install_line("failed (exit code 1)")
        p._on_install_done(False)
        assert not p.bun_robot.building and p.bun_robot.sad > 0.5
        from soundboard.ui.kit import toast
        assert "exit code 1" in toast.shown(p)[-1].text() and p.lbl_install.isHidden()
        p._on_install_done(False, "network unreachable")
        assert "network unreachable" in toast.shown(p)[-1].text()
    finally:
        p.shutdown()
        p.deleteLater()


def test_ai_voice_download_keeps_its_button_visible_and_focused(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from soundboard.online import net
    from soundboard.ui.voice import aivoicepanel
    from soundboard.ui.kit import busy
    monkeypatch.setattr(net, "offline", lambda: False)
    p = aivoicepanel.AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [])
    workers = []
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): workers.append(self.target)
    monkeypatch.setattr(aivoicepanel, "threading", type("Threads", (), {"Thread": Thread}))
    try:
        p.show()
        qapp.processEvents()
        p.b_get.setFocus()
        QTest.mouseClick(p.b_get, Qt.LeftButton)
        assert p.b_get.isVisible() and busy.is_busy(p.b_get) and p.focusWidget() is p.b_get
        QTest.mouseClick(p.b_get, Qt.LeftButton)
        assert len(workers) == 1
        p._on_install_done(False, "offline")
        assert not busy.is_busy(p.b_get) and p.focusWidget() is p.b_get
    finally:
        p.shutdown()
        p.deleteLater()


def test_ai_voice_install_keeps_focus(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from soundboard.online import net
    from soundboard.ui.voice import aivoicepanel
    from soundboard.ui.kit import busy
    monkeypatch.setattr(net, "offline", lambda: False)
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for name in ("module.json", "voices.json"):
        (folder / name).write_bytes((ADDON / name).read_bytes())
    (info,) = modules.discover([tmp_path])
    p = aivoicepanel.AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [info])
    workers = []
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): workers.append(self.target)
    monkeypatch.setattr(aivoicepanel, "threading", type("Threads", (), {"Thread": Thread}))
    try:
        p.show()
        qapp.processEvents()
        p.b_install.setFocus()
        QTest.mouseClick(p.b_install, Qt.LeftButton)
        assert p.b_install.isVisible() and busy.is_busy(p.b_install)
        assert p.focusWidget() is p.b_install
        QTest.mouseClick(p.b_install, Qt.LeftButton)
        assert len(workers) == 1
        p._on_install_done(False, "offline")
        assert not busy.is_busy(p.b_install) and p.focusWidget() is p.b_install
    finally:
        p.shutdown()
        p.deleteLater()


def test_a_load_that_ran_out_of_memory_says_so(addon_code):
    _conv, helper = addon_code
    assert helper._out_of_memory(MemoryError())
    assert helper._out_of_memory(RuntimeError("[ONNXRuntimeError] : 6 : bad allocation"))
    assert helper._out_of_memory(ImportError("DLL load failed: The paging file is too small"))
    assert not helper._out_of_memory(ImportError("No module named 'onnxruntime'"))


def test_downloaded_languages_voices_are_cards_on_ai_voices(qapp, tmp_path):
    """Each downloaded language's own voice is a card under Languages: clicking one
    speaks that language with it (the AI voice goes off); it's lit while it speaks."""
    from soundboard.ui.voice.aivoicepanel import LANGS, AiVoicePanel
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for f in ("module.json", "voices.json"):
        (folder / f).write_bytes((ADDON / f).read_bytes())
    (info,) = modules.discover([tmp_path])
    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [info])
    try:
        langs = [{"id": "piper:de", "name": "German", "language": "de", "about": "Thorsten"},
                 {"id": "piper:zh", "name": "Chinese", "language": "zh", "about": "Huayan"}]
        p.set_language_voices(langs, "")
        assert {"piper:de", "piper:zh"} <= set(p._tile)
        p.show_group("")   # All: under their own heading, last
        g = p._tile_grid

        def row(w):
            return g.getItemPosition(g.indexOf(w))[0]
        assert row(p._heads[LANGS]) > max(row(b) for i, b in p._tile.items()
                                          if not i.startswith("piper:"))
        assert row(p._tile["piper:zh"]) > row(p._heads[LANGS])
        picked = []
        p.language_picked.connect(picked.append)
        p._tile["piper:zh"].click()
        assert picked == ["zh"] and not p.is_on()
        p.set_language_voices(langs, "zh")                  # it speaks Chinese now: lit
        assert p._tile["piper:zh"].isChecked() and not p._tile["piper:de"].isChecked()
        p._tile["piper:zh"].click()                         # the lit one again: off
        assert picked == ["zh", ""]
        p.set_language_voices(langs[:1], "")                # Chinese deleted: its card goes
        assert "piper:zh" not in p._tile and "piper:de" in p._tile
    finally:
        p.shutdown()
        p.deleteLater()
