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

- A web page in the **Browser** tab reaching anything beyond its own audio:
  the loopback WebSocket, local files, the app's settings, other processes.
- The Browser tab opening a page outside its allowed sites (`ALLOWED_SITES` in
  `soundboard/browser.py`), or downloading a file.
- Another local process or web page connecting to the app's loopback sockets
  (browser audio sink, module link) without the per-launch secret.
- The installer or `install-vbcable.ps1` running something that isn't what it
  claims to be (e.g. the VB-Cable signature check being bypassable).
- Crafted audio / video files that cause code execution, not just a failed import.
- Anything that sends the user's data off the machine without them asking.

Out of scope:

- **Modules** (`%APPDATA%\Soundboard\modules\`) are Python code that runs with
  your user's full permissions, exactly like any program you download. A
  malicious module being malicious isn't a vulnerability in Soundboard; a
  module escaping into something the user never installed is.
- Games' anti-cheat reacting to global hotkeys or `SendInput` (auto push-to-talk).
- Chromium bugs in Qt WebEngine that are already fixed upstream. Tell us if
  the pinned PySide6 is behind on security releases, though — that's in scope.

## What the app does on the network

So you know what normal looks like when auditing it:

| When | Where | Why |
|---|---|---|
| You use the Browser tab | the sites you visit (YouTube, SoundCloud, clip sites) and what their pages load | it's a browser |
| Ad blocker filter refresh | `easylist.to`, `ublockorigin.github.io` | block lists for the Browser tab |
| You click *Add as sound* in the Browser tab | the page's site (e.g. YouTube), via `yt-dlp` | downloads that one video's audio stream and its thumbnail (the pad's picture) into a temp folder, imports them, deletes the download |
| You paste a link into *Search sounds* on the Sounds tab | that link's site, via `yt-dlp` (only `http`/`https` links) | looks the link up (title, length); *Add as sound* / *Play once* then download its audio stream (and thumbnail, for the pad's picture) into a temp folder, which is deleted once it's imported, or when the link is cleared or the app closes |
| When you click *Update now* / *Reset downloader* (Settings → General), or — only if you tick *Update it automatically*, off by default — once a day and after an *Add as sound* that failed | `pypi.org`, `files.pythonhosted.org` | checks for a newer `yt-dlp`; if there is one, downloads the `yt-dlp` and `yt-dlp-ejs` wheels, checks each against PyPI's SHA-256, and unpacks them into `%APPDATA%\Soundboard\yt-dlp\`. That code then runs inside the app, like the bundled copy it replaces |
| You press Enter in *Search sounds* (or its *YouTube* button) | `youtube.com` via `yt-dlp`, and `i.ytimg.com` | one page of YouTube search results for what you typed (titles, channels, lengths) and their thumbnails; nothing is downloaded until you press *Play* or *Add* on a result, which then works like a pasted link |
| Lite mini-player shows a YouTube video | `i.ytimg.com` | the video's thumbnail, fetched by the app itself |
| You tick *Play M4A, AAC and video files* in the installer | `winget` (Microsoft's package source, then the FFmpeg build it points to) | installs `Gyan.FFmpeg.Essentials` |
| You install the virtual cable | `vb-audio.com` | downloads VB-Cable; the installer's signature is checked before it runs |
| Install from source (`install.ps1`) | PyPI, and `winget` if you accept installing Python | the app's `requirements.txt` |
| You install a module (its Install button, its `install.bat`, or the installer's *live voice* box) | PyPI, via `pip`, plus whatever the module fetches | that module's `requirements.txt`; *live-voice* downloads a Whisper speech model from Hugging Face (via `faster-whisper`), and picking a different model in the Voice tab downloads that one the first time it starts |
| You pick a language under *Speak in* (Voice tab) and press its *Download* button | `argos-net.com` | downloads that language's translation model (65–195 MB) once, checks it against the SHA-256 in its add-on's `module.json`, and unpacks only the model files into `%APPDATA%\Soundboard\translation\`. Translating what you say then happens on your PC |
| Always | `127.0.0.1` only | browser audio sink and module link, each guarded by a random per-launch secret |
| Always | a local named pipe (`Soundboard.App`) | single instance: a second launch asks the first to come to the front. It only accepts that one request |

No telemetry, analytics, crash upload or update pings. Logs and settings stay in
`%APPDATA%\Soundboard\`.

## For users filing bug reports

`%APPDATA%\Soundboard\soundboard.log` contains file paths that include your
Windows user name. Skim it and replace anything personal before attaching it to a
public issue.
