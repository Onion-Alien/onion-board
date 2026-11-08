"""Invite links: the installer's note and the first start's greeting."""
import re
from pathlib import Path

from conftest import said
from soundboard.core import invite
from soundboard.sounds import library
from soundboard.ui.window import invitecontrol
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_clean_keeps_a_gamertag_and_drops_the_rest():
    assert invite.clean("  xX_Sn1per_Xx  ") == "xX_Sn1per_Xx"
    assert invite.clean("Zoë  the   Great") == "Zoë the Great"
    assert invite.clean("Ник") == "Ник"
    # nothing that could break the link, a file name or the greeting's rich text
    assert invite.clean('<b>bob</b>/"&?(1)') == "bbobb1"
    assert invite.clean("a" * 40) == "a" * invite.MAX_NAME
    assert invite.clean("...") == ""


def test_take_note_reads_the_installers_note_once(tmp_path):
    assert invite.take_note(tmp_path) == ""
    # the installer writes UTF-8 with a BOM and a line break
    (tmp_path / invite.NOTE_NAME).write_bytes("﻿Zoë<x>\r\n".encode())
    assert invite.take_note(tmp_path) == "Zoëx"
    assert not (tmp_path / invite.NOTE_NAME).exists()
    assert invite.take_note(tmp_path) == ""


def test_first_start_says_who_invited_them(window, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    assert invitecontrol.welcome(window) is False   # no note: nothing said
    (tmp_path / invite.NOTE_NAME).write_text("Bob", encoding="utf-8")
    assert invitecontrol.welcome(window) is True
    assert "Bob invited you to Onion Board" in said(window)
    assert window.cfg.invited_by == "Bob"
    assert invitecontrol.welcome(window) is False   # once


def test_installer_reads_a_name_in_any_script():
    # Inno's script Copy and Trim turn letters outside the Windows code page into '?':
    # a friend invited by "Ник" got no greeting at all
    root = Path(__file__).resolve().parent.parent
    iss = (root / "installer" / "OnionBoard.iss").read_text("utf-8")
    body = re.search(r"^function InviteName: String;$(.*?)^end;$", iss, re.S | re.M).group(1)
    assert not re.search(r"\b(Copy|Trim)\s*\(", body, re.I)
