"""Trimming a sound (part of its effects), the opt-in update check and start with
Windows. No network: the GitHub answer is faked. No registry: winreg is faked."""
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


def test_check_only_when_opted_in_and_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest",
                        lambda: calls.append(1) or updates.Release("99.0.0", "https://x"))
    cfg = Config()
    assert updates.check(cfg) is None and calls == []            # not opted in
    cfg.update_check_optin = True
    rel = updates.check(cfg)
    assert rel.version == "99.0.0" and cfg.update_checked > 0
    assert updates.check(cfg) is None and len(calls) == 1        # checked today already
    assert updates.check(cfg, force=True).version == "99.0.0"    # "Check now" still asks
    cfg.update_checked, cfg.update_skip = 0, "99.0.0"
    assert updates.check(cfg) is None                            # skipped version


def test_latest_only_links_to_github(monkeypatch):
    monkeypatch.setattr(updates, "_get", lambda url: {
        "tag_name": "v2.1.0", "html_url": "https://evil.example.com/x", "body": "a\nb"})
    rel = updates.latest()
    assert rel.version == "2.1.0" and rel.url == updates.RELEASES and rel.notes == "a\nb"


def test_network_errors_are_quiet_unless_asked(monkeypatch):
    def boom():
        raise OSError("offline")
    monkeypatch.setattr(updates, "latest", boom)
    cfg = Config(update_check_optin=True)
    assert updates.check(cfg) is None
    with pytest.raises(OSError):
        updates.check(cfg, force=True)


# --------------------------------------------------------------------------- autostart

class FakeReg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, root, path, *a):
        return self._Key()

    CreateKey = OpenKey

    def QueryValueEx(self, k, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, k, name, _r, _t, value):
        self.values[name] = value

    def DeleteValue(self, k, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


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
