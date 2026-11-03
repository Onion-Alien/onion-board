- Fix: a stuck extra download at the end of setup (FFmpeg, live voice-to-speech or Tor) could
  hang a silent install or update for good. Each one now stops after 10 minutes (live voice
  20) and is listed as skipped, with where to add it later.
