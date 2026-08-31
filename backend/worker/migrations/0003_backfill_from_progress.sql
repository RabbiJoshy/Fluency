-- Backfill the event/state tables from the legacy `progress` table.
--
-- Idempotent: every insert is OR IGNORE against a primary/unique key, so
-- re-running changes nothing. `progress` is read-only here and left intact.
--
-- ID transform. Legacy ids embed language and mode as a three-character
-- prefix: "es0" = Spanish speech, "es1" = Spanish lyrics, likewise "pl0".
-- Sparse items carry their parent's full id first ("es00040eeb4~k1:lemma:…"),
-- so the same prefix rule applies to them and to parent_word_id.
--   lang_code = substr(id,1,2)     mode = substr(id,3,1)     bare = substr(id,4)
-- Keeping lang_code means the client's composite id is reconstructed exactly,
-- so the wire protocol is unchanged.

INSERT OR IGNORE INTO users (user_id, display_name, created_at, last_seen_at)
SELECT DISTINCT user, user, COALESCE(MIN(last_seen), ''), COALESCE(MAX(last_seen), '')
FROM progress WHERE user <> '' GROUP BY user;

-- Settings out of the progress table.
INSERT OR IGNORE INTO user_meta (user_id, scope, key, meta_id, value_json, updated_at)
SELECT
  user,
  language || '|' || CASE WHEN mode = 'artist' THEN 'lyrics' ELSE 'speech' END
           || CASE WHEN source <> '' THEN '|' || source ELSE '' END,
  label,
  item_id,
  CASE WHEN value = '' THEN 'null'
       WHEN CAST(value AS REAL) = value OR value GLOB '-[0-9]*' OR value GLOB '[0-9]*' THEN value
       ELSE '"' || replace(value, '"', '\"') || '"' END,
  COALESCE(last_seen, '')
FROM progress
WHERE item_type = 'meta' AND user <> '';

-- Current state per item. Derives the same stage/due-ness the client computes
-- in getSrsStage/getProgressState today, so nothing changes for the learner —
-- it is just computed once here instead of per card on every render.
INSERT OR IGNORE INTO item_state (
  user_id, lang_code, item_id, mode, item_type, parent_id, language, source,
  label, correct_count, incorrect_count, first_seen_at, last_seen_at,
  last_correct_at, last_incorrect_at, srs_stage, due_at, unresolved, updated_at
)
WITH base AS (
  SELECT
    user AS user_id,
    substr(item_id, 1, 2) AS lang_code,
    substr(item_id, 4)    AS bare_id,
    CASE WHEN substr(item_id, 3, 1) = '1' THEN 'lyrics' ELSE 'speech' END AS mode2,
    item_type,
    CASE WHEN parent_word_id = '' THEN '' ELSE substr(parent_word_id, 4) END AS parent2,
    language, source, label,
    CAST(COALESCE(correct, 0) AS INTEGER) AS c,
    CAST(COALESCE(wrong, 0) AS INTEGER)   AS w,
    COALESCE(last_correct, '') AS lc,
    COALESCE(last_wrong, '')   AS lw,
    COALESCE(last_seen, '')    AS ls,
    CASE WHEN srs_stage = '' THEN NULL ELSE CAST(srs_stage AS INTEGER) END AS explicit_stage
  FROM progress
  WHERE item_type <> 'meta' AND user <> '' AND length(item_id) > 3
),
scored AS (
  SELECT *,
    -- The effective stage, used only to place due_at. It is NOT what gets
    -- stored: '' meant "never explicitly staged, derive from counts", and the
    -- client still derives it that way. Writing a derived value into srs_stage
    -- would pin the schedule and override any later change to the derivation.
    CASE
      WHEN explicit_stage IS NOT NULL AND explicit_stage >= 0 THEN MIN(explicit_stage, 7)
      WHEN c = 0 THEN 0
      ELSE MIN(MAX(1, c - w), 7)
    END AS stage,
    CASE WHEN explicit_stage IS NOT NULL AND explicit_stage >= 0
         THEN MIN(explicit_stage, 7) ELSE NULL END AS stored_stage,
    -- getProgressState: a later wrong than correct leaves the card unresolved;
    -- with no timestamps at all, never-correct counts as unresolved.
    CASE
      WHEN w > 0 OR lw <> '' THEN
        CASE WHEN lw <> '' OR lc <> ''
             THEN CASE WHEN lw > lc THEN 1 ELSE 0 END
             ELSE CASE WHEN c = 0 THEN 1 ELSE 0 END END
      ELSE 0
    END AS unres
  FROM base
)
SELECT
  user_id, lang_code, bare_id, mode2, item_type, parent2, language, source, label,
  c, w,
  CASE WHEN ls <> '' THEN ls WHEN lc <> '' THEN lc ELSE lw END,
  ls, lc, lw,
  stored_stage,
  -- Unresolved cards are due immediately; resolved ones follow the v1 ladder
  -- (1, 3, 7, 14, 30, 60, 120 days) from the last correct answer.
  CASE
    WHEN unres = 1 THEN COALESCE(NULLIF(lw, ''), NULLIF(ls, ''), NULLIF(lc, ''))
    WHEN lc <> '' AND stage > 0 THEN strftime('%Y-%m-%dT%H:%M:%SZ', lc,
      '+' || CASE stage WHEN 1 THEN 1 WHEN 2 THEN 3 WHEN 3 THEN 7 WHEN 4 THEN 14
                        WHEN 5 THEN 30 WHEN 6 THEN 60 ELSE 120 END || ' days')
    ELSE NULL
  END,
  unres,
  ls
FROM scored;

-- Seed events. Deliberately two rows per item at most, not one per answer:
-- the individual answers were never recorded, only totals and the last
-- correct/wrong timestamps, so emitting 11k events with invented timestamps
-- would be fabricated precision that later poisons any scheduling analysis.
-- Pre-cutover totals live in item_state; review_events is complete from the
-- cutover forward, and origin='synthetic' marks the boundary.
INSERT OR IGNORE INTO review_events (
  user_id, item_id, item_type, parent_id, lang_code, language, mode, source,
  outcome, answered_at, origin, idempotency_key
)
SELECT user_id, item_id, item_type, parent_id, lang_code, language, mode, source,
       'correct', last_correct_at, 'synthetic',
       'seed:correct:' || user_id || ':' || lang_code || ':' || item_id || ':' || mode
FROM item_state WHERE correct_count > 0 AND last_correct_at <> '';

INSERT OR IGNORE INTO review_events (
  user_id, item_id, item_type, parent_id, lang_code, language, mode, source,
  outcome, answered_at, origin, idempotency_key
)
SELECT user_id, item_id, item_type, parent_id, lang_code, language, mode, source,
       'incorrect', last_incorrect_at, 'synthetic',
       'seed:incorrect:' || user_id || ':' || lang_code || ':' || item_id || ':' || mode
FROM item_state WHERE incorrect_count > 0 AND last_incorrect_at <> '';
