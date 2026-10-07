"""Reading Discord's own voice settings (soundboard.discordcfg) from a fake LevelDB
folder, and what counts as a problem on the mic vs the virtual cable."""
import json

from soundboard import discordcfg as dc

DEFAULTS = {"mode": "VOICE_ACTIVITY", "echoCancellation": True, "noiseSuppression": False,
            "automaticGainControl": True, "noiseCancellation": True,
            "bypassSystemInputProcessing": False, "activeInputProfile": "VOICE_ISOLATION",
            "inputDeviceId": "default"}


def store(**over) -> bytes:
    d = dict(DEFAULTS, **over)
    return (b"\x01_https://discord.com\x00\x01MediaEngineStore\xcd*\x01"
            + json.dumps({"default": d, "stream": {}}).encode())


def folder(client="discord"):
    f = dc._appdata() / client / "Local Storage" / "leveldb"
    f.mkdir(parents=True, exist_ok=True)
    return f


def test_nothing_installed_reads_nothing():
    assert dc.read() == []
    assert dc.signature() == ()


def test_the_newest_write_wins():
    """Discord appends to the .log; the last store in it is the current one, and the
    .log is newer than any table."""
    f = folder()
    (f / "000010.ldb").write_bytes(b"junk" + store(activeInputProfile="STUDIO") + b"junk")
    (f / "000012.log").write_bytes(store() + b"\x00garbage" + store(
        activeInputProfile="CUSTOM", noiseCancellation=False, echoCancellation=False,
        automaticGainControl=False))
    s, = dc.read()
    assert (s.client, s.profile, s.krisp, s.echo, s.agc) == ("Discord", "CUSTOM", False,
                                                           False, False)
    assert s.problems(on_mic=True) == []


def test_a_cut_off_store_falls_back_to_the_one_before():
    f = folder()
    good = store(activeInputProfile="STUDIO")
    (f / "000012.log").write_bytes(good + store()[:60])   # the last write cut short
    s, = dc.read()
    assert s.profile == "STUDIO"


def test_a_folder_with_no_store_is_unknown():
    (folder() / "000003.log").write_bytes(b"\x00\x01nothing here")
    assert dc.read() == []


def test_studio_and_bypass_skip_the_mic_but_suit_the_cable():
    s = dc.parse({"default": dict(DEFAULTS, activeInputProfile="STUDIO")})
    assert s.problems(on_mic=True) == [dc.STUDIO]
    assert s.problems(on_mic=False) == []
    s = dc.parse({"default": dict(DEFAULTS, activeInputProfile="CUSTOM",
                                  bypassSystemInputProcessing=True, noiseCancellation=False,
                                  echoCancellation=False, automaticGainControl=False)})
    assert s.problems(on_mic=True) == [dc.BYPASS]
    assert s.problems(on_mic=False) == []


def test_discords_defaults_are_all_problems():
    """A fresh Discord: Voice Isolation (Krisp); its Custom defaults keep Krisp, echo
    cancellation and gain control on."""
    assert dc.parse({"default": DEFAULTS}).problems(True) == [dc.ISOLATION]
    s = dc.parse({"default": dict(DEFAULTS, activeInputProfile="CUSTOM")})
    assert s.problems(True) == [dc.KRISP, dc.ECHO, dc.AGC]
    s = dc.parse({"default": {}})   # an older Discord that wrote none of the keys
    assert s.profile == "" and s.problems(True) == [dc.KRISP, dc.ECHO, dc.AGC]
    s = dc.parse({"default": dict(DEFAULTS, activeInputProfile="CUSTOM",
                                  noiseCancellation=False, noiseSuppression=True)})
    assert s.problems(True) == [dc.SUPPRESSION, dc.ECHO, dc.AGC]


def test_odd_values_fall_back_to_discords_defaults():
    s = dc.parse({"default": {"echoCancellation": "yes", "activeInputProfile": None,
                              "noiseCancellation": 0}})
    assert s.echo is True and s.krisp is True and s.profile == ""


def test_several_clients_most_recently_changed_first():
    import os
    import time
    (folder("discord") / "000001.log").write_bytes(store())
    (folder("discordcanary") / "000001.log").write_bytes(store(activeInputProfile="CUSTOM"))
    old = time.time() - 3600
    os.utime(folder("discord") / "000001.log", (old, old))
    got = dc.read()
    assert [s.client for s in got] == ["Discord Canary", "Discord"]
    assert len(dc.signature()) == 2
