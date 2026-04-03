# MWE-as-Sense: Implementation Plan

## Goal
Each MWE in a word's `mwe_memberships` becomes a synthetic meaning entry in the card's `meanings` array. Learners tap it like any other POS sense, see a matching lyric example, and the MWE expression is highlighted within the sentence.

## Changes

### 1. `js/vocab.js` — Synthesize MWE meanings at load time

In `loadVocabularyData()`, after building the `meanings` array from `item.meanings`, append synthetic MWE meanings:

```js
// For each MWE membership, create a synthetic meaning entry
if (item.mwe_memberships) {
    for (const mwe of item.mwe_memberships) {
        // Scan ALL existing meanings' examples for a lyric line containing the expression
        let matchedExample = null;
        for (const m of item.meanings) {
            if (!m.examples) continue;
            const match = m.examples.find(ex => {
                const text = (ex.spanish || ex.target || '').toLowerCase();
                return text.includes(mwe.expression.toLowerCase());
            });
            if (match) { matchedExample = match; break; }
        }

        meanings.push({
            pos: 'MWE',
            meaning: mwe.translation,       // "really, truly"
            expression: mwe.expression,     // "de verdad" — separate field
            percentage: 0,                  // won't show a % for MWE pills
            targetSentence: matchedExample ? (matchedExample.spanish || matchedExample.target || '') : '',
            englishSentence: matchedExample ? (matchedExample.english || '') : '',
            allExamples: matchedExample ? [matchedExample] : []
        });
    }
}
```

Do the same in the second flashcard construction site (the "incorrect words reload" path around line 343).

**Percentage normalization**: The existing normalization code runs *before* MWE meanings are appended, so MWE entries keep `percentage: 0` and don't affect the existing senses' percentages. This is intentional — MWEs aren't competing frequency senses.

### 2. `js/flashcards.js` — Render MWE pills differently

In the meaning pill loop inside `updateCard()`, detect `pos === 'MWE'` and adjust:

- **Pill left side**: Instead of `XX%`, show the expression text (e.g. "de verdad") — since percentage is meaningless for MWEs
- **Pill center**: Show the translation (e.g. "really, truly") — same as other pills
- **Pill right side**: POS badge shows "MWE"

So the pill reads: `de verdad | really, truly | MWE`

This means replacing:
```js
<span style="...">${Math.round(m.percentage * 100)}%</span>
<span style="...">${m.meaning}</span>
<span class="card-pos ...">${m.pos}</span>
```

With a conditional: if `m.pos === 'MWE'`, show `m.expression` in the left slot instead of the percentage.

### 3. `css/style.css` — Add MWE POS color

Add a `.pos-mwe` class to the existing POS color scheme. A warm gold/amber that's distinct from existing colors:

```css
.pos-mwe { background: rgba(251, 191, 36, 0.2); border-color: rgba(251, 191, 36, 0.5); color: #fbbf24; }
```

### 4. `js/flashcards.js` — `getPosColorClass()` update

Add MWE mapping:
```js
if (posLower === 'mwe') return 'pos-mwe';
```

### 5. `js/flashcards.js` — Highlight MWE expression in example sentence

When the selected meaning is an MWE (`currentMeaning.pos === 'MWE'` and `currentMeaning.expression` exists), wrap occurrences of the expression in the displayed target sentence with a highlight span:

```js
if (currentMeaning.expression) {
    const regex = new RegExp(`(${escapeRegex(currentMeaning.expression)})`, 'gi');
    displayTargetSentence = displayTargetSentence.replace(regex,
        '<span style="font-weight: 700; color: var(--accent-secondary);">$1</span>');
}
```

### 6. Remove the standalone MWE box

Delete the "Part of" display block (lines 972-979) that was added earlier — MWEs are now shown as meaning pills, so the standalone section is redundant. Also remove `mweMemberships` from the card object since MWEs are now inside `meanings`.

## What doesn't change
- No pipeline changes — `BadBunnyvocabulary.json` stays as-is
- No Gemini API calls
- `selectMeaning()` and `cycleExample()` work unchanged — MWE senses are just meanings with special rendering
- Percentage normalization is unaffected (MWEs are appended after normalization)
- Non-Bad-Bunny vocab is unaffected (no `mwe_memberships` field = no synthetic meanings)

## Edge cases
- **No matching example**: If no existing lyric line contains the MWE expression, the MWE sense shows with no example sentence (same as any meaning with no examples)
- **Words with many MWEs**: "que" has 22 MWEs — this will produce 22 extra pills. Could cap at ~5 most common, but let's see how it looks first and cap later if needed
- **Case/accent sensitivity in matching**: Use case-insensitive matching. Caribbean elisions (e.g. "pa'" vs "para") may cause some misses — acceptable for now
