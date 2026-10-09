# Security policy

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Use GitHub's private reporting instead: go to the repository's **Security** tab →
**Report a vulnerability**. Include what you found, how to reproduce it, and which
version (it's in the title bar).

You'll get an acknowledgement within a week. Fixes ship in a normal release and
the CHANGELOG credits you unless you'd rather not be named.

## Supported versions

Only the latest release gets security fixes.

## What counts

In scope, for example:

- The Radio tab showing a station's name / country as rich text (it's
  community-edited data).
- Another local process or web page connecting to the app's loopback sockets
  (module link) without the per-launch secret.
- Anything reaching the local control API (Settings → Remote → *Remote
  control*, off by default) without its key, from another machine, or through a
  web page (e.g. DNS rebinding), or making it do more than play / stop / pause
  sounds and list them.
- The phone remote's server (Onion Pocket, off by default) answering without its key,
  from outside the local network, or doing more than the actions it lists.
- The installer or `installer/install-vbcable.ps1` running something that isn't what it
  claims to be (e.g. the VB-Cable signature check being bypassable).
- Crafted audio / video files that cause code execution, not just a failed import.
- *Straight into my mic* (how sounds reach others by default; see [below](#what-straight-into-my-mic-changes-on-your-pc)):
  its effect DLL runs inside Windows' audio engine
  (`audiodg.exe`, as LOCAL SERVICE). Anything another local user or program can write
  into `%ProgramData%\OnionBoard\MicPlugin\ring2.bin` (signed-in users may write it,
  by design) that crashes the audio engine, runs code in it, or reads or writes outside
  the file is in scope; the effect takes the sizes once and checks every sample. So is
  the admin step (`--direct-mic install / uninstall`) installing any DLL but the app's
  own copy, touching any device but a mic Windows lists, or leaving a mic's effect
  settings changed after an uninstall. Others on
  the PC hearing or changing what goes into your mic through that file is a known part
  of the design (anyone signed in can already record and play audio).
- Anything that sends the user's data off the machine without them asking.
- With a proxy set (Settings → Connection), any request the
  app makes that goes around it, or a DNS lookup of a site's name on this PC
  (see *Through a proxy* below for what it covers).
- The proxy relay on `127.0.0.1` accepting a request without its per-launch secret.

Out of scope:

- **Modules** (`%APPDATA%\OnionBoard\modules\`) are Python code that runs with
  your user's full permissions, exactly like any program you download. A
  malicious module being malicious isn't a vulnerability in Onion Board; a
  module escaping into something the user never installed is. The same goes for
  custom voice programs (a `"command"` in `%APPDATA%\OnionBoard\voices\`, or the
  `piper.exe` there): they're programs you chose to run.
- Games' anti-cheat reacting to global hotkeys or `SendInput` (auto push-to-talk);
  see [Anti-cheat](#anti-cheat) for what the app does and doesn't touch.
- Bugs in Qt that are already fixed upstream. Tell us if the pinned PySide6 is
  behind on security releases, though — that's in scope.

## What the app does on the network

So you know what normal looks like when auditing it:

| When | Where | Why | Switch |
|---|---|---|---|
| You paste a link into *Search sounds* on the Sounds tab | that link's site, via `yt-dlp` (only `http`/`https` links) | looks the link up (title, length); *Add as sound* / *Play once* then download its audio stream (and thumbnail, for the pad's picture) into a temp folder, which is deleted once it's imported, or when the link is cleared or the app closes | `sounds_web` |
| You press Enter in *Search sounds* (or its *Search* button) | `youtube.com` via `yt-dlp` (`music.youtube.com` with *YouTube Music* picked), and `i.ytimg.com` — or, with *SoundCloud* picked above the results, `soundcloud.com` / `api-v2.soundcloud.com` via `yt-dlp`, and `i1.sndcdn.com` — or, with *Myinstants* picked, `www.myinstants.com` directly (its search page, then the picked `.mp3` itself; yt-dlp can't fetch it) | one page of search results for what you typed (titles, channels, lengths, view counts) and their thumbnails; nothing more is fetched per result (no video page, no like or comment look-ups); no audio is downloaded until you press *Play* or *Add* on a result, which then works like a pasted link | `sounds_web` |
| You open *Free sound packs…* (Sounds tab → Backup) | `raw.githubusercontent.com` | reads this project's list of free sound packs (`packs/catalog.json`: each pack's name, description, download link and SHA-256). Nothing else is sent | `sound_packs` |
| You press *Add to my board* on a pack there | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that pack's zip (only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\packs\` and checks it against the SHA-256 in the list; a file that doesn't match is deleted. Its sounds are then imported like a dropped backup zip | `sound_packs` |
| When you click *Update now* / *Reset downloader* (Settings → Updates), or — only if you tick *Update automatically*, off by default — once a day and after an *Add as sound* that failed | `pypi.org`, `files.pythonhosted.org` | checks for a newer `yt-dlp`; if there is one, downloads the `yt-dlp` and `yt-dlp-ejs` wheels, checks each against PyPI's SHA-256, and unpacks them into `%APPDATA%\OnionBoard\yt-dlp\`. That code then runs inside the app, like the bundled copy it replaces | `ytdlp_update` |
| Unless you untick *Check for updates* (Settings → Updates): 45 s after start, then at most every 6 hours; or when you click *Check now* | `api.github.com` | asks for this project's latest release (version number, release page, the first lines of its notes, and its installer's download link and SHA-256). If that release came out less than a day ago (and isn't an urgent fix), the automatic check also asks for the last 10 releases, to offer the newest one that's been out a day instead. A newer version is only announced; nothing is downloaded until you click *Update now* | `app_update` |
| You click *Update now* on a newer version (installed app only; a copy running from source only opens the release page) | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that release's `OnionBoardSetup.exe` (only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\updates\` and checks it against the SHA-256 GitHub lists for it; a file that doesn't match is deleted. When you click *Restart now* the app closes and runs it silently over the installed copy (never the virtual cable, FFmpeg or live-voice extras), then the installer opens the app again. Downloaded installers are removed on the next start | `app_update` |
| Unless you untick *Count me in* (the installer, or Settings → Privacy & security; on for new installs, off for copies installed before it existed): once a day, 60 s after start (and checked every 6 hours, for an app left running); also once when you click *Update now* (installed app only; a copy running from source never sends it) | `onionalien.goatcounter.com` (GoatCounter, a privacy-friendly counter; the website counts its visits there too) | one HTTPS POST to its `/api/v0/count`: the path `/app/<version>`, a random ID made on this PC (`stats_id` in `config.json`) and a short tag made from it (`u-` and 12 letters of its hash, as the count's referrer), sent with every one of these so one person counts once and we can follow how each person uses the app over time (which tabs, which versions, whether they come back, where they stop), only to fix errors and see which features need work. The ID isn't tied to your name, account or anything else about you, and on the very first send a `first-start` event (`first-start/heard-<where>` if you picked where you heard about the app on the installer's last page: YouTube, Reddit, GitHub, Google, a friend, or a short name you typed under Other; a typed answer that looks like an email address, a link or a number is dropped, not sent); *Update now* sends an `update-now/<from>-to-<to>` event instead. The daily one also says which tabs you opened since the last one (`tab/sounds`, `tab/radio`… names only, nothing about what you did there). It also gives a rough picture of how the app is used, each as a bucket or a name from a fixed list: how long ago it was installed (`age/day-1`, `age/days-2-7`, `age/days-8-30`, `age/days-31-plus`), where your sounds go (`route/mic`, `route/cable`, `route/device`, `route/off`), how many sounds your board has and how many you played since the last one (`sounds/…` and `played/…`: `0`, `1-10`, `11-50` or `51-plus`), how long the app was open since the last one (`open/under-15m`, `15m-1h`, `1-3h`, `3-8h` or `8h-plus`; added up every 5 minutes while it runs, never the times of day, and a sleeping PC doesn't count), the app's language (`lang/de`), and which features you used or have set up since then (`used/voice-changer`, `used/youtube`, whether you opened *+ More tabs* and then added a tab from it or closed it (`used/more-tabs-opened`, `used/more-tabs-added-radio`, `used/more-tabs-closed`), a tab hidden from its right-click menu (`used/tab-hidden-voice`)… only the names in `FEATURES` in `soundboard/usage.py`, never what you did with them). A new install also sends its first steps once each, when they happen: `step/added-sound`, `step/played-sound` and `step/sent-to-others` (a copy counted before these existed never sends them); and once each, when you switch on a tab a new install starts without: `step/added-radio-tab`, `step/added-apps-tab` or `step/added-triggers-tab`. Soon after a start, how many problems there were since the last send, as counts only: `crash/<version>`, `error/<version>` or `freeze/<version>` for each crash or freeze report saved in `crash-reports\` (with where it happened in Onion Board's own code: the error's type, such as `KeyError`, and the file and line, such as `soundboard/engine.py:1090`, which anyone can look up in the public source. That, the kind and the version are all that's read from it: never the error message, paths, devices or log lines. The report itself never leaves your PC unless you post it), and `unclean-exit/<version>/<why>` when the last run ended without the app closing itself, with which kind it was (`native-crash`, `windows-error`, `not-responding`, `while-closing`, `frozen`, `pc-restarted` or `ended`; for a crash also the error's name, such as `access-violation`, and the Windows file or the line of Onion Board's code it happened in, such as `Qt6Core.dll`. The app works this out on your PC, from its own notes and Windows' Application log). Answering *Send feedback*'s "What would you improve?" sends your picks right away, with a one-off random session instead of this PC's ID so they can't be linked to you or to the daily count (`improve/sounds`, `improve/looks`… only the names in `IMPROVE` in `soundboard/usage.py`) and what you typed under *Something else* as dashed words (`improve/other/more-anime-sounds`, at most 100 characters; anything that looks like an email address, a link or a long number is taken out first). Switching *Count me in* off (the installer's box, or Settings) sends one last `opt-out/installer` or `opt-out/settings`, with no ID, tag or session, so it can't be tied to anything sent before (only when it was on until then, never in Offline or Tor mode, and the installer waits at most 5 s); after that nothing is sent. Uninstalling sends one `uninstall/<version>` (the uninstaller runs `OnionBoard.exe --uninstall-count`; not in Tor mode, and it gives up after 15 s). Nothing else: no user name, PC name, sounds, settings, devices, games or crash messages, and the app doesn't send its IP address in the message (GoatCounter sees the connection's address like any site, and isn't asked to look it up or keep it). The key in `soundboard/usage.py` can only add counts, not read them | `usage_stats` |
| You open the Radio tab (or start the app with Radio as the last tab you used: the app reopens it), or a phone remote / the control API asks for the popular stations or searches them | `*.api.radio-browser.info` | the station directory: the ~3000 most-listened stations with a location (cached for a day), your searches, and — only if you tick *Share play counts* (Settings → Privacy & security, off by default) — a "click" when you start a station (Radio Browser's own popularity count). Nothing else about you is sent. The map's country outlines ship with the app and load from its own folder: no CDN is contacted | `radio` |
| You play a radio station | that station's stream server (the address listed for it in the directory; its `https` address when the directory lists one, so the network in between can't see which station) | the stream itself, decoded by Qt Multimedia (FFmpeg) and played through the app's audio engine | `radio` |
| You speak a line with a custom voice server you added (Voice tab → More options → *Custom voices*; a `.json` with a `"url"` in `%APPDATA%\OnionBoard\voices\`) | the address you gave it (normally a TTS server on your own PC, e.g. `127.0.0.1`) | sends the line's text (and the voice / model / API key you entered) and gets the spoken audio back. Nothing is sent until you add one | `voice_servers` |
| You tick *Play M4A, AAC and video files* in the installer | `winget` (Microsoft's package source, then the FFmpeg build it points to) | installs `Gyan.FFmpeg.Essentials` | — (the installer) |
| You install the virtual cable (only if you choose to: sounds go straight into your mic by default, so its box in the installer is unticked; also the setup guide's and Setup tab's *Install the free virtual cable* button) | `vb-audio.com` | downloads VB-Cable; the installer's signature is checked before it runs | `setup_downloads` (not the installer's box) |
| You press *Get Tor* / *Update Tor* (Settings → Connection), or tick *Private connection (Tor)* in the installer (unticked by default) | `dist.torproject.org`, or `archive.torproject.org` once dist no longer has this version (through your proxy if *Connection* is set to one; when updating, through the Tor that's already there if Tor is picked) | downloads the Tor Project's Tor Expert Bundle for Windows (about 22 MB), checks it against the SHA-256 pinned in `soundboard/torget.py` (taken from the release's GPG-signed checksum list; a download that doesn't match is thrown away) and unpacks only `tor.exe`, `lyrebird.exe`, `pt_config.json` and their licence texts into `%APPDATA%\OnionBoard\tor\bin\`. The app doesn't ship Tor. Where Tor is blocked, this download often is too | `tor_download` |
| Install from source (`scripts/install.ps1`) | PyPI, and `winget` if you accept installing Python | the app's `requirements.txt` | — |
| You install a module (its Install button, its `install.bat`, or the installer's *live voice* box) | PyPI, via `pip`, plus whatever the module fetches | that module's `requirements.txt`; *live-voice* downloads a Whisper speech model from Hugging Face (via `faster-whisper`), and picking a different model in the Voice tab downloads that one the first time it starts. Each time live voice starts, `faster-whisper` also asks `huggingface.co` whether the model has changed (no audio or text is sent) | `addons` (pip); `voices` (the speech model) |
| You click *Get Onion Watch* on the Triggers tab | `api.github.com` | asks for the Onion Watch project's latest release (version number, release page, the first lines of its notes, and its add-on zip's download link and SHA-256) | `addons` |
| Right after that, or when you click *Update* on the Triggers tab | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads `OnionWatch-module.zip` (only from `github.com/Onion-Alien/onion-watch/releases/download/`, HTTPS only) into `%APPDATA%\OnionBoard\updates\`, checks it against the SHA-256 GitHub lists for it, and unpacks it into `%APPDATA%\OnionBoard\modules\onion-watch\` only if every file stays inside that folder. That code then runs inside the app, like any module. The zip is deleted afterwards | `addons` |
| Once Onion Watch is installed, with the update check above (only while *Check for updates* is ticked) | `api.github.com` | asks for Onion Watch's latest release too. A newer one is only offered on the Triggers tab; nothing is downloaded until you click *Update* | `addons` |
| You pick a language under *Speak in* (Voice tab) and press its *Download* button | `argos-net.com` | downloads that language's translation model (65–196 MB) once, checks it against the SHA-256 in its add-on's `module.json`, and unpacks only the model files into `%APPDATA%\OnionBoard\translation\`. Translating what you say then happens on your PC | `voices` |
| You press *Install the … voice* under *Speak in* (Voice tab) and say Yes to Windows' permission prompt | Windows Update (Microsoft) | Windows itself (`Add-WindowsCapability`, run elevated) downloads and installs its free text-to-speech voice for that language, the same as Settings → Speech → Add voices. The app only starts it and reads back whether it worked | `voices` |
| You press *Support Onion Board* (Settings → Add-ons & help) | `github.com`, in your own web browser | opens this project's page at its Support section | — (your browser) |
| You press *Report on GitHub* in the crash window | `github.com`, in your own web browser | opens a new-issue page; the report is only put on your clipboard, and nothing is posted unless you paste it and submit | — (your browser) |
| You press *Join the Discord* (Settings → Add-ons & help, Settings → About, the tray icon's menu, the *What's new* window, or the installer's last page), *Send feedback*, *Report a problem* or *Report a security issue* (Settings → Add-ons & help, and Settings → About), a *Report it* link beside an error message, *Yes* to "Would you tell us why?" after uninstalling, or *Website* / *Source code* / *Licenses* (Settings → About) | `discord.gg` (the Onion Board Discord server), `tally.so` (the no-account feedback form), `github.com` or `onion-alien.github.io`, in your own web browser | opens that page with the app's version (and, for *Report it*, the error's text) filled in; the app sends nothing itself, and nothing is posted unless you submit it there | — (your browser) |
| While a module runs (e.g. live voice) | `127.0.0.1` only | module link, guarded by a random per-launch secret | — (this PC) |
| You turn on *Remote control* (Settings → Remote; off by default) | listens on `127.0.0.1` only (port 7474 unless you change it) | lets a Stream Deck, AutoHotkey or a script on this PC play / stop / pause sounds and list them. Every request needs the key shown in Settings. Unlike the sockets above the key survives restarts (a Stream Deck button has to keep working), so it's stored in `config.json`; it's never exported with a backup or logged, and *New key* replaces it. Requests for any other `Host` are refused and no CORS headers are sent, so web pages can't use it | — (this PC) |
| You click *Get AI voices* (Voice tab) | `api.github.com`, then `github.com` → GitHub's release download server | asks for this project's `ai-voices` release (its title's version, its notes, and its add-on zip's download link and SHA-256), then downloads `AiVoices-module.zip` (about 40 MB: the add-on's code and its voice model; only from `github.com/Onion-Alien/onion-board/releases/download/`, HTTPS only) into `%APPDATA%\OnionBoard\updates\`, checks it against the SHA-256 GitHub lists for it and unpacks it into `%APPDATA%\OnionBoard\modules\ai-voices\` only if every file stays inside that folder. Its install then fetches `onnxruntime` and `numpy` from PyPI (the module row above). The zip is deleted afterwards. While an AI voice runs nothing goes online: your mic goes to its helper over `127.0.0.1` and back | `addons` |
| The AI voices add-on finds its voice model missing (its install step, `helper.py --download`) | the address in its `voices.json` (`model.url`, HTTPS only) | downloads the model zip and keeps it only if it matches the SHA-256 written there. Unused when the add-on came with its model (the normal case) | `addons` |
| You click *Get Onion Pocket* (Settings → Remote) | `api.github.com`, then `github.com` → GitHub's release download server | the same as *Get Onion Watch* above, for the Onion Pocket project: its latest release, then `OnionPocket-module.zip` (only from `github.com/Onion-Alien/onion-pocket/releases/download/`, HTTPS only), checked against the SHA-256 GitHub lists for it and unpacked into `%APPDATA%\OnionBoard\modules\onion-pocket\` only if every file stays inside that folder. The zip is deleted afterwards | `addons` |
| You open Settings → Remote with Onion Pocket installed (at most once an hour), and *Update Onion Pocket to …* on its card when you click it | `api.github.com`; on the click, `github.com` → GitHub's release download server | the same release lookup as *Get Onion Pocket*: is its latest release newer than the installed one? Nothing else is sent, and nothing is downloaded until you click. Then the same checked download as above; the running copy is stopped and the new one started with your settings and key unchanged. If anything fails the old copy keeps running | `addons` |
| You install the Onion Pocket add-on and turn it on (Settings → Remote → *Let phones on this Wi-Fi use it*; off by default) | listens on this PC's address on the local network only (port 7475 unless you change it); answers only local-network addresses (private / link-local), and never listens on a network Windows calls Public (a café's or a hotel's Wi-Fi), even if Windows Firewall would let it: it checks when it starts and every 30 seconds after | serves the phone page and lets a phone on your Wi-Fi list, play, stop and pause sounds, change the volume and category, and mute you; never the mic, the voice changer or the replay. It has its own key, separate from *Remote control*'s, given to the phone in the QR code's `#fragment` (browsers never send that part); every request needs it, and an address that gets it wrong 5 times in a row is ignored for a minute. Onion Pocket 0.2.2 and newer never send the key itself: each request carries a one-time HMAC-SHA256 signature made with it (over the time, a random nonce and the request), taken once and only within 5 minutes of this PC's clock. Stored in `config.json`, never exported with a backup or logged; *Forget phones* replaces it. **Plain HTTP**: someone else on the same network who can read its traffic sees only one-time signatures (Onion Pocket 0.2.2+; older versions send the key itself), but someone who can change that traffic on its way could still take the key, so use it at home, not on public Wi-Fi. The page loads nothing from anywhere else (hash-only Content-Security-Policy, `connect-src 'self'`). Turning it on (or *Let it through Windows Firewall*) adds one inbound rule after Windows' admin prompt, which Onion Board itself asks for (`OnionBoard.exe --firewall-rule`, so the prompt names it): that port and this program, TCP, Private networks, local subnet only | — (this network) |
| Always | a local named pipe (`OnionBoard.App`) | single instance: a second launch asks the first to come to the front. It only accepts that one request | — (this PC) |

To see it happen, Settings → Connection → *Network activity* lists every
connection the app makes or refuses while it runs (`soundboard/netlog.py`):
server, feature, why (what you did that caused it, or the app's own timer), route,
result, bytes, and the HTTP request line, answer and TLS
version where the app can read them (inside a radio or yt-dlp `https` tunnel it
can't). The list is kept in memory only (at most 1000 entries) unless you tick
*Keep a history between starts* there (or the installer's box for it; off by
default): then each connection is also saved to
`%APPDATA%\OnionBoard\network-activity.jsonl` as it ends and listed again on the
next start (Clear empties it; unticking deletes it). The file keeps more than the
list shows, for *Totals…*: up to about 10 MB (at 5 MB it moves to `.old`, and the
`.old` before it goes). It's never written to the
log or sent anywhere, and it never holds proxy passwords, the relay's secret, request
headers or bodies; query values whose names look like keys or tokens are masked.
`tor.exe`'s own connections to the Tor network and everything under *Not covered*
below aren't in it.

### Switches and Offline mode

Settings → Privacy & security has a switch for each feature in the *Switch* column
above, grouped into Sounds and radio, Voices, Updates and add-ons, and Setup downloads,
and *Offline mode*, which switches them all off. The installer's *Your privacy* page
has the same *Offline mode* box (or `/OFFLINE=1` for a silent install): it's written to
`config.json` before the app first starts, so the app never goes online at all, and
it unticks the installer's own downloads (VB-Cable, FFmpeg, live voice, Tor).
Connection settings live on Settings → Connection; automatic update preferences
live only on Settings → Updates. Changing a category does not change permissions.
Off means fully off, in every
Connection mode: every request names its feature, and `soundboard/net.py` refuses a
switched-off one (or one that names none) before anything is looked up or connected.
FFmpeg and Qt connect from C++, so they always go through the app's loopback relay,
Direct mode included; the relay's per-launch login names the feature, and the relay
refuses a switched-off one. Programs the app starts get their own feature's login
(`pip`: add-ons; the live-voice helper: voices, plus `HF_HUB_OFFLINE=1` while that's
off, so it only uses a speech model it already has). Sounds from the web also have a
switch per site (YouTube, SoundCloud, Myinstants, other links). Everything is on by
default, except what was already opt-in (yt-dlp's automatic updates, play counts).

A change applies to what's already running, not only to what starts next: switching
a feature off, turning on *Offline mode* or changing the Connection setting cuts that
feature's open connections, so a download in progress (an update, a model, a sound)
stops instead of finishing the old way, and a playing radio station stops (or, after
a Connection change, reconnects the new way). The update download also checks its
switch between chunks.

Not covered: links you open in your own browser (Support, feedback and report
buttons, Report on GitHub, release pages), the installer's own downloads (FFmpeg, VB-Cable, live voice), and
Windows Update installing a voice or the PowerShell VB-Cable download (they can't go
through the app's connection, so their buttons are disabled while their switch is off).
A custom voice that's a program you added may go online on its own; it gets the
voice servers' login, but one that ignores proxy settings can't be stopped.

### Through a proxy

Settings → Connection → *Through a proxy* sends what the app
fetches through a SOCKS5 (`socks5h://host:port`; `socks5://` and a bare `host:port`
mean the same) or HTTP (`http://host:port`, via `CONNECT`) proxy. All of it goes
through `soundboard/net.py`:

| What | How it reaches the proxy |
|---|---|
| Update checks and downloads, the yt-dlp updater, Myinstants, translation models, Onion Watch, AI voices, Onion Pocket, Tor's download, custom voice servers, the usage count | `net.urlopen()`: connections are opened by the proxy, and site names are sent to it unresolved |
| yt-dlp (searches, link look-ups, downloads, and the ffmpeg it may start) | its `proxy` option, set to the relay |
| Radio Browser and search thumbnails (Qt's network managers) | an HTTP proxy setting pointing at the relay |
| Radio streams (Qt Multimedia / FFmpeg), including redirects, HLS playlists and segments, and ICY titles | the `http_proxy` environment variable, pointing at the relay |
| Programs the app starts while the proxy is on (`pip` installing a module, the AI voices helper's model download, the live-voice helper's Hugging Face download / check) | `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`, pointing at the relay. A helper already running keeps the setting it started with |

The relay is a small HTTP proxy inside the app that listens on `127.0.0.1` only,
needs a random per-launch secret (Basic auth, compared with
`secrets.compare_digest`) and makes every onward connection through the proxy. It
refuses targets on this PC or the home network (loopback, private and link-local
addresses, `.local`, `.lan`).

In Direct mode the relay still carries FFmpeg's and Qt's connections (that's where
their switches are enforced). There, names are looked up on this PC anyway, so the
relay looks a name up first and refuses one that leads to this PC or the home network:
a radio station (or a stream redirect) whose name resolves to `127.0.0.1` or a router
address isn't played. FFmpeg's environment has no `no_proxy` list, so a redirect to
`127.0.0.1` or `localhost` goes through the relay too instead of straight to this PC,
and the relay refuses it in every mode: every station comes from Radio Browser, so
nothing the radio plays lives on this PC. (For the other features, Direct mode keeps
this PC reachable through the relay, as it was before the relay ran there.)

- **Fails closed.** If the proxy is unreachable, refuses, or its address can't be
  used, the request fails with a message saying so. Nothing falls back to a
  direct connection. A mode this version doesn't know (from a newer version's
  `config.json`) counts as a proxy with no address: nothing goes online.
- **DNS** goes through the proxy. While it's on, the radio player no longer looks a
  station's name up on this PC to check it isn't on the home network (that would
  tell your DNS server which station it is); the relay refuses home-network
  addresses instead.
- **Stays direct:** `127.0.0.1`, `::1` and `localhost` (a custom voice server on
  this PC, module links, the remote-control API). A custom voice server elsewhere
  on your network goes through the proxy like anything else. Radio streams are the
  exception: nothing a station sends the player to on this PC is reached.
- **Switching** applies at once: Qt's network managers are switched and their kept
  connections dropped, open relayed connections are closed, and a playing radio
  station reconnects.
- **Not covered**, because the app doesn't make these requests itself: pages it
  opens in your web browser (*Support*, the feedback and report buttons, *Report on GitHub*, a release page), the
  installer's downloads (VB-Cable, `winget`), Windows Update (*Install the … voice*)
  and the VB-Cable installer the setup guide starts (Windows PowerShell uses
  Windows' own proxy setting, not this one). The config keeps the proxy address
  (with any password in it) in `config.json`. It's never exported with a backup
  or written to the log.

### Through Tor

Settings → Connection → *Tor* sends everything above
through the app's own Tor instead of a proxy: the same paths and rules (fails
closed, DNS through Tor, loopback stays direct), with Tor's SOCKS port on
`127.0.0.1` as the proxy. Off by default. The app doesn't ship Tor: it's only
on your PC once you press *Get Tor* or tick *Private connection (Tor)* in the
installer (see *Get Tor* in the table above); a source checkout can also use
`scripts/fetch_tor.py`. Uninstalling leaves it in `%APPDATA%\OnionBoard\tor\bin\`
with your settings; delete that folder to remove it.

| When | Where | Why |
|---|---|---|
| Tor mode is on and the app first needs the network (or you pick *Tor* in Settings) | the Tor network: Tor's directory authorities and relays (or, with *Hide that I'm using Tor*, the Snowflake broker via a CDN plus WebRTC volunteers, or the built-in obfs4 bridges) | `tor.exe` connects ("bootstraps"). Its data folder is `%APPDATA%\OnionBoard\tor\` (directory cache, the control-port cookie); it logs at notice level with `SafeLogging` (no addresses) to the app only |

- **What it is.** `tor.exe` and `lyrebird.exe` are the Tor Project's own Windows
  Expert Bundle (`dist.torproject.org`), unmodified. The download is checked
  against a SHA-256 pinned in `soundboard/torget.py`, taken from the
  release's GPG-signed `sha256sums-signed-build.txt`. Antivirus programs sometimes
  flag `tor.exe` (a false positive common to Tor).
- **Only while it's needed.** Tor starts when Tor mode is on and something goes
  online, and stops when you switch Tor mode off or the app quits. It's tied to
  the app three ways (a Windows job object that kills it with the app, even after a
  crash; `TAKEOWNERSHIP` on its control connection; `__OwningControllerProcess`).
  Its SOCKS and control ports are on `127.0.0.1`, picked by Tor, and the control
  port needs the cookie only the app can read.
- **The switches still hold.** A feature that's switched off is refused before
  Tor is asked, so it never starts Tor; in Offline mode `tor.exe` isn't started at
  all, and one that's running stops. *Try this one without Tor* only skips the
  Connection setting: that site's switch still has to be on.
- **Waits, then fails.** Until Tor has connected, a request waits (the app shows
  how far Tor has got) and then fails if Tor doesn't make it. It never goes direct.
- **YouTube** often turns Tor away ("Sign in to confirm you're not a bot", HTTP
  429 / 403). The app then asks Tor for a new identity (`SIGNAL NEWNYM`: new
  circuits, usually another exit) and tries again, up to 3 times. If YouTube still
  refuses, it says so and offers *Try this one without Tor* (search: *Search this
  without Tor*). Only that click makes that one request directly, and the site then
  sees your own address.
- **Radio** streams reconnect over a new circuit if theirs breaks (more retries
  and more time than without Tor).
- **New identity** (Settings) sends `NEWNYM`: new connections leave from a
  different exit. Connections already open (a playing station) keep theirs.
- **What Tor hides:** your IP address from every site the app contacts (YouTube,
  SoundCloud, Myinstants, Radio Browser, radio stations, GitHub, PyPI), and which
  sites those are from your internet provider. With *Hide that I'm using Tor* the
  provider also can't easily tell that it's Tor at all.
- **What it can't hide:** what you send. YouTube still sees a Tor exit asking
  for that video; Radio Browser still gets your searches (and your plays, if you
  tick that box); a custom voice server still gets the text. The exit relay can
  see a plain `http://` radio stream (the app prefers `https` where the directory
  lists one). Everything under *Not covered* above stays outside Tor too.
  Connecting looks like Tor to your provider unless *Hide that I'm using Tor* is
  ticked.

No telemetry, analytics or crash upload beyond the anonymous usage count above (crash counts, never crash reports)
(*Count me in*). Its random ID does link your counts together over time, only to fix errors and see which features need work; untick *Count me in* and one last anonymous `opt-out` count goes, then nothing. The update check only reads the public
release list, and nothing is installed unless you click *Update now*. *Export* only writes a zip where you save it; nothing is uploaded. Logs and
settings stay in
`%APPDATA%\OnionBoard\`.

## What *Straight into my mic* changes on your PC

Sounds reach Discord and games through your own mic by default: a small Windows audio
effect (`native/directmic/obmic.cpp`, built from source with the app; `soundboard/directmic.py`)
mixes them into the mic. It's the one part of the app that needs admin, and it never
goes online.

- **Setting it up** (one click in the setup guide or on the Setup tab, then Windows'
  admin prompt; a one-click repair the same way if Windows takes it off): the app runs its own exe again as admin with
  `--direct-mic install <mic id>`. The id must be a recording device Windows lists,
  and the DLL copied is always the one inside the app, never a path from the command
  line. That step copies it to `%ProgramFiles%\Onion Board Mic\` (which only admins
  can change; the file is named after its SHA-256), registers it as an audio effect under
  `HKLM\SOFTWARE\Classes` (`CLSID\{C55E76FE-…}` and
  `AudioEngine\AudioProcessingObjects`), and puts it in that one mic's stream-effect
  slot (`MMDevices\Audio\Capture\<mic>\FxProperties`). An effect the mic's driver
  had there is kept and run first, inside ours. Every value is noted under
  `HKLM\SOFTWARE\OnionBoard\MicPlugin` before it changes. Windows' audio stops for a
  few seconds while this happens; a helper started first brings it back however the
  admin step ends, along with the services that run on it (Windows' MIDI service...).
  One admin step runs at a time, every command it runs has a time limit, and a set-up
  that fails half-way puts the mic back as it was. It logs to
  `%ProgramData%\OnionBoard\directmic-admin.log`.
- **The data folders**: anyone signed in can make folders in `%ProgramData%`, so before
  writing anything there the admin step makes `%ProgramData%\OnionBoard` a real folder
  owned by Administrators that only admins can change (a link someone put there is
  removed, never followed; so is anything inside not made by an admin), and sets
  `MicPlugin`'s own access on the folder itself, without walking what's inside.
- **The shared file**: `%ProgramData%\OnionBoard\MicPlugin\` lets LOCAL SERVICE (the
  audio engine), WRITE RESTRICTED and signed-in users make and change files in it, but
  not delete, rename or swap the folder itself, nor make folders in it (admins and SYSTEM
  have full access; store apps none). The board writes what others hear there, and the effect writes the
  clean mic back, so the board's meter and voice changer hear only you. Every app
  recording that mic runs its own copy of the effect. When the board is closed or
  late, the effect crossfades back to the plain mic. Since others can write the file,
  the effect trusts nothing in it: a damaged, cut-short or tampered file (even one
  that makes reading it fault) gets the plain mic passed through, never a crash of
  Windows' audio engine. `scripts/fuzz_directmic.py` tests this.
- **Taking it off**: uninstalling Onion Board runs `--direct-mic remove`, which asks
  for admin only if the effect is on a mic, then does what `--direct-mic uninstall`
  (as admin) does: put every mic's values back from the notes, unregister the effect and
  delete `Onion Board Mic` and the notes. If Windows already took the effect off (a
  driver update, *Reset sound settings*), what's there now stays. The shared file and
  the admin log stay in `%ProgramData%\OnionBoard\`.
- **The virtual cable**, the fallback, is VB-Audio's own signed driver: installed by
  `installer/install-vbcable.ps1` only when you ask, and removed by VB-Audio's own
  uninstaller (Setup tab → *Remove the virtual cable*, or the uninstaller's question),
  both after Windows' admin prompt.

## Anti-cheat

Onion Board never touches a game's process: it doesn't inject code into it, read
or write its memory, hook it, or install a kernel driver of its own. What it does
use is plain Windows APIs that any desktop app can call:

| Feature | What it does | Touches the game? |
| --- | --- | --- |
| *Straight into my mic* | an audio effect DLL that Windows loads into its own audio engine (`audiodg.exe`), not into the game ([details](#what-straight-into-my-mic-changes-on-your-pc)). It isn't code-signed | no |
| Hotkeys | `RegisterHotKey`: Windows tells the app when one of its own key combos is pressed. No keyboard or mouse hook | no |
| Auto push-to-talk | `SendInput` holds the push-to-talk key you set, only while a sound is going out | sends that one key, like a keyboard would |
| MIDI pads | reads the controller through Windows' MIDI API | no |
| Overlay | a separate always-on-top window that never takes focus, drawn by the app itself | no (drawn on top, not inside) |
| Onion Watch screen triggers (add-on) | copies the game window's picture (`PrintWindow`, or the screen through `BitBlt` / DXGI desktop duplication) and compares it with your pictures. It plays sounds; it never presses keys itself | reads pixels only |
| App audio / game detection | Windows' per-app audio capture, and `OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` (the least access there is, as Task Manager uses) just to read a program's name and whether it's still running. A refused handle is treated as "running" | a name-only handle, closed at once |

None of the anti-cheats checked (Riot Vanguard, Easy Anti-Cheat, BattlEye, FACEIT)
publish a rule against any of this: their published rules target vulnerable or blocked
kernel drivers, code loaded into the game, and cheats or macros that play the game
for you. The app hasn't been tested in-game against them, and no one can promise what
an anti-cheat will do next, so if one ever complains, please
[open an issue](https://github.com/Onion-Alien/onion-board/issues).
Two sensible habits: set your push-to-talk key to the game's push-to-talk only (never
a key that moves or shoots), and don't build Onion Watch triggers that react to
gameplay in a way that helps you play.

## For users filing bug reports

`%APPDATA%\OnionBoard\onionboard.log` contains file paths that include your
Windows user name. Skim it and replace anything personal before attaching it to a
public issue. It can also name a site a download or radio station failed on.
*Keep an app log* (Settings → Connection) switches it off and deletes it. Crash reports (the crash window, and
`%APPDATA%\OnionBoard\crash-reports\`) already have your home folder, user name
and computer name replaced — still skim them before posting.
