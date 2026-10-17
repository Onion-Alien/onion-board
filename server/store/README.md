# The sound store's server

The Store tab (`soundboard/store.py`, `soundboard/ui/storetab.py`) talks to this: a
[Cloudflare Worker](https://developers.cloudflare.com/workers/) with the sounds' files
in Workers KV and the list, votes and reports in D1. Both fit Cloudflare's free plan,
and neither needs a payment card on the account.

## What it does

| Route | What |
|---|---|
| `GET /v1/sounds?sort=top\|new&q=&offset=` | a page (50) of the sounds that are live |
| `GET /v1/sounds/<id>/file` | one sound's file |
| `POST /v1/sounds` | share a sound (form: `file`, `name`, `tags`, `agree=own-cc0-v1`); it waits for review |
| `POST /v1/links` | share a link (JSON: `link`, `name`, `tags`, `agree=link-v1`): only the link is kept, and only to known video and sound sites; it waits for review |
| `POST /v1/sounds/<id>/vote` | `{"value": 1 \| -1 \| 0}`, one per install |
| `POST /v1/sounds/<id>/report` | `{"reason": "copyright" \| "offensive" \| "broken" \| "other"}`; 3 reports take it off until it's looked at again |
| `GET /v1/chat?after=N&wait=1` | the Chat tab's room: messages after number N (held up to 20 s until one arrives); names are picked by the server from the install and per-launch ids (`X-Onion-Session`) |
| `POST /v1/chat` | `{"text": "..."}`: say something (280 characters, no links, rate-limited) |
| `POST /v1/chat/<n>/report` | report message n (10 reports per address in 10 minutes); 3 people from different addresses mute its author, and the address it came from, for an hour |
| `/v1/admin/chat`, `/off`, `/ban` | the owner's: reports, the kill switch (`{"off": true}`), bans (`{"who": "<hash>"}`: an install's hash also bans the addresses the room saw it speak from; an address hash from the reports bans just that; `"ban": false` lifts it) |
| `GET /admin` | the review page: listen, approve, reject |
| `/v1/admin/...` | the review page's calls (`Authorization: Bearer <ADMIN_TOKEN>`), and `POST /v1/admin/import` to add a sound straight to the store |
| `GET /v1/admin/queue?status=pending\|live\|rejected\|all&q=&offset=` | the owner's: sounds (200 a page) with their reports and hashes, and how many there are of each status |
| `GET /v1/admin/log?before=&kind=&sound=&who=&limit=` | the owner's: the action log, newest first (uploads, links, votes, reports, reviews, and the first time each rate limit is hit in a day), filtered by kind, sound, or an address / install hash |

The app sends a random id it made itself (`X-Onion-Install`); the server keeps only a
salted hash of it, and of the address, for one vote per install and the daily limits
(10 uploads per install, 20 per address, 400 votes per address, and at most 3 installs
from one address ever counted on one sound). The review queue takes 1,000 sounds or 300 MB
of files, then refuses more until some are reviewed. Files are checked by
their first bytes (MP3, OGG, WAV, FLAC), up to 4 MB, and the same file can't be
shared twice. A rejected sound's file is deleted at once.

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
