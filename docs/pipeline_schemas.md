# Pipeline Step Schemas

Per-step inputs / outputs / upstream-deps. One section per stable step id used by
`scripts/pipeline_status.py`. Labels and dep edges here should stay in lockstep
with the `STEPS` list in that file.

Conventions
- **Artist paths** are relative to `Artists/{Name}/` unless noted.
- **Normal paths** are relative to `Data/Spanish/`.
- "Shared" means one script with `--artist-dir` selecting the mode (both
  modes use the same implementation).
- Every versioned step writes either an inline `_meta` block or a
  `<output>.meta.json` sidecar via `pipeline/util_pipeline_meta.py`.

---

## Phase 1 — Acquire (artist only)

### `1a_lyrics` — download lyrics (artist only)
- **Script**: `pipeline/artist/step_1a_download_lyrics.py`
- **Inputs**: `Artists/{Name}/artist.json` (`name`, `genius_query`), Genius API
- **Outputs**: `data/input/batches/*.json` (raw lyrics + community translations)
- **Depends on**: —

### `1b_translations` — scrape community translations (artist only)
- **Script**: `pipeline/artist/step_1b_scrape_translations.py`
- **Inputs**: batches from `1a`, `Artists/curations/known_translations/` (optional overrides)
- **Outputs**: `data/input/translations/translations.json`,
  `data/input/translations/aligned_translations.json`
- **Depends on**: `1a_lyrics`

---

## Phase 2 — Extract

### `2a_inventory` — build word inventory
- **Scripts**:
  - Artist: `pipeline/artist/step_2a_count_words.py`
  - Normal: `pipeline/step_2a_build_inventory.py`
- **Inputs**:
  - Artist: `data/input/batches/`, `data/input/duplicate_songs.json`,
    `Artists/curations/{proper_nouns,interjections,skip_mwes,…}.json`
  - Normal: `Data/Spanish/corpora/frequency/*.csv` and `spanish_ranks.json`
- **Outputs**:
  - Artist: `data/word_counts/vocab_evidence.json`, `data/word_counts/mwe_detected.json`
  - Normal: `layers/word_inventory.json`
- **Depends on**: `1a_lyrics` (artist only; no-op on normal)
- **Notes**: Artist version strips `[...]`/`(...)` bracket content before counting
  (ad-libs, echoes, section tags). Normal version seeds from frequency list.

---

## Phase 3 — Normalize

### `3a_elisions` — merge Caribbean elisions (artist only)
- **Script**: `pipeline/artist/step_3a_merge_elisions.py`
- **Inputs**: `data/word_counts/vocab_evidence.json`,
  `Artists/curations/elision_mapping.json`
- **Outputs**: `data/elision_merge/vocab_evidence_merged.json` (adds `surface` field on examples)
- **Depends on**: `2a_inventory`

---

## Phase 4 — Route

### `4a_routing` — classify words by treatment
- **Scripts**:
  - Artist: `pipeline/artist/step_4a_filter_known_vocab.py` (6 phases)
  - Normal: `pipeline/step_4a_route_clitics.py` (clitic-only)
- **Inputs**:
  - Artist: merged evidence, `Artists/curations/{proper_nouns,interjections,extra_english,…}.json`,
    Wiktionary redirect + clitic data, CogNet cache
  - Normal: `layers/word_inventory.json`, Wiktionary clitic detection
- **Outputs**:
  - Artist: `data/known_vocab/word_routing.json`, `data/layers/detected_proper_nouns.json`
  - Normal: `layers/word_routing.json` (clitic buckets only)
- **Depends on**: `2a_inventory`, `3a_elisions`
- **Schema** (`word_routing.json`): top-level keys `exclude{english,proper_nouns,interjections,low_frequency}`,
  `biencoder{normal_vocab,conjugation,elision,derivation,shared}`,
  `gemini{caribbean_slang}`, `clitic_merge{word: base_verb}`, `clitic_keep[word]`.
  Normal mode emits only the clitic buckets; downstream should treat missing
  buckets as empty. **Shared helpers** (`pipeline/util_4a_routing.py`):
  `load_wiktionary_clitic_data`, `classify_clitics` (three-tier + gerund+clitic),
  and `resolve_derivation`. Both 4a scripts call into this module.

---

## Phase 5 — Build Menus

### `5a_examples` — examples layer
- **Scripts**:
  - Artist: `pipeline/artist/step_5a_split_evidence.py` (splits merged evidence
    into inventory + examples layers; carries `surface`)
  - Normal: `pipeline/step_5a_build_examples.py` (fetches Tatoeba first, then
    stride-samples OpenSubtitles; diversity sampling across difficulty thirds)
- **Inputs**:
  - Artist: `data/elision_merge/vocab_evidence_merged.json`
  - Normal: `layers/word_inventory.json`, `corpora/{tatoeba,opensubtitles,…}`
- **Outputs**: `data/layers/examples_raw.json` (both);
  artist also rewrites `data/layers/word_inventory.json`
- **Depends on**: `2a_inventory`, `3a_elisions`, `4a_routing`
- **Normal-only flags**: `--max-lines N` caps OpenSubtitles scan (default 5M).

### `5b_conjugations` — conjugation tables (normal only)
- **Script**: `pipeline/step_5b_build_conjugations.py`
- **Inputs**: `layers/word_inventory.json`, verbecc, Jehle CSVs (optional)
- **Outputs**: `layers/conjugations.json`, `layers/conjugation_reverse.json`
- **Depends on**: `2a_inventory`
- **Consumed by**: `5c_sense_menu` (verb POS filtering), `8a_assemble`

### `5c_sense_menu` — sense menu per source
- **Script** (shared): `pipeline/step_5c_build_senses.py`
  - `--sense-source wiktionary` (normal only): kaikki.org Wiktionary extract
  - `--sense-source spanishdict [--artist-dir PATH]`: SpanishDict shared cache
  - Replaces the old `pipeline/artist/tool_5c_build_spanishdict_menu.py`
- **Inputs**: `layers/word_inventory.json` (or artist equivalent),
  `layers/conjugations.json` + `layers/conjugation_reverse.json` (wiktionary path),
  `Data/Spanish/Senses/spanishdict/{surface_cache,headword_cache}.json` (spanishdict path),
  `data/known_vocab/word_routing.json` (artist spanishdict: exclude filtering)
- **Outputs**: `layers/sense_menu/<source>.json`
- **Depends on**: `2a_inventory`, `5c_spanishdict_cache`, `5b_conjugations` (wiktionary only)

### `5c_spanishdict_cache` — SpanishDict scrape cache (shared)
- **Script**: `pipeline/tool_5c_build_spanishdict_cache.py`
- **Inputs**: `layers/word_inventory.json` or `--artist-dir`, SpanishDict HTML
- **Outputs**: `Data/Spanish/Senses/spanishdict/{surface_cache,headword_cache,phrases_cache,redirects,status}.json`
- **Depends on**: `2a_inventory`
- **Status**: tracked via `status.json` — versioned via dashboard's `check_spanishdict_*` helpers rather than a per-file `_meta`.

### `5d_mwes` — multi-word expressions (normal only)
- **Script**: `pipeline/step_5d_build_mwes.py`
- **Inputs**: `corpora/wiktionary/kaikki-spanish.jsonl.gz`, inventory, examples
- **Outputs**: `layers/mwe_phrases.json`
- **Depends on**: `2a_inventory`

---

## Phase 6 — Build Assignments

### `6a_pos` — precompute spaCy POS per example (shared)
- **Script**: `pipeline/tool_6a_tag_example_pos.py`
  - Omit `--artist-dir` for normal mode; pass `--artist-dir "Artists/Name"` for artist mode.
  - Formerly two scripts; unified in this refactor.
- **Inputs**: `layers/examples_raw.json`, spaCy `es_dep_news_trf` (falls back to `es_core_news_*`)
- **Outputs**: `layers/example_pos.json` (`{word: {idx: POS}, _example_ids: {...}, _meta: {...}}`)
- **Depends on**: `5a_examples`
- **Notes**: Incremental; skips words whose example IDs haven't changed. `--force` retags all.

### `6a_assignments` — sense assignments per source
- **Scripts** (both modes now dispatch through a shared pipeline):
  - Artist dispatcher: `pipeline/artist/step_6a_assign_senses.py`
  - Normal dispatcher: `pipeline/step_6a_assign_senses.py`
  - Shared classifiers (`--artist-dir` optional):
    - `pipeline/step_6b_assign_senses_local.py` (bi-encoder / keyword)
    - `pipeline/step_6c_assign_senses_gemini.py` (Gemini Flash Lite + gap-fill)
  - The legacy monolithic normal-mode implementation is preserved at
    `pipeline/legacy_6a_assign_senses.py` for reference.
- **Inputs**: `layers/sense_menu/<source>.json`, `layers/examples_raw.json`,
  `layers/example_pos.json` (optional but recommended),
  `data/known_vocab/word_routing.json` (artist),
  `shared/curated_translations.json` (and per-artist overrides)
- **Outputs**: `layers/sense_assignments/<source>.json`
  (unified format `{word: {method: [{sense, examples, ...}]}}`)
- **Depends on**: `5a_examples`, `5c_sense_menu`, `6a_pos`
- **Method priority** (`pipeline/method_priority.py`): methods coexist per word
  additively; priority controls which is the "best" — never overwrites.

---

## Phase 7 — Consolidate

### `7a_lemma_assignments` — split assignments onto `word|lemma` keys
- **Scripts**:
  - Artist: `pipeline/artist/step_7a_map_senses_to_lemmas.py`
  - Normal: `pipeline/step_7a_map_senses_to_lemmas.py`
- **Inputs**: `layers/sense_assignments/<source>.json`, `layers/sense_menu/<source>.json`,
  `layers/example_pos.json` (artist; for unassigned-example routing)
- **Outputs**: `layers/sense_assignments_lemma/<source>.json`,
  `layers/unassigned_routing/<source>.json` (artist only)
- **Depends on**: `6a_assignments`, `5c_sense_menu`

### `7b_rerank` — ranking + easiness (artist only)
- **Script**: `pipeline/artist/step_7b_rerank.py`
- **Inputs**: lemma assignments, `layers/cognates.json`, `layers/word_inventory.json`
- **Outputs**: `data/layers/ranking.json`
- **Depends on**: `7a_lemma_assignments`, `7c_cognates`

### `7c_cognates` — flag transparent cognates (shared layer)
- **Script**: `pipeline/step_7c_flag_cognates.py` (renamed from `step_7b_flag_cognates.py` in this refactor)
- **Inputs**: auto-discovered menus in `Data/Spanish/layers/sense_menu/*.json`,
  `shared/cognet_spa_eng.json`
- **Outputs**: `Data/Spanish/layers/cognates.json` (shared by all artists + normal)
- **Depends on**: `5c_sense_menu`

---

## Phase 8 — Assemble

### `8a_lrc` — fetch LRCLIB synced lyrics (artist only)
- **Script**: `pipeline/artist/step_8a_fetch_lrc_timestamps.py`
- **Inputs**: `layers/examples_raw.json`, LRCLIB API, `data/lrclib_cache/`
- **Outputs**: `data/layers/lyrics_timestamps.json`
- **Depends on**: `5a_examples`

### `8a_assemble` — normal-mode assembly
- **Script**: `pipeline/step_8a_assemble_vocabulary.py`
- **Inputs**: all layer files (inventory, examples, menus, assignments_lemma,
  conjugations, mwe_phrases, cognates)
- **Outputs**: `Data/Spanish/vocabulary.json`, `vocabulary.index.json`, `vocabulary.examples.json`
- **Depends on**: `7a_lemma_assignments`, `5a_examples`, `5b_conjugations`, `5d_mwes`, `7c_cognates`

### `8b_artist_assemble` — artist-mode assembly
- **Script**: `pipeline/artist/step_8b_assemble_artist_vocabulary.py`
- **Inputs**: artist layers + `Artists/vocabulary_master.json`
- **Outputs**: `Artists/{Name}/{Name}vocabulary.json` (monolith),
  `{Name}vocabulary.index.json`, `{Name}vocabulary.examples.json`,
  `data/layers/clitic_forms.json`, `data/layers/archive/clitic_id_migration.json`
- **Depends on**: `7a_lemma_assignments`, `7b_rerank`, `8a_lrc`

### `8c_master` — merge artist monoliths into shared master
- **Script**: `pipeline/artist/tool_8c_merge_to_master.py`
- **Inputs**: `Artists/{*}/{*}vocabulary.json` monoliths
- **Outputs**: `Artists/vocabulary_master.json`
- **Depends on**: `8b_artist_assemble`

---

## Planned / deferred unifications

These are tracked in `TODO.md`-style comments in the dashboard `STEPS` entries:

- **6a sense assignments** *(initial unification complete — follow-ups)*.
  Both modes now dispatch through shared `pipeline/step_6{b,c}_*.py`
  classifiers (see the `6a_assignments` entry above). Remaining work:
  1. Port normal-mode-only features still living in
     `pipeline/legacy_6a_assign_senses.py` — cross-corpus sense merging via
     `sense_merges.json` and the `--english-only` token-trimming flag — into
     the shared `step_6c` behind opt-in flags, then delete the legacy file.
  2. Build a parity harness (run the legacy monolith and the new dispatcher
     on the same corpus fixture, diff outputs) before deleting the legacy.
  3. Consider retiring the separate artist dispatcher in favour of the normal
     one plus a `--artist-dir` flag — today they are near-duplicates differing
     only in arg forwarding.
