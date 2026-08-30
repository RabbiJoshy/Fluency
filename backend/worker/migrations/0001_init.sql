-- Fluency progress store. Mirrors the Apps Script "Progress" tab (schema v4)
-- one column per sheet header, so a row round-trips without reshaping.
--
-- row_key is the port of progressRowKey() in backend/GoogleAppsScript.js:326.
-- The Apps Script recomputed that key for every row on every request and
-- scanned linearly; here it is the primary key, so an upsert is one indexed
-- lookup. Keep the two definitions in sync -- if progressRowKey changes,
-- this column has to be rebuilt.
--
--   non-meta rows: user|item_type|mode|item_id
--   meta rows:     user|item_type|mode|source|language|label|item_id
CREATE TABLE IF NOT EXISTS progress (
  row_key        TEXT PRIMARY KEY,
  user           TEXT    NOT NULL,
  item_id        TEXT    NOT NULL,
  item_type      TEXT    NOT NULL,
  mode           TEXT    NOT NULL,
  source         TEXT    NOT NULL DEFAULT '',
  parent_word_id TEXT    NOT NULL DEFAULT '',
  label          TEXT    NOT NULL DEFAULT '',
  language       TEXT    NOT NULL DEFAULT '',
  correct        INTEGER NOT NULL DEFAULT 0,
  wrong          INTEGER NOT NULL DEFAULT 0,
  last_correct   TEXT    NOT NULL DEFAULT '',
  last_wrong     TEXT    NOT NULL DEFAULT '',
  last_seen      TEXT    NOT NULL DEFAULT '',
  schema_version INTEGER NOT NULL DEFAULT 4,
  srs_stage      TEXT    NOT NULL DEFAULT '',
  value          TEXT    NOT NULL DEFAULT ''
);

-- The whole point of the migration: 'load' and 'loadItems' filter by user and
-- item_type, which the sheet could only do by reading every row. These make it
-- a range scan over one user's rows, so a tenth user costs the first nine
-- nothing.
CREATE INDEX IF NOT EXISTS idx_progress_user_type   ON progress(user, item_type);
CREATE INDEX IF NOT EXISTS idx_progress_user_parent ON progress(user, parent_word_id);

-- Mirrors the "SongSets" tab (schema v2). findSongSetRow matched on
-- (user, source, set_id); that tuple is the primary key here.
CREATE TABLE IF NOT EXISTS song_sets (
  user              TEXT    NOT NULL,
  set_id            TEXT    NOT NULL,
  source            TEXT    NOT NULL,
  name              TEXT    NOT NULL DEFAULT '',
  language          TEXT    NOT NULL DEFAULT '',
  song_ids_json     TEXT    NOT NULL DEFAULT '[]',
  updated_at        TEXT    NOT NULL DEFAULT '',
  schema_version    INTEGER NOT NULL DEFAULT 2,
  artist_slugs_json TEXT    NOT NULL DEFAULT '[]',
  PRIMARY KEY (user, source, set_id)
);
