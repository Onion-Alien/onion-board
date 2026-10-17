"""The voice changer's Background: built-in sounds behind your voice, made live or as
loops (voicefx.backdrop), board sounds, and its card with the Speed and pitch pop-up."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard import savedvoices, voicefx
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
def test_every_layer_at_the_top_is_about_a_voice_loud_and_finite(layer):
    e = voicefx.REGISTRY["backdrop"](SR, {layer: 1, "talk": 0})
    e.reseed(1)
    y = _run(e, np.zeros(SR * 3, np.float32))[SR:]
    assert np.all(np.isfinite(y))
    assert 0.5 < _rms(y) / e.LEVEL < 1.5
    assert np.max(np.abs(y)) < 1.0


def test_all_sliders_down_passes_the_voice_untouched():
    e = voicefx.REGISTRY["backdrop"](SR, {"talk": 0})
    x = _voice(0.2)[:480 * 20]
    assert np.array_equal(_run(e, x), x)


def test_only_while_i_talk_is_quiet_in_the_pauses_and_there_behind_words():
    e = voicefx.REGISTRY["backdrop"](SR, {"rain": 1, "talk": 1})
    e.reseed(2)
    quiet = _run(e, np.zeros(SR * 2, np.float32))
    assert _rms(quiet[SR:]) < 1e-6                 # an idle mic sends no rain
    x = _voice(1.0)
    y = _run(e, x)
    assert _rms(y[SR // 4:] - x[SR // 4:len(y)]) > 0.03   # rain under the words


def test_the_gate_lets_go_after_you_stop():
    e = voicefx.REGISTRY["backdrop"](SR, {"wind": 1, "talk": 1})
    e.reseed(3)
    x = np.concatenate([_voice(0.5), np.zeros(SR * 2, np.float32)])
    y = _run(e, x)
    assert _rms(y[int(SR * 1.5):]) < 1e-6          # gone well after the hold and fade


def test_moving_a_level_glides_without_a_jump():
    e = voicefx.REGISTRY["backdrop"](SR, {"engine": 0, "talk": 0})
    e.reseed(4)
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
    from soundboard import library
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    st = savedvoices.Store()
    effects = {"backdrop": {"on": True, "fire": 0.5,
                            "sounds": [{"id": "abc", "level": 0.3, "tweaks": {"pitch": 3}}]}}
    st.put("Camp", effects)
    again = savedvoices.Store()
    got = again.voices["Camp"]["backdrop"] if "Camp" in again.voices else None
    assert got is not None and got["sounds"][0]["id"] == "abc"
    assert got["sounds"][0]["tweaks"]["pitch"] == 3


def test_a_share_code_carries_the_levels_not_the_board_sounds():
    effects = {"backdrop": {"on": True, "rain": 0.5,
                            "sounds": [{"id": "abc", "level": 0.3}]}}
    _name, got, _notes = savedvoices.read_code(savedvoices.share_code("Wet", effects))
    assert got["backdrop"]["rain"] == 0.5 and "sounds" not in got["backdrop"]


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


def test_new_voices_with_a_background_run_in_the_chain():
    names = [n for n, fx in voicefx.PRESETS.items() if "backdrop" in fx]
    assert len(names) >= 6
    x = np.stack([_voice(0.6)] * 2, 1)
    for n in names:
        ch = voicefx.VoiceChain()
        fx = voicefx.PRESETS[n]
        ch.configure({"enabled": True, "effects": {t: {"on": True, **c} for t, c in fx.items()}})
        out = np.concatenate([ch.process(x[i:i + 480], SR) for i in range(0, len(x) - 479, 480)])
        assert np.all(np.isfinite(out)) and not ch.errors, n


# ------------------------------------------------------------------ the card

@pytest.fixture
def row(qapp):
    from soundboard.ui.backdroprow import BackdropRow
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
    from soundboard import library
    from soundboard.speech import tts
    from soundboard.ui.voicepanel import VoicePanel
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
