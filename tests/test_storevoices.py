"""Community voices: what comes from the store is checked again here, what's shared is
only numbers and short text, and a voice taken in lands in your own lists."""
import json
import random

import numpy as np
import pytest

from soundboard.mic import savedvoices, voicesetups
from soundboard import voicefx
from soundboard.online import store, storevoices as sv
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl

ID = "0123456789ab"


def raw(kind="fx", **kw):
    data = {"fx": {"e": {"pitch": {"semitones": 7}}},
            "ai": {"mix": [[171, 0.5], [60, 0.5]], "formant": -1, "pitch_hz": 90},
            "setup": {"e": {"pitch": {"semitones": 7}}, "fx": "Chipmunk",
                      "ai": {"id": "bear", "name": "Bear", "pitch": 2}, "lang": "it"}}.get(kind, {})
    return {"id": ID, "kind": kind, "name": "Squeaky", "about": "Hi", "emoji": "🤖",
            "tags": ["fun"], "data": data, "up": 3, "down": 1, "created": 1, **kw}


def test_plain_text_is_one_safe_line():
    nasty = "\u202eevil\u200b\x00na\nme\t<b>x</b> Z" + "\u0301" * 50 + "\ue000"
    t = sv.plain(nasty, 32)
    assert "\u202e" not in t and "\u200b" not in t and "\x00" not in t and "\n" not in t
    assert "\ue000" not in t and "\u0301\u0301\u0301" not in t
    assert len(t) <= 32 and "b x /b" in t and not set("<>`{}\\") & set(t)   # as sound names
    assert sv.plain("\u200b \u202e", 10) == ""
    assert sv.one_emoji("🤖") == "🤖" and sv.one_emoji("🐿️") == "🐿️"
    assert sv.one_emoji("👨‍👩‍👧") == "" and sv.one_emoji("ab") == ""
    assert sv.one_emoji("\u202e") == ""


def test_a_voice_from_the_store_is_checked_again():
    v = sv.voice_from(raw())
    assert v is not None and v.kind == "fx" and v.name == "Squeaky" and v.score == 2
    assert v.effects == {"pitch": {"on": True, "semitones": 7.0}}
    # numbers outside a slider are pulled in; effects this version lacks are named
    v = sv.voice_from(raw(data={"e": {"pitch": {"semitones": 1e9}, "warp9": {"x": 1}}}))
    assert v.effects["pitch"]["semitones"] == voicefx.REGISTRY["pitch"].params[0].clamp(1e9)
    assert v.unknown == ["warp9"]
    a = sv.voice_from(raw("ai", data={"mix": [[171, 9]], "formant": -9, "pitch_hz": 1e9}))
    assert a.ai == {"mix": [[171, 1.0]], "formant": avl.FORMANT[0], "pitch_hz": avl.PITCH_HZ[1]}
    s = sv.voice_from(raw("setup"))
    assert s.fx == "Chipmunk" and s.ai == {"id": "bear", "name": "Bear", "pitch": 2.0}
    assert s.language == "it"


@pytest.mark.parametrize("bad", [
    {"id": "../../x"}, {"id": "0123456789AB"}, {"kind": "exe"}, {"name": "\u200b"},
    {"data": "rm -rf"}, {"data": {"e": {}}}, {"data": {"e": {"pitch": 5}}},
    {"data": {"e": [1]}}, {"kind": "ai", "data": {"mix": []}},
    {"kind": "ai", "data": {"mix": [[1, 1]] * 5, "pitch_hz": 100}},
    {"kind": "setup", "data": {"ai": {"id": "C:\\x"}, "lang": "../../"}},
    {"kind": "setup", "data": {"ai": {"id": "my-someone"}}},   # an AI voice only its maker has
])
def test_a_voice_that_cant_be_one_is_left_out(bad):
    assert sv.voice_from(raw(**bad)) is None


def test_junk_from_the_store_never_raises_and_never_gets_through_unchecked():
    rnd = random.Random(5)
    atoms = [None, True, 0, -1, 1e308, float("nan"), float("inf"), "", "x", "\u202e", [], {},
             [[171, 1]], "🤖", "pitch", "semitones", "e", "mix", "a" * 5000, ID]

    def junk(d=0):
        r = rnd.random()
        if d > 3 or r < 0.3:
            return rnd.choice(atoms)
        if r < 0.6:
            return [junk(d + 1) for _ in range(rnd.randrange(4))]
        return {str(rnd.choice(atoms))[:20]: junk(d + 1) for _ in range(rnd.randrange(4))}

    kept = 0
    for i in range(3000):
        d = {"id": ID, "kind": sv.KINDS[i % 3], "name": junk(2), "about": junk(2),
             "emoji": junk(3), "tags": junk(2), "data": junk(), "up": junk(3), "mine": junk(3)}
        v = sv.voice_from(json.loads(json.dumps(d, allow_nan=True)))
        if v is None:
            continue
        kept += 1
        assert v.name and len(v.name) <= sv.MAX_NAME and v.name == sv.plain(v.name, 99)
        for cfg in v.effects.values():
            assert all(isinstance(x, (bool, float)) and np.isfinite(x) for x in cfg.values())
    lists, more = sv.parse({"voices": [raw(), "x", None, raw(id="nope")], "more": 1})
    assert [v.id for v in lists] == [ID] and more is True
    assert sv.parse("garbage") == ([], False)


def test_what_you_share_is_only_settings_and_comes_back_the_same():
    effects = {"pitch": {"on": True, "semitones": 5.0}, "cleanup": {"on": True, "gate": 0.9},
               "growl": {"on": False, "amount": 0.9}}
    p = sv.pack_fx("  My   voice ", effects, about="so\nfunny")
    assert p == {"kind": "fx", "name": "My voice", "about": "so funny", "emoji": "",
                 "data": {"e": {"pitch": {"semitones": 5.0}}}}   # mic clean-up stays yours
    back = sv.voice_from({"id": ID, **p})
    assert back.effects == {"pitch": {"on": True, "semitones": 5.0}}
    mine = {"id": "my-abc", "name": "Gravel", "emoji": "🪨", "about": "deep",
            "mix": [[171, 1.0]], "formant": -1.0, "pitch_hz": 90, "recipe": {"base": "bear"}}
    a = sv.pack_ai(mine)
    assert a["data"] == {"mix": [[171, 1.0]], "formant": -1.0, "pitch_hz": 90}
    assert "my-abc" not in json.dumps(a) and "recipe" not in json.dumps(a)
    setup = {"name": "x", "fx": "Robot", "effects": {"robot": {"on": True}},
             "ai": {"id": "my-abc", "name": "Gravel", "pitch": 1.0}, "language": "pt-BR"}
    s = sv.pack_setup("Combo", setup, mine)
    assert s["data"]["ai"] == {"id": "my-abc", "name": "Gravel", "pitch": 1.0,
                               "mix": [[171, 1.0]], "formant": -1.0, "pitch_hz": 90}
    assert s["data"]["lang"] == "pt-BR" and sv.can_share(s)
    # your own AI voice that's gone: the setup goes without it
    assert "ai" not in sv.pack_setup("Combo", setup, None)["data"]
    assert not sv.can_share(sv.pack_fx("x", {"pitch": {"on": False}}))


def test_taking_a_voice_puts_it_in_your_own_lists(app_dir):
    saved, ai, setups = savedvoices.Store(), avl.Store(), voicesetups.Store()
    fx = sv.voice_from(raw())
    assert sv.take_fx(fx, saved) == "Squeaky"
    assert sv.take_fx(fx, saved) == "Squeaky (2)"                 # never over one of yours
    chip = sv.voice_from(raw(name="Chipmunk"))
    assert sv.take_fx(chip, saved) == "Chipmunk (shared)"        # not a built-in's name
    got = sv.take_ai(sv.voice_from(raw("ai")), ai)
    assert got and avl.is_mine(got) and got["mix"] == [[171, 0.5], [60, 0.5]]
    s = sv.voice_from(raw("setup"))
    assert sv.take_setup(s, setups, ai) == "Squeaky"
    got = setups.setups["Squeaky"]
    assert got["ai"]["id"] == "bear" and got["language"] == "it"
    own = sv.voice_from(raw("setup", name="Own", data={"ai": {
        "id": "my-zzz", "name": "Gravel", "pitch": 0, "mix": [[5, 1]], "pitch_hz": 120}}))
    assert sv.take_setup(own, setups, ai) == "Own"
    new_id = setups.setups["Own"]["ai"]["id"]
    assert new_id != "my-zzz" and ai.get(new_id)["mix"] == [[5, 1.0]]   # yours now
    assert sv.take_setup(s, setups, ai) == "Squeaky (2)"
    # all of it is still there after a restart
    assert "Squeaky (2)" in voicesetups.Store().setups and avl.Store().get(new_id)


def test_hear_it_runs_the_line_through_the_voice(monkeypatch):
    t = np.arange(16000) / 16000
    monkeypatch.setattr(aipreview, "sample",
                        lambda: (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
    v = sv.voice_from(raw())
    y, left_out = sv.preview(v)
    assert y.ndim == 2 and y.shape[1] == 2 and y.dtype == np.float32 and not left_out
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) <= 0.8 + 1e-6 and np.max(np.abs(y)) > 0.01
    # a setup with an AI voice and no add-on: its effects, and it says the AI part is left out
    y2, left_out = sv.preview(sv.voice_from(raw("setup")))
    assert left_out and len(y2)


def test_store_errors_say_voice_not_sound(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 409, "x", {}, None)
    monkeypatch.setattr(store.net, "urlopen", boom)
    with pytest.raises(store.StoreError, match="voice is already"):
        sv.share("0" * 20, sv.pack_fx("x", {"pitch": {"on": True, "semitones": 3}}))
