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
├── scripts/                     # Root-level one-off utilities
│   ├── finalize_vocabulary.py     # Post-build vocabulary finalization
│   └── migrate_vocab_ids.py       # One-off ID migration tool
├── research/                    # Playlist pipeline PoC — see research/CLAUDE.md
├── manifest.json / service-worker.js
├── Data/                        # Vocabulary JSON files — see Data/CLAUDE.md
│   └── Spanish/
│       ├── layers/                # Pipeline layer files — see layers/CLAUDE.md
│       ├── Scripts/               # Normal-mode pipeline scripts + orchestrator
│       └── corpora/               # Tatoeba, OpenSubtitles, Wiktionary, Jehle
└── Artists/                     # Pipeline scripts + per-artist data — see Artists/CLAUDE.md
    └── vocabulary_master.json   # Shared master vocab (all word|lemma entries + senses)
```

## Common Tasks — Start Here

| Task | Start at |
|------|----------|
| Flashcard display issue | `js/flashcards.js` → `updateCard()` (~line 960) |
| Filtering / deck logic | `js/vocab.js` → `buildFilteredVocab()` |
| Multi-artist merge | `js/vocab.js` → `mergeArtistVocabularies()`, `joinWithMaster()` |
| Master vocab / IDs | `Artists/scripts/merge_to_master.py`, `6_llm_analyze.py` → `assign_ids_from_master()` |
| Setup UI flow | `js/ui.js` → `renderLevelSelector()`, `renderRangeSelector()` |
| Level estimation | `js/estimation.js` → adaptive staircase algorithm |
| TTS / speech | `js/speech.js` → `speakWord()` |
| Auth / progress saving | `js/auth.js` → `saveWordProgress()`, `loadUserProgressFromSheet()` |
| CSS changes | `css/style.css` (single file) |
| Pipeline word analysis | `Artists/scripts/6_llm_analyze.py` |
| Pipeline reranking | `Artists/scripts/8_rerank.py` |
| Add/exclude songs | `Artists/{Name}/data/input/duplicate_songs.json` |
| Artist config | `config/artists.json` + `Artists/{Name}/artist.json` |
| Curated translation fixes | `shared/curated_translations.json` (unified), `Artists/{Name}/data/llm_analysis/curated_translations.json` (artist-specific) |
| Homograph disambiguation | `Data/Spanish/Scripts/build_inventory.py` → `compute_homograph_ratios()`, overrides in `Data/Spanish/layers/homograph_overrides.json` |
| Sense matching / embeddings | `Data/Spanish/Scripts/match_senses.py` → classify + merge + filter |
| Conjugation tables / verb data | `Data/Spanish/Scripts/build_conjugations.py`, front-end in `js/flashcards.js` → `buildConjugationTableHTML()` |

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

- **Adlib/bracket stripping**: Step 3 strips `[...]` and `(...)` content before word counting (removes ad-libs, echoes, section tags). Original text preserved in example lyrics.
- **Song exclusions**: `duplicate_songs.json` has 5 sections: `duplicates`, `placeholders`, `non_spanish`, `non_songs` (freestyles, monologues, previews, recaps), `stats`. See `Artists/DEDUP_INSTRUCTIONS.md` (includes automated scan guidance for catching remixes/live versions).
- **Short word whitelist**: Step 6 skips words <=2 chars unless in `_SHORT_WORD_WHITELIST`. If a short word gets POS=X, it probably needs adding to the whitelist.
- **Easiness scoring**: Step 8 computes median Spanish frequency rank per example sentence. Strips adlibs and ignores interjections/English/proper nouns from the median. Front-end re-scores with personal easiness (`computePersonalEasiness` in `flashcards.js`) using `Data/Spanish/spanish_ranks.json` — excludes known words so sentences get progressively harder.
- **POS=X filtering**: `buildFilteredVocab()` in `vocab.js` strips meanings with `pos=X` and empty translation. Words left with no valid meanings are removed from the deck.
- **Normal mode pipeline**: 8 steps (orchestrated by `Data/Spanish/Scripts/run_pipeline.py`) — (1) build_inventory → (2) build_examples (Tatoeba + OpenSubtitles, 50 examples/word) → (3) build_conjugations (verbecc) → (4) build_senses (Wiktionary + conjugation POS filtering + cross-POS dedup + sense cap) → (5) build_mwes (Wiktionary derived terms) → (6) match_senses (local embeddings via sentence-transformers, ~3 min) → (7) flag_cognates (suffix rules + CogNet) → (8) build_vocabulary. Step 2 loads Tatoeba first (preferred), then fills remaining slots from OpenSubtitles (stride-sampled across full corpus, `--max-lines` flag, default 5M). Quality filters: subtitle junk regex, trivial sentence filter (all top-100 words), MAX_CANDIDATES=500 cap. Scoring: proximity to target word's inventory rank + easiness, with diversity sampling across difficulty thirds. Step 3 generates conjugation tables and reverse lookup; step 4 uses the reverse lookup to filter non-VERB senses from confirmed verb entries. Step 6 classifies examples to senses using `all-mpnet-base-v2` embeddings, merges synonym senses (cosine sim ≥ 0.70), and drops senses with < 10% frequency. Use `--keyword-only` flag for instant fallback without embeddings.
- **Master vocabulary**: `Artists/vocabulary_master.json` holds all word|lemma entries with accumulated senses across all artists. 6-char hex IDs (`md5(word|lemma)[:6]`). Per-artist files hold only examples and corpus stats. Front-end joins master + artist index + artist examples at load time. Run `Artists/scripts/merge_to_master.py` to rebuild the master from existing artist vocabs.
