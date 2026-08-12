import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');

test('routing abstentions are explicit Artist Extra cards', async () => {
    const vocab = await readFile(resolve(root, 'js/vocab.js'), 'utf8');
    assert.match(
        vocab,
        /ARTIST_EXTRA_CATEGORIES = new Set\([\s\S]*'unresolved'/,
    );
    assert.match(vocab, /unresolved: 'Needs classification'/);
    assert.match(vocab, /extra_category: idx\.extra_category \|\| m\.extra_category/);
    assert.match(vocab, /absence is not new proof[\s\S]*core Spanish/);
});
