# Codex changes and cross-model handoff

This file tells Claude and future Codex sessions what Codex changed, why, and how it was checked. Git remains authoritative for exact diffs; `config/dev_changelog.json` remains the in-app user-visible history; GitHub Issues remains the live backlog.

Maintenance rule: after each completed Codex task, prepend a dated entry to **Codex task history** after the commit exists. Include the final commit hash, user-visible result, non-obvious decisions, verification, and cache version for front-end work. Do not silently rewrite an earlier decision—add a newer entry explaining the change.

## Current architectural decisions from the Codex work

- Study decks use finishable frequency levels and stable, discrete study sets. Set identity is rank-based so changing Merge Lemmas or Cognates does not reshuffle the underlying set boundaries.
- Lyrics vocabulary has exactly two lemma-family scopes: Main for more than one distinct lyric line and Artist Extra for one. Extra is a learnable corpus scope, not a readiness quarantine; unclassified lyrics remain visible without pretending they match a sense.
- The normal setup and active-study flow share radial pickers and a discrete progress rail. Partial level progress is visible, and study sets are intended to feel independently completable.
- Merge Lemmas is the user-facing name. It is off by default; Exclude Cognates is off by default.
- Artist corpus frequency excludes exact repeated lyric lines within each song. Lemma-mode card frequency and examples use the same pooled sibling basis.
- Artist rank ties use each word's full distinct-song spread, not the capped example sample. Artist lyric examples prefer an explicitly credited active artist, Spotify availability, and a standard release in that order before the teaching signals.
- Desktop lyric autoplay is line-bounded and card-wide: it announces each sense/sub-sense/Expression with distinguishing context, plays that item's eligible examples, and skips unplayable lines without changing full-list counters. It remains unavailable on mobile where Spotify handoff timers cannot guarantee the stop boundary.
- Card grammar uses an adaptive identity block: a distinct lemma shares its row with POS, repeated lemmas leave no placeholder hole, and verb morphology wraps independently below. POS pills, English morphology labels, semantic POS/special-row colour themes, pooled-form highlighting, and the grouped/linked card-back layout remain. Sense-row typography scales with copy length; Expression rows stack upright source text above italic English, while clitic rows remain compact. Trivial plural and elision form metadata is suppressed on the back.
- SpanishDict sense menus for normal and artist modes share `pipeline/util_5c_spanishdict.py`; reverse-direction conjugation collisions such as `sea` are guarded there rather than patched only in a final deck.
- Spanish Speech vNext is a versioned data candidate rather than an in-place rewrite or a separate learner UI. Its eventual route must use the ordinary setup, sets, cards, navigation, and info panel while swapping only same-schema Spanish index/example paths. Stable SpanishDict sense IDs, legacy word IDs, canonical examples, and reviewed evidence may migrate forward; legacy runs remain recoverable. The earlier four-word custom preview is superseded and must not be treated as the target app experience.
- Sentence-aligned bilingual string matching is rejected as Spanish Speech WSD or prominence evidence. It may retrieve candidates, but a word aligner is needed to bind an English cue to the Spanish token and a separate semantic gate is still needed for the full SpanishDict translation/context. No string-match counts may become learner percentages.
- For high-precision external examples, literal cues may retrieve candidates and a conservative closed-set semantic gate may validate the exact SpanishDict leaf. On the first fixed benchmark, semantic validation outperformed mandatory word alignment; alignment remains useful diagnostic/consensus evidence. This candidate-selected method cannot estimate prominence because retrieval and gate recall are sense-dependent.
- Audit flags separate the target (pairing, meaning, example, lemma, word form, card, or note only) from the problem category. They default to the visible sense–example pairing and store structured evidence through the existing FlaggedWords backend contract.
- Artist expressions remain rows on word/lemma cards. Curated and morphology-backed construction templates pool deterministic unique-line evidence, require their semantic complement, and preserve exact lyric surfaces.
- Per-sense, Expression, and clitic knowledge is a sparse override layer on whole-card progress. The newest parent/item timestamp wins, and level review synthesizes focused word cards rather than creating a second permanent card taxonomy. Standard and artist decks now ship stable sense IDs, preserving aliases and legacy content-derived progress during migration.
- Progress-fill colours are semantic across every language and artist: green means Known/current, amber means Review/due, and neutral means Unseen. Source identity remains in surrounding accents and selection borders rather than competing with progress meaning.
- App appearance has three device-persistent choices: Dark, Light, and System. Dark remains the no-preference default; a synchronous head bootstrap prevents a wrong-theme first paint. Light uses its own semantic paper/ink palette and targeted media/glass treatments rather than inversion, while language, artist, POS, and progress meaning remain intact.
- The original warm-paper light direction is superseded by a cool daylight hierarchy: a blue-grey app canvas, true-white working surfaces, subtly tinted nested panels, and crisp neutral shadows. This is still the same Fluency visual language—not a separate product skin—and existing typography, rounded card construction, density, accent framing, radial interactions, and semantic colours stay authoritative.
- Light appearance must not inherit literal white text or translucent-white chrome except on solid semantic fills, artwork, branded media, and floating dark toasts. Muted ink must meet WCAG AA on the darkest light neutral, and POS light-mode ink is authoritative even inside more-specific component selectors.
- SpanishDict usage metadata is a visible sense qualifier, not an automatic MWE claim. Cards keep ordinary semantic context separate from compact usage cues, and a companion found in an example is labelled only as a possible textual match because co-occurrence does not prove same-clause attachment.
- SpanishDict-backed cards expose a visible Dictionary tile on the back. Its disclosure browser shows only source fields actually packaged with the card plus the app's explicitly labelled presentation parsing; it never presents estimated sense share or model output as SpanishDict metadata.
- Spaced repetition is an optional, device-persistent Study setting and defaults Off while the app is under development. When enabled it is level-scoped, with transparent 1, 3, 7, 14, 30, 60, and 120-day intervals. Pausing suppresses time-based due status without erasing stages/timestamps; explicit mistakes and partial cards always remain in Review.
- Level estimation is a 30-item receptive check over the normal Speech frequency list. It samples the full distribution before adapting around the uncertain boundary, reports a range, and persists the curve's point estimate through the existing single-rank contract. It is deliberately not labelled as productive ability or calibrated IRT.
- A card's stable `targetWord` identity is separate from `displaySurface`, `citationForm`, and `productionAnswer`. Spanish→English uses the first two and labels pronominal lemmas in plain language. English→Spanish uses the production answer: exact surface when unmerged, lemma when merged, and the complete `-se` citation for older pronominal data, with the evidenced example form shown separately.
- English-first surface cards use a bounded semantic fingerprint: one distinct cue per lemma/POS reading first, then other strong senses, with duplicate English text removed and a four-cue cap. English morphology is resolved against each sense's lemma rather than the card's majority lemma, and incompatible non-verb lemma-menu leakage is suppressed when a surface-compatible cue exists.
- English production cues are keyed by complete mood/tense analysis. Indicative forms, conditionals, affirmative/negative commands, gerunds, and past participles can render the matching English form; supported alternatives on one Spanish surface remain compactly visible. Context-dependent imperfect and subjunctive readings deliberately retain the dictionary gloss beside the persistent grammar cue rather than claiming one universal English equivalent.
- English-first verb morphology is a persistent coupled subject + tense/mood cue, with the full analysis still available from the POS pill. Sentence context is optional and may become a cloze only when the active example contains the exact production answer; merged/restored mismatches abstain. Recognition sense groups default to all-open only when their measured rendered height fits, and manual expansion always wins thereafter.
- Regular plural dictionary twins share their explicit singular lemma identity while preserving every source sense ID. Derivational families such as `besito` → `beso` remain separate cards/progress records and use a conservative, auditable relation layer rather than suffix-only collapsing.
- Card reporting has one owner-facing route: both visible report controls open the structured audit sheet directly; the obsolete metadata/field-flag sheet is retired.
- Artist clitic rows consume split-example `c` buckets in single- and multi-artist decks. They teach the exact attached form as an infinitive, gerund, or affirmative command plus the clitic's person/case and English role, rather than presenting only the base infinitive gloss.
- Boot, source navigation, exact resume, and deck replacement share one app-level loading surface. It covers partial auth/setup/card DOM until the destination is coherent; it does not justify artificial waiting, and cached progress should remain usable while remote Sheets reconciliation runs in the background.
- Source setup keeps parsed indexes by data path and shares one source/settings/examples-keyed filtered vocabulary across level, progress, exclusion, and set UI. Artist frequency extraction must use that same canonical loader rather than parsing the index independently.
- Source navigation is directional rather than a mandatory mode decision: choosing or changing a language continues directly in Speech, while Browse Lyrics opens the Lyrics-source picker. Spanish Test Playlist remains a shipped source; Choose your own is a separate synthetic source that unions the live catalogues and stores one editable song selection without changing card IDs.
- Google Sheets schema v4 has one discriminated `Progress` tab for word, sense, MWE, clitic, and metadata rows, plus the separate `FlaggedWords` tab. Speech/Lyrics are a `Mode`, item rows use `ParentWordId`, and artist-specific routing metadata carries a `Source`; the automatic migration retains the old three progress tabs as `*_legacy` backups and accepts cached v3 clients during rollout.
- A marked-done level is a scoped, reversible suggestion-routing override only. It is keyed by mode + language + artist source, skips auto/estimate/resume/advance suggestions, never synthesizes card knowledge, and never prevents explicitly opening the level.
- Completing a new-card set automatically continues after a short 1.2-second completion beat. The router verifies rendered set progress, skips nominal levels with no unseen cards, and never falls back to replaying a completed set; Main menu and Redo remain explicit cancellation choices. Audit flags acknowledge the gesture immediately and resolve in a global `Card flagged` status above all app surfaces.
- Artist corpus evidence now has a language-neutral segment/occurrence ledger contract. Mutable normalization, routing, POS, lemma, and sense decisions address persisted evidence IDs; model methods coexist under an active profile; card identity is registered separately from mutable lemma/gloss properties. The artist orchestrator now inserts a provider-neutral occurrence-level vocal-artifact claim run and a strict-parity active-view materializer before legacy normalization, so compact app decks can be rebuilt from the ledger without making the browser load it. Classification labels remain separate from exclusion policy.

## Open handoff notes

- The English production layer still needs sentence-level composition for compound verb phrases and attached clitics (for example `hemos hablado` or `dámelo`) rather than pretending a single-token card proves that whole English frame. Blank dictionary translations such as the `venir` reading of `vino` also cannot produce `came`; context-dependent imperfect and subjunctive readings intentionally abstain.
- The Dictionary browser is ready to display `regions` once deck assembly begins shipping them. Current normal and artist compact decks omit that field, and artist decks also omit SpanishDict examples, so the browser truthfully shows only the raw fields that reached each card rather than fetching or reconstructing missing source data in the app.
- SpanishDict usage cues are presentation-only for now. A later WSD experiment should preserve that boundary and measure clause/attachment evidence before using a companion token as a feature. Other promising upstream features currently absent from the embedding gloss include sense regions, exact headword/lemma identity, redirect/conjugation relation, the second dictionary example, and sense-aligned thesaurus links; these should be evaluated as priors/features rather than silently folded into observed corpus frequency.
- `backend/GoogleAppsScript.js` commit `b4fac72e` adds the `SongSets` sheet contract, but the Apps Script deployment is deliberately manual and has not been performed by Codex. Until Josh deploys that revision, per-song choices remain durable on-device and queued account writes will retry from Offline & sync.
- The accepted pipeline, app, compact decks, assignments, and register are protected by release commit `1e6b70b6`. Large local Evidence Store ledgers and generated candidate previews remain deliberately outside Git; closing this chat does not remove those local artifacts.
- Spanish Test Playlist, Bad Bunny, Rosalía, Young Miko, J Balvin, and Rels B now have Evidence Store ledgers. Bad Bunny, Rosalía, and Young Miko have been rebuilt into the live compact app decks; J Balvin and Rels B have deterministic inventory/POS checkpoints but still need SpanishDict cache coverage and sense work before they become configured live sources.
- The large artist evidence directories total roughly 3 GB and Git LFS is not installed. They remain local pending an explicit artifact-storage/compression decision; do not attempt to push the raw 100+ MB J Balvin normalization shards to ordinary GitHub storage.
- The playlist's ignored working SpanishDict menu and assignments are now recoverable through committed immutable snapshots selected by `data/evidence/profiles/current.json`; do not reintroduce those large mutable inputs as the only replay source.
- Speech-shaped parallel segments are accepted and tested by the shared contract, but Speech and Normal Mode have not been migrated to use the Artist evidence store or card registry.
- The full Node suite currently has seven pre-existing failures against `HEAD`: five stale `tests/ui-refinements.test.mjs` assertions (cognate explanation naming, morphology markup, bilingual row markup, grammar markup, and reference-control class names), one reviewed personalised-frame/data mismatch, and the already-recorded offline-manifest checksum mismatch for the rebuilt Spanish index. Theme-focused and relevant UI/offline-policy tests pass; this unrelated test/data debt was not rewritten as part of appearance work.

## Codex task history

### 2026-08-17 — Expand analysis-aligned English production forms

- Commit `9df65d81`; front-end cache `flashcards-v249` / `20260817a`; GitHub issue #61.
- Step 5e v3 now keys its shared English layer by complete mood/tense analysis and adds LemmInflect-backed gerund and past-participle spellings. Conditional and command frames are derived from the same exact infinitive sense in the app, keeping the shared layer at 5.6 MB instead of repeating predictable strings for every person.
- English-first cards now render conditionals, affirmative/negative commands, gerunds, and past participles as well as the existing indicative forms. Multiple supported analyses are deduplicated and displayed compactly (`da` can show indicative and command prompts); unsupported alternatives do not suppress a supported one.
- Spanish imperfect and subjunctive still abstain because there is no single context-free English realization. The card retains its dictionary gloss and the already-persistent person + grammar cue, avoiding a confidently wrong paraphrase.
- Shipped-data audit: usable verb-card cues rise from 1,674 to 3,368 across the 9,338-card Spanish index. Verification: four Python generator regressions, thirteen reverse-cue/presentation regressions, a full step-5e rebuild and spot checks, JavaScript syntax for every module/service worker, asset-version lockstep, and `git diff --check`. The full Node suite remains 64/71 with the same seven documented baseline failures (one reviewed-frame fixture, one offline checksum, five stale UI assertions). No browser preview was used.

### 2026-08-16 — Auto-continue new study sets and make flag confirmation unmistakable

- Commit `adfcb088`; front-end cache `flashcards-v248` / `20260816n`.
- Completing a new-card set now retains the completion card for 1.2 seconds and then invokes its continuation automatically. Main menu and Redo cancel the timer, review completion remains deliberate, and a failed load reopens a stable non-retrying error state.
- Next-level routing now verifies the candidate level's rendered sets and scans forward until it finds a genuinely unfinished set. It no longer falls back to replaying an arbitrary completed set when progress metadata is stale or filters empty a nominal level.
- Flag submission now raises a global `Flagging card…` status before awaiting the durable save/queue, then resolves the same card to `Card flagged` or `Flag not sent`. Its stacking level sits above menus, modals, cards, and the loading surface, and success remains visible for 2.6 seconds.
- Verification: two new continuation/flag regressions plus 19 focused routing, progress, surface, and English-first checks; JavaScript syntax for every module and service worker; asset/cache lockstep; `git diff --check`. The full Node suite is 62/69, with the same seven documented baseline failures unchanged. No browser preview was used.

### 2026-08-16 — Refine production cues and recognition sense density

- Commit `afccfd1a`; front-end cache `flashcards-v247` / `20260816m`.
- English-first verb cards now keep each coupled person + tense/mood analysis visible beneath the semantic fingerprint. The verb POS pill still opens the complete explanation, while recognition cards retain the quieter popover-only treatment.
- Added an optional Sentence hint outside the flip target. It blanks context only when the active example contains the exact production answer, with boundary-safe matching across whitespace and straight/curly apostrophes; uncertain merged/restored mismatches do not manufacture a cloze.
- Recognition backs now place `+N` directly after the summary gloss, omit the pressuring `Choose` label above POS filters, and give ordinary sense copy a one-pixel type increase. Multi-POS groups are all opened on first presentation when their measured natural height fits the remaining card space; dense cards keep the active group open, and any manual expansion choice disables the automatic default.
- Verification: 12 reverse/presentation regressions, 20 relevant SpanishDict/surface/theme checks, JavaScript syntax for every module and service worker, asset/cache lockstep, and `git diff --check`. The full Node suite is 60/67 after the three added passing regressions; the same seven documented baseline failures remain. No service-worker browser preview was used.

### 2026-08-16 — Improve English-first semantic and morphological cues

- Commit `347aa1bf`; front-end cache `flashcards-v246` / `20260816l`.
- English-first cards now present a bounded semantic fingerprint rather than only positive-frequency leaves: every distinct lemma/POS reading gets first consideration, followed by other strong senses, with duplicate glosses removed and a four-cue cap.
- English production now consumes each sense's own lemma. Homographs such as `fue` render both `he/she/it went` and `he/she/it was`; mixed readings such as `casas` independently render `houses`, `companies`, and `you marry`.
- A conservative surface-compatibility gate removes lemma-menu leakage such as noun `power` from finite `puedes`, while an explicit fallback guarantees that older/incomplete cards never acquire a blank reverse face. Ambiguous Spanish analyses still decline to manufacture one English form.
- Verification: eight focused reverse-cue regressions, JavaScript syntax for every module, asset/cache lockstep, `git diff --check`, and a shipped-data audit covering all 9,338 Spanish cards. The full Node suite remains at its documented 57/64 baseline: one personalised-frame fixture mismatch, one stale offline-manifest checksum, and five stale broad UI assertions are unchanged. No service-worker browser preview was used.

### 2026-08-16 — Add a card-back SpanishDict data browser

- Commit `8761de64`; front-end cache `flashcards-v245` / `20260816k`.
- Added a visible Dictionary tile to every card carrying SpanishDict senses. It opens a full-card, scrollable disclosure browser rather than relying on a hidden long press or the owner-only model-provenance menu.
- Each sense exposes the raw fields actually packaged with the card: English gloss, headword, part of speech, stable sense ID, raw context, optional regions, and any packaged dictionary example. The usage parser's friendly label and display-only candidate spellings sit alongside the raw note with an explicit no-attachment/no-WSD caveat.
- Kept estimated corpus percentages, assignment methods, and model provenance out of the dictionary panel. App-side joins now preserve future `headword` and `regions` fields when deck assembly supplies them; no runtime source fetch or guessed metadata was added.
- Verification: five focused parser/metadata/rendering regressions; eleven relevant card/surface/theme regressions; JavaScript syntax for the card renderer and vocabulary join; all 72 asset tags in lockstep; `git diff --check`. The five relevant offline policy/version checks pass; the pre-existing Spanish index manifest-size assertion remains stale. Browser preview was not used, per repository policy.

### 2026-08-16 — Present SpanishDict usage metadata on sense examples

- Commit `1a2d53e3`; front-end cache `flashcards-v244` / `20260816j`.
- Added a pure usage-note parser and rendered SpanishDict's structured hints as compact sense qualifiers while retaining any separate semantic context. The current menu's 5,855 `used with` occurrences across 382 distinct strings parse without fallback loss, including alternatives, complements, structural notes, and `often` / `frequently` qualifiers.
- Added display-only surface expansion for common contractions and pronoun forms. Literal companions in the active example use a distinct possible-match highlight whose tooltip says attachment is unverified; this is deliberately not WSD evidence and longer phrases are protected from nested highlighting.
- Audited adjacent SpanishDict metadata for the deferred WSD pass. The menu retains regional labels and up to two dictionary examples, while final assembly drops regions and normal mode keeps only the first example; analysis-level redirect relations and sense-aligned thesaurus structure also do not reach the current embedding gloss. These are candidates for controlled evaluation, not frequency evidence.
- Verification: four focused parser/variant/rendering regressions; eleven relevant theme and occurrence-surface regressions; JavaScript syntax for the new module, card renderer, and service worker; all 72 asset tags in lockstep; full-menu parse audit; `git diff --check`. The existing offline-manifest checksum and five stale broad UI assertions remain outside this pass. Browser preview was not used, per repository policy.

### 2026-08-16 — Repair light-appearance contrast and invisible chrome

- Commit `bf0148c2`; front-end cache `flashcards-v243` / `20260816i`.
- Audited the base stylesheet's literal-white foregrounds and translucent-white surfaces against the light override. Replaced the dark-only treatment on audit/reporting, the card-back scrubber, current progress markers, Knowledge, synonym, conjugation and provenance sheets, reference/breakdown controls, completion stats, and related hover/selected states while retaining intentional white on solid status fills, artwork, Spotify and toasts.
- Fixed the cascade bug that let higher-specificity component rules restore white text over all 21 pale POS treatments. Each light POS ink now wins explicitly and individually clears WCAG AA on white; muted text was deepened to clear AA even on the darkest light neutral, and placeholders now share that readable token.
- Preserved semantic states after the contrast remap: Known, Review, phrase, selected synonym, active conjugation, and visited/current scrubber states still remain distinct instead of collapsing to generic grey.
- Verification: five theme/bootstrap/persistence/contrast/major-sheet regressions; three relevant Settings/performance/conjugation checks; two offline policy/version checks; JavaScript syntax for every module and service worker; CSS block structure; 70 asset tags in lockstep; valid changelog JSON; `git diff --check`. Browser preview was not used, per repository policy.

### 2026-08-16 — Refine light appearance as Fluency in daylight

- Commit `8cc332fc`; front-end cache `flashcards-v242` / `20260816h`.
- Reworked the light palette after live review found the first pass too close to an inverted dark theme. The warm beige canvas and brown shadows are replaced by cool daylight neutrals, true-white working surfaces, blue-grey borders/shadows, and clearer surface elevation.
- Preserved the product's established visual grammar: typography, compact density, rounded card geometry, dynamic language/artist accent framing, POS colour families, semantic progress states, and radial interactions remain unchanged. Nested setup/settings panels, study-set empty states, examples, artist artwork, pickers, authentication, native fields, and floating surfaces now use intentional light-specific roles.
- Updated the browser theme colour and strengthened the theme regression to pin the cool canvas, white card surface, key Fluency panel coverage, and WCAG-AA status/text contrast.
- Verification: four theme/bootstrap/persistence/system-sync/contrast regressions; three relevant Settings/performance/conjugation checks; two offline policy/version checks; JavaScript syntax for every module and service worker; CSS block structure; 70 asset tags in lockstep; valid changelog JSON; `git diff --check`. Browser preview was not used, per repository policy.

### 2026-08-16 — Add a designed light appearance

- Commit `d0dbda26`; front-end cache `flashcards-v241` / `20260816g`.
- Added device-persistent Dark, Light, and System choices at the top of Account settings. The stored choice is applied synchronously before CSS paints, System follows live OS changes, open tabs synchronize, browser chrome updates, and the three-way control has radio semantics plus arrow/Home/End keyboard behavior. Dark remains the backward-compatible default.
- Built a separate semantic light stylesheet around warm paper surfaces, dark ink, quiet borders/shadows, and WCAG-AA text/status colours rather than an inversion. Language and artist accents remain dynamic; fixed accent contrast now uses stable dark ink on light brand colours instead of borrowing the current page background.
- Covered setup, cards and their grouped content, POS themes, examples, artist artwork, radial pickers, authentication, settings, audit/knowledge sheets, popovers, native fields, desktop/mobile controls, About examples, and offline surfaces. Media-backed identities such as album thumbnails and Spotify retain intentional white-on-image treatment.
- Verification: four focused theme/bootstrap/persistence/system-sync/contrast/offline-cache regressions; two relevant offline policy/version checks; three relevant existing Settings/performance/conjugation UI checks; JavaScript syntax for every module and service worker; CSS block structure; 70 asset tags in lockstep; valid changelog JSON; `git diff --check`. The full Node run is 43/50 with the seven pre-existing failures recorded under Open handoff notes. Browser preview was not used, per repository policy.

### 2026-08-16 — Select and persist Lyrics decks by song

- Commit `b4fac72e`; front-end cache `flashcards-v240` / `20260816f`; GitHub issue #60.
- Added a reproducible compact song-catalog generator that joins the surface-keyed final indexes to complete `song_ids` membership from merged evidence. Shipped catalogs cover Bad Bunny (295 songs / 10,685 linked cards), Rosalía (107 / 3,215), Young Miko (90 / 4,460), and Create your own (17 / 1,108).
- Artist setup now opens a searchable multi-song picker. The selected union filters cards without changing IDs or global order; sampled lyric examples from unselected songs are removed while songless SpanishDict evidence remains. Spanish Test Playlist is relabelled `Create your own`.
- Selections persist locally, are included in exact study-session snapshots, and queue one idempotent named-account record per source. Word and granular knowledge remain on their existing surface IDs and continue to share across Lyrics sources.
- Added a version-1 `SongSets` Apps Script sheet with save/load/delete actions and capability reporting. The production script is ready in the repository, but deployment remains Josh's manual step; the app degrades safely to local persistence against the older deployment.
- Added each song catalog to its retained offline source manifest and invalidated cache-first configuration/data. Verification: focused pipeline generator parity, five card/example/config/session/backend app regressions, extended in-memory Apps Script round trip, JavaScript syntax, catalog/index referential integrity, JSON parsing, asset-version lockstep, and whitespace validation pass. Browser preview was not used, per repository policy.

### 2026-08-16 — Import surface-keyed Spanish Speech vocabulary

- Commit `bd0fc096`; front-end cache `flashcards-v239` / `20260816e`; GitHub issue #59.
- Added a named-account importer under Account settings with paste/file input, exact preview, skipped-row evidence, projected Known/Review/Due state, and explicit confirmation. It accepts one surface per line or UTF-8 CSV/TSV with `surface`/`word` plus optional lemma and last-correct/last-incorrect fields.
- Matches only the shipped Spanish Speech index after trim, NFC, and Spanish lowercase. Accents and punctuation remain identity-bearing, lemma is never a fallback, unmatched rows are never hashed, and every imported ID is explicitly `es0` plus the index's authoritative eight-hex ID even when opened from Lyrics.
- Historical dates remain truthful: undated rows receive a correct event at confirmation, a newer imported mistake remains Review, invalid/future dates are skipped, and newer existing progress, cumulative counts, and review stages never regress. Duplicate input and re-import are idempotent.
- Reused the deployed schema-v4 `bulkSave` path in 50-row chunks, with the account on every row and pending bulk rows included in the local overlay. Production Apps Script did not change and needs no deployment.
- Verification: seven focused parser/identity/date/merge/batch/UI/queue regressions; the existing in-memory Apps Script migration and round-trip suite extended with bulk insert/update/idempotency; all 9,338 shipped Spanish Speech surfaces are unique with valid eight-hex IDs; JavaScript syntax, asset/cache lockstep, JSON parsing, and whitespace validation pass. Browser preview was not used, per repository policy.

### 2026-08-16 — Activate imperfect-subjunctive conjugation data

- Generator commit `d6b00155`; generated-data/cache commit `616c1b01`; front-end cache `flashcards-v238` / `20260816d`; GitHub issue #57.
- Added Verbecc's `subjuntivo / pretérito-imperfecto-1` to the learner-facing table as `Subj. Imperfecto`, including the exact `haber` paradigm `hubiera`, `hubieras`, `hubiera`, `hubiéramos`, `hubierais`, `hubieran`.
- Kept the reverse lookup keyed to Verbecc's explicit `-1` table, while mapping Wiktionary's intentionally normalized `subjuntivo / pretérito-imperfecto` fallback into the same display slot without pretending it distinguishes `-ra` from `-se`.
- Rebuilt both conjugation layers from active generator version 4. The checked-in artifacts had remained on version 2, so this also materializes the already-committed version-3 morphology fallback: 1,496 verb entries now carry the new table, with the generator's current source set adding 104 lemmas, removing 15, and changing four other paradigms.
- Verification: two focused generator regressions, exact `haber` JSON assertion, sidecar-version checks, full JSON parsing, JavaScript asset-version lockstep, and whitespace validation pass.

### 2026-08-16 — Normalize conjugation-panel typography

- Commit `7ee58393`; front-end cache `flashcards-v237` / `20260816c`; scope update recorded on GitHub issue #8.
- Audited the panel before editing. The ordinary panel copy correctly inherited `--font-reading` and the infinitive correctly used `--font-emphasis`, but mood/tense tabs and pronouns used `--font-data`, conjugated forms used `--font-emphasis`, and the close control had no author font token.
- The infinitive remains the only emphasized panel title. Close control, text tabs, subjects, and conjugated forms now explicitly use the card's reading face; the data face remains reserved for counts, codes, and diagnostics elsewhere.
- Verification: focused executable CSS regression proves the core conjugation block contains no data-face declaration and only the infinitive retains emphasis; asset-version lockstep and whitespace validation pass. The five unrelated stale assertions already documented under Open handoff notes remain outside this typography scope.

### 2026-08-16 — Replace header form piles with explicit elision cues

- Commit `75911281`; front-end cache `flashcards-v236` / `20260816b`; GitHub issue #58.
- Verified first: all shipped Speech and Spanish Artist decks already render zero generic header form lists, and exact occurrence-surface highlighting is healthy across 6,398 artist examples. The remaining risk was dormant object-variant code that could revive a pile later, while none of the requested non-obvious restorations was visible.
- Removed generic variant-driven headword replacement. The card's own word now remains the headword in every deck; exact occurrence surfaces continue to be highlighted in the example sentence.
- Preserved only three reviewed, metadata-gated relations as compact cues: `pa' → para`, `na' → nada`, and `cometamo' → cometamos`. Ordinary final-letter elisions, plurals, conjugation families, and clitic arrays cannot enter the header path.
- Verification: six focused executable surface/card/progress regressions, JavaScript syntax checks, asset-version lockstep, JSON parsing, and whitespace validation pass.

### 2026-08-16 — Seek Spotify to each lyric example timestamp

- Commit `875ddbb8`; front-end cache `flashcards-v235` / `20260816a`; GitHub issue #56.
- Direct lyric playback now identifies a request by both Spotify track and requested start time. Choosing another example from the same song therefore issues a fresh timestamped play command instead of entering the same-track pause/resume branch.
- Repeated activation of the same example retains the existing pause/resume behavior. Desktop card-wide autoplay remains unchanged: it still uses the SDK's local seek/resume path for consecutive snippets on one loaded track.
- Verification: focused executable playback-identity regression, JavaScript syntax check, asset-version lockstep, and whitespace validation pass. The unrelated offline-manifest integrity assertion remains stale against the already-present rebuilt Spanish index (`15,795,398` actual bytes vs `15,104,343` recorded); the remaining offline policy/version tests pass.

### 2026-08-12 — Replace mixed-scope curations and gate shared-register membership

- Commit `4f2e22ef`; front-end cache `flashcards-v225` / `20260812d`.
- Compacted `elision_mapping.json` from 2,882 to 1,891 active records by deleting 971 consumer-inert `same_word_dup` rows, seven non-operative `skip` rows, and thirteen reviewed bad generated restorations. Trailing-apostrophe fallback now requires corpus attestation, resolves ambiguity only at fourfold frequency dominance, and protects already registered lyric lexemes such as `mai`.
- Removed global noise/name drops for mixed lexical surfaces and recategorized definite English items. The occurrence-level vocal-artifact layer remains responsible for repeated, echoed, and hyphenated uses; a surface with lexical evidence is no longer erased everywhere.
- Removed curated MWEs that contradicted skip policy, duplicated productive construction templates, or represented incomplete/dead fragments. Deck assembly now revalidates stale materialized curated MWEs against the current curated and skip files.
- Added register policy roles. Bad Bunny, J Balvin, Young Miko, and Rels B contribute to `reggaeton`; Rosalía and Spanish Test Playlist consume only. Two distinct occurrences or two contributors establish a menu candidate. Singletons remain provisional and can transfer only through one-sense exact-line reuse.
- Defined non-transitive growth rules for future register members: consumer-first admission, independent multi-register thresholds, one vote per contributing artist, provenance-preserving disputed/retired states, and locale only as a ranking hint.
- Coalesced historical analysis aliases that resolve to the same persistent card ID, preserving combined senses, examples, counts and provenance. Rebuilt the four live Spanish Artist decks without Gemini/API calls and refreshed offline integrity metadata.
- Protected new evidence stores and disposable preview decks from accidental Git staging. The roughly 3.36 GB local archive is not an app-runtime dependency, but remains a moderate exact-rebuild/data-loss risk until copied to verified external artifact storage.
- Final verification covers 59 focused Python contracts, compact JSON parsing, zero duplicate IDs, exact index/example alignment, routing/elision/register/MWE invariants, offline hashes, cache lockstep, and whitespace validation.

### 2026-08-12 — Standardize reusable slang senses across tagged artists

- Commit `1e6b70b6`; active shared front-end cache `flashcards-v224` / `20260812c`.
- Added configurable `sense_registers` to artist configuration and seeded a `reggaeton` register with Bad Bunny, J Balvin, Young Miko, and Spanish Test Playlist. Its derived 1,357-word / 1,665-sense inventory clusters near-duplicate same-POS proposals while retaining the contributing artist, method, prompt, run, example, and occurrence provenance.
- Register senses supplement SpanishDict only for words present in the target inventory. Identical cross-artist Genius song lines can reuse one registered sense as deterministic `shared-register-auto`; different contexts merely receive the standardized candidates and remain eligible for POS filtering or WSD. Gemini now treats deterministic `*-auto` coverage as already handled, reserving calls for unresolved occurrences.
- Tightened single-sense automatic assignment: trusted occurrence POS can veto an incompatible menu sense, and an exact full credited-performer match vetoes an unrelated common-noun reading. The assembly fallback applies the same name guard so an unassigned example cannot restore the rejected sense.
- Rebuilt Spanish Test Playlist without an API call. `mari` now uses registered NOUN “marijuana” via POS auto, `feka` reuses registered ADJ “fake” from its identical Bad Bunny line, and `Boza` is a proper-name Extra card with no “rope” meaning. Thirteen exact cross-artist lines were reused deterministically.
- Fixed an existing classifier identity bug that converted explicit provider/register sense mappings to value lists and re-hashed their IDs, plus a stale-assignment sanitizer bug that reloaded discarded state and incorrectly treated inline discovered senses as menu-stale.
- Verification: focused register/config/POS/menu/deck tests, exact target-card assertions, zero duplicate deck IDs, JavaScript syntax and provenance tests, JSON validation, offline checksum validation, cache-version lockstep, and diff whitespace validation.

### 2026-08-12 — Replace risky lyric overrides with deterministic elision and abstention rules

- Commit `1e6b70b6`; front-end cache `flashcards-v222` / `20260812a`.
- Added high-precision internal-apostrophe restoration: a form is rewritten only when inserting one consonant at the apostrophe yields one known Spanish form. Contextual checks resolve otherwise ambiguous past-tense, adjective, and plural cases; diminutive `d` elisions validate against their base adjective; unsupported forms abstain.
- Rebuilt Spanish Test Playlist from its occurrence ledger without a Gemini/API call. The audited lyric forms now resolve as `uste'`→`usted`, `e'to`→`esto`, `moja'íta`→`mojadita`, `e'perado`→`esperado`, `llega'te`→`llegaste`, `pasa'te`→`pasaste`, `tíguere'`→`tigueres`, and `discoteka'`→`discotecas`, while the exact lyric surfaces remain in occurrence evidence.
- Stopped treating low-frequency routing abstentions as positive `core` evidence. The compact artist index now carries artist-local classification, and 26 unresolved playlist forms appear in Artist Extra as **Needs classification**; validated conjugations and derivations remain in Main.
- Guarded SpanishDict's malformed `usted` page, which embeds the plural `ustedes` analysis beside the exact singular entry and previously produced a duplicate card identity. The rebuilt monolith and compact index contain zero duplicate IDs.
- Verification: 23 SpanishDict guard cases, 42 focused normalization/evidence/tag tests, seven Node routing/offline tests, JavaScript syntax checks, JSON validation, exact offline manifest sizes/checksums, cache-version lockstep, and diff whitespace validation.

### 2026-08-11 — Prevent deterministic SpanishDict assignments from appearing model-authored

- Commit `1e6b70b6`; front-end cache `flashcards-v221` / `20260811c`.
- The JST provenance panel now identifies `spanishdict-auto` and other `*-auto` methods as “SpanishDict auto · no model call,” including the deterministic single-menu explanation.
- Added a historical-data guard while split examples are attached: if every evidenced assignment method for a sense is automatic, the card adopts that method and discards any stale prompt ID, run timestamp, or model-proposed flag. This corrects old Spanish Test Playlist rows without reclassifying or rebuilding their senses.
- Verification: focused executable regression for stale `sd-cop-v3` stamps, provenance/shortcut tests, JavaScript parsing, cache-version lockstep, and diff whitespace validation.

### 2026-08-11 — Restore JST provenance inspection and identify model-proposed definitions

- Commit `1e6b70b6`; front-end cache `flashcards-v220` / `20260811b`.
- Restored the owner-only Data & model info Study option and Command-I shortcut. The panel is created lazily if auth arrived after the card rendered, opens the card back directly, and lists deterministic/retained senses instead of disappearing whenever a card lacks model provenance.
- Added an owner-only `AI` pill beside definitions Gemini proposed outside SpanishDict's supplied menu. The deck builder now emits an aligned `sense_model_proposed` flag from authoritative `lexical-gap-fill-*` assignment methods; it does not guess from missing source fields or apply the marker to ordinary model-selected SpanishDict senses.
- Rebuilt the three live Artist split decks. The shipped indexes mark 160 Bad Bunny, 41 Rosalía, and 85 Young Miko senses, while all stamped model provenance remains limited to the accepted named `sd-lexical-v1-g31` and `sd-lexical-v2-g31` prompts.
- Verification: 17 focused Python tests, five focused Node tests, JavaScript syntax checks, rebuilt-deck flag/prompt audits, offline integrity checks, asset-version lockstep, and diff whitespace validation.

### 2026-08-09 — Split lexical WSD from tagging and prepare the Gemini 3.1 rerun

- Commit `1e6b70b6`; pipeline/data change only, so no front-end cache bump.
- Registered `sd-lexical-v1-g31` for `gemini-3.1-flash-lite`. The prompt now owns only menu selection and genuinely missing lexical glosses (including slang); proper nouns, usage tags, POS, vocal artifacts, and construction-only meanings stay in their separate evidence layers. Invalid output and excluded/construction-only material abstain instead of silently falling back to sense zero.
- Activated prompt-tier 20 as the Artist deck floor, leaving older `legacy-unknown` assignments archived but recoverable. Deterministic auto decisions no longer masquerade as Gemini provenance, and prompt/model-scoped checkpoints cannot resume across a different run identity.
- Retained occurrence-level legacy evidence only when the current menu/POS leaves one stable sense or two independent historical method families agree on the same still-valid sense. Retained 9,481 Bad Bunny, 1,374 Rosalía, and 1,694 Young Miko occurrences; Spanish Test Playlist needed none. Immutable claims, manifests, compatibility assignments, and audit reports were written without deleting source evidence.
- Made elision restoration the first linguistic transform at ledger ingestion while preserving the raw lyric surface. Bad Bunny, Rosalía, and Young Miko were rerun through artifact classification, routing, inventory and incremental POS; the later compatibility elision pass reduced all three by zero entries, proving downstream inputs were already restored.
- The final no-API Gemini plan contains exactly 5,202 word records / 16,303 unresolved examples: Bad Bunny 2,655 / 8,860, Rosalía 1,110 / 2,928, and Young Miko 1,437 / 4,515. All 5,202 resolve to existing menus; there are zero off-menu gap-fill prompts. No Gemini request was made.
- Verification: 33 focused evidence/prompt/deck tests, Python compilation, idempotent retention rerun, three exact prompt-plan dry runs, and a parallel 10,908-card Bad Bunny preview. The preview contains retained deterministic/consensus examples and no `legacy-unknown` prompt provenance.

### 2026-08-09 — Migrate Spanish artists and ship Bad Bunny from the evidence ledger

- Commit `1e6b70b6`; data/offline release only, so the already-active front-end cache remains `flashcards-v218` / `20260809b`.
- Migrated Bad Bunny, Rosalía, Young Miko, J Balvin, and Rels B to persisted segment/occurrence ledgers. Deterministic normalization, conservative vocal-artifact policy, elision merge, routing, inventory/example split, and POS layers can now be rerun independently without deleting prior evidence.
- Rebuilt Bad Bunny only up to the Gemini boundary, without an API call. Its basic policy excluded 13,275 occurrences (11,742 adlib claims, 41 echo claims, and 2,171 stutter claims, with overlaps), POS retagged 218 changed/new word groups, and the structured dry-run audit records 3,548 prospective prompt records versus 3,587 before migration. Of common records, 2,441 differ only in harmless menu ordering; 152 have meaningful menu/example-selection changes, 56 leave and 17 enter the queue, and no retained stable example changed POS.
- Preserved existing assignment decisions and reattached stable example/occurrence references where the new active example view still contains them. Fixed the SpanishDict prompt path so it preserves explicit sense IDs instead of regenerating collision-prone IDs from source order.
- Put ledger freshness hashes into the deck build contract and promoted ledger-built Bad Bunny, Rosalía, and Young Miko compact decks. Fixed the card registry's quadratic index rebuild: the previously stalled Bad Bunny assembly now completes in about 49 seconds.
- Verification: 35 focused evidence, identity, POS, deck-contract, and vocal-artifact tests; Python compilation; JSON validation of live master/deck/report files; refreshed offline sizes and SHA-256 hashes. No Gemini/API request was made.

### 2026-08-09 — Make active-set progress auditable and preserve exact lyric surfaces

- Commit `28a379f3`; front-end cache `flashcards-v217` / `20260809a`.
- Replaced the active set's aggregate statistics sheet with one expandable row per picked card. Each card shows its current-set result and exact in-session attempt times, saved whole-card and sense/expression totals, cross-mode history, SRS stage, and every latest timestamp the consolidated Progress sheet retains. The UI explicitly says that older per-answer timestamps do not exist in the current sheet contract.
- Added Ctrl+S for Study progress and Ctrl+P for the restricted Study preferences sheet. Owner audit shortcuts now use Ctrl+F for an immediate whole-card flag and Ctrl+Shift+F for the detailed menu; text inputs keep their normal keyboard behavior.
- Every flag route now closes at the send gesture and confirms the saved/queued type in an external toast. Failures use a distinct “Flag not sent” state instead of claiming success.
- Found that artist normalization already retained exact occurrence spellings and fed restored canonical text to POS/WSD, but step 8 dropped `surface` from assigned compact examples. Builder v13 now preserves non-canonical occurrence surfaces; 5,363 exact surfaces were backfilled into the shipped Bad Bunny example shard without adopting unrelated local rebuild differences. The frontend highlights that evidence first, treats straight/curly apostrophes equivalently, and no longer renders clitic/conjugation arrays as headword variant piles. Non-obvious counted elision pairs such as `para | pa'` and `nada | na'` remain available.
- Verification: 24 current Node tests pass; the same five pre-existing stale `ui-refinements` assertions remain and are documented above. All 29 focused Evidence Store/identity/surface Python tests pass; every JS module and service worker parses; changelog, offline manifest, and 18.9 MB compact Bad Bunny example JSON validate; offline sizes/checksums match; cache versions are in lockstep; `git diff --check` passes. GitHub search found no indexed overlapping issue.

### 2026-08-08 — Keep Learn New limited to genuinely unseen cards

- Commit `cfcf5b88`; front-end cache `flashcards-v216` / `20260808d`.
- Fixed the mismatch Josh found after shared Spanish progress shipped: setup counted only the current card identity, while final deck construction also removed cross-mode and same-lemma progress. A button could therefore advertise two new cards, filter both at launch, and trigger the old empty-selection fallback that silently opened the entire set as Study Again.
- Setup now uses the same current/cross-mode IDs and merged-lemma history as deck construction. A late progress refresh that empties a Learn New request reports completion and refreshes the set controls; only an explicit Study Again action can open the full set.
- Verification: two executable regressions covering same-artist, cross-mode, inherited-lemma, and review precedence plus the no-full-set invariant; 15 focused routing/offline/personalisation/Speech tests; syntax checks for every JavaScript module and service worker; valid changelog JSON; cache-version lockstep; `git diff --check`. The five already-recorded stale UI assertions remain unchanged. GitHub search found no indexed overlapping issue, and issue creation/update remains blocked because the GitHub CLI is unavailable.

### 2026-08-08 — Put Artist Evidence Store into the live deck path

- Commits `62148235` and `f65eb1ed`; front-end cache `flashcards-v215` / `20260808c`.
- Made Spanish Test Playlist the first shipped Evidence Store consumer: 980 stable lyric segments, 6,897 raw occurrences, immutable normalization/membership runs, and an active conservative vocal-artifact run with 832 adlib/stutter claims. The strict no-filter projection exactly matches the old 1,184-word / 3,941-token counter, and the basic policy currently produces the same vocabulary because all claimed normalized artifacts were already ignored by the legacy tokenizer.
- Froze the previously ignored SpanishDict menu and both assignment layers as hashed snapshots, linked all 2,170 assignment records to stable occurrences, and persisted card/sense registries so future lyric, lemma, WSD, provider, and language changes can coexist without renumbering learner progress.
- Rebuilt the 1,125-card playlist deck from the active profile, preserved reviewed Normal-mode personalisation in immutable run `2026-08-08_spanishdict_examples_v3_cross_mode_ids`, shared word progress across Speech/Lyrics, retained exact playlist Spotify track IDs, and added the playlist to the verified offline catalogue.
- Verification: 70 shared + 34 Artist Python tests; 13 personalisation/offline/Speech Node tests; JavaScript and Python syntax checks; strict neutral materialization parity; 2,170/2,170 occurrence-linked assignment audit; exact offline sizes/checksums; valid JSON; cache-version lockstep; `git diff --check`. The five pre-existing stale UI assertions are recorded above and were not treated as cutover regressions.

### 2026-08-03 — Benchmark word alignment and semantic exact-leaf validation

- Commit `9382d725`; no shipped deck or front-end change, so no cache bump.
- Froze and manually labelled a deterministic 60-row, polysemous, sense-stratified panel before predictions: 40 valid exact-leaf attachments and 20 invalid ones. The raw cue baseline was 66.7% precision.
- SimAlign with `bert-base-multilingual-cased` revision `3f076fdb1ab68d5b2880cb87a0886f315b8146f8` completed the panel on CPU in six seconds after load. Strict intersection reached 82.5% precision and IterMax 81.8%, confirming that word alignment fixes some wrong-token cues but cannot establish exact SpanishDict context.
- A separate temperature-zero `gemini-3.5-flash-lite` closed-set gate accepted 23 medium/high-confidence same-leaf candidates at 100% precision on the panel (57.5% recall of valid candidates); high-only accepted 20 at 100%. Requiring strict alignment as well retained 19 at the same precision, so mandatory alignment reduced useful recall without improving this panel's precision.
- Decision: advance only to a larger candidate-validation benchmark, not a corpus-wide run. Use literal matching for retrieval, semantic validation for exact-leaf publication, and alignment as optional audit/consensus evidence. Keep prominence separate because this subset is selection-biased. Require at least 95% exact-leaf precision on a second 200+ row POS/frequency/cue/alignment-stratified human review before scaling.
- Verification: 14 focused Speech evidence/alignment tests; repeatable scoring; exact confusion-matrix assertions; manual inspection of every semantic acceptance and miss; tracked report with real examples; `git diff --check`. Active and immutable decks remain unchanged.

### 2026-08-03 — Reject raw string matching as Spanish Speech WSD

- Commit `f3d8d3ba`; no shipped deck or front-end change, so no cache bump.
- Audited the completed 61,434,251-line zero-AI run: 302,551,875 surface/line matches, 49,554,992 unique-English-cue matches (16.4%), and 38,328 observed SpanishDict leaves. The scan itself completed correctly, but its cue matches are not valid sense counts.
- A deterministic 60-row polysemous sample contained at least 14 plainly wrong or unusable attachments, establishing a precision ceiling of about 77% before debatable context distinctions. Examples include `hacer` assigned “to think” because `think` translated `creo`, `mano` assigned “way” because it translated `forma`, and `daba` assigned “to press” because it translated `presionaba` elsewhere in the same sentence.
- Decision: do not build or activate a deck from these counts. Preserve the output as a large retrieval-candidate and benchmark bank. The next bounded experiment is pretrained word alignment (SimAlign or AWESOME-Align) followed by a separate full-translation/context semantic gate with abstention; require at least 95% exact-leaf precision before another corpus-wide run.
- Verification: ten focused Speech evidence tests; complete manifest/headline inspection; targeted high-frequency/concrete/verb examples; deterministic 60-row sample; tracked decision report with real data; `git diff --check`. The active deck and immutable historical runs remain unchanged.

### 2026-08-03 — Prepare the full zero-AI Spanish Speech audit

- Commit `e047506b`; no shipped deck or front-end change, so no cache bump.
- Added a resumable full-corpus runner for the new deterministic method: exact Spanish app-surface matching on the Spanish subtitle plus a literal English cue that belongs to exactly one SpanishDict leaf. Missing cues and conflicting cues abstain; there are no model, embedding, or API calls.
- The plan covers all 11,729 app cards: 9,412 of 9,453 surface forms have SpanishDict menus, comprising 89,914 stable leaves; 54,519 leaves have at least one automatically derived cue unique within their surface menu. Counts scan all 61,434,251 aligned lines rather than a sentence sample, while only bounded deterministic assignment/abstention examples are retained for audit.
- The runner prints percentage, throughput, ETA and live assignment coverage, checkpoints every two million lines, safely resumes after interruption, and refuses to overwrite an existing run without `--resume`. Its outputs remain under ignored `Data/Spanish/Intermediates/` and do not activate or modify an app deck.
- Verification: ten focused zero-AI and prior evidence tests; inventory-plan assertions; a 50,000-line real-corpus smoke run plus a successful 10,000-line resume at roughly 33,000–50,000 lines/second; approximately 16.2% conservative early coverage; `git diff --check`. The prior GitHub backlog search found only issue #18's narrower subtitle-MWE scope, so no duplicate work item was recorded.

### 2026-08-03 — Establish Spanish Speech vNext as a reversible candidate method

- Commit `38cf8de7`; front-end cache `flashcards-v180` / `20260803b`.
- Added `index.html?speech=vnext` as a first-class Spanish Speech route using the existing card shell, navigation, sense rows, SpanishDict links, and example presentation. The four-word pilot shows only selected important senses with Dominant/Common/Occasional labels and exact SpanishDict examples.
- Created immutable run `Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1` with a checksum manifest. It retains legacy whole-word IDs, every SpanishDict sense and stable leaf ID, raw audit counts, canonical examples, and explicit source references; only its selected senses render.
- Kept the existing `Data/Spanish/vocabulary.index.json` / `vocabulary.examples.json` route and `2026-08-03_spanishdict_examples_v2` candidate fully intact. Legacy percentages, personalised frames, and unaudited corpus candidates are referenced but not adopted as vNext truth. Pilot answers are explicitly barred from progress persistence.
- The route starts before migration, secrets, sync, progress, and offline-catalogue work, so its runtime reflects the intended compact architecture. A route-local versioned data fallback protects first load from an older service worker's cached config.
- Verification: deterministic exporter and manifest hash assertions; Python compilation; JavaScript syntax checks; 23 Speech-vNext/UI/offline/personalisation tests; valid config/deck/manifest JSON; cache-version lockstep; `git diff --check`. Per repository policy, the service-worker app was not browser-automated; a localhost-only, restricted-asset server was started for Josh's live review. GitHub search found no broader matching issue beyond #18's narrower OpenSubtitles-MWE scope.

### 2026-08-03 — Refine card grammar and set completion

- Commit `36022593`; front-end cache `flashcards-v179` / `20260803a`.
- Replaced the fixed empty lemma slot with one adaptive grammar block. Distinct lemmas share an identity row with POS, repeated lemmas let POS occupy that row, and active verb morphology wraps on its own row below.
- Stacked Expression source text above its English meaning with a subtle divider, preserving upright source text, italic English, adaptive sizing, and language-neutral behavior.
- Simplified set completion to the suggested continuation plus compact icon actions for Main menu and Redo set. Removed mistake-only review and duplicate no-mistakes copy; desktop Enter now triggers the available suggested continuation.
- Verification: syntax checks for changed JavaScript and the service worker; 19 UI/offline/personalisation tests plus the Google Apps Script v4 regression; valid changelog JSON; cache-version lockstep; `git diff --check`. Per repository policy, no browser preview was used against the service-worker app. GitHub backlog search found no indexed overlap; issue creation/update remains blocked because the GitHub CLI is unavailable.

### 2026-08-03 — Benchmark zero-training Spanish slot filling

- Commit `c28f2884`; no front-end or shipped-deck change, so no cache bump.
- Added `tool_8c_benchmark_masked_fillers` (inference-only slot benchmark) using pinned BETO revision `c4d86612f51b4f46759c8390d1798c2febe71b93`, with no training or fine-tuning. It ranks 3,096 single-token noun candidates from the first 10,000 Spanish entries for six reusable constructions and records exact OpenSubtitles construction fillers.
- Masked-slot ranking produced useful classes (`coche` rank 2 and `camión` 13 for `¿Quieres ver mi ___ nuevo?`; `tarjeta` 11 for `¿Me puedes pasar esa ___?`; `dinero` 1 for `comprarlo sin ___`). However, it also ranked `iglesia` 7 for the contrived breakfast sentence.
- Whole-sentence pseudo-log-likelihood achieved only 50% pairwise separation between the 12 human-accepted and four human-rejected pilot variants. Decision: use the pretrained model as a cheap proposal/ranking signal, combine it with grammatical and corpus constraints, and never treat it as the final naturalness or target-sense gate.
- Verification: pinned CPU rerun with offline model loading; 61,434,251-line OpenSubtitles scan; exact JSON metric assertions; Python compilation; `git diff --check`. GitHub backlog search found no overlapping issue, but issue creation/update is blocked because the GitHub CLI is unavailable in this environment.

### 2026-08-02 — Expand reviewed personalised Spanish practice

- Commit `a405048e`; front-end cache `flashcards-v177` / `20260802h`.
- Added a bounded, resumable offline expansion pipeline that selects exact-sense SpanishDict bases and common single-meaning noun reinforcements, then records generation, deterministic checks, a separate semantic gate, and explicit release decisions as distinct evidence layers.
- The pilot proposed 58 variants across 60 target senses. Structural checks retained 23, the model gate marked 16 high-confidence, and manual review retained 12 after rejecting four confident failures involving idiomatic prepositions, adverb scope, contrivance, and a malformed support construction. The stricter future gate now calls out those failure classes explicitly.
- Activated immutable run `2026-08-03_spanishdict_examples_v2` with 27 personalised frames total (15 earlier dual-audit frames plus 12 reviewed pilot frames), covering 10 new reinforcement words and 9 target senses. Runtime selection remains recent-mistake-only; all frames preserve their exact target sense and contribute nothing to sense distributions.
- Verification: Python compilation; exact active/run deck match; pilot metric assertions; offline file size/checksum integrity; all 17 focused personalisation, offline, and UI tests; `git diff --check`; refreshed local app loaded `20260802h` with no browser console errors.

### 2026-08-02 — Polish card tools and stabilize POS information

- Commit `0f4fcec7`; front-end cache `flashcards-v176` / `20260802g`; tracked by GitHub issue #55.
- Replaced the scaled favicon-proxy presentation for the SpanishDict and Reverso card-back links with local inline SVG marks, preserving the familiar identities without density-dependent raster softness or adding a new asset request.
- Restyled the Synonyms and Verb icons with the same translucent white tile, border, and white artwork used by the sense-progress trigger.
- Made the POS information popover a bounded momentum-scroll surface with contained overscroll. A post-scroll synthetic click can no longer dismiss it: only the explicit close button, backdrop, or Escape closes the dialog.
- Verification: syntax checks for the changed JavaScript modules and service worker; all 14 focused UI/offline tests including crisp vector controls, scroll containment, backdrop-only dismissal, and asset-version lockstep; valid developer-changelog JSON; `git diff --check`. Per repository policy, no browser preview was used against the service-worker app.

### 2026-08-02 — Build the SpanishDict-example Normal Mode candidate

- Commit `97a3e76e`; front-end cache `flashcards-v175` / `20260802f`.
- Activated immutable candidate run `2026-08-02_spanishdict_examples_v1`: the existing displayed senses and legacy percentages remain the provisional proxy, while 27,115 canonical SpanishDict examples now cover 25,978 of 26,566 displayed meanings through exact `sense_id` joins. The builder repaired 261 reversed bilingual pairs and left 588 unsupported meanings empty rather than assigning evidence to the wrong leaf.
- Embedded only the 15 generated variants accepted by both independent Iteration 3 audits. The app hides each template unless its reinforcement word has a dated mistake in the last seven days, then promotes and labels it as personalised practice; generated evidence never changes a distribution and study makes no model call.
- Added a reproducible candidate builder, compact tracked frame bank, immutable run manifest, offline checksums, and focused runtime/data tests. Verification: Python compilation; zero residual direction reversals under the Spanish/English detector; exact run/active and manifest hashes; valid JSON; JavaScript syntax; all 16 focused personalisation, offline, and UI tests; `git diff --check`.

### 2026-08-02 — Scale short italic submeanings with their rows

- Commit `0cf5501e`; front-end cache `flashcards-v174` / `20260802e`; follow-up to GitHub issue #53.
- Raised the adaptive italic context/submeaning sizes from 14/13/12/11px to 17/15/13/11.5px across the XL/L/M/S density tiers. Short supporting copy now benefits from available space alongside the already-adaptive main translation, while long context still steps down to protect wrapping and card height.
- Verification: syntax checks for every JavaScript module and the service worker; all 13 UI/offline tests including exact context-tier assertions and asset-version lockstep; valid developer-changelog JSON; `git diff --check`. Per repository policy, no browser preview was used against the service-worker app.

### 2026-08-02 — Advance setup past seen and skipped levels

- Commit `0c3cbbf3`; front-end cache `flashcards-v173` / `20260802d`; tracked by GitHub issue #54.
- Corrected level completion for new-set routing from Known to Seen, matching the stable-set dots and the established rule that Review is a separate level action. This removes the Level 1 / Set 10 trap when every set was encountered but some answers remain in Review.
- Main menu return now deliberately reruns first-actionable routing instead of restoring the level that owned the abandoned/completed set. Fully seen and marked-done levels are skipped; manual level selections remain sticky while setup is open. Artist Extra category landing and auto-start use the same routing contract.
- Applied localStorage progress synchronously before the first IndexedDB await, then retained the durable-store and remote reconciliation passes. A remote update reroutes only an automatic choice, not a learner's manual level choice.
- Verification: syntax checks for every JavaScript module and the service worker; all 13 UI/offline tests, including executable fully-seen-with-review and marked-done routing cases plus cached-progress ordering and asset-version lockstep; valid developer-changelog JSON; `git diff --check`. Per repository policy, no browser preview was used against the service-worker app.

### 2026-08-02 — Preserve Spanish Normal Mode assignment runs

- Commit `84383de7`; no front-end cache change (pipeline provenance only).
- Added an immutable, versioned Normal Mode run registry and froze the pre-rebuild SpanishDict menu, surface/lemma assignment mappings, and deterministically derived sense distributions as `2026-05-02_legacy_gemini`.
- Added `tool_6d_archive_normal_run.py`, which binds each future checkpoint to hashes and resource references and refuses to overwrite an existing run. The active-run pointer remains declarative so changing it cannot silently replace working layers.
- Recorded the inherited evidence limitation honestly: the original raw example layer was already absent, and 42,537 of 88,730 assigned example IDs remain present in the published deck. Verification covered Python compilation, exact source/archive hashes, all manifest hashes, JSON parsing, distribution totals, overwrite refusal, and `git diff --check`.

### 2026-08-02 — Keep Expression translations white

- Commit `1061bc55`; front-end cache `flashcards-v172` / `20260802c`; follow-up to GitHub issue #53.
- Added a deliberately stronger `.card-details .special-meaning-copy strong` rule so the later generic strong-text accent cannot override bilingual-row English with the active red artist colour. Spanish remains upright and English remains italic.
- Verification: bundled-Node syntax checks for the changed modules and service worker; all 12 UI/offline tests including a CSS-cascade regression assertion; valid developer-changelog JSON; `git diff --check`. Per repository policy, no browser preview was used against the service-worker app.

### 2026-08-02 — Give card rows distinct themes and adaptive type

- Commit `06eedf41`; front-end cache `flashcards-v171` / `20260802b`; tracked by GitHub issue #53.
- Split previously shared or fallback colours into explicit themes for proper nouns, auxiliaries, coordinating/subordinating conjunctions, particles, prefixes, suffixes, contractions, Expressions/MWEs, clitics, and unknown values while keeping true label aliases together.
- Reworked Expression and clitic copy into an inline-first bilingual layout: source text is upright, English is italic and uses the normal text colour, context is subordinate, and wrapping remains available for genuinely long rows.
- Added four content-density type tiers across singleton, grouped, remainder, Expression, and clitic rows so compact copy renders larger and long copy steps down before the existing wrap/clamp safeguards.
- Verification: bundled-Node syntax check for `js/flashcards.js`; 12 focused UI/offline tests including executable POS alias and type-tier checks plus asset-version lockstep; valid developer-changelog JSON; `git diff --check`. Per repository policy, no browser preview was used against the service-worker app.

### 2026-08-02 — Remove systemic startup and study stalls

- Commit `8bb74735`; front-end cache `flashcards-v170` / `20260802a`; follow-up on GitHub issue #5.
- Replaced the service worker's per-request scan across every retained download with one manifest-derived pathname index. Shell/runtime cache hits are now genuinely cache-first for their version instead of launching another background transfer and cache write for multi-megabyte deck JSON on every visit.
- Coalesced whole-progress IndexedDB/localStorage snapshots into an idle-time write with hide/page-exit flushing. Per-answer and per-item operations remain immediately durable in the existing IndexedDB sync queue, so the responsiveness improvement does not weaken offline recovery.
- Reused the prepared setup filter's stable baseline and restored joined artist sense trees only after deck construction actually mutates them. This removes redundant full-corpus sorting plus repeated `_base_meanings` cloning during setup while preserving Main/Extra and example-attachment isolation.
- Kept Spotify and the large card-modal module out of normal Speech startup, deferred the 1.4 MB conjugation table until its panel is opened, and skipped identical back-card DOM/layout, album-art, and direction-control writes. Updated all artist offline sizes/checksums after the latest shared-master/deck rebuild so integrity checks succeed again.
- Verification: syntax checks for every JavaScript module and the service worker; 11 focused Node tests covering exact offline size/checksum integrity, retained-cache routing, no cached-hit re-download, durable sync metadata, idle progress batching, setup reuse/dirty restoration, lazy startup modules, lazy conjugations, unchanged-card render reuse, authentication fail-open, morphology behavior, and asset-version lockstep; valid JSON; `git diff --check`. Repository policy leaves real-device Safari confirmation to Josh's installed app.

### 2026-08-01 — Simplify morphology person and tense pills

- Commit `2f0dc889`; front-end cache `flashcards-v169` / `20260801b`; follow-up on GitHub issue #52.
- Replaced technical person/plurality labels with Spanish subject labels: `Yo`, `Tú`, `Él(la)`, `Nosotros`, `Vosotros`, and `Ellos`. Ambiguous analyses keep every applicable subject together, such as `Yo/Él(la)`.
- Suppressed the `present` pill whenever it is the only named tense across the available analyses. It remains visible when another tense such as preterite is present and the contrast matters.
- Verification: bundled-Node syntax checks; focused executable tests for all six person mappings, ambiguous analysis ordering, lone-present suppression, contrasted-present retention, coupled alternatives, and asset-version lockstep; `git diff --check`.

### 2026-08-01 — Focus active-deck Study settings and compact morphology alternatives

- Commit `3f2db31b`; front-end cache `flashcards-v168` / `20260801a`; tracked by GitHub issue #52.
- Active-deck Study preferences now presents only the canonical Study content and a close control; the main-menu Settings entry still restores Account, Study, Offline & sync, and the gated App data tab.
- Removed the obsolete single-occurrence, proper-noun, noise, and English-loanword rows from Study because those routing categories belong to Artist Extra. Cognate sensitivity again has a discoverable explanation button with concise Loose/Default/Strict guidance.
- Morphology now renders one preferred analysis row, prioritizing indicative over imperative. Only changed pills carry a `+`; opening any one reveals every complete alternative analysis together so person, number, tense, and mood permutations remain coupled.
- Verification: bundled-Node syntax checks for changed JavaScript and the service worker; three focused UI regression tests including executable indicative/imperative ordering; four unaffected offline/service-worker tests; valid changelog JSON; cache-version lockstep; `git diff --check`. The full offline-manifest suite retains a pre-existing pipeline-owned size mismatch for `Artists/spanish/vocabulary_master.json`.

### 2026-07-31 — Make GitHub Issues the live backlog

- Commit `08fae949`; no front-end cache change (workflow documentation only).
- Established repository Issues as the single live backlog and the private Fluency TODO project as its phone-friendly dashboard, with automatic intake for every open issue.
- Documented duplicate-search, labeling, authorization, update, and closure rules in the shared agent instructions. Marked both Markdown TODO files as read-only migration history and linked their overlapping album-selection note to issue #9.
- Consolidated the future multi-artist/per-album selector into issue #9, expanded its acceptance criteria, and relabeled it as a large Codex-owned Lyrics/setup idea. Preserved 12 migrated open issues carrying `horizon: completed` for a separate state audit because that label is inconsistent with several issue titles and is not safe evidence that the work is done.
- Verification: GitHub issue search confirmed issue #9 and its labels; the linked Project and open-issue auto-add workflow were inspected in the signed-in GitHub session; `git diff --check` and focused documentation searches passed.

### 2026-07-31 — Separate settings by study, offline, and app-data purpose

- Commit `bda12254`; front-end cache `flashcards-v167` / `20260731m`.
- Made the card's Study preferences action open the canonical Study tab directly and routed the top-bar synchronization indicator to Offline & sync.
- Renamed the mixed Data surface to Offline & sync, moved freshness/version/changelog diagnostics into a separate JST-only App data tab, and removed the main settings Artists tab plus its obsolete modal-specific JavaScript and CSS.
- Added a TODO for a future combined multi-artist and per-album selector opened from artist selection under the new schema.
- Verification: bundled-Node syntax checks for every changed JavaScript module and the service worker; focused settings-routing/JST-gating/removal assertions; asset-version lockstep; valid changelog JSON; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-31 — Keep headwords white and reserve POS colour for separate lemmas

- Commit `9553fc33`; front-end cache `flashcards-v166` / `20260731l`.
- Front and back headwords remain white even when the displayed word is itself the lemma.
- Only a separately rendered citation lemma uses the contrast-adjusted active POS colour; it continues to update when the selected POS changes.
- Verification: bundled-Node syntax checks, changelog JSON parsing, cache-version and removed-state-class assertions, and `git diff --check`.

### 2026-07-31 — Separate surface-word and lemma colour hierarchy

- Commit `e0d74260`; front-end cache `flashcards-v165` / `20260731k`.
- A displayed surface word remains white whenever a distinct citation lemma is present; if the displayed word is itself the lemma, the headword receives the active POS colour.
- Separate front/back lemma text keeps the active POS identity and updates after a POS choice. Its colour is automatically mixed toward `--text-primary`, adapting contrast to the theme rather than relying on a fixed brightness.
- Verification: bundled-Node syntax checks, changelog JSON parsing, cache-version and word/lemma state assertions, and `git diff --check`.

### 2026-07-31 — Improve card hierarchy and multi-POS defaults

- Commit `b040b2ae`; front-end cache `flashcards-v164` / `20260731j`.
- Redistributed the active-set scrubber visually: the large centre markers have progressively wider separation, while smaller distant markers cluster progressively toward the ends.
- Example sentences/lyrics are upright and their translations remain italic. Removed the enclosing multi-POS chooser panel while retaining its explicit label and pills.
- Multi-POS cards now default to and list the POS with the greatest summed sense percentage first, with stable source order as the tie-breaker. A learner's explicit POS selection remains remembered on that card.
- Front/back headwords and citation lemmas now use the active POS colour and update with POS selection rather than inheriting the artist/language accent.
- Verification: bundled-Node syntax checks, changelog JSON parsing, cache-version and targeted behavior assertions, and `git diff --check`.

### 2026-07-31 — Clean up the active-set controls and morphology defaults

- Commit `77466b91`; front-end cache `flashcards-v163` / `20260731i`.
- Replaced the scrubber's accent connector with neutral grey and kept every numbered marker opaque at its own visible footprint so the connector cannot show through subdued markers.
- Made Study options visually icon-only with a 50px desktop target and a mobile target extending from the screen edge to the card. The radial keeps generous circular hit areas around cleaner icon-and-text actions, removes Shuffle, and labels its centre as the close action.
- Combined morphology person and number into one pill, uses `SING` / `PLURAL`, and suppresses the assumed indicative and affirmative defaults while keeping distinct analyses on separate rows.
- Verification: bundled-Node syntax checks, focused morphology grouping regression, changelog JSON parsing, cache-version and removed-control assertions, and `git diff --check`.

### 2026-07-31 — Enlarge the active-set rail and separate morphology alternatives

- Commit `37749f01`; front-end cache `flashcards-v162` / `20260731h`.
- Enlarged the active-set number markers and Study options button, and gave the mobile rail a modest height increase so its main navigation targets are easier to acquire by touch.
- Moved the scrubber connector onto a true behind-marker layer and composited marker fills against the card background, preventing the connector from showing through translucent numbered shapes.
- Morphology now compacts only ambiguous grammatical person with `/` (for example `1st/3rd`). Distinct number, tense, or mood analyses render as separate rows of pills on both card faces.
- Verification: JavaScript syntax checks, a focused morphology grouping regression case, changelog JSON parsing, cache-version assertions, and `git diff --check`. Browser preview was intentionally left to Josh's real app session because service-worker previews are unreliable in this repository.

### 2026-07-31 — Retry sync after reconnect warm-up

- Commit `90c70874`; front-end cache `flashcards-v160` / `20260731f`.
- Corrected the real-device reconnect race: the browser's `online` event can precede a usable iOS network route, but the queue attempted immediately, marked the first transient failure final, and scheduled no later drain. Manual Sync now was therefore the only recovery.
- Reconnect now waits 1.5 seconds. Transient failures remain Pending and retry automatically with bounded 2/4/8-second exponential delays; four failed attempts produce the final Sync failed state. Launch/foreground reset exhausted transient entries for a new bounded cycle, manual retry resets its attempt count, and auth-paused operations remain paused.
- Verification: five focused Node tests with retry/grace/reset policy assertions; bundled-Node syntax checks; valid changelog JSON; cache-version lockstep; `git diff --check`. Real-device reconnect remains the decisive end-to-end verification.

### 2026-07-31 — Fix the sync-queue browser parser error

- Commit `1309427a`; front-end cache `flashcards-v159` / `20260731e`.
- Reproduced the deployed failure in a real browser and read the decisive console error: `SyntaxError: Invalid regular expression flags` in `sync-queue.js`. The URL-sanitizing regex had double-escaped slashes, which Node's syntax check accepted but the browser parsed as an early regex terminator plus invalid flags; because `main.js` statically imports the queue, this aborted the entire application module graph.
- Corrected the literal to `/https?:\/\/\S+/g`. This is the root fix for the spinner, static/untappable login, and nonfunctional setup after fallback login; the earlier non-module auth fallback remains as defense in depth.
- Verification: deployed-browser console reproduction; five focused Node tests with a new assertion rejecting the malformed literal; bundled-Node syntax checks; valid changelog JSON; cache-version lockstep; `git diff --check`. Deployment will be rechecked in-browser after publishing.

### 2026-07-31 — Add a Safari-safe login fallback

- Commit `e7ca69d5`; front-end cache `flashcards-v158` / `20260731d`.
- After the early module handlers still proved untappable on the real iPhone, added direct classic-script handlers to Continue with initials, Explore as a guest, Continue, and Back. These controls now function without depending on the ES-module graph; normal module handlers remain additive when initialization succeeds.
- Restored centered mobile authentication and explicitly gave its action controls touch handling and stacking priority. Verified the deployed prior release served the expected `20260731c` HTML and all 17 startup modules returned HTTP 200, narrowing the remaining failure to Safari-side module evaluation rather than a missing deployment asset.
- Verification: five focused Node tests including presence of every inline fallback action; bundled-Node syntax checks; valid changelog JSON; cache-version lockstep; live HTTP status checks for deployed startup assets; `git diff --check`. Real-device confirmation remains required.

### 2026-07-31 — Initialize login before app boot

- Commit `6d7bddc6`; front-end cache `flashcards-v157` / `20260731c`.
- Identified why the prior fail-open change could still show an untappable modal: authentication markup is present in static HTML, while its click handlers were attached only inside `loadConfig().then(...)`. The 12-second watchdog could therefore reveal the modal after a stalled configuration request without ever initializing its controls.
- Authentication listeners and session restoration now run before artist/configuration loading. Showing auth forcibly hides the boot surface, adds an explicit auth-active guard, and raises the auth modal above every transient overlay; listener setup is idempotent.
- Verification: five focused Node tests, including listener/check-auth ordering before `resolveArtist`; bundled-Node syntax checks; valid changelog JSON; cache-version lockstep; `git diff --check`. No live iPhone/browser verification was available.

### 2026-07-31 — Make Home Screen startup fail open

- Commit `6afae1b5`; front-end cache `flashcards-v156` / `20260731b`.
- Moved authentication ahead of remote secrets, IndexedDB migration, sync initialization, and offline-catalogue loading. A signed-out user now gets an interactive login/guest surface immediately instead of the 12-second watchdog merely revealing an uninitialized page.
- Bounded the optional secrets, IndexedDB-open, and content-catalogue operations with short abort/timeouts. Sync and download initialization now continue in the background and report failures without blocking source rendering; an unavailable sync endpoint leaves local progress intact for later reconciliation.
- Verification: five focused Node tests, including authentication-before-optional-services and timeout assertions; bundled-Node syntax checks for all changed modules and the service worker; valid changelog JSON; asset-version lockstep; `git diff --check`. The in-app browser could not reach the workspace local server, so no live browser preview was completed.

### 2026-07-31 — Add offline-first downloads and durable synchronization

- Commit `a118d60d`; front-end cache `flashcards-v155` / `20260731a`.
- Added a shared IndexedDB database for queued operations, receipts, retained-download metadata, local progress state, and migrations. Legacy localStorage queue entries migrate forward; every operation carries account/type/timestamps/attempt/error/retry/idempotency metadata, ambiguous responses remain queued, and bounded drains run at launch, reconnect, foreground, authentication recovery, opportunistic writes, and explicit retry/Sync now.
- Added a checksummed, versioned content catalogue based on measured repository files plus a device-local Offline Content manager for Spanish, French, Bad Bunny, Rosalía, and Young Miko. Downloads use hidden staging caches and a completion marker before switching versions; interruption/failure metadata survives termination, updates preserve the prior verified version, and removal does not touch progress.
- Split service-worker shell caches from retained content caches, removed optional secrets from core precaching, kept a failed new install from replacing the working worker, staged worker activation behind an Update ready action, preferred retained local content while online, and preserved retained decks during shell cleanup.
- Added compact/full synchronization states, pending count, last-success time, safe error text, queue inspection/per-operation retry, download sizes/status/removal/cancellation, and mobile layouts in Settings → Data. Current manifests package whole sources because shard generation belongs to the pipeline/data owner; the manifest schema already supports multiple files and dependencies.
- Verification: bundled-Node syntax checks for all changed modules and the service worker; four focused Node tests covering exact manifest size/checksum integrity, staged/retained cache policy, durable retry/idempotency fields, and asset-version lockstep; valid JSON; `git diff --check`. No live browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Match Study options to the scrubber tiles

- Commit `ebdb0421`; front-end cache `flashcards-v153` / `20260729y`.
- Changed the icon-only Study options control from a 44px circle to the scrubber marker's 36×36px softly rounded tile with a 10px radius.
- Increased the gear from 22px to 26px and reduced padding from 10px to 5px, allowing the icon to occupy more of the control while retaining its accent tint and focus treatment.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; exact tile/icon/padding assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Colour scrubber results and reuse POS styling for morphology

- Commit `0e76784b`; front-end cache `flashcards-v152` / `20260729x`.
- Replaced circular scrubber markers with softly rounded 36×36px tiles and switched their bold 16px numbers to the normal reading/interface font. Unanswered stays neutral, correct-only is green, incorrect-only is red, and mixed attempts are amber.
- Kept current position independent from answer state: its accent outline, scale, and lens animation sit around the retained result-coloured fill. Each marker's result is also exposed through `data-result` and its accessible label.
- Morphology now reuses the actual POS-pill classes appropriate to each face (`card-pos` or `front-meaning-pos`) rather than parallel approximate styling. Font, size, weight, casing, padding, radius, fill, border, and colour therefore match the connected Verb pill exactly; only zero margin/nowrap are layout-specific.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; result-state, accessible-label, rounded-shape, interface-font, and shared-POS-class assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Add real mobile drag scrubbing

- Commit `97487314`; front-end cache `flashcards-v151` / `20260729w`.
- On viewports below 768px, pressing and dragging the connected numbered rail now changes the active card continuously at approximately one card per 24px. Right advances, left goes back, and indices clamp to the active set.
- Intermediate scrubbed cards suppress speech and centre their active marker immediately rather than queueing smooth-scroll animations. Releasing after movement suppresses the synthetic click, preventing a second unintended jump.
- Active drag brightens/thickens the rail and shortens marker transitions. Ordinary number taps remain available. Desktop retains its existing interaction and only uses the connected visual/lens animation.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; mobile-breakpoint, silent-intermediate, pointer-capture, and click-suppression assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Connect and animate the card scrubber

- Commit `532833b3`; front-end cache `flashcards-v150` / `20260729v`.
- Added a continuous accent-tinted rail behind the numbered card markers and reduced their spacing/basis so the control reads as one connected scrubber rather than isolated buttons.
- Increased markers to 36px and number text to bold 16px. The active position uses a 300ms expand-and-settle lens animation, while the nearest three positions progressively ease down in size and opacity through a spring-like transform curve.
- Added a reduced-motion override that removes the lens animation and collapses transition duration for users who request it.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; connected-rail/lens/reduced-motion assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Put desktop study controls in a row above the card

- Commit `17ec1b56`; front-end cache `flashcards-v149` / `20260729u`.
- Changed the desktop card container to a vertical layout with a real 44px controls row before the card. The numbered active-set scrubber and icon-only Study options button now share that row, followed by an explicit 8px gap and the card.
- Removed the desktop rail's absolute positioning/translation so the controls no longer behave as an overlay. Existing stacked-card hiding and scrubber interaction remain unchanged.
- The mobile breakpoint retains its prior absolute top-padding rail and card sizing.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; desktop/mobile positioning assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Use full morphology names in POS-matched pills

- Commit `f657d585`; front-end cache `flashcards-v148` / `20260729t`.
- Replaced compact grammar codes with full English labels: for example `1st/3rd singular`, `present`, and `subjunctive` instead of `1/3SG`, `PRES`, and `SUBJ`. Ambiguity remains local to the category that differs.
- Matched morphology tokens more closely to the POS controls: reading font, 11px size, 600 weight, 4×8px padding, fully rounded ends, 14% current-colour tint, and 38% current-colour border.
- Preserved the front's centred-below-Verb placement and the back's horizontal Verb attachment.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; abbreviation-removal assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Reserve lemma space and clarify multi-POS switching

- Commit `bad45d28`; front-end cache `flashcards-v147` / `20260729s`.
- Every card back now reserves a fixed 28px citation/lemma slot. Cards without a distinct lemma render an invisible placeholder, keeping the POS controls and sense area at a consistent vertical position across cards and tab changes.
- Multi-POS controls now sit inside a shared segmented track with an explicit “Choose part of speech” label. Inactive tabs remain clearly visible, while the active tab has a stronger POS-coloured fill, border, outline, and depth cue.
- Single-POS cards deliberately retain the simpler standalone pill and do not receive switch framing or an instructional label.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; reserved-slot and conditional-tab static assertions; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

### 2026-07-29 — Attach morphology directly to the verb pill

- Commit `6bc65c3c`; front-end cache `flashcards-v146` / `20260729r`.
- Removed morphology from the independent top-right front/back header position. On either kind of card front, the compact feature strip is now centred immediately beneath the relevant Verb pill as part of the same POS unit.
- On the back, the Verb tab or informational pill and morphology strip render as one horizontal unit. Morphology tokens use the same green colour, rounded outline, and tinted-fill language as the verb control; this covers both multi-POS and legacy/single-POS verb cards.
- Retained the compact person+number/tense/mood codes and per-category ambiguity representation without adding back the old header spacing.
- Verification: bundled-Node syntax checks for `flashcards.js`, `main.js`, and `service-worker.js`; valid changelog JSON; asset-version lockstep; absence of the former back-header morphology path; `git diff --check`. No browser preview was used because of the repository's service-worker policy.

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

## 2026-08-12 — Claude, cross-boundary edit to `js/` and `css/` (agreed with Josh)

Normally Claude stays on the engine side. Josh explicitly asked for these two.

**`js/flashcards.js`**
- `exampleProvenanceHTML()` — new. Renders where a corpus example came from. The
  OpenSubtitles `title_id` is an IMDb id (OPUS layout `es/{year}/{imdb}/{sub}.xml.gz`),
  so it links out directly; no local title table needed. Wired into
  `exampleSourceLabel` as the fallback when the example is not artist/SpanishDict.
- `buildProvenancePanelHTML()` — the Cmd-I panel now shows, per sense:
  the **confidence** (`gap`, plus a high/medium/low band) and **the actual
  sentences that sense was assigned to**, with their IMDb source and alignment
  score. Previously it named a model but never showed the evidence it decided on.

**`css/style.css`** — styles for `.prov-conf*` and `.prov-ex*`. The panel already
scrolled (absolute inset-0 + `overflow-y:auto`); only iOS momentum scrolling added.

Band cuts are absolute values transferred from the hand-labelled panel at
`Data/Spanish/Intermediates/wsd_sense_harness`, not quantiles of a run:
high = gap >= 0.035 (100% acceptable measured), medium >= 0.021 (91.9%).

Cache: `CACHE_NAME` -> flashcards-v224, `ASSET_VERSION` -> 20260812c,
`flashcards.js?v=` -> 20260812c in `js/main.js` and `index.html`.
