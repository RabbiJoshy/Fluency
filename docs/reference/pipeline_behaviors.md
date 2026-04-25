# Pipeline Behaviors — Reference

Detailed behaviors of the Fluency pipeline. This is reference material — load it on demand when working on a specific area, don't read it cover-to-cover.

For navigation see the root `CLAUDE.md` "Common Tasks" table. For the step-by-step listings see `pipeline/CLAUDE.md` and `Artists/CLAUDE.md`.

---

## Adlib / bracket stripping

The count step strips `[...]` and `(...)` content before word counting (removes ad-libs, echoes, section tags). Original text preserved in example lyrics.

## Song exclusions

`duplicate_songs.json` has 5 sections: `duplicates`, `placeholders`, `non_spanish`, `non_songs` (freestyles, monologues, previews, recaps), `stats`. See `Artists/DEDUP_INSTRUCTIONS.md` (includes automated scan guidance for catching remixes/live versions).

## Short word whitelist

Step 6 skips words ≤2 chars unless in `_SHORT_WORD_WHITELIST`. If a short word gets `POS=X`, it probably needs adding to the whitelist.

## Easiness scoring

The rerank step computes median Spanish frequency rank per example sentence. Strips adlibs and ignores interjections / English / proper nouns from the median. Front-end re-scores with personal easiness (`computePersonalEasiness` in `flashcards.js`) using `Data/Spanish/spanish_ranks.json` — excludes known words so sentences get progressively harder.

## POS=X filtering

`buildFilteredVocab()` in `vocab.js` strips meanings with `pos=X` and empty translation. Words left with no valid meanings are removed from the deck.

## Normal mode pipeline overview

10 steps (orchestrated by `pipeline/run_normal_pipeline.py`).

Entry:
```bash
.venv/bin/python3 pipeline/run_normal_pipeline.py --sense-source spanishdict --classifier gemini --max-examples 20
```

- Steps 1–4: build inventory + examples + conjugations + clitic routing.
- Step 5: build sense inventory.
- Step 6 (`step_6a_assign_senses.py`): dispatches to ONE classifier — `--classifier {keyword,biencoder,gemini}` + `--gap-fill/--no-gap-fill`.
- Steps 7a/7c: split assignments onto `word|lemma` keys + flag cognates.
- Step 10 (`step_8a_assemble_vocabulary.py`): writes the final deck.

Long-running steps: 2 (Tatoeba + OpenSubtitles) and 3 (verbecc conjugations).

**Example-level incrementality**: re-running step 6 with a larger `--max-examples` only sends new indices to Gemini; `--force` wipes prior entries.

## Master vocabulary

`Artists/vocabulary_master.json` holds all `word|lemma` entries with accumulated senses across all artists.

- 6-char hex IDs: `md5(word|lemma)[:6]`
- Per-artist files hold only examples and corpus stats
- Front-end joins master + artist index + artist examples at load time
- Run `pipeline/artist/merge_to_master.py` to rebuild the master from existing artist vocabs
- `SENSE_CYCLE` entries are never stored in the master — they exist only in the index's `sense_cycles` field

See also: `Artists/CLAUDE.md` "Shared Master Vocabulary" section for details.

## Surface form tracking

Step 3 stamps `surface` on each example (the original lyric form, e.g. `"vece'"` for key `"veces"`). Steps 6a/6b/6c substitute the canonical word into the sentence for spaCy POS tagging and sense classification, keeping the original for translation lookup.

## POS tagging

`tool_6a_tag_example_pos.py` precomputes per-example POS tags into `example_pos.json` using `es_dep_news_trf` (transformer). Incremental by default (skips unchanged words); `--force` to retag. Sense-assignment steps (6b, 6c) read this file and fall back to live spaCy only for untagged words.

## Clitic bundling

Verb+clitic forms (`calentarte`, `hacértelo`) are detected via Wiktionary form-of data and classified into 3 tiers:

- **Tier 1+2** (non-reflexive clitics, or reflexive where base has no reflexive senses) → merged into base verb, removed from deck, data preserved in `clitic_forms.json` layer (MWE-style, keyed by hex ID, with own examples and sense assignments).
- **Tier 3** (reflexive where base HAS reflexive senses, e.g. `irse`) → kept as own entry with reflexive-only senses extracted from base verb.

Detection in step 4 (`load_wiktionary_raw`); tier 3 sense extraction in `build_senses.py` post-processing; merge in builders. Both pipelines use unified method-aware assignment format with content-hash sense IDs. Clitic hex IDs preserved in master + migration maps for progress reversibility.

## Word routing (`word_routing.json`)

Step 4 produces this with buckets:
- `exclude` — `english` / `cognate` / `proper_nouns` / `interjections` / `low_frequency`
- `biencoder` (metadata only, no longer drives classifier dispatch)
- `gemini` (metadata only)
- `clitic_merge` / `clitic_keep`

Step 6 classifier processes every word that isn't in `exclude.*` or `clitic_merge`. Builder reads `exclude` sub-categories for `is_english` / `is_propernoun` / `is_interjection` flags.

## Sense files

Per artist and for normal mode, two layer files per source (`wiktionary`, `spanishdict`):

- `sense_menu/{source}.json` — sense definitions (built by `step_5c`)
- `sense_assignments/{source}.json` — method-keyed assignments in `{word: {method: [{sense, examples}]}}` form, written by `step_6b` and `step_6c`
- `sense_assignments_lemma/{source}.json` — same assignments re-keyed by `word|lemma` (written by `step_7a`)
- `unassigned_routing/{source}.json` — orphan examples routed to a lemma by POS (written by `step_7a`). Used for `SENSE_CYCLE` remainder buckets when `--remainders` is on.

Gap-fill senses are inlined in assignments (not in the menu). Method priority at build time picks the best assignment per example. See `docs/reference/method_priority.md`.

## Canonical Spanish forms

`Data/Spanish/layers/spanish_forms.json` — built offline by `pipeline/util_4a_build_spanish_forms.py` from Wiktionary form-of + verbecc + normal_vocab. Single source of truth for "is this a Spanish word" and "is this a verb form" — used by `step_4a` routing and `step_3a` elision tiebreakers.

## Builder toggles

`step_8a` (normal) and `step_8b` (artist) share two orthogonal flags:

- `--remainders` — default off; emits `SENSE_CYCLE` buckets for orphan examples
- `--min-priority N` — drops assignments below priority N; auto-assignments always pass through

`--min-priority` default is language-specific — see `docs/reference/method_priority.md`. Full flag detail in `docs/reference/builder_flags.md`.

## Derivation detection

Step 4 catches diminutives (`carita → cara`, `chiquito → chico` with `qu→c`) and gerund+clitic forms (`dándote → dar`) programmatically. These skip Gemini and get bi-encoder treatment.
