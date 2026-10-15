- Settings → Updates now has one *Helper programs* card listing FFmpeg, yt-dlp, the
  JavaScript engine and Tor, each saying how it updates. yt-dlp's *Reset downloader*
  is now called *Reinstall*, like FFmpeg's, and its *Update automatically* box (still
  off by default) sits on its row. Data & quality no longer repeats these.
- FFmpeg and Tor copies the app downloaded now follow app updates: when an update names
  a newer version, the app fetches it (checked against its SHA-256) at the next start.
  Tor waits while Connection is set to Tor.
