# The sound store's server

The Store tab (`soundboard/store.py`, `soundboard/ui/storetab.py`) talks to this: a
[Cloudflare Worker](https://developers.cloudflare.com/workers/) with the sounds' files
in Workers KV and the list, votes and reports in D1. Both fit Cloudflare's free plan,
and neither needs a payment card on the account.

## What it does

| Route | What |
|---|---|
| `GET /v1/sounds?sort=top\|new\|trending&cat=&q=&offset=` | a page (50) of the sounds that are live, in one category or all; *trending* = hot on the synced sites now plus this week's 👍 here |
| `GET /v1/categories` | how many live sounds each category has |
| `GET /v1/sounds/<id>/file` | one sound's file |
| `POST /v1/sounds` | share a sound (form: `file`, `name`, `tags`, `agree=own-cc0-v1`); it waits for review |
| `POST /v1/links` | share a link (JSON: `link`, `name`, `tags`, `agree=link-v1`): only the link is kept, and only to known video and sound sites; it waits for review |
| `POST /v1/sounds/<id>/vote` | `{"value": 1 \| -1 \| 0}`, one per install |
| `POST /v1/sounds/<id>/report` | `{"reason": "copyright" \| "offensive" \| "broken" \| "other"}`; 3 reports take it off until it's looked at again |
| `GET /v1/voices?kind=fx\|ai\|setup&sort=top\|new\|trending&q=&offset=` | a page (50) of community voices with their settings: voice changer voices, AI voices and voice setups |
| `POST /v1/voices` | share a voice (JSON: `kind`, `name`, `about`, `emoji`, `tags`, `data`); live at once (below) |
| `POST /v1/voices/<id>/vote`, `/report` | as for sounds; 3 reports hide it until the owner looks |
| `GET /v1/chat?after=N&wait=1` | the Chat tab's room: messages after number N (held up to 20 s until one arrives); names are picked by the server from the install and per-launch ids (`X-Onion-Session`) |
| `POST /v1/chat` | `{"text": "..."}`: say something (280 characters, no links, rate-limited) |
| `POST /v1/chat/<n>/report` | report message n (10 reports per address in 10 minutes); 3 people from different addresses mute its author, and the address it came from, for an hour |
| `/v1/admin/chat`, `/off`, `/ban` | the owner's: reports, the kill switch (`{"off": true}`), bans (`{"who": "<hash>"}`: an install's hash also bans the addresses the room saw it speak from; an address hash from the reports bans just that; `"ban": false` lifts it) |
| `GET /admin` | the review page: listen, approve, reject |
| `/v1/admin/...` | the review page's calls (`Authorization: Bearer <ADMIN_TOKEN>`), and `POST /v1/admin/import` to add a sound straight to the store |
| `GET /v1/admin/queue?status=pending\|live\|rejected\|all&q=&offset=` | the owner's: sounds (200 a page) with their reports and hashes, and how many there are of each status |
| `POST /v1/admin/sync` | the owner's: run one sync step now (below) |
| `GET /v1/admin/voices?status=hidden\|live\|removed`, `POST /v1/admin/voices/<id>` | the owner's: voices (hidden ones by default, most reported first); `{"action": "live" \| "removed"}` |
| `GET /v1/admin/log?before=&kind=&sound=&who=&limit=` | the owner's: the action log, newest first (uploads, links, votes, reports, reviews, and the first time each rate limit is hit in a day), filtered by kind, sound, or an address / install hash |

The app sends a random id it made itself (`X-Onion-Install`); the server keeps only a
salted hash of it, and of the address, for one vote per install and the daily limits
(10 uploads per install, 20 per address, 400 votes per address, and at most 3 installs
from one address ever counted on one sound). The review queue takes 1,000 sounds or 300 MB
of files, then refuses more until some are reviewed. Files (MP3, OGG, WAV, FLAC, up to
4 MB) are walked from end to end in `src/audio.js`: every MP3 frame, WAV chunk, Ogg page
and FLAC header block has to be in place, tags and cover art may take 2 MB at most, and
a file with web page, script or program text anywhere in it is refused. Names and tags
lose markup characters (``<>`{}\``) and invisible or right-to-left ones. A served file is
always a download (`content-disposition: attachment`, a sandboxing CSP, `nosniff`), and
the app keeps one only when it starts like the sound it was told about. The same file
can't be shared twice. A rejected sound's file is deleted at once.

**Community voices** (`src/voices.js`) are settings, never files or recordings, so they
go live with no review. Nothing is kept as it was sent: the server rebuilds each voice
from the fields it checked (known kinds, effect and setting names of plain letters, every
number finite and pulled into range, an AI voice's 1–4 speakers, a language code) and
drops everything else. Names (32 characters) and abouts (140) become one plain line: no
control or format characters (bidi overrides, zero-width joiners), no piles of combining
marks, and the chat's blocked words and links are refused. The same settings can't be
shared twice. 20 a day per install, 40 per address. The app checks every voice again
when it takes one in.

**Sounds from other sites.** Every 10 minutes a cron step (`src/sync.js`) reads Myinstants'
trending page and one page of one of its categories (5 pages of 10 categories, a cycle
about every 8 hours) and adds what's new as live *links*: the name, the link and the
category, never the file (the app plays and downloads it from Myinstants, as a pasted link).
They're voted on, reported and reviewed like any other sound, and a later sync never brings
back one that was rejected or taken off by reports.

Every action is logged with its time and those hashes (never the address or id itself),
for the owner to see who did what. A daily cron (`wrangler.toml`) deletes log lines older
than 90 days and old rate-limit counters.

## Putting it online

With Node.js installed, from this folder:

```sh
npx wrangler login
npx wrangler d1 create onion-board-store          # paste its database_id into wrangler.toml
npx wrangler kv namespace create FILES            # paste its id into wrangler.toml
npx wrangler d1 execute onion-board-store --remote --file schema.sql
npx wrangler secret put ADMIN_TOKEN               # a long random password for /admin
npx wrangler secret put SALT                      # another long random string, never changed
npx wrangler deploy
```

## Trying it on your own PC

Put `ADMIN_TOKEN=...` and `SALT=...` in a `.dev.vars` file here (git-ignored), then:

```sh
npx wrangler d1 execute onion-board-store --local --file schema.sql
npx wrangler dev --local
```

## Tests

`node --test "test/*.test.mjs"` (Node 22.5 or newer; CI runs them): the routes against
Node's built-in SQLite standing in for D1 and a `Map` for KV.

## Changing the database

`schema.sql` is the whole schema for a new database, and safe to run again. A change to
an existing table goes in `migrations/` too, numbered: run each new file once, before
`schema.sql` (`npx wrangler d1 execute onion-board-store --remote --file migrations/<file>`).
