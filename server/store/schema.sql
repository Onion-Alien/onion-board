-- The sound store's database (Cloudflare D1). Apply with:
--   npx wrangler d1 execute onion-board-store --remote --file schema.sql
-- Every statement is safe to run again.

CREATE TABLE IF NOT EXISTS sounds (
  id TEXT PRIMARY KEY,               -- 12 hex characters
  name TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',     -- comma-separated, lower case
  ext TEXT NOT NULL,                 -- mp3, ogg, wav or flac; "link" for a shared link
  link TEXT NOT NULL DEFAULT '',     -- a shared link's web address (no file is kept)
  size INTEGER NOT NULL,             -- bytes
  sha256 TEXT NOT NULL UNIQUE,       -- the same file (or link) can't be shared twice
  author TEXT NOT NULL DEFAULT '',   -- "" = a community upload
  uploader TEXT NOT NULL,            -- salted hash of the uploader's install id
  ip TEXT NOT NULL,                  -- salted hash of the upload's address (rate limits)
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | live | rejected
  up INTEGER NOT NULL DEFAULT 0,
  down INTEGER NOT NULL DEFAULT 0,
  reports INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL,          -- unix seconds
  reviewed INTEGER,
  cat TEXT NOT NULL DEFAULT '',      -- one of index.js's CATS, or none
  source TEXT NOT NULL DEFAULT '',   -- "myinstants": synced from that site (sync.js); "" ours
  hot INTEGER NOT NULL DEFAULT 0,    -- how trending it is on its site now (fades each run)
  pop INTEGER NOT NULL DEFAULT 0,    -- how popular it is on its site (0-1000)
  likes INTEGER NOT NULL DEFAULT 0   -- this week's 👍 here (vote() sets it, the daily cron ages it)
);
CREATE INDEX IF NOT EXISTS sounds_status ON sounds (status, created);

CREATE TABLE IF NOT EXISTS votes (
  sound TEXT NOT NULL,
  voter TEXT NOT NULL,               -- salted hash of the install id
  value INTEGER NOT NULL,            -- 1 or -1
  PRIMARY KEY (sound, voter)
);

CREATE TABLE IF NOT EXISTS reports (
  sound TEXT NOT NULL,
  voter TEXT NOT NULL,               -- "ip:" + salted hash of the address: one per address
  reason TEXT NOT NULL DEFAULT '',
  created INTEGER NOT NULL,
  PRIMARY KEY (sound, voter)
);

-- which address each install voted on a sound from (a salted hash): only a few
-- installs from one address count per sound, however many ids it makes up
CREATE TABLE IF NOT EXISTS vote_from (
  sound TEXT NOT NULL,
  voter TEXT NOT NULL,               -- the install's hash ("x:" + address: the cap was hit)
  ip TEXT NOT NULL,
  PRIMARY KEY (sound, voter)
);
CREATE INDEX IF NOT EXISTS vote_from_ip ON vote_from (sound, ip);

-- where each site's sync is up to: "<next page>:<cycles done>"; also, under 'categories',
-- the category chips' counts (JSON) the cron works out each hour (index.js catCounts())
CREATE TABLE IF NOT EXISTS sync (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- per-day counters for rate limits: key = "<what>:<hash>", day = days since 1970
CREATE TABLE IF NOT EXISTS counters (
  key TEXT NOT NULL,
  day INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (key, day)
);

-- what happened in the store, newest last; the daily cron drops rows over 90 days old
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,               -- unix seconds
  kind TEXT NOT NULL,                -- upload | link | import | voice | vote | report | hidden |
                                     -- approve | reject | rename | limit
  sound TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',       -- salted hash of the address ("owner" for /admin)
  install TEXT NOT NULL DEFAULT '',  -- salted hash of the install id
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS actions_at ON actions (at);
CREATE INDEX IF NOT EXISTS actions_sound ON actions (sound, id);

-- the list's orders (index.js list()): with these a page of 50 reads about 50 rows instead of
-- every live sound (D1's free plan allows 5 million row reads a day). An ORDER BY has to
-- stay exactly as written here, or SQLite goes back to reading the whole table.
DROP INDEX IF EXISTS sounds_cat;     -- sounds_new_cat starts with the same columns
CREATE INDEX IF NOT EXISTS sounds_new_cat ON sounds (status, cat, created);
CREATE INDEX IF NOT EXISTS sounds_top ON sounds (status, (up - down) DESC, up DESC,
  (CASE WHEN source = '' THEN 500 ELSE pop END) DESC, created DESC);
CREATE INDEX IF NOT EXISTS sounds_top_cat ON sounds (status, cat, (up - down) DESC, up DESC,
  (CASE WHEN source = '' THEN 500 ELSE pop END) DESC, created DESC);
CREATE INDEX IF NOT EXISTS sounds_trend ON sounds (status, (hot + 40 * likes) DESC,
  (up - down) DESC, pop DESC);
CREATE INDEX IF NOT EXISTS sounds_trend_cat ON sounds (status, cat, (hot + 40 * likes) DESC,
  (up - down) DESC, pop DESC);
-- the few sounds still fading from a site's trending page (sync.js)
CREATE INDEX IF NOT EXISTS sounds_hot ON sounds (hot) WHERE hot > 0;
CREATE INDEX IF NOT EXISTS sounds_actions_votes ON actions (sound, kind, at);

-- community voices (src/voices.js): settings, never files; live as soon as they're shared,
-- hidden by reports. Their votes and reports share the sounds' tables (ids never clash:
-- both are 12 random hex characters).
CREATE TABLE IF NOT EXISTS voices (
  id TEXT PRIMARY KEY,               -- 12 hex characters
  kind TEXT NOT NULL,                -- fx (voice changer) | ai (AI voice) | setup
  name TEXT NOT NULL,
  about TEXT NOT NULL DEFAULT '',
  emoji TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',     -- comma-separated, lower case
  data TEXT NOT NULL,                -- the settings as voices.js rebuilt them (JSON)
  sha256 TEXT NOT NULL UNIQUE,       -- of kind + data: the same voice can't be shared twice
  uploader TEXT NOT NULL,            -- salted hash of the sharer's install id
  ip TEXT NOT NULL,                  -- salted hash of the address (rate limits)
  status TEXT NOT NULL DEFAULT 'live',   -- live | hidden (reports) | removed (owner)
  up INTEGER NOT NULL DEFAULT 0,
  down INTEGER NOT NULL DEFAULT 0,
  reports INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL,          -- unix seconds
  likes INTEGER NOT NULL DEFAULT 0   -- this week's 👍 (as the sounds')
);
CREATE INDEX IF NOT EXISTS voices_status ON voices (status, kind, created);
-- the lists' orders (voices.js list()), so a page reads its own rows, not every voice
CREATE INDEX IF NOT EXISTS voices_new ON voices (status, created);
CREATE INDEX IF NOT EXISTS voices_top ON voices (status, (up - down) DESC, up DESC, created DESC);
CREATE INDEX IF NOT EXISTS voices_top_kind ON voices (status, kind, (up - down) DESC, up DESC, created DESC);
CREATE INDEX IF NOT EXISTS voices_trend ON voices (status, likes DESC, (up - down) DESC, created DESC);
CREATE INDEX IF NOT EXISTS voices_trend_kind ON voices (status, kind, likes DESC, (up - down) DESC, created DESC);
