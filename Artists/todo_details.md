# Todo Details

Companion to `todo.txt`. Each section expands on a todo item with context, decisions made, and implementation notes for future sessions.

---

## Normal mode parity [high]

Artist mode is significantly ahead of normal vocabulary mode. Key gaps identified:

- **Example sentence cycling** — artist mode cycles through multiple examples per word (`allExamples` + `currentExampleIndex`). Normal mode shows a single static example.
- **Easiness-based sorting** — artist mode sorts cards by personal easiness (`computePersonalEasiness` in `flashcards.js`), showing harder sentences first. Normal mode uses static ordering.
- **Improved card layout** — artist mode has album art backgrounds, artist attribution on examples, and a more polished card face layout.

**Starting point**: Compare `loadVocabularyData()` and `updateCard()` code paths for `activeArtist` vs normal mode to identify exactly what's missing. The `isMultiMeaning` flag is always `true` in artist mode but the code still has legacy single-meaning paths.

**Note**: Josh wasn't ready for this in the April 2025 session. Don't start without asking.

---

## Shared master vocabulary architecture

### Problem

Each artist's pipeline independently generates vocabulary entries (word, lemma, POS, translation, meanings) and assigns hex IDs via `md5(word|lemma)[:4]`. When two different `word|lemma` pairs collide within one artist's vocab, `assign_unique_ids()` reassigns one to a suffix-based hash — making the ID no longer deterministic from `word|lemma`. This causes:

- **Cross-artist ID collisions**: 336 cases where different words in Bad Bunny and Rosalia share the same 4-char ID (e.g., "rinde"/"francotiradora" both get `f8c6`). The front-end merge Frankensteins them into one card.
- **Same word, different ID**: 380 cases where the same `word|lemma` pair gets different IDs across artists because collision reassignment happened in one artist's vocab but not the other.
- **Normal-vs-artist mode mismatch**: 817 additional cases where normal mode and artist mode disagree on lemma for the same surface word (e.g., "abierta" → lemma "abrir" in normal, "abierto" in artist). These are lemmatization differences, not hash issues, and are arguably correct (different analysis = different card).

### Design direction

The vocabulary entries (word, lemma, POS, translations/senses) are largely the same regardless of which artist they appear in. Only the **example sentences** differ per artist. The idea:

1. **Master vocabulary file** — one source of truth for all `word|lemma` entries, accumulating senses across all artists. Each artist's Gemini run can discover new senses (a word used differently in reggaeton vs flamenco), which get added to the master.
2. **Per-artist example files** — each artist contributes examples (lyrics) linked to specific senses in the master vocabulary.
3. **`--no-gemini` reuse** — when running without Gemini, pull existing senses from the master vocab instead of producing lower-quality entries.

### Key files

- ID generation: `Artists/scripts/6_llm_analyze.py:212-232` (`make_stable_id`, `assign_unique_ids`)
- Front-end merge: `js/vocab.js:948-1082` (`mergeArtistVocabularies`)
- Progress keys: `js/vocab.js:17-22` (`getWordId`)
- Current per-artist outputs: `{Artist}vocabulary.json` (monolith), `.index.json`, `.examples.json`

### Open questions

- Exact file structure: one `vocabulary_master.json` at project root? Per-language?
- How senses link to examples: index into meanings array? POS+translation key?
- Migration path: generate master from existing artist vocabs, or rebuild from scratch?
- Hash length: should increase to 8 chars regardless (eliminates collision reassignment, making IDs truly deterministic)

---

## General vocab for level estimation

Currently the level estimation quiz uses whatever vocabulary is active (artist vocab in artist mode, general vocab in normal mode). Artist vocabularies are genre-biased (reggaeton slang ranks highly), which skews the estimate.

**Idea**: Always estimate against the base Spanish frequency list (`Data/Spanish/`) regardless of mode. This gives a truer picture of general Spanish proficiency.

**Open question**: How to map the result back to the artist deck. A word at rank 200 in general Spanish might be rank 3000 in Bad Bunny's corpus (or not appear at all). Options discussed:
1. Filter artist words by their general Spanish rank — if you know ~2000 general words, show artist words whose general rank is >2000
2. Just use the number as a rough starting point in the artist deck

Neither was chosen yet. Needs more thought on the mapping strategy.

---

## Spotify links [low] — partially done

Spotify track IDs are looked up via `Artists/scripts/spotify_lookup.py` using the Spotify Web API (client credentials flow). The script reads each artist's `*vocabulary.examples.json`, collects unique song names, and queries `GET /v1/search?q=track:{song} artist:{artist}&type=track&limit=1`.

**Current state**:
- Bad Bunny: 248/302 songs matched (82%). Results in `Artists/Bad Bunny/data/spotify_tracks.json` and combined in `Data/spotify_tracks.json`.
- Rosalía: **not yet run** — got rate-limited on first attempt. Just re-run the script after the limit resets.
- Front-end is fully wired: `vocab.js` loads `Data/spotify_tracks.json` at startup, `flashcards.js` shows a green Spotify icon next to the song name when a match exists. Tapping opens `https://open.spotify.com/track/{id}` which deep-links into the Spotify app on mobile.

**Missed songs**: ~54 Bad Bunny songs didn't match. Mostly Genius title quirks (asterisks like `Siempre Picheo*`, slashes like `Calm Down / Party (Mixed)`, DJ mixes, some obscure features). Could add manual overrides to `spotify_tracks.json` if desired.

**Credentials**: `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env` (gitignored). Spotify app is in development mode (Josh's Spotify developer dashboard).

**Key files**:
- Script: `Artists/scripts/spotify_lookup.py`
- Per-artist output: `Artists/{Name}/data/spotify_tracks.json`
- Combined front-end data: `Data/spotify_tracks.json`
- Front-end loading: `js/vocab.js` (~line 170)
- Front-end button: `js/flashcards.js` (~line 1092, song name display area)
- CSS: `css/style.css` (`.spotify-btn` class)

---

## Auto-populate albums dictionaries [deferred]

`albums_dictionary.json` is manually curated per artist (maps songs to albums for album art display). Genius has album objects with track listings — a pipeline step could scrape these to auto-assign songs.

Would save manual work when adding new artists or when an artist drops a new album. Not urgent since only 2 artists exist and their dictionaries are complete.

---

## Decisions made (for context)

### Per-artist verse filtering — decided against
Filtering corpus to only the primary artist's verses (e.g., only Bad Bunny's lines, not featured artists). Decided against because:
- The goal is understanding the songs, not just the artist's personal vocab
- Feature verses are in Spanish and help learners understand the full song
- Genius verse labels are community-contributed and unreliable
- Would gut collaborative albums (OASIS with J Balvin, etc.)
- Existing filters (English line stripping, non-song exclusions, adlib removal) already handle the real quality problems

### Level estimation algorithm
Rebuilt from batch binary search (5 words, score, jump) to adaptive staircase:
- One word at a time, step size halves on direction reversals
- Translation can be revealed before answering to confirm knowledge
- Converges when step < 50 and 5 consecutive correct, or 30 words max
- Retest option seeds near previous result for faster convergence
- Initial step is 1/6 of max level (was 1/4, felt too slow to converge)

### Service worker strategy
Switched from cache-first to network-first for all assets. No need to bump `CACHE_NAME` on deploys anymore. Cache is only an offline fallback.

### Song exclusion approach
DEDUP_INSTRUCTIONS.md has an "Automated scan" section describing how to generate a one-off Python script to catch remixes/live versions/DJ mixes. The script is disposable — don't commit it. ~20 Bad Bunny remix-only tracks were intentionally kept because they're feature tracks where the remix is the only version of the song.
