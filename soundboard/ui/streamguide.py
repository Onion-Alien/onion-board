"""Remote control for streamers, the easy way: a step-by-step guide to wiring a
Stream Deck, channel points and chat commands to the control API (soundboard.remote),
with the links ready to copy, and a ready-made message for an AI assistant (ChatGPT,
Claude, …) that knows the API, the port and the person's own sounds, so it can walk
them through whatever tools they use.
"""
from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame, QHBoxLayout,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard import remote, theme
from soundboard.ui import busy, fit, icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.chatguide import _header, _label


def link(cfg, action: str, query: str = "") -> str:
    """A ready-to-paste URL for one endpoint, with the key in it."""
    sep = "&" if query else ""
    return (f"http://{remote.HOST}:{cfg.api_port}/api/{action}?{query}{sep}"
            f"token={cfg.api_token}")


def copy_prompt(mw, with_key: bool) -> str:
    """Put the AI setup prompt on the clipboard; returns what to say about it."""
    cfg = mw.cfg
    token = cfg.api_token if with_key and cfg.api_enabled else ""
    QApplication.clipboard().setText(remote.setup_prompt(cfg, cfg.api_port, token))
    if token:
        return ("Copied, with your key in it. Paste it into ChatGPT, Claude or any AI "
                "chat and say which tools you use.")
    return ("Copied (without your key: the AI will tell you where it goes). Paste it into "
            "ChatGPT, Claude or any AI chat and say which tools you use.")


class StreamerGuide(QDialog):
    """Remote control in plain words, for someone who has never used an API."""

    def __init__(self, parent, mw):
        super().__init__(parent)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle("Streamer guide — play sounds from your Stream Deck and chat")
        self.setMinimumWidth(660)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header("Streamer guide", _label(
            "Remote control lets your other stream tools press Onion Board's buttons for "
            "you: a <b>Stream Deck</b> key, a <b>channel point</b> reward, a <b>!command</b> "
            "in chat. Each one is just a link. Everything stays on this PC."),
            BunnyWidget("star")))

        ok = theme.status("ok")
        steps = _label(
            "<ol style='margin-left:-20px'>"
            "<li style='margin-bottom:8px'><b>Turn it on.</b> Click <b>Turn it on</b> "
            "below (or tick <i>Enable remote control</i> in Settings → Remote). Onion "
            "Board has to be open — the tray is fine.</li>"
            "<li style='margin-bottom:8px'><b>Test it.</b> Click <b>Random sound</b> below "
            "to copy its link, paste it into your web browser's address bar and press "
            "Enter. You hear a random sound and the page shows "
            f"<span style='color:{ok}'>\"playing\"</span>. It works!</li>"
            "<li style='margin-bottom:8px'><b>A Stream Deck key.</b> In the Stream Deck "
            "app drag <b>System → Website</b> onto a key. Pick a sound below, click "
            "<b>Copy</b> and paste the link into the URL box. Tick <b>GET request in "
            "background</b> so no browser window opens. One key per sound.</li>"
            "<li style='margin-bottom:8px'><b>Channel points and chat commands</b> "
            "(Twitch, YouTube, Kick). Get the free <b>Streamer.bot</b>. Under "
            "<b>Actions</b>, add an action, then right-click → <b>Core → Network → Fetch "
            "URL</b> and paste a link. Under <b>Triggers</b> pick what sets it off, e.g. "
            "<b>Twitch → Channel Reward → Reward Redemption</b> and your reward, or a "
            "chat command. Touch Portal, SAMMI and Mix It Up work the same way: look "
            "for their <i>HTTP / web request</i> action.</li>"
            "<li style='margin-bottom:8px'><b>A panic button.</b> Make a key with the "
            "<b>Panic mute</b> link: one press and nobody hears anything (your sounds "
            "or your mic); press it again to go live. <b>Stop all</b> just stops the "
            "sounds.</li>"
            "<li style='margin-bottom:8px'><b>Let your stream hear the sounds.</b> "
            "Settings → Audio → <b>Stream output</b>, then add that device in OBS as an "
            "<i>Audio Output Capture</i> (for a virtual cable: an <i>Audio Input "
            "Capture</i> of its Output end). Your sounds get their own volume slider in "
            "OBS. No virtual cable, or Voicemeeter / a mixer instead? Setup → Devices → "
            "<b>Send to others through</b> → <i>Another device</i> or <i>Nowhere</i>.</li>"
            "<li><b>Keep the key secret.</b> Every link holds your key. Don't show it on "
            "stream or paste it into chat. If it leaks, click <b>New key</b> in Settings → "
            "Remote — the old links stop working and you paste the new ones.</li>"
            "</ol>"
            "<span style='font-size:9.5pt'>Stuck, or want something fancier (a key per "
            "category, a random sound for every new follower, AutoHotkey)? Click "
            "<b>Copy AI prompt</b> and paste it into ChatGPT or Claude: it knows how "
            "Onion Board's links work and which sounds you have, and walks you through "
            "it.</span>")
        steps.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.addWidget(steps)
        bl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(300)
        v.addWidget(scroll, 1)

        # the links, ready to copy
        self.state = _label("", "font-size:10pt;")
        self.state.setObjectName("hint")
        row = QHBoxLayout()
        self.btn_on = QPushButton("Turn it on")
        self.btn_on.setObjectName("primary")
        self.btn_on.clicked.connect(self.turn_on)
        row.addWidget(self.btn_on)
        self.sound = QComboBox()
        self.sound.setAccessibleName("Sound to copy a link for")
        self.sound.addItems([m.name for m in mw.cfg.sounds])
        self.sound.setMinimumWidth(180)
        row.addWidget(self.sound, 1)
        self.btn_play = QPushButton("Copy")
        icons.set_icon(self.btn_play, "copy")
        self.btn_play.setToolTip("Copy the link that plays this sound")
        self.btn_play.clicked.connect(
            lambda: self._copy(self.btn_play, "play",
                               "name=" + quote(self.sound.currentText())))
        row.addWidget(self.btn_play)
        v.addLayout(row)
        row = QHBoxLayout()
        self.link_btns = [self.btn_play]
        for text, action, query, tip in (
                ("Random sound", "random", "category=", "Plays any of your sounds"),
                ("Stop all", "stop", "", "Stops every sound"),
                ("Panic mute", "live", "on=toggle",
                 "Muted / live: while muted nobody hears your sounds or your mic")):
            b = QPushButton(text)
            b.setToolTip(f"Copy the link: {tip}")
            b.clicked.connect(lambda _=False, b=b, a=action, q=query: self._copy(b, a, q))
            row.addWidget(b)
            self.link_btns.append(b)
        row.addStretch(1)
        ai = QPushButton("Copy AI prompt")
        ai.setToolTip("A message for ChatGPT / Claude that explains Onion Board's links and "
                      "lists your sounds, so it can set up your tools with you")
        ai.clicked.connect(lambda: (self.state.setText(copy_prompt(mw, False)),
                                    busy.flash(ai, "✓  Copied")))
        row.addWidget(ai)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)
        v.addWidget(self.state)
        self.refresh()

    def refresh(self):
        cfg = self.mw.cfg
        on = cfg.api_enabled and self.mw.remote.running
        self.btn_on.setVisible(not on)
        for b in self.link_btns:
            b.setEnabled(on)
        self.sound.setEnabled(on and self.sound.count() > 0)
        if not self.sound.count():
            self.btn_play.setEnabled(False)
        if not cfg.api_enabled:
            self.state.setText("Remote control is off: turn it on to get your links.")
        elif not on:
            self.state.setText(f"Remote control couldn't start: {self.mw.remote.error}. "
                               "Try another port in Settings → Remote.")
        else:
            self.state.setText(f"On, at {remote.HOST}:{self.mw.remote.port}. Pick a link "
                               "to copy.")

    def turn_on(self):
        self.mw.cfg.api_enabled = True
        self.mw.cfg.save()
        self.mw.apply_remote()
        self.refresh()

    def _copy(self, btn, action: str, query: str):
        QApplication.clipboard().setText(link(self.mw.cfg, action, query))
        busy.flash(btn, "✓  Copied")
        self.state.setText("Copied. It holds your key: paste it only into your own tools, "
                           "never into chat.")
