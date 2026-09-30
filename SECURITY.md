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
- Anything reaching the local control API (Settings → General → *Remote
  control*, off by default) without its key, from another machine, or through a
  web page (e.g. DNS rebinding), or making it do more than play / stop / pause
  sounds and list them.
- The installer or `installer/install-vbcable.ps1` running something that isn't what it
  claims to be (e.g. the VB-Cable signature check being bypassable).
- Crafted audio / video files that cause code execution, not just a failed import.
- Anything that sends the user's data off the machine without them asking.

Out of scope:

- **Modules** (`%APPDATA%\OnionBoard\modules\`) are Python code that runs with
  your user's full permissions, exactly like any program you download. A
  malicious module being malicious isn't a vulnerability in Onion Board; a
  module escaping into something the user never installed is.
- Games' anti-cheat reacting to global hotkeys or `SendInput` (auto push-to-talk).
- Chromium bugs in Qt WebEngine that are already fixed upstream. Tell us if
  the pinned PySide6 is behind on security releases, though — that's in scope.

## What the app does on the network

So you know what normal looks like when auditing it:

| When | Where | Why |
|---|---|---|
| You paste a link into *Search sounds* on the Sounds tab | that link's site, via `yt-dlp` (only `http`/`https` links) | looks the link up (title, length); *Add as sound* / *Play once* then download its audio stream (and thumbnail, for the pad's picture) into a temp folder, which is deleted once it's imported, or when the link is cleared or the app closes |
| You press Enter in *Search sounds* (or its *Search* button) | `youtube.com` via `yt-dlp` (`music.youtube.com` with *YouTube Music* picked), and `i.ytimg.com` — or, with *SoundCloud* picked above the results, `soundcloud.com` / `api-v2.soundcloud.com` via `yt-dlp`, and `i1.sndcdn.com` — or, with *Myinstants* picked, `www.myinstants.com` directly (its search page, then the picked `.mp3` itself; yt-dlp can't fetch it) | one page of search results for what you typed (titles, channels, lengths) and their thumbnails; nothing is downloaded until you press *Play* or *Add* on a result, which then works like a pasted link |
| When you click *Update now* / *Reset downloader* (Settings → General), or — only if you tick *Update it automatically*, off by default — once a day and after an *Add as sound* that failed | `pypi.org`, `files.pythonhosted.org` | checks for a newer `yt-dlp`; if there is one, downloads the `yt-dlp` and `yt-dlp-ejs` wheels, checks each against PyPI's SHA-256, and unpacks them into `%APPDATA%\OnionBoard\yt-dlp\`. That code then runs inside the app, like the bundled copy it replaces |
| Unless you untick *Tell me when a new version is out* (Settings → General): once a day, 45 s after start (and every 6 hours after, for an app left running); or when you click *Check now* | `api.github.com` | asks for this project's latest release (version number, release page, the first lines of its notes, and its installer's download link and SHA-256). A newer version is only announced; nothing is downloaded until you click *Update now* |
| You click *Update now* on a newer version (installed app only; a copy running from source only opens the release page) | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that release's `OnionBoardSetup.exe` (only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\updates\` and checks it against the SHA-256 GitHub lists for it; a file that doesn't match is deleted. When you click *Restart now* the app closes and runs it silently over the installed copy (never the virtual cable, FFmpeg or live-voice extras), then the installer opens the app again. Downloaded installers are removed on the next start |
| You open the Radio tab (or start the app with Radio as the last tab you used: the app reopens it) | `*.api.radio-browser.info` | the station directory: the ~3000 most-listened stations with a location (cached for a day), your searches, and a "click" when you start a station (Radio Browser's own popularity count). Nothing else about you is sent |
| You open the Radio tab (same as above) | `cdn.jsdelivr.net` | the 3D globe: `globe.gl` at a pinned version, checked against its SHA-384 (subresource integrity), and the Earth pictures |
| You play a radio station | that station's stream server (the address listed for it in the directory) | the stream itself, decoded by Qt Multimedia (FFmpeg) and played through the app's audio engine |
| You tick *Play M4A, AAC and video files* in the installer | `winget` (Microsoft's package source, then the FFmpeg build it points to) | installs `Gyan.FFmpeg.Essentials` |
| You install the virtual cable (its box is ticked by default in the installer; also the setup guide's button) | `vb-audio.com` | downloads VB-Cable; the installer's signature is checked before it runs |
| Install from source (`scripts/install.ps1`) | PyPI, and `winget` if you accept installing Python | the app's `requirements.txt` |
| You install a module (its Install button, its `install.bat`, or the installer's *live voice* box) | PyPI, via `pip`, plus whatever the module fetches | that module's `requirements.txt`; *live-voice* downloads a Whisper speech model from Hugging Face (via `faster-whisper`), and picking a different model in the Voice tab downloads that one the first time it starts. Each time live voice starts, `faster-whisper` also asks `huggingface.co` whether the model has changed (no audio or text is sent) |
| You click *Get Onion Watch* on the Triggers tab | `api.github.com` | asks for the Onion Watch project's latest release (version number, release page, the first lines of its notes, and its add-on zip's download link and SHA-256) |
| Right after that, or when you click *Update* on the Triggers tab | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads `OnionWatch-module.zip` (only from `github.com/Onion-Alien/onion-watch/releases/download/`, HTTPS only) into `%APPDATA%\OnionBoard\updates\`, checks it against the SHA-256 GitHub lists for it, and unpacks it into `%APPDATA%\OnionBoard\modules\onion-watch\` only if every file stays inside that folder. That code then runs inside the app, like any module. The zip is deleted afterwards |
| Once Onion Watch is installed, with the daily update check above (only while *Tell me when a new version is out* is ticked) | `api.github.com` | asks for Onion Watch's latest release too. A newer one is only offered on the Triggers tab; nothing is downloaded until you click *Update* |
| You pick a language under *Speak in* (Voice tab) and press its *Download* button | `argos-net.com` | downloads that language's translation model (65–195 MB) once, checks it against the SHA-256 in its add-on's `module.json`, and unpacks only the model files into `%APPDATA%\OnionBoard\translation\`. Translating what you say then happens on your PC |
| You press *Install the … voice* under *Speak in* (Voice tab) and say Yes to Windows' permission prompt | Windows Update (Microsoft) | Windows itself (`Add-WindowsCapability`, run elevated) downloads and installs its free text-to-speech voice for that language, the same as Settings → Speech → Add voices. The app only starts it and reads back whether it worked |
| You press *Support Onion Board* (Settings → General) | `github.com`, in your own web browser | opens this project's page at its Support section |
| You press *Report on GitHub* in the crash window | `github.com`, in your own web browser | opens a new-issue page; the report is only put on your clipboard, and nothing is posted unless you paste it and submit |
| While a module runs (e.g. live voice) | `127.0.0.1` only | module link, guarded by a random per-launch secret |
| You turn on *Remote control* (Settings → General; off by default) | listens on `127.0.0.1` only (port 7474 unless you change it) | lets a Stream Deck, AutoHotkey or a script on this PC play / stop / pause sounds and list them. Every request needs the key shown in Settings. Unlike the sockets above the key survives restarts (a Stream Deck button has to keep working), so it's stored in `config.json`; it's never exported with a backup or logged, and *New key* replaces it. Requests for any other `Host` are refused and no CORS headers are sent, so web pages can't use it |
| Always | a local named pipe (`OnionBoard.App`) | single instance: a second launch asks the first to come to the front. It only accepts that one request |

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
