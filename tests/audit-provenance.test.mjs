import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');

test('JST and JSTA share the explicit audit-account capability', async () => {
    const [auth, flashcards, ui] = await Promise.all([
        readFile(resolve(root, 'js/auth.js'), 'utf8'),
        readFile(resolve(root, 'js/flashcards.js'), 'utf8'),
        readFile(resolve(root, 'js/ui.js'), 'utf8')
    ]);
    assert.match(auth, /new Set\(\['JST', 'JSTA'\]\)/);
    assert.match(auth, /window\.isAuditAccount = isAuditAccount/);
    assert.doesNotMatch(flashcards, /initials\s*[!=]==?\s*['"]JST['"]/);
    assert.match(ui, /window\.isAuditAccount/);
});

test('flags persist an exact run snapshot in the app and Apps Script contract', async () => {
    const [auth, modals, backend] = await Promise.all([
        readFile(resolve(root, 'js/auth.js'), 'utf8'),
        readFile(resolve(root, 'js/flashcards-modals.js'), 'utf8'),
        readFile(resolve(root, 'backend/GoogleAppsScript.js'), 'utf8')
    ]);
    assert.match(auth, /schemaVersion: 3/);
    assert.match(auth, /provenanceJson: JSON\.stringify\(provenance\)/);
    assert.match(modals, /function _flagRunProvenance/);
    assert.match(modals, /Release ID:/);
    assert.match(modals, /Run ID:/);
    assert.match(backend, /FLAG_SCHEMA_VERSION = 3/);
    assert.match(backend, /'ReleaseId', 'RunId', 'RunTimestamp', 'PromptId'/);
    assert.match(backend, /'Model', 'AssignmentMethod', 'ProvenanceJson'/);
});
