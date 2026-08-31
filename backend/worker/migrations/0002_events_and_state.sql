-- Event-sourced progress. Replaces the single `progress` table, which was the
-- Google Sheet's shape: one row per item holding counters, a baked SRS stage,
-- and settings rows pretending to be progress.
--
-- Three tables now hold what one did:
--   review_events  immutable facts — the system of record
--   item_state     derived read model, rebuildable from events
--   user_meta      settings that were never progress
--
-- The old `progress` table is deliberately left in place as a snapshot.

-- Identity. Kept minimal on purpose: initials remain the natural key for now,
-- so this changes nothing today. It exists so that fixing identity later is a
-- change to one row per user rather than a rekey of every progress row.
CREATE TABLE IF NOT EXISTS users (
  user_id      TEXT PRIMARY KEY,          -- currently the initials
  display_name TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL,
  last_seen_at TEXT NOT NULL DEFAULT ''
);

-- Append-only. Never updated, never deleted in normal operation.
--
-- Mode is a column now. It used to be the third character of every id
-- ("es0…" speech, "es1…" lyrics), which forced normalizeMode() to infer it by
-- string position and crossModeProgressId() to flip a character to find the
-- same word in the other mode. item_id is the bare card id; lang_code keeps
-- the two-letter prefix so the client's composite fullId round-trips exactly.
--
-- idempotency_key is the sync queue's own key. UNIQUE plus INSERT OR IGNORE
-- makes a replayed write a no-op at the database level, which is the same
-- failure class that silently dropped answers when a 403 parked the queue.
CREATE TABLE IF NOT EXISTS review_events (
  event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id         TEXT NOT NULL,
  item_id         TEXT NOT NULL,
  item_type       TEXT NOT NULL,            -- word | sense | mwe | clitic | lemma
  parent_id       TEXT NOT NULL DEFAULT '',
  lang_code       TEXT NOT NULL,            -- es, pl, fr …
  language        TEXT NOT NULL,            -- spanish, polish …
  mode            TEXT NOT NULL,            -- speech | lyrics
  source          TEXT NOT NULL DEFAULT '',
  release_id      TEXT NOT NULL DEFAULT '',
  outcome         TEXT NOT NULL,            -- correct | incorrect | revealed | skipped
  answered_at     TEXT NOT NULL,
  session_id      TEXT NOT NULL DEFAULT '',
  client_build    TEXT NOT NULL DEFAULT '',
  -- 'synthetic' marks the seed rows seeded from the old counters at migration.
  -- Individual answers before the cutover were never recorded — only totals and
  -- the last correct/wrong timestamps — so real history begins here.
  origin          TEXT NOT NULL DEFAULT 'live',
  idempotency_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_events_user_item ON review_events(user_id, item_id, mode);
CREATE INDEX IF NOT EXISTS idx_events_user_time ON review_events(user_id, answered_at);
CREATE INDEX IF NOT EXISTS idx_events_session   ON review_events(session_id);

-- Derived. Every column here is a function of review_events, so a change to
-- the scheduling algorithm is a replay rather than a data loss.
--
-- due_at is the point of the whole exercise: the client currently loads every
-- progress row and computes due-ness for ~10k cards in JavaScript on each
-- setup render. Stored and indexed, "what is due" becomes a range scan and the
-- per-set counters become one GROUP BY.
CREATE TABLE IF NOT EXISTS item_state (
  user_id           TEXT NOT NULL,
  lang_code         TEXT NOT NULL,
  item_id           TEXT NOT NULL,
  mode              TEXT NOT NULL,
  item_type         TEXT NOT NULL,
  parent_id         TEXT NOT NULL DEFAULT '',
  language          TEXT NOT NULL DEFAULT '',
  source            TEXT NOT NULL DEFAULT '',
  label             TEXT NOT NULL DEFAULT '',
  correct_count     INTEGER NOT NULL DEFAULT 0,
  incorrect_count   INTEGER NOT NULL DEFAULT 0,
  first_seen_at     TEXT NOT NULL DEFAULT '',
  last_seen_at      TEXT NOT NULL DEFAULT '',
  last_correct_at   TEXT NOT NULL DEFAULT '',
  last_incorrect_at TEXT NOT NULL DEFAULT '',
  srs_stage         INTEGER,                 -- NULL = never explicitly staged
  due_at            TEXT,                    -- NULL = not scheduled (unseen)
  unresolved        INTEGER NOT NULL DEFAULT 0,  -- last answer was wrong
  updated_at        TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, lang_code, item_id, mode)
);

CREATE INDEX IF NOT EXISTS idx_state_due       ON item_state(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_state_user_type ON item_state(user_id, item_type, mode);
CREATE INDEX IF NOT EXISTS idx_state_parent    ON item_state(user_id, parent_id);
-- Cross-mode lookups are a query now rather than a string transform.
CREATE INDEX IF NOT EXISTS idx_state_item      ON item_state(user_id, lang_code, item_id);

-- Settings that were living in the progress table as item_type='meta', which
-- is why the old row key needed a second branch and why `value` had to hold
-- mixed types.
CREATE TABLE IF NOT EXISTS user_meta (
  user_id    TEXT NOT NULL,
  scope      TEXT NOT NULL DEFAULT '',   -- e.g. "spanish|lyrics|bad-bunny"
  key        TEXT NOT NULL,              -- level-done, level-estimate …
  meta_id    TEXT NOT NULL DEFAULT '',   -- the level id the key applies to
  value_json TEXT NOT NULL DEFAULT 'null',
  updated_at TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, scope, key, meta_id)
);

-- Flags move out of the spreadsheet. The sheet stays as an export for triage,
-- but it is no longer the system of record — that is what forced 42 columns
-- and two in-place schema migrations.
--
-- The ~29 attribute columns collapse into payload_json: they are a snapshot of
-- how the card looked when flagged, read whole during triage and never
-- filtered on. What is filtered on stays a real column.
CREATE TABLE IF NOT EXISTS flags (
  flag_id          TEXT PRIMARY KEY,      -- client-generated, so retries dedupe
  user_id          TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  item_id          TEXT NOT NULL DEFAULT '',
  item_type        TEXT NOT NULL DEFAULT '',
  lang_code        TEXT NOT NULL DEFAULT '',
  language         TEXT NOT NULL DEFAULT '',
  mode             TEXT NOT NULL DEFAULT '',
  source           TEXT NOT NULL DEFAULT '',
  release_id       TEXT NOT NULL DEFAULT '',
  target           TEXT NOT NULL DEFAULT '',   -- sense | example | translation | lemma | card
  category         TEXT NOT NULL DEFAULT '',
  note             TEXT NOT NULL DEFAULT '',
  -- The answer that provoked the flag, when there is one. This is what lets a
  -- bad card be told apart from a card the learner simply did not know.
  event_id         INTEGER,
  payload_json     TEXT NOT NULL DEFAULT '{}',
  status           TEXT NOT NULL DEFAULT 'open',  -- open | accepted | rejected | fixed
  resolved_at      TEXT NOT NULL DEFAULT '',
  resolved_by      TEXT NOT NULL DEFAULT '',
  fixed_in_release TEXT NOT NULL DEFAULT '',
  exported_at      TEXT NOT NULL DEFAULT ''      -- last push to the audit sheet
);

CREATE INDEX IF NOT EXISTS idx_flags_status ON flags(status, created_at);
CREATE INDEX IF NOT EXISTS idx_flags_item   ON flags(item_id, mode);
CREATE INDEX IF NOT EXISTS idx_flags_event  ON flags(event_id);
