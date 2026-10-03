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

- The Radio tab's globe page navigating anywhere, running script other than the
  pinned `globe.gl`, or showing a station's name / country as HTML (it's
  community-edited data).
- Another local process or web page connecting to the app's loopback sockets
  (module link) without the per-launch secret.
- Anything reaching the local control API (Settings → Remote → *Remote
  control*, off by default) without its key, from another machine, or through a
  web page (e.g. DNS rebinding), or making it do more than play / stop / pause
  sounds and list them.
- The installer or `installer/install-vbcable.ps1` running something that isn't what it
  claims to be (e.g. the VB-Cable signature check being bypassable).
- Crafted audio / video files that cause code execution, not just a failed import.
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
- Games' anti-cheat reacting to global hotkeys or `SendInput` (auto push-to-talk).
- Chromium bugs in Qt WebEngine that are already fixed upstream. Tell us if
  the pinned PySide6 is behind on security releases, though — that's in scope.

## What the app does on the network

So you know what normal looks like when auditing it:

| When | Where | Why | Switch |
|---|---|---|---|
| You paste a link into *Search sounds* on the Sounds tab | that link's site, via `yt-dlp` (only `http`/`https` links) | looks the link up (title, length); *Add as sound* / *Play once* then download its audio stream (and thumbnail, for the pad's picture) into a temp folder, which is deleted once it's imported, or when the link is cleared or the app closes | `sounds_web` |
| You press Enter in *Search sounds* (or its *Search* button) | `youtube.com` via `yt-dlp` (`music.youtube.com` with *YouTube Music* picked), and `i.ytimg.com` — or, with *SoundCloud* picked above the results, `soundcloud.com` / `api-v2.soundcloud.com` via `yt-dlp`, and `i1.sndcdn.com` — or, with *Myinstants* picked, `www.myinstants.com` directly (its search page, then the picked `.mp3` itself; yt-dlp can't fetch it) | one page of search results for what you typed (titles, channels, lengths) and their thumbnails; nothing is downloaded until you press *Play* or *Add* on a result, which then works like a pasted link | `sounds_web` |
| When you click *Update now* / *Reset downloader* (Settings → Updates), or — only if you tick *Update automatically*, off by default — once a day and after an *Add as sound* that failed | `pypi.org`, `files.pythonhosted.org` | checks for a newer `yt-dlp`; if there is one, downloads the `yt-dlp` and `yt-dlp-ejs` wheels, checks each against PyPI's SHA-256, and unpacks them into `%APPDATA%\OnionBoard\yt-dlp\`. That code then runs inside the app, like the bundled copy it replaces | `ytdlp_update` |
| Unless you untick *Check once a day* (Settings → Updates): once a day, 45 s after start (and every 6 hours after, for an app left running); or when you click *Check now* | `api.github.com` | asks for this project's latest release (version number, release page, the first lines of its notes, and its installer's download link and SHA-256). A newer version is only announced; nothing is downloaded until you click *Update now* | `app_update` |
| You click *Update now* on a newer version (installed app only; a copy running from source only opens the release page) | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that release's `OnionBoardSetup.exe` (only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\updates\` and checks it against the SHA-256 GitHub lists for it; a file that doesn't match is deleted. When you click *Restart now* the app closes and runs it silently over the installed copy (never the virtual cable, FFmpeg or live-voice extras), then the installer opens the app again. Downloaded installers are removed on the next start | `app_update` |
| You open the Radio tab (or start the app with Radio as the last tab you used: the app reopens it) | `*.api.radio-browser.info` | the station directory: the ~3000 most-listened stations with a location (cached for a day), your searches, and — only if you tick *Share play counts* (Settings → Privacy & security, off by default) — a "click" when you start a station (Radio Browser's own popularity count). Nothing else about you is sent. The maps (country outlines, the 3D globe's `globe.gl`, its Earth pictures) ship with the app and load from its own folder: no CDN is contacted | `radio` |
| You play a radio station | that station's stream server (the address listed for it in the directory; its `https` address when the directory lists one, so the network in between can't see which station) | the stream itself, decoded by Qt Multimedia (FFmpeg) and played through the app's audio engine | `radio` |
| You speak a line with a custom voice server you added (Voice tab → More options → *Custom voices*; a `.json` with a `"url"` in `%APPDATA%\OnionBoard\voices\`) | the address you gave it (normally a TTS server on your own PC, e.g. `127.0.0.1`) | sends the line's text (and the voice / model / API key you entered) and gets the spoken audio back. Nothing is sent until you add one | `voice_servers` |
| You tick *Play M4A, AAC and video files* in the installer | `winget` (Microsoft's package source, then the FFmpeg build it points to) | installs `Gyan.FFmpeg.Essentials` | — (the installer) |
| You install the virtual cable (its box is ticked by default in the installer; also the setup guide's button) | `vb-audio.com` | downloads VB-Cable; the installer's signature is checked before it runs | `setup_downloads` (not the installer's box) |
| You press *Get Tor* / *Update Tor* (Settings → Connection), or tick *Private connection (Tor)* in the installer (unticked by default) | `dist.torproject.org` (through your proxy if *Connection* is set to one; when updating, through the Tor that's already there if Tor is picked) | downloads the Tor Project's Tor Expert Bundle for Windows (about 22 MB), checks it against the SHA-256 pinned in `soundboard/torget.py` (taken from the release's GPG-signed checksum list; a download that doesn't match is thrown away) and unpacks only `tor.exe`, `lyrebird.exe`, `pt_config.json` and their licence texts into `%APPDATA%\OnionBoard\tor\bin\`. The app doesn't ship Tor. Where Tor is blocked, this download often is too | `tor_download` |
| Install from source (`scripts/install.ps1`) | PyPI, and `winget` if you accept installing Python | the app's `requirements.txt` | — |
| You install a module (its Install button, its `install.bat`, or the installer's *live voice* box) | PyPI, via `pip`, plus whatever the module fetches | that module's `requirements.txt`; *live-voice* downloads a Whisper speech model from Hugging Face (via `faster-whisper`), and picking a different model in the Voice tab downloads that one the first time it starts. Each time live voice starts, `faster-whisper` also asks `huggingface.co` whether the model has changed (no audio or text is sent) | `addons` (pip); `voices` (the speech model) |
| You click *Get Onion Watch* on the Triggers tab | `api.github.com` | asks for the Onion Watch project's latest release (version number, release page, the first lines of its notes, and its add-on zip's download link and SHA-256) | `addons` |
| Right after that, or when you click *Update* on the Triggers tab | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads `OnionWatch-module.zip` (only from `github.com/Onion-Alien/onion-watch/releases/download/`, HTTPS only) into `%APPDATA%\OnionBoard\updates\`, checks it against the SHA-256 GitHub lists for it, and unpacks it into `%APPDATA%\OnionBoard\modules\onion-watch\` only if every file stays inside that folder. That code then runs inside the app, like any module. The zip is deleted afterwards | `addons` |
| Once Onion Watch is installed, with the daily update check above (only while *Check once a day* is ticked) | `api.github.com` | asks for Onion Watch's latest release too. A newer one is only offered on the Triggers tab; nothing is downloaded until you click *Update* | `addons` |
| You pick a language under *Speak in* (Voice tab) and press its *Download* button | `argos-net.com` | downloads that language's translation model (65–195 MB) once, checks it against the SHA-256 in its add-on's `module.json`, and unpacks only the model files into `%APPDATA%\OnionBoard\translation\`. Translating what you say then happens on your PC | `voices` |
| You press *Install the … voice* under *Speak in* (Voice tab) and say Yes to Windows' permission prompt | Windows Update (Microsoft) | Windows itself (`Add-WindowsCapability`, run elevated) downloads and installs its free text-to-speech voice for that language, the same as Settings → Speech → Add voices. The app only starts it and reads back whether it worked | `voices` |
| You press *Support Onion Board* (Settings → Add-ons & help) | `github.com`, in your own web browser | opens this project's page at its Support section | — (your browser) |
| You press *Report on GitHub* in the crash window | `github.com`, in your own web browser | opens a new-issue page; the report is only put on your clipboard, and nothing is posted unless you paste it and submit | — (your browser) |
| While a module runs (e.g. live voice) | `127.0.0.1` only | module link, guarded by a random per-launch secret | — (this PC) |
| You turn on *Remote control* (Settings → Remote; off by default) | listens on `127.0.0.1` only (port 7474 unless you change it) | lets a Stream Deck, AutoHotkey or a script on this PC play / stop / pause sounds and list them. Every request needs the key shown in Settings. Unlike the sockets above the key survives restarts (a Stream Deck button has to keep working), so it's stored in `config.json`; it's never exported with a backup or logged, and *New key* replaces it. Requests for any other `Host` are refused and no CORS headers are sent, so web pages can't use it | — (this PC) |
| Always | a local named pipe (`OnionBoard.App`) | single instance: a second launch asks the first to come to the front. It only accepts that one request | — (this PC) |

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

Not covered: links you open in your own browser (Support, Report on GitHub,
release pages), the installer's own downloads (FFmpeg, VB-Cable, live voice), and
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
| Update checks and downloads, the yt-dlp updater, Myinstants, translation models, Onion Watch, custom voice servers | `net.urlopen()`: connections are opened by the proxy, and site names are sent to it unresolved |
| yt-dlp (searches, link look-ups, downloads, and the ffmpeg it may start) | its `proxy` option, set to the relay |
| Radio Browser and search thumbnails (Qt's network managers) | an HTTP proxy setting pointing at the relay |
| Radio streams (Qt Multimedia / FFmpeg), including redirects, HLS playlists and segments, and ICY titles | the `http_proxy` environment variable, pointing at the relay |
| Programs the app starts while the proxy is on (`pip` installing a module, the live-voice helper's Hugging Face download / check) | `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`, pointing at the relay. A helper already running keeps the setting it started with |

The relay is a small HTTP proxy inside the app that listens on `127.0.0.1` only,
needs a random per-launch secret (Basic auth, compared with
`secrets.compare_digest`) and makes every onward connection through the proxy. It
refuses targets on this PC or the home network (loopback, private and link-local
addresses, `.local`, `.lan`). Without the setting it isn't started.

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
  on your network goes through the proxy like anything else.
- **Switching** applies at once: Qt's network managers are switched and their kept
  connections dropped, open relayed connections are closed, and a playing radio
  station reconnects.
- **The radio globe page** loads only the app's own files, and its web profile
  refuses any `http`/`https`/`ws` request.
- **Not covered**, because the app doesn't make these requests itself: pages it
  opens in your web browser (*Support*, *Report on GitHub*, a release page), the
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

No telemetry, analytics or crash upload. The update check only reads the public
release list, and nothing is installed unless you click *Update now*. *Export* only writes a zip where you save it; nothing is uploaded. Logs and
settings stay in
`%APPDATA%\OnionBoard\`.

## For users filing bug reports

`%APPDATA%\OnionBoard\onionboard.log` contains file paths that include your
Windows user name. Skim it and replace anything personal before attaching it to a
public issue. Crash reports (the crash window, and
`%APPDATA%\OnionBoard\crash-reports\`) already have your home folder, user name
and computer name replaced — still skim them before posting.
