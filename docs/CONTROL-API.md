# Control API

Onion Board can be driven by other programs on the same PC: a Stream Deck, Streamer.bot,
Firebot, Touch Portal, Bitfocus Companion, SAMMI, Mix It Up, TikFinity, AutoHotkey or
your own script. Turn it on in **Settings → Remote → Remote control**. The *Streamer
guide* and *Copy AI prompt* buttons there help you set it up.

`/api/help` always lists every endpoint with what it takes, straight from the app.

## The basics

- Address: `http://127.0.0.1:7474` (the port can be changed in Settings). It only
  listens on this PC; never forward it to the internet.
- Every request needs the key shown in Settings, as `?token=KEY`, an `X-Token: KEY`
  header or `Authorization: Bearer KEY`.
- GET or POST, every answer is JSON. A POST can send its values as a JSON object or a
  form instead of in the URL (a value in the URL wins).
- Switches take `on=1`, `on=0` or `on=toggle` (no `on=`: toggle).
- Names (sounds, categories, voices) match exactly, any case. A wrong sound or voice
  name answers 404 with `did_you_mean`.
- Errors: 400 a value it can't use, 401 wrong key, 404 no such thing, 409 not ready (a
  sound still loading, a tab switched off), 413 a body over 64 KB, 503 the app was busy
  (safe to retry).

## Sounds, voice and everything else

| Endpoint | Does |
|---|---|
| `/api/status` | what's playing and queued, the category, live / voice / mic / hear, volume, live speed and effects, sound mode, radio |
| `/api/sounds[?q=&category=]` | every sound with its hotkey, categories, colour, volume, loop, press mode, plays, length, effects |
| `/api/play?name=` / `?id=` | play a sound |
| `/api/stop[?name=]` | stop one sound, or everything |
| `/api/pause`, `/api/random[?category=]`, `/api/last`, `/api/queue` | pause, a random sound, the last one again, the play queue |
| `/api/category`, `/api/volume` | the category showing, the sounds' volume |
| `/api/live`, `/api/mic`, `/api/hear`, `/api/mic_gate` | the Live / Muted panic switch, your mic, *Hear what they hear*, *Mute my mic while a sound plays* |
| `/api/voice?name=` / `?random=1` `[&seconds=30]` | the voice changer: a voice, a random one, for a while or for good |
| `/api/voices`, `/api/say?text=` | the voices, a line in the computer voice |
| `/api/setups`, `/api/setup?name=&tab=` | *My voice combos* on the Sounds, Radio or Apps live controls |
| `/api/speed`, `/api/pitch`, `/api/effects`, `/api/reset` | live speed, pitch and effects on every sound |
| `/api/mode` | who's listening (Game, Voice chat, Clean, Advanced) |
| `/api/apps`, `/api/app?name=&send=&volume=` | the Apps tab: send one program's sound |
| `/api/hotkeys` | every global hotkey off (to type) or on |
| `/api/replay` | save the instant replay as a sound |
| `/api/stations`, `/api/radio…` | the Radio tab |

## Chat commands: `/api/chat`

Have your bot send **every chat line** here:

```
/api/chat?user=NAME&message=MESSAGE&mod=0&sub=0&vip=0&broadcaster=0&token=KEY
```

(`badges=` as Twitch sends them, or `role=mod`, work too.) Onion Board runs the commands
itself:

| Command | Does | Who by default |
|---|---|---|
| `!sound <name>` | plays it (an exact name, or the one sound whose name starts with or holds it) | everyone |
| `!sounds` | lists the sounds chat may play | everyone |
| `!random [category]` | a random sound | everyone |
| `!say <text>` | says it in the computer voice | off |
| `!voice <name>` | a voice for 30 seconds | mods |
| `!stop` | stops every sound | mods |

The answer says whether it ran (`handled`), why not (`reason`, and `wait` seconds on a
cooldown) and `reply`: a line for your bot to post back in chat (empty: post nothing).

Change the rules with `/api/chat_rules` (alone: what they are now):

- who may use each: `sound=`, `sounds=`, `random=`, `say=`, `voice=`, `stop=` set to
  `everyone`, `subs`, `vips`, `mods`, `broadcaster` or `off`
- `tts=everyone` (or subs…): every chat line that isn't a command is read out, as
  `tts_format=` says (`{user} says {message}`)
- `user_cooldown=30`, `cooldown=5`: seconds between one viewer's commands and between
  anyone's (mods and the broadcaster don't wait)
- `category=Chat`: chat may only play sounds from this category
- `blocked=word,word`: a line with one of these does nothing; links are read as "link"
  unless `links=1`; `max_length=200` characters are spoken at most
- `prefix=!`, `voice_seconds=30`, `reply_list=`, `reply_missing=`, `on=0` (all off),
  `reset=1`

## Alerts and donations: `/api/event`

Send each follow, sub, gift sub, cheer, raid, donation, channel-point redemption or
TikTok gift:

```
/api/event?type=donation&user=NAME&amount=5&currency=USD&message=MESSAGE&id=ID&token=KEY
```

Types: `follow`, `sub`, `resub`, `gift_sub`, `cheer`, `raid`, `donation`, `redeem`,
`gift`, `like`, `share`, `hype_train`, or a name of your own. Other tools' names are
understood too (`tip`, `bits`, `subscriber`, `channel.follow`, `kofi`, `superchat`…). An
`id` that came before is skipped, so an alert sent twice plays once. `test=1` fills in a
test viewer (and is a follow when there's no `type=`).

What each type does is set once with `/api/alerts`:

```
/api/alerts?type=follow&sound=Airhorn
/api/alerts?type=donation&say=Thanks {user} for {amount}: {message}
/api/alerts?type=donation&min=50&category=Big%20moments
/api/alerts?type=redeem&voice=Chipmunk&voice_seconds=60
```

`sound=` plays one, `category=` a random one from it (`*`: any), `say=` speaks a line
(`{user}`, `{amount}`, `{currency}`, `{message}`, `{reward}`, `{months}`, `{count}`,
`{tier}`), `voice=` turns a voice on for `voice_seconds`. With `min=` the rule only
counts from that amount up; the highest one reached is used. `clear=1` removes a rule,
`on=0` switches every alert off. `/api/alerts` alone lists every rule; `?type=raid` alone
lists that type's rules (an empty list when it has none). A request can also say it all itself
(`/api/event?type=raid&sound=Airhorn`), which needs nothing set.

Viewer text that's spoken goes through the chat rules' blocked words, links and length.

### Sending the JSON other tools make

A POST to `/api/event` may carry what these send, as it is: **Twitch EventSub**
notifications, **StreamElements** (widget and socket events), **Streamlabs** socket
events and **Ko-fi** webhooks (its `data=` form). Those services send to the internet,
not to your PC, so let Streamer.bot or Firebot receive them and forward them here.

### Where each tool sends a request

- **Streamer.bot:** a sub-action *Core → Network → Fetch URL*. Chat: a *Twitch → Chat
  Message* trigger calling `/api/chat?user=%user%&message=%rawInput%&mod=%isModerator%&sub=%isSubscriber%&vip=%isVip%`.
  Alerts: each event's trigger calling `/api/event?type=…` with its variables.
- **Firebot:** the *HTTP Request* effect on events and commands.
- **TikFinity:** *Actions → Call webhook*: `/api/event?type=gift&user={nickname}&reward={giftname}&count={repeatcount}`.
- **Mix It Up, SAMMI:** their web request command.
- **Stream Deck:** the [Onion Board plugin](https://github.com/Onion-Alien/onion-board/releases/latest/download/com.onionalien.onionboard.streamDeckPlugin) (`streamdeck/`,
  on every release) needs no links at all. Without it: *System → Website*, ticking *GET
  request in background*.

URL-encode anything a viewer typed (a space is `%20`).

## The feed: `/api/feed`

What chat commands and alerts did, oldest first, for an overlay or a bot:
`/api/feed?since=LAST_ID` answers `events` (`id`, `time`, `kind`, `user`, the sound's
`name`, what was said…) and `last`, the id to ask from next time. It's kept in memory
only, the last 200.
