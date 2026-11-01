"""The voice changer's Background: built-in sounds behind your voice, made live or as
loops (voicefx.backdrop), board sounds, and its card with the Speed and pitch pop-up."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard.mic import savedvoices
from soundboard import voicefx
from soundboard.voicefx import backdrop
from tests.conftest import process_events

SR = 48000
LAYERS = backdrop.LAYERS


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))


def _run(e, x, block=480, rate=SR):
    return np.concatenate([e.run(x[i:i + block], rate)
                           for i in range(0, len(x) - block + 1, block)])


def _voice(secs, amp=0.1, rate=SR):
    t = np.arange(int(secs * rate)) / rate
    return (amp * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


@pytest.mark.parametrize("layer", LAYERS)
def test_every_recorded_layer_is_audible_and_has_peak_headroom(layer):
    e = voicefx.REGISTRY["backdrop"](SR, {layer: 1, "talk": 0})
    e.beds = backdrop.Beds({layer: backdrop.recording(layer)})
    y = _run(e, np.zeros(SR * 3, np.float32))[SR:]
    assert np.all(np.isfinite(y))
    assert 0.05 < _rms(y) / e.LEVEL < 1.5
    assert np.max(np.abs(y)) < 1.0


def test_all_sliders_down_passes_the_voice_untouched():
    e = voicefx.REGISTRY["backdrop"](SR, {"talk": 0})
    x = _voice(0.2)[:480 * 20]
    assert np.array_equal(_run(e, x), x)


def test_only_while_i_talk_is_quiet_in_the_pauses_and_there_behind_words():
    e = voicefx.REGISTRY["backdrop"](SR, {"rain": 1, "talk": 1})
    e.beds = backdrop.Beds({"rain": backdrop.recording("rain")})
    quiet = _run(e, np.zeros(SR * 2, np.float32))
    assert _rms(quiet[SR:]) < 1e-6                 # an idle mic sends no rain
    x = _voice(1.0)
    y = _run(e, x)
    assert _rms(y[SR // 4:] - x[SR // 4:len(y)]) > 0.001   # rain under the words


def test_the_gate_lets_go_after_you_stop():
    e = voicefx.REGISTRY["backdrop"](SR, {"wind": 1, "talk": 1})
    e.beds = backdrop.Beds({"wind": backdrop.recording("wind")})
    x = np.concatenate([_voice(0.5), np.zeros(SR * 2, np.float32)])
    y = _run(e, x)
    assert _rms(y[int(SR * 1.5):]) < 1e-6          # gone well after the hold and fade


def test_moving_a_level_glides_without_a_jump():
    e = voicefx.REGISTRY["backdrop"](SR, {"engine": 0, "talk": 0})
    e.beds = backdrop.Beds({"engine": backdrop.recording("engine")})
    a = e.run(np.zeros(480, np.float32), SR)
    e.set_values({"engine": 1, "talk": 0})
    b = e.run(np.zeros(480, np.float32), SR)
    assert np.all(a == 0)
    assert abs(float(b[0])) < 0.01 < np.max(np.abs(b))   # from silence, not a step


def test_loops_play_instead_of_the_live_layer_and_wrap():
    e = voicefx.REGISTRY["backdrop"](SR, {"rain": 1, "talk": 0})
    loop = np.full(1000, 0.5, np.float32)
    e.beds = backdrop.Beds({"rain": loop}, (("s1", np.full(700, -0.25, np.float32), 1.0),))
    y = _run(e, np.zeros(4800, np.float32))
    # after the glide in: the loop (0.5) and the board sound (-0.25), both at full level
    assert np.allclose(y[-480:], (0.5 - 0.25) * e.LEVEL, atol=1e-4)
    assert e.pos[("sound", "s1")] < 700 and e.pos["rain"] < 1000   # wrapped round


def test_a_sound_taken_out_stops_and_starts_from_silence_again():
    e = voicefx.REGISTRY["backdrop"](SR, {"talk": 0})
    bed = (("s1", np.full(500, 0.5, np.float32), 1.0),)
    e.beds = backdrop.Beds({}, bed)
    _run(e, np.zeros(2400, np.float32))
    e.beds = backdrop.Beds({}, ())
    y = _run(e, np.zeros(960, np.float32))
    assert np.all(y == 0) and ("sound", "s1") not in e.levels


def test_a_loop_at_another_rate_is_stepped_through():
    e = voicefx.REGISTRY["backdrop"](44100, {"rain": 1, "talk": 0})
    e.beds = backdrop.Beds({"rain": np.arange(4800, dtype=np.float32)}, ())
    e.run(np.zeros(441, np.float32), 44100)
    assert abs(e.pos["rain"] - 480) < 1e-6         # 10 ms of a 48 kHz loop


def test_saved_settings_keep_tweaks_and_sounds_and_drop_damage():
    raw = {"enabled": True, "effects": {"backdrop": {
        "on": True, "rain": 0.4, "junk": "x",
        "tweaks": {"rain": {"speed": 9, "pitch": "x"}, "wind": {}, "lava": {"speed": 1.5}},
        "sounds": [{"id": "a", "level": 3}, {"id": "a"}, {"id": 5}, "x",
                   {"id": "b", "level": float("nan"), "tweaks": {"bass": 4}},
                   {"id": "c"}, {"id": "d"}, {"id": "e"}]}}}
    cfg = voicefx.clean_spec(raw)["effects"]["backdrop"]
    assert cfg["rain"] == 0.4 and "junk" not in cfg
    assert cfg["tweaks"] == {"rain": {**backdrop.neutral_tweaks(), "speed": 2.0}}
    assert [d["id"] for d in cfg["sounds"]] == ["a", "b", "c", "d"]     # MAX_SOUNDS
    assert cfg["sounds"][0]["level"] == 1.0 and cfg["sounds"][1]["level"] == 0.5
    assert cfg["sounds"][1]["tweaks"]["bass"] == 4


def test_a_saved_voice_keeps_its_background(tmp_path, monkeypatch):
    from soundboard.sounds import library
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    st = savedvoices.Store()
    effects = {"backdrop": {"on": True, "fire": 0.5,
                            "sounds": [{"id": "abc", "level": 0.3, "tweaks": {"pitch": 3}}]}}
    st.put("Camp", effects)
    again = savedvoices.Store()
    got = again.voices["Camp"]["backdrop"] if "Camp" in again.voices else None
    assert got is not None and got["sounds"][0]["id"] == "abc"
    assert got["sounds"][0]["tweaks"]["pitch"] == 3


def test_a_share_code_carries_the_voice_not_whats_on_top_of_it():
    """The Background and the Effects extras are yours, on top of any voice: a code
    (or the store) carries only the voice."""
    effects = {"robot": {"on": True, "freq": 120},
               "backdrop": {"on": True, "rain": 0.5, "sounds": [{"id": "abc", "level": 0.3}]},
               "extra_echo": {"on": True, "mix": 0.5}}
    _name, got, _notes = savedvoices.read_code(savedvoices.share_code("Wet", effects))
    assert set(got) == {"robot"}


def test_a_loop_has_no_seam():
    t = np.arange(SR * 2) / SR
    x = np.sin(2 * np.pi * 3.3 * t).astype(np.float32)     # doesn't line up by itself
    y = backdrop.loopable(x, 0.5)
    jump = abs(float(y[0]) - float(y[-1]))
    step = float(np.max(np.abs(np.diff(y))))
    assert jump < 3 * step


def test_changed_built_in_sound_renders_a_loop_at_voice_level():
    loop = backdrop.render_layer("wind", {"speed": 1.5, "pitch": -3, "muffle": 0.5})
    assert loop.dtype == np.float32 and np.all(np.isfinite(loop))
    assert abs(len(loop) / SR - backdrop.LOOP_S) < 0.1
    assert 0.8 < _rms(loop) < 1.2


def test_a_board_sound_is_levelled_and_cut_to_a_loop():
    tone = (np.sin(np.arange(SR * 2) / SR * 2 * np.pi * 200) * 3000).astype(np.int16)
    loop = backdrop.render_sound(np.stack([tone, tone], 1), {"bass": 5})
    assert 0.8 < _rms(loop) < 1.2
    assert len(loop) < SR * 2
    silent = backdrop.render_sound(np.zeros((SR, 2), np.int16), None)
    assert np.all(silent == 0)


def test_maker_hands_over_only_the_newest_request():
    got, done = [], threading.Event()

    def ready(b):
        got.append(b)
        done.set()
    m = backdrop.Maker(ready)
    loads = []
    tone = np.zeros((SR // 2, 2), np.int16)
    tone[:, :] = 1000

    def load(sid):
        loads.append(sid)
        return tone if sid != "gone" else None
    m.update({"on": True, "sounds": [{"id": "x", "level": 0.2}]}, load)
    m.update({"on": True, "sounds": [{"id": "x", "level": 0.7}, {"id": "gone"}]}, load)
    assert done.wait(20)
    for _ in range(200):
        if not m._busy:
            break
        threading.Event().wait(0.05)
    last = got[-1]
    assert [(s, lv) for s, _l, lv in last.sounds] == [("x", 0.7)]   # "gone" left out
    assert loads.count("x") == 1                    # made once, kept for the level change


def test_maker_off_hands_over_nothing_to_play():
    got, done = [], threading.Event()
    m = backdrop.Maker(lambda b: (got.append(b), done.set()))
    m.update(None, lambda s: None)
    assert done.wait(10)
    assert got[-1].layers == {} and got[-1].sounds == ()


def test_no_voice_comes_with_a_background():
    """A background is something you add on top of any voice (Effects), never part
    of one: picking a voice leaves yours as it is."""
    assert not [n for n, fx in voicefx.PRESETS.items() if "backdrop" in fx]


# ------------------------------------------------------------------ the card

@pytest.fixture
def row(qapp):
    from soundboard.ui.voice.backdroprow import BackdropRow
    sounds = [("s1", "Lofi beat", ["Music"]), ("s2", "Rain loop", []), ("s3", "Airhorn", ["Memes"])]
    r = BackdropRow(voicefx.REGISTRY["backdrop"], {"on": True, "rain": 0.5}, lambda: sounds)
    yield r
    r.deleteLater()


def test_card_has_a_row_and_a_speed_button_per_built_in_sound(row):
    assert {s.q.key for s in row.sliders} == set(LAYERS) | {"talk"}
    assert set(LAYERS) <= set(row.tweak_buttons)
    assert row.state()["rain"] == 0.5 and row.state()["talk"] == 1


def test_adding_and_removing_a_board_sound(row):
    seen = []
    row.changed.connect(lambda: seen.append(row.state()))
    row._add("s1")
    row._add("s1")                                   # twice: once
    assert row.state()["sounds"] == [{"id": "s1", "level": 0.5}]
    assert "sound:s1" in row.tweak_buttons
    row._level("s1", 0.8)
    assert row.state()["sounds"][0]["level"] == 0.8
    row._remove("s1")
    assert "sounds" not in row.state() and "sound:s1" not in row.tweak_buttons
    assert seen


def test_the_add_button_hides_when_full(row):
    row.show()
    for i in range(backdrop.MAX_SOUNDS):
        row._add(f"x{i}")
    assert row.btn_add.isHidden()
    row._remove("x0")
    assert not row.btn_add.isHidden()


def test_the_pop_up_changes_one_sound_and_lights_its_button(row, qapp):
    row.show()
    row._open_pop("rain", "Rain", row.tweak_buttons["rain"])
    pop = row.pop
    assert pop.isVisible()
    pop.sliders["pitch"].set_value(-4)
    pop._moved()                                   # what a drag sends
    assert row.state()["tweaks"] == {"rain": {**backdrop.neutral_tweaks(), "pitch": -4.0}}
    assert row.tweak_buttons["rain"].isChecked()
    pop._place("Through a wall")
    t = row.state()["tweaks"]["rain"]
    assert t["pitch"] == -4 and t["muffle"] == backdrop.PLACES["Through a wall"]["muffle"]
    pop.btn_reset.click()
    assert "tweaks" not in row.state() and not row.tweak_buttons["rain"].isChecked()
    pop.hide()


def test_a_board_sound_gets_its_own_pop_up(row):
    row.show()
    row._add("s3")
    row._open_pop("sound:s3", "Airhorn", row.tweak_buttons["sound:s3"])
    row.pop.sliders["speed"].set_value(1.5)
    row.pop._moved()
    assert row.state()["sounds"][0]["tweaks"]["speed"] == 1.5
    row.pop.hide()


def test_load_puts_back_tweaks_and_sounds(row):
    row.load({"on": True, "wind": 0.3, "tweaks": {"wind": {"bass": 6}},
              "sounds": [{"id": "s2", "level": 0.4}, {"id": "missing", "level": 0.1}]})
    st = row.state()
    assert st["wind"] == 0.3 and st["tweaks"]["wind"]["bass"] == 6
    assert [d["id"] for d in st["sounds"]] == ["s2", "missing"]
    assert row.tweak_buttons["wind"].isChecked()
    row.reset()
    assert "sounds" not in row.state() and "tweaks" not in row.state()


def test_the_voice_panel_makes_loops_for_board_sounds(qapp, monkeypatch):
    from soundboard.sounds import library
    from soundboard.speech import tts
    from soundboard.ui.voice.voicepanel import VoicePanel
    from tests.test_voicepanel import FakeEngine
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    tone = np.full((SR, 2), 2000, np.int16)
    monkeypatch.setattr(library, "load_sound", lambda m: tone)
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "rate": 2})
    try:
        p.board_sounds = lambda: [SimpleNamespace(id="s1", name="Lofi beat", tags=[])]
        p.board_changed()
        p._fx_changed({"enabled": True, "effects": {"backdrop": {
            "on": True, "sounds": [{"id": "s1", "level": 0.6}]}}})
        process_events(qapp, lambda: p.chain.beds is not None and p.chain.beds.sounds,
                       timeout=20)
        assert [(s, lv) for s, _l, lv in p.chain.beds.sounds] == [("s1", 0.6)]
        assert p.fx.sound_list() == [("s1", "Lofi beat", [])]
    finally:
        p.shutdown()
        p.deleteLater()


def test_the_add_menu_lists_board_sounds_by_category_and_skips_picked_ones(row):
    row._add("s1")
    m = row.add_menu()
    subs = {a.text(): [b.text() for b in a.menu().actions()] for a in m.actions() if a.menu()}
    assert subs == {"Memes": ["Airhorn"], "Not in a category": ["Rain loop"]}
    m.deleteLater()


def test_board_sound_rows_line_up_with_the_built_in_ones(row, qapp):
    row.resize(520, 600)
    row.show()
    row._add("s1")
    process_events(qapp, lambda: False, timeout=0.2)
    rain = row.sliders[0]
    mine = row._mine_rows[0].findChildren(type(rain))[0]
    assert abs(rain.val.mapTo(row, rain.val.rect().topLeft()).x()
               - mine.val.mapTo(row, mine.val.rect().topLeft()).x()) <= 1


def _voice_panel(monkeypatch):
    from soundboard.speech import tts
    from soundboard.ui.voice.voicepanel import VoicePanel
    from tests.test_voicepanel import FakeEngine
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    return VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                      {"voice": "Microsoft Zira Desktop", "rate": 2})


def test_effects_sit_on_top_of_the_voice_and_stay_when_you_pick_another(qapp, monkeypatch):
    p = _voice_panel(monkeypatch)
    try:
        fx = p.fx
        fx.pick("Robot")
        assert fx.btn_effects.accessibleName() == "Effects"
        tweak = fx.btn_tweak.accessibleName()
        fx.set_on_top("rain", 0.6)
        fx.set_on_top("extra_echo", 0.4)
        assert fx.btn_effects.accessibleName() == "Effects  ·  2"
        assert fx.preset == "Robot"                       # still the voice you picked
        assert fx.btn_tweak.accessibleName() == tweak     # (not counted as the voice's)
        fx.pick("Deep voice")                             # another voice: they stay
        spec = fx.spec()
        assert fx.preset == "Deep voice"
        assert spec["effects"]["backdrop"]["on"] and spec["effects"]["backdrop"]["rain"] == 0.6
        assert spec["effects"]["extra_echo"] == {**voicefx.defaults("extra_echo"),
                                                 "on": True, "mix": 0.4}
        assert "robot" not in fx.effects_of("Deep voice")
        # never part of a voice: not in what a sound takes, a setup or a share code
        assert not {"backdrop", "extra_echo"} & set(fx.effects_of("Deep voice"))
        assert not {"backdrop", "extra_echo"} & set(p.current_setup()["effects"])
        assert not {"backdrop", "extra_echo"} & set(savedvoices.shared_effects(spec["effects"]))
        fx.set_on_top("rain", None)
        fx.set_on_top("extra_echo", None)
        assert fx.btn_effects.accessibleName() == "Effects"
        assert not fx.spec()["effects"]["backdrop"]["on"]   # nothing left to play: off
        assert "extra_echo" not in fx.spec()["effects"]
    finally:
        p.shutdown()
        p.deleteLater()


def test_the_effects_pop_up_adds_changes_and_takes_off(qapp, monkeypatch):
    from PySide6.QtCore import QPoint
    p = _voice_panel(monkeypatch)
    try:
        fx = p.fx
        fx.pick("Robot")
        fx.btn_effects.click()
        pop = fx.effects_pop
        process_events(qapp, lambda: pop.isVisible(), timeout=5)
        assert not pop.sliders and pop.hint.isVisibleTo(pop)   # nothing on yet
        assert {"rain", "wind", "crowd", "fire", "extra_echo", "extra_robot",
                "sound"} <= set(pop.adds)
        b = fx.btn_effects
        top = b.mapToGlobal(QPoint(0, 0)).y()

        def beside():   # just above the button, or just under it (no room above)
            g = pop.geometry()
            return top - 12 < g.bottom() < top or top + b.height() < g.top() < top + b.height() + 12

        assert beside()
        pop.adds["wind"].click()
        pop.adds["extra_reverb"].click()
        assert set(pop.sliders) == {"wind", "extra_reverb"}
        assert beside()   # taller now, and still beside it (it hung over the bar)
        assert "wind" not in pop.adds                     # on: not offered again
        assert fx.on_top_state()["layers"] == {"wind": 0.5}
        sl = pop.sliders["wind"].slider
        sl.setValue(sl.maximum())                         # as a drag does
        assert fx.on_top_state()["layers"] == {"wind": 1.0}
        pop.removes["extra_reverb"].click()
        assert set(pop.sliders) == {"wind"} and "extra_reverb" in pop.adds
        assert fx.btn_effects.accessibleName() == "Effects  ·  1"
        pop.btn_advanced.click()                          # the full editor
        process_events(qapp, lambda: fx.dlg.isVisible(), timeout=5)
        assert not pop.isVisible()
        fx.dlg.close()
    finally:
        p.shutdown()
        p.deleteLater()


def test_a_background_sound_can_be_heard_before_adding_it(qapp, monkeypatch):
    """There was no way to hear Rain or Wind before keeping it: the ▶ dot inside its
    chip plays a few seconds in your own headphones (again: stops)."""
    from types import SimpleNamespace
    from soundboard.ui.voice import effectspopup
    p = _voice_panel(monkeypatch)
    try:
        fx = p.fx
        fx.btn_effects.click()
        pop = fx.effects_pop
        process_events(qapp, lambda: pop.isVisible(), timeout=5)
        played, stopped = [], []
        eng = SimpleNamespace(
            play=lambda sid, data, gain, **kw: played.append((sid, len(data), kw)),
            stop=stopped.append, playing=lambda: {s: 0 for s, *_r in played[-1:]})
        monkeypatch.setattr(pop.panel, "window", lambda: SimpleNamespace(engine=eng))
        dot = pop.listens["rain"]
        assert dot.parent() is pop.adds["rain"]          # inside its chip: one pill
        dot.click()
        process_events(qapp, lambda: bool(played), timeout=10)
        sid, n, kw = played[-1]
        assert sid == effectspopup.LISTEN_SID and sid.endswith(":preview") and kw["preview"]
        assert n == int(effectspopup.LISTEN_S * 48000)
        assert dot.property("playing") and "rain" not in fx.on_top_state()["layers"]
        dot.click()                                       # again: stops
        assert stopped[-1] == effectspopup.LISTEN_SID and not dot.property("playing")
    finally:
        p.shutdown()
        p.deleteLater()


def test_effects_come_back_after_a_restart(qapp):
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    fx = VoiceFxPanel({"enabled": True, "preset": "Robot",
                       "effects": {"extra_radio": {"on": True, "drive": 12},
                                   "backdrop": {"on": True, "crowd": 0.3}}})
    try:
        assert fx.on_top_state() == {"layers": {"crowd": 0.3}, "sounds": [],
                                     "extras": {"extra_radio": 12}}
        assert fx.spec()["effects"]["extra_radio"]["drive"] == 12
        assert fx.btn_effects.accessibleName() == "Effects  ·  2"
    finally:
        fx.deleteLater()


def test_the_extras_run_on_the_mic_after_the_voice():
    chain = voicefx.VoiceChain()
    chain.configure({"enabled": True, "effects": {"robot": {"on": True},
                                                  "extra_echo": {"on": True}}})
    chain._rebuild(48000)
    types = [e.type for e in chain._effects]
    assert types.index("robot") < types.index("extra_echo")
    assert "extra_echo" not in {c.type for c in voicefx.REGISTRY.values() if not c.extra}


class _PassSource:
    """The AI voice in the chain, as a stand-in: hands your voice back as it is."""
    def process(self, mono, rate):
        return mono.copy()

    def latency(self):
        return 0.0


def _through(chain, x, block=480):
    """Mono `x` through the chain's mic path, block by block: the mono out."""
    st = np.stack([x, x], axis=1)
    return np.concatenate([chain.process(st[i:i + block], SR)[:, 0]
                           for i in range(0, len(x) - block + 1, block)])


def test_the_effects_play_on_the_ai_voice_with_the_voice_changer_off():
    """Only an AI voice on: Rain and Echo from the Effects pop-up are heard on it, the
    voice changer's own voice (Robot) isn't, and with both on they run once."""
    x = _voice(1.5)
    effects = {"robot": {"on": True}, "extra_echo": {"on": True, "mix": 0.6},
               "backdrop": {"on": True, "rain": 1.0}}

    def chain(enabled, effects, src=True):
        c = voicefx.VoiceChain()
        c.set_beds(backdrop.Beds({"rain": backdrop.recording("rain")}))
        c.configure({"enabled": enabled, "effects": effects})
        c.source = _PassSource() if src else None
        return c

    ai_only = _through(chain(False, effects), x)
    assert _rms(ai_only - x[:len(ai_only)]) > 0.005          # rain and echo are heard
    on_top = {t: v for t, v in effects.items() if t != "robot"}
    want = _through(chain(True, on_top), x)                # just those two, once each
    assert np.allclose(ai_only, want, atol=1e-6)            # (no Robot on the AI voice)
    both = _through(chain(True, effects), x)                 # the voice changer on too
    assert np.allclose(both, _through(chain(True, effects), x), atol=1e-6)
    assert not np.allclose(both, want, atol=1e-3)             # its Robot as well
    off = _through(chain(False, effects, src=False), x)     # nothing on: your voice
    assert np.array_equal(off, x[:len(off)])


def test_the_ai_voice_bar_has_the_same_effects_button(qapp, monkeypatch):
    """The AI voice's bar opens the same Effects pop-up, both say the same count, and
    the Background's loops are made for the AI voice with the voice changer off."""
    p = _voice_panel(monkeypatch)
    try:
        fx, ai = p.fx, p.ai
        assert ai.btn_effects.text() == "Effects"
        fx.set_on_top("rain", 0.6)
        fx.set_on_top("extra_echo", 0.4)
        assert not fx.btn_power.isChecked()                  # the voice changer stays off
        assert fx.btn_effects.accessibleName() == "Effects  ·  2"
        assert ai.btn_effects.accessibleName() == fx.btn_effects.accessibleName()
        ai.btn_effects.click()
        pop = fx.effects_pop
        process_events(qapp, lambda: pop.isVisible(), timeout=5)
        assert pop._under is ai.btn_effects                   # over the AI bar's button
        pop.removes["extra_echo"].click()
        assert ai.btn_effects.text() == "Effects  ·  1"
        pop.close()
        made = []
        monkeypatch.setattr(p.backdrop, "update", lambda cfg, load: made.append(cfg))
        p._update_backdrop(fx.spec())
        assert made[-1] is None                               # nothing is on: no loops
        monkeypatch.setattr(ai, "is_on", lambda: True)
        p._ai_live(True)
        assert made[-1] and made[-1]["rain"] == 0.6           # the AI voice gets them
    finally:
        p.shutdown()
        p.deleteLater()


def _picked_bar(qapp):
    from PySide6.QtWidgets import QLayout
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    fx = VoiceFxPanel({"enabled": False, "effects": {}})
    fx.pick("Robot")
    fx.set_on_top("rain", 0.6)
    fx.set_on_top("wind", 0.5)
    bar = fx.picked
    fx.layout().removeWidget(bar)
    bar.setParent(None)
    # squeezable, as it is when laid out in the Voice tab
    fx.picked_box.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    bar.show()
    return fx, bar


def test_the_voice_bar_puts_its_buttons_under_the_name_when_narrow(qapp):
    """The Voice tab pins the bar outside the panel, where a narrow window squeezes
    it: its buttons go under the voice's name instead of losing their words."""
    from PySide6.QtWidgets import QBoxLayout
    fx, bar = _picked_bar(qapp)
    try:
        for width, want in ((1100, QBoxLayout.Direction.LeftToRight),
                            (300, QBoxLayout.Direction.TopToBottom),
                            (1100, QBoxLayout.Direction.LeftToRight)):
            bar.resize(width, bar.height())
            process_events(qapp, lambda: False, timeout=0.1)
            assert fx.picked_box.direction() == want, width
        bar.resize(300, 200)
        process_events(qapp, lambda: False, timeout=0.1)
        for b in (fx.btn_tweak, fx.btn_effects):
            assert b.width() >= b.minimumSizeHint().width() - 1   # nothing squeezed
    finally:
        bar.close()
        bar.deleteLater()
        fx.deleteLater()


def test_the_voice_bar_buttons_sit_beside_the_name_on_a_wide_bar(qapp):
    """A wide window leaves the buttons right after the voice's name, not mid-bar."""
    fx, bar = _picked_bar(qapp)
    try:
        bar.resize(2000, 200)
        process_events(qapp, lambda: False, timeout=0.1)
        first = min((b for b in (fx.btn_effects, fx.btn_tweak) if not b.isHidden()),
                    key=lambda b: b.mapTo(bar, b.rect().topLeft()).x())
        name_end = fx.picked_name.mapTo(bar, fx.picked_name.rect().topRight()).x()
        assert first.mapTo(bar, first.rect().topLeft()).x() - name_end <= 40
    finally:
        bar.close()
        bar.deleteLater()
        fx.deleteLater()


def test_effects_keeps_its_words_while_they_fit_and_its_name_always(qapp):
    fx, bar = _picked_bar(qapp)
    try:
        on = fx._count_on()
        full = f"Edit voice  ·  {on} on"
        bar.resize(2000, 200)
        process_events(qapp, lambda: False, timeout=0.1)
        m = fx.picked_box.contentsMargins()
        # the folded line with every word: the three buttons side by side (font-free)
        folded = (sum(b.minimumSizeHint().width() for b in
                      (fx.btn_tweak, fx.btn_effects, fx.btn_sample) if not b.isHidden())
                  + 2 * fx._picked_pb.spacing() + m.left() + m.right() + 4)
        for width, words, tweak in ((2000, True, full), (folded, True, full),
                                    (folded - 30, False, full), (120, False, "Edit voice"),
                                    (2000, True, full)):
            bar.resize(width, 200)
            process_events(qapp, lambda: False, timeout=0.1)
            assert bool(fx.btn_effects.text()) == words, width
            assert fx.btn_tweak.text() == tweak, width
            assert fx.btn_effects.accessibleName() == "Effects  ·  2"
            assert fx.btn_tweak.accessibleName() == full
    finally:
        bar.close()
        bar.deleteLater()
        fx.deleteLater()


@pytest.mark.parametrize("layer", LAYERS)
def test_background_preview_and_live_audio_use_the_bundled_recording(layer):
    raw = backdrop.recording(layer)
    assert not raw.flags.writeable
    preview = backdrop.generate(layer, 1)
    assert np.array_equal(preview, raw[:SR])
    e = voicefx.REGISTRY["backdrop"](SR, {layer: 1, "talk": 0})
    e.beds = backdrop.Beds({layer: raw})
    e.levels[layer] = 1
    actual = e.run(np.zeros(SR, np.float32), SR)
    assert np.allclose(actual, preview * e.LEVEL)


@pytest.mark.parametrize("layer", LAYERS)
def test_recorded_background_wraps_identically_with_different_callback_sizes(layer):
    raw = backdrop.recording(layer)
    def render(block):
        e = voicefx.REGISTRY["backdrop"](SR, {layer: 1, "talk": 0})
        e.beds = backdrop.Beds({layer: raw})
        e.levels[layer] = 1
        return np.concatenate([e.run(np.zeros(min(block, len(raw) + 500 - i), np.float32), SR)
                               for i in range(0, len(raw) + 500, block)])
    assert np.allclose(render(240), render(2048), atol=1e-6)


def test_idle_talk_gate_starts_closed():
    e = voicefx.REGISTRY["backdrop"](SR, {"rain": 1, "talk": 1})
    assert np.all(_run(e, np.zeros(SR, np.float32)) == 0)


def test_typed_speech_uses_the_same_background_loops_as_the_mic():
    chain = voicefx.VoiceChain()
    chain.configure({"enabled": True, "effects": {
        "backdrop": {"on": True, "rain": 1, "talk": 0}}})
    chain.set_beds(backdrop.Beds({"rain": np.full(1000, 0.25, np.float32)},
                                (("board", np.full(700, 0.5, np.float32), 1.0),)))
    out = chain.render(np.zeros(4800, np.float32), SR, 480)
    assert np.allclose(out[-480:], 0.75 * voicefx.REGISTRY["backdrop"].LEVEL)



def test_neutral_background_is_loaded_by_maker_off_the_caller_thread(monkeypatch):
    caller = threading.get_ident()
    seen, done, got = [], threading.Event(), []
    original = backdrop.render_layer
    def render(layer, tweaks):
        seen.append(threading.get_ident())
        return original(layer, tweaks)
    monkeypatch.setattr(backdrop, "render_layer", render)
    m = backdrop.Maker(lambda beds: (got.append(beds), done.set()))
    try:
        m.update({"on": True, "rain": 0.5, "window": 0.4}, lambda sid: None)
        assert done.wait(10)
        assert set(got[-1].layers) == {"rain", "window"}
        assert seen and all(t != caller for t in seen)
    finally:
        m.close()


def test_missing_background_stays_silent_without_callback_file_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("file access on the audio callback")
    monkeypatch.setattr(backdrop, "recording", forbidden)
    e = voicefx.REGISTRY["backdrop"](SR, {"rain": 1, "talk": 0})
    x = _voice(0.1)
    assert np.array_equal(e.run(x, SR), x)
    e.beds = backdrop.Beds({"rain": np.ones(1000, np.float32)})
    out = e.run(x, SR)
    assert out[0] - x[0] < 0.001 and out[-1] > x[-1]


def test_every_background_has_a_verified_cc0_credit_and_build_data():
    import hashlib
    import json
    from pathlib import Path
    credits = json.loads((backdrop.AUDIO_DIR / "credits.json").read_text("utf-8"))
    assert {Path(c["file"]).stem for c in credits} == set(LAYERS)
    for credit in credits:
        assert credit["license"] == "CC0-1.0"
        assert credit["source"].startswith("https://freesound.org/people/")
        content = (backdrop.AUDIO_DIR / credit["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == credit["sha256"]
    root = Path(__file__).resolve().parents[1]
    assert 'assets\\backgrounds;backgrounds' in (root / "build.ps1").read_text("utf-8")
    # every recording in the folder is a credited one (no FLAC left behind in the build)
    audio = {p.name for p in backdrop.AUDIO_DIR.iterdir() if p.suffix not in (".json", ".md")}
    assert audio == {c["file"] for c in credits}


def test_every_bundled_loop_decodes_and_still_loops_without_a_click():
    """The loops are Ogg Vorbis made from FLAC loops with the seam baked in: a lossy
    encoder's start or end that drifted would click at every turn."""
    backdrop.recording.cache_clear()
    for layer in LAYERS:
        x = backdrop.recording(layer)
        assert x.ndim == 1 and len(x) >= 16 * backdrop.SR and np.isfinite(x).all()
        step = float(np.percentile(np.abs(np.diff(x)), 99))
        assert abs(float(x[0] - x[-1])) < step, layer   # the seam: no bigger than a usual step



def test_closing_or_stopping_a_pending_background_preview_discards_it(qapp, monkeypatch):
    p = _voice_panel(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def generate(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return np.ones(SR, np.float32)
    monkeypatch.setattr(backdrop, "generate", generate)
    played = []
    eng = SimpleNamespace(play=lambda *a, **kw: played.append(a), stop=lambda sid: None)
    try:
        p.fx.btn_effects.click()
        pop = p.fx.effects_pop
        process_events(qapp, pop.isVisible, timeout=5)
        monkeypatch.setattr(pop.panel, "window", lambda: SimpleNamespace(engine=eng))
        delivered = threading.Event()
        pop.preview_ready.connect(lambda *args: delivered.set())
        pop._listen("rain")
        assert entered.wait(5)
        pop._listen("rain")  # cancel before loading finished
        assert pop._listening is None
        pop.hide()
        release.set()
        process_events(qapp, delivered.is_set, timeout=5)
        assert delivered.is_set() and not played
    finally:
        release.set()
        p.shutdown()
        p.deleteLater()


@pytest.mark.parametrize("layer", LAYERS)
def test_background_tweaks_keep_peak_headroom(layer):
    loop = backdrop.render_layer(layer, {"bass": 8})
    assert np.isfinite(loop).all() and np.max(np.abs(loop)) <= 8.0001
