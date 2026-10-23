"""Putting Discord back the way you talk on quit (soundboard.mic.discordtalk): LevelDB's log
format, the write into a fake Discord folder (never the real one: conftest), what's put
back and when nothing is touched, and the board remembering how you talk."""
import json
import struct

import pytest

from soundboard.mic import discordcfg as dc
from soundboard.mic import discordtalk as dt
from test_mainwindow import window  # noqa: F401 - the real window, offscreen

SOUND = {"activeInputProfile": "CUSTOM", "noiseCancellation": False,
         "echoCancellation": False, "automaticGainControl": False,
         "bypassSystemInputProcessing": False, "inputDeviceId": "default",
         "modeOptions": {"vadUseKrisp": False, "autoThreshold": False, "threshold": -50}}


def make_db(default: dict, client="discord", seq=500, manifest_seq=900, extra=b""):
    """A Discord settings folder: CURRENT, a MANIFEST whose edit records `manifest_seq`,
    and a log holding a put of the store at `seq` (plus `extra` bytes)."""
    f = dc._appdata() / client / "Local Storage" / "leveldb"
    f.mkdir(parents=True, exist_ok=True)
    (f / "CURRENT").write_text("MANIFEST-000002\n", "ascii")
    edit = (b"\x01" + dt._put_varint(26) + b"leveldb.BytewiseComparator"
            + b"\x02\x03" + b"\x03\x05" + b"\x04" + dt._put_varint(manifest_seq))
    (f / "MANIFEST-000002").write_bytes(dt.frame(edit, 0))
    value = dt.encode_value(json.dumps({"default": default, "stream": {}}, separators=(",", ":")))
    (f / "000003.log").write_bytes(dt.frame(dt.batch_put(seq, dt.KEY, value), 0) + extra)
    (f / "LOCK").write_bytes(b"")
    return f


def settings(client="discord", name="Discord"):
    return dc.read_client(client, name)


# ---------------------------------------------------------------- the log format

def test_crc32c_known_answer():
    assert dt.crc32c(b"123456789") == 0xE3069283


@pytest.mark.parametrize("offset", [0, 100, dt.BLOCK - 7, dt.BLOCK - 3, dt.BLOCK - 20])
@pytest.mark.parametrize("size", [10, 40_000, 100_000])
def test_frames_read_back_across_block_edges(offset, size):
    data = dt.frame(b"a" * (offset - dt.HEADER), 0) if offset else b""
    assert len(data) == offset
    rec = bytes(range(256)) * (size // 256) + b"!"
    data += dt.frame(rec, len(data))
    got = dt.read_records(data)
    assert got is not None and got[-1] == rec


def test_a_damaged_log_reads_as_none():
    data = bytearray(dt.frame(b"hello world", 0))
    data[-1] ^= 1
    assert dt.read_records(bytes(data)) is None
    assert dt.read_records(dt.frame(b"x" * 50, 0)[:-5]) is None   # cut off


def test_batch_value_round_trip():
    v = dt.encode_value('{"a":"Mikrofon (Ünïcode ✓)"}')
    assert v[:1] == b"\x00"   # not Latin-1: UTF-16
    assert dt.decode_value(dt.batch_value(dt.batch_put(7, dt.KEY, v))) == \
        '{"a":"Mikrofon (Ünïcode ✓)"}'


# ---------------------------------------------------------------- putting it back

def test_sound_mode_is_put_back_to_discords_defaults(tmp_path):
    f = make_db(SOUND)
    assert not dt.talking(settings())
    assert dt.restore({}, tmp_path / "bk", running=set()) == []
    s = settings()
    assert s.krisp and s.echo and s.agc and s.auto
    store = dt.read_store("discord")
    assert store["default"]["modeOptions"]["threshold"] == -50   # the rest kept
    assert store["stream"] == {}
    recs = dt.read_records((f / "000003.log").read_bytes())
    assert len(recs) == 2
    seq = struct.unpack_from("<Q", recs[-1])[0]
    assert seq == 901                                  # above the manifest's 900
    assert list((tmp_path / "bk" / "discord").iterdir())   # a copy kept first


def test_saved_talking_settings_win_over_the_defaults(tmp_path):
    make_db(SOUND)
    saved = {"discord": {"activeInputProfile": "VOICE_ISOLATION", "echoCancellation": True}}
    dt.restore(saved, tmp_path / "bk", running=set())
    s = settings()
    assert s.profile == "VOICE_ISOLATION" and s.echo
    assert not s.agc                                   # not in the saved ones: as it was


def test_studio_is_left_for_custom(tmp_path):
    make_db(dict(SOUND, activeInputProfile="STUDIO"))
    dt.restore({}, tmp_path / "bk", running=set())
    assert settings().profile == "CUSTOM"


def test_a_running_discord_is_left_for_the_helper(tmp_path):
    f = make_db(SOUND)
    before = (f / "000003.log").read_bytes()
    assert dt.restore({}, tmp_path / "bk", running={"discord"}) == ["discord"]
    assert (f / "000003.log").read_bytes() == before


def test_a_locked_database_is_not_touched(tmp_path):
    import msvcrt
    f = make_db(SOUND)
    before = (f / "000003.log").read_bytes()
    with open(f / "LOCK", "r+b") as held:   # as an open Discord holds it
        msvcrt.locking(held.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            assert dt.restore({}, tmp_path / "bk", running=set()) == ["discord"]
        finally:
            held.seek(0)
            msvcrt.locking(held.fileno(), msvcrt.LK_UNLCK, 1)
    assert (f / "000003.log").read_bytes() == before


def test_a_damaged_database_is_not_touched(tmp_path):
    f = make_db(SOUND, extra=b"\x01\x02\x03\x04\x05\x06\x07garbage")
    before = (f / "000003.log").read_bytes()
    assert dt.restore({}, tmp_path / "bk", running=set()) == []
    assert (f / "000003.log").read_bytes() == before
    assert not (tmp_path / "bk").exists()


def test_already_talking_is_left_alone(tmp_path):
    f = make_db(dict(SOUND, noiseCancellation=True))
    before = (f / "000003.log").read_bytes()
    dt.restore({}, tmp_path / "bk", running=set())
    assert (f / "000003.log").read_bytes() == before


def test_snapshot_takes_only_the_talking_keys():
    snap = dt.snapshot({"default": dict(SOUND, noiseCancellation=True)})
    assert snap["noiseCancellation"] is True
    assert snap["modeOptions.autoThreshold"] is False
    assert snap["modeOptions.threshold"] == -50          # your own slider, put back on quit
    assert "inputDeviceId" not in snap


# ---------------------------------------------------------------- in the board

def test_the_board_remembers_how_you_talk_once(window):  # noqa: F811
    talk = {"discord": {"noiseCancellation": True}}
    found = [dc.parse({"default": dict(SOUND, noiseCancellation=True)})]
    window.alertctl._on_discord((found, ("a",), talk))
    assert window.cfg.discord_talk == talk
    found = [dc.parse({"default": SOUND})]   # set up for sounds later: not taken
    window.alertctl._on_discord((found, ("b",), {"discord": {"noiseCancellation": False}}))
    assert window.cfg.discord_talk == talk


def test_quitting_hands_an_open_discord_to_the_helper(window, monkeypatch):  # noqa: F811
    started = []
    monkeypatch.setattr(dt, "restore", lambda saved, root, **k: ["discord"])
    monkeypatch.setattr(dt, "start_helper", lambda *a: started.append(a[2]))
    window.cfg.discord_restore = False
    window.alertctl.discord_quit()
    assert started == []
    window.cfg.discord_restore = True
    window.alertctl.discord_quit()
    assert started == [["discord"]]


def _helper_job(monkeypatch, tmp_path, pending=("discord",)) -> list:
    """The job a quit leaves for the helper, in a fake app folder; its wait (the event
    loop) ends at once. Returns the notifications it shows."""
    from PySide6 import QtWidgets

    from soundboard.core import bootmark
    from soundboard.ui.kit import theme

    class App:   # no second QApplication in the test run, no event loop
        instance = staticmethod(QtWidgets.QApplication.instance)   # conftest asks

        def __init__(self, *a):
            pass

        def setQuitOnLastWindowClosed(self, on):
            pass

        def exec(self):
            return 0
    shown = []

    class Tray:
        MessageIcon = QtWidgets.QSystemTrayIcon.MessageIcon

        def __init__(self, *a, **k):
            self.messageClicked = self

        def connect(self, *a):
            pass

        def setToolTip(self, *a):
            pass

        def show(self):
            pass

        def hide(self):
            pass

        def showMessage(self, title, *a):
            shown.append(title)
    monkeypatch.setattr(QtWidgets, "QApplication", App)
    monkeypatch.setattr(QtWidgets, "QSystemTrayIcon", Tray)
    monkeypatch.setattr(theme, "app_icon", lambda: None)
    monkeypatch.setattr(bootmark, "app_dir", lambda: tmp_path)
    dt.job_path(tmp_path).write_text(json.dumps({"saved": {}, "pending": list(pending)}),
                                     "utf-8")
    return shown


def test_the_uninstaller_puts_discord_back_at_once(monkeypatch, tmp_path):
    """The uninstaller can't leave the helper waiting (it's removing its exe): `--now`
    puts back a closed Discord and ends, or says one is still open (exit code 2)."""
    f = make_db(SOUND)
    before = (f / "000003.log").read_bytes()
    monkeypatch.setattr(dt, "running_clients", lambda: {"discord"})
    _helper_job(monkeypatch, tmp_path)
    assert dt.cli(["--now"]) == 2 == dt.STILL_OPEN
    assert (f / "000003.log").read_bytes() == before   # never into an open Discord
    assert not dt.job_path(tmp_path).exists()           # nothing left to wait for it

    monkeypatch.setattr(dt, "running_clients", lambda: set())
    _helper_job(monkeypatch, tmp_path)
    assert dt.cli(["--now"]) == 0
    s = settings()
    assert s.krisp and s.echo and s.agc
    assert not dt.job_path(tmp_path).exists()


def test_the_helper_started_again_by_the_installer_says_nothing(monkeypatch, tmp_path):
    """After an update the installer starts the helper it stopped again (`--quiet`): it
    goes on waiting for Discord, without a second notification."""
    told = _helper_job(monkeypatch, tmp_path)
    assert dt.cli(["--quiet"]) == 0
    assert told == []
    assert dt.job_path(tmp_path).exists()   # still waiting: the job's kept
    assert dt.cli([]) == 0
    assert told == ["Discord is still set up for sounds"]


def test_the_installer_stops_the_helper_and_starts_it_again():
    """The helper runs the exe, so Windows listed it as Onion Board still open on the
    installer's Preparing to Install page: the installer stops it first (PrepareToInstall
    runs before that check) and starts it again once the files are in; the uninstaller
    stops it and puts Discord back at once."""
    from pathlib import Path
    iss = (Path(__file__).resolve().parents[1] / "installer" / "OnionBoard.iss").read_text(
        "utf-8")
    def body(head):   # a procedure of the script, to its end
        rest = iss[iss.index(head):]
        return rest[:rest.index("\nend;")]
    assert "StopDiscordHelper" in body("function PrepareToInstall(")
    assert "StartDiscordHelper" in body("procedure CurStepChanged(")
    assert "'--discord-restore --quiet'" in iss
    unins = body("procedure CurUninstallStepChanged(")
    assert "StopDiscordHelper" in unins and "'--discord-restore --now'" in unins
    assert unins.index("StopDiscordHelper") < unins.index("--uninstall-count")


def test_put_back_by_hand_also_does_a_half_set_discord(tmp_path):
    """the Mic effect card's Put Discord back: quitting leaves a Discord with some clean-up
    on alone, the button puts the rest back too."""
    assert not dt.installed()
    half = dict(SOUND, noiseCancellation=True)
    make_db(half)
    assert dt.installed()
    assert dt.to_restore({}) == ["discord"]
    dt.restore({}, tmp_path / "bk", running=set())
    assert not settings().echo                         # on quit: left alone
    assert dt.restore({}, tmp_path / "bk", running=set(), only={"discord"}, always=True) == []
    s = settings()
    assert s.krisp and s.echo and s.agc
    assert dt.to_restore({}) == []                     # nothing left to put back


def test_put_back_waits_for_an_open_discord_to_close(window, monkeypatch, tmp_path):  # noqa: F811
    """Discord open: the card leaves it to the window, which puts it back once Discord's
    gone and says so."""
    from soundboard.ui.setup.audiorecovery import RecoveryCard
    toasts = []
    monkeypatch.setattr(window, "toast", lambda text, kind="", *a, **k: toasts.append(text))
    card = RecoveryCard(window)
    card._discord_back(["discord"], ["discord"])
    assert window.alertctl.discord_pending == {"discord"}
    assert "Close Discord" in toasts[-1]
    window.alertctl._on_discord(([], None, {}, ["discord"]))
    assert window.alertctl.discord_pending == set()
    assert "back the way you talk" in toasts[-1]
    card._discord_back([], [])
    assert "already" in toasts[-1]
    card.deleteLater()


def test_set_up_window_puts_discord_back_too(window, monkeypatch):  # noqa: F811
    """The "set up for your sounds" window shows the Mic effect card's Put Discord back
    row, and its button really does it (it used to be a picture of the button)."""
    import time
    from PySide6.QtWidgets import QApplication
    from soundboard.ui.setup.chatguide import DiscordFixed
    toasts, asked = [], []
    monkeypatch.setattr(window, "toast", lambda text, kind="", *a, **k: toasts.append(text))
    monkeypatch.setattr(dt, "to_restore", lambda saved: ["discord"])
    monkeypatch.setattr(dt, "restore", lambda saved, root, **k: asked.append(k) or [])
    box = DiscordFixed(window, "Discord", [("Echo Cancellation", "On", "Off")], False,
                       mw=window)
    assert not box.back.button.isHidden()
    box.back.button.click()
    end = time.monotonic() + 5
    while not toasts and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert asked and asked[0]["only"] == {"discord"} and asked[0]["always"]
    assert "back the way you talk" in toasts[-1]
    assert box.result() == DiscordFixed.DialogCode.Accepted   # its news is old now
    box.deleteLater()


# ---------------------------------------------------------------- setting it up for sounds

TALK = {"activeInputProfile": "CUSTOM", "noiseCancellation": True, "echoCancellation": True,
        "automaticGainControl": True, "bypassSystemInputProcessing": False,
        "mode": "VOICE_ACTIVITY", "inputDeviceId": "default",
        "modeOptions": {"vadUseKrisp": True, "autoThreshold": True, "threshold": -50}}


def test_set_up_saves_how_you_talk_then_clears_what_chops_sounds(tmp_path):
    """Discord set for talking: the talking settings are handed back to be saved,
    then every clean-up that chops sounds goes off; the rest (the mic, the
    threshold) stays, and a copy of the folder is kept first."""
    make_db(TALK)
    res = dt.set_up({}, tmp_path / "bk", on_mic=True, running=set())
    assert [n for n, _b, _a in res["done"]] == ["Discord"]
    assert res["talk"]["discord"]["noiseCancellation"] is True   # how they talk, saved
    s = settings()
    assert not s.problems(True) and s.profile == "CUSTOM"
    store = dt.read_store("discord")
    assert store["default"]["inputDeviceId"] == "default"
    assert store["default"]["modeOptions"]["threshold"] == dt.THRESHOLD_DB == -65
    assert res["talk"]["discord"]["modeOptions.threshold"] == -50   # put back on quit
    assert list((tmp_path / "bk" / "discord").iterdir())
    # ...and putting it back gives the talking settings again (the Mic effect card)
    dt.restore(res["talk"], tmp_path / "bk", running=set(), always=True)
    assert dt.talking(settings())


def test_set_up_keeps_talking_settings_already_saved(tmp_path):
    make_db(TALK)
    res = dt.set_up({"discord": {"echoCancellation": True}}, tmp_path / "bk", on_mic=True,
                    running=set())
    assert res["talk"] == {} and res["done"]


def test_set_up_leaves_a_right_discord_alone(tmp_path):
    f = make_db(SOUND)
    before = (f / "000003.log").read_bytes()
    res = dt.set_up({}, tmp_path / "bk", on_mic=True, running=set())
    assert res["done"] == [] and res["running"] == []
    assert (f / "000003.log").read_bytes() == before


def test_set_up_never_writes_into_a_running_discord(tmp_path):
    f = make_db(TALK)
    before = (f / "000003.log").read_bytes()
    res = dt.set_up({}, tmp_path / "bk", on_mic=True, running={"discord"})
    assert res["running"] == ["discord"] and res["done"] == []
    assert (f / "000003.log").read_bytes() == before
