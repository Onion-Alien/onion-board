"""soundboard.firewall: the admin copy that adds a remote add-on's firewall rule, so
Windows' prompt names Onion Board. Nothing here runs netsh or asks for admin."""
import subprocess
import sys

import pytest

from soundboard import firewall


@pytest.mark.parametrize("name, port", [("OnionPocket", 7475), ("A-b9", "1024"), ("x", 65535)])
def test_valid_rules(name, port):
    assert firewall.valid(name, port)


@pytest.mark.parametrize("name, port", [
    ("OnionPocket", 80), ("OnionPocket", 70000), ("OnionPocket", "7475 & calc"),
    ("Onion Pocket", 7475), ("x\" & calc", 7475), ("", 7475), ("9lives", 7475),
    ("a" * 41, 7475), ("OnionPocket", None),
])
def test_anything_else_is_refused(name, port):
    assert not firewall.valid(name, port)
    with pytest.raises(ValueError):
        firewall.commands(name, port, r"C:\x\OnionBoard.exe")


def test_commands_replace_the_rules_with_port_and_program_limited_to_the_home_network():
    exe = r"C:\Program Files\Onion Board\OnionBoard.exe"
    delete, port, prog = firewall.commands("OnionPocket", 7475, exe)
    assert delete == ["netsh", "advfirewall", "firewall", "delete", "rule", "name=OnionPocket"]
    for call in (port, prog):
        assert call[:9] == ["netsh", "advfirewall", "firewall", "add", "rule",
                            "name=OnionPocket", "dir=in", "action=allow", "protocol=TCP"]
        assert call[-3:] == ["localport=7475", "profile=private", "remoteip=localsubnet"]
    assert f"program={exe}" in prog and not any(a.startswith("program=") for a in port)


def test_cli_adds_both_rules_for_its_own_program(monkeypatch):
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda call, **kw: ran.append(call)
                        or subprocess.CompletedProcess(call, 0))
    assert firewall.cli(["OnionPocket", "7475"]) == 0
    assert ran == firewall.commands("OnionPocket", 7475, sys.executable)


def test_cli_refuses_bad_arguments_and_reports_a_failed_rule(monkeypatch):
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda call, **kw: ran.append(call)
                        or subprocess.CompletedProcess(call, 1))
    assert firewall.cli(["OnionPocket"]) == 2
    assert firewall.cli(["OnionPocket", "7475", r"C:\evil.exe"]) == 2
    assert firewall.cli(["bad name", "7475"]) == 2
    assert ran == []
    assert firewall.cli(["OnionPocket", "7475"]) == 1   # netsh said no


def test_from_source_the_admin_copy_runs_main_py(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    params = firewall.relaunch_params("OnionPocket", 7475)
    assert params.startswith('"') and 'main.py" --firewall-rule OnionPocket 7475' in params
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert firewall.relaunch_params("OnionPocket", 7475) == "--firewall-rule OnionPocket 7475"


def test_allow_never_asks_for_a_bad_rule(monkeypatch):
    assert firewall.allow("bad name", 7475) is False
    assert firewall.allow("OnionPocket", 22) is False


def test_main_py_hands_the_flag_to_the_cli_without_starting_the_app():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    flag_at = src.index('["--firewall-rule"]')
    assert flag_at < src.index("from soundboard.app import main")
