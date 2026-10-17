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
  pop INTEGER NOT NULL DEFAULT 0     -- how popular it is on its site (0-1000)
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

-- where each site's sync is up to: "<next page>:<cycles done>"
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
  kind TEXT NOT NULL,                -- upload | link | import | vote | report | hidden |
                                     -- approve | reject | rename | limit
  sound TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',       -- salted hash of the address ("owner" for /admin)
  install TEXT NOT NULL DEFAULT '',  -- salted hash of the install id
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS actions_at ON actions (at);
CREATE INDEX IF NOT EXISTS actions_sound ON actions (sound, id);

CREATE INDEX IF NOT EXISTS sounds_cat ON sounds (status, cat);
CREATE INDEX IF NOT EXISTS sounds_actions_votes ON actions (sound, kind, at);
