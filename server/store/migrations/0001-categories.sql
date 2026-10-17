-- For a database made before categories and site syncs (2026-10-17): run once, before
-- schema.sql. (A new database gets these columns from schema.sql and skips this.)
--   npx wrangler d1 execute onion-board-store --remote --file migrations/0001-categories.sql
ALTER TABLE sounds ADD COLUMN cat TEXT NOT NULL DEFAULT '';
ALTER TABLE sounds ADD COLUMN source TEXT NOT NULL DEFAULT '';
ALTER TABLE sounds ADD COLUMN hot INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sounds ADD COLUMN pop INTEGER NOT NULL DEFAULT 0;
-- the sound packs' sounds get their pack's category
UPDATE sounds SET cat = 'esports' WHERE cat = '' AND (',' || tags || ',') LIKE '%,esports,%';
UPDATE sounds SET cat = 'spooky' WHERE cat = '' AND (',' || tags || ',') LIKE '%,halloween,%';
UPDATE sounds SET cat = 'podcast' WHERE cat = '' AND (',' || tags || ',') LIKE '%,podcast,%';
UPDATE sounds SET cat = 'streamer' WHERE cat = '' AND (',' || tags || ',') LIKE '%,streamer,%';
UPDATE sounds SET cat = 'memes' WHERE cat = '' AND (',' || tags || ',') LIKE '%,memes,%';
