- Setup no longer has the *Test your local mix* card (Record 6s). To check what others
  get, use *Hear what they hear* or your chat app's microphone test.
- The side menu starts open on a new install, so the tabs show their names and not
  just icons. The button at the bottom still shuts it, and that choice is kept.

- Themes use clean, flat cards and a faint accent glow, without window grain,
  dark background fades or panel textures. High Contrast keeps its strong outlines.

- Quick setup: on the very first launch the guide starts by asking what you'll use Onion
  Board for. *Just sounds* changes nothing, *Streaming* adds the Apps tab and links
  the *Streamer guide* on the last step, *Competitive games* adds the Triggers tab
  (Onion Watch), and *Show me everything* adds every tab. It's asked once only; Settings →
  Tabs changes it later.
- Mini player shows connection status and a microphone mute switch. Expanded sidebar
  actions have labels; Setup puts devices first. Sounds groups
  library tools, Voice opens its presets on first visit, and secondary text reads more
  clearly. The full-width drop target is preserved.
- Add sounds and Record are flat icon buttons like the rest of the Sounds toolbar
  (Add sounds in the accent colour), with a divider before the search box.
- AI voices puts Start and live status at the top, with a wider voice picker,
  grouped pitch controls and shorter explanatory text in every language.
- The note that pops up above the player ("Added … to Sounds", device changes and so
  on) now sits centred over the page instead of jammed in the bottom-left corner on
  top of the sidebar, and is no wider than 560 px.
- YouTube and YouTube Music searches are about a second faster after the first one:
  YouTube's page settings are kept for an hour instead of being fetched before every
  search (Direct connection only; if a search with them fails, it's done again the old
  way, with fresh ones).
- *Straight into my mic*: when Windows starts running the mic effect after Onion Board
  opened (it loads it late sometimes), your sounds switch to it within a second instead
  of staying on the virtual cable until the app was restarted. If Windows takes the
  effect off, they go back to the cable the same way.
- The log no longer warns about "a native error was caught and survived" for Windows
  error code 0x8001010d and its kin: COM raises and handles those itself, so they're
  harmless. They no longer count as a crash at the next start either.
- The Voice tab's status bar (mic level and what others hear) moved from the top to
  just above the *type a line* bar at the bottom, and keeps the same height when a
  voice turns on or off, so nothing jumps.
