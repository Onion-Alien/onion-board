"""The simple sound modes (soundboard.profiles): which one a config is in, and which
destination mode each picks from what's seen."""
from soundboard import profiles
from soundboard.profiles import ADVANCED, CLEAN, GAME, VOICE, Hint


def test_old_configs_land_in_the_matching_simple_mode():
    assert profiles.current({}) is CLEAN
    assert profiles.current(None) is CLEAN
    assert profiles.current({"mode": "off"}) is CLEAN
    assert profiles.current({"mode": "discord"}) is VOICE
    assert profiles.current({"mode": "webrtc"}) is VOICE
    for k in ("game", "eos", "steam", "unity", "game_lo"):
        assert profiles.current({"mode": k}) is GAME
    custom = {"key": "custom1", "label": "Mumble"}
    assert profiles.current({"mode": "custom1", "custom": [custom]}) is ADVANCED
    # it switched between everything by itself: it still does, in Advanced
    assert profiles.current({"mode": "discord", "auto": True}) is ADVANCED


def test_a_simple_mode_an_older_version_changed_under_it_is_read_again():
    assert profiles.current({"simple": "voice", "mode": "discord"}) is VOICE
    # an older version picked Steam voice: "simple" is stale, "mode" wins
    assert profiles.current({"simple": "voice", "mode": "steam"}) is GAME
    assert profiles.current({"simple": "clean", "mode": "discord"}) is VOICE
    assert profiles.current({"simple": "advanced", "mode": "discord"}) is ADVANCED
    assert profiles.current({"simple": 5, "mode": "discord"}) is VOICE
    assert profiles.current({"simple": "nope", "mode": "off"}) is CLEAN


def test_game_picks_the_game_engine_and_keeps_the_last_one_when_blind():
    hints = [Hint("unity", "The game uses Photon", "game")]
    assert profiles.choose(GAME, hints, "game") == ("unity", "The game uses Photon")
    assert profiles.choose(GAME, [], "steam") == ("steam", "")      # nothing seen: keep it
    assert profiles.choose(GAME, [], "off") == ("game", "")         # not a game mode: Vivox
    # Discord listening is a Voice chat thing: Game ignores it
    assert profiles.choose(GAME, [Hint("discord", "Discord", "voice")], "game")[0] == "game"


def test_voice_chat_picks_the_listening_app():
    teamspeak = Hint("game", "TeamSpeak is listening", "voice")
    assert profiles.choose(VOICE, [teamspeak], "discord")[0] == "game"
    browser = Hint("webrtc", "Your browser is listening", "voice")
    assert profiles.choose(VOICE, [browser], "discord")[0] == "webrtc"
    front = Hint("game", "The game you have open uses Vivox", "game")
    assert profiles.choose(VOICE, [front], "discord")[0] == "discord"   # the game's own
    assert profiles.choose(VOICE, [], "off") == ("discord", "")


def test_clean_and_advanced_never_switch():
    hints = [Hint("unity", "x", "game"), Hint("discord", "y", "voice")]
    assert profiles.choose(CLEAN, hints, "off") == ("off", "")
    assert profiles.choose(ADVANCED, hints, "steam") == ("steam", "")
    assert not profiles.auto_picks(CLEAN) and not profiles.auto_picks(ADVANCED)
    assert profiles.auto_picks(GAME) and profiles.auto_picks(VOICE)


def test_another_mode_is_suggested_only_when_nothing_seen_suits_this_one():
    discord = Hint("discord", "Discord is listening", "voice")
    front = Hint("game", "The game uses Vivox", "game")
    assert profiles.better(GAME, [discord]) == discord
    assert profiles.better(GAME, [front, discord]) is None
    assert profiles.better(VOICE, [front, discord]) is None
    assert profiles.better(VOICE, [front]) == front
    assert profiles.better(CLEAN, [discord]) == discord
    assert profiles.better(ADVANCED, [discord]) is None
    assert profiles.better(GAME, []) is None


def test_pick_writes_both_keys_and_turns_off_advanced_switching():
    d = {"mode": "discord", "auto": True}
    why = profiles.pick(d, "game", [Hint("steam", "Steam game", "game")])
    assert d == {"mode": "steam", "auto": False, "simple": "game"} and why == "Steam game"
    profiles.pick(d, "clean")
    assert d["mode"] == "off" and d["simple"] == "clean"
    profiles.pick(d, "advanced")
    assert d["mode"] == "off" and d["simple"] == "advanced"


def test_every_mode_says_what_it_does():
    for p in profiles.PROFILES:
        assert p.label and p.summary and len(p.details) > 60
    assert profiles.explain({}) == "Clean: your sounds go out exactly as mixed."
    s = profiles.explain({"mode": "unity", "simple": "game"}, "The game uses Photon")
    assert s.startswith("Game: shaping for Unity voice") and "because the game uses" in s
    assert "nothing detected yet" in profiles.explain({"mode": "discord"})
    assert profiles.explain({"mode": "steam", "simple": "advanced"}) == (
        "Advanced: shaping for Steam voice.")
