# Codex changes and cross-model handoff

This file tells Claude and future Codex sessions what Codex changed, why, and how it was checked. Git remains authoritative for exact diffs; `config/dev_changelog.json` remains the in-app user-visible history; `TODO.md` remains the backlog.

Maintenance rule: after each completed Codex task, prepend a dated entry to **Codex task history** after the commit exists. Include the final commit hash, user-visible result, non-obvious decisions, verification, and cache version for front-end work. Do not silently rewrite an earlier decision—add a newer entry explaining the change.

## Current architectural decisions from the Codex work

- Study decks use finishable frequency levels and stable, discrete study sets. Set identity is rank-based so changing Merge Lemmas or Cognates does not reshuffle the underlying set boundaries.
- The normal setup and active-study flow share radial pickers and a discrete progress rail. Partial level progress is visible, and study sets are intended to feel independently completable.
- Merge Lemmas is the user-facing name. It is off by default; Exclude Cognates is off by default.
- Artist corpus frequency excludes exact repeated lyric lines within each song. Lemma-mode card frequency and examples use the same pooled sibling basis.
- Artist rank ties use each word's full distinct-song spread, not the capped example sample. Artist lyric examples prefer an explicitly credited active artist, Spotify availability, and a standard release in that order before the teaching signals.
- Desktop lyric autoplay is bounded to the displayed example's start and inferred end and advances through the card examples once; it is intentionally unavailable on mobile where Spotify handoff timers cannot guarantee the stop boundary.
- Card grammar uses separate POS pills, English morphology labels, POS-linked colour, pooled-form highlighting, and a grouped/linked card-back layout. Trivial plural and elision form metadata is suppressed on the back.
- SpanishDict sense menus for normal and artist modes share `pipeline/util_5c_spanishdict.py`; reverse-direction conjugation collisions such as `sea` are guarded there rather than patched only in a final deck.
- Flags default to the visible sense–example pairing, accept a free-text note, and store a structured report through the existing FlaggedWords backend contract.

## Codex task history

### 2026-07-25 — Persistent artist/source setup card

- Commit `9a26780e`; front-end cache `flashcards-v85` / `20260725ad`.
- Lyrics setup now shows the active artist in a source card that can reopen the same-language artist radial picker or return directly to Speech setup in that language.
- Changed the redundant outer heading from Choose Language to Language and lightened Young Miko's secondary accent from `#1A1A2E` to `#C4B5FD` for dark-background contrast.
- Verification: JavaScript syntax, artists JSON validation, cache lockstep, and `git diff --check` passed; no service-worker browser preview was used.

### 2026-07-25 — Explicit study-completion routes

- Commit `87b015ca`; front-end cache `flashcards-v84` / `20260725ac`.
- Every completed set now retains a separate Back to main menu action. The primary continuation moves forward through unfinished sets without wrapping to an earlier set.
- The structurally final set of a level offers the first available set of the next level when one exists; the final level falls back to the main-menu action alone.
- Verification: JavaScript syntax, cache lockstep, and `git diff --check` passed; no service-worker browser preview was used.

### 2026-07-25 — Artist metadata and timestamp rebuild

- Commit `b185f23d`; no front-end files changed, so the current cache remains `flashcards-v83` / `20260725ab`.
- Rebuilt Bad Bunny, Rosalía, and Young Miko using only steps 2, 3, 5, 7b, 8, and build. Translation scraping, routing, POS tagging, Gemini sense assignment, and lemma remapping were skipped; existing sense layers were read unchanged.
- All 11,386 Bad Bunny, 3,392 Rosalía, and 4,692 Young Miko inventory entries now carry the corpus-wide song count. The shipped decks retain the same 45,510 song/sentence example multiset, reordered by the new preferences; 38,353 rendered example occurrences have exact end boundaries.
- Eight uncached Bad Bunny LRCLIB lookups failed offline and were left uncached so a connected future run can retry them. Their examples safely remain without autoplay boundaries rather than using guessed end times.
- Verification: six pipeline tests, Python and JavaScript syntax checks, all changed JSON files, cache lockstep, and `git diff --check` passed; no service-worker browser preview was used.

### 2026-07-25 — Sense–example flag reports with notes

- Commit `64b10f8a`; front-end cache `flashcards-v83` / `20260725ab`.
- The flag menu now defaults to the exact selected sense and rendered example, previews them together, and accepts an optional 600-character note. Alternatives are sense only, lemma, and whole card.
- Reports include word, lemma, sense/POS/context, Spanish example, English translation, source song, and note as applicable. They use a stable pairing path and store structured readable text in the existing FlaggedWords `word` value column, so no ninth column or Apps Script deployment is needed.
- Verification: JavaScript syntax checks, cache lockstep assertions, changelog JSON validation, and `git diff --check` passed; no service-worker browser preview was used.

### 2026-07-25 — Strict line-bounded lyric autoplay

- Commit `49ea0b88`; front-end cache `flashcards-v82` / `20260725aa`.
- LRCLIB parsing now keeps empty timestamp rows as real boundaries, uses the next timestamp as `end_ms`, and falls back to track duration only for the final line; step 8b carries it as `end_timestamp_ms`.
- A desktop card control plays only the displayed lyric interval, pauses slightly before its end, advances through the current example list once, skips missing/implausible boundaries, and cancels on navigation or tab hide. Mobile omits the control because Connect handoff cannot guarantee a foreground stop timer.
- Verification: six unit tests plus Python/JavaScript syntax, cache lockstep, changelog JSON, and diff checks passed. Existing Bad Bunny caches yielded 9,706/9,706 matched examples with ends and 9,651 strict-duration-eligible intervals. Re-run 8a and 8b after rebuilding examples; no Gemini rerun is required.

### 2026-07-25 — Credited and prioritised lyric examples

- Commit `e5857ef`; front-end cache `flashcards-v81` / `20260725z`.
- Step 2 parses explicitly named Genius section performers, preserves them through existing raw-example indices, and leaves generic sections unknown. The card shows the available singer credit beneath the lyric.
- Artist examples now sort by active-artist singer credit, Spotify availability, and standard-release status before the existing translation, mistake, length, deck-neighbour, and easiness signals.
- Verification: four pipeline unit tests and Python/JavaScript syntax checks passed. Across 537 Bad Bunny records, enriched cleaning found 23,799 explicitly credited content lines and produced zero cleaned-line-sequence mismatches, preserving IDs. Rebuild from step 2/3/5/8b is needed; steps 6 and 7a/Gemini need not rerun.

### 2026-07-25 — Corpus-accurate distinct-song ranking

- Commit `a85e17f`; pipeline-only change, so no front-end cache bump.
- Step 2 now records the complete distinct song-ID set for every word on the same exact-line-deduplicated corpus basis as frequency; elision normalization unions those sets and step 5 carries their counts into the inventory.
- Step 7b now uses the inventory count for the third ranking key (after corpus count and general Spanish rank), with capped retained examples only as a legacy fallback.
- Verification: three unit tests cover chorus deduplication, song-ID union across variants, and song-count ranking; Python compilation, changelog JSON validation, and `git diff --check` passed. Rebuilding from step 2 is required to populate existing artist data; Gemini steps need not be rerun.

### 2026-07-25 — Language-first learning source

- Commit `7237b94`; front-end cache `flashcards-v80` / `20260725y`.
- Removed the landing top-bar mode switch. Choosing a language now opens a radial Speech/Lyrics decision; Speech continues subtitle setup and Lyrics opens the existing artist clock filtered to that language.
- Preserved direct artist URLs and exact saved-set resume routes, and refreshed the stale setup/help copy to describe stable small sets and the new source choice.
- Verification: JavaScript syntax checks, changelog JSON validation, cache lockstep assertions, and `git diff --check` passed; no service-worker browser preview was used.

### 2026-07-25 — Study feedback and progress surfaces

- Commit `e23684b`; front-end cache `flashcards-v79` / `20260725x`.
- Rebuilt the set-complete result around one contextual primary action plus restrained review and restart actions, with consistent typography and spacing.
- Made landing and in-set progress details explicit information-button actions, clarified weighted coverage in the all-time modal, and replaced ambiguous literal question marks with accessible information icons.
- Verification: JavaScript syntax checks, changelog JSON validation, cache-version search, and `git diff --check` passed; no browser preview was used because this repo's service worker makes it unreliable.

### 2026-07-25 — Account-first settings and persistent study defaults

- Commit `1ab5eeb`; front-end cache `flashcards-v78` / `20260725w`.
- Made the settings gear open Account rather than overriding the HTML state with Advanced.
- Added warned, device-wide defaults for Merge Lemmas and Exclude Cognates that apply to new Speech/Lyrics setups and refresh the current setup immediately.
- Exact saved-set resume continues to restore the saved set's own configuration.

### 2026-07-25 — Partial progress on study-set choices

- Commit `c118fdd`; front-end cache `flashcards-v77` / `20260725v`.
- Added proportional progress fill to every started-but-incomplete set cell, using the same percentage as the set detail and accessible label.
- Preserved the separate current-set focus ring, solid completed state, and unavailable state.

### 2026-07-25 — Inflected English text-to-speech

- Commit `b2672c5`; front-end cache `flashcards-v76` / `20260725u`.
- Routed English speech on flips, sense changes, grouped translations, and swipe navigation through the same conjugation-aware helper as the visible gloss.
- A surface such as `merezco` now displays and speaks “I deserve” instead of speaking the underlying infinitive “to deserve.”

### 2026-07-25 — Audited follow-up backlog

- Commit `cc0c8b0`.
- Captured Josh's settings, study-flow, progress, completion, artist-example, autoplay, ranking, TTS, and flagging requests in `TODO.md` with the relevant current-code findings and dependencies.
- No app behavior or deck data changed in this task.

### 2026-07-25 — Persistent Codex/Claude handoff

- Commit `a58c930`.
- Added this ledger, linked it from `CLAUDE.md`, and added root `AGENTS.md` instructions so both Claude and future Codex chats discover and preserve the same handoff.
- Reconstructed the Codex work in this conversation from the committed git history rather than relying on the chat's compressed context.

### 2026-07-25 — Reverse-direction SpanishDict protection

- Commits `16955dc`, `be52ef3`; front-end cache `flashcards-v75` / `20260725t`.
- Fixed `sea` being offered Spanish translations of the English noun *sea*. A legacy cache record had been fetched in the wrong dictionary direction while the corpus token was the Spanish conjugation of `ser`.
- Added a conservative conjugation-aware replacement in `build_menu_analyses()`: it requires a known non-self conjugation lemma, no usable matching lemma analysis, and a majority of Spanish-looking glosses before replacing the legacy self-headword with the cached lemma analysis.
- Added invalidation support and targeted rebuild behavior; corrected normal, Bad Bunny, Rosalía, Young Miko, and shared-master outputs.
- Verification: `pipeline/test_util_5c_guard.py` covers 22 cases, including `sea → ser`, while retaining valid homographs `vino → wine` and `baila → spotted sea bass`.

### 2026-07-25 — Front-card morphology and pooled examples

- Commits `51f77bd`, `cae174c`; caches advanced through the v73/v74 sequence.
- Made morphology consistently English and reordered labels so person/number leads the grammatical mood/tense detail.
- In Merge Lemmas mode, examples pooled from sibling forms highlight the form actually present in the lyric rather than only the host card surface.

### 2026-07-25 — Stable levels, sets, and progress

- Commits `9a011a7`, `94bdeaa`, `def2f94`, `5b3f96d`, `21768e7`, `f3cb882`.
- Unified setup and in-study controls, made frequency levels finishable, introduced stable discrete study sets, and added partial-level progress indicators.
- Set boundaries remain stable across Merge Lemmas/Cognates filtering so preference changes do not move cards into a different numbered set.

### 2026-07-25 — Card-back metadata cleanup

- Commit `4588ac4`.
- Removed rank and occurrence metadata from the back and suppressed trivial plural/elision surface-form notes, retaining non-obvious canonical-form information.

### 2026-07-24 — Card grammar and sense/example presentation

- Commits `0143c2f`, `1351d42`, `2649ab2`, `5bd7093`, `0658c92`, `270b69c`, `3902737`, `2920fc3`, `5cb5632`, `0cfe7ff`, `5f7eaf0`, `80cd9cb`.
- Added the active setup-step pulse, highlighted “used with X” context terms, grouped senses by POS, visually linked assigned senses to examples, then refined the layout into the current POS-linked grammar system.
- Removed redundant matched/matched-sentence and Expressions/Clitics pills during the refinements; split multi-POS front pills and tied morphology styling to VERB.

### 2026-07-24 — Language/setup presentation

- Commits `3f2a6e9`, `34cf23f`, `4a9bf8e`, `29bbc61`, `c92d0f0`, `bcbe509`, `bdfa03b`, `cd040cf`.
- Renamed Collapse Lemmas to Merge Lemmas, shortened Cognates labels, brightened active-study progress, preserved Lemma/Cognates help in artist mode, reused the radial picker for normal-mode languages, and folded standard progress into the language step.

### 2026-07-24 — Lemma pooling and frequency design

- Commits `1196e94`, `e4364aa`, `44e4d3f`, `cf59df5`.
- Audited and fixed lemma sibling pooling so card-front corpus frequency uses the same pooled basis as examples.
- Reworked smart frequency partitioning after the pooling fix to improve useful resolution in the artist long tail.

### 2026-07-24 — Artist corpus and deck rebuild

- Commits `7c63853`, `8b5df27`, `26a7c32`, `1d710a5`, `56f6a27`, `b32e34e`, `6147581`.
- Excluded exact repeated lyric lines from corpus counts, backfilled missing verb conjugation tables, rebuilt the three Spanish artist decks/shared master, and reconciled the Spotify desktop-confirmation backlog item.

### 2026-07-24 — Backlog capture and reconciliation

- Commits `edb9b38`, `f648ba3`, `360d9d7`, `dc0c3a9`.
- Captured the Notes-app backlog and judgment-dependent dependencies in `TODO.md`, then reconciled the smaller completed items against the implemented state.
