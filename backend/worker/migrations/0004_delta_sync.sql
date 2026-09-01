-- Support incremental progress sync.
--
-- The client refetches every progress row on every startup — ~9,500 rows and a
-- 1.4 MB payload — to re-learn state that usually has not changed since the
-- last visit. That is the dominant consumer of D1's daily row-read allowance
-- and a large part of startup time.
--
-- With this index, "has anything changed?" is the last entry of a range scan,
-- and "what changed?" is a short scan from a timestamp. Both are O(rows that
-- actually changed) rather than O(everything the user has ever studied).
CREATE INDEX IF NOT EXISTS idx_state_user_updated ON item_state(user_id, updated_at);

-- The backfill left every row with the same updated_at, which is correct (they
-- all became current at the same instant) and harmless: a client syncing from
-- before then gets everything, exactly as a first sync should.
