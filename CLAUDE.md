# Fluency — AI Reference

> **Don't bulk-read layer JSON files** (`vocabulary_master.json`, `sense_assignments/*.json`, etc.) — Grep them for the keys you need.
> **For deep reference** (file formats, builder flags, step internals, pipeline behaviors), read the linked `docs/reference/` files on demand.

Vocabulary flashcard PWA. Vanilla JS front-end (no framework/bundler/build step). Static JSON data. No backend. Artist vocabulary pipeline generates decks from song lyrics via NLP + Gemini.

## Repository Layout

```
Fluency/
├── index.html                   # App shell
├── css/style.css                # All CSS
├── js/                          # ES modules — see js/CLAUDE.md
├── config/                      # artists.json, config.json, cefr_levels.json
├── backend/                     # GoogleAppsScript.js (deploy manually)
├── shared/                      # Cross-pipeline shared code + data
├── pipeline/                    # All pipeline scripts — see pipeline/CLAUDE.md
│   └── artist/                  # Artist-mode variants
├── research/                    # Playlist scraping — see research/CLAUDE.md
├── manifest.json / service-worker.js
├── Data/                        # Vocabulary JSON — see Data/CLAUDE.md
│   └── Spanish/layers/          # Pipeline layers — see layers/CLAUDE.md
├── Artists/                     # Per-artist data + curations — see Artists/CLAUDE.md
└── docs/                        # On-demand docs — see docs/design/CLAUDE.md
    ├── reference/               # Deep reference (load on demand)
    └── setup/                   # Setup + onboarding guides
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
| Word filter pipeline | `pipeline/artist/step_4a_filter_known_vocab.py` (5 phases, uses `spanish_forms.json`). Output: `word_routing.json` with `exclude`/`biencoder`/`gemini`/`clitic_merge` buckets. |
| Clitic bundling | `pipeline/step_5c_build_senses.py` → `load_wiktionary()` + `pipeline/artist/step_4a_filter_known_vocab.py`. Builders write `clitic_forms.json`. |
| Sense assignment | `pipeline/step_6a_assign_senses.py` (normal) or `pipeline/artist/step_6a_assign_senses.py` (artist). Flags: `--classifier {keyword,biencoder,gemini}` + `--gap-fill/--no-gap-fill`. Output: `sense_assignments/{source}.json`. |
| Method priority | `pipeline/util_6a_method_priority.py` — see `docs/reference/method_priority.md` for the full table. |
| Builder filters | `--remainders` and `--min-priority N` on `step_8a` / `step_8b`. See `docs/reference/builder_flags.md`. |
| Context disambiguation | `step_8a` dedupes on `(pos, translation, context)`; renders context parenthetically when needed. |
| Curated overrides | `shared/curated_translations.json` (mode-tagged) and per-artist overrides. |
| Artist config | `config/artists.json` + `Artists/{lang}/{Name}/artist.json` |
| Homograph disambiguation | `pipeline/build_inventory.py` → `compute_homograph_ratios()`, overrides in `Data/Spanish/layers/homograph_overrides.json` |
| Sense matching / embeddings | `pipeline/match_senses.py` → classify + merge + filter |
| Conjugation tables / verb data | `pipeline/build_conjugations.py`, front-end in `js/flashcards.js` → `buildConjugationTableHTML()` |

## Detailed Docs

- **Pipeline work?** Read `pipeline/CLAUDE.md` (both modes) and `Artists/CLAUDE.md` (artist mode specifics)
- **Front-end JS work?** Read `js/CLAUDE.md`
- **Data schemas / IDs / progress?** Read `Data/CLAUDE.md`
- **Pipeline layer files?** Read `Data/Spanish/layers/CLAUDE.md`
- **Backlog context?** Read `TODO.md` (root — unified backlog for both modes)
- **Design docs** — `docs/design/` (WSD exploration, example selection, vocab filter design)
- **On-demand reference** — `docs/reference/` (pipeline behaviors, builder flags, method priority, sense-assignment internals)
- **Setup guides** — `docs/setup/` (Google Sheets, artist pipeline quick start, new-artist onboarding)

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

Detailed behaviors (adlib stripping, song exclusions, short-word whitelist, easiness scoring, POS=X filtering, normal mode pipeline, master vocabulary, surface form tracking, POS tagging, clitic bundling, word routing, sense files, canonical Spanish forms, builder toggles, derivation detection) live in `docs/reference/pipeline_behaviors.md`. Read it on demand when you need a specific one.
