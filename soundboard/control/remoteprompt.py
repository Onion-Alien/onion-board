"""The control API's AI setup prompt: a message to paste into an AI assistant so it can set
up a Stream Deck, Streamer.bot, Touch Portal… (`remote` re-exports it)."""
from __future__ import annotations


# --------------------------------------------------------------------------- AI setup prompt

KEY_PLACEHOLDER = "YOUR-KEY"
PROMPT_SOUNDS = 120     # a big library: list this many names, the AI can ask for the rest


def setup_prompt(cfg, port: int, token: str = "", voices: list[str] | None = None) -> str:
    """A message to paste into ChatGPT / Claude / any AI assistant so it can walk
    someone through wiring their Stream Deck, Streamer.bot, Touch Portal… to the
    control API: what the app can do, the address, every endpoint, their own sounds,
    categories and voices, and how each common tool sends a request. Without `token`
    the key is a placeholder the person fills in themselves; `voices` (voice_names)
    is left out when the Voice tab is switched off."""
    from urllib.parse import quote

    from soundboard.control.remote import ENDPOINTS, HOST

    key = token or KEY_PLACEHOLDER
    base = f"http://{HOST}:{port}"
    sounds = list(cfg.sounds)
    names = [f"- {m.name}" + (f"  (categories: {', '.join(m.tags)})" if m.tags else "")
             for m in sounds[:PROMPT_SOUNDS]]
    if len(sounds) > PROMPT_SOUNDS:
        names.append(f"- … and {len(sounds) - PROMPT_SOUNDS} more (GET /api/sounds lists "
                     "them all)")
    example = sounds[0].name if sounds else "Airhorn"
    # a category of theirs, or none: a made-up one would answer 404
    cat = cfg.categories[0] if cfg.categories else ""
    rnd = (f"Random sound from a category: {base}/api/random?category={quote(cat)}&token={key}"
           if cat else f"Random sound (any of them): {base}/api/random?category=&token={key}")
    voice = (voices or ["Robot"])[0]
    queue = (f"\n- Play the whole \"{cat}\" category in a random order, one after another: "
             f"{base}/api/queue?category={quote(cat)}&shuffle=1&token={key}" if cat else "")
    voice_lines = (f"- Voice changer voices: {', '.join(voices)}" if voices else
                   "- Voice changer: the Voice tab is switched off in Settings → Tabs, so "
                   "/api/voice, /api/voices and /api/say answer 409 until it's back on")
    thanks = quote("Thanks {user} for {amount}!")
    endpoints = "\n".join(f"- /api/{a} — {d}" for a, d in ENDPOINTS.items())
    key_note = ("" if token else
                f"\nMy key isn't in this message: write {KEY_PLACEHOLDER} wherever it goes "
                "and remind me to replace it with the key from Settings → Remote (click "
                "Show).\n")
    return f"""\
I use Onion Board, a free Windows soundboard and voice changer. Its "Remote control" \
feature lets other programs on my PC control it over a small local HTTP API. Please help \
me set up my streaming tools to use it. Ask me first which tools I use (Stream Deck, \
Streamer.bot, Touch Portal, Bitfocus Companion, SAMMI, Mix It Up, AutoHotkey, a macro \
pad…) and what I want the buttons / triggers to do, then give me exact click-by-click \
steps for each one, with the full URLs ready to copy. If I'm not sure what I want, \
suggest a few ideas from the list below.

WHAT ONION BOARD CAN DO FROM A BUTTON
- Sounds: play one, a random one (from a category), the last one again, queue one up \
after the one playing, or play a whole category in a row; stop one or all; pause.
- Live speed, pitch and effects (bass, echo, reverb, muffle, crunch…) on every sound.
- A panic button: the Live / Muted switch (Muted: nobody hears my sounds; my plain \
mic still goes out unless the voice changer is on or Send my mic is off).
- The voice changer: on / off, or straight to a named voice (Chipmunk, Robot…).
- Text to speech: a typed line spoken for others in the computer voice (through the \
voice changer if it's on).
- "Hear what they hear": I hear my own mic the way others do, to check my voice.
- The instant replay: save the last seconds I heard as a new sound.
- Who's listening: the sound mode (Game, Voice chat, Clean, Advanced) that shapes my \
sounds for a game or voice chat.
- The Radio tab: play / stop a station, a random one, star it, its volume, whether \
others hear it.
- The Apps tab: send one program's sound (Spotify, a browser…) to whoever's \
listening, and its volume.
- All hotkeys off / on (to type in chat), and "mute my mic while a sound plays".
- Chat commands: a bot passes every chat line to /api/chat and Onion Board runs \
!sound <name>, !sounds, !random, !say, !voice and !stop by itself, with cooldowns, who \
may use each (everyone, subs, VIPs, mods), a category chat is limited to and blocked \
words (/api/chat_rules); it answers a "reply" line for the bot to post back. It can \
also read every chat line aloud.
- Alerts and donations: follows, subs, gift subs, bits, raids, tips / donations, \
channel points, TikTok gifts… sent to /api/event play a sound, a random one from a \
category, say a line ("Thanks {{user}} for {{amount}}!") or put on a voice for some \
seconds, per type and per amount (/api/alerts). Streamer.bot, Firebot, Mix It Up, \
SAMMI and TikFinity can send them; Twitch EventSub, StreamElements, Streamlabs and \
Ko-fi JSON can be POSTed as it is.
- Reading what's going on (/api/status): what's playing, what's queued, the voice, \
live / muted, the mode, the radio — handy for a key that lights up. /api/feed lists \
what chat and alerts did, for an overlay.

HOW THE API WORKS
- Address: {base}  (it only listens on this PC: tools on another computer or phone \
can't reach it, so they must run on this PC. For a phone there's a separate add-on, \
Onion Pocket, in Settings → Remote: it needs no setup)
- Every request needs my key, as ?token=KEY in the URL (simplest: works anywhere a URL \
can be opened), an X-Token: KEY header, or Authorization: Bearer KEY.
- GET or POST both work; every answer is JSON. A POST may send its values as a JSON \
object or a form instead of in the URL. The Host header must be 127.0.0.1 or \
localhost.
- Sound, category and voice names must match exactly (any case) and be URL-encoded: a \
space is %20, & is %26. A wrong sound or voice name answers 404 with "did_you_mean".
- Switches take on=1 (on), on=0 (off) or on=toggle; with no on= they toggle.
- Errors: 400 = a value it can't use, 401 = wrong / missing key, 404 = no such sound / \
category / voice / station, 409 = not ready (a sound not loaded yet, or the Voice or \
Radio tab switched off in Settings), 503 = the app was busy (safe to retry). If nothing \
answers at all, Onion Board isn't running or "Enable remote control" is off.
- Test it first by opening {base}/api/status?token={key} in a browser.
{key_note}
ENDPOINTS
{endpoints}

EXAMPLES
- Play a sound: {base}/api/play?name={quote(example)}&token={key}
- {rnd}{queue}
- Stop everything: {base}/api/stop?token={key}
- Panic button (others hear none of my sounds until pressed again): \
{base}/api/live?on=toggle&token={key}
- Voice changer on / off: {base}/api/voice?on=toggle&token={key}
- Straight to one voice: {base}/api/voice?name={quote(voice)}&token={key}
- Say a line: {base}/api/say?text=thanks%20for%20the%20follow&token={key}
- Sounds fast and squeaky: {base}/api/speed?set=1.5&token={key}, then back to normal: \
{base}/api/reset?token={key}
- Echo on every sound: {base}/api/effects?echo=0.5&token={key}  (/api/effects alone \
lists the knobs and presets)
- Sound mode for a game: {base}/api/mode?simple=game&token={key}
- Radio on / off: {base}/api/radio?on=toggle&token={key}
- Chat commands (a bot sends every chat line): \
{base}/api/chat?user=NAME&message=MESSAGE&mod=0&sub=0&token={key} — post the answer's \
"reply" back in chat when it isn't empty
- Let subs use !say, with a 60-second cooldown per viewer: \
{base}/api/chat_rules?say=subs&user_cooldown=60&token={key}
- Set what a donation does: \
{base}/api/alerts?type=donation&sound={quote(example)}&say={thanks}&token={key} \
(&min=10: only from 10 up)
- Send an alert: {base}/api/event?type=follow&user=NAME&token={key} (&test=1 to try one)
- A channel-point reward that changes my voice for 30 s: \
{base}/api/voice?name={quote(voice)}&seconds=30&token={key}

WHERE EACH TOOL SENDS A REQUEST (as far as I know — correct me if a tool has changed)
- Elgato Stream Deck app: System → Website action, paste the URL, tick "GET request in \
background" so no browser opens. (Or a free "API Request" plugin from the Marketplace.)
- Streamer.bot: an Action with the sub-action Core → Network → Fetch URL; triggers such \
as Twitch → Channel Reward → Reward Redemption, chat commands, cheers / bits, raids, \
follows. Fetch URL runs in the background. Its variables go in the URL too (URL-encode \
anything a viewer typed), e.g. a !say command or a "say something" reward. For chat \
commands: a Twitch → Chat Message trigger whose Fetch URL calls /api/chat with \
user=%user%&message=%rawInput% and the isModerator / isSubscriber / isVip flags; for \
alerts, each event's trigger calls /api/event?type=… with its %user% / %bits% / \
%amount% / %message% variables.
- Firebot: an "HTTP Request" effect (GET or POST) on its events and commands.
- TikFinity (TikTok LIVE): Actions → "Call webhook" pointed at /api/event with \
type=gift&user={{nickname}}&reward={{giftname}}&count={{repeatcount}}, or a sound per gift.
- StreamElements / Streamlabs / Ko-fi send their alerts to the internet, not to this \
PC: let Streamer.bot or Firebot receive them and pass them on to /api/event.
- Touch Portal: the "HTTP Get" action (or a web-request plugin).
- Bitfocus Companion: the "Generic HTTP" connection, a GET action with the full URL \
(Companion must run on this PC).
- SAMMI / Mix It Up: their "HTTP request" / "Web Request" command, GET.
- AutoHotkey v2: whr := ComObject("WinHttp.WinHttpRequest.5.1"), \
whr.Open("GET", url), whr.Send() — bound to a key.
- Anything else that can open a URL or run a command: curl -s "URL".

MY SETUP RIGHT NOW
- Port: {port}
- Categories: {", ".join(cfg.categories) or "(none yet: every sound is in All)"}
{voice_lines}
- Sounds ({len(sounds)}):
{chr(10).join(names) or "- (none yet)"}

Keep the steps beginner-friendly. Don't suggest exposing the API to the internet, \
port-forwarding it or running it on another machine: it's meant for this PC only. If I \
let viewers trigger /api/say with their own text, remind me that whatever they type is \
spoken on my stream: limit it to a channel-point reward or mods, with a cooldown.
"""
