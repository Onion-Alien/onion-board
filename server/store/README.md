# The sound store's server

The Store tab (`soundboard/online/store.py`, `soundboard/ui/store/storetab.py`) talks to this: a
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
| `GET /admin` | the review page: listen, approve, reject |
| `/v1/admin/...` | the review page's calls (`Authorization: Bearer <ADMIN_TOKEN>`), and `POST /v1/admin/import` to add a sound straight to the store |
| `GET /v1/admin/queue?status=pending\|live\|rejected\|all&q=&offset=` | the owner's: sounds (200 a page) with their reports and hashes, and how many there are of each status |
| `POST /v1/admin/sync` | the owner's: run one sync step now (below) |
| `GET /v1/admin/voices?status=hidden\|live\|removed`, `POST /v1/admin/voices/<id>` | the owner's: voices (hidden ones by default, most reported first); `{"action": "live" \| "removed"}` |
| `GET /v1/admin/log?before=&kind=&sound=&who=&limit=` | the owner's: the action log, newest first (uploads, links, votes, reports, reviews, and the first time each rate limit is hit in a day), filtered by kind, sound, or an address / install hash |

The app sends a random id it made itself (`X-Onion-Install`); the server keeps only a
salted hash of it, and of the address, for one vote per install and the daily limits
(10 uploads per install, 20 per address, 400 votes per address, and at most 3 installs
from one address ever counted on one sound). An IPv6 address counts as its /64 (one home or
phone gets a whole /64), and a report as its /48, so new addresses from one place don't get
around a limit or take a sound off alone. List pages and files are limited to 90 a minute
per address (Cloudflare's rate limiter, `READS` in `wrangler.toml`), lists page at most
2,000 deep, and a search looks words of 3 letters or more up in an index of every 3 letters
(`sounds_fts`, `voices_fts`), so no one can use up the free plan's daily reads for everyone. The review queue takes 1,000 sounds or 300 MB
of files, then refuses more until some are reviewed. Files (MP3, OGG, WAV, FLAC, up to
4 MB) are walked from end to end in `src/audio.js`: every MP3 frame, WAV chunk, Ogg page
and FLAC header block has to be in place, tags and cover art may take 2 MB at most, and
a file with web page or script text, or a program, anywhere in it is refused. Names and tags
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
marks, and the owner's blocked words and links are refused. The same settings can't be
shared twice. 20 a day per install, 40 per address, and 300 a day from everyone. The app checks every voice again
when it takes one in.

**Sounds from other sites.** Every 10 minutes a cron step (`src/sync.js`) reads Myinstants'
trending page and one page of one of its categories (5 pages of 10 categories, a cycle
about every 8 hours) and adds what's new as live *links*: the name, the link and the
category, never the file (the app plays and downloads it from Myinstants, as a pasted link).
They're voted on, reported and reviewed like any other sound, and a later sync never brings
back one that was rejected or taken off by reports. Anyone can put a sound on Myinstants, so
a name with a link or one of the owner's blocked words is left out, as it would be from
someone sharing it here.

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
A file that says so runs after `schema.sql` instead (`0003-search.sql` fills the search
index the schema makes with the sounds and voices already there).

D1's free plan reads at most 5 million rows a day, and every row a query looks at counts.
A list page goes through an index made for its order (`sounds_top`, `sounds_trend`, ... in
`schema.sql`), so it reads about one page of rows; the category chips' counts are worked
out by the cron once an hour. A new list order or filter needs its own index, and the
query-plan test in `test/store.test.mjs` fails when one reads the whole table.
