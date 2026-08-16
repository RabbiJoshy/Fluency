// Pure parsing and merge helpers for the Spanish Speech vocabulary importer.
// This module deliberately has no browser/app imports so its identity and
// timestamp rules can be exercised directly in Node.

export const IMPORT_CHUNK_SIZE = 50;

const SURFACE_HEADERS = new Set(['surface', 'word', 'spanish', 'term']);
const LEMMA_HEADERS = new Set(['lemma', 'headword']);
const CORRECT_HEADERS = new Set(['last_correct', 'lastcorrect']);
const WRONG_HEADERS = new Set(['last_incorrect', 'lastincorrect', 'last_wrong', 'lastwrong']);

export function normalizeImportedSurface(value) {
    return String(value ?? '').trim().normalize('NFC').toLocaleLowerCase('es');
}

function normalizeHeader(value) {
    return String(value ?? '').trim().replace(/^\ufeff/, '').toLocaleLowerCase('en');
}

function parseDelimited(text, delimiter) {
    const rows = [];
    let row = [];
    let field = '';
    let quoted = false;
    for (let index = 0; index < text.length; index++) {
        const character = text[index];
        if (quoted) {
            if (character === '"' && text[index + 1] === '"') {
                field += '"';
                index++;
            } else if (character === '"') {
                quoted = false;
            } else {
                field += character;
            }
            continue;
        }
        if (character === '"' && field === '') {
            quoted = true;
        } else if (character === delimiter) {
            row.push(field);
            field = '';
        } else if (character === '\n') {
            row.push(field.replace(/\r$/, ''));
            rows.push(row);
            row = [];
            field = '';
        } else {
            field += character;
        }
    }
    if (quoted) throw new Error('The file ends inside a quoted field.');
    if (field || row.length) {
        row.push(field.replace(/\r$/, ''));
        rows.push(row);
    }
    return rows;
}

function findHeaderIndex(headers, aliases) {
    return headers.findIndex(header => aliases.has(header));
}

export function parseVocabularyImport(text) {
    const source = String(text ?? '').replace(/^\ufeff/, '');
    const firstLine = source.split(/\r?\n/, 1)[0] || '';
    const candidateDelimiter = firstLine.includes('\t') ? '\t' : firstLine.includes(',') ? ',' : null;
    const candidateHeaders = candidateDelimiter
        ? parseDelimited(firstLine, candidateDelimiter)[0].map(normalizeHeader)
        : [];
    const knownHeaders = new Set([
        ...SURFACE_HEADERS, ...LEMMA_HEADERS, ...CORRECT_HEADERS, ...WRONG_HEADERS
    ]);
    // A comma or tab can be part of an exact surface. Treat the input as a
    // table only when its first row actually looks like the required header.
    const delimiter = candidateHeaders.some(header => knownHeaders.has(header))
        ? candidateDelimiter
        : null;

    if (!delimiter) {
        const rows = source.split(/\r?\n/)
            .map((surface, index) => ({
                line: index + 1,
                surface: surface.trim(),
                lemma: '',
                lastCorrect: '',
                lastWrong: ''
            }))
            .filter(row => row.surface);
        if (!rows.length) throw new Error('Paste at least one Spanish surface form.');
        return { format: 'text', rows };
    }

    const table = parseDelimited(source, delimiter)
        .filter(row => row.some(value => String(value).trim()));
    if (table.length < 2) throw new Error('CSV and TSV imports need a header and at least one data row.');
    const headers = table[0].map(normalizeHeader);
    const surfaceIndex = findHeaderIndex(headers, SURFACE_HEADERS);
    if (surfaceIndex < 0) throw new Error('The header must include surface (or word).');
    const lemmaIndex = findHeaderIndex(headers, LEMMA_HEADERS);
    const correctIndex = findHeaderIndex(headers, CORRECT_HEADERS);
    const wrongIndex = findHeaderIndex(headers, WRONG_HEADERS);
    const rows = table.slice(1).map((values, index) => ({
        line: index + 2,
        surface: String(values[surfaceIndex] ?? '').trim(),
        lemma: lemmaIndex >= 0 ? String(values[lemmaIndex] ?? '').trim() : '',
        lastCorrect: correctIndex >= 0 ? String(values[correctIndex] ?? '').trim() : '',
        lastWrong: wrongIndex >= 0 ? String(values[wrongIndex] ?? '').trim() : ''
    })).filter(row => row.surface || row.lastCorrect || row.lastWrong || row.lemma);
    if (!rows.length) throw new Error('The file has no vocabulary rows.');
    return { format: delimiter === '\t' ? 'tsv' : 'csv', rows };
}

function parseImportedDate(value, now) {
    const raw = String(value ?? '').trim();
    if (!raw) return { iso: '', error: '' };
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw);
    const timestamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw);
    if (!dateOnly && !timestamp) return { iso: '', error: 'Use YYYY-MM-DD or an ISO-8601 timestamp.' };
    const [year, month, day] = raw.slice(0, 10).split('-').map(Number);
    const calendarCheck = new Date(Date.UTC(year, month - 1, day));
    if (calendarCheck.getUTCFullYear() !== year || calendarCheck.getUTCMonth() !== month - 1 ||
            calendarCheck.getUTCDate() !== day) {
        return { iso: '', error: 'The date is not valid.' };
    }
    const parsed = new Date(dateOnly ? `${raw}T00:00:00.000Z` : raw);
    const time = parsed.getTime();
    if (!Number.isFinite(time)) return { iso: '', error: 'The date is not valid.' };
    if (time > now) return { iso: '', error: 'Future dates are not accepted.' };
    return { iso: parsed.toISOString(), error: '' };
}

function timestamp(value) {
    const parsed = value ? new Date(value).getTime() : 0;
    return Number.isFinite(parsed) ? parsed : 0;
}

function newestIso(...values) {
    let latest = '';
    let latestTime = 0;
    for (const value of values) {
        const time = timestamp(value);
        if (time > latestTime) {
            latest = new Date(time).toISOString();
            latestTime = time;
        }
    }
    return latest;
}

function normalizedCount(value) {
    return Math.max(0, Math.floor(Number(value) || 0));
}

function sameProgress(left, right) {
    return ['word', 'language', 'correct', 'wrong', 'lastCorrect', 'lastWrong', 'lastSeen', 'srsStage']
        .every(key => (left?.[key] ?? '') === (right?.[key] ?? ''));
}

function mergeProgress(existing, imported) {
    const current = existing || {};
    const currentOutcomeTime = Math.max(timestamp(current.lastCorrect), timestamp(current.lastWrong));
    const importedOutcomeTime = Math.max(timestamp(imported.lastCorrect), timestamp(imported.lastWrong));
    const finalLastCorrect = newestIso(current.lastCorrect, imported.lastCorrect);
    const finalLastWrong = newestIso(current.lastWrong, imported.lastWrong);
    const finalCorrectTime = timestamp(finalLastCorrect);
    const finalWrongTime = timestamp(finalLastWrong);
    let srsStage;
    if (importedOutcomeTime > currentOutcomeTime && timestamp(imported.lastWrong) > timestamp(imported.lastCorrect)) {
        srsStage = 0;
    } else if (finalWrongTime > finalCorrectTime) {
        srsStage = Math.max(0, normalizedCount(current.srsStage));
    } else {
        srsStage = Math.max(1, normalizedCount(current.srsStage), normalizedCount(imported.srsStage));
    }
    return {
        word: imported.word,
        language: 'spanish',
        correct: Math.max(normalizedCount(current.correct), normalizedCount(imported.correct), 1),
        wrong: Math.max(normalizedCount(current.wrong), normalizedCount(imported.wrong)),
        lastCorrect: finalLastCorrect,
        lastWrong: finalLastWrong,
        lastSeen: newestIso(current.lastSeen, imported.lastSeen, finalLastCorrect, finalLastWrong),
        srsStage
    };
}

export function buildVocabularyImportPlan(parsed, vocabularyIndex, existingProgress = {}, options = {}) {
    const now = Number.isFinite(Number(options.now)) ? Number(options.now) : Date.now();
    const nowIso = new Date(now).toISOString();
    const bySurface = new Map();
    for (const entry of vocabularyIndex || []) {
        const surface = normalizeImportedSurface(entry?.word);
        if (!surface) continue;
        if (!bySurface.has(surface)) bySurface.set(surface, []);
        bySurface.get(surface).push(entry);
    }

    const mergedInputs = new Map();
    const invalid = [];
    let duplicateCount = 0;
    for (const row of parsed?.rows || []) {
        const surface = normalizeImportedSurface(row.surface);
        if (!surface) {
            invalid.push({ ...row, reason: 'Missing surface form.' });
            continue;
        }
        const correct = parseImportedDate(row.lastCorrect, now);
        const wrong = parseImportedDate(row.lastWrong, now);
        if (correct.error || wrong.error) {
            const field = correct.error ? 'last_correct' : 'last_incorrect';
            invalid.push({ ...row, reason: `${field}: ${correct.error || wrong.error}` });
            continue;
        }
        const previous = mergedInputs.get(surface);
        if (previous) duplicateCount++;
        mergedInputs.set(surface, {
            surface,
            sourceSurface: previous?.sourceSurface || row.surface,
            lines: [...(previous?.lines || []), row.line],
            lastCorrect: newestIso(previous?.lastCorrect, correct.iso),
            lastWrong: newestIso(previous?.lastWrong, wrong.iso),
            hasUndatedRow: Boolean(previous?.hasUndatedRow) || (!row.lastCorrect && !row.lastWrong)
        });
    }

    const unmatched = [];
    const ambiguous = [];
    const entries = [];
    for (const input of mergedInputs.values()) {
        const matches = bySurface.get(input.surface) || [];
        if (!matches.length) {
            unmatched.push({ surface: input.sourceSurface, lines: input.lines });
            continue;
        }
        if (matches.length !== 1 || !/^[0-9a-f]{8}$/.test(String(matches[0].id || ''))) {
            ambiguous.push({ surface: input.sourceSurface, lines: input.lines });
            continue;
        }
        const card = matches[0];
        const itemId = `es0${card.id}`;
        const importedLastCorrect = input.hasUndatedRow ? nowIso : input.lastCorrect;
        const importedLastWrong = input.lastWrong;
        const imported = {
            word: card.word,
            correct: 1,
            wrong: importedLastWrong ? 1 : 0,
            lastCorrect: importedLastCorrect,
            lastWrong: importedLastWrong,
            lastSeen: input.hasUndatedRow
                ? nowIso
                : newestIso(importedLastCorrect, importedLastWrong),
            srsStage: timestamp(importedLastWrong) > timestamp(importedLastCorrect) ? 0 : 1
        };
        const existing = existingProgress[itemId] || null;
        const progress = mergeProgress(existing, imported);
        entries.push({
            itemId,
            surface: card.word,
            progress,
            existed: Boolean(existing),
            changed: !sameProgress(existing, progress)
        });
    }

    return {
        inputRows: parsed?.rows?.length || 0,
        uniqueInputs: mergedInputs.size,
        duplicateCount,
        invalid,
        unmatched,
        ambiguous,
        matchedCount: entries.length,
        existingCount: entries.filter(entry => entry.existed).length,
        changedExistingCount: entries.filter(entry => entry.existed && entry.changed).length,
        entries,
        changedEntries: entries.filter(entry => entry.changed)
    };
}

export function buildImportBulkChunks(plan, user, chunkSize = IMPORT_CHUNK_SIZE) {
    if (!user) throw new Error('A named account is required.');
    const rows = (plan?.changedEntries || []).map(entry => ({
        user,
        itemId: entry.itemId,
        itemType: 'word',
        mode: 'normal',
        label: entry.surface,
        language: 'spanish',
        correct: entry.progress.correct,
        wrong: entry.progress.wrong,
        lastCorrect: entry.progress.lastCorrect,
        lastWrong: entry.progress.lastWrong,
        lastSeen: entry.progress.lastSeen,
        srsStage: entry.progress.srsStage
    }));
    const chunks = [];
    for (let index = 0; index < rows.length; index += chunkSize) {
        chunks.push(rows.slice(index, index + chunkSize));
    }
    return chunks;
}

export function importPlanFingerprint(plan) {
    const source = (plan?.changedEntries || [])
        .map(entry => JSON.stringify([
            entry.itemId,
            entry.surface,
            entry.progress.correct,
            entry.progress.wrong,
            entry.progress.lastCorrect,
            entry.progress.lastWrong,
            entry.progress.lastSeen,
            entry.progress.srsStage
        ]))
        .sort()
        .join('\n');
    let hash = 2166136261;
    for (let index = 0; index < source.length; index++) {
        hash ^= source.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}
