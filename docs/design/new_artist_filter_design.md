---
title: Artist vocabulary filter
status: implemented
created: 2026-04-07
updated: 2026-04-07
---

# New Artist Vocabulary Filter — Design Notes

Reference for the vocabulary filter step that reduces an artist's raw word list to only the words that need Gemini analysis.

## Problem (2026-04-07)

The current pipeline sends ~11,000 words per artist through step 6 (Gemini analysis). Most of these are standard Spanish words that already exist in normal mode or are proper nouns / English / junk. Step 4 (proper noun detection via capitalization + spaCy + curated lists) catches some, but the Gemini cost is still dominated by words that don't need analysis.

## Key insight

An artist's vocabulary is mostly standard Spanish. The interesting words — Caribbean slang, profanity, regionalism — are a small fraction. By subtracting known Spanish words through a chain of free set operations, we can reduce the Gemini workload by ~93%.

## Empirical data (Bad Bunny)

Tested against Bad Bunny's 11,546 words from `vocab_evidence_merged.json`:

| Filter step | Words removed | Running total remaining |
|---|---|---|
| Starting vocabulary | — | 11,546 |
| Subtract es_50k wordlist | 8,183 | 3,363 |
| Subtract conjugation_reverse.json | 202 | 3,065 |
| Subtract shared lists (proper_nouns, interjections, extra_english) | 96 | 3,065 → 2,969 |
| Lingua English filter (≥0.90 confidence) | 250 | ~2,720 |
| Cut frequency=1 | ~1,900 | ~820 |

The ~820 remaining words are overwhelmingly real Caribbean Spanish vocabulary (perreo, bellaca, bichote, frontear, janguear, chamaquito, etc.) with ~30-40 proper nouns mixed in. Those proper nouns get tagged PROPN naturally by Gemini during normal step 6 analysis — no separate detection step needed.

## Implementation

This is a single pipeline step — e.g., `4_filter_known_vocab.py`. Takes `vocab_evidence_merged.json` as input, outputs a reduced word list for step 6. All substeps below are sequential set operations in one script, runs in seconds.

### 1. Normalize elisions
Map contracted forms to standard Spanish using the elision merge step. `pa'` → `para`, `to'` → `todo`, etc. Check the standard form against subsequent filters.

### 2. Subtract normal mode vocabulary
Word forms from `Data/Spanish/vocabulary.json` (~10k words). Mostly subsumed by step 3, but catches lemma forms the frequency list might miss.

### 3. Subtract es_50k wordlist
FrequencyWords Spanish 50k list from OpenSubtitles (`Data/Spanish/es_50k_wordlist.txt`). This is the biggest single filter — removes ~71% of words.

Source: `https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/es/es_50k.txt`
Format: `word count` per line, sorted by frequency. One-time download.

### 4. Subtract conjugation reverse lookup
`Data/Spanish/layers/conjugation_reverse.json` maps ~84k inflected forms → infinitives. Catches conjugated forms of known verbs that aren't in the 50k wordlist (e.g., `llueven`, `boté`, `prendías`).

### 5. Subtract shared curated lists
- `Artists/curations/proper_nouns.json` (~145 entries)
- `Artists/curations/interjections.json`
- `Artists/curations/extra_english.json`

These accumulate across artists.

### 6. Lingua language detection
Run `lingua-language-detector` (already a dependency) on remaining words. Remove any word classified as English with ≥0.90 confidence. Catches obvious English (`flow`, `shirt`) without false-positiving on ambiguous words (`trap`, `carbon`, `combo`).

**Known limitation (2026-04):** Lingua fails on short/common English words — `babies`, `boobies`, `wannabes`, `fit`, `hoes`, `goddamn`, `milf`, `wifey`, `picky` all pass through at 0.90 threshold because single-word character n-gram detection can't confidently distinguish them. Proposed fix: supplement with a common English word list (top 20-30k). By this point in the filter chain, Spanish homographs (no, pan, solo) are already removed by the 50k Spanish wordlist, so false positive risk from the English list is low. The real question is "would an English speaker recognise this word?" — a frequency list answers that directly without needing NLP.

### 7. Cut frequency=1
Words appearing only once in the artist's corpus. This removes ~1,600 words — mostly single-mention proper nouns, OCR artifacts, English words, and very rare slang. Biggest single reduction after step 3.

Trade-off: a few genuine slang words get lost. Acceptable because a word used once in the entire corpus is unlikely to be encountered by a listener.

### 8. Send remainder to Gemini
~600-850 words get full step 6 analysis: translation, POS, lemma, sense assignment. Proper nouns are tagged PROPN as part of normal analysis — no separate detection step needed.

## What this replaces

This step replaces **step 4 (`4_detect_proper_nouns.py`)** in the pipeline. Capitalization heuristics only caught 7-87 words depending on threshold, and spaCy NER added complexity for marginal gain. The filter chain removes most proper nouns via the 50k list and shared lists; the ~30-40 that remain are cheaply handled by Gemini during normal step 6 analysis.

Gemini-based proper noun classification (previously considered as an alternative) is also unnecessary. The set-difference approach is faster, free, and more reliable.

## Open questions

### 1. Elision normalization

The hardcoded `elision_canonical()` map covers common cases (pa', to', vo'a, tá, etc.) but misses rarer forms. Step 5's `elision_mapping.json` already knows every elision pair it found — entries with `action: skip` are contractions step 5 left as-is but knows the canonical form for. The filter could load this mapping to resolve more elisions instead of relying on the hardcoded list. This would make the elision filter artist-aware and more complete.

### 2. Single-occurrence words

Current behavior: freq=1 words are cut and don't go to Gemini. Proposed design for these:

- They still exist in the data (in `vocab_evidence_merged.json` and the artist's word inventory)
- They don't get a Gemini translation — the front-end shows them as "unknown" or greyed out
- Users can manually mark them if they know the word
- A "hide single-occurrence words" toggle in the UI keeps the deck focused
- **Multi-artist accumulation**: a word that's hapax in Bad Bunny but also appears once in Rosalía becomes freq=2 across the combined corpus and gets promoted to Gemini analysis. This is the right behavior — if a word shows up across multiple artists, it's worth learning regardless of per-artist frequency.

### 3. Proper noun display threshold

After the filter chain, proper nouns that survive (freq≥2, not in 50k Spanish) go to Gemini and get tagged PROPN with a translation as part of normal step 6 analysis. The pipeline doesn't need a separate threshold — the frequency cut already handles it.

The remaining question is front-end: should PROPN entries show by default or behind a toggle? Some proper nouns are culturally useful (Ponce = city in Puerto Rico, Balvin = J Balvin), others are noise. Options:
- Show all PROPN by default, let users skip individually
- Hide PROPN by default, let users opt in (like the cognate toggle)
- Show only PROPN above a frequency threshold (e.g., freq≥5)

### 4. Normal mode reuse at display time

Words removed by the filter chain still appear in lyrics. Should the front-end pull their translations from normal mode vocabulary, or just skip them? If pulled, the join logic in `vocab.js` needs updating.

### 5. Updating shared lists

Should the pipeline auto-append newly discovered proper nouns / English / interjections to the shared lists after each artist run, so subsequent artists benefit?
