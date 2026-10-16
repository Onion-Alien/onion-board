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
| `GET /v1/chat?after=N&wait=1` | the Chat tab's room: messages after number N (held up to 20 s until one arrives) |
| `POST /v1/chat` | `{"text": "..."}`: say something (280 characters, no links, rate-limited) |
| `POST /v1/chat/<n>/report` | report message n; 3 different people mute its author for an hour |
| `/v1/admin/chat`, `/off`, `/ban` | the owner's: reports, the kill switch (`{"off": true}`), bans (`{"who": "<hash>"}`) |
| `GET /admin` | the review page: listen, approve, reject |
| `/v1/admin/...` | the review page's calls (`Authorization: Bearer <ADMIN_TOKEN>`), and `POST /v1/admin/import` to add a sound straight to the store |

The app sends a random id it made itself (`X-Onion-Install`); the server keeps only a
salted hash of it, and of the address, for one vote per install and the daily limits
(10 uploads per install, 20 per address, 400 votes per address). Files are checked by
their first bytes (MP3, OGG, WAV, FLAC), up to 4 MB, and the same file can't be
shared twice. A rejected sound's file is deleted at once.

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
