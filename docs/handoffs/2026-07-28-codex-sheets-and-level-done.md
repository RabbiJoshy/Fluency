# Codex handoff — Sheets consolidation (4→2) + "Mark level done"

> Written by Claude (engine side) 2026-07-28. Both items are app-surface + sheet
> schema — Codex's domain. They share the sheet-meta mechanism, so build them
> together. Full design context: `docs/design/sheets_consolidation.md`.

## Item 1 — Google Sheets tab consolidation (4 → 2)

**Why:** `UserProgress` (normal mode) and `Lyrics` (lyric/artist mode) are the
same grain differing only by mode; `ItemProgress` is a superset schema. Three
progress tabs where one discriminated tab suffices.

**Target schema — one `Progress` tab:**
- `ItemType`: `word` | `sense` | `mwe` | `clitic`
- `Mode` (or reuse an artist/`Language` key): normal vs artist — replaces the
  `UserProgress`-vs-`Lyrics` split
- `ParentWordId`: links item rows to their word row (empty for `word`)
- Shared: User, WordId/ItemId, Correct, Wrong, LastCorrect, LastWrong, LastSeen,
  SchemaVersion, SrsStage
- Keep `FlaggedWords` as its own tab.

**Call sites that hard-code the mode→tab split (replace with one tab + mode filter):**
- `js/auth.js` ~340/341, ~460, ~523: `activeArtist ? 'Lyrics' : 'UserProgress'`
- `js/flashcards.js` ~1259: `sheet: activeArtist ? 'Lyrics' : 'UserProgress'`
- `backend/GoogleAppsScript.js`: route `save`/`load`/`bulkSave`/`saveItem`/
  `loadItems`/`delete`/`deleteItems` to `Progress` with ItemType/Mode filters;
  bump `SchemaVersion`.
- `backend/sync_sheets.py` `SHEETS` list, `backend/push_sheets.py`
  `SHEETS`/`PUSHABLE_SHEETS`.

**Migration:** one-time copy of the three tabs' rows into `Progress` (stamp
ItemType/Mode), keep old tabs renamed `*_legacy` until a full session confirms
progress round-trips in both modes, then retire them. Preserve the level-estimate
load/save path (see Item 2 — it rides the same meta mechanism).

## Item 2 — "Mark level done" toggle

**What Josh wants:** he already knows Bad Bunny levels 1–N and doesn't want to
grind them just to advance the app's *suggestions*. A per-level switch under the
set UI that, when on, **excludes that level from next-set suggestions only** —
real per-card progress and correct/incorrect history keep recording exactly as
now. Reversible (toggle off → level returns to suggestions). Marking 1–9 done →
the app's "go to next set" starts at level 10.

**Key invariant:** "done" is a *suggestion-routing* flag, NOT fake progress. Do
not synthesize per-card Known states — only suppress the level from the
next-set/advance logic.

**Mirror the level-estimate machinery** (it already persists a per-(user,language)
scalar to the sheet):
- `js/estimation.js`: `useEstimatedLevel()` (~442), `levelEstimates[selectedLanguage]=level` (~444),
  `saveLevelEstimateToSheet(level)` (~445), `selectLevelForRank(rank)` (~462).
- Add a sibling: `markedDoneLevels[scope] = Set<levelId>` persisted the same way
  (a meta row in the consolidated `Progress` tab — this is why it pairs with
  Item 1). Scope = (user, mode/artist, language) so lyric-mode Bad Bunny dones
  don't leak into speech mode or other languages.

**Where the "next set" logic must consult it:**
- The advance/next-set selection (in `js/vocab.js` set-selection + `js/estimation.js`
  `selectLevelForRank`/level-advance): when choosing the level to suggest, skip
  any level in `markedDoneLevels[scope]`, advancing to the lowest not-done level.
- Resume / "Welcome back" (`js/vocab.js` `renderResumeLastSetCard`): a marked-done
  level should not be re-suggested as the next set, but an *explicitly chosen*
  marked-done level still opens normally (the flag only gates suggestions).

**UI:** a small on/off control on the set/level header (near `renderLevelSelector`
in `js/ui.js`), labelled so it's clear it only affects suggestions ("Mark known —
skip in suggestions"). Per-level, toggleable, reflects persisted state on load.

**Scope guard:** because Josh is about to run speech mode, other languages, and
more artists, the done-set MUST be scoped per (mode, artist, language) — never a
global level list. Verify a Bad Bunny "level 9 done" does not affect a fresh
artist or speech mode.
