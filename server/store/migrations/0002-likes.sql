-- For a database made before the lists got their indexes (2026-10-17): run once, before
-- schema.sql. (A new database gets these columns from schema.sql and skips this.)
--   npx wrangler d1 execute onion-board-store --remote --file migrations/0002-likes.sql
ALTER TABLE sounds ADD COLUMN likes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE voices ADD COLUMN likes INTEGER NOT NULL DEFAULT 0;
-- this week's 👍, as Trending counted them
UPDATE sounds SET likes = (SELECT count(*) FROM actions a WHERE a.sound = sounds.id
  AND a.kind = 'vote' AND a.detail = '1' AND a.at > unixepoch() - 7 * 86400)
  WHERE id IN (SELECT sound FROM actions WHERE kind = 'vote' AND at > unixepoch() - 7 * 86400);
UPDATE voices SET likes = (SELECT count(*) FROM actions a WHERE a.sound = voices.id
  AND a.kind = 'vote' AND a.detail = '1' AND a.at > unixepoch() - 7 * 86400)
  WHERE id IN (SELECT sound FROM actions WHERE kind = 'vote' AND at > unixepoch() - 7 * 86400);
