import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = path => fs.readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('completed new-card sets continue automatically without replaying completed sets', () => {
    const ui = source('js/ui.js');
    const modals = source('js/flashcards-modals.js');
    const cards = source('js/flashcards.js');
    const continuation = ui.slice(
        ui.indexOf('async function startNextStudyLevelFirstSet()'),
        ui.indexOf('\n\nfunction showStatsModal()'),
    );

    assert.match(continuation, /while \(true\)/u);
    assert.match(continuation, /const firstUnseenSet = setDots\.find/u);
    assert.match(continuation, /Number\(dot\.dataset\.pct \|\| 0\) < 100/u);
    assert.doesNotMatch(continuation, /\|\| setDots\.find/u,
        'continuation must never fall back to replaying a completed set');
    assert.match(modals, /stats\.studyMode === 'new'/u);
    assert.match(modals, /finishBtn\.click\(\);[\s\S]*?\}, 1200\);/u);
    assert.match(modals, /function hideDeckCompleteModal\(\) \{\s*_cancelDeckCompleteAutoContinue\(\)/u);
    assert.match(cards, /showEndOfDeckOptions\?\.\(\{ autoContinue: false \}\)/u,
        'a failed continuation must reopen without an automatic retry loop');
});

test('flagging immediately shows a global card and resolves to Card flagged', () => {
    const modals = source('js/flashcards-modals.js');
    const html = source('index.html');
    const css = source('css/style.css');
    const sendStart = modals.indexOf('async function _sendSimpleFlag');
    const pending = modals.indexOf('showFlagSentToast(typeLabel, false, true)', sendStart);
    const save = modals.indexOf('await flagWord(card, fieldPath, report, fields)', sendStart);

    assert.ok(pending > sendStart && pending < save,
        'the flag card must appear before the durable save can block');
    assert.match(modals, /isError \? 'Flag not sent' : 'Card flagged'/u);
    assert.match(modals, /toast\.setAttribute\('aria-busy', String\(isPending\)\)/u);
    assert.match(html, /id="flagSentToastTitle">Card flagged</u);
    assert.match(css, /\.flag-sent-toast\s*\{[\s\S]*?z-index: 30002;/u);
    assert.match(css, /\.flag-sent-toast\.is-pending/u);
});
