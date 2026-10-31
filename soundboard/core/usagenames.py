"""Every name the usage count (core/usage.py) may send: the tabs, the features (`FEATURES`),
the reasons a download or the mic effect failed, the first steps, the routes, the Improve
box's picks and the patterns a language or Twitch login must match. `usage` re-exports
them."""
from __future__ import annotations

from soundboard.core import achievements
from soundboard.core.usagetags import DL_SITES


# the tabs whose use is counted (tabcontrol.TAB_KEYS); anything else is never sent
TABS = ("sounds", "radio", "apps", "triggers", "voice", "setup", "store")
# the Onion Watch add-on's feature names (onionwatch/core/usage.py USED + SET_UP)
TRIGGERS_FEATURES = (
    "watching", "went-off", "test", "cut-from-window", "picture-file", "paste-picture",
    "area-trigger", "duplicate", "pick-windows", "pack-export", "pack-import",
    "history", "restore-deleted",
    "mode-appear", "mode-vanish", "mode-change", "mode-still", "mode-colour", "ring",
    "several-places", "every-copy", "area", "hold", "quiet-in-front", "own-interval",
    "categories", "profiles", "view-pads", "view-cards")
# the Voice tab's tabs (ui/voice/voicepanel.py VoicePanel._section keys)
VOICE_TABS = ("clean", "fx", "ai", "speak", "addons")
# The Mic effect card's actions (ui/setup/audiorecovery.py; "cleanup-none" counts as cleanup)
RECOVERY = ("install", "repair", "update", "reinstall", "cleanup", "remove")
# why one of them failed: an install's reason (MIC_FAILS), or leftovers still there after
# a clean-up, the effect still on after a remove, an install the status didn't confirm,
# or an error in the app itself
RECOVERY_FAILS = ("leftovers", "not-removed", "unverified", "error")
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
              "timeout", "memory", "ctypes", "other",
              "err-2", "err-3", "err-5", "err-32", "err-33", "err-87", "err-1224",
              "err-1314", "err-other", "err-none")
# exit code 6 (Windows' audio wouldn't stop): which of its services was still up, that
# it couldn't tell, or that the step logged nothing (directmic STUCK_WHICH, read back
# from the admin log)
MIC_STUCK = ("audio", "builder", "both", "unknown", "other", "unlogged")
# exit code 8 (the effect didn't start on its mic): what the effect's own log showed
# instead (with nothing in it: its DLL gone, Audio enhancements off, never a log), or
# that the step logged nothing (directmic UNSTARTED_WHY)
MIC_UNSTARTED = ("silent", "no-dll", "enh-off", "never-logged", "no-init", "unnamed",
                 "other-mics", "other", "unlogged")
# why a download from a link or search failed (errors.download_reason): the kind only
DL_FAILS = ("private", "age", "bot", "members", "region", "gone", "no-formats", "429",
            "403", "5xx", "stalled", "timeout", "cut-off", "offline", "proxy", "sign-in",
            "too-big", "no-downloader", "disk-full", "no-ffmpeg", "other")
# why the mic effect still wasn't working when the wait after its set-up ran out
# (statuscontrol._no_load_why): sent elsewhere since, Windows took it off, not on the
# mic, the board's sending into it not open, or open but the effect never ran
MIC_NO_LOAD = ("off-route", "wiped", "not-on", "no-stream", "not-running")
# how the setup guide's mic test went when its step was left (ui/setup/setupwizard.py):
# the level bar heard them, the mic opened but stayed quiet, it wouldn't open, there was
# no mic, or not heard while Windows' privacy settings keep apps off the mic
# (micstate.windows_blocks_mic)
MIC_TESTS = ("heard", "silent", "no-open", "no-mic", "blocked")
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
                 *(f"fx-{k}" for k in ("bass", "treble", "muffle", "reverb", "echo", "crunch",
                                          "volume")))
# their effect presets (audio/livefx.py PRESETS, as dashed words); any other is "other"
LIVE_PRESETS = ("nightcore", "slowed-reverb", "bass-boosted", "chipmunk", "deep-voice",
                "underwater", "other")
# what was done to a Voice tab recording or an Apps tab saved clip (ui/apps/clipshelf.py)
CLIP_ACTIONS = ("play", "mic", "add", "copy", "delete")
# Bun's games (ui/bun/bunpong.py games()); any other is "other"
BUN_GAMES = ("pong", "dodge", "homerun", "whack", "other")
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
            # used or are set up (triggershost.BoardHost.count): onionwatch/core/usage.py's
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
            *(f"mic-effect-code-8-{k}" for k in MIC_UNSTARTED),
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
            # Settings' Mic effect card: what was run on a mic, No to Windows' prompt for
            # it, and it failing (and why: MIC_FAILS, RECOVERY_FAILS)
            *(f"recovery-{k}" for k in RECOVERY), "recovery-said-no", "recovery-failed",
            *(f"recovery-failed-{k}" for k in (*MIC_FAILS, *RECOVERY_FAILS)),
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
            # Clean mic switched on (never how strong), its Hear the difference played, and
            # Open Clean mic in the box after Bun set Discord up
            "clean-mic", "clean-mic-test", "clean-mic-open",
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
            # the setup guide's mic test, as it stood when its step was left (MIC_TESTS)
            *(f"mic-test-{k}" for k in MIC_TESTS),
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
