- The mic helper and the mic effect's admin step can no longer be steered by a folder
  link another account on the PC puts in Onion Board's shared folders: they work through
  handles to folders they checked, and a link is removed, never followed. The helper
  updates once (one Windows prompt).
- The removal tool no longer follows a link someone put at `%ProgramData%\OnionBoard`.
- Names and titles from the web, other soundboards, backups and packs always show as the
  text they are: one that looked like HTML could make Windows contact another server,
  around the proxy, Tor and Offline mode.
- A board file from another soundboard that lists sounds on a network share no longer
  makes Windows connect to that server: those sounds are left out.
- A custom voice program that's a script (`.bat`, `.cmd`, `.ps1`) or a shell no longer
  gets the line to say on its command line, where Twitch chat could run commands; use
  `{text_file}` or the program's input instead.
- Twitch: a "no such sound" reply posted from your account goes through the blocked words
  and link rule first and counts for the cooldown, and a viewer's name read out in chat
  TTS is filtered too. Twitch signing you out also resets *Let the developer see this
  channel's name*.
- Backups no longer carry the auto push-to-talk key, Twitch chat rules, the store's vote
  id, privacy switches or this PC's Discord state, and a sound pack can't take a key every
  app uses (Space, a letter, Ctrl+C).
- Onion Pocket's firewall step adds one rule for Onion Board only, not a second one for
  any program on that port.
- Quitting only puts back a Discord that Onion Board set up itself.
- A voice server's key is never sent on to another site by a redirect, and a carrier's
  NAT or a tailnet (the shared address range) counts as the home network.
- Live voice no longer writes what you said into its log, and its log goes with the app
  log when *Keep an app log* is off.
- Admin steps start Windows' own tools from System32, never by name.
- The installer's Cancel for the extras stops them again.
