- **Connect Twitch.** Settings → Remote has a Twitch card: click *Connect Twitch*, say yes on
  twitch.tv, and Onion Board plays your sounds when viewers redeem channel points, cheer,
  follow, sub, gift subs or raid. Pick a sound (or a random one) for each channel point reward
  and each alert, right there. Chat can use !sound, !random and !sounds, and the answer is
  posted back in chat. No Streamer.bot or other bot needed. Twitch has its own switch in
  Settings > Privacy & security.
- The control API's `/api/alerts` takes `&reward=` for channel points, so each reward can play
  its own sound.
