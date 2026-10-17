- The control API (Settings → Remote) takes chat commands: a bot like Streamer.bot sends
  each chat line to `/api/chat` and viewers can use `!sound`, `!sounds`, `!random`, `!say`,
  `!voice` and `!stop`, with cooldowns, who may use each, a category chat is kept to,
  blocked words, and a reply for the bot to post back. It can read chat aloud too.
- Alerts and donations: `/api/event` plays a sound, a random one from a category, says a
  thank-you or puts on a voice for a while for follows, subs, bits, raids, tips, channel
  points or TikTok gifts, set per type and amount with `/api/alerts`. It also reads what
  Twitch, StreamElements, Streamlabs and Ko-fi send. `/api/feed` lists what they did.
- The control API reaches the newer parts of the app: the Apps tab, My setups, a random
  voice (or any voice for some seconds), all hotkeys off / on, *Mute my mic while a sound
  plays*, and sound search. A POST can send its values as JSON or a form.
