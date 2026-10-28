"""Invite a friend: the link, the installer's note and the first start's greeting."""
import re
from pathlib import Path

from PySide6.QtWidgets import QApplication

from conftest import said
from soundboard.core import invite
from soundboard.sounds import library
from soundboard.ui.settings.settings import SettingsDialog
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


def test_link_has_the_name_only_when_there_is_one():
    assert invite.link("") == invite.INVITE_URL
    assert invite.link("<>") == invite.INVITE_URL
    assert invite.link("Big Bob") == invite.INVITE_URL + "?from=Big%20Bob"
    assert invite.link("Zoë") == invite.INVITE_URL + "?from=Zo%C3%AB"


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


def test_about_page_copies_an_invite_link_with_their_name(window):  # noqa: F811
    window.cfg.invite_name = ""
    d = SettingsDialog(window, "about")
    assert d.invite_link.text() == invite.INVITE_URL
    d.invite_name.setText("Big <Bob>")
    assert window.cfg.invite_name == "Big Bob"
    assert d.invite_link.text() == invite.link("Big Bob")
    d.invite_copy.click()
    assert QApplication.clipboard().text() == invite.INVITE_URL + "?from=Big%20Bob"
    d.close()
    # the name is kept for the next time
    d = SettingsDialog(window, "about")
    assert d.invite_name.text() == "Big Bob"
    d.close()


def test_installer_reads_a_name_in_any_script():
    # Inno's script Copy and Trim turn letters outside the Windows code page into '?':
    # a friend invited by "Ник" got no greeting at all
    root = Path(__file__).resolve().parent.parent
    iss = (root / "installer" / "OnionBoard.iss").read_text("utf-8")
    body = re.search(r"^function InviteName: String;$(.*?)^end;$", iss, re.S | re.M).group(1)
    assert not re.search(r"\b(Copy|Trim)\s*\(", body, re.I)
