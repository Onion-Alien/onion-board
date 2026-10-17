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
  reviewed INTEGER
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
