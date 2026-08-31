/**
 * Storage layer for the event-sourced schema.
 *
 * The wire protocol is unchanged, so this module's job is translation:
 *
 *   wire                              storage
 *   ────                              ───────
 *   fullId "es1d6ffed1a"              lang_code "es" + mode "lyrics" + item_id "d6ffed1a"
 *   mode "normal" | "artist"          mode "speech" | "lyrics"
 *   cumulative correct/wrong          an event per delta, plus item_state
 *
 * Mode used to be the third character of every id, which is why the old code
 * had to infer it by string position and flip that character to find the same
 * word in the other mode. It is a column now; the prefix is reconstructed only
 * at the wire boundary so the client sees exactly what it always saw.
 */

export const ITEM_TYPES = ['sense', 'mwe', 'clitic', 'lemma'];
const SRS_INTERVAL_DAYS = [1, 3, 7, 14, 30, 60, 120];
const DAY_MS = 86400000;

/* ------------------------------- identity ------------------------------- */

export function wireMode(storedMode) {
  return storedMode === 'lyrics' ? 'artist' : 'normal';
}

export function storedMode(wire) {
  return wire === 'artist' || wire === 'lyrics' ? 'lyrics' : 'speech';
}

/** "es1d6ffed1a" -> { langCode:"es", mode:"lyrics", itemId:"d6ffed1a" } */
export function parseFullId(fullId) {
  const text = String(fullId ?? '');
  if (text.length < 4) return null;
  return {
    langCode: text.slice(0, 2),
    mode: text.charAt(2) === '1' ? 'lyrics' : 'speech',
    itemId: text.slice(3)
  };
}

export function toFullId(langCode, mode, itemId) {
  return `${langCode}${mode === 'lyrics' ? '1' : '0'}${itemId}`;
}

export function normalizeItemType(itemType) {
  const value = String(itemType || '').toLowerCase();
  if (value === 'expression' || value === 'mwe') return 'mwe';
  if (['sense', 'clitic', 'word', 'meta', 'lemma'].includes(value)) return value;
  return value || 'sense';
}

/** Legacy sheet names still arrive from cached clients. */
export function legacySheetMode(sheetName) {
  const name = String(sheetName || '');
  if (name.startsWith('Lyrics') || name.startsWith('BadBunny')) return 'artist';
  if (name.startsWith('UserProgress')) return 'normal';
  return '';
}

/* ------------------------------- schedule ------------------------------- */

const ts = value => {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

/**
 * The v1 ladder, unchanged from the client's getSrsStage/getProgressState —
 * computed once here instead of for every card on every render. Because it is
 * derived, changing this function and replaying review_events re-schedules
 * everything without touching the source data.
 */
export function computeSchedule({ correct, wrong, lastCorrect, lastWrong, lastSeen, srsStage }) {
  const c = Math.max(0, Number(correct) || 0);
  const w = Math.max(0, Number(wrong) || 0);
  const lc = ts(lastCorrect);
  const lw = ts(lastWrong);

  // An explicitly recorded stage and a derived one are not interchangeable:
  // '' means "no stage was ever written, derive it from the counts", and the
  // client still does that itself. Persisting a derived value as though it
  // were explicit would silently pin the card's schedule and override any
  // future change to the derivation. So keep them apart — explicitStage is
  // what gets stored, stage is what due_at is computed from.
  const parsed = Number(srsStage);
  const explicitStage = (srsStage !== null && srsStage !== undefined && srsStage !== ''
    && Number.isFinite(parsed) && parsed >= 0)
    ? Math.min(Math.floor(parsed), SRS_INTERVAL_DAYS.length)
    : null;

  let stage;
  if (explicitStage !== null) stage = explicitStage;
  else if (c === 0) stage = 0;
  else stage = Math.min(Math.max(1, c - w), SRS_INTERVAL_DAYS.length);

  let unresolved = false;
  if (w > 0 || lw > 0) unresolved = (lw > 0 || lc > 0) ? lw > lc : c === 0;

  let dueAt = null;
  if (unresolved) {
    dueAt = lastWrong || lastSeen || lastCorrect || null;
  } else if (lc > 0 && stage > 0) {
    dueAt = new Date(lc + SRS_INTERVAL_DAYS[stage - 1] * DAY_MS).toISOString();
  }
  return { stage, explicitStage, dueAt, unresolved: unresolved ? 1 : 0 };
}

/* -------------------------------- mapping ------------------------------- */

/** item_state row -> the shape `load` has always returned for a word. */
export function stateToWireWord(row) {
  return {
    word: row.label,
    wordId: toFullId(row.lang_code, row.mode, row.item_id),
    itemType: 'word',
    mode: wireMode(row.mode),
    language: row.language,
    correct: row.correct_count,
    wrong: row.incorrect_count,
    lastCorrect: row.last_correct_at,
    lastWrong: row.last_incorrect_at,
    lastSeen: row.last_seen_at,
    schemaVersion: 4,
    srsStage: row.srs_stage === null ? '' : row.srs_stage
  };
}

/** item_state row -> the shape `loadItems` has always returned. */
export function stateToWireItem(row) {
  return {
    itemId: toFullId(row.lang_code, row.mode, row.item_id),
    parentWordId: row.parent_id ? toFullId(row.lang_code, row.mode, row.parent_id) : '',
    itemType: row.item_type,
    mode: wireMode(row.mode),
    label: row.label,
    language: row.language,
    correct: row.correct_count,
    wrong: row.incorrect_count,
    lastCorrect: row.last_correct_at,
    lastWrong: row.last_incorrect_at,
    lastSeen: row.last_seen_at,
    schemaVersion: 4,
    srsStage: row.srs_stage === null ? '' : row.srs_stage
  };
}

const UPSERT_STATE = `
INSERT INTO item_state (
  user_id, lang_code, item_id, mode, item_type, parent_id, language, source,
  label, correct_count, incorrect_count, first_seen_at, last_seen_at,
  last_correct_at, last_incorrect_at, srs_stage, due_at, unresolved, updated_at
) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19)
ON CONFLICT(user_id, lang_code, item_id, mode) DO UPDATE SET
  item_type=excluded.item_type, parent_id=excluded.parent_id,
  language=excluded.language, source=excluded.source, label=excluded.label,
  correct_count=excluded.correct_count, incorrect_count=excluded.incorrect_count,
  first_seen_at=CASE WHEN item_state.first_seen_at='' THEN excluded.first_seen_at
                     ELSE item_state.first_seen_at END,
  last_seen_at=excluded.last_seen_at, last_correct_at=excluded.last_correct_at,
  last_incorrect_at=excluded.last_incorrect_at, srs_stage=excluded.srs_stage,
  due_at=excluded.due_at, unresolved=excluded.unresolved,
  updated_at=excluded.updated_at`;

export function upsertStateStmt(db, s) {
  return db.prepare(UPSERT_STATE).bind(
    s.userId, s.langCode, s.itemId, s.mode, s.itemType, s.parentId || '',
    s.language || '', s.source || '', s.label || '',
    s.correct, s.wrong, s.firstSeen || '', s.lastSeen || '',
    s.lastCorrect || '', s.lastWrong || '',
    s.stage === null || s.stage === undefined ? null : s.stage,
    s.dueAt, s.unresolved, new Date().toISOString()
  );
}

const INSERT_EVENT = `
INSERT OR IGNORE INTO review_events (
  user_id, item_id, item_type, parent_id, lang_code, language, mode, source,
  release_id, outcome, answered_at, session_id, client_build, origin,
  idempotency_key
) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,'live',?14)`;

export function insertEventStmt(db, e) {
  return db.prepare(INSERT_EVENT).bind(
    e.userId, e.itemId, e.itemType, e.parentId || '', e.langCode,
    e.language || '', e.mode, e.source || '', e.releaseId || '',
    e.outcome, e.answeredAt, e.sessionId || '', e.clientBuild || '',
    e.idempotencyKey || null
  );
}

/**
 * The client posts cumulative totals, not individual answers, so the events
 * are the difference between what it now claims and what we last stored.
 * Normally that is exactly one event; it is more when the offline queue
 * coalesced several answers to the same card into one write.
 */
export function deriveEvents(prior, incoming, meta) {
  const priorCorrect = prior ? prior.correct_count : 0;
  const priorWrong = prior ? prior.incorrect_count : 0;
  const gainedCorrect = Math.max(0, incoming.correct - priorCorrect);
  const gainedWrong = Math.max(0, incoming.wrong - priorWrong);
  const events = [];
  for (let i = 0; i < gainedCorrect; i++) {
    events.push({ ...meta, outcome: 'correct',
      answeredAt: incoming.lastCorrect || incoming.lastSeen || new Date().toISOString(),
      idempotencyKey: meta.idempotencyKey ? `${meta.idempotencyKey}:c${i}` : null });
  }
  for (let i = 0; i < gainedWrong; i++) {
    events.push({ ...meta, outcome: 'incorrect',
      answeredAt: incoming.lastWrong || incoming.lastSeen || new Date().toISOString(),
      idempotencyKey: meta.idempotencyKey ? `${meta.idempotencyKey}:w${i}` : null });
  }
  return events;
}
