-- For a database made before search had its own index (2026-10-19): run once, AFTER
-- schema.sql (which makes the index; new sounds and voices go into it by themselves).
--   npx wrangler d1 execute onion-board-store --remote --file migrations/0003-search.sql
INSERT INTO sounds_fts (rowid, id, name, tags) SELECT rowid, id, name, tags FROM sounds
  WHERE rowid NOT IN (SELECT rowid FROM sounds_fts);
INSERT INTO voices_fts (rowid, id, name, tags, about) SELECT rowid, id, name, tags, about
  FROM voices WHERE rowid NOT IN (SELECT rowid FROM voices_fts);
