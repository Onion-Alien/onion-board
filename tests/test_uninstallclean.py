"""The uninstaller's tidy-up (soundboard/core/uninstallclean.py): the firewall rule goes,
their sounds only on Yes, ProgramData's folder never while the mic effect is still
there, and Windows' prompt only when something needs admin."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

if sys.platform == "win32":
    from soundboard.core import cleanup, uninstallclean as uc
    from soundboard.sounds import files


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A made-up PC: their folder, ProgramData's, the firewall rules on it, and every
    admin prompt noted instead of shown."""
    user, machine = tmp_path / "AppData" / "OnionBoard", tmp_path / "ProgramData" / "OnionBoard"
    for d in (user, machine):
        d.mkdir(parents=True)
        (d / "config.json").write_text("{}")
    state = {"rules": set(), "prompts": [], "mic": False}

    def netsh(*args):
        name = args[2].split("=", 1)[1]
        if args[0] == "show":
            return 0 if name in state["rules"] else 1
        state["rules"].discard(name)
        return 0

    def run_elevated(args, wait_s=600.0, source=()):
        state["prompts"].append(args)
        return uc.admin_part(uc.DATA in args)

    def recycle(path, warn_if_permanent=False):
        assert warn_if_permanent
        shutil.rmtree(path)
        return True

    monkeypatch.setattr(uc, "_netsh", netsh)
    monkeypatch.setattr(uc, "user_dir", lambda: user)
    monkeypatch.setattr(uc, "machine_dir", lambda: machine)
    monkeypatch.setattr(uc, "mic_parts_left", lambda: state["mic"])
    monkeypatch.setattr(cleanup, "run_elevated", run_elevated)
    monkeypatch.setattr(files, "recycle", recycle)
    state.update(user=user, machine=machine)
    return state


def test_keeping_their_sounds_asks_nothing_and_deletes_nothing(pc):
    assert uc.cli([]) == 0
    assert pc["prompts"] == []
    assert pc["user"].exists() and pc["machine"].exists()


def test_the_firewall_rule_goes_after_one_prompt(pc):
    pc["rules"].add("OnionPocket")
    assert uc.cli([]) == 0
    assert len(pc["prompts"]) == 1 and uc.ADMIN in pc["prompts"][0]
    assert not pc["rules"]
    assert pc["user"].exists() and pc["machine"].exists()


def test_yes_deletes_their_folder_and_programdata(pc):
    assert uc.cli([uc.DATA]) == 0
    assert not pc["user"].exists() and not pc["machine"].exists()


def test_programdata_stays_while_the_mic_effect_is_on(pc):
    """Without a prompt for it, and not said as their sounds staying: the uninstaller
    says the mic effect stayed."""
    pc["mic"] = True
    assert uc.cli([uc.DATA]) == 0
    assert pc["prompts"] == []
    assert pc["machine"].exists()
    assert not pc["user"].exists()


def test_a_turned_down_prompt_says_what_stayed(pc, monkeypatch):
    pc["rules"].add("OnionPocket")
    monkeypatch.setattr(cleanup, "run_elevated", lambda *a, **k: None)
    assert uc.cli([uc.DATA]) == uc.MACHINE_LEFT | uc.RULE_LEFT
    assert not pc["user"].exists()   # that part needs no admin


def test_main_runs_it_before_the_app(monkeypatch):
    """main.py hands the flag over before the breadcrumb and logging, which write into
    the folder being deleted."""
    text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert text.index('["--uninstall-cleanup"]') < text.index("bootmark")
    assert uc.FLAG == "--uninstall-cleanup"
