/**
 * Fluency backend — Cloudflare Worker + D1.
 *
 * The wire protocol is byte-identical to the Apps Script it replaced, so
 * js/auth.js and js/sync-queue.js are untouched. Underneath, progress is now
 * event-sourced: review_events is the system of record, item_state is a
 * derived read model carrying a materialised due_at, and settings live in
 * user_meta rather than masquerading as progress rows.
 *
 * Flags are written to D1 and mirrored to the Apps Script deployment so the
 * spreadsheet audit tab keeps working — the sheet is an export now, not the
 * store. A failed mirror never fails the request.
 */

import {
  ITEM_TYPES, wireMode, storedMode, parseFullId, toFullId, normalizeItemType,
  legacySheetMode, computeSchedule, stateToWireWord, stateToWireItem,
  upsertStateStmt, insertEventStmt, deriveEvents
} from './store.js';

const PROGRESS_SCHEMA_VERSION = 4;
const SONG_SET_SCHEMA_VERSION = 2;
const FLAG_SCHEMA_VERSION = 4;

/* ------------------------------ plumbing -------------------------------- */

const cors = () => ({
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400'
});

function response(success, message, data) {
  const body = { success, message, timestamp: new Date().toISOString() };
  if (data !== undefined && data !== null) body.data = data;
  // The client reads body.success and never the status code.
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json', ...cors() }
  });
}

/* ------------------------------- writing -------------------------------- */

/**
 * One write path for words and sparse items alike: append the events implied
 * by the change, then store the recomputed state. Both land in a single
 * db.batch, so a write either fully happens or does not.
 */
async function recordProgress(db, params, { itemType, fullId, parentFullId, label }) {
  const parsed = parseFullId(fullId);
  if (!parsed) return response(false, `Unrecognised item id: ${fullId}`);
  const parentParsed = parentFullId ? parseFullId(parentFullId) : null;

  const prior = await db.prepare(
    `SELECT * FROM item_state
     WHERE user_id=?1 AND lang_code=?2 AND item_id=?3 AND mode=?4`
  ).bind(params.user, parsed.langCode, parsed.itemId, parsed.mode).first();

  const incoming = {
    correct: Math.max(0, Number(params.correct) || 0),
    wrong: Math.max(0, Number(params.wrong) || 0),
    lastCorrect: params.lastCorrect || (prior ? prior.last_correct_at : ''),
    lastWrong: params.lastWrong || (prior ? prior.last_incorrect_at : ''),
    lastSeen: params.lastSeen || new Date().toISOString(),
    srsStage: params.srsStage
  };
  const schedule = computeSchedule(incoming);

  const identity = {
    userId: params.user, itemId: parsed.itemId, itemType,
    parentId: parentParsed ? parentParsed.itemId : '',
    langCode: parsed.langCode, language: params.language || (prior?.language ?? ''),
    mode: parsed.mode, source: params.source || (prior?.source ?? ''),
    releaseId: params.releaseId || '', sessionId: params.sessionId || '',
    clientBuild: params.clientBuild || '', idempotencyKey: params.idempotencyKey || null
  };

  const statements = deriveEvents(prior, incoming, identity)
    .map(event => insertEventStmt(db, event));

  statements.push(upsertStateStmt(db, {
    ...identity,
    label: label || (prior?.label ?? ''),
    correct: incoming.correct, wrong: incoming.wrong,
    firstSeen: prior?.first_seen_at || incoming.lastSeen,
    lastSeen: incoming.lastSeen,
    lastCorrect: incoming.lastCorrect, lastWrong: incoming.lastWrong,
    stage: schedule.explicitStage, dueAt: schedule.dueAt, unresolved: schedule.unresolved
  }));

  await db.batch(statements);
  return null;
}

async function saveProgress(db, params, env) {
  if (params.sheet === 'FlaggedWords') return saveFlag(db, params, env);
  // Legacy sentinel: the old client stored level estimates as a fake word row.
  if (params.word === '_LEVEL_ESTIMATE_') {
    return saveMetaProgress(db, {
      user: params.user, metaKey: 'level-estimate',
      metaId: params.language || 'unknown', mode: 'normal', source: 'speech',
      language: params.language || '', value: params.wordId, lastSeen: params.lastSeen
    });
  }
  if (!params.user || params.wordId === undefined) {
    return response(false, 'Missing required fields: user, wordId');
  }
  const failure = await recordProgress(db, params, {
    itemType: 'word', fullId: params.wordId, parentFullId: '', label: params.word || ''
  });
  return failure || response(true, 'Progress saved successfully');
}

async function saveItemProgress(db, params) {
  const itemType = normalizeItemType(params.itemType);
  if (!params.user || !params.itemId || !params.parentWordId) {
    return response(false, 'Missing required fields: user, itemId, parentWordId');
  }
  if (!ITEM_TYPES.includes(itemType)) {
    return response(false, `Invalid itemType: ${itemType}`);
  }
  const failure = await recordProgress(db, params, {
    itemType, fullId: params.itemId, parentFullId: params.parentWordId,
    label: params.label || ''
  });
  return failure || response(true, 'Item progress saved successfully');
}

async function saveMetaProgress(db, params) {
  if (!params.user || !params.metaKey || params.metaId === undefined) {
    return response(false, 'Missing required fields: user, metaKey, metaId');
  }
  const mode = storedMode(params.mode);
  const scope = params.scopeKey
    || [params.language || '', mode, params.source || ''].filter(Boolean).join('|');
  await db.prepare(`
    INSERT INTO user_meta (user_id, scope, key, meta_id, value_json, updated_at)
    VALUES (?1,?2,?3,?4,?5,?6)
    ON CONFLICT(user_id, scope, key, meta_id) DO UPDATE SET
      value_json=excluded.value_json, updated_at=excluded.updated_at`)
    .bind(params.user, scope, params.metaKey, String(params.metaId),
          JSON.stringify(params.value ?? null),
          params.lastSeen || new Date().toISOString())
    .run();
  return response(true, 'Progress metadata saved successfully');
}

async function bulkSave(db, params, env) {
  const rows = params.rows;
  if (!Array.isArray(rows) || rows.length === 0) {
    return response(false, 'Missing or empty rows array');
  }
  if (params.sheet === 'FlaggedWords') {
    let saved = 0;
    for (const row of rows) { await saveFlag(db, { ...row, user: row.user || params.user }, env); saved++; }
    return response(true, `Bulk save complete: ${saved} flags`);
  }
  let written = 0;
  for (const row of rows) {
    if (!row.user) continue;
    const itemType = normalizeItemType(row.itemType || 'word');
    if (itemType === 'meta') {
      await saveMetaProgress(db, { ...row, metaKey: row.label || row.metaKey,
        metaId: row.itemId !== undefined ? row.itemId : row.metaId });
    } else {
      const fullId = itemType === 'word'
        ? (row.itemId !== undefined ? row.itemId : row.wordId)
        : row.itemId;
      if (fullId === undefined || fullId === null) continue;
      await recordProgress(db, { ...row, sheet: params.sheet }, {
        itemType, fullId, parentFullId: row.parentWordId || '',
        label: row.label || row.word || ''
      });
    }
    written++;
  }
  return response(true, `Bulk save complete: ${written} rows`);
}

/* ------------------------------- reading -------------------------------- */

async function loadProgress(db, params) {
  if (!params.user) return response(false, 'Missing required field: user');
  const requested = params.mode || legacySheetMode(params.sheet) || 'all';
  const filter = requested === 'all' ? null : storedMode(requested);

  const words = filter
    ? await db.prepare(
        `SELECT * FROM item_state WHERE user_id=?1 AND item_type='word' AND mode=?2`
      ).bind(params.user, filter).all()
    : await db.prepare(
        `SELECT * FROM item_state WHERE user_id=?1 AND item_type='word'`
      ).bind(params.user).all();

  const metaRows = await db.prepare(
    'SELECT * FROM user_meta WHERE user_id=?1'
  ).bind(params.user).all();

  const levelEstimates = {};
  const meta = metaRows.results.map(row => {
    const [language = '', mode = 'speech', source = ''] = String(row.scope).split('|');
    let value = null;
    try { value = JSON.parse(row.value_json); } catch (_) {}
    if (row.key === 'level-estimate') levelEstimates[language] = value;
    return {
      metaId: row.meta_id, metaKey: row.key, mode: wireMode(mode),
      source, language, value, lastSeen: row.updated_at
    };
  });

  return response(true, 'Progress loaded successfully', {
    schemaVersion: PROGRESS_SCHEMA_VERSION,
    progress: words.results.map(stateToWireWord),
    levelEstimates, meta
  });
}

async function loadItemProgress(db, params) {
  if (!params.user) return response(false, 'Missing required field: user');
  const requested = params.mode || 'all';
  const filter = requested === 'all' ? null : storedMode(requested);
  const slots = ITEM_TYPES.map(() => '?').join(',');
  const sql = `SELECT * FROM item_state WHERE user_id=? AND item_type IN (${slots})`
    + (filter ? ' AND mode=?' : '');
  const binds = filter ? [params.user, ...ITEM_TYPES, filter] : [params.user, ...ITEM_TYPES];
  const { results } = await db.prepare(sql).bind(...binds).all();
  return response(true, 'Item progress loaded successfully',
    { items: results.map(stateToWireItem) });
}

/**
 * What the materialised due_at exists for. Not used by the client yet — the
 * app still loads everything and decides locally — but this is the query that
 * replaces walking every card in JavaScript once the scheduler is built.
 */
async function loadDue(db, params) {
  if (!params.user) return response(false, 'Missing required field: user');
  const limit = Math.min(500, Math.max(1, Number(params.limit) || 50));
  const now = new Date().toISOString();
  const filter = params.mode && params.mode !== 'all' ? storedMode(params.mode) : null;
  const sql = `SELECT * FROM item_state
               WHERE user_id=?1 AND due_at IS NOT NULL AND due_at <= ?2`
    + (filter ? ' AND mode=?3' : '') + ' ORDER BY due_at LIMIT ' + limit;
  const binds = filter ? [params.user, now, filter] : [params.user, now];
  const { results } = await db.prepare(sql).bind(...binds).all();
  return response(true, 'Due items loaded', {
    now, count: results.length,
    items: results.map(r => r.item_type === 'word' ? stateToWireWord(r) : stateToWireItem(r))
  });
}

/* ------------------------------- deleting ------------------------------- */

async function deleteProgress(db, params, env) {
  if (params.sheet === 'FlaggedWords') return deleteFlag(db, params, env);
  if (!params.user) return response(false, 'Missing required field: user');
  const requested = params.mode || legacySheetMode(params.sheet) || 'all';
  const filter = requested === 'all' ? null : storedMode(requested);

  // Events are immutable history; deleting progress resets the derived state
  // only. A replay would restore it, which is the intended safety property.
  let sql = `DELETE FROM item_state WHERE user_id=? AND item_type='word'`;
  const binds = [params.user];
  if (filter) { sql += ' AND mode=?'; binds.push(filter); }
  if (params.wordId !== undefined) {
    const parsed = parseFullId(params.wordId);
    if (!parsed) return response(false, `Unrecognised item id: ${params.wordId}`);
    sql += ' AND lang_code=? AND item_id=? AND mode=?';
    binds.push(parsed.langCode, parsed.itemId, parsed.mode);
  }
  const { meta } = await db.prepare(sql).bind(...binds).run();
  return response(true, `Deleted ${meta.changes || 0} progress rows`);
}

async function deleteItemProgress(db, params) {
  if (!params.user) return response(false, 'Missing required field: user');
  const parents = Array.isArray(params.parentWordIds)
    ? params.parentWordIds
    : (params.parentWordId ? [params.parentWordId] : []);
  if (parents.length === 0) return response(false, 'Missing parentWordId or parentWordIds');
  const bare = parents.map(parseFullId).filter(Boolean).map(p => p.itemId);
  if (bare.length === 0) return response(true, 'Deleted 0 item progress rows');
  const typeSlots = ITEM_TYPES.map(() => '?').join(',');
  const parentSlots = bare.map(() => '?').join(',');
  const { meta } = await db.prepare(
    `DELETE FROM item_state WHERE user_id=? AND item_type IN (${typeSlots})
     AND parent_id IN (${parentSlots})`
  ).bind(params.user, ...ITEM_TYPES, ...bare).run();
  return response(true, `Deleted ${meta.changes || 0} item progress rows`);
}

async function deleteExactProgressRow(db, params) {
  const itemType = normalizeItemType(params.itemType);
  if (!params.user || params.itemId === undefined || !itemType) {
    return response(false, 'Missing required fields: user, itemId, itemType');
  }
  const parsed = parseFullId(params.itemId);
  if (!parsed) return response(false, `Unrecognised item id: ${params.itemId}`);
  const { meta } = await db.prepare(
    `DELETE FROM item_state
     WHERE user_id=? AND lang_code=? AND item_id=? AND mode=? AND item_type=?`
  ).bind(params.user, parsed.langCode, parsed.itemId, parsed.mode, itemType).run();
  return response(true, `Deleted ${meta.changes || 0} exact progress rows`);
}

/* -------------------------------- flags --------------------------------- */

/**
 * Flags live in D1 now. The ~29 attribute columns the sheet needed collapse
 * into payload_json: they are a snapshot of how the card looked when flagged,
 * read whole during triage and never filtered on. What is filtered on —
 * status, target, category, item, release — stays a real column.
 */
async function saveFlag(db, params, env) {
  const parsed = parseFullId(params.wordId || params.cardId || '');
  const flagId = params.flagId
    || `${params.user}:${params.wordId}:${params.flaggedAt || Date.now()}`;
  await db.prepare(`
    INSERT INTO flags (
      flag_id, user_id, created_at, item_id, item_type, lang_code, language,
      mode, source, release_id, target, category, note, event_id, payload_json,
      status
    ) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,'open')
    ON CONFLICT(flag_id) DO UPDATE SET
      payload_json=excluded.payload_json, note=excluded.note,
      target=excluded.target, category=excluded.category`)
    .bind(
      flagId, params.user || '', params.flaggedAt || new Date().toISOString(),
      parsed ? parsed.itemId : '', normalizeItemType(params.itemType || 'word'),
      parsed ? parsed.langCode : '', params.language || '',
      parsed ? parsed.mode : storedMode(params.mode), params.source || '',
      params.releaseId || '', params.target || '', params.category || '',
      params.note || '', params.eventId ?? null, JSON.stringify(params)
    ).run();

  // Mirror to the audit tab. Best-effort: the sheet is an export, so a failure
  // there must not fail the learner's flag.
  mirrorToSheets(params, env);
  return response(true, 'Flag event saved');
}

async function deleteFlag(db, params, env) {
  if (!params.flagId) return response(false, 'Missing required field: flagId');
  const { meta } = await db.prepare('DELETE FROM flags WHERE flag_id=? AND user_id=?')
    .bind(params.flagId, params.user || '').run();
  mirrorToSheets(params, env);
  return response(true, `Deleted ${meta.changes || 0} flags`);
}

function mirrorToSheets(params, env) {
  if (!env.SHEETS_URL) return;
  try {
    fetch(env.SHEETS_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params), redirect: 'follow'
    }).catch(() => {});
  } catch (_) { /* export only */ }
}

/* -------------------------------- misc ---------------------------------- */

async function saveSongSet(db, params) {
  const user = String(params.user || '').trim();
  const setId = String(params.setId || '').trim();
  const source = String(params.source || '').trim();
  const songIds = Array.isArray(params.songIds)
    ? [...new Set(params.songIds.map(id => String(id || '').trim()).filter(Boolean))].slice(0, 1000)
    : [];
  const artistSlugs = Array.isArray(params.artistSlugs)
    ? [...new Set(params.artistSlugs.map(s => String(s || '').trim()).filter(Boolean))].slice(0, 100)
    : [];
  if (!user || !setId || !source || !songIds.length) {
    return response(false, 'Missing required song-set fields');
  }
  const prior = await db.prepare(
    'SELECT 1 FROM song_sets WHERE user=? AND source=? AND set_id=?'
  ).bind(user, source, setId).first();
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
      SONG_SET_SCHEMA_VERSION, JSON.stringify(artistSlugs)).run();
  return response(true, prior ? 'Song set updated' : 'Song set saved');
}

async function loadSongSets(db, params) {
  const user = String(params.user || '').trim();
  if (!user) return response(false, 'Missing required field: user');
  const { results } = await db.prepare('SELECT * FROM song_sets WHERE user=?')
    .bind(user).all();
  const songSets = results.map(row => {
    let songIds = [], artistSlugs = [];
    try { songIds = JSON.parse(row.song_ids_json || '[]'); } catch (_) {}
    try { artistSlugs = JSON.parse(row.artist_slugs_json || '[]'); } catch (_) {}
    return {
      setId: String(row.set_id || ''), source: String(row.source || ''),
      name: String(row.name || ''), language: String(row.language || ''),
      songIds, artistSlugs, updatedAt: row.updated_at || '',
      schemaVersion: Number(row.schema_version) || SONG_SET_SCHEMA_VERSION
    };
  });
  return response(true, 'Song sets loaded',
    { schemaVersion: SONG_SET_SCHEMA_VERSION, songSets });
}

async function deleteSongSet(db, params) {
  const user = String(params.user || '').trim();
  const setId = String(params.setId || '').trim();
  const source = String(params.source || '').trim();
  if (!user || !setId || !source) return response(false, 'Missing required song-set fields');
  const { meta } = await db.prepare(
    'DELETE FROM song_sets WHERE user=? AND source=? AND set_id=?'
  ).bind(user, source, setId).run();
  return response(true, meta.changes ? 'Song set deleted' : 'Song set not found');
}

/** Legacy positional dump, kept so sync_sheets.py / push_sheets.py still work. */
const PROGRESS_HEADERS = [
  'User', 'ItemId', 'ItemType', 'Mode', 'Source', 'ParentWordId', 'Label',
  'Language', 'Correct', 'Wrong', 'LastCorrect', 'LastWrong', 'LastSeen',
  'SchemaVersion', 'SrsStage', 'Value'
];
const SONG_SET_HEADERS = ['User', 'SetId', 'Source', 'Name', 'Language',
  'SongIdsJson', 'UpdatedAt', 'SchemaVersion', 'ArtistSlugsJson'];

async function dumpSheet(db, params) {
  const requested = params.sheet || 'Progress';
  if (requested === 'SongSets') {
    const { results } = await db.prepare('SELECT * FROM song_sets').all();
    return response(true, 'Sheet dumped successfully', {
      headers: SONG_SET_HEADERS,
      rows: results.map(r => [r.user, r.set_id, r.source, r.name, r.language,
        r.song_ids_json, r.updated_at, r.schema_version, r.artist_slugs_json])
    });
  }
  if (requested === 'Flags' || requested === 'FlaggedWords') {
    const { results } = await db.prepare(
      'SELECT * FROM flags ORDER BY created_at DESC').all();
    return response(true, 'Sheet dumped successfully', {
      headers: ['FlagId', 'User', 'CreatedAt', 'ItemId', 'Mode', 'Target',
        'Category', 'Note', 'Status', 'PayloadJson'],
      rows: results.map(r => [r.flag_id, r.user_id, r.created_at,
        toFullId(r.lang_code, r.mode, r.item_id), wireMode(r.mode), r.target,
        r.category, r.note, r.status, r.payload_json])
    });
  }
  const state = await db.prepare('SELECT * FROM item_state').all();
  const metaRows = await db.prepare('SELECT * FROM user_meta').all();
  const rows = state.results.map(r => [
    r.user_id, toFullId(r.lang_code, r.mode, r.item_id), r.item_type,
    wireMode(r.mode), r.source,
    r.parent_id ? toFullId(r.lang_code, r.mode, r.parent_id) : '',
    r.label, r.language, r.correct_count, r.incorrect_count,
    r.last_correct_at, r.last_incorrect_at, r.last_seen_at,
    PROGRESS_SCHEMA_VERSION, r.srs_stage === null ? '' : r.srs_stage, ''
  ]);
  for (const m of metaRows.results) {
    const [language = '', mode = 'speech', source = ''] = String(m.scope).split('|');
    let value = null;
    try { value = JSON.parse(m.value_json); } catch (_) {}
    rows.push([m.user_id, m.meta_id, 'meta', wireMode(mode), source, '', m.key,
      language, 0, 0, '', '', m.updated_at, PROGRESS_SCHEMA_VERSION, '',
      value === null ? '' : value]);
  }
  return response(true, 'Sheet dumped successfully', { headers: PROGRESS_HEADERS, rows });
}

/* ------------------------------- routing -------------------------------- */

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors() });
    }
    if (request.method === 'GET') {
      return new Response(JSON.stringify({
        status: 'success', message: 'Flashcard API is running',
        backend: 'cloudflare-worker-d1', storage: 'event-sourced',
        schemaVersion: PROGRESS_SCHEMA_VERSION,
        flagSchemaVersion: FLAG_SCHEMA_VERSION,
        songSetSchemaVersion: SONG_SET_SCHEMA_VERSION,
        flagMirrorConfigured: Boolean(env.SHEETS_URL),
        timestamp: new Date().toISOString()
      }), { headers: { 'Content-Type': 'application/json', ...cors() } });
    }

    const db = env.DB;
    let params;
    try { params = await request.json(); }
    catch (_) { return response(false, 'Error: invalid JSON body'); }

    try {
      switch (params.action) {
        case 'save':          return await saveProgress(db, params, env);
        case 'load':          return await loadProgress(db, params);
        case 'loadDue':       return await loadDue(db, params);
        case 'delete':        return await deleteProgress(db, params, env);
        case 'deleteRow':     return await deleteExactProgressRow(db, params);
        case 'dump':          return await dumpSheet(db, params);
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
            sheets: ['Progress', 'FlaggedWords', 'SongSets'],
            storage: 'event-sourced', supports: ['loadDue']
          });
        // Schema changes are migration files now, not runtime actions.
        case 'migrateProgress':
          return response(true, 'Progress schema migration complete', { migrated: 0 });
        case 'migrateFlags':
          return response(true, 'Flag schema migration complete', { migrated: 0 });
        default:
          return response(false, 'Invalid action');
      }
    } catch (error) {
      return response(false, `Error: ${error?.message || error}`);
    }
  }
};
