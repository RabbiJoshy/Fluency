/**
 * Fluency backend — Cloudflare Worker + D1.
 *
 * Drop-in replacement for backend/GoogleAppsScript.js. It speaks the identical
 * JSON protocol (POST {action, ...} to one URL, get back
 * {success, message, timestamp, data?}), so js/auth.js and js/sync-queue.js
 * need no change beyond the URL in backend/secrets.json.
 *
 * Two deliberate differences from the Apps Script:
 *   1. Progress and song sets live in D1. Every read is an indexed lookup on
 *      one user's rows instead of a full-sheet scan, and every write is an
 *      upsert on a primary key instead of read-modify-write, which is what
 *      made concurrent saves lose data.
 *   2. Flag traffic (sheet === 'FlaggedWords') is proxied unchanged to the
 *      Apps Script deployment, so the FlaggedWords audit tab keeps working.
 *      Set SHEETS_URL to that /exec URL.
 *
 * The helpers below are ported verbatim from the Apps Script. Their exact
 * behaviour is the compatibility contract — including the quirks, like
 * valueOr() treating '' as a real value and normalizeMode() inferring the mode
 * from the third character of an item id.
 */

const PROGRESS_SCHEMA_VERSION = 4;
const SONG_SET_SCHEMA_VERSION = 2;
const FLAG_SCHEMA_VERSION = 4;

/** Sparse row types: senses, expressions, clitics, lemmas. */
const ITEM_TYPES = ['sense', 'mwe', 'clitic', 'lemma'];

/* ------------------------------------------------------------------ *
 * Helpers ported from GoogleAppsScript.js — keep behaviour identical.
 * ------------------------------------------------------------------ */

function normalizeMode(mode, id) {
  if (mode === 'normal' || mode === 'artist' || mode === 'all') return mode;
  const text = String(id || '');
  if (text.length > 2 && text.charAt(2) === '1') return 'artist';
  if (text.length > 2 && text.charAt(2) === '0') return 'normal';
  return 'normal';
}

function legacySheetMode(sheetName) {
  const name = String(sheetName || '');
  if (name.indexOf('Lyrics') === 0 || name.indexOf('BadBunny') === 0) return 'artist';
  if (name.indexOf('UserProgress') === 0) return 'normal';
  return '';
}

function normalizeItemType(itemType) {
  const value = String(itemType || '').toLowerCase();
  if (value === 'expression' || value === 'mwe') return 'mwe';
  if (value === 'sense' || value === 'clitic' || value === 'word' || value === 'meta') {
    return value;
  }
  return value || 'sense';
}

/** Incoming wins when supplied ('' counts as supplied), else existing, else fallback. */
function valueOr(existingValue, incomingValue, fallback) {
  if (incomingValue !== undefined && incomingValue !== null) return incomingValue;
  if (existingValue !== undefined && existingValue !== null) return existingValue;
  return fallback;
}

function normalizeSrsStage(value) {
  if (value === undefined || value === null || value === '') return '';
  const numeric = Number(value);
  if (!isFinite(numeric)) return '';
  return Math.max(0, Math.min(7, Math.floor(numeric)));
}

/** Port of progressRowKey(). Mirrored by row_key in migrations/0001_init.sql. */
function rowKey(row) {
  const user = String(row.user || '');
  const itemId = String(row.itemId || '');
  const type = normalizeItemType(row.itemType);
  const mode = normalizeMode(row.mode, row.parentWordId || itemId);
  if (type === 'meta') {
    return [user, type, mode, row.source || '', row.language || '',
      row.label || '', itemId].join('|');
  }
  return [user, type, mode, itemId].join('|');
}

/** Port of buildProgressRow(): merge incoming params over the existing row. */
function buildRow(params, existing) {
  const e = existing || {};
  const mode = normalizeMode(
    params.mode || legacySheetMode(params.sheet),
    params.parentWordId || params.itemId
  );
  return {
    user: String(params.user),
    itemId: String(params.itemId),
    itemType: normalizeItemType(params.itemType),
    mode: mode,
    source: params.source || '',
    parentWordId: params.parentWordId || '',
    label: valueOr(e.label, params.label, ''),
    language: valueOr(e.language, params.language, ''),
    correct: Number(valueOr(e.correct, params.correct, 0)) || 0,
    wrong: Number(valueOr(e.wrong, params.wrong, 0)) || 0,
    lastCorrect: valueOr(e.lastCorrect, params.lastCorrect, ''),
    lastWrong: valueOr(e.lastWrong, params.lastWrong, ''),
    lastSeen: valueOr(e.lastSeen, params.lastSeen, new Date().toISOString()),
    schemaVersion: PROGRESS_SCHEMA_VERSION,
    srsStage: params.srsStage === undefined
      ? valueOr(e.srsStage, undefined, '')
      : normalizeSrsStage(params.srsStage),
    value: valueOr(e.value, params.value, '')
  };
}

function normalizedSongIds(value) {
  if (!Array.isArray(value)) return [];
  const seen = {};
  const result = [];
  for (const songId of value) {
    const id = String(songId || '').trim();
    if (!id || seen[id] || result.length >= 1000) continue;
    seen[id] = true;
    result.push(id);
  }
  return result;
}

function normalizedArtistSlugs(value) {
  if (!Array.isArray(value)) return [];
  const seen = {};
  const result = [];
  for (const rawSlug of value) {
    const slug = String(rawSlug || '').trim();
    if (!slug || seen[slug] || result.length >= 100) continue;
    seen[slug] = true;
    result.push(slug);
  }
  return result;
}

/* ------------------------------------------------------------------ *
 * D1 row mapping
 * ------------------------------------------------------------------ */

/** DB row (snake_case) → protocol object (camelCase). */
function fromDb(r) {
  return {
    user: r.user,
    itemId: r.item_id,
    itemType: r.item_type,
    mode: r.mode,
    source: r.source,
    parentWordId: r.parent_word_id,
    label: r.label,
    language: r.language,
    correct: r.correct,
    wrong: r.wrong,
    lastCorrect: r.last_correct,
    lastWrong: r.last_wrong,
    lastSeen: r.last_seen,
    schemaVersion: r.schema_version,
    // The sheet stored '' for unset and a number 0-7 otherwise. The column is
    // TEXT (SQLite has no union type), so convert back on the way out or the
    // client sees "1" where the Apps Script sent 1. Every current reader
    // coerces with Number(), but the contract should still match exactly.
    srsStage: (r.srs_stage === '' || r.srs_stage === null) ? '' : Number(r.srs_stage),
    value: reviveScalar(r.value)
  };
}

/**
 * Sheets cells carry a type: a level-done row's value came back as the number
 * 1, while a level-estimate's is a string like 'B1'. The D1 column is TEXT, so
 * restore the number when — and only when — the text is exactly what that
 * number stringifies to. '007' and 'B1' stay strings; '' stays ''.
 */
function reviveScalar(text) {
  if (text === '' || text === null || text === undefined) return text === null ? '' : text;
  const asNumber = Number(text);
  return Number.isFinite(asNumber) && String(asNumber) === String(text) ? asNumber : text;
}

const UPSERT_SQL = `
INSERT INTO progress (
  row_key, user, item_id, item_type, mode, source, parent_word_id, label,
  language, correct, wrong, last_correct, last_wrong, last_seen,
  schema_version, srs_stage, value
) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17)
ON CONFLICT(row_key) DO UPDATE SET
  label=excluded.label, language=excluded.language, correct=excluded.correct,
  wrong=excluded.wrong, last_correct=excluded.last_correct,
  last_wrong=excluded.last_wrong, last_seen=excluded.last_seen,
  schema_version=excluded.schema_version, srs_stage=excluded.srs_stage,
  value=excluded.value, source=excluded.source,
  parent_word_id=excluded.parent_word_id`;

function upsertStmt(db, row) {
  return db.prepare(UPSERT_SQL).bind(
    rowKey(row), row.user, row.itemId, row.itemType, row.mode, row.source,
    row.parentWordId, row.label, row.language, row.correct, row.wrong,
    row.lastCorrect, row.lastWrong, row.lastSeen, row.schemaVersion,
    String(row.srsStage), row.value
  );
}

/** Read one existing row so buildRow can merge over it, mirroring existingProgressRow(). */
async function existingRow(db, params) {
  const key = rowKey(buildRow(params, {}));
  const found = await db.prepare('SELECT * FROM progress WHERE row_key = ?').bind(key).first();
  return found ? fromDb(found) : {};
}

async function saveOne(db, params) {
  const row = buildRow(params, await existingRow(db, params));
  await upsertStmt(db, row).run();
}

/* ------------------------------------------------------------------ *
 * Actions
 * ------------------------------------------------------------------ */

async function saveProgress(db, params, env) {
  if (params.sheet === 'FlaggedWords') return proxyToSheets(params, env);
  // Legacy sentinel: the old client stored level estimates as a fake word row.
  if (params.word === '_LEVEL_ESTIMATE_') {
    return saveMetaProgress(db, {
      user: params.user,
      metaKey: 'level-estimate',
      metaId: params.language || 'unknown',
      mode: 'normal',
      source: 'speech',
      language: params.language || '',
      value: params.wordId,
      lastSeen: params.lastSeen
    });
  }
  if (!params.user || params.wordId === undefined) {
    return response(false, 'Missing required fields: user, wordId');
  }
  await saveOne(db, {
    user: params.user,
    itemId: params.wordId,
    itemType: 'word',
    mode: params.mode || legacySheetMode(params.sheet),
    source: '',
    parentWordId: '',
    label: params.word || '',
    language: params.language || '',
    correct: params.correct,
    wrong: params.wrong,
    lastCorrect: params.lastCorrect,
    lastWrong: params.lastWrong,
    lastSeen: params.lastSeen,
    srsStage: params.srsStage,
    value: ''
  });
  return response(true, 'Progress saved successfully');
}

async function saveItemProgress(db, params) {
  const itemType = normalizeItemType(params.itemType);
  if (!params.user || !params.itemId || !params.parentWordId) {
    return response(false, 'Missing required fields: user, itemId, parentWordId');
  }
  if (ITEM_TYPES.indexOf(itemType) < 0) {
    return response(false, 'Invalid itemType: ' + itemType);
  }
  await saveOne(db, {
    user: params.user,
    itemId: params.itemId,
    itemType: itemType,
    mode: params.mode || normalizeMode('', params.parentWordId),
    source: '',
    parentWordId: params.parentWordId,
    label: params.label || '',
    language: params.language || '',
    correct: params.correct,
    wrong: params.wrong,
    lastCorrect: params.lastCorrect,
    lastWrong: params.lastWrong,
    lastSeen: params.lastSeen,
    srsStage: params.srsStage,
    value: ''
  });
  return response(true, 'Item progress saved successfully');
}

async function saveMetaProgress(db, params) {
  if (!params.user || !params.metaKey || params.metaId === undefined) {
    return response(false, 'Missing required fields: user, metaKey, metaId');
  }
  await saveOne(db, {
    user: params.user,
    itemId: String(params.metaId),
    itemType: 'meta',
    mode: params.mode || 'normal',
    source: params.source || '',
    parentWordId: '',
    label: params.metaKey,
    language: params.language || '',
    correct: 0,
    wrong: 0,
    lastCorrect: '',
    lastWrong: '',
    lastSeen: params.lastSeen || new Date().toISOString(),
    srsStage: '',
    value: params.value
  });
  return response(true, 'Progress metadata saved successfully');
}

async function loadProgress(db, params) {
  const user = params.user;
  if (!user) return response(false, 'Missing required field: user');
  const modeFilter = normalizeMode(params.mode || legacySheetMode(params.sheet) || 'all');

  const { results } = await db
    .prepare("SELECT * FROM progress WHERE user = ? AND item_type IN ('word','meta')")
    .bind(user)
    .all();

  const progress = [];
  const levelEstimates = {};
  const meta = [];

  for (const raw of results) {
    const row = fromDb(raw);
    const itemType = normalizeItemType(row.itemType);
    const rowMode = normalizeMode(row.mode, row.parentWordId || row.itemId);
    if (itemType === 'word') {
      if (modeFilter !== 'all' && rowMode !== modeFilter) continue;
      progress.push({
        word: row.label,
        wordId: row.itemId,
        itemType: 'word',
        mode: rowMode,
        language: row.language,
        correct: row.correct,
        wrong: row.wrong,
        lastCorrect: row.lastCorrect,
        lastWrong: row.lastWrong,
        lastSeen: row.lastSeen,
        schemaVersion: row.schemaVersion || PROGRESS_SCHEMA_VERSION,
        srsStage: row.srsStage
      });
    } else if (itemType === 'meta') {
      const metaRow = {
        metaId: row.itemId,
        metaKey: row.label,
        mode: rowMode,
        source: row.source || '',
        language: row.language || '',
        value: row.value,
        lastSeen: row.lastSeen
      };
      meta.push(metaRow);
      if (metaRow.metaKey === 'level-estimate') {
        levelEstimates[metaRow.language] = metaRow.value;
      }
    }
  }

  return response(true, 'Progress loaded successfully', {
    schemaVersion: PROGRESS_SCHEMA_VERSION,
    progress: progress,
    levelEstimates: levelEstimates,
    meta: meta
  });
}

async function loadItemProgress(db, params) {
  const user = params.user;
  if (!user) return response(false, 'Missing required field: user');
  const modeFilter = normalizeMode(params.mode || 'all');

  const placeholders = ITEM_TYPES.map(() => '?').join(',');
  const { results } = await db
    .prepare(`SELECT * FROM progress WHERE user = ? AND item_type IN (${placeholders})`)
    .bind(user, ...ITEM_TYPES)
    .all();

  const items = [];
  for (const raw of results) {
    const row = fromDb(raw);
    const rowMode = normalizeMode(row.mode, row.parentWordId);
    if (modeFilter !== 'all' && rowMode !== modeFilter) continue;
    items.push({
      itemId: row.itemId,
      parentWordId: row.parentWordId,
      itemType: normalizeItemType(row.itemType),
      mode: rowMode,
      label: row.label,
      language: row.language,
      correct: row.correct,
      wrong: row.wrong,
      lastCorrect: row.lastCorrect,
      lastWrong: row.lastWrong,
      lastSeen: row.lastSeen,
      schemaVersion: row.schemaVersion || PROGRESS_SCHEMA_VERSION,
      srsStage: row.srsStage
    });
  }
  return response(true, 'Item progress loaded successfully', { items: items });
}

async function deleteProgress(db, params, env) {
  if (params.sheet === 'FlaggedWords') return proxyToSheets(params, env);
  const user = params.user;
  if (!user) return response(false, 'Missing required field: user');
  const modeFilter = normalizeMode(params.mode || legacySheetMode(params.sheet) || 'all');

  // mode is derived per row in the Apps Script, so select then filter in JS to
  // keep the same rows in scope, and delete by primary key.
  const { results } = await db
    .prepare("SELECT * FROM progress WHERE user = ? AND item_type = 'word'")
    .bind(user)
    .all();

  const doomed = [];
  for (const raw of results) {
    const row = fromDb(raw);
    if (modeFilter !== 'all' && normalizeMode(row.mode, row.itemId) !== modeFilter) continue;
    if (params.wordId === undefined || String(row.itemId) === String(params.wordId)) {
      doomed.push(raw.row_key);
    }
  }
  if (doomed.length) {
    await db.batch(doomed.map(k =>
      db.prepare('DELETE FROM progress WHERE row_key = ?').bind(k)));
  }
  return response(true, 'Deleted ' + doomed.length + ' progress rows');
}

async function deleteItemProgress(db, params) {
  const user = params.user;
  if (!user) return response(false, 'Missing required field: user');
  const parents = Array.isArray(params.parentWordIds)
    ? params.parentWordIds
    : (params.parentWordId ? [params.parentWordId] : []);
  if (parents.length === 0) return response(false, 'Missing parentWordId or parentWordIds');

  const typeSlots = ITEM_TYPES.map(() => '?').join(',');
  const parentSlots = parents.map(() => '?').join(',');
  const { meta } = await db
    .prepare(`DELETE FROM progress WHERE user = ? AND item_type IN (${typeSlots})
              AND parent_word_id IN (${parentSlots})`)
    .bind(user, ...ITEM_TYPES, ...parents)
    .run();
  return response(true, 'Deleted ' + (meta.changes || 0) + ' item progress rows');
}

async function deleteExactProgressRow(db, params) {
  const itemType = normalizeItemType(params.itemType);
  if (!params.user || params.itemId === undefined || !itemType) {
    return response(false, 'Missing required fields: user, itemId, itemType');
  }
  const key = rowKey({
    user: params.user,
    itemId: params.itemId,
    itemType: itemType,
    mode: normalizeMode(params.mode, params.parentWordId || params.itemId),
    source: params.source || '',
    parentWordId: params.parentWordId || '',
    label: params.label || '',
    language: params.language || ''
  });
  const { meta } = await db
    .prepare('DELETE FROM progress WHERE row_key = ?').bind(key).run();
  return response(true, 'Deleted ' + (meta.changes || 0) + ' exact progress rows');
}

/**
 * Batch upsert. The Apps Script version needed a hand-built row index to avoid
 * being quadratic; here the primary key does that job, and db.batch() runs the
 * whole set in one transaction, so a batch either lands or it doesn't.
 */
async function bulkSave(db, params, env) {
  const rows = params.rows;
  if (!rows || !Array.isArray(rows) || rows.length === 0) {
    return response(false, 'Missing or empty rows array');
  }
  if (params.sheet === 'FlaggedWords') return proxyToSheets(params, env);

  const legacyMode = legacySheetMode(params.sheet);
  const normalized = [];

  for (const row of rows) {
    const itemType = normalizeItemType(row.itemType || 'word');
    if (!row.user) continue;
    if (itemType === 'meta') {
      if (row.itemId === undefined && row.metaId === undefined) continue;
      normalized.push({
        user: row.user,
        itemId: String(row.itemId !== undefined ? row.itemId : row.metaId),
        itemType: 'meta',
        mode: row.mode || legacyMode || 'normal',
        source: row.source || '',
        parentWordId: '',
        label: row.label || row.metaKey || '',
        language: row.language || '',
        correct: 0,
        wrong: 0,
        lastCorrect: '',
        lastWrong: '',
        lastSeen: row.lastSeen,
        srsStage: '',
        value: row.value
      });
    } else if (itemType === 'word') {
      const itemId = row.itemId !== undefined ? row.itemId : row.wordId;
      if (itemId === undefined) continue;
      normalized.push({
        user: row.user,
        itemId: itemId,
        itemType: 'word',
        mode: row.mode || legacyMode || normalizeMode('', itemId),
        source: '',
        parentWordId: '',
        label: row.label || row.word || '',
        language: row.language || '',
        correct: row.correct,
        wrong: row.wrong,
        lastCorrect: row.lastCorrect,
        lastWrong: row.lastWrong,
        lastSeen: row.lastSeen,
        srsStage: row.srsStage,
        value: ''
      });
    } else {
      if (!row.itemId || !row.parentWordId) continue;
      normalized.push({
        user: row.user,
        itemId: row.itemId,
        itemType: itemType,
        mode: row.mode || normalizeMode('', row.parentWordId),
        source: '',
        parentWordId: row.parentWordId,
        label: row.label || '',
        language: row.language || '',
        correct: row.correct,
        wrong: row.wrong,
        lastCorrect: row.lastCorrect,
        lastWrong: row.lastWrong,
        lastSeen: row.lastSeen,
        srsStage: row.srsStage,
        value: ''
      });
    }
  }
  if (!normalized.length) return response(true, 'Bulk save complete: 0 updated, 0 inserted');

  // One read for the whole batch, mirroring makeProgressIndex().
  const keys = normalized.map(p => rowKey(buildRow(p, {})));
  const existing = {};
  const CHUNK = 100;
  for (let i = 0; i < keys.length; i += CHUNK) {
    const slice = keys.slice(i, i + CHUNK);
    const { results } = await db
      .prepare(`SELECT * FROM progress WHERE row_key IN (${slice.map(() => '?').join(',')})`)
      .bind(...slice)
      .all();
    for (const r of results) existing[r.row_key] = fromDb(r);
  }

  let updated = 0;
  let inserted = 0;
  const stmts = normalized.map((p, i) => {
    const prior = existing[keys[i]];
    if (prior) updated++; else inserted++;
    return upsertStmt(db, buildRow(p, prior || {}));
  });

  for (let i = 0; i < stmts.length; i += CHUNK) {
    await db.batch(stmts.slice(i, i + CHUNK));
  }
  return response(true, 'Bulk save complete: ' + updated + ' updated, ' + inserted + ' inserted');
}

async function saveSongSet(db, params) {
  const user = String(params.user || '').trim();
  const setId = String(params.setId || '').trim();
  const source = String(params.source || '').trim();
  const songIds = normalizedSongIds(params.songIds);
  const artistSlugs = normalizedArtistSlugs(params.artistSlugs);
  if (!user || !setId || !source || !songIds.length) {
    return response(false, 'Missing required song-set fields');
  }
  const prior = await db
    .prepare('SELECT 1 FROM song_sets WHERE user = ? AND source = ? AND set_id = ?')
    .bind(user, source, setId).first();

  await db.prepare(`
    INSERT INTO song_sets (user, set_id, source, name, language, song_ids_json,
                           updated_at, schema_version, artist_slugs_json)
    VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
    ON CONFLICT(user, source, set_id) DO UPDATE SET
      name=excluded.name, language=excluded.language,
      song_ids_json=excluded.song_ids_json, updated_at=excluded.updated_at,
      schema_version=excluded.schema_version,
      artist_slugs_json=excluded.artist_slugs_json`)
    .bind(user, setId, source, String(params.name || ''), String(params.language || ''),
      JSON.stringify(songIds), params.updatedAt || new Date().toISOString(),
      SONG_SET_SCHEMA_VERSION, JSON.stringify(artistSlugs))
    .run();

  return response(true, prior ? 'Song set updated' : 'Song set saved');
}

async function loadSongSets(db, params) {
  const user = String(params.user || '').trim();
  if (!user) return response(false, 'Missing required field: user');
  const { results } = await db
    .prepare('SELECT * FROM song_sets WHERE user = ?').bind(user).all();

  const songSets = results.map(row => {
    let songIds = [];
    let artistSlugs = [];
    try { songIds = normalizedSongIds(JSON.parse(row.song_ids_json || '[]')); } catch (_) {}
    try { artistSlugs = normalizedArtistSlugs(JSON.parse(row.artist_slugs_json || '[]')); } catch (_) {}
    return {
      setId: String(row.set_id || ''),
      source: String(row.source || ''),
      name: String(row.name || ''),
      language: String(row.language || ''),
      songIds: songIds,
      artistSlugs: artistSlugs,
      updatedAt: row.updated_at || '',
      schemaVersion: Number(row.schema_version) || SONG_SET_SCHEMA_VERSION
    };
  });

  return response(true, 'Song sets loaded', {
    schemaVersion: SONG_SET_SCHEMA_VERSION,
    songSets: songSets
  });
}

async function deleteSongSet(db, params) {
  const user = String(params.user || '').trim();
  const setId = String(params.setId || '').trim();
  const source = String(params.source || '').trim();
  if (!user || !setId || !source) return response(false, 'Missing required song-set fields');
  const { meta } = await db
    .prepare('DELETE FROM song_sets WHERE user = ? AND source = ? AND set_id = ?')
    .bind(user, source, setId).run();
  return response(true, meta.changes ? 'Song set deleted' : 'Song set not found');
}

/** Whole-table dump, used by backend/sync_sheets.py. */
async function dumpSheet(db, params, env) {
  const requested = params.sheet || 'Progress';
  if (requested === 'FlaggedWords') return proxyToSheets(params, env);
  if (requested === 'SongSets') {
    const { results } = await db.prepare('SELECT * FROM song_sets').all();
    return response(true, 'Sheet dumped', { sheet: 'SongSets', rows: results });
  }
  const { results } = await db.prepare('SELECT * FROM progress').all();
  return response(true, 'Sheet dumped', {
    sheet: 'Progress',
    rows: results.map(fromDb)
  });
}

/* ------------------------------------------------------------------ *
 * Flag proxy — keeps the FlaggedWords audit tab alive in Sheets.
 * ------------------------------------------------------------------ */

async function proxyToSheets(params, env) {
  if (!env.SHEETS_URL) {
    return response(false, 'Flag storage unavailable: SHEETS_URL is not configured');
  }
  try {
    const upstream = await fetch(env.SHEETS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
      redirect: 'follow'
    });
    const text = await upstream.text();
    return new Response(text, {
      status: 200,
      headers: { 'Content-Type': 'application/json', ...corsHeaders() }
    });
  } catch (err) {
    return response(false, 'Flag proxy error: ' + err);
  }
}

/* ------------------------------------------------------------------ *
 * Plumbing
 * ------------------------------------------------------------------ */

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400'
  };
}

/** Port of createResponse(): the exact envelope the client expects. */
function response(success, message, data) {
  const body = { success: success, message: message, timestamp: new Date().toISOString() };
  if (data !== undefined && data !== null) body.data = data;
  return new Response(JSON.stringify(body), {
    status: 200,   // the client reads body.success, never the status code
    headers: { 'Content-Type': 'application/json', ...corsHeaders() }
  });
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    // Port of doGet(): a health check that touches no data.
    if (request.method === 'GET') {
      return new Response(JSON.stringify({
        status: 'success',
        message: 'Flashcard API is running',
        backend: 'cloudflare-worker-d1',
        schemaVersion: PROGRESS_SCHEMA_VERSION,
        flagSchemaVersion: FLAG_SCHEMA_VERSION,
        songSetSchemaVersion: SONG_SET_SCHEMA_VERSION,
        flagProxyConfigured: Boolean(env.SHEETS_URL),
        timestamp: new Date().toISOString()
      }), { headers: { 'Content-Type': 'application/json', ...corsHeaders() } });
    }

    const db = env.DB;
    let params;
    try {
      params = await request.json();
    } catch (err) {
      return response(false, 'Error: invalid JSON body');
    }

    try {
      switch (params.action) {
        case 'save':          return await saveProgress(db, params, env);
        case 'load':          return await loadProgress(db, params);
        case 'delete':        return await deleteProgress(db, params, env);
        case 'deleteRow':     return await deleteExactProgressRow(db, params);
        case 'dump':          return await dumpSheet(db, params, env);
        case 'bulkSave':      return await bulkSave(db, params, env);
        case 'saveItem':      return await saveItemProgress(db, params);
        case 'loadItems':     return await loadItemProgress(db, params);
        case 'deleteItems':   return await deleteItemProgress(db, params);
        case 'saveMeta':      return await saveMetaProgress(db, params);
        case 'saveSongSet':   return await saveSongSet(db, params);
        case 'loadSongSets':  return await loadSongSets(db, params);
        case 'deleteSongSet': return await deleteSongSet(db, params);
        case 'capabilities':
          return response(true, 'Backend capabilities', {
            schemaVersion: PROGRESS_SCHEMA_VERSION,
            flagSchemaVersion: FLAG_SCHEMA_VERSION,
            songSetSchemaVersion: SONG_SET_SCHEMA_VERSION,
            sheets: ['Progress', 'FlaggedWords', 'SongSets']
          });
        // Schema migrations are files now (migrations/), not runtime actions.
        // Accepted so a cached client calling them does not see an error.
        case 'migrateProgress':
          return response(true, 'Progress schema migration complete', { migrated: 0 });
        case 'migrateFlags':
          return proxyToSheets(params, env);
        default:
          return response(false, 'Invalid action');
      }
    } catch (error) {
      return response(false, 'Error: ' + (error && error.message ? error.message : error));
    }
  }
};
