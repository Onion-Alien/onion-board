"""soundboard.online.firewall: the admin copy that adds a remote add-on's firewall rule, so
Windows' prompt names Onion Board. Nothing here runs netsh or asks for admin."""
import subprocess
import sys

import pytest

from soundboard.online import firewall
from soundboard.win import systools

NETSH = systools.tool("netsh")   # Windows' own, by its full path


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


def test_commands_replace_the_rules_with_one_for_this_program_on_the_home_network():
    """One rule: this program, on the port, Private networks, local subnet. A second
    port-only rule let any program that took the port take phones' connections, and
    stayed after Onion Board was gone."""
    exe = r"C:\Program Files\Onion Board\OnionBoard.exe"
    delete, rule = firewall.commands("OnionPocket", 7475, exe)
    assert delete == [NETSH, "advfirewall", "firewall", "delete", "rule", "name=OnionPocket"]
    assert rule == [NETSH, "advfirewall", "firewall", "add", "rule", "name=OnionPocket",
                    "dir=in", "action=allow", "protocol=TCP", f"program={exe}",
                    "localport=7475", "profile=private", "remoteip=localsubnet"]


def test_cli_adds_the_rule_for_the_program_that_listens(monkeypatch):
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda call, **kw: ran.append(call)
                        or subprocess.CompletedProcess(call, 0))
    assert firewall.cli(["OnionPocket", "7475"]) == 0
    assert ran == firewall.commands("OnionPocket", 7475, firewall.listener())


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
    assert flag_at < src.index("from soundboard.core.app import main")
