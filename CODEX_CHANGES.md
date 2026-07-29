# Codex changes and cross-model handoff

This file tells Claude and future Codex sessions what Codex changed, why, and how it was checked. Git remains authoritative for exact diffs; `config/dev_changelog.json` remains the in-app user-visible history; `TODO.md` remains the backlog.

Maintenance rule: after each completed Codex task, prepend a dated entry to **Codex task history** after the commit exists. Include the final commit hash, user-visible result, non-obvious decisions, verification, and cache version for front-end work. Do not silently rewrite an earlier decision—add a newer entry explaining the change.

## Current architectural decisions from the Codex work

- Study decks use finishable frequency levels and stable, discrete study sets. Set identity is rank-based so changing Merge Lemmas or Cognates does not reshuffle the underlying set boundaries.
- Lyrics vocabulary has exactly two lemma-family scopes: Main for more than one distinct lyric line and Artist Extra for one. Extra is a learnable corpus scope, not a readiness quarantine; unclassified lyrics remain visible without pretending they match a sense.
- The normal setup and active-study flow share radial pickers and a discrete progress rail. Partial level progress is visible, and study sets are intended to feel independently completable.
- Merge Lemmas is the user-facing name. It is off by default; Exclude Cognates is off by default.
- Artist corpus frequency excludes exact repeated lyric lines within each song. Lemma-mode card frequency and examples use the same pooled sibling basis.
- Artist rank ties use each word's full distinct-song spread, not the capped example sample. Artist lyric examples prefer an explicitly credited active artist, Spotify availability, and a standard release in that order before the teaching signals.
- Desktop lyric autoplay is line-bounded and card-wide: it announces each sense/sub-sense/Expression with distinguishing context, plays that item's eligible examples, and skips unplayable lines without changing full-list counters. It remains unavailable on mobile where Spotify handoff timers cannot guarantee the stop boundary.
- Card grammar uses separate POS pills, English morphology labels, POS-linked colour, pooled-form highlighting, and a grouped/linked card-back layout. Trivial plural and elision form metadata is suppressed on the back.
- SpanishDict sense menus for normal and artist modes share `pipeline/util_5c_spanishdict.py`; reverse-direction conjugation collisions such as `sea` are guarded there rather than patched only in a final deck.
- Audit flags separate the target (pairing, meaning, example, lemma, word form, card, or note only) from the problem category. They default to the visible sense–example pairing and store structured evidence through the existing FlaggedWords backend contract.
- Artist expressions remain rows on word/lemma cards. Curated and morphology-backed construction templates pool deterministic unique-line evidence, require their semantic complement, and preserve exact lyric surfaces.
- Per-sense, Expression, and clitic knowledge is a sparse override layer on whole-card progress. The newest parent/item timestamp wins, and level review synthesizes focused word cards rather than creating a second permanent card taxonomy. Standard and artist decks now ship stable sense IDs, preserving aliases and legacy content-derived progress during migration.
- Progress-fill colours are semantic across every language and artist: green means Known/current, amber means Review/due, and neutral means Unseen. Source identity remains in surrounding accents and selection borders rather than competing with progress meaning.
- Spaced repetition is an optional, device-persistent Study setting and defaults Off while the app is under development. When enabled it is level-scoped, with transparent 1, 3, 7, 14, 30, 60, and 120-day intervals. Pausing suppresses time-based due status without erasing stages/timestamps; explicit mistakes and partial cards always remain in Review.
- Level estimation is a 30-item receptive check over the normal Speech frequency list. It samples the full distribution before adapting around the uncertain boundary, reports a range, and persists the curve's point estimate through the existing single-rank contract. It is deliberately not labelled as productive ability or calibrated IRT.
- A card's stable `targetWord` identity is separate from `displaySurface`, `citationForm`, and `productionAnswer`. Spanish→English uses the first two and labels pronominal lemmas in plain language. English→Spanish uses the production answer: exact surface when unmerged, lemma when merged, and the complete `-se` citation for older pronominal data, with the evidenced example form shown separately.
- Regular plural dictionary twins share their explicit singular lemma identity while preserving every source sense ID. Derivational families such as `besito` → `beso` remain separate cards/progress records and use a conservative, auditable relation layer rather than suffix-only collapsing.
- Card reporting has one owner-facing route: both visible report controls open the structured audit sheet directly; the obsolete metadata/field-flag sheet is retired.
- Artist clitic rows consume split-example `c` buckets in single- and multi-artist decks. They teach the exact attached form as an infinitive, gerund, or affirmative command plus the clitic's person/case and English role, rather than presenting only the base infinitive gloss.
- Boot, source navigation, exact resume, and deck replacement share one app-level loading surface. It covers partial auth/setup/card DOM until the destination is coherent; it does not justify artificial waiting, and cached progress should remain usable while remote Sheets reconciliation runs in the background.
- Source setup keeps parsed indexes by data path and shares one source/settings/examples-keyed filtered vocabulary across level, progress, exclusion, and set UI. Artist frequency extraction must use that same canonical loader rather than parsing the index independently.
- Google Sheets schema v4 has one discriminated `Progress` tab for word, sense, MWE, clitic, and metadata rows, plus the separate `FlaggedWords` tab. Speech/Lyrics are a `Mode`, item rows use `ParentWordId`, and artist-specific routing metadata carries a `Source`; the automatic migration retains the old three progress tabs as `*_legacy` backups and accepts cached v3 clients during rollout.
- A marked-done level is a scoped, reversible suggestion-routing override only. It is keyed by mode + language + artist source, skips auto/estimate/resume/advance suggestions, never synthesizes card knowledge, and never prevents explicitly opening the level.

## Codex task history

### 2026-07-29 — Replace morphology circles with a feature strip

- Commit `ae97a5ff`; front-end cache `flashcards-v145` / `20260729q`.
- Replaced the cramped four-circle matrix with up to three shallow independent tokens: combined person+number (`1SG`, `3PL`), tense (`PRES`, `PRET`, `IMPF`, etc.), and mood/form (`IND`, `SUBJ`, `INF`, etc.). Irrelevant empty categories are omitted.
- Ambiguity is now expressed inside the affected category. The common `sea`-style first/third singular ambiguity renders as `1/3SG · PRES · SUBJ` rather than selecting one analysis and showing a vague count. If tense or mood differs, that token carries its own slash alternatives; the tooltip/accessibility label preserves the exact full analyses.
- The back header reserves one shallow row above the word for the strip, preventing overlap without constraining the headword horizontally.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; removal assertions for the old grid/count classes; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Load the next level without rebuilding the current one

- Commit `3345ba9c`; front-end cache `flashcards-v144` / `20260729p`.
- Follow-up after the awaited-setup fix still failed when the learner jumped to a final physical set while earlier sets in that level were unfinished. Removed the regular next-level path's setup detour entirely: it now selects the next level in the existing selector DOM, awaits that level's own range promise, and loads its first available set directly.
- Passed the next level number into the new deck metadata and made missing level/render/set state explicit errors. The completion screen is restored with a retry message if continuation cannot resolve instead of silently stalling.
- Artist Main→Extra still uses the necessary setup/scope transition because it changes vocabulary sources rather than merely changing a level.
- Verification: bundled-Node syntax checks for `ui.js`, `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; regular-path assertion showing no setup detour; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Reveal the direction choice inline on the card

- Commit `6060d4d1`; supersedes the intermediate radial implementation in `c9ec6324`; front-end cache `flashcards-v143` / `20260729o`.
- Holding the back headword now reveals one compact, explicitly labelled direction button directly beneath the word. It does not open the general Study options picker or any dedicated overlay/radial UI.
- The card reverses only when the revealed button is selected. Existing movement cancellation, haptic acknowledgement, focus placement, and synthetic-click suppression remain intact.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; absence of the discarded direction radial; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Fix next-level continuation and tab multi-POS cards

- Commit `113c8a88`; front-end cache `flashcards-v141` / `20260729m`.
- Fixed the end-of-level continuation race by awaiting the completed level's setup-range rebuild before selecting and rendering the next level. Previously the old and new asynchronous renders could overwrite the same set panel, leaving no first-set target while the completion action appeared stalled.
- Multi-POS card backs now turn their POS badges into tabs and render only the active grammatical section. Selecting a tab focuses its first sense without invoking sense-cycle behavior; single-POS cards retain the existing informational badge.
- Expressions and clitics remain pinned below the tabbed grammatical section, and selecting them preserves the active POS tab. POS selection follows direct sense and knowledge-item navigation as well.
- Verification: bundled-Node syntax checks for `flashcards.js`, `ui.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; POS-tab handler/static routing assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Require an explicit direction choice after holding

- Commit `996e1ffc`; front-end cache `flashcards-v140` / `20260729l`.
- Corrected the back-headword long press so it opens the existing Study options picker rather than reversing immediately. The user must then select the dynamically labelled target→English or English→target action.
- Retained the 600ms threshold, movement cancellation, haptic acknowledgement where supported, and synthetic-click suppression.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Lighten morphology and add hold-to-reverse

- Commit `afbd255d`; front-end cache `flashcards-v139` / `20260729k`.
- Removed the morphology grid's enclosing panel, shadow, and padding. Its four independent circles now use a tighter 32px 2×2 arrangement, with correspondingly reduced back-header reservation.
- Made the back-word flip target visually invisible in hover and active states. A 600ms hold directly on the headword now reverses study direction, provides supported-device haptic acknowledgement, suppresses the resulting synthetic click, and cancels after 10px of pointer movement so swipes do not trigger it.
- POS tabs were deliberately not introduced in this styling/gesture task. Recommended follow-up behavior is to render tabs only for genuinely multi-POS cards, keeping single-POS cards unchanged and preserving a separate all-items route.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Compact morphology into a fixed card-header badge

- Commit `f972c954`; front-end cache `flashcards-v138` / `20260729j`.
- Replaced the vertically expanding morphology pills with a fixed 2×2 circular badge for person, number, tense, and mood/form in the top-right of both card faces. Every token now uses the same restrained tense/mood text colour.
- Ambiguous forms preserve the fixed footprint by showing the first active analysis plus a `+N` count; the full set remains available through the badge's accessible label and tooltip. Merged-lemma cards derive the badge from the active example, so it changes with the example selection.
- Long front prompts now remain on one line and shrink from their normal display size down to 18px on mobile or 22px on desktop rather than wrapping. The back keeps its existing conservative sizing, with header space reserved around the new badge.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Clarify grouped-sense selection hierarchy

- Commit `716c5d5a`; front-end cache `flashcards-v137` / `20260729i`.
- Made the primary selection treatment symmetrical: selected meanings and their paired examples now use matching left/right POS-coloured rails and balanced gradients.
- Removed the redundant inner highlight and inset marker from a whole-family group selection. The outer grouped row alone communicates that the combined family is active.
- When one member inside a family is explicitly selected, the outer row retains the primary family context and only that member receives the smaller symmetrical secondary marker. Ordinary single meanings retain one primary selection state.
- Verification: bundled-Node syntax checks, valid changelog JSON, cache-version lockstep, static assertions for the three symmetrical rail widths and absence of the shared group marker, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Add POS flags and keep search visible until cards render

- Commit `f68f95df`; front-end cache `flashcards-v136` / `20260729h`.
- Added Wrong card POS to the main specific-problem grid. Each row in the sense–meaning view now has separate Flag this pairing and Wrong POS actions; sense POS reports carry the current POS, gloss, stable sense ID, context, and assignment method.
- Hardened the still-inert Find word route again: it now keeps the result sheet visible until temporary-card rendering completes and calls the exported example/form, ID, link, layout, initialization, and rendering helpers explicitly. A genuine exception reopens/retains search with “Could not open card,” rather than hiding the sheet and looking like a dead click.
- Both POS actions use the simplified reporter's confirmation-and-stay-open behavior. The visual layout retains a balanced two-column specific-action grid and paired per-sense actions.
- Verification: bundled-Node syntax checks for every affected module, valid changelog JSON, unique static HTML IDs, explicit temporary-card helper assertions, eager/lazy/service-worker version lockstep, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Replace the audit matrix with one predictable flag sheet

- Commit `0d591dea`; front-end cache `flashcards-v135` / `20260729g`.
- Replaced the rendered target/category/preview matrix with one calm hierarchy: an independent free-form note composer, explicit Proper noun / English / Cognate / Wrong lemma / Wrong elision correction actions, a dedicated sense–meaning pairing view, and one full-width Flag whole card action.
- Notes require only text and the explicit Send note button. Enter remains ordinary multiline input; no target or category selection is involved, and the current card ID is included only as retrieval context.
- Every accepted flag now produces a visible success confirmation. Notes, classifications, lemma/elision issues, and sense pairings keep the sheet open for further reports; a whole-card report confirms and closes after a 1.1-second visible pause. Reports no longer advance the study deck.
- Made `flagWord()` await queue acceptance and report whether a flag was accepted, allowing signed-out/guest failures to remain visible instead of falsely confirming.
- Verification: bundled-Node syntax checks for every affected module, valid changelog JSON, unique static HTML IDs, removal assertions for legacy rendered controls, cache-version lockstep, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Make Find word temporary-card navigation deterministic

- Commit `c432f3d2`; front-end cache `flashcards-v134` / `20260729f`.
- Follow-up after a refreshed client proved that cache-version lockstep alone did not restore Find word. Search results now retain the exact full joined vocabulary entry used to render them, so opening a card cannot fail because another setup operation repointed the legacy global index cache.
- Promoted `flashcards-modals.js`, which owns temporary cards, to an eager primary-navigation dependency and preloaded it with the other boot modules. The first result click no longer doubles as a dynamic module-loading attempt.
- Missing source entries now throw into the existing visible “Could not open card” handler instead of warning and returning silently.
- Verification: bundled-Node syntax checks for all affected modules, valid changelog JSON, eager/lazy/service-worker asset versions in lockstep, exact-source routing assertions, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Restore temporary cards opened from search

- Commit `16dad7cc`; front-end cache `flashcards-v133` / `20260729e`.
- Fixed Find word and other temporary-card routes loading `flashcards-modals.js` through the obsolete `20260728g` cache URL while the main app had advanced. Lazy modal and conjugation imports now share the service worker's current asset version, preventing a stale implementation from silently owning search-result clicks.
- Lazy import errors are rethrown to the existing Find word handler, so a genuine load failure now shows “Could not open card” instead of only logging and appearing inert.
- Confirmed Rosalía `por` (`a67298`) remains searchable and has 133 corpus occurrences plus lyric evidence. It correctly opens as an examples-only temporary view because the current artist entry has no assigned translated sense.
- Verification: bundled-Node syntax checks for the eager, modal, and worker modules; valid changelog JSON; all eager and lazy asset versions in lockstep; real Rosalía `por` data assertion; and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Refine the numbered card scrubber

- Commit `01eaa2ef`; front-end cache `flashcards-v132` / `20260729d`.
- Turned the bare card numbers into circular position markers contained in a dedicated 42px strip above the card on desktop and mobile. The current position is largest; the nearest three positions on either side progressively shrink and fade, while distant markers disappear into the scrubber's masked edges.
- Reversed the earlier labelled-control decision: Study options is now a larger 44px circular icon-only button at every breakpoint, as requested.
- Verification: bundled-Node syntax check, valid changelog JSON, cache-version lockstep, removed-label assertion, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Replace the active-set progress rail with a card scrubber

- Commit `99e86429`; front-end cache `flashcards-v131` / `20260729c`.
- Replaced the thin discrete progress cells with a horizontally swipeable, numbered card-position scrubber modelled on the main-menu level picker. The current card is magnified, visited positions remain legible, and choosing a number jumps directly to that card.
- Removed the separate rail arrows and desktop gutter chevrons. Swipe gestures and keyboard navigation remain available, while Study options uses the freed width for a larger labelled desktop control and a 42px mobile control.
- Updated the in-app study help and developer changelog. Verification: bundled-Node syntax checks, valid changelog JSON, cache-version lockstep, stale navigation-hook scan, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — [Claude, cross-boundary] Sense-provenance card panel + deck fields

- **Author: Claude (engine side), touching the app surface by explicit user request** — this is a diagnostic UI whose purpose is to expose pipeline provenance, so it was built alongside the engine work rather than handed off. Recorded here so future Codex sessions know Claude edited `js/`, `css/`, `index.html`, and `dev_changelog.json`.
- Commit `pending`; front-end cache bumped `20260728g` → `20260729a` (all `?v=` tags in `index.html` + `js/main.js`).
- Engine: new `config/prompt_registry.json`; assignments now carry `prompt_id`/`run_ts` (backfilled 242,289 items via `pipeline/tool_6a_backfill_provenance.py`; `step_6c` stamps future runs). `step_8b` emits per-sense `sense_prompt_ids`/`sense_run_ts` in the artist index, keyed by stable sense_id. Full design + coverage caveats in `docs/design/sense_provenance.md`.
- Front-end: `config.js` loads the registry into `window._promptRegistry`; `vocab.js` `joinWithMaster()` + the `buildFilteredVocab()` meaning rebuild + `mergeArtistVocabularies()` carry `prompt_id`/`run_ts` through (parallel to the existing `assignment_method` plumbing); `flashcards.js` adds a JST-gated `ⓘ` provenance button + panel on the card back (`buildProvenancePanelHTML`/`toggleProvenancePanel`), styled in `css/style.css` (`.provenance-panel`).
- Deliberately did NOT change `resolve_best_per_example` winner selection (still method-priority) — the tier-based re-rank is a separate deferred task. Verified: all 3 Spanish artist decks rebuild clean and ship provenance (Bad Bunny 2001 stamped senses, Young Miko 190, Rosalía 78); no `_sense_provenance` internal field leaks into the shipped index/examples.
- Not verified in a live browser (per repo policy Claude doesn't run previews); JS not run through Node (unavailable) — Codex/Josh should sanity-check the panel renders.

### 2026-07-28 — Remove phantom sets and make note submission explicit

- Commit `e8fa8e6d`; front-end cache `flashcards-v129` / `20260728g`.
- Reproduced the set discrepancy against JST's live schema-v4 progress and the current Bad Bunny deck. `tequi` is a genuinely unseen/buildable level-11 card, while level-12 entries such as `señores` and `relaciones` had corpus counts above one but no artist sense at the renderer's 0.05 support threshold: setup counted them and deck construction later discarded them. `buildFilteredVocab()` now applies the same shared threshold, so these phantom cards never enter set counts.
- Added a race-safe fallback for the other empty-set path: if Sheets reconciliation makes every advertised new card seen between setup render and the tap, the selected range opens using the existing Study Again behavior rather than throwing “No unseen flashcards remain.”
- Simplified notes into one inline interaction. Tapping “Add a note” expands the textarea immediately below it; only the separate enabled “Send note” button submits. The initial tap and ordinary Enter key can no longer send a report.
- Changed service-worker navigations to network-first while retaining stale-while-revalidate for versioned modules and deck data. The previous cached-shell policy deliberately delayed every deployment by one page load, which explained why both earlier fixes could remain invisible together; future online opens receive current module tags immediately while offline shell fallback remains.
- Verification: live Apps Script progress/item reads, current Bad Bunny level-11/12 fixture assertions, first-tap-no-submit and explicit-send assertions, bundled-Node parsing, unique DOM IDs, balanced CSS, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-28 — Mobile-first card reporting and direct notes

- Commit `d3b3a844`; front-end cache `flashcards-v128` / `20260728f`.
- Gave the mobile audit bottom sheet a definite visual-viewport height, safe-area padding, momentum/touch scrolling, and an independently fixed footer. This removes the ambiguous clipped state where lower report controls existed but could not reliably be reached on a phone.
- “Send a note” now opens a focused note-only composer rather than selecting an option beside an already-visible textarea. The mobile keyboard's Send/Enter action submits the note immediately; Shift+Enter preserves multiline input, the visible Send button remains an accessible fallback, and a back action returns to structured report choices.
- Detailed reports retain free text through a collapsed “Add details” disclosure, so the capability remains available without consuming the main sheet's limited height.
- Verification: bundled-Node parsing, unique DOM-ID parsing, balanced CSS-block assertion, focused-note/keyboard-send/mobile-scroll static regressions, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-28 — Keep setup set counts synchronized

- Commit `417175a6`; front-end cache `flashcards-v127` / `20260728e`.
- Replaced progress refresh's row-count-only change test with a comparison of the actual UI-driving card, granular-item, level-estimate, and marked-level state. Existing rows changing from unseen/review to known now trigger the same setup re-render as newly added rows.
- Applied the rule to both schema-v4 `Progress` loading and the legacy fallback. This fixes stale “Learn 1 new card” actions that were rejected as already complete when deck construction consulted the newer in-memory state; no progress records or Apps Script schema changed.
- Verification: bundled-Node syntax checks, a same-row-count status-transition regression assertion, unchanged-state assertion, valid changelog JSON, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-28 — Make the About page demonstrate its argument

- Commit `780eb56f`; front-end cache `flashcards-v126` / `20260728d`.
- Removed the unsupported public product name from the About copy and restored the intended narrative order: the limitation of themed word lists first, then this app's frequency- and context-based response.
- Explained why *aunque* matters as a small linking word and what the app does differently: its three uses are kept separate and shown with the sentence that calls for each meaning.
- Reduced each animated demo to the word discussed beside it. Speech now starts and remains on the real `aunque` card (rank 429, 229/million, ≈50% even though / 30% although / 20% even if); Lyrics starts and remains on `fuego` (≈70% fire / 20% light / 10% passion). Every demonstrated meaning now carries its percentage instead of making a visitor wait through unrelated cards.
- Verification: bundled-Node parsing, exact one-card-per-mode/word/percentage-total assertions, live Spanish-index rank/frequency/meaning-total checks, absence of the repo name in About copy, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-28 — Consolidate progress storage and streamline level completion

- Commit `24149b26`; front-end cache `flashcards-v125` / `20260728c`.
- Replaced the three progress tabs with schema-v4 `Progress` rows discriminated by item type and mode. Metadata rows retain level estimates and add artist/language/mode-scoped level-routing flags; `FlaggedWords` remains independent. The guarded first POST migrates and deduplicates old rows, renames source tabs `*_legacy`, recovers from a stray pre-v4 `Progress` tab, and keeps old cached action/sheet names compatible during deployment.
- Added a reversible “Skip this level in suggestions” control below the set picker. Setup auto-pick, estimated placement, resume prompting, next-set routing, and cross-level completion skip it; explicit selection still works and all true card/item answers continue unchanged.
- Compact morphology groups shared tense/mood analyses such as “1st/3rd singular · present subjunctive.” The end-of-set modal now owns keyboard interaction and advances to the next genuinely unfinished set/level even when later physical dots were completed earlier.
- Updated the pull/push tools for the unified schema, including exact typed-row deletion, and added a dependency-free in-memory Apps Script migration/round-trip regression test. Verification: all changed JS parsed with bundled Node, Python tools compiled, migration/legacy compatibility/word-item-meta CRUD/artist isolation/idempotence tests passed, morphology and scope-isolation assertions passed, JSON/cache lockstep and `git diff --check` passed. No browser preview was used.
- Deployment note: copy `backend/GoogleAppsScript.js` into Apps Script and publish a new version. The app probes capabilities and safely keeps using the legacy route until v4 is live; the first v4 progress request performs the migration.

### 2026-07-28 — Tighten the employer-facing About page

- Commit `80f07792`; front-end cache `flashcards-v124` / `20260728b`.
- Added one plain-language product sentence, replaced the arbitrary *mañana* example with *aunque* as an often-overlooked connecting word, and removed jargon from the explanation of ranking and meaning selection.
- Corrected the claim that the Lyrics deck contains every word in a complete discography and separated subtitle frequency, example, and dictionary source roles. The technical section remains brief rather than becoming a longer portfolio essay.
- Replaced the invented *fuego* demo copy with genuine catalogue lines, exposed its complete indicative split (fire ≈70%, light ≈20%, passion ≈10%), updated current ranks/counts and labels, and moved part of speech into the same single legend used by live cards.
- Verification: JavaScriptCore module parsing, valid changelog JSON, cache-version lockstep, percentage-total/data assertions, and `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-28 — Streamline audit notes and classification tags

- Commit `4b28d948`; front-end cache `flashcards-v123` / `20260728a`.
- Promoted the most frequent owner audit actions into a Quick report area: Write a note, English, Loanword, and Cognate. Classification choices retain their current pipeline stamps in the card model and include those values in the structured FlaggedWords report.
- Write a note is now an explicit entry mode: it focuses and scrolls to a required textarea, keeps Enter available for normal multiline writing, and disables the final Send note action until non-whitespace text exists. Selecting the action itself cannot submit a blank report.
- The detailed sense/example/lemma/form/card categories remain available, and routing tags use distinct stable paths such as `routing:cognate`. The existing FlaggedWords payload contract is unchanged, so no Apps Script redeployment is required.
- Verification: bundled-Node syntax checks for changed modules, valid changelog JSON, unique HTML IDs, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Make merged-lemma cards follow their examples

- Commit `1987dfd1`; front-end cache `flashcards-v122` / `20260727q`.
- Merged cards remain one stable lemma-owned rank/progress record, but Spanish→English now presents the exact surface carried by the current pooled example. The citation lemma remains directly underneath on both faces when it differs.
- Pooled sibling examples retain their source entry's morphology. The front and back grammar display follows that form, and the existing conjugated-English table supplies a matching gloss only for a single unambiguous supported analysis. Ambiguous forms such as `da` retain all visual analyses without guessing an English conjugation.
- English→Spanish continues to ask for the shared lemma and uses the existing “In this example” cue for its surface form. An in-session per-card cursor advances the starting example when a merged card is revisited.
- Verification: bundled-Node syntax checks, valid changelog JSON, cache-version lockstep, real `dar` family morphology and `dieron`→“they gave” data assertions, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Emphasize the selected study set

- Commit `e5a2d872`; front-end cache `flashcards-v121` / `20260727p`.
- Replaced the selected set number's subtle outline with a bright layered accent ring and a gentle lift, bounce, and halo pulse, while leaving its wrong/review/known/unseen segmented fill unobscured.
- Added an equally clear static treatment for learners who request reduced motion.
- Verification: valid changelog JSON, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Speed source setup and refine study controls

- Commit `73f6741c`; front-end cache `flashcards-v120` / `20260727o`.
- Removed the largest repeated Lyrics setup work: artist frequency extraction now reuses the canonical parsed/joined index, parsed source indexes are retained by path, and the slider, level-progress annotation, exclusion summary, and set picker share one prepared filter pass until source/settings/examples change. Deck construction invalidates the prepared view before mutating entries.
- Replaced Speech's compact pill cluster with the same structured source-card language used in Lyrics: selected language with a direct language picker, an explicit “Switch to Lyrics” action, and progress underneath.
- Tapping an already-selected numbered set starts it, while the existing full-width start button remains. Expression and attached-form rows now centre the Spanish form above the English explanation instead of pulling the two languages to opposite edges.
- Study options now say Main menu, explicit `English → Spanish`/`Spanish → English`, and Mute/Enable automatic speech; Study preferences opens the Study tab and the redundant in-deck Help item is gone.
- Autoplay is rendered and activated only when the card contains at least one timestamp-bounded, mapped Spotify example; sense announcements alone cannot create an empty autoplay run.
- Verification: bundled-Node syntax checks for all changed modules, unique static HTML IDs, valid changelog JSON, cache lockstep assertions, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Make app transitions coherent and faster

- Commit `8f29412e`; front-end cache `flashcards-v119` / `20260727n`.
- Added a single branded loading surface above authentication, setup, and active study. It now covers initial hydration, Lyrics↔Speech navigation, artist selection, exact-session resume, review loading, and set/level replacement, with contextual rather than generic copy.
- Removed the loader's unconditional 800 ms post-build delay. Decks swap on the next animation frame, and the completion modal is covered before the old final card can reappear, making warm next-set transitions both faster and visually atomic.
- Exact resume now starts from synchronously restored local progress instead of waiting for the remote Google Sheets refresh. Sheets still reconcile in the background, but hidden setup controls are not expensively rebuilt underneath an active resumed deck.
- Artist and Speech setup now await their asynchronous level/exclusion work before revealing the screen. A 12-second fail-open guard and `finally` cleanup prevent an initialization or data error from trapping the learner behind the loading surface.
- Verification: bundled-Node syntax checks for every changed JavaScript/service-worker file, valid changelog JSON, one-value cache/version scan, removed-delay assertion, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Repair clitic cards and reporting flow

- Commit `c0ade7a3`; front-end cache `flashcards-v118` / `20260727m`.
- Removed the obsolete metadata-and-inline-flag modal. The desktop shortcut and card-back flag icon now open the modern target/category/note audit sheet directly, leaving one reporting flow.
- Fixed the single-artist loader's missing `c`-bucket attachment and taught multi-artist merging to combine, artist-tag, dedupe, and re-emit clitic examples. The current artist decks contain aligned real lyric evidence for all 905 shipped clitic forms; fake blank examples are no longer synthesized.
- Clitic rows now distinguish infinitive, gerund, and affirmative-command forms, show the attached pronoun's person/case and English role, speak that distinction during autoplay, and highlight the complete attached form in its lyric. Examples include `darte` (“to give · you/yourself”), `dándole` (gerund + indirect object), and `hazme` (command + first-person object).
- Added a conservative live-deck guard for stale self-infinitive duplicates: `quité|quité` is suppressed only because a same-surface authoritative `quité|quitar` conjugation exists; the correct card retains “1st singular · preterite” and its conjugated English gloss.
- Verification: bundled-Node syntax checks, representative clitic grammar assertions, exhaustive parsing of all 905 live forms, 905/905 split-example alignment across three artists, a synthetic two-artist clitic merge, live `quité` rejection/retention, unique HTML IDs, valid changelog JSON, cache lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Normalize plural lemmas and link diminutives

- Commit `a116d533`; front-end cache `flashcards-v117` / `20260727l`.
- SpanishDict analysis twins such as `besitos|besitos` and `besitos|besito` now assemble under the singular lemma key while retaining the original sense identities. The rule requires both dictionary analyses and compatible nominal/adjectival parts of speech, so it does not blindly strip plural-looking verb forms.
- Added a shared, reviewable derivational-relation layer. Diminutives and superlatives stay independent cards, but supported entries can label their base lemma in quiet card-back text; curated overrides handle orthographic changes such as `placita` → `plaza`, and risky suffix lookalikes remain excludable.
- The relation builder currently records 89 evidence-backed or curated relations. A validation rebuild proved the plural merge in real Bad Bunny data, but its broad unrelated output drift was deliberately restored; the live deck files should receive this metadata in Claude's next coordinated assembly. No Gemini rerun is required.
- Verification: 11 focused Python tests, Python compilation, bundled-Node syntax checks, valid JSON, real-data `besitos` routing, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Complete English-to-Spanish card forms

- Commit `5bee518b`; front-end cache `flashcards-v116` / `20260727k`.
- Unmerged cards now reveal and speak the encountered surface form, while Merge Lemmas cards reveal and speak the shared citation lemma. Merged prompts retain infinitival English rather than inheriting the representative host form's conjugated gloss.
- Pronominal cards whose old deck data lacks explicit production morphology safely use the complete `-se` citation (`quejarse`) and label an exact form found in the active example (`se queja`). Expressions and attached forms use their own active answer and translation rather than falling back to the parent word.
- Verification: JavaScript syntax, direct form-contract assertions for unmerged `está`, merged `estar`, and pronominal `quejarse`, valid changelog JSON, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Lemma-first merged cards

- Commit `e340a4d4`; front-end cache `flashcards-v115` / `20260727j`.
- Merge Lemmas cards now present and speak the citation lemma instead of exposing whichever high-frequency surface entry hosts the family: `está|estar` displays as `estar`, while the host remains `está` internally.
- Kept `targetWord` and new `representativeSurface` separate from `displaySurface`, preserving stable progress IDs, levels, ranks, pooled frequency, links, and exact host/sibling example highlighting.
- Suppressed representative-form morphology when it would misdescribe the displayed lemma, and used the lemma/production answer on the reverse-direction card back as well. Search previews remain surface-specific because they do not opt into merged presentation.
- Verification: JavaScript syntax, direct normal/merged `está|estar` form-contract cases, merged `queja|quejarse` pronominal case, cache-version lockstep, valid changelog JSON, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Compact merged-lemma knowledge inventory

- Commit `2b9ec48f`; front-end cache `flashcards-v114` / `20260727i`.
- Large Merge Lemmas cards now keep only the active meaning, Expression, or attached form in the ordinary card flow once their learnable inventory exceeds four items. Small and unmerged cards retain the full inline menu.
- Removed the persistent per-item Know/Review strip. A bottom knowledge-map icon carries the explicit known/total count and opens a responsive, scrollable inventory grouped into Meanings, Expressions, and Attached forms; each row can be focused on the card or independently marked Known/Review.
- Focusing an Expression/clitic preserves its exact cycle index, while focusing a grouped sense remains pinned to that sub-sense instead of immediately reverting to the overarching group.
- Verification: JavaScript syntax checks, a synthetic sense/Expression identity and cycle-index case, actual Spanish inventory assertions (`decir` 11 items, merged `está` 4, non-representative `estemos` 11), valid changelog JSON, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Spanish card surface and citation forms

- Commit `557f65f0`; front-end cache `flashcards-v113` / `20260727h`.
- Added an app-side form adapter that separates the stable card/source word from the surface prompt, dictionary citation form, and future production answer. It consumes optional snake_case pipeline fields when available but needs no deck rebuild and falls back to the existing word/lemma pair.
- Spanish→English now displays the encountered surface as its prompt and puts a non-trivial citation form on a separate, quieter line. A verb such as `queja|quejarse` is explicitly described as “verb with se” without adding another pill; target-language TTS follows the displayed surface.
- Search, homograph-peek, ordinary, review, and legacy temporary cards all receive the same form contract. English→Spanish intentionally retains its old answer rendering until the next direction-specific slice can use `productionAnswer` deliberately.
- Verification: JavaScriptCore compilation of all changed modules, direct `queja|quejarse` and noun-homograph adapter cases, optional future-field compatibility, cache-version lockstep, valid changelog JSON, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Adaptive frequency-band level estimate

- Commit `ad8f67d1`; front-end cache `flashcards-v112` / `20260727g`.
- Replaced the reversal-sensitive one-rank staircase with a ten-band receptive estimator. It samples every frequency region, then allocates remaining questions around the inferred known/unknown boundary while avoiding duplicate lemmas.
- Band response rates are monotonically fitted and integrated into a vocabulary-size point estimate with an approximate 90% interval. Only the point estimate is saved, preserving the current Apps Script, progress, artist projection, and level-selection contracts; Lyrics still tests against the general Speech list.
- The learner now thinks of a meaning, reveals it, and only then reports whether it was known beforehand. The result is explicitly a receptive range rather than an exact rank or productive-language score.
- Verification: JavaScriptCore compilation, synthetic all-known/all-unknown/50%-boundary/contradictory-response cases, first-pass ten-band coverage and adaptive-boundary selection, valid changelog JSON, cache-version lockstep, and `git diff --check`. No browser preview was used.

### 2026-07-27 — Pausable spaced repetition

- Commit `457b14ca`; front-end cache `flashcards-v111` / `20260727f`.
- Study settings now exposes a persistent Spaced repetition Off/On control. It defaults Off where no choice has been saved, so unfinished app/content work does not turn the historical vocabulary into an immediate due backlog.
- Off suppresses only time-based `due` classification: correct cards render Known, while newer mistakes and partially completed sense/Expression cards remain in Review. Answer counts, timestamps, and SRS stages continue to be stored, so turning it back On resumes rather than resets the schedule.
- Verification: direct off/on/incorrect state cases, JavaScriptCore parsing, unique DOM IDs, cache-version lockstep, valid changelog JSON, and `git diff --check`. No service-worker browser preview was used.

### 2026-07-27 — Singular level-frequency wording

- Commit `e4fb3abb`; front-end cache `flashcards-v110` / `20260727e`.
- Follow-up to `895fec61`: a one-occurrence band now says “1 time in the lyrics” (or per million words), while all plural cutoffs retain “times.” Verified by JavaScriptCore parsing, cache lockstep, and `git diff --check`.

### 2026-07-27 — Audit-focused card flagging

- Commit `98d45281`; front-end cache `flashcards-v109` / `20260727d`.
- The flag dialog now exposes seven report targets: the visible sense–example match, meaning, example line, lemma, word form, whole card, or a note with no selected field. Problem category is a separate optional choice, so lemma and morphology reports no longer masquerade as pairing errors.
- The report sent through the unchanged `FlaggedWords` contract includes stable card/sense/Expression IDs plus relevant assignment methods, translation source, song/artist, Spotify/timing data, morphology, rank/frequency, and the learner's note. Note-only requires text and receives a unique path so unrelated observations do not overwrite one another.
- The dialog is a bounded, scrollable desktop sheet/mobile bottom sheet with explicit target cards, compact category chips, a contextual preview, and a fixed send action.
- Verification: JavaScriptCore parsing, seven-target/report-field assertions, unique DOM IDs, cache-version lockstep, valid changelog JSON, and `git diff --check`. No service-worker browser preview was used.

### 2026-07-27 — Explicit mobile Spotify Connect handoff

- Commit `127ea212`; front-end cache `flashcards-v108` / `20260727c`.
- Mobile playback now asks Spotify for available Connect devices, favours an unrestricted phone even if another desktop is active, transfers playback to an inactive phone, and sends play/pause commands with that device ID. A stale device triggers one fresh discovery before the existing Premium/no-device guidance appears.
- Spotify controls and the conjugation, synonym, dictionary, and card-info links now use larger, consistent tap targets and artwork.
- Verification: JavaScriptCore parsing, static discovery→transfer→targeted-play assertions, cache-version lockstep, and `git diff --check`. No service-worker browser preview was used.

### 2026-07-27 — Clearer level progression, resume, and Artist Extra unlock

- Commit `895fec61`; front-end cache `flashcards-v107` / `20260727b`.
- The level readout no longer repeats a card count above the slider. Its supporting sentence reports the level's filtered word count and corpus cutoff: “X words appear X times in the lyrics” in artist mode, with the equivalent per-million wording in Speech.
- Resume is now a one-time Welcome back decision when entering with an unfinished set, rather than a persistent setup-page card. Completing a deck clears that snapshot; dismissing the prompt only suppresses it for the current app session, and continuing still restores the exact card and settings.
- Artist Extra unlocks per artist when understood coverage in that artist's Main scope reaches 60%. The lock is durable once earned, blocked URL/resume paths cannot bypass it, and the disabled setup control explains the threshold.
- Verification: JavaScriptCore parsing of all changed modules, unique DOM IDs, cache-version lockstep, valid changelog JSON, and `git diff --check`. No service-worker browser preview was used.

### 2026-07-27 — Modern, persistent study settings

- Commit `063493d7`; front-end cache `flashcards-v106` / `20260727a`.
- The active-study clock retains all seven actions but replaces garish per-action colours and emoji fallbacks with one neutral line-icon system. The progress-rail ellipsis is now a conventional settings gear.
- The main modal now has Account, Study, Data, and Artists tabs. Freshness diagnostics, level-estimate clearing, and current-set reset live under Data; the modal is a bounded scroll surface on desktop and a bottom sheet on mobile.
- Target/English card direction and automatic speech join Merge Lemmas/Cognates as device-level defaults. In-study changes persist immediately, and exact resume snapshots also retain speech state.
- Verification: JavaScriptCore parsing of the changed modules, unique DOM IDs, cache-version lockstep, and `git diff --check`. No service-worker browser preview was used.

### 2026-07-26 — Level-scoped spaced repetition v1

- Commit `a546cd76`; front-end cache `flashcards-v105` / `20260726l`.
- Correct whole-card and granular sense/Expression recalls now advance through explicit 1, 3, 7, 14, 30, 60, and 120-day stages. A mistake resets that answer source to stage zero; legacy count-only rows receive a conservative derived starting stage.
- Due cards collect in the selected level's Review queue alongside incorrect and partial cards, ordered by the oldest review time. They remain Known for corpus coverage, while the set fill turns amber until reviewed; Learn new still contains only unseen cards.
- Apps Script schema v3 migrates existing tabs in place: `UserProgress`/`Lyrics` gain `SrsStage` and `LastSeen`, and `ItemProgress` gains `SrsStage`. The updated `backend/GoogleAppsScript.js` must be copied and deployed as a new version.
- Verification covered SRS transitions and stage caps, legacy migration, due/incorrect/partial aggregation, mocked Apps Script schema migration and card/item round trips, JavaScriptCore parsing, cache lockstep, and `git diff --check`. No service-worker browser preview was used.

### 2026-07-26 — Sense-aware, card-wide lyric autoplay

- Commit `e3d87c5b`; front-end cache `flashcards-v104` / `20260726k`.
- Collapsed rows now enter on their overarching grouped sense instead of silently selecting the first sub-sense. Explicit sub-row clicks still pin the narrower meaning.
- Autoplay creates an ordered card-wide queue across ordinary senses, sub-senses, Expressions, clitics, and remainder senses. It announces the conjugated English gloss plus context (for example “own, related to property”), plays that item's line-bounded Spotify clips, then advances to the next item without repeating the Spanish headword.
- Non-playable lyrics are skipped while counters remain tied to the full displayed example list (for example 6/8). A fallback control remains visible when the current item has no renderable sentence but another item on the card is playable.
- `speech.js` gained an optional completion callback with once-only end/error handling. Verification covered grouped defaults, card-wide ordering, current-unplayable/later-playable eligibility, exact single-button rendering across empty/filtered sentence paths, callback de-duplication, module parsing, cache lockstep, and `git diff --check`.

### 2026-07-26 — Partial cards remain reviewable until resolved

- Commit `324d48ec`; front-end cache `flashcards-v103` / `20260726j`.
- Knowing one item no longer makes the whole word appear Known. The card moves to level-scoped Review and its focused version contains both explicit mistakes and untouched sibling senses/Expressions, while already-known items are hidden.
- Explicitly knowing every learnable item promotes the parent card to Known, so setup/coverage can recognise completion without loading the deck schema. A later item mistake still reopens only that item, and a later whole-card correct still resolves all items.
- Renamed the queue from “Review mistakes” to “Review cards,” since a partial card can need attention without every unresolved sibling being an incorrect answer.
- Verification covered 1/3 and 3/3 completion, targeted reopening, whole-card reset, module parsing, cache lockstep, and `git diff --check`.

### 2026-07-26 — Stable sense identity and progress migration

- Commit `fcb431d1`; front-end cache `flashcards-v102` / `20260726i`.
- Standard assembly now retains every source-menu sense ID. Artist assembly carries IDs through ordinary meanings, unassigned sense cycles, and the shared master; equivalent collapsed rows retain alternate IDs in `sense_id_aliases`.
- All 26,001 learnable standard meanings and all 16,995 learnable artist-master senses have durable IDs. The 3,397 legacy artist senses without a current menu row receive reproducible `generated:artist-master:*` IDs; a later authoritative source ID supersedes a generated ID while preserving it as an alias.
- Existing `ItemProgress` is not abandoned: `knowledge.js` recognises old POS/gloss/context IDs and stable-ID aliases, uses the newest matching legacy row, and migrates its counts/timestamps to the canonical ID on the learner's next explicit answer.
- Rebuilds used only deterministic assembly (no Gemini). Verification covered six identity unit tests, JavaScriptCore parsing and compatibility cases, 100% learnable-sense ID coverage, and proof that the committed deck JSON differs from the previous output only by `sense_id`/`sense_id_aliases` fields.

### 2026-07-26 — Extra fills its categories; setup declutter (Claude front-end follow-up)

- Commit `53ffe425`; front-end cache `flashcards-v100` / `20260726g`. Authored by Claude; recorded here for the app-owner agent. Depends on pipeline commit `0b4d96fd` which stamped `extra_category` on `Artists/spanish/vocabulary_master.json` (live values: `single_occurrence`, `core`, `english`, `proper_noun`, `loanword`, `cognate`, `noise`).
- `joinWithMaster()` (vocab.js) now copies `extra_category` from the master onto each joined entry, so the Extra category selector actually receives it.
- Removed the always-visible Main-vs-Extra explainer paragraph (and its CSS) from the setup page; the Extra confirm modal is now the sole explanation. Kept the small "Vocabulary set" label and the confirm gate.
- In Extra scope only, `renderExtraCategorySelector()` hides `lemmaToggleContainer` and `cognateToggleContainer` (Merge Lemmas / Exclude Cognates are meaningless there). Main/normal mode still shows both.
- Filter policy: `buildFilteredVocab()` now KEEPS the over-tagged words in the EXTRA scope only — the `is_english`, noise, `is_english_loanword`, and proper-noun drops (and the cognate drop) are gated behind `artistVocabularyScope !== 'extra'`. Main scope is unchanged, so it stays clean; Extra retains these words and groups them by `extra_category`. Verified against the live Bad Bunny index: Extra scope (3,941 entries) now surfaces One-off words 2,720, English words 663, Names & places 260, Core words 107, Loanwords 90, Cognates 36, Interjections 26, plus ~39 still-untagged residual in "All Extra". These categories were previously empty because the words were dropped from both scopes.
- Added a `core` → "Core words" label to the map. Untagged entries still fall back to the single "All Extra" group; a mixed residual (some tagged, some not) lands in an "All Extra" bucket sorted last until the next assembly rebuild stamps the rest.
- Boundaries the app-owner may want to confirm: (1) scope membership is still frequency-based (`lemma_example_count <= 1`); this task only changed which flagged words survive the filter within Extra, not the Main/Extra split itself. (2) Merge Lemmas can still functionally apply in Extra if it was toggled on in Main (only the control is hidden); Exclude Cognates is now inert in Extra by the filter gate regardless of toggle state.
- Verification: JavaScriptCore module parse of `vocab.js`/`ui.js`/`main.js`; live-data simulation of the Extra grouping against `BadBunnyvocabulary.index.json` + `vocabulary_master.json`; cache-version lockstep (SW + every `?v=` tag). No service-worker browser preview (project policy).

### 2026-07-26 — Three-state study-set progress

- Commit `3fb24b2d`; front-end cache `flashcards-v99` / `20260726f`.
- Replaced the themed percentage-seen fill with fixed proportional segments for Known, Review, and Unseen. Exact counts now appear in the selected-set description and accessible set labels.
- Removed the unexplained numeric review badge and added a compact colour key. Artist/language theming remains on set borders and the selected focus ring, while progress colours keep one meaning everywhere.
- The amber state deliberately says Review rather than Wrong so the same visual model can later include successfully recalled cards that become due under spaced repetition.
- Verification: JavaScriptCore parsing, three-state percentage invariants, cache lockstep, stale badge/style searches, and `git diff --check` pass. No service-worker browser preview was used.

### 2026-07-26 — Extra explainer, confirm gate, and category grouping (Claude front-end task)

- Commit `9e7c0f0e`; front-end cache `flashcards-v98` / `20260726e`. Authored by Claude under an explicit front-end task; recorded here so the app-owner agent sees the change.
- Setup now states plainly that Main is the core recurring vocabulary and Extra is supplementary (one-off words, loanwords, names, slang) best after mostly finishing Main. The dynamic one-line scope hint is hidden in favour of the static two-part explainer.
- Extra is no longer a plain toggle: the Extra scope button opens `#extraScopeModal`, a modal matching the app aesthetic, with an explicit `Switch to Extra mode` confirm plus a `Stay on Main` cancel and backdrop/✕ dismissal. Main still switches directly. `openExtraScopeModal()`/`wireExtraScopeModal()` live in `main.js`.
- Extra replaces frequency levels with category groups read from a per-entry `extra_category` string. `buildFilteredVocab()` (vocab.js) stamps a contiguous, category-blocked `categoryRank` on each Extra entry and exposes ordered group metadata via `window.getExtraCategoryGroups()`. `renderExtraCategorySelector()` (ui.js) renders one chip per distinct value backed by a hidden `.level-btn` with `data-rank-basis="category"`, so the existing study-set paging, next-set/next-level, resume, and stats machinery work unchanged. `_levelRankAccessor`, `renderRangeSelector`, and `loadVocabularyData`'s slice all learned the `category` basis.
- Fallback: the category list is NOT hardcoded. Distinct present values are rendered with a label map (`loanword`→Loanwords, `english`→English words, `cognate`→Cognates, `proper_noun`→Names & places, `slang`→Slang & informal, `single_occurrence`→One-off words, plus a few more) and a title-cased default for unknown values. If NO entry carries `extra_category`, everything collapses into one `All Extra` group so nothing breaks before the pipeline populates the field.
- Boundaries assumed for the app-owner to double-check: (1) `extra_category` is read case-insensitively off the joined per-entry object (the same object `joinWithMaster`/`buildFilteredVocab` produce) — if the pipeline emits it under a nested key or on senses rather than the entry, the join step must surface it onto the entry. (2) Extra category grouping applies only when `activeArtist && artistVocabularyScope === 'extra'`. (3) Category order is by descending count then label; group set membership pages the incoming frequency/pooled order in 20-card slots.
- Verification: JavaScriptCore module parsing of `vocab.js`, `ui.js`, `main.js`, `flashcards-modals.js`; cache-version lockstep (SW `CACHE_NAME`+`ASSET_VERSION`, every `?v=` tag in `main.js`/`index.html`). No service-worker browser preview was used (project policy).

### 2026-07-26 — Granular sense and Expression knowledge

- Commit `2de025d7`; front-end cache `flashcards-v97` / `20260726d`.
- Added optional back-card actions for the active sense, Expression, or clitic form plus an `x/y known` summary. Ordinary gestures still answer the whole word; item choices create only sparse overrides, and the newest whole-card/item timestamp determines current knowledge.
- Level review now builds focused word cards containing only unresolved rows. A later whole-card correct resolves older row mistakes without writing every sense, while a later row mistake reopens that item. Identical rendered sense identities count once.
- Added offline queue/cache overlay support and an Apps Script schema-v2 `ItemProgress` tab with save/load/delete actions. Existing deployments must copy the updated `backend/GoogleAppsScript.js` and publish a new version; the sheet and headers are created automatically.
- Current assembled decks omit upstream sense IDs, so item identity temporarily falls back to normalized POS/gloss/context or Expression identity. Front-end loading already prefers future `sense_id`/`id` fields; pipeline changes must keep those IDs stable or migrate `ItemProgress`.
- Verification: JavaScriptCore parsing, timestamp-inheritance and focused-review cases, mocked Apps Script CRUD, module-preload/cache lockstep, unique DOM IDs, and `git diff --check` pass. No service-worker browser preview was used.

### 2026-07-26 — Level-scoped new learning and mistake review

- Commit `78b33505`; front-end cache `flashcards-v96` / `20260726c`.
- Replaced the lifetime `wrong > 0` language-wide deck with two explicit tracks. Learn new selects the earliest stable set with unseen cards and loads only its unseen subset; unresolved mistakes are collected across every set in the selected level under the current source, artist scope, Merge Lemmas, and Cognates configuration.
- Set fill now represents exposure rather than current mastery, and each set carries a small unresolved-review count. This means a wrong first answer advances the new-card sequence instead of holding the learner in that set. Continue last set remains an exact source/settings/order/card-position resume.
- Centralized backward-compatible progress state: timestamps determine the latest outcome, a newer correct resolves a prior wrong, lifetime counts remain intact, and legacy count-only rows with both correct and wrong are treated as resolved because their ordering cannot be recovered. Speech and Lyrics remain separate progress namespaces for now; selected artists supply the eligible lyric vocabulary.
- Verification: progress-state cases (`unseen`, unresolved wrong, legacy resolved, wrong-later, correct-later), JavaScriptCore parsing, unique DOM IDs, cache lockstep, stale-loader searches, and `git diff --check` pass. No service-worker browser preview was used.

### 2026-07-26 — Artist Expression vertical closed and handed back

- Commit `f53c82d8`; tests/documentation only, so no front-end cache bump or deck rebuild.
- Extended the multi-word contraction regression to prove that `vo'a` credits both `voy` and `a`, removes the fused token from word counts, preserves `vo'a` as each component's source surface, and preserves `me vo'a` as the exact Expression match.
- Added explicit final-consonant regression coverage: `lu'` restores to `luz` only when that restoration is unique, while ambiguous candidates remain untouched.
- Re-audited the shipped Bad Bunny, Rosalía, and Young Miko decks: 103/69/85 detected study rows, 669/318/367 card memberships, zero blank Expression translations, zero membership/example mismatches, and zero Expression rows without examples. No Gemini or pipeline rebuild was needed.
- Formally handed future pipeline-side MWE/clitic maintenance back to Claude under `COLLABORATION.md`; Codex retains Expression UI and the later granular-progress work. Six blank attached-clitic rows were deliberately not papered over because the audit found routing errors such as `prendaste → prenderse` where the lyric actually uses `prendarse`; those belong in Claude's routing gate.

### 2026-07-26 — Deterministic artist expressions completed

- Commit `1f649cfe`; front-end cache `flashcards-v95` / `20260726b`.
- Added 15 explicit lemma/link templates backed by the shared Spanish conjugation reverse map. They pool observed inflections, require a genuine construction complement, and safely recognise lyric infinitives with a morphology-confirmed dropped `r`; location uses such as `voy a casa` are excluded from `ir a + infinitive`.
- Construction lines can be removed from semantically different shorter expressions, so `me voy a beber` no longer inflates standalone `me voy`. Full phrase-dictionary contents are not auto-promoted: that audit caught the false match of `qué va` inside `qué va a pasar`.
- Only translated curated/construction rows and independently strong translated PMI rows enter learner decks. Untranslated PMI and variable-pronoun patterns remain review diagnostics; assembled rows have exact artist evidence and preserve their source tags.
- Rebuilt Bad Bunny, Rosalía, and Young Miko deterministically without Gemini. The decks contain 103, 69, and 85 study-ready artist expressions, including 42 construction families representing 229 observed inflected prefixes. Seven regression tests, Python compilation, JSON parsing, cache lockstep, and `git diff --check` pass. No service-worker browser preview was used.

### 2026-07-26 — Deterministic artist expression pooling

- Commit `44de7313`; front-end cache `flashcards-v94` / `20260726a`.
- Replaced the old “keep the most frequent spelling” family dedupe with a distinct-line union across curated morphological variants. Overlapping forms count a lyric once, while raw occurrence and distinct-song diagnostics remain available.
- Retained the canonical counting form, each variant, and the literal displayed lyric surface independently. This lets `voy a`, `va a`, `vas a`, `vo'a`, and similar forms share one construction while the card filters and highlights the spelling the learner actually sees. Samples split by punctuation/ad-libs are not presented as exact matches.
- Tightened variable-pronoun detection to reject fragments ending at the pronoun slot, and corrected the emitted MWE schema so curated, PMI, and pattern sources stay distinct. Expressions remain pinned rows on their relevant word/lemma cards; no new ordinary card type was introduced.
- Rebuilt deterministic step 2 and assembly output for Bad Bunny, Rosalía, and Young Miko without a Gemini step. Audit: 32 pooled families, no family without exact evidence, zero unmatched retained expression samples, and all family metadata reaches the artist indexes. Five Python regression tests, Python compilation, JavaScriptCore module parsing, JSON parsing, cache lockstep, and `git diff --check` pass. No service-worker browser preview was used.

### 2026-07-25 — Main and Artist Extra vocabulary scopes

- Commit `d0772972`; front-end cache `flashcards-v93` / `20260725al`.
- Replaced the individual single-occurrence filter with exactly two artist vocabularies. Main contains lemma families found in more than one distinct lyric line; Artist Extra contains families found in one. Classification is fixed at the lemma-family level, so an inflected surface seen once stays in Main when its lemma recurs and Merge Lemmas cannot move cards between scopes.
- Step 8b now stamps the pooled unique-line count, preserves the raw lyric for every Extra entry and every one-off Main surface, and packages a compact set of already-built Speech examples by lemma and sense. It does not invoke Gemini or manufacture a sense match: unclassified artist lyrics use the neutral linkage state, while inherited Speech examples retain their existing assignment evidence. Entries without a dictionary sense render as lyric-only cards with `No translation available yet`.
- Artist setup exposes Main/Extra beside the artist source. Each scope feeds the existing finishable level/set partition and scope-restricted stats, search explains cross-scope exclusions, saved sessions and URLs retain the scope, and finishing the final Main level offers the first Extra set. Provisional Learn later/Flag/Skip controls remain deferred until the cross-mode learner-options design.
- Rebuilt only deterministic assembly output for Bad Bunny, Rosalía, and Young Miko. The shipped split is Main/Extra `6,981/3,941`, `1,626/1,592`, and `2,361/2,102`; all Extra entries and all `3,384` one-off surface forms retained in Main have raw lyric evidence. Existing Speech support is available for `693`, `538`, and `533` Extra entries respectively.
- Verification: all three artist index/example JSON pairs parse; every classified fallback passes the raw-lyric audit; Python compilation, JavaScriptCore module parsing, duplicate DOM-ID checks, cache lockstep, and `git diff --check` pass. No service-worker browser preview was used.

### 2026-07-25 — Track-aware Spotify lyric autoplay

- Commit `8ec0c3dd`; front-end cache `flashcards-v92` / `20260725ak`.
- Autoplay now creates one fixed queue from the visible example, groups all eligible examples by Spotify track in first-seen order, and visits each track once. This removes `A → B → A` reloads while retaining every playable lyric example.
- At each line boundary Spotify pauses without forgetting the current track. A consecutive line from that song uses the official Web Playback SDK `seek()` and `resume()` methods; moving to a different song still issues a new play command but no longer repeats the browser-device transfer after the SDK session is active.
- The line-end timer now waits up to three seconds for `getCurrentState()` to confirm the requested track and position, so network/load latency no longer consumes the lyric's intended listening duration. A pulsing ellipsis communicates that initial song load, and the counter follows autoplay queue position rather than jumping with the underlying grouped indices.
- Verification: `spotify.js` and `flashcards.js` pass JavaScriptCore module parsing; queue/data attributes, cache lockstep, and `git diff --check` pass. The implementation was checked against Spotify's official Web Playback SDK reference. No service-worker browser preview was used.

### 2026-07-25 — Explicitly silent in-card rendering

- Commit `496e9b4e`; front-end cache `flashcards-v91` / `20260725aj`.
- The earlier object-identity guard in `updateCard()` did not prove strong enough in the running app. Replaced it with an explicit `announceHeadword` option that defaults to false.
- Only initial deck entry, next/previous navigation, answer/flag advancement, and shuffle-to-first-card opt into the Spanish headword. Autoplay, example/sense/expression cycling, row selection, grouped selection, and card-order changes remain on the silent default.
- Every silent rerender also cancels any queued Web Speech utterance, preventing a delayed headword from starting during the next Spotify lyric snippet.
- Verification: every `updateCard()` caller in `flashcards.js` was classified as entry or in-card rendering, opt-in calls are limited to six genuine navigation paths, cache versions are in lockstep, and `git diff --check` passes. No service-worker browser preview was used.

### 2026-07-25 — Progress-rail Study options

- Commit `569fd2e0`; front-end cache `flashcards-v90` / `20260725ai`.
- Moved the single Study options trigger from the detached floating toolbar to the final position in the active-set progress rail, replacing the old direct set-progress info button on desktop and mobile.
- The radial menu now contains `Set progress`, which opens the current-set stats modal. Removed its former all-time/global Progress action; global coverage remains available from setup rather than competing with set progress during study.
- Replaced the abstract `Direction` action with the destination wording `English first` or `<selected language> first`, calculated from the current card order.
- Mobile no longer displays the old toolbar inside the top of each card face; navigation and Study options remain together in the rail above the card.
- Verification: one unique `studyMenuBtn` remains, no `deckProgressInfo` references remain, cache versions are in lockstep, and `git diff --check` passes. No service-worker browser preview was used.

### 2026-07-25 — Transforming language and source setup

- Commit `b470516c`; front-end cache `flashcards-v89` / `20260725ah`.
- Step 1 begins as one keyboard-accessible `Choose language` box rather than a Language heading followed by a second choice row. After selection, that same box compacts to a `Language` summary containing the selected language and progress bar.
- Added a compact source control to the summary. It reads `Choose source` during the source decision and `Speech` after selection; tapping it reopens the shared Speech/Lyrics radial picker, with Lyrics continuing to the artist clock filtered to the selected language.
- Returning from Lyrics to Speech still uses the existing pending-language route and now lands with the source summary correctly set to Speech.
- Verification: required DOM IDs are unique, cache versions are in lockstep, `git diff --check` passes, and the remaining hidden language buttons continue to be the canonical loading/action targets. No service-worker browser preview was used.

### 2026-07-25 — Silent in-card navigation and autoplay

- Commit `6b615a2a`; front-end cache `flashcards-v88` / `20260725ag`.
- `updateCard()` now distinguishes an actual card arrival from a rerender of the same card, so the Spanish headword is announced once on entry rather than whenever an example, sense, expression, or autoplay step changes.
- Removed the additional TTS calls from tap/swipe sense selection and grouped rows. Deliberately flipping the card still speaks the newly revealed side, preserving the useful answer cue.
- Brought the lazy flashcard-module version into lockstep with the main asset version while bumping the service-worker cache.
- Verification: all remaining `speakWord()` call sites were inspected, cache versions are in lockstep, changelog JSON parses, and `git diff --check` passes. This environment has no Node runtime, and no service-worker browser preview was used.

### 2026-07-25 — Filter-aware, examples-safe vocabulary search

- Commit `6fb3ed91`; front-end cache `flashcards-v87` / `20260725af`.
- Search now indexes a clone of the full source vocabulary, so applying the current deck filter cannot strip meanings from the cached entries it later opens.
- Results and popup fronts identify current exclusions such as cognate, proper noun, single occurrence, English loanword, noise/interjection, or merged lemma form instead of displaying a misleading configuration rank.
- Entries with no usable translation or positive artist sense are guaranteed a safe examples-only meaning. All available sense/MWE/remainder examples are flattened and deduplicated; if none exist, the card shows an explicit unavailable message rather than throwing on an empty meaning array.
- Corrected the result-list gloss lookup from the nonexistent `meaning` field to `translation`. A data audit found 577 Spanish Speech source entries with examples but no usable sense, confirming this is a material path rather than a hypothetical edge case.
- Verification: JavaScript syntax, cache lockstep, and `git diff --check` passed; no service-worker browser preview was used.

### 2026-07-25 — Modern first-login surface

- Commit `4d8dc90a`; front-end cache `flashcards-v86` / `20260725ae`.
- Replaced the old generic Welcome to Flashcards dialog with a responsive Fluency welcome surface, modern entry cards for initials and guest use, and a restrained password-free beta explanation.
- Initials entry now has a dedicated form state and resets cleanly whenever the auth surface is reopened. The existing local/session storage and Google Sheets login contracts are unchanged.
- Verification: JavaScript syntax, required auth element IDs, cache lockstep, and `git diff --check` passed; no service-worker browser preview was used.

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
