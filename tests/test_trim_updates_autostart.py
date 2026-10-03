"""Trimming a sound (part of its effects), the update check / self-update and start
with Windows. No network: GitHub's answers and downloads are faked. No registry: winreg
is faked."""
import hashlib
import io

import numpy as np
import pytest

from soundboard import autostart, library, soundfx, updates
from soundboard.library import SR, Config, SoundMeta


# --------------------------------------------------------------------------- trim

def _audio(seconds):
    return (np.ones((int(SR * seconds), 2)) * 0.25).astype(np.float32)


def test_trim_cuts_the_original_before_other_effects():
    x = _audio(4)
    out = soundfx.render(x, {"start": 1.0, "end": 2.5})
    assert abs(len(out) / SR - 1.5) < 1e-3
    fast = soundfx.render(x, {"start": 1.0, "end": 3.0, "speed": 2.0})
    assert abs(len(fast) / SR - 1.0) < 0.02          # 2 s kept, played twice as fast
    assert abs(len(soundfx.render(x, {"start": 3.0})) / SR - 1.0) < 1e-3   # to the end


def test_trim_settings_are_cleaned_and_keep_old_cache_keys():
    assert soundfx.is_neutral({"start": 0.0, "end": 0.0})
    assert not soundfx.is_neutral({"start": 0.5})
    assert soundfx.clean({"start": 3.0, "end": 2.0})["end"] == 0.0   # nothing left: whole
    assert soundfx.clean({"start": -4})["start"] == 0.0
    # sounds with effects from before trim existed keep their cache files
    assert soundfx.key({"speed": 1.5}) == soundfx.key({"speed": 1.5, "start": 0, "end": 0})
    assert soundfx.key({"speed": 1.5}) != soundfx.key({"speed": 1.5, "start": 0.2})
    assert "trimmed 0:01.0" in soundfx.summary({"start": 1.0, "end": 2.0})


def test_trim_past_the_end_of_a_short_sound_is_ignored():
    x = _audio(1)
    assert len(soundfx.trim(x, {"start": 5.0})) == len(x)


def test_original_peaks_read_the_cache_without_effects(app_dir):
    m = SoundMeta(id="t1", name="t", file="missing.wav", fx={"start": 0.5})
    t = np.arange(SR * 2) / SR
    data = np.stack([np.sin(2 * np.pi * 220 * t) * (t > 1)] * 2, 1).astype(np.float32)
    library.store_cached(m.id, data)
    peaks, length = library.original_peaks(m, 20)
    assert abs(length - 2.0) < 1e-3 and len(peaks) == 20
    assert peaks[:9].max() < 0.01 and peaks[11:].min() > 0.9   # quiet, then loud


def test_trim_panel_values(qapp):
    from soundboard.ui.trim import TrimPanel
    p = TrimPanel(np.zeros(10, np.float32), 10.0)
    assert p.values() == (0.0, 0.0)
    p.set_values(2.0, 4.0)
    assert p.values() == (2.0, 4.0)
    p.box_end.setValue(10.0)
    assert p.values() == (2.0, 0.0)                  # the very end is stored as 0
    p.box_start.setValue(9.99)
    s, e = p.values()
    assert s < 10.0 and e == 0.0                     # never an empty sound


# --------------------------------------------------------------------------- updates

@pytest.mark.parametrize("latest, current, want", [
    ("v1.0.1", "1.0.0", True), ("1.0.0", "1.0.0", False), ("0.9", "1.0.0", False),
    ("Onion Board 1.2", "1.1.9", True), ("nightly", "1.0", False),
])
def test_version_compare(latest, current, want):
    assert updates.newer(latest, current) is want


def test_check_on_by_default_and_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest",
                        lambda: calls.append(1) or updates.Release("99.0.0", "https://x"))
    cfg = Config(update_check=False)
    assert updates.check(cfg) is None and calls == []            # unticked
    cfg = Config()
    rel = updates.check(cfg)
    assert rel.version == "99.0.0" and cfg.update_checked > 0
    assert updates.check(cfg) is None and len(calls) == 1        # checked today already
    assert updates.check(cfg, force=True).version == "99.0.0"    # "Check now" still asks
    cfg.update_checked, cfg.update_skip = 0, "99.0.0"
    assert updates.check(cfg) is None                            # skipped version


def test_latest_only_links_to_github(monkeypatch):
    monkeypatch.setattr(updates, "_get", lambda url, *_f: {
        "tag_name": "v2.1.0", "html_url": "https://evil.example.com/x", "body": "a\nb"})
    rel = updates.latest()
    assert rel.version == "2.1.0" and rel.url == updates.RELEASES and rel.notes == "a b"


def test_network_errors_are_quiet_unless_asked(monkeypatch):
    def boom():
        raise OSError("offline")
    monkeypatch.setattr(updates, "latest", boom)
    cfg = Config()
    assert updates.check(cfg) is None
    with pytest.raises(OSError):
        updates.check(cfg, force=True)


def test_old_opt_in_setting_gives_way_to_the_new_default():
    cfg = Config.from_raw({"version": library.CONFIG_VERSION, "update_check_optin": False})
    assert cfg.update_check is True


SETUP = b"MZ pretend installer " * 1000
SETUP_SHA = hashlib.sha256(SETUP).hexdigest()
SETUP_URL = updates.DOWNLOADS + "v9.0.0/OnionBoardSetup.exe"


def _release_json(**asset):
    a = {"name": "OnionBoardSetup.exe", "browser_download_url": SETUP_URL,
         "digest": f"sha256:{SETUP_SHA}", "size": len(SETUP)}
    a.update(asset)
    return {"tag_name": "v9.0.0", "html_url": "https://github.com/x", "body": "notes",
            "assets": [{"name": "other.zip"}, a]}


def test_latest_finds_the_installer_and_its_checksum(monkeypatch):
    monkeypatch.setattr(updates, "_get", lambda url, *_f: _release_json())
    rel = updates.latest()
    assert (rel.asset_url, rel.sha256, rel.size) == (SETUP_URL, SETUP_SHA, len(SETUP))


def test_an_installer_under_the_old_repo_name_is_still_trusted(monkeypatch):
    """The repo was renamed onionboard -> onion-board; GitHub redirects the old name."""
    old = "https://github.com/Onion-Alien/onionboard/releases/download/v9.0.0/OnionBoardSetup.exe"
    assert updates.DOWNLOADS == "https://github.com/Onion-Alien/onion-board/releases/download/"
    monkeypatch.setattr(updates, "_get", lambda url, *_f: _release_json(browser_download_url=old))
    assert updates.latest().asset_url == old


def test_latest_takes_the_checksum_from_the_notes_without_a_digest(monkeypatch):
    data = _release_json(digest=None)
    data["body"] = f"Download below.\n\nSHA-256: `{SETUP_SHA.upper()}`\n"
    monkeypatch.setattr(updates, "_get", lambda url, *_f: data)
    assert updates.latest().sha256 == SETUP_SHA


@pytest.mark.parametrize("asset", [
    {"browser_download_url": "https://evil.example.com/OnionBoardSetup.exe"},
    {"browser_download_url": "https://github.com/someone-else/onionboard/releases/"
                             "download/v9.0.0/OnionBoardSetup.exe"},
    {"digest": None},                     # nothing to check it against
    {"digest": "sha512:abcd"},
    {"name": "Setup.exe"},
])
def test_latest_offers_no_installer_it_cannot_trust(monkeypatch, asset):
    monkeypatch.setattr(updates, "_get", lambda url, *_f: _release_json(**asset))
    rel = updates.latest()
    assert rel.version == "9.0.0" and rel.asset_url == "" and rel.sha256 == ""


class FakeResponse(io.BytesIO):
    def __init__(self, data, url=SETUP_URL):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url


def _release():
    return updates.Release("9.0.0", "https://github.com/x", "", SETUP_URL, SETUP_SHA,
                           len(SETUP))


def test_download_checks_the_file_and_reports_progress(monkeypatch):
    opened = []
    monkeypatch.setattr(updates, "_open",
                        lambda url, *_f: opened.append(url) or FakeResponse(SETUP))
    monkeypatch.setattr(updates, "CHUNK", 4096)
    seen = []
    path = updates.download(_release(), lambda d, t: seen.append((d, t)))
    assert path == updates.installer_path(_release()) and path.read_bytes() == SETUP
    assert opened == [SETUP_URL] and seen[-1] == (len(SETUP), len(SETUP)) and len(seen) > 1
    assert not list(path.parent.glob("*.part"))
    assert updates.download(_release()) == path and len(opened) == 1   # already there


def test_download_throws_away_a_file_that_does_not_match(monkeypatch):
    monkeypatch.setattr(updates, "_open", lambda url, *_f: FakeResponse(SETUP + b"tampered"))
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download(_release())
    assert not list(updates.UPDATES_DIR.glob("*"))


def test_download_refuses_a_release_without_a_checked_installer():
    rel = _release()
    rel.sha256 = ""
    with pytest.raises(updates.UpdateError):
        updates.download(rel)
    rel = _release()
    rel.asset_url = "https://evil.example.com/OnionBoardSetup.exe"
    with pytest.raises(updates.UpdateError):
        updates.download(rel)


def test_download_refuses_a_redirect_off_https(monkeypatch):
    monkeypatch.setattr(updates, "_open",
                        lambda url, *_f: FakeResponse(SETUP, "http://example.com/x.exe"))
    with pytest.raises(updates.UpdateError, match="HTTPS"):
        updates.download(_release())
    assert not list(updates.UPDATES_DIR.glob("*"))


def test_download_stops_when_cancelled_or_offline(monkeypatch):
    monkeypatch.setattr(updates, "_open", lambda url, *_f: FakeResponse(SETUP))
    with pytest.raises(updates.UpdateError, match="cancelled"):
        updates.download(_release(), cancelled=lambda: True)

    def offline(url, *_feature):
        raise OSError("no network")
    monkeypatch.setattr(updates, "_open", offline)
    with pytest.raises(updates.UpdateError, match="no network"):
        updates.download(_release())
    assert not list(updates.UPDATES_DIR.glob("*.part"))


def test_installer_runs_quietly_without_the_extras_and_reopens_the_app(tmp_path):
    args = updates.installer_args(tmp_path / "OnionBoardSetup-9.0.0.exe")
    assert args[0].endswith("OnionBoardSetup-9.0.0.exe")
    assert "/SILENT" in args and "/NORESTART" in args and "/RELAUNCH=1" in args
    assert "/MERGETASKS=!vbcable,!ffmpeg,!livevoice" in args
    assert any(a.startswith("/LOG=") for a in args)


@pytest.mark.parametrize("pending, current, want", [
    ("9.0.0", "9.0.0", True), ("9.0.0", "9.0.1", True), ("9.0.0", "1.3.2", False),
])
def test_finished_compares_versions(pending, current, want):
    assert updates.finished(pending, current) is want


def test_cleanup_removes_downloaded_installers_only():
    updates.UPDATES_DIR.mkdir(parents=True)
    for name in ("OnionBoardSetup-9.0.0.exe", "OnionBoardSetup-9.0.1.exe.part",
                 "install.log"):
        (updates.UPDATES_DIR / name).write_bytes(b"x")
    updates.cleanup()
    assert [p.name for p in updates.UPDATES_DIR.iterdir()] == ["install.log"]


# --------------------------------------------------------------------------- autostart

class FakeReg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}     # the Run key
        self.approved = {}   # Task Manager's StartupApproved\Run key

    class _Key:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, root, path, *a):
        return self._Key(self.approved if path == autostart.APPROVED_KEY else self.values)

    CreateKey = OpenKey

    def QueryValueEx(self, k, name):
        if name not in k.values:
            raise FileNotFoundError(name)
        return k.values[name], self.REG_SZ

    def SetValueEx(self, k, name, _r, _t, value):
        k.values[name] = value

    def DeleteValue(self, k, name):
        if name not in k.values:
            raise FileNotFoundError(name)
        del k.values[name]


def test_autostart_adds_updates_and_removes_the_run_value(monkeypatch):
    reg = FakeReg()
    monkeypatch.setattr(autostart, "winreg", reg)
    assert not autostart.is_enabled()
    assert autostart.set_enabled(True, hidden=True)
    cmd = reg.values["OnionBoard"]
    assert cmd.endswith(" --tray") and "main.py" in cmd and cmd.startswith('"')
    autostart.refresh(hidden=False)
    assert not reg.values["OnionBoard"].endswith("--tray")
    assert autostart.set_enabled(False) and not autostart.is_enabled()
    assert autostart.set_enabled(False)              # already off: fine
    autostart.refresh(hidden=True)
    assert not autostart.is_enabled()                # refresh never switches it on


def test_autostart_follows_task_managers_switch(monkeypatch):
    reg = FakeReg()
    monkeypatch.setattr(autostart, "winreg", reg)
    assert autostart.set_enabled(True)
    reg.approved["OnionBoard"] = b"" + bytes(11)   # Task Manager → Startup apps: off
    assert not autostart.is_enabled()                # the box shows what Windows will do
    assert autostart.set_enabled(True)               # ticking it again really turns it on
    assert autostart.is_enabled() and "OnionBoard" not in reg.approved
    reg.approved["OnionBoard"] = b"" + bytes(11)   # on there: fine
    assert autostart.is_enabled()


def test_release_notes_become_plain_whole_paragraphs():
    body = ("Drum pads and **instant replay**: see [the docs](https://example.com).\n\n"
            "- **MIDI pads.** Plug in a `Launchpad` and go.\n"
            "- Hold to play.\n\n"
            + "A very long third paragraph. " * 30)
    s = updates.summary(body)
    assert "**" not in s and "`" not in s and "](" not in s
    assert s.startswith("Drum pads and instant replay: see the docs.")
    assert "MIDI pads. Plug in a Launchpad and go. - Hold to play." in s
    assert "third paragraph" not in s                  # only whole paragraphs that fit
    long = updates.summary("First sentence here. " * 40)
    assert long.endswith(".") and len(long) <= 420


def test_installer_starts_without_the_frozen_apps_variables():
    bundle = r"C:\Apps\OnionBoard\_internal"
    env = updates.installer_env({
        "PATH": bundle + r";C:\Windows;C:\Apps\OnionBoard\_internal\sub",
        "_PYI_APPLICATION_HOME_DIR": bundle, "_PYI_ARCHIVE_FILE": "x",
        "_PYI_PARENT_PROCESS_LEVEL": "0", "_MEIPASS2": bundle,
        "QT_PLUGIN_PATH": bundle + r"\PySide6\plugins", "APPDATA": r"C:\Roaming",
    }, bundle)
    assert env == {"PATH": r"C:\Windows", "APPDATA": r"C:\Roaming",
                   "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    # from source there's no bundle: only the reset flag is added
    assert updates.installer_env({"PATH": r"C:\x"}, "") == {
        "PATH": r"C:\x", "PYINSTALLER_RESET_ENVIRONMENT": "1"}


def test_installer_reopens_the_app_through_explorer():
    """Straight from setup, the new app inherits the old frozen app's variables and
    crashed on start (1.3.3 -> 1.4.0)."""
    from pathlib import Path
    iss = (Path(__file__).parent.parent / "installer" / "OnionBoard.iss").read_text("utf-8")
    run = [line for line in iss.splitlines() if "Check: Relaunch" in line]
    assert len(run) == 1 and run[0].startswith(r'Filename: "{win}\explorer.exe"')
