"""Share codes for saved voices (soundboard.savedvoices.share_code / read_code)."""
import base64
import json
import zlib

import pytest

from soundboard import savedvoices, voicefx
from soundboard.savedvoices import CodeError, read_code, share_code

VOICE = {"pitch": {"on": True, "semitones": 7.5, "mix": 1.0},
         "echo": {"on": True, "delay": 250.0, "mix": 0.3},
         "robot": {"on": False, "pitch": 3.0},            # off: not shared
         "cleanup": {"on": True}}                          # yours, not the voice's


def _code(data, prefix="OB1-") -> str:
    raw = json.dumps(data).encode("utf-8")
    return prefix + base64.urlsafe_b64encode(zlib.compress(raw)).rstrip(b"=").decode()


def _loaded(effects: dict) -> dict:
    """What a saved voice sounds like once picked: off effects and missing settings
    load as their defaults."""
    out = {}
    for t, cls in voicefx.REGISTRY.items():
        cfg = effects.get(t) or {}
        if t in savedvoices.NOT_SHARED or not cfg.get("on"):
            continue
        out[t] = {q.key: round(q.clamp(cfg.get(q.key, q.default)), 4) for q in cls.params}
    return out


def test_round_trip():
    code = share_code("Squeaky robot", VOICE)
    assert code.startswith("OB1-") and len(code) < 200
    assert set(code[4:]) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                                "0123456789-_")
    name, effects, notes = read_code(code)
    assert name == "Squeaky robot" and notes == []
    assert set(effects) == {"pitch", "echo"}
    assert _loaded(effects) == _loaded(VOICE)


def test_a_code_survives_being_pasted_with_spaces_and_line_breaks():
    code = share_code("A", VOICE)
    name, effects, _ = read_code(f"  {code[:10]}\n {code[10:]}  ")
    assert name == "A" and _loaded(effects) == _loaded(VOICE)


def test_every_built_in_voice_round_trips_short():
    for name, fx in voicefx.PRESETS.items():
        effects = {t: {"on": True, **cfg} for t, cfg in fx.items()}
        code = share_code(name, effects)
        assert len(code) < 400
        assert _loaded(read_code(code)[1]) == _loaded(effects)


def test_holds_only_the_name_and_numbers():
    data = json.loads(zlib.decompress(base64.urlsafe_b64decode(
        share_code("x", {**VOICE, "pitch": {**VOICE["pitch"], "path": "C:/secret"}})[4:]
        + "==")))
    assert set(data) == {"n", "e"}
    assert all(isinstance(v, (int, float)) for cfg in data["e"].values() for v in cfg.values())


@pytest.mark.parametrize("junk", [
    "", "   ", "hello", "OB1", "OB1-", "OB1-!!!!", "XX1-abcd", "OBx-abcd", "OB²-abcd",
    "OB1-" + "A" * 50,                                   # not zlib
    _code([1, 2, 3]), _code({"n": 5, "e": {}}), _code({"n": "x"}),
    _code({"n": "x", "e": []}), _code({"n": "x", "e": {"pitch": [1]}}),
    "OB1-" + base64.urlsafe_b64encode(zlib.compress(b"\xff\xfe")).decode(),   # not UTF-8
    "OB1-" + base64.urlsafe_b64encode(zlib.compress(b"[" * 5000)).decode(),   # nesting
])
def test_junk_is_rejected_with_a_reason(junk):
    with pytest.raises(CodeError) as e:
        read_code(junk)
    assert str(e.value)


def test_oversized_codes_are_rejected():
    with pytest.raises(CodeError, match="too long"):
        read_code("OB1-" + "A" * savedvoices.MAX_CODE)
    # small to paste, huge once unpacked (a zip bomb): stopped at MAX_JSON
    bomb = _code({"n": "x", "e": {}, "pad": " " * 200_000})
    assert len(bomb) < savedvoices.MAX_CODE
    with pytest.raises(CodeError, match="far too much"):
        read_code(bomb)


def test_tampered_codes_are_rejected():
    code = share_code("Squeaky", VOICE)
    for i in (6, len(code) // 2, len(code) - 2):
        bad = code[:i] + ("A" if code[i] != "A" else "B") + code[i + 1:]
        with pytest.raises(CodeError):
            read_code(bad)
    with pytest.raises(CodeError):
        read_code(code[:-6])                              # cut short


def test_a_newer_version_says_so():
    with pytest.raises(CodeError, match="newer version"):
        read_code(_code({"n": "x", "e": {}}, prefix="OB2-"))


def test_numbers_are_clamped_to_each_slider():
    pitch = {q.key: q for q in voicefx.REGISTRY["pitch"].params}
    name, effects, _ = read_code(_code({"n": "  Loud \n one ", "e": {"pitch": {
        "semitones": 1e9, "mix": -50, "tune": True, "nope": 3, "size": 10 ** 400,
        "on": False}}}))
    assert name == "Loud one"
    p = effects["pitch"]
    assert p["on"] is True                                # in the code = on
    assert p["semitones"] == pitch["semitones"].hi and p["mix"] == pitch["mix"].lo
    assert not {"tune", "nope", "size"} & set(p)   # bool, unknown key, too big: dropped
    assert all(pitch[k].lo <= v <= pitch[k].hi for k, v in p.items() if k != "on")


def test_unknown_effects_from_newer_versions_are_left_out_with_a_note():
    name, effects, notes = read_code(_code({"n": "Future", "e": {
        "pitch": {"semitones": 3}, "warp_drive": {"x": 1}, "cleanup": {}}}))
    assert set(effects) == {"pitch"} and len(notes) == 1 and "warp_drive" in notes[0]


def test_long_and_empty_names():
    assert read_code(_code({"n": "x" * 500, "e": {}}))[0] == "x" * savedvoices.MAX_NAME
    assert read_code(_code({"n": "   ", "e": {}}))[0] == "Shared voice"
