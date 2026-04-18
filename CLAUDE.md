# Fluency — AI Reference

Vocabulary flashcard PWA. Vanilla JS front-end (no framework/bundler/build step). Static JSON data. No backend. Artist vocabulary pipeline generates decks from song lyrics via NLP + Gemini.

## Repository Layout

```
Fluency/
├── index.html                   # App shell (HTML only, CSS + JS extracted)
├── css/style.css                # All CSS
├── js/                          # ES modules — see js/CLAUDE.md
├── config/
│   ├── artists.json             # Artist configs for lyrics mode (includes masterPath)
│   ├── config.json              # Language config and file path mappings
│   └── cefr_levels.json         # CEFR level definitions per language
├── backend/
│   ├── GoogleAppsScript.js      # Apps Script backend (deploy manually)
│   └── secrets.template.json    # Template for secrets.json (not in git)
├── shared/                      # Cross-pipeline shared code + data
│   ├── curated_translations.json  # Unified curated overrides (mode-tagged, both pipelines)
│   ├── flag_cognates.py           # Cognate detection logic (used by both pipelines)
│   └── cognet_spa_eng.json        # CogNet cognate database
├── pipeline/                    # All pipeline scripts — see Artists/CLAUDE.md for artist variant
│   ├── method_priority.py         # Shared METHOD_PRIORITY + sense ID helpers (both pipelines)
│   ├── classify_senses.py         # Shared classifiers: bi-encoder, Gemini, keyword, gap-fill
│   ├── build_inventory.py         # Normal-mode pipeline steps
│   ├── build_examples.py
│   ├── build_vocabulary.py        # ... (8 steps + run_pipeline.py)
│   └── artist/                    # Artist-mode variant scripts
│       ├── run_pipeline.py          # Artist pipeline orchestrator
│       ├── assign_senses.py         # Step 6: unified sense assignment (bi-encoder + Gemini)
│       ├── 6_llm_analyze.py         # ... (numbered steps + utilities)
│       └── _artist_config.py        # Shared helper for artist scripts
├── research/                    # Playlist-scraping tooling (Spotify → lyrics → lang split)
├── manifest.json / service-worker.js
├── Data/                        # Vocabulary JSON files — see Data/CLAUDE.md
│   └── Spanish/
│       ├── layers/                # Pipeline layer files — see layers/CLAUDE.md
│       └── corpora/               # Tatoeba, OpenSubtitles, Wiktionary, Jehle
└── Artists/                     # Per-artist data + curations — see Artists/CLAUDE.md
    ├── curations/                 # Shared curated lists (Spanish-flavoured today; split by language when needed)
    ├── vocabulary_master.json     # Shared master vocab for Spanish (all word|lemma entries + senses)
    ├── spanish/                   # Artists/spanish/{Name}/ — Bad Bunny, Rosalía, Young Miko
    └── french/                    # Artists/french/{Name}/ — TestPlaylist (keyword-only first pass)
```

## Common Tasks — Start Here

| Task | Start at |
|------|----------|
| Flashcard display issue | `js/flashcards.js` → `updateCard()` (~line 960) |
| Filtering / deck logic | `js/vocab.js` → `buildFilteredVocab()` |
| Multi-artist merge | `js/vocab.js` → `mergeArtistVocabularies()`, `joinWithMaster()` |
| Master vocab / IDs | `pipeline/artist/merge_to_master.py`, `6_llm_analyze.py` → `assign_ids_from_master()` |
| Setup UI flow | `js/ui.js` → `renderLevelSelector()`, `renderRangeSelector()` |
| Level estimation | `js/estimation.js` → adaptive staircase algorithm |
| TTS / speech | `js/speech.js` → `speakWord()` |
| Auth / progress saving | `js/auth.js` → `saveWordProgress()`, `loadUserProgressFromSheet()` |
| CSS changes | `css/style.css` (single file) |
| Pipeline word analysis | `pipeline/artist/step_6a_assign_senses.py` (one-classifier dispatcher; see `pipeline/CLAUDE.md`) |
| Pipeline reranking | `pipeline/artist/step_7b_rerank.py` |
| Add/exclude songs | `Artists/{lang}/{Name}/data/input/duplicate_songs.json`, `Artists/tools/scan_duplicates.py` |
| Word filter pipeline | `pipeline/artist/step_4a_filter_known_vocab.py` (parsimonious design: 5 phases, uses canonical `spanish_forms.json` for known-word lookup). Output: `word_routing.json` with `exclude`/`biencoder`/`gemini`/`clitic_merge` buckets. |
| Clitic bundling | `pipeline/step_5c_build_senses.py` → `load_wiktionary()` + `pipeline/artist/step_4a_filter_known_vocab.py` (simple rule: word ends in clitic pronoun AND base is in verb-form set; resolves to infinitive via `conjugation_reverse.json`). Builders write `clitic_forms.json`. |
| Sense assignment | `pipeline/step_6a_assign_senses.py` (normal) or `pipeline/artist/step_6a_assign_senses.py` (artist). Flags: `--classifier {keyword,biencoder,gemini}` + `--gap-fill/--no-gap-fill` (default: on for gemini, off otherwise). One classifier per invocation. Output: `sense_assignments/{source}.json` in `{word: {method: [{sense, examples}]}}` form. |
| Method priority | `pipeline/util_6a_method_priority.py` → `METHOD_PRIORITY`, `TRANSLATION_PRIORITY`, `best_method_priority()`. Gemini=50, biencoder=30, keyword=10, auto=0 (exempt from `--min-priority` filter). |
| Builder filters | `--remainders` (SENSE_CYCLE buckets, default off) and `--min-priority N` (drop low-priority claims, default 0) on both `step_8a` and `step_8b`. Orthogonal: combine to get sparsest/full/clean/catch-all decks. |
| Context disambiguation | `step_8a` dedupes on `(pos, translation, context)`; when multiple rows share `(pos, translation)` but differ in context, the context is rendered parenthetically on the translation (e.g. `uno → PRON one (numeral or indefinite)` vs `PRON one (impersonal use)`). |
| Curated overrides | `shared/archive/curated_translations.json` — each entry has a `mode` field: `wiktionary` / `spanishdict` / `all` apply per sense-source; `archive` retains but never applies. The `a → ADP: to, at` override is the only active entry today (all other legacy entries archived). |
| Artist config | `config/artists.json` + `Artists/{lang}/{Name}/artist.json` |
| Curated translation fixes | `shared/curated_translations.json` (unified), `Artists/{lang}/{Name}/data/llm_analysis/curated_translations.json` (artist-specific) |
| Homograph disambiguation | `pipeline/build_inventory.py` → `compute_homograph_ratios()`, overrides in `Data/Spanish/layers/homograph_overrides.json` |
| Sense matching / embeddings | `pipeline/match_senses.py` → classify + merge + filter |
| Conjugation tables / verb data | `pipeline/build_conjugations.py`, front-end in `js/flashcards.js` → `buildConjugationTableHTML()` |

## Detailed Docs

- **Pipeline work?** Read `Artists/CLAUDE.md`
- **Front-end JS work?** Read `js/CLAUDE.md`
- **Data schemas / IDs / progress?** Read `Data/CLAUDE.md`
- **Backlog context?** Read `TODO.md` (root — unified backlog for both modes)
- **Design docs** — `docs/design/` (WSD exploration, example selection, vocab filter design)
- **Setup guides** — `docs/setup/` (Google Sheets, quick start)

## Working with the Human

**Long-running commands:** Pipeline steps and other slow processes (>30s) should NOT be run inline. Print the command for Josh to run in his terminal — saves tokens and shows real-time progress.

**No browser previews:** Do NOT use preview tools or Claude-in-Chrome. Service worker caching makes previews unreliable. Josh tests in his own browser.

**Parallel agents:** Use sub-agents for independent tasks that don't touch the same files. Group work into waves. Keep the main conversation going across waves — agents get their own context windows.

**Safe git pushes:** Josh often has multiple Claude sessions open on the same repo. Before pushing, always `git pull --rebase` first to avoid overwriting changes from another session. If there are conflicts, stop and tell Josh rather than force-pushing. Never use `git push --force`. Proactively suggest committing and pushing after completing a logical chunk of work — don't wait for Josh to ask.

**When to suggest a new conversation:** Only when context is genuinely stale (very long chat, topic shift). When suggesting, provide a ready-to-paste prompt with: task, files involved, and decisions that carry forward.

## Dependencies

```
google-genai              # Gemini API (artist pipeline step 6, optionally 4)
lyricsgenius              # Genius API scraper (step 1)
lingua-language-detector  # English line filter (step 2, 2b)
verbecc                   # Spanish verb conjugation (pipeline step 3)
sentence-transformers     # Local embeddings for sense matching (normal mode step 5)
torch                     # PyTorch backend for sentence-transformers
```

Python 3.9+ via `.venv/bin/python3`. Dev server: `python3 -m http.server 8765` from project root.

## Key Pipeline Behaviors

- **Adlib/bracket stripping**: The count step strips `[...]` and `(...)` content before word counting (removes ad-libs, echoes, section tags). Original text preserved in example lyrics.
- **Song exclusions**: `duplicate_songs.json` has 5 sections: `duplicates`, `placeholders`, `non_spanish`, `non_songs` (freestyles, monologues, previews, recaps), `stats`. See `Artists/DEDUP_INSTRUCTIONS.md` (includes automated scan guidance for catching remixes/live versions).
- **Short word whitelist**: Step 6 skips words <=2 chars unless in `_SHORT_WORD_WHITELIST`. If a short word gets POS=X, it probably needs adding to the whitelist.
- **Easiness scoring**: The rerank step computes median Spanish frequency rank per example sentence. Strips adlibs and ignores interjections/English/proper nouns from the median. Front-end re-scores with personal easiness (`computePersonalEasiness` in `flashcards.js`) using `Data/Spanish/spanish_ranks.json` — excludes known words so sentences get progressively harder.
- **POS=X filtering**: `buildFilteredVocab()` in `vocab.js` strips meanings with `pos=X` and empty translation. Words left with no valid meanings are removed from the deck.
- **Normal mode pipeline**: 10 steps (orchestrated by `pipeline/run_normal_pipeline.py`). Entry: `.venv/bin/python3 pipeline/run_normal_pipeline.py --sense-source spanishdict --classifier gemini --max-examples 20`. Steps 1-4 build inventory + examples + conjugations + clitic routing. Step 5 builds sense inventory. Step 6 (`step_6a_assign_senses.py`) dispatches to ONE classifier: `--classifier {keyword,biencoder,gemini}` + `--gap-fill/--no-gap-fill`. Steps 7a/7c split assignments onto word|lemma keys + flag cognates. Step 10 (`step_8a_assemble_vocabulary.py`) writes the final deck. Long-running steps: 2 (Tatoeba + OpenSubtitles) and 3 (verbecc conjugations). Example-level incrementality: re-running step 6 with a larger `--max-examples` only sends new indices to Gemini; `--force` wipes prior entries.
- **Master vocabulary**: `Artists/vocabulary_master.json` holds all word|lemma entries with accumulated senses across all artists. 6-char hex IDs (`md5(word|lemma)[:6]`). Per-artist files hold only examples and corpus stats. Front-end joins master + artist index + artist examples at load time. Run `pipeline/artist/merge_to_master.py` to rebuild the master from existing artist vocabs. SENSE_CYCLE entries are never stored in the master — they exist only in the index's `sense_cycles` field.
- **Surface form tracking**: Step 3 stamps `surface` on each example (the original lyric form, e.g. "vece'" for key "veces"). Steps 6a/6b/6c substitute the canonical word into the sentence for spaCy POS tagging and sense classification, keeping the original for translation lookup.
- **POS tagging**: `tool_6a_tag_example_pos.py` precomputes per-example POS tags into `example_pos.json` using `es_dep_news_trf` (transformer). Incremental by default (skips unchanged words); `--force` to retag. Sense assignment steps (6b, 6c) read this file and fall back to live spaCy only for untagged words.
- **Clitic bundling**: Verb+clitic forms (calentarte, hacértelo) are detected via Wiktionary form-of data and classified into 3 tiers. Tier 1+2 (non-reflexive clitics, or reflexive where base has no reflexive senses) → merged into base verb, removed from deck, data preserved in `clitic_forms.json` layer (MWE-style, keyed by hex ID, with own examples and sense assignments). Tier 3 (reflexive where base HAS reflexive senses, e.g. irse) → kept as own entry with reflexive-only senses extracted from base verb. Detection in step 4 (`load_wiktionary_raw`), tier 3 sense extraction in `build_senses.py` post-processing, merge in builders. Both pipelines use unified method-aware assignment format with content-hash sense IDs. Clitic hex IDs preserved in master + migration maps for progress reversibility.
- **Word routing** (`word_routing.json`): Step 4 produces this with buckets `exclude` (english/cognate/proper_nouns/interjections/low_frequency), `biencoder` (metadata only, no longer drives classifier dispatch), `gemini` (metadata only), `clitic_merge`/`clitic_keep`. Step 6 classifier processes every word that isn't in `exclude.*` or `clitic_merge`. Builder reads `exclude` sub-categories for is_english/is_propernoun/is_interjection flags.
- **Sense files**: Per artist and for normal mode, two layer files per source (`wiktionary`, `spanishdict`):
  - `sense_menu/{source}.json` = sense definitions (built by `step_5c`)
  - `sense_assignments/{source}.json` = method-keyed assignments in `{word: {method: [{sense, examples}]}}` form, written by `step_6b` and `step_6c`
  - `sense_assignments_lemma/{source}.json` = same assignments re-keyed by `word|lemma` (written by `step_7a`)
  - `unassigned_routing/{source}.json` = orphan examples routed to a lemma by POS (written by `step_7a`). Used for SENSE_CYCLE remainder buckets when `--remainders` is on.
  Gap-fill senses are inlined in assignments (not in the menu). Method priority at build time picks the best assignment per example.
- **Canonical Spanish forms** (`Data/Spanish/layers/spanish_forms.json`): built offline by `pipeline/util_4a_build_spanish_forms.py` from Wiktionary form-of + verbecc + normal_vocab. Single source of truth for "is this a Spanish word" and "is this a verb form" — used by step_4a routing and step_3a elision tiebreakers.
- **Builder toggles**: `step_8a` (normal) and `step_8b` (artist) share two orthogonal flags: `--remainders` (default off, emits SENSE_CYCLE buckets for orphan examples) and `--min-priority N` (default 0, drops assignments below priority N; auto-assignments always pass through).
- **Derivation detection**: Step 4 catches diminutives (carita→cara, chiquito→chico with qu→c) and gerund+clitic forms (dándote→dar) programmatically. These skip Gemini and get bi-encoder treatment.
