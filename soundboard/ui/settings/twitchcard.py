"""Settings → Remote's Twitch card: *Connect Twitch* (soundboard.control.twitchlink signs in
with Twitch's device code), then what each channel point reward and each alert plays,
and whether chat commands are on. The rules it sets are the control API's own
(soundboard.control.streamapi), so a bot or /api/alerts sees the same ones."""
from __future__ import annotations

import html

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.control import streamapi, twitchlink
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.online import twitch
from soundboard.ui.kit import busy, icons, theme
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.settings import _button_row

RANDOM = "*"      # a picker's "A random sound"
ELSEWHERE = None  # a rule set some other way (/api/alerts): left as it is


def alert_names() -> list[tuple[str, str]]:
    return [("follow", _("Follow")), ("sub", _("Sub")), ("gift_sub", _("Gift sub")),
            ("cheer", _("Cheer (bits)")), ("raid", _("Raid"))]


def rule_for(mw, kind: str, reward: str = "") -> dict | None:
    """The plain rule (no minimum amount) for an alert type, or one reward."""
    want = " ".join(reward.split()).casefold()
    return next((r for r in streamapi.alert_rules(mw).get(kind, [])
                 if float(r.get("min") or 0) == 0 and streamapi.reward_of(r) == want), None)


def picked(rule: dict | None):
    """What a picker shows for a rule: "" nothing, RANDOM, a sound's name, or ELSEWHERE."""
    if rule is None:
        return ""
    if rule.get("say") or rule.get("voice") or (rule.get("category") not in ("", "*", None)):
        return ELSEWHERE
    if rule.get("sound"):
        return str(rule["sound"])
    return RANDOM if rule.get("category") == "*" else ""


def set_rule(mw, kind: str, value: str, reward: str = "") -> None:
    params = {"type": kind, "min": "0"}
    if reward:
        params["reward"] = reward
    if value == "":
        params["clear"] = "1"
    elif value == RANDOM:
        params.update(category="*", sound="")
    else:
        params.update(sound=value, category="")
    streamapi.set_alerts(mw, params)


class TwitchCard(QObject):
    """The card's parts and its answers to the link (a QObject owned by the card, so
    the link's signals stop reaching it when Settings closes)."""

    def __init__(self, page):
        pill = QLabel()
        pill.setObjectName("pill")
        card, cv = page._card(_("Twitch"), _(
            "Plays your sounds when viewers redeem channel points, cheer, follow, sub or "
            "raid, and lets chat use !sound. Onion Board talks to Twitch itself: no bot to "
            "set up."), icon="twitch", end=(pill,))
        super().__init__(card)
        self.page, self.mw, self.link = page, page.mw, page.mw.twitch
        self.card, self.pill = card, pill
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        cv.addWidget(self.status)

        # not connected
        self.start = QWidget()
        sv = QVBoxLayout(self.start)
        sv.setContentsMargins(0, 0, 0, 0)
        row = _button_row()
        self.btn_connect = QPushButton(_("Connect Twitch"))
        self.btn_connect.setObjectName("primary")
        icons.set_icon(self.btn_connect, "twitch")
        row.addWidget(self.btn_connect)
        self._help_buttons(row)
        sv.addLayout(row)
        cv.addWidget(self.start)

        # signing in: the code
        self.signin = QWidget()
        gv = QVBoxLayout(self.signin)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(8)
        self.code = QLabel()
        self.code.setObjectName("helptitle")
        gv.addWidget(self.code)
        hint = QLabel(_("Say yes to Onion Board on the Twitch page that opened. If it asks for "
                        "a code, type this one."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        gv.addWidget(hint)
        row = _button_row()
        self.btn_open = QPushButton(_("Open Twitch"))
        icons.set_icon(self.btn_open, "link")
        self.btn_copy = QPushButton(_("Copy code"))
        icons.set_icon(self.btn_copy, "copy")
        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.setProperty("quiet", True)
        for b in (self.btn_open, self.btn_copy, self.btn_cancel):
            row.addWidget(b)
        gv.addLayout(row)
        cv.addWidget(self.signin)

        # connected: what plays
        self.on = QWidget()
        ov = QVBoxLayout(self.on)
        ov.setContentsMargins(0, 4, 0, 0)
        ov.setSpacing(8)
        head = QLabel(_("Channel points"))
        head.setObjectName("section")
        ov.addWidget(head)
        self.rewards_box = QGridLayout()
        self.rewards_box.setHorizontalSpacing(12)
        self.rewards_box.setVerticalSpacing(6)
        self.rewards_box.setColumnStretch(2, 1)
        ov.addLayout(self.rewards_box)
        self.no_rewards = QLabel(_("No channel point rewards yet. Twitch gives channel points "
                                   "to affiliates and partners; make rewards on your Twitch "
                                   "dashboard, then reload."))
        self.no_rewards.setObjectName("hint")
        self.no_rewards.setWordWrap(True)
        ov.addWidget(self.no_rewards)
        head = QLabel(_("Alerts"))
        head.setObjectName("section")
        ov.addWidget(head)
        alerts = self.alerts_box = QGridLayout()
        alerts.setHorizontalSpacing(12)
        alerts.setVerticalSpacing(6)
        alerts.setColumnStretch(2, 1)
        self.alert_pickers = {}
        for i, (kind, name) in enumerate(alert_names()):
            alerts.addWidget(QLabel(name), i, 0)
            box = self._picker(name)
            box.activated.connect(lambda _i, k=kind, b=box: self._chose(k, b))
            alerts.addWidget(box, i, 1)
            self.alert_pickers[kind] = box
        ov.addLayout(alerts)
        self.chat = QCheckBox(_("Chat commands: viewers can type !sound, !random and !sounds"))
        self.chat.setToolTip(_("Cooldowns, who may use each command and blocked words: the "
                               "streamer guide below shows how to change them"))
        ov.addWidget(self.chat)
        self.share = QCheckBox(_("Let the Onion Board developer see this channel's name"))
        self.share.setToolTip(_("Sent once a day with the usage count, only while you're "
                                "connected and Count me in is on, so the developer can see "
                                "who streams with Onion Board. Just the name. Untick to "
                                "stop."))
        ov.addWidget(self.share)
        row = _button_row()
        self.btn_reload = QPushButton(_("Reload rewards"))
        icons.set_icon(self.btn_reload, "reload")
        self.btn_reload.setProperty("quiet", True)
        self.btn_disconnect = QPushButton(_("Disconnect"))
        self.btn_disconnect.setObjectName("danger")
        self.btn_disconnect.setProperty("quiet", True)
        row.addWidget(self.btn_reload)
        self._help_buttons(row)
        row.addWidget(self.btn_disconnect)
        ov.addLayout(row)
        cv.addWidget(self.on)

        self.reward_pickers: dict[str, QComboBox] = {}
        self._url = ""
        self.btn_connect.clicked.connect(self._connect)
        self.btn_open.clicked.connect(self._open)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_reload.clicked.connect(self._reload)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.chat.toggled.connect(self._chat)
        self.share.toggled.connect(self._share)
        self.link.changed.connect(self.refresh)
        self.link.code_ready.connect(self._code)
        self.link.login_done.connect(self._done)
        self.signing_in = False
        self.refresh()

    # ------------------------------------------------------------------ help

    def _help_buttons(self, row) -> None:
        """The guide and the AI prompt, in both the connect row and the connected one."""
        guide = QPushButton(_("Twitch guide"))
        icons.set_icon(guide, "question")
        guide.setProperty("quiet", True)
        guide.setToolTip(_("How channel points, alerts and chat commands work, step by step"))
        guide.clicked.connect(self._guide)
        ai = QPushButton(_("Copy AI prompt"))
        icons.set_icon(ai, "copy")
        ai.setProperty("quiet", True)
        ai.setToolTip(_("A message for ChatGPT / Claude that explains the Twitch card "
                        "and lists your rewards and sounds, so it can help you set "
                        "it up"))
        ai.clicked.connect(lambda: self._copy_prompt(ai))
        row.addWidget(guide)
        row.addWidget(ai)

    def _guide(self):
        from soundboard.ui.kit.crashdialog import free_dialog
        from soundboard.ui.settings.twitchguide import TwitchGuide
        usage.used("twitch-guide")
        g = TwitchGuide(self.page.dlg, self.mw)
        g.exec()
        free_dialog(g)

    def _copy_prompt(self, btn):
        from soundboard.ui.settings.twitchguide import copy_twitch_prompt
        copy_twitch_prompt(self.mw)
        usage.used("twitch-prompt-copied")
        busy.flash(btn, _("✓ Copied"))
        busy.toast(self.page.dlg, html.escape(_(
            "Copied. Paste it into ChatGPT, Claude or any AI chat and say what you want "
            "your stream to do.")), "ok")

    # ------------------------------------------------------------------ pickers

    def _picker(self, name: str) -> QComboBox:
        box = QComboBox()
        box.setAccessibleName(name)
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        box.setMaximumWidth(280)
        no_wheel(box)
        return box

    def _fill(self, box: QComboBox, now) -> None:
        box.blockSignals(True)
        box.clear()
        box.addItem(_("Nothing"), "")
        box.addItem(_("A random sound"), RANDOM)
        names = [m.name for m in self.mw.cfg.sounds]
        if now is ELSEWHERE:
            box.addItem(_("Something else (set with the control API)"), "elsewhere")
        elif now and now != RANDOM and now.casefold() not in {n.casefold() for n in names}:
            box.addItem(_("{name} (not found)", name=now), now)
        for n in names:
            box.addItem(n, n)
        want = "elsewhere" if now is ELSEWHERE else now
        i = next((i for i in range(box.count())
                  if str(box.itemData(i)).casefold() == str(want).casefold()), 0)
        box.setCurrentIndex(i)
        box.blockSignals(False)
        # as wide as its longest choice (up to the cap): its own size hint left
        # "A random sound" cut off
        fm = box.fontMetrics()
        widest = max((fm.horizontalAdvance(box.itemText(j)) for j in range(box.count())),
                     default=0)
        box.setMinimumWidth(min(widest + 48, box.maximumWidth()))

    def _chose(self, kind: str, box: QComboBox, reward: str = ""):
        value = box.currentData()
        if value == "elsewhere":
            return
        set_rule(self.mw, kind, value or "", reward)

    def _rewards(self):
        if list(self.link.rewards) == list(self.reward_pickers):   # same rewards: just the picks
            for title, box in self.reward_pickers.items():
                self._fill(box, picked(rule_for(self.mw, "redeem", title)))
            return
        while self.rewards_box.count():
            item = self.rewards_box.takeAt(0)
            gone = item.widget() if item is not None else None
            if gone is not None:   # off the card now, not when the deletion comes round
                gone.hide()
                gone.setParent(None)
                gone.deleteLater()
        self.reward_pickers = {}
        for i, title in enumerate(self.link.rewards):
            label = QLabel(title)
            label.setWordWrap(True)
            self.rewards_box.addWidget(label, i, 0)
            box = self._picker(title)
            self._fill(box, picked(rule_for(self.mw, "redeem", title)))
            box.activated.connect(lambda _i, t=title, b=box: self._chose("redeem", b, t))
            self.rewards_box.addWidget(box, i, 1)
            self.reward_pickers[title] = box
        self.no_rewards.setVisible(not self.link.rewards)

    # ------------------------------------------------------------------ state

    def refresh(self):
        link, cfg = self.link, self.mw.cfg
        connected = link.connected
        self.start.setVisible(not connected and not self.signing_in)
        self.signin.setVisible(self.signing_in)
        self.on.setVisible(connected)
        tone, words = "", ""
        if self.signing_in:
            tone, words = "muted", _("Signing in")
        elif connected and link.state == twitchlink.ON:
            tone, words = "ok", _("Connected")
        elif connected and link.state == twitchlink.PROBLEM:
            tone, words = "warn", _("Not connected")
        elif connected:
            tone, words = "muted", _("Connecting")
        self.pill.setVisible(bool(words))
        self.pill.setText(words)
        theme.set_tone(self.pill, tone)
        if connected:
            text = _("Signed in as {name}.", name=cfg.twitch_login or "?")
            if link.state == twitchlink.PROBLEM and link.message:
                text += " " + link.message
            if link.refused:
                text += " " + _("Twitch won't send some events to this channel: {events}.",
                                events=", ".join(link.refused))
            self.status.setText(text)
            theme.set_tone(self.status, "warn" if link.state == twitchlink.PROBLEM else "")
            self._rewards()
            for kind, box in self.alert_pickers.items():
                self._fill(box, picked(rule_for(self.mw, kind)))
            # both lists' pickers in one column
            labels = [self.rewards_box, self.alerts_box]
            cells = [g.itemAtPosition(r, 0) for g in labels for r in range(g.rowCount())]
            shown = [c.widget() for c in cells if c is not None]
            width = max((x.sizeHint().width() for x in shown if x is not None), default=0)
            for g in labels:
                g.setColumnMinimumWidth(0, min(width, 220))
            self.chat.blockSignals(True)
            self.chat.setChecked(bool(streamapi.chat_rules(self.mw)["on"]))
            self.chat.blockSignals(False)
            self.share.blockSignals(True)
            self.share.setChecked(bool(cfg.twitch_share))
            self.share.blockSignals(False)
        elif not self.signing_in:
            self.status.setText("")
        self.status.setVisible(bool(self.status.text()))

    # ------------------------------------------------------------------ signing in

    def _connect(self):
        busy.set_busy(self.btn_connect, True)
        self.link.login()

    def _code(self, code: str, url: str):
        busy.set_busy(self.btn_connect, False)
        self.signing_in, self._url = True, url
        self.code.setText(code)
        self.status.setText("")
        self.refresh()
        self._open()

    def _open(self):
        if self._url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(self._url))

    def _copy(self):
        QApplication.clipboard().setText(self.code.text())
        busy.flash(self.btn_copy, _("✓ Copied"))

    def _cancel(self):
        self.link.cancel_login()
        self.signing_in = False
        self.refresh()

    def _done(self, ok: bool, message: str):
        busy.set_busy(self.btn_connect, False)
        self.signing_in = False
        self.refresh()
        if ok:
            busy.toast(self.page.dlg, html.escape(_("Connected to Twitch as {name}.",
                                                    name=message)), "ok")
        else:
            self.status.setText(message)
            theme.set_tone(self.status, "error")
            self.status.setVisible(True)

    def _reload(self):
        self.link.refresh_rewards()
        busy.flash(self.btn_reload, _("✓ Asked Twitch"))

    def _disconnect(self):
        name = self.mw.cfg.twitch_login
        self.link.disconnect()
        if qt_valid(self.page.dlg):
            busy.toast(self.page.dlg, html.escape(_("Disconnected from Twitch ({name}).",
                                                    name=name)), "ok")

    def _chat(self, on: bool):
        streamapi.set_chat_rules(self.mw, {"on": "1" if on else "0"})

    def _share(self, on: bool):
        self.mw.cfg.twitch_share = on
        self.mw._save_now()


def twitch_card(page):
    """The card, or None when this version can't sign in to Twitch."""
    if not twitch.offered() or getattr(page.mw, "twitch", None) is None:
        return None
    return TwitchCard(page).card
