"""The anonymous usage count: how many people use Onion Board, and which versions.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter): the version number and a random ID made on this PC, so
the same person isn't counted twice and we can follow how people use the app over time
(which tabs, which versions, whether they come back) to see what to improve.
Also a one-off "first start" (with where they
heard about the app, if they picked it on the installer's last page), and "updated" when
*Update now* installs a new version. With the daily one: which tabs were opened since the
last one (their names only). Soon after a start: how many problems there were since the
last send, as counts, never the report itself: a crash report or a freeze saved
(`crash/<version>`, `error/<version>`, `freeze/<version>`, with the error's type and
the file and line of this app's own code it happened in, e.g. `error/1.9.8/KeyError@
soundboard/audio/engine.py:1090`; also the line that called it and the library function it
was raised or stuck in, and for a freeze how long it lasted and whether the window or
another thread was busy:
never its message or anything else from the report), an error the app caught itself and
showed as a warning instead of crashing (`warned/<version>/<type>@<soundboard/…py:line>`
from `warned()`, the type and the deepest line of our own code it came from, never the
message), or the last run ending without the app closing itself
(`unclean-exit/<version>/<why>`: a hard crash, ended in Task Manager, a power cut;
exitwatch.py works out which, on this PC), or a run that died before it even started
(`startup-failed/<version>` when the breadcrumb bootmark.py leaves in main.py is still
there the next time, with the native stacks or Windows' own error for it when either is
there). Past MAX_PROBLEMS in one send, one `problems-dropped/<bucket>` says roughly
how many more. On the first start of a new version, `updated/<from>-to-<to>` (so an
update that never finished shows up as an *Update now* without one). One-off events
wait in config.json until a send takes them; at a real quit, what waits (those, and
the tabs and features used since the last daily count) is sent then, so the last
day before someone stops using the app isn't lost (at_quit). And
`uninstall/<version>` when the uninstaller removes it.
With the daily one, a rough picture of how it's used, each as a bucket or a name from a
fixed list: how long ago it was installed (`age/days-2-7`), where sounds go
(`route/mic`), how many sounds the board has and how many were played since the last
one (`sounds/11-50`, `played/1-10`), how long the app was open since then
(`open/1-3h`), how many sounds were fetched from a link or a web search since then
(`downloads/2-5`), how many times it was started since then (`launches/2-5`), the system
(`os/win11`, `os/win10`), the app's language (`lang/de`), its theme (`theme/dark`: a
built-in theme's name, else `other`), how many achievements were earned
(`achievements/3-5`) and their score (`ach-score/51-150`), and which features
were used since then (`used/voice-changer`, `used/more-tabs-added-radio`: the names
in FEATURES only; for the Triggers tab, the names the Onion Watch add-on passes to
triggershost.BoardHost.count, as `used/triggers-mode-colour`). A use is only noted
on this PC (used()); it goes with the next daily count, as a yes for that name, never
how many times. And once each,
the first steps of a new install (`step/added-sound`, `step/played-sound`,
`step/sent-to-others`), to see where new people get stuck; never for a copy that was
counted before these existed. Also once each, switching on a tab a new user starts
without (`step/added-radio-tab`, `-apps-`, `-triggers-`): sent when it happens, since
a tab opened after the first daily count waits a day, and most people trying the app
never send that one.
And when someone answers *Send feedback*'s "What would you improve?", their picks
(`improve/sounds`: names from IMPROVE only, sent with a one-off random session, not this
PC's ID), the follow-up ticks under a pick (`improve/sounds/memes`: IMPROVE_MORE only),
and what they typed under Other or Fewer bugs as dashed
words (`improve/other/more-anime-sounds`), with email addresses, links and long numbers
taken out first.
And when someone answers *Enjoying Onion Board?* (shown once ever, after a few days of heavy
use: enjoy.py), their thumb (`feedback/positive`, `feedback/negative`) and what they
typed under it as dashed words (`feedback/positive/more-meme-sounds`, other_tag), plus
`feedback/shown` and `feedback/dismissed` to see how many answer, with a one-off random
session like the improve picks.
And with the daily one, only for a streamer who ticked the Twitch card's "Let the Onion
Board developer see this channel's name" (off until then) and only while connected, that
channel's Twitch login (`twitch-channel/<login>`).
Nothing else: no name, sounds, settings, devices, games or IP address in the message
(GoatCounter sees the connection's address like any site does, and isn't sent it to
keep or look up).

On unless switched off: the installer's "Count me in" box, or Settings > Privacy &
security > Usage count (soundboard.online.net, so it also obeys Offline mode, a proxy and
Tor). Copies from before it existed start with it off: they were installed as an app
that sent nothing. A copy running from source never sends anything, and neither does
one on a PC with ONIONBOARD_NO_STATS set (the developer's own PCs and test VMs:
GoatCounter's "Ignore IPs" can't catch these sends, as they carry no IP)."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from soundboard import __version__
from soundboard.core import achievements, enjoy
from soundboard.core.usagereports import (  # noqa: F401  (usage.X keeps working)
    ALL_HELD_MARK, BUSY, GC_SWEEP_MARK, IN_DIALOG_MARK, mark_running, mark_stopped,
    MAX_PROBLEMS, MEM_HIGH, PAGING_PER_S, problems, RUNNING, startup_failed, VERSION_RE,
    _ANY_FRAME, _blocked_in, _busy, _error_tag, _ERROR_TYPE, _error_type, _freeze_tag,
    _INNER, _lasted, _memory, _OUR_FILE, _OUR_FRAME, _ours, _report_event, _tb_where,
    _where)
from soundboard.core.usagetags import (  # noqa: F401  (usage.X keeps working)
    ach_bucket, ach_tag, age_bucket, bucket, DL_SITES, download_bucket, download_site,
    HEARD, HEARD_ALIASES, HEARD_MAX, heard_tag, launch_bucket, open_bucket, os_tag,
    OTHER_MAX, other_tag, score_bucket, theme_tag, user_tag, _DL_HOSTS, _wordlike)
from soundboard.online import net, netlog

log = logging.getLogger(__name__)

FEATURE = "usage_stats"   # its switch in Settings > Privacy & security (soundboard.online.net)
ENDPOINT = "https://onionalien.goatcounter.com/api/v0/count"
# a key that can only add counts (GoatCounter's "Record pageviews" permission), not
# read or change anything; "" sends nothing
TOKEN = "1mdp7aoiksvjn2e3oitmjdaqd1u33msk6p74g7samuec2tufwr"  # gitleaks:allow (count-only)
EVERY_S = 24 * 3600
TIMEOUT_S = 15
# the tabs whose use is counted (tabcontrol.TAB_KEYS); anything else is never sent
TABS = ("sounds", "radio", "apps", "triggers", "voice", "setup", "store")
# the Onion Watch add-on's feature names (onionwatch/usage.py USED + SET_UP)
TRIGGERS_FEATURES = (
    "watching", "went-off", "test", "cut-from-window", "picture-file", "paste-picture",
    "area-trigger", "duplicate", "pick-windows", "pack-export", "pack-import",
    "history", "restore-deleted",
    "mode-appear", "mode-vanish", "mode-change", "mode-still", "mode-colour", "ring",
    "several-places", "every-copy", "area", "hold", "quiet-in-front", "own-interval",
    "categories", "profiles", "view-pads", "view-cards")
# the Voice tab's tabs (ui/voice/voicepanel.py VoicePanel._section keys)
VOICE_TABS = ("fx", "ai", "speak", "addons")
# The Mic effect card's actions (ui/setup/audiorecovery.py; "cleanup-none" counts as cleanup)
RECOVERY = ("install", "repair", "update", "reinstall", "cleanup", "remove")
# why a mic effect set-up failed, a click's or the repair-by-itself's (directmic.FAIL_KINDS:
# the admin prompt unanswered, the step not starting or stopping half-way, a silent mic,
# the helper not answering, no mic (and why: unplugged or off, two alike, unknown to
# Windows), no effect, the admin step's exit code 1-6, 8 or 9, or another)
MIC_FAILS = ("unanswered", "no-start", "stuck", "silent", "no-helper", "no-mic",
             "no-mic-off", "no-mic-unsure", "no-mic-gone", "no-effect", "code-1", "code-2",
             "code-3", "code-4", "code-5", "code-6", "code-8", "code-9", "code-other")
# exit code 1 (the admin step raised): where in it (or that it logged nothing), what
# Windows said (or, with no error number, the kind of error) and its error number
# (directmic RAISED_WHERE / RAISED_WHAT / RAISED_ERR, read back from its log)
MIC_RAISED = ("at-register", "at-mic-settings", "at-ring", "at-files", "at-audio",
              "at-rights", "at-other", "at-unlogged", "denied", "in-use", "missing",
              "type", "value", "key", "attr", "index", "runtime", "assert", "os",
              "timeout", "memory", "other",
              "err-2", "err-3", "err-5", "err-32", "err-33", "err-87", "err-1224",
              "err-1314", "err-other", "err-none")
# exit code 6 (Windows' audio wouldn't stop): which of its services was still up, that
# it couldn't tell, or that the step logged nothing (directmic STUCK_WHICH, read back
# from the admin log)
MIC_STUCK = ("audio", "builder", "both", "unknown", "other", "unlogged")
# why a download from a link or search failed (errors.download_reason): the kind only
DL_FAILS = ("private", "age", "bot", "members", "region", "gone", "no-formats", "429",
            "403", "5xx", "stalled", "timeout", "cut-off", "offline", "proxy", "sign-in",
            "too-big", "no-downloader", "other")
# why the mic effect still wasn't working when the wait after its set-up ran out
# (statuscontrol._no_load_why): sent elsewhere since, Windows took it off, not on the
# mic, the board's sending into it not open, or open but the effect never ran
MIC_NO_LOAD = ("off-route", "wiped", "not-on", "no-stream", "not-running")
# a pad's "On press" modes other than the default (library.MODES, without "restart")
PRESS_MODES = ("overlap", "toggle", "solo", "queue")
# the add-ons with install steps (their module.json id); any other is "other"
ADDONS = ("ai-voices", "live-voice", "other")
# why an add-on's install failed (modules._install): add-ons switched off, no Python
# for it (pyget), a step that wouldn't start, its venv / pip / model download step
# failing, another step, a step stopped for taking too long (the model download's
# apart), or an error in the app itself
ADDON_FAILS = ("off", "python", "run", "venv", "pip", "download", "step", "timeout",
               "download-timeout", "other")
# the free sound packs (soundboard.sounds.packs BUILT_IN ids); any other is "other"
PACKS = ("streamer", "esports", "general", "podcast", "halloween", "gm-starter", "other")
# the Live controls' tabs (ui/voice/livesetups.py)
LIVE_TABS = ("sounds", "radio", "apps")
# the Live controls' sliders and switches (ui/sounds/speedpitch.py; the effects by their
# livefx.PARAMS keys, "crunch" being Distortion)
LIVE_CONTROLS = ("speed", "pitch", "keep-pitch", "redline", "reset",
                 *(f"fx-{k}" for k in ("bass", "treble", "muffle", "reverb", "echo", "crunch")))
# their effect presets (audio/livefx.py PRESETS, as dashed words); any other is "other"
LIVE_PRESETS = ("bass-boosted", "blown-out", "concert-hall", "canyon", "underwater",
                "phone-call", "other")
# what was done to a Voice tab recording or an Apps tab saved clip (ui/apps/clipshelf.py)
CLIP_ACTIONS = ("play", "mic", "add", "copy", "delete")
# Bun's games (ui/bun/bunpong.py games()); any other is "other"
BUN_GAMES = ("pong", "draw", "rps", "ttt", "other")
# the rare loading screens (ui/bun/splashacts.py RARES' keys)
SPLASH_RARES = ("gold", "ice", "galaxy", "rainbow")
# Settings' pages (settings.SettingsDialog's page keys, without Show advanced)
SETTINGS_PAGES = ("audio", "appearance", "hotkeys", "tabs", "general", "about",
                  "overlay", "privacy", "connection", "data", "updates", "help",
                  "remote", "achievements")
# what else is counted, only ever these names (see the docstring)
FEATURES = ("add-files", "youtube", "record", "clip", "clip-editor", "import-board",
            "voice-changer", "text-to-speech", "hotkeys", "phone-remote", "also-send",
            # + More tabs: opened it, added a tab from it, or closed it adding none; and
            # a tab hidden from its right-click menu
            "more-tabs-opened", "more-tabs-closed",
            *(f"more-tabs-added-{k}" for k in ("radio", "apps", "triggers", "voice", "store")),
            *(f"tab-hidden-{k}" for k in ("radio", "apps", "triggers", "voice", "store")),
            # the Store tab: a sound heard, added to the board, voted on, or shared
            "store-heard", "store-added", "store-voted", "store-shared",
            # its Voices: a community voice taken into yours, or one of yours shared
            "store-voice-added", "store-voice-shared",
            # the tabs the first start's last step started with, as the old "What's it
            # for?" answers (lookstep.use_for: "custom" for any other mix), or the
            # guide closed before that step; its "Set up Discord" ticked at Finish
            *(f"use-{k}" for k in ("normal", "streamer", "games", "all", "custom", "skipped")),
            "setup-discord",
            # the setup guide closed on one of its device steps (where people give up),
            # its send step skipped, finished sending or not; Bun's first-run tour of the
            # empty board shown, searched from, or skipped (ui/setup/firsttour.py)
            *(f"setup-closed-{k}" for k in ("mic", "headphones", "send", "look", "last")),
            "setup-skipped-send", "setup-finished", "setup-finished-not-sending",
            "tour-shown", "tour-searched", "tour-files", "tour-skipped", "tour-ignored",
            "tour-added", "tour-failed",
            # a tab's first-visit how-to (ui/setup/tabtours.py): shown, done, put off, or an
            # error; two put off quickly, which switches the rest off
            *(f"tour-{t}-{k}" for t in ("radio", "apps", "triggers", "voice", "store")
              for k in ("shown", "done", "skipped", "failed")),
            "tours-quit",
            # the Triggers tab's Add Onion Watch window: shown, Add clicked, closed
            "watch-prompt-shown", "watch-prompt-get", "watch-prompt-closed",
            # Get FFmpeg clicked / failed; a file that couldn't play without it
            "get-ffmpeg", "get-ffmpeg-failed", "needs-ffmpeg",
            # the link download bar: Cancel, Retry, shrunk to one line
            "dl-cancel", "dl-retry", "dl-bar-small",
            # a downloaded sound's source: Open on <site>, Copy link, Details, its info
            # deleted, and Remember where it came from switched off (features_now)
            "source-open", "source-copy-link", "source-details", "source-deleted",
            "source-off",
            # the Apps tab: a card or section dragged, a category added / renamed /
            # deleted, and own categories set up (features_now); a program's window shown
            "apps-reorder", "apps-category-added", "apps-category-renamed",
            "apps-category-deleted", "apps-own-categories", "apps-window-view",
            # Settings' search box used, and a search that found nothing
            "settings-search", "settings-search-nothing",
            # the mini player's mic mute switch; the setup guide opened from Setup; the
            # mini player turned into Bun (ui/bun/bunmode.py)
            "mini-mic-mute", "setup-guide-opened", "bun-mode",
            # the side rail: Ctrl+1-9 / Ctrl+Tab, the version clicked for What's new,
            # kept shut (features_now)
            "tab-keys", "whats-new", "rail-shut",
            # Show more under web search results, Trending on Myinstants opened; a pad's
            # Edit: Effects tab, a picture from a file or a link
            "search-show-more", "search-trending", "pad-effects", "pad-picture-file",
            "pad-picture-link",
            # the Triggers tab (the Onion Watch add-on) says which of its features were
            # used or are set up (triggershost.BoardHost.count): onionwatch/usage.py's
            # FEATURES, keep in step
            *(f"triggers-{k}" for k in TRIGGERS_FEATURES),
            # the Easter eggs, to see if anyone finds them: Pong with Bun opened, left
            # before the end, won or lost; sleepy Bun woken
            "egg-pong-opened", "egg-pong-quit", "egg-pong-won", "egg-pong-lost",
            "egg-bun-woken",
            # sounds fetched from a link or a web search (ui/sounds/linkbar.py): the site
            # (DL_SITES), a pasted link or a search pick, Add as sound or Play once, one
            # waiting in the queue, a pick already in the library, and the sites that
            # failed. Never the link, title or search words
            *(f"dl-{k}" for k in DL_SITES),
            "dl-link", "dl-search", "dl-add", "dl-play", "dl-queue", "dl-already-have",
            *(f"dl-failed-{k}" for k in DL_SITES), *(f"dl-failed-why-{k}" for k in DL_FAILS),
            # a failed download that worked when tried again by itself (ytdl.download_audio)
            "dl-retried-ok",
            # FFmpeg got by the app itself while it loads (not a click), and that failing
            "get-ffmpeg-auto", "get-ffmpeg-auto-failed",
            "ffmpeg-broken", "ffmpeg-recovered",
            # the mic effect: put on by a click, put back by itself after Windows took it
            # off, updated; No to Windows' admin prompt; a click's set-up failed; the
            # fix-by-itself failed; on, but not working when the wait ran out; Windows took
            # it off (found by the app); and the mic helper set up (features_now); and
            # why a set-up or the fix-by-itself failed (MIC_FAILS: a fixed word, never
            # the message)
            "mic-effect-on", "mic-effect-fixed", "mic-effect-updated", "mic-effect-said-no",
            "mic-effect-failed", *(f"mic-effect-failed-{k}" for k in MIC_FAILS),
            "mic-effect-fix-failed", *(f"mic-effect-fix-failed-{k}" for k in MIC_FAILS),
            "mic-effect-no-load", *(f"mic-effect-no-load-{k}" for k in MIC_NO_LOAD),
            "mic-effect-taken-off", "mic-helper",
            *(f"mic-effect-code-1-{k}" for k in MIC_RAISED),
            *(f"mic-effect-code-6-{k}" for k in MIC_STUCK),
            # the helper's step raised and Windows' prompt was asked instead, and where
            # the helper's raised (MIC_RAISED)
            "mic-effect-helper-fallback",
            *(f"mic-effect-helper-code-1-{k}" for k in MIC_RAISED),
            # Onion Board's own update: the download cancelled or failed, the installer
            # wouldn't start, Copy error, Later at "Restart now", one that didn't finish,
            # one installing itself as the app started
            "update-cancelled", "update-download-failed", "update-install-failed",
            "update-copy-error", "update-later", "update-didnt-finish", "update-auto",
            # On Air switched off / on by a click, a line of the On Air card clicked; a
            # proxy, Tor or Offline mode set (features_now)
            "on-air-off", "on-air-on", "on-air-line", "net-proxy", "net-tor", "net-offline",
            # the playing sound's picture behind the board (features_now)
            "playing-bg",
            # the Voice tab's own tabs clicked (VOICE_TABS); Speak in switched on
            *(f"voice-tab-{k}" for k in VOICE_TABS), "translate-on",
            # Radio: a station played, a station that wouldn't play, the list down
            "radio-played", "radio-failed", "radio-list-down",
            # Settings' Mic effect card: what was run on a mic, and it failing
            *(f"recovery-{k}" for k in RECOVERY), "recovery-failed",
            # a file import stopped from its card; an import that skipped some files
            "import-stopped", "import-skipped",
            # Pause and Stop all (the side menu, a hotkey), and the taskbar preview's
            # buttons; a sound set to a press mode other than the default one at a time
            # (features_now, SoundMeta.mode)
            "pause", "stop-all", "taskbar-buttons",
            *(f"press-{k}" for k in PRESS_MODES),
            # an add-on with install steps (ADDONS) set up or failing to (and why:
            # ADDON_FAILS), Repair, and a Python got for it (soundboard.online.pyget)
            # or that failing
            *(f"addon-installed-{k}" for k in ADDONS), *(f"addon-failed-{k}" for k in ADDONS),
            *(f"addon-failed-{k}-{r}" for k in ADDONS for r in ADDON_FAILS),
            "addon-repaired", "addon-got-python", "addon-python-failed",
            # a restore point saved before an update; a restore point put back
            "restore-point-update", "restore-point-used",
            # unticking Others hear it while the mic effect isn't on: the pop-up saying it
            # can't mute yet, and its Set it up
            "mute-warning-shown", "mute-warning-setup",
            # the voice changer: a group or Favorites picked, a voice starred, Make it
            # yours opened, Randomize, Save as a voice, a share code copied or imported
            "voice-group", "voice-favorite", "voice-tweak", "voice-random", "voice-saved",
            "voice-code-shared", "voice-code-imported",
            # the Random voice card (or its key) and a voice changer voice's Hear it
            "voice-roll", "voice-hear",
            # the voice bar's Effects pop-up opened
            "voice-effects",
            # AI voices: switched on, a group picked, a voice starred, Hear it, one of
            # your own made (never which voice)
            "ai-voice", "ai-voice-group", "ai-voice-favorite", "ai-voice-hear",
            "ai-voice-made",
            # Free packs: the window opened, a sample heard, a pack added (PACKS)
            "packs-opened", "pack-heard", *(f"pack-added-{k}" for k in PACKS),
            # a custom colour from the colour wheel (a pad or a group of them)
            "custom-colour",
            # Settings: Show advanced opened, which pages were looked at (SETTINGS_PAGES)
            "settings-advanced", *(f"settings-page-{k}" for k in SETTINGS_PAGES),
            # yt-dlp's Update now, Reinstall, Force update, and one failing
            "ytdlp-update", "ytdlp-reinstall", "ytdlp-force", "ytdlp-failed",
            # the mic card saying the headset is unplugged, or the mic sends silence
            # (also right after a set-up)
            "mic-unplugged", "mic-silent", "mic-silent-after-setup",
            # the mic check after a set-up (micprobe): its test sound heard in the mic,
            # missing, can't tell; another app's mic cut off by the set-up
            "mic-probe-heard", "mic-probe-missing", "mic-probe-unsure", "mic-probe-app-cut-off",
            # a sound played at 0% Sounds volume (the warning), its Set to 100%; a
            # hotkey no keyboard can press or Windows keeps (Win+L) refused
            "sound-vol-0", "sound-vol-0-fixed", "hotkey-refused",
            # Cards or a list (features_now): the Sounds, Apps or Voice tab set to a list
            *(f"view-list-{k}" for k in ("sounds", "apps", "voice")),
            # hotkeys: the game no longer gets the key (Settings), a key for a voice, auto
            # push-to-talk's key set (all features_now)
            "hotkeys-share-off", "voice-hotkeys", "auto-ptt",
            # the voice leveler switched off; a sound with a voice laid over it, an AI
            # voice among them (all features_now)
            "voice-leveler-off", "sound-voice", "sound-ai-voice",
            # Live controls: a setup picked for sounds, the radio or programs (LIVE_TABS),
            # one speaking in another language; Not now on its "may take a while"
            # question; one cancelled while it got ready
            *(f"live-setup-{k}" for k in LIVE_TABS), "live-setup-language",
            "live-setup-said-no", "live-setup-cancel",
            # the Voice tab's setups: one saved, one renamed
            "voice-setup-saved", "voice-setup-renamed",
            # the Up next chip opened, its Clear, a row played now or dragged; the Live
            # switch's "muted a long time" ring
            "upnext-opened", "upnext-cleared", "upnext-play-now", "upnext-reordered",
            "muted-ring",
            # the tray's Voice changer menu: switched on / off, or a voice picked
            "tray-voice-toggle", "tray-voice-pick",
            # What's new shown by itself after an update, and its Settings button
            "whats-new-shown", "whats-new-page",
            # Bun's games: which one was opened (BUN_GAMES; egg-pong-opened is any game)
            *(f"egg-game-{k}" for k in BUN_GAMES),
            # the Store tab's order (Trending is the default) and a category picked
            "store-sort-new", "store-sort-top", "store-sort-trending", "store-category",
            # the voice changer's Background on, with board sounds in it (features_now)
            "voice-background", "voice-background-sounds",
            # a category hidden from All (features_now); a My voice combos share code copied
            "hidden-from-all", "setup-code-shared",
            # the control API / a phone remote add-on actually answered a request; the
            # API's chat commands and alerts set up (features_now) and used: a chat
            # command, an alert, a donation's alert (never who, what or how much)
            "remote-used-api", "remote-used-phone", "api-chat-rules", "api-alerts",
            "api-chat-command", "api-alert", "api-alert-donation",
            # a rare loading screen came up (ui/bun/splashacts.py RARES: Golden, Ice, Galaxy,
            # Rainbow Bun); Bun or Hoot clicked into saying a line
            *(f"splash-{k}" for k in SPLASH_RARES), "bun-talk", "hoot-talk",
            # a game run as admin in front with hotkeys set: the note, its Restart as admin
            "admin-game", "admin-restart",
            # the red "didn't work" card (ui/kit/oops.py): Try again, Report a problem
            "oops-retry", "oops-report",
            # the Community tab's "store's down" page, and its down-for-maintenance one; a
            # web search's site down or turning requests away; a web search that failed
            # and why (DL_FAILS, as a download's)
            "store-down", "store-maintenance", "search-site-down",
            "search-failed", *(f"search-failed-why-{k}" for k in DL_FAILS),
            # the setup guide's "almost done" note (closed while the mic is set up); the
            # cable's "only if you need it" box, and its Use my mic instead
            "setup-wait-note", "cable-confirm", "cable-confirm-mic",
            # the Voice tab saying no mic is open; one voice bar chip's close button
            "voice-no-mic", "voice-chip-off",
            # the Voice tab's Voices ON / OFF switch; a voice bar chip clicked on or off
            "voices-master", "voice-chip-toggle",
            # a background sound's ▶ heard before adding it; the mini player's Full board
            "voice-background-hear", "mini-full-board",
            # a deleted category's Undo; a sound played while muted (the note), its Go live
            "category-undo", "muted-note", "muted-go-live",
            # Plain instead of Textured (features_now)
            "textures-off",
            # Live controls (ui/sounds/speedpitch.py): opened, and changed while open, on
            # the Sounds tab, the radio or the programs (LIVE_TABS); which control
            # (LIVE_CONTROLS) or preset (LIVE_PRESETS): names only, never the values
            *(f"live-opened-{k}" for k in LIVE_TABS), *(f"live-changed-{k}" for k in LIVE_TABS),
            *(f"live-{k}" for k in LIVE_CONTROLS), *(f"live-preset-{k}" for k in LIVE_PRESETS),
            # Settings > Achievements: one earned (achieved(): its id, from the fixed list in
            # core/achievements.py), the filters used; pop-ups or their chime on
            # (features_now)
            *(f"ach-{a.id.replace('_', '-')}" for a in achievements.ALL),   # (ach_tag)
            "achievements-filter",
            "achievement-popups", "achievement-chime",
            # Lite mode on, Use less CPU picked by hand on or off (features_now); a slower
            # PC's Lite mode hint shown, and its Turn on
            "lite-mode", "light-voice-on", "light-voice-off", "lite-suggested",
            "lite-suggested-on",
            # Connect Twitch: signed in (features_now), Connect clicked, the sign-in
            # failing; a chat line or another event (an alert, channel points) from
            # Twitch; its step-by-step guide, its Copy AI prompt
            "twitch-connected", "twitch-login", "twitch-login-failed", "twitch-chat",
            "twitch-event", "twitch-guide", "twitch-prompt-copied",
            # the Voice tab's recordings and the Apps tab's saved clips: what was done to
            # one (CLIP_ACTIONS: played, sent through the mic, added to Sounds, copied,
            # deleted)
            *(f"voice-rec-{k}" for k in CLIP_ACTIONS), *(f"saved-clip-{k}" for k in CLIP_ACTIONS),
            # a voice searched for (never the words); the Stream Deck plugin answered;
            # Play next on a Community tab card; Edit sound's Reset effects
            "voice-search", "remote-stream-deck", "store-play-next", "pad-effects-reset",
            # Windows started the app again after it crashed or hung
            "crash-restarted",
            # the onion on Settings > About: poked, ate the window, given back early
            "egg-onion-poked", "egg-onion-eaten", "egg-onion-please")
STEPS = ("added-sound", "played-sound", "sent-to-others",
         # a tab a new user starts without (+ More tabs, Settings > Tabs)
         "added-radio-tab", "added-apps-tab", "added-triggers-tab")
ROUTES = ("cable", "device", "off", "mic")   # library.ROUTES
# the Apps tab's own categories (ui/apps/approw.py APP_CATEGORIES + "Other"): any other
# name in Config.apps_categories is one the user made (counted as apps-own-categories)
APPS_BUILT_IN = ("Browsers", "Music & media", "Calls & chat", "Games", "Other")
# the feedback box's "What would you improve?" picks (ui/kit/feedbackdialog.py)
IMPROVE = ("sounds", "setup", "voice-chat", "voice-changer", "speed", "looks", "bugs",
           "other")
# the follow-up ticks that open under a pick ("More sounds" > "Memes"), sent as
# improve/<pick>/<name>; only these names
IMPROVE_MORE = {
    "sounds": ("memes", "music", "game", "reactions", "voice-lines"),
    "setup": ("others-hear-me", "pick-mic", "hotkeys", "install"),
    "voice-chat": ("discord", "in-game", "calls", "streaming"),
    "voice-changer": ("more-voices", "more-real", "less-delay", "ai-voices"),
    "speed": ("starts-slow", "heavy", "lags-games", "stutters"),
    "looks": ("crowded", "hard-to-find", "themes", "text-size"),
}
BUGS_MAX = 200   # characters of "What bugs did you hit?" (Fewer bugs opens only that)
LANG_RE = r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,4})?"
TWITCH_LOGIN_RE = r"[a-z0-9_]{1,25}"   # what Twitch allows in a login
DAY_S = 24 * 3600


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a key, not on a dev PC."""
    return (bool(TOKEN) and bool(getattr(sys, "frozen", False))
            and not os.environ.get("ONIONBOARD_NO_STATS"))


def install_id(cfg) -> str:
    """This PC's random ID (made once, kept in config.json)."""
    if not cfg.stats_id:
        cfg.stats_id = uuid.uuid4().hex
    return cfg.stats_id


def _event(name: str, sid: str) -> dict:
    return {"path": name, "title": name, "event": True, "session": sid, "ref": user_tag(sid)}


def due(sent: float, now: float) -> bool:
    """Is the daily count due: a new day on this PC's clock since the last one, or a
    whole day gone by. By the calendar, not 24 hours: someone who used it at 8 pm
    and again at 6 pm the next day counts on both days (with a 24-hour rule the
    second day went with the third, and looked like a day off)."""
    if now - sent >= EVERY_S:
        return True
    return now > sent and time.localtime(now)[:3] != time.localtime(sent)[:3]


def hits(cfg, now: float, event: str = "", extra=()) -> list[dict]:
    """What a send would say: the daily "still here" for this version if one is due
    (with "first-start" the first time ever, and the tabs opened since the last one),
    or the one `event`. `extra` (problem events) go now, due or not."""
    sid = install_id(cfg)
    if event:
        return [_event(event, sid)]
    out = [_event(e, sid) for e in extra]
    if not due(cfg.stats_sent, now):
        return out
    out.insert(0, {"path": f"/app/{__version__}", "title": f"Onion Board {__version__}",
                   "session": sid, "ref": user_tag(sid)})
    if not cfg.stats_sent:
        heard = heard_tag(cfg.stats_heard)
        out.append(_event(f"first-start/heard-{heard}" if heard else "first-start", sid))
    out += [_event(f"tab/{t}", sid) for t in cfg.stats_tabs if t in TABS]
    out += [_event(e, sid) for e in about(cfg, now)]
    login = cfg.twitch_login
    if cfg.twitch_share and cfg.twitch_token and re.fullmatch(TWITCH_LOGIN_RE, login or ""):
        # only when the streamer ticked the Twitch card's box, and only while connected
        out.append(_event(f"twitch-channel/{login}", sid))
    return out


# how long the app was open: added up every OPEN_TICK_S (open_tick); a longer gap than
# OPEN_GAP_S (the PC slept or hibernated) counts as nothing
OPEN_TICK_S = 300
OPEN_GAP_S = 600
_open_mark: float | None = None


def open_tick(cfg, now: float | None = None) -> None:
    """Add the time since the last tick to cfg.stats_open_s (for the next daily count's
    `open/`). Called at start, every OPEN_TICK_S, before a send and at quit."""
    global _open_mark
    now = time.monotonic() if now is None else now
    counting = enabled() and net.allowed(FEATURE)   # off: nothing piles up for later
    if counting and _open_mark is not None and 0 < now - _open_mark <= OPEN_GAP_S:
        cfg.stats_open_s = max(0.0, float(cfg.stats_open_s or 0)) + (now - _open_mark)
        enjoy.add(cfg, now - _open_mark)   # per day, for *Enjoying Onion Board?*
    _open_mark = now


def downloaded(cfg, url: str, via: str, kind: str, ok: bool, why: str = "") -> None:
    """A link or web-search pick finished (ui/sounds/linkbar.py): `via` "link" or "search",
    `kind` "add" or "play", `why` it failed (DL_FAILS). Counted as used() names, and one
    more for the next daily `downloads/` when it worked (only while the count is on,
    like open_tick)."""
    site = download_site(url)
    if not ok:
        used(f"dl-failed-{site}")
        used(f"dl-failed-why-{why if why in DL_FAILS else 'other'}")
        return
    for k in (site, via, kind):
        used(f"dl-{k}")
    if enabled() and net.allowed(FEATURE):
        cfg.stats_downloads = max(0, int(cfg.stats_downloads or 0)) + 1


def started(cfg) -> None:
    """At start: count this launch for the next daily count's `launches/`, and when
    another version ran here last, keep `updated/<from>-to-<to>` for the next send
    (however it was updated: *Update now*, the installer, a download). Nothing piles
    up while the count is off; the version is noted either way."""
    old, cfg.stats_version = cfg.stats_version, __version__
    if not enabled() or not net.allowed(FEATURE):
        return
    cfg.stats_launches = max(0, int(cfg.stats_launches or 0)) + 1
    if old and old != __version__ and re.fullmatch(VERSION_RE, old):
        _keep(cfg, [f"updated/{old}-to-{__version__}"])


def total_plays(cfg) -> int:
    return sum(max(0, int(getattr(m, "plays", 0) or 0)) for m in cfg.sounds)


def settle(cfg, now: float) -> None:
    """Once: when this install started, for age/. A copy counted before this existed
    (or with sounds already played) isn't a new install: its age comes from the app
    folder, and its first steps are long done, so they're never sent."""
    if cfg.stats_started:
        return
    if cfg.stats_sent or total_plays(cfg):
        born = cfg.stats_sent or now
        try:
            from soundboard.sounds.library import APP_DIR
            born = min(born, APP_DIR.stat().st_ctime)   # created, on Windows
        except (OSError, ImportError):
            pass
        cfg.stats_started = born
        cfg.stats_steps = list(STEPS)
        cfg.stats_plays = total_plays(cfg)
    else:
        cfg.stats_started = now


_used: set[str] = set()   # features used this run, kept in cfg by remember()


def addon_tag(module_id: str) -> str:
    """An add-on's id as a count's word: one of ADDONS, else "other"."""
    return module_id if module_id in ADDONS else "other"


def used(key: str) -> None:
    """Feature `key` (one of FEATURES) was used, for the next daily count (and for
    Settings > Achievements' counting)."""
    achievements.event(key)
    if key in FEATURES:
        _used.add(key)


def ffmpeg_state(cfg, state: str) -> None:
    """Remember a broken copy or failed get until a later check verifies it works.
    The marker survives daily sends and restarts; missing on a new install is normal,
    and an unknown check or a cancelled get cannot prove recovery. A check that only
    timed out ("slow") is neither: on a new install's first start the virus scan of the
    new ffmpeg.exe can outlast it, and it works a moment later. If the get it starts
    then fails, get-failed still counts. Only fixed feature
    names are counted, never a path or error message.
    On purpose, only this count's own switch (and Offline / Tor) stop it, not FFmpeg's
    download switch: the check that finds a broken copy is local, so with that switch off
    a broken copy still counts, no get runs (so no get-failed), and a copy the user fixes
    themselves still counts as recovered on the next check.
    """
    if not enabled() or not net.allowed(FEATURE) or net.mode() == net.TOR:
        cfg.stats_ffmpeg_failed = False
        return
    if state == "slow":
        return
    if state in ("broken", "get-failed"):
        cfg.stats_ffmpeg_failed = True
        if state == "broken":
            used("ffmpeg-broken")
    elif state == "ok" and cfg.stats_ffmpeg_failed:
        used("ffmpeg-recovered")
        cfg.stats_ffmpeg_failed = False


def remember(cfg) -> None:
    """Keep this run's used() features in cfg (so they survive a quit before the
    next daily count)."""
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    new = [k for k in FEATURES if k in _used and k not in have]
    _used.clear()
    if new:
        cfg.stats_used = [*have, *new]
    if _pending:   # note()d events: kept in cfg too, so a quit before the send keeps them
        taken = _pending[:]
        del _pending[:len(taken)]
        _keep(cfg, taken)


def features_now(cfg) -> list[str]:
    """Features that are set up, counted as used every day they are."""
    out = []
    if any(getattr(m, "hotkey", "") for m in cfg.sounds) or cfg.category_hotkeys:
        out.append("hotkeys")
    if cfg.remote_addons or cfg.api_enabled:
        out.append("phone-remote")
    stream = cfg.api_stream if cfg.api_enabled and isinstance(cfg.api_stream, dict) else {}
    if stream.get("chat"):
        out.append("api-chat-rules")
    if stream.get("alerts") and stream.get("alerts_on", True) is not False:
        out.append("api-alerts")
    if cfg.hidden_from_all:
        out.append("hidden-from-all")
    fx = cfg.voice_fx if isinstance(cfg.voice_fx, dict) else {}
    bg = (fx.get("effects") or {}).get("backdrop") if fx.get("enabled") else None
    if isinstance(bg, dict) and bg.get("on"):
        from soundboard.voicefx import backdrop
        if bg.get("sounds") or any(_positive(bg.get(k)) for k in backdrop.LAYERS):
            out.append("voice-background")
        if bg.get("sounds"):
            out.append("voice-background-sounds")
    if cfg.also_send:
        out.append("also-send")
    if not cfg.theme_texture:
        out.append("textures-off")
    from soundboard.online import quality
    if not quality.current.keep_source:
        out.append("source-off")
    if set(cfg.apps_categories or ()) - set(APPS_BUILT_IN):
        out.append("apps-own-categories")
    if not cfg.sidebar_open:
        out.append("rail-shut")
    if cfg.net_mode in ("proxy", "tor"):
        out.append(f"net-{cfg.net_mode}")
    if cfg.net_offline:
        out.append("net-offline")
    if cfg.playing_background:
        out.append("playing-bg")
    modes = {getattr(m, "mode", "") for m in cfg.sounds}
    out += [f"press-{k}" for k in PRESS_MODES if k in modes]
    for key, view in (("sounds", cfg.pad_view), ("apps", cfg.app_view),
                      ("voice", cfg.voice_view)):
        if view == "list":
            out.append(f"view-list-{key}")
    if not cfg.hotkeys_share:
        out.append("hotkeys-share-off")
    if cfg.voice_hotkeys:
        out.append("voice-hotkeys")
    if cfg.ptt_key:
        out.append("auto-ptt")
    if not cfg.voice_level:
        out.append("voice-leveler-off")
    voices = [(getattr(m, "fx", None) or {}).get("voice") for m in cfg.sounds]
    voices = [v for v in voices if isinstance(v, dict) and v]
    if voices:
        out.append("sound-voice")
    if any(v.get("ai") for v in voices):
        out.append("sound-ai-voice")
    if cfg.lite_mode:
        out.append("lite-mode")
    if cfg.light_voice in ("on", "off"):   # picked by hand ("auto" follows Lite mode)
        out.append(f"light-voice-{cfg.light_voice}")
    if cfg.twitch_token:
        out.append("twitch-connected")
    if cfg.achievement_popups:
        out.append("achievement-popups")
        if cfg.achievement_sound:
            out.append("achievement-chime")
    from soundboard.mic import michelper
    if cfg.route == "mic" and michelper.known():   # its last check's answer, no new one
        out.append("mic-helper")
    return out


def _positive(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def achieved(ach_id: str) -> None:
    """An achievement was earned (core/achievements.py): its id, for the next daily count.
    Ids not in its fixed list (a newer version's) are never sent."""
    if ach_id in achievements.BY_ID:
        used(ach_tag(ach_id))


def live_preset_tag(name: str) -> str:
    """A Live controls effect preset's name as a count's word ("Bass boosted" ->
    bass-boosted); one not in LIVE_PRESETS is "other"."""
    tag = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return tag if tag in LIVE_PRESETS else "other"


def game_tag(name: str) -> str:
    """A Bun game's name as a count's word: one of BUN_GAMES, else "other"."""
    return name if name in BUN_GAMES else "other"


def pack_tag(pack_id: str) -> str:
    """A free pack's id as a count's word: one of PACKS, else "other" (a pack from
    the online list that's newer than this version)."""
    return pack_id if pack_id in PACKS else "other"


def about(cfg, now: float) -> list[str]:
    """The daily count's picture of how it's used (see the docstring): buckets and
    names from fixed lists only."""
    out = [f"age/{age_bucket((now - (cfg.stats_started or now)) / DAY_S)}"]
    if cfg.route in ROUTES:
        out.append(f"route/{cfg.route}")
    out.append(f"sounds/{bucket(len(cfg.sounds))}")
    out.append(f"played/{bucket(total_plays(cfg) - cfg.stats_plays)}")
    out.append(f"open/{open_bucket(cfg.stats_open_s or 0)}")
    out.append(f"downloads/{download_bucket(cfg.stats_downloads or 0)}")
    lang = cfg.language if re.fullmatch(LANG_RE, cfg.language or "") else "auto"
    out.append(f"lang/{lang}")
    out.append(f"theme/{theme_tag(cfg.theme)}")
    out.append(f"os/{os_tag()}")
    out.append(f"launches/{launch_bucket(cfg.stats_launches or 0)}")
    got = cfg.achievements.get("got") if isinstance(cfg.achievements, dict) else None
    got = got if isinstance(got, dict) else {}
    out.append(f"achievements/{ach_bucket(len(got))}")
    score = sum(achievements.points(a) for a in achievements.ALL if a.id in got)
    out.append(f"ach-score/{score_bucket(score)}")
    have = (set(cfg.stats_used if isinstance(cfg.stats_used, list) else [])
            | set(features_now(cfg)))
    out += [f"used/{k}" for k in FEATURES if k in have]
    return out


def tab_opened(cfg, key: str) -> None:
    """Remember that tab `key` was opened, for the next daily count."""
    tabs = cfg.stats_tabs if isinstance(cfg.stats_tabs, list) else []
    if key in TABS and key not in tabs:
        cfg.stats_tabs = [*tabs, key]


_pending: list[str] = []   # an unclean exit found at start, for the next send
MAX_PENDING = 20           # one-off events kept in cfg.stats_pending while unsent


def note(event: str) -> None:
    """Send `event` with the next count (any thread: remember() moves it into cfg)."""
    if event:
        _pending.append(event)


def _keep(cfg, events) -> None:
    """Keep one-off events in cfg.stats_pending until a send takes them."""
    have = [e for e in (cfg.stats_pending if isinstance(cfg.stats_pending, list) else [])
            if isinstance(e, str)]
    cfg.stats_pending = [*have, *(e for e in events if e)][:MAX_PENDING]


_warned: set[str] = set()   # reportable problems handled this run, for warned()


def warned(e: BaseException) -> None:
    """The app caught an error it couldn't fix and showed the user itself, as a warning
    instead of a crash (errors.warn / errors.html): count that it happened, once per
    distinct (type, place) per run, as `warned/<version>/<type>@<soundboard/…py:line>`
    -- the type and the deepest line of our own code it came from (like error/ events),
    never its message (a message can hold a path, a device or a user name). A string
    problem (no traceback) isn't counted."""
    if not isinstance(e, BaseException):
        return
    where = _tb_where(e.__traceback__)
    key = f"{type(e).__name__}@{where}" if where else type(e).__name__
    if key in _warned:
        return
    _warned.add(key)
    note(f"warned/{__version__}/{key}")


def uninstall_event() -> str:
    return f"uninstall/{__version__}"


OPT_OUT_WHERE = ("installer", "settings")
OPT_OUT_TIMEOUT_S = 5   # the installer waits on it: never long


def opt_out(where: str) -> bool:
    """Count me in switched from on to off (`where`: the installer's box or Settings):
    one last "opt-out/<where>" so we know how many people aren't counted, then nothing
    ever again. No random ID, no tag, no session: it can't be tied to anything they
    sent before. Only while the count is still allowed (call it before switching it
    off), and never in Tor mode (SECURITY.md). Waits for the answer: call it off the
    UI thread."""
    if (where not in OPT_OUT_WHERE or not enabled() or not net.allowed(FEATURE)
            or net.mode() == net.TOR):
        return False
    name = f"opt-out/{where}"
    netlog.cause(FEATURE, f"Anonymous usage count ({name}, the last one)")
    return send([{"path": name, "title": name, "event": True}],
                timeout=OPT_OUT_TIMEOUT_S, no_sessions=True)


def update_event(to: str) -> str:
    """The event for *Update now* from this version to `to`."""
    return f"update-now/{__version__}-to-{to}"


MAX_HITS = 100   # GoatCounter's most per request: a longer list goes in parts


def send(payload: list[dict], timeout: float = TIMEOUT_S, no_sessions: bool = False) -> bool:
    """POST them to the counter, MAX_HITS at a time. True if it took them all (it stops
    at the first part it didn't take). Call off the UI thread."""
    for i in range(0, max(len(payload), 1), MAX_HITS):
        if not _send_part(payload[i:i + MAX_HITS], timeout, no_sessions):
            return False
    return True


def _send_part(payload: list[dict], timeout: float, no_sessions: bool) -> bool:
    body = json.dumps({"hits": payload, "no_sessions": True} if no_sessions
                      else {"hits": payload}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
        "User-Agent": "OnionBoard"})
    try:
        with net.urlopen(req, timeout=timeout, feature=FEATURE) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, switched off meanwhile, counter down
        log.info("usage count not sent: %s", e)
        return False


MEMORY_FULL = 90   # % of the PC's memory in use from which the count waits


def _memory_full() -> bool:
    """The PC is short of memory: Windows is swapping to disk, and even starting the
    count's thread could stall the window for many seconds. A PC that stays this full
    all day goes uncounted: fine, the count never slows anyone down."""
    from soundboard.core import hangwatch
    load = hangwatch.memory_load()
    return load is not None and load >= MEMORY_FULL


def maybe_send(cfg, on_sent=None, event: str = "", app_dir: Path | None = None) -> None:
    """The daily count if it's due (or `event` now), on a thread, when it's allowed.
    Problems since the last send go too, due or not: note()d ones, and with `app_dir`
    the reports saved there.

    The thread only sends what was gathered here; cfg belongs to the UI thread, which
    keeps adding to the same stats_* fields (tab_opened, downloaded, remember). Once a
    count (not an `event`) went, `on_sent(apply)` is called on that thread: the caller
    runs apply() on the thread that owns cfg (the main window queues it to the UI
    thread), and apply clears exactly what was sent, keeping anything added meanwhile.
    Without on_sent, apply runs right there (a caller with no UI thread)."""
    if not enabled() or not net.allowed(FEATURE):
        return
    if not event and _memory_full():   # a later check sends it; an event goes anyway
        return
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    extra, taken, newest = ([], [], 0.0) if event else _waiting(cfg, now, app_dir)
    open_tick(cfg)
    payload = hits(cfg, now, event, extra)
    if not payload:
        return
    daily = not event and not payload[0].get("event")
    tabs = [h["path"][4:] for h in payload if h["path"].startswith("tab/")]
    feats = [h["path"][5:] for h in payload if h["path"].startswith("used/")]
    plays = total_plays(cfg)
    opened = cfg.stats_open_s or 0
    launches = cfg.stats_launches or 0
    downloads = cfg.stats_downloads or 0
    netlog.cause(FEATURE, "Anonymous usage count" + (f" ({event})" if event
                                                     else " (once a day)" if daily
                                                     else " (problems)"))

    def apply():   # on the thread that owns cfg: only what this count took
        if daily:
            cfg.stats_sent = now
            cfg.stats_tabs = [t for t in cfg.stats_tabs if t not in tabs]
            cfg.stats_used = [k for k in cfg.stats_used if k not in feats]
            cfg.stats_plays = plays
            cfg.stats_open_s = max(0.0, (cfg.stats_open_s or 0) - opened)   # since then
            cfg.stats_launches = max(0, (cfg.stats_launches or 0) - launches)
            cfg.stats_downloads = max(0, (cfg.stats_downloads or 0) - downloads)
        cfg.stats_pending = _without(cfg.stats_pending, taken)
        cfg.stats_problems_seen = max(cfg.stats_problems_seen, newest)

    def run():   # the network only: never touches cfg
        if send(payload) and not event:
            (on_sent or (lambda f: f()))(apply)
    threading.Thread(target=run, daemon=True, name="usage-count").start()


def _waiting(cfg, now: float, app_dir: Path | None) -> tuple[list[str], list[str], float]:
    """The one-off and problem events waiting for a send: (the events, the ones taken
    from cfg.stats_pending, the newest report's time). Call after remember()."""
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    extra = list(cfg.stats_pending)   # remember() just made it a clean list
    taken = extra[:]
    skipped, newest = [0], 0.0
    if app_dir is not None:
        found, newest = problems(app_dir, cfg.stats_problems_seen, skipped)
        extra += found
    dropped = skipped[-1] + max(0, len(extra) - MAX_PROBLEMS)
    extra = extra[:MAX_PROBLEMS]
    if dropped:   # a bug in a loop: one count saying roughly how many more
        extra.append(f"problems-dropped/{bucket(dropped)}")
    return extra, taken, newest


def _without(have, sent) -> list[str]:
    """`have` with each of `sent` taken out once: any added meanwhile stay."""
    left = [e for e in (have if isinstance(have, list) else []) if isinstance(e, str)]
    for e in sent:
        if e in left:
            left.remove(e)
    return left


QUIT_WAIT_S = 2.0   # the longest a quit waits for at_quit's send (it runs while the rest closes)


def at_quit(cfg, app_dir: Path | None = None):
    """At a real quit: what's waiting for the next count, sent now, so the last day
    someone used the app isn't lost when they never start it again (or closed it
    within a minute of starting). Only the events the next count would carry anyway:
    the features used (`used/`, not features_now, which the daily count adds), the tabs
    opened (`tab/`) and the one-off and problem events waiting. Never the daily count
    itself or its buckets, and nothing when nothing waits.

    Starts the send on a thread and returns finish(), or None when nothing goes. Call
    finish() later in the quit, on the thread that owns cfg: it waits what's left of
    QUIT_WAIT_S and returns True when the counter took them, after clearing exactly
    those from cfg (save it after). If it didn't (offline, too slow), they stay for
    the next count."""
    if not enabled() or not net.allowed(FEATURE):
        return None
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    feats = [k for k in FEATURES if k in have]
    tabs = [t for t in TABS if t in (cfg.stats_tabs if isinstance(cfg.stats_tabs, list)
                                     else [])]
    extra, taken, newest = _waiting(cfg, now, app_dir)
    events = [*(f"used/{k}" for k in feats), *(f"tab/{t}" for t in tabs), *extra]
    if not events:
        return None
    sid = install_id(cfg)
    payload = [_event(e, sid) for e in events]
    netlog.cause(FEATURE, "Anonymous usage count (at quit)")
    done: list[bool] = []
    end = time.monotonic() + QUIT_WAIT_S
    t = threading.Thread(target=lambda: done.append(send(payload, timeout=QUIT_WAIT_S)),
                         daemon=True, name="usage-count")
    t.start()

    def finish() -> bool:
        t.join(max(0.0, end - time.monotonic()))
        if not (done and done[0]):
            return False
        cfg.stats_used = [k for k in cfg.stats_used if k not in feats]
        cfg.stats_tabs = [k for k in cfg.stats_tabs if k not in tabs]
        cfg.stats_pending = _without(cfg.stats_pending, taken)
        cfg.stats_problems_seen = max(cfg.stats_problems_seen, newest)
        return True
    return finish


def step(cfg, name: str, on_sent=None) -> None:
    """A new install's first time doing `name` (one of STEPS): sent right away, once.
    A copy counted before these existed never sends them (settle)."""
    if name not in STEPS or not enabled() or not net.allowed(FEATURE):
        return
    settle(cfg, time.time())
    if name in cfg.stats_steps:
        return
    cfg.stats_steps = [*cfg.stats_steps, name]
    maybe_send(cfg, on_sent, event=f"step/{name}")


def improve(cfg, picks, other: str = "", bugs: str = "") -> bool:
    """The feedback box's "What would you improve?" picks, sent now as `improve/<name>`
    (names from IMPROVE only), their follow-up ticks (`sounds/memes` in `picks`) as
    `improve/sounds/memes` (names from IMPROVE_MORE only), what was typed under Other
    as `improve/other/<words>` and under Fewer bugs as `improve/bugs/said/<words>`
    (other_tag, BUGS_MAX for bugs). Anonymous: they go with a one-off random session
    made for this send, never this PC's stats_id, so they can't be linked to the daily
    count or to each other. False when nothing can be sent (usage count off, offline, running from
    source)."""
    events = []
    for k in IMPROVE:
        if k not in picks:
            continue
        tag = other_tag(other) if k == "other" else ""
        events.append(f"improve/{k}/{tag}" if tag else f"improve/{k}")
        events += [f"improve/{k}/{sub}" for sub in IMPROVE_MORE.get(k, ())
                   if f"{k}/{sub}" in picks]
        said = other_tag(bugs, BUGS_MAX) if k == "bugs" else ""
        if said:
            events.append(f"improve/bugs/said/{said}")
    if not events or not enabled() or not net.allowed(FEATURE):
        return False
    sid = uuid.uuid4().hex   # not install_id(cfg): the box says it isn't linked to this PC
    netlog.cause(FEATURE, "Anonymous usage count (feedback picks)")
    threading.Thread(target=send, args=([_event(e, sid) for e in events],), daemon=True,
                     name="usage-count").start()
    return True


SURVEY = ("shown", "dismissed", "positive", "negative")   # feedback/<one of these>


def survey(sid: str, what: str, said: str = "") -> bool:
    """*Enjoying Onion Board?* (ui/window/enjoycontrol.py): `feedback/<what>` (SURVEY names
    only), with what they typed as `feedback/<what>/<words>` (other_tag). `sid` is a
    random session the bar made, never this PC's stats_id. False when nothing can be
    sent (usage count off, offline, running from source)."""
    if what not in SURVEY or not enabled() or not net.allowed(FEATURE):
        return False
    tag = other_tag(said) if what in ("positive", "negative") else ""
    event = f"feedback/{what}/{tag}" if tag else f"feedback/{what}"
    netlog.cause(FEATURE, "Anonymous usage count (feedback)")
    threading.Thread(target=send, args=([_event(event, sid)],), daemon=True,
                     name="usage-count").start()
    return True


def send_now(cfg, event: str) -> bool:
    """Send one `event` and wait for it (the uninstaller's `--uninstall-count`)."""
    if not enabled() or not net.allowed(FEATURE):
        return False
    netlog.cause(FEATURE, f"Anonymous usage count ({event})")
    return send(hits(cfg, time.time(), event))
