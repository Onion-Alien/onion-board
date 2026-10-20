"""The Twitch card's help (Settings → Remote): a step-by-step guide to what *Connect
Twitch* does, and a ready-made message for an AI assistant (ChatGPT, Claude, …) that
knows the card, the person's rewards, alerts, chat rules and sounds, so it can walk
them through Twitch's side and the extras only the control API sets (cooldowns, who
may use each command, a line said for a donation…)."""
from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard.control import remote, streamapi
from soundboard.i18n import _
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.setup.chatguide import _bun, _header, _label, _steps

PROMPT_SOUNDS = 120     # a big library: list this many names, the AI can ask for the rest


def _what_plays(rule: dict | None) -> str:
    if rule is None:
        return "nothing"
    if rule.get("sound"):
        return f'the sound "{rule["sound"]}"'
    if rule.get("category") == "*":
        return "a random sound"
    bits = []
    if rule.get("category"):
        bits.append(f'a random sound from the "{rule["category"]}" category')
    if rule.get("say"):
        bits.append(f'says "{rule["say"]}"')
    if rule.get("voice"):
        bits.append(f'puts on the "{rule["voice"]}" voice')
    return ", ".join(bits) or "nothing"


def twitch_prompt(mw) -> str:
    """A message to paste into ChatGPT / Claude / any AI assistant so it can help with
    the Twitch card: how it works, what's set now, and the control API calls for what
    the card itself has no switch for. The key is never in it."""
    from soundboard.ui.settings.twitchcard import alert_names, rule_for
    cfg, link = mw.cfg, mw.twitch
    base = f"http://{remote.HOST}:{cfg.api_port}"
    key = remote.KEY_PLACEHOLDER
    sounds = list(cfg.sounds)
    names = [f"- {m.name}" + (f"  (categories: {', '.join(m.tags)})" if m.tags else "")
             for m in sounds[:PROMPT_SOUNDS]]
    if len(sounds) > PROMPT_SOUNDS:
        names.append(f"- … and {len(sounds) - PROMPT_SOUNDS} more")
    example = sounds[0].name if sounds else "Airhorn"
    if link is not None and link.connected:
        state = f"Connected, signed in as {cfg.twitch_login or '?'}."
        if link.refused:
            state += (" Twitch refuses to send these events to my channel: "
                      f"{', '.join(link.refused)}.")
        rewards = [f'- "{t}": {_what_plays(rule_for(mw, "redeem", t))}' for t in link.rewards]
        rewards_text = "\n".join(rewards) or "- (none: I have no channel point rewards yet)"
    else:
        state = "Not connected yet."
        rewards_text = "- (not connected, so not loaded yet)"
    alerts = "\n".join(f"- {kind}: {_what_plays(rule_for(mw, kind))}"
                       for kind, _name in alert_names())
    rules = streamapi.chat_rules(mw)
    shown = {**rules, "on": "on" if rules["on"] else "off",
             "category": rules["category"] or "(any)",
             "blocked": ", ".join(rules["blocked"]) or "(none)"}
    chat = "\n".join(f"- {k}: {shown[k]}" for k in (
        "on", "prefix", *streamapi.COMMANDS, "tts", "user_cooldown", "cooldown",
        "category", "blocked"))
    api_state = "on" if cfg.api_enabled else "off"
    return f"""\
I use Onion Board, a free Windows soundboard and voice changer, and I want help with \
its Twitch card (Settings → Remote → Twitch). Ask me what I want my stream to do \
(channel point rewards, alerts for follows / subs / bits / raids, chat commands), then \
give me beginner-friendly, click-by-click steps on Twitch's side and in Onion Board. \
If I'm not sure, suggest a few fun ideas using my own sounds below. Answer in the \
language I write to you in.

HOW THE TWITCH CARD WORKS
- "Connect Twitch" signs in with Twitch's device code: a Twitch page opens, I say yes \
(and type the code if it asks). No bot, no Streamer.bot, nothing else to install. \
Onion Board must be open while I stream (minimised to the tray is fine).
- Channel points: once connected, the card lists my channel point rewards and I pick \
what each one plays: nothing, a random sound, or one of my sounds. Only Twitch \
Affiliates and Partners have channel points. Rewards are made on Twitch (Creator \
Dashboard → Viewer Rewards → Channel Points → Manage Rewards), then "Reload rewards" \
on the card.
- Alerts: the card picks a sound (or a random one) for Follow, Sub, Gift sub, Cheer \
(bits) and Raid.
- Chat commands (one tick box): viewers type !sound <name>, !random [category] and \
!sounds (lists them); mods can !stop and !voice <name>; !say <text> is off by default. \
Onion Board posts its answers in my chat itself.
- So my stream hears the sounds: Setup → Devices → "Also play on", add a device set \
to "Clean, for streaming", then add that device in OBS as an Audio Output Capture.
- "Disconnect" makes Twitch forget the sign-in.

EXTRAS THE CARD HAS NO SWITCH FOR (Onion Board's local control API)
These need "Enable remote control" in Settings → Remote (now: {api_state}) and my key \
(Settings → Remote, click Show). The key isn't in this message: write {key} where it \
goes and remind me to replace it. I open each link once in my browser on this PC; the \
answer is JSON. The API only listens on this PC: never suggest port-forwarding it.
- Chat rules: {base}/api/chat_rules?token={key} shows them. Set any of: who may use \
each command (sound=, sounds=, random=, say=, voice=, stop=; each one of \
{", ".join(streamapi.ROLES)}), tts= (read every chat line aloud, same roles), \
user_cooldown= and cooldown= (seconds), voice_seconds= (how long !voice lasts), \
max_length=, category= (chat may only play this category), blocked= (comma-separated \
words), prefix=, reply_list=, reply_missing=. reset=1 goes back to the defaults. \
Example: {base}/api/chat_rules?say=subs&user_cooldown=60&token={key}
- Alerts: {base}/api/alerts?type=TYPE&...&token={key} with type follow, sub, resub, \
gift_sub, cheer, raid, redeem, hype_train; then sound=NAME, category=NAME (or * for \
any), say=TEXT (spoken in the computer voice; {{user}}, {{amount}}, {{message}}, \
{{reward}}, {{months}}, {{count}} are filled in), voice=NAME with voice_seconds=; \
min=AMOUNT for "only from this many bits up" (several rules per type, one per min); \
reward=TITLE for one channel point reward; clear=1 removes it. A thank-you for 100+ \
bits: {base}/api/alerts?type=cheer&min=100&sound={quote(example)}&\
say={quote("Thanks {user} for {amount} bits!")}&token={key}
- Try an alert without waiting for a viewer: {base}/api/event?type=follow&user=Test&\
test=1&token={key}
- Names must match exactly (any case) and be URL-encoded (a space is %20). A rule set \
this way shows on the card as "Something else (set with the control API)".

MY SETUP RIGHT NOW
- Twitch: {state}
- Channel point rewards:
{rewards_text}
- Alerts:
{alerts}
- Chat rules:
{chat}
- Categories: {", ".join(cfg.categories) or "(none yet)"}
- Sounds ({len(sounds)}):
{chr(10).join(names) or "- (none yet)"}

If I let viewers make it speak their own text (!say, a "say something" reward, \
tts=), remind me that whatever they type is spoken on my stream: keep it to mods or \
subs, or a channel point reward, with a cooldown and blocked words.
"""


def copy_twitch_prompt(mw) -> None:
    QApplication.clipboard().setText(twitch_prompt(mw))


class TwitchGuide(QDialog):
    """The Twitch card in plain words, step by step, with the AI prompt at the bottom."""

    def __init__(self, parent, mw):
        super().__init__(parent)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle(_("Twitch guide"))
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header(_("Twitch guide"), _label(_(
            "Your viewers can play your sounds: with <b>channel points</b>, with "
            "<b>alerts</b> when they follow, sub, cheer or raid, and with <b>!commands</b> "
            "in chat. Onion Board talks to Twitch itself, so there's no bot to set up.")),
            _bun("star")))

        steps = _label(_steps(
            _("<b>Connect.</b> Click <b>Connect Twitch</b>. A Twitch page opens: say yes "
              "to Onion Board (if it asks for a code, type the one the card shows). Keep "
              "Onion Board open while you stream (the tray is fine)."),
            _("<b>Channel points.</b> Make your rewards on Twitch first: Creator Dashboard "
              "→ Viewer Rewards → Channel Points. Then click <b>Reload rewards</b> on the "
              "card and pick a sound for each one, or <b>A random sound</b>. Channel points "
              "are only for Twitch affiliates and partners."),
            _("<b>Alerts.</b> Pick a sound for a follow, a sub, a gift sub, a cheer (bits) "
              "and a raid. Leave one on <b>Nothing</b> to skip it."),
            _("<b>Chat commands.</b> Tick <b>Chat commands</b>. Viewers type <b>!sound</b> "
              "and a sound's name, <b>!random</b>, or <b>!sounds</b> for the list, and "
              "Onion Board answers in your chat. Each viewer waits 30 seconds between "
              "commands by default, so chat can't spam you. Mods can type <b>!stop</b>."),
            _("<b>Try it.</b> Type <b>!random</b> in your own chat: you hear a sound."),
            _("<b>Let your stream hear the sounds.</b> Setup → Devices → <b>Also play "
              "on</b>: add a device set to <b>Clean, for streaming</b>, then add that device "
              "in OBS: Sources → + → <i>Audio Output Capture</i>."),
            _("<b>Want more?</b> Longer or shorter cooldowns, who may use each command, a "
              "thank-you line read out for 100 bits, a voice for a reward: click <b>Copy AI "
              "prompt</b> and paste it into ChatGPT or Claude. It knows your rewards and "
              "sounds and walks you through it.")))
        steps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.addWidget(steps)
        bl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(300)
        v.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_ai = QPushButton(_("Copy AI prompt"))
        icons.set_icon(self.btn_ai, "copy")
        self.btn_ai.setToolTip(_("A message for ChatGPT / Claude that explains the Twitch card "
                                 "and lists your rewards and sounds, so it can help you set "
                                 "it up"))
        self.btn_ai.clicked.connect(self._copy)
        row.addWidget(self.btn_ai)
        done = QPushButton(_("Done"))
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)

    def _copy(self):
        copy_twitch_prompt(self.mw)
        busy.flash(self.btn_ai, _("✓ Copied"))
        busy.toast(self, _("Copied. Paste it into ChatGPT, Claude or any AI chat and say "
                           "what you want your stream to do."), "ok")
