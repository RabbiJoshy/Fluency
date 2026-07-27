---
title: Google Sheets tab consolidation (4 → 2) + FlaggedWords hygiene
status: decided
language: cross-lang
created: 2026-07-27
updated: 2026-07-27
---

# Google Sheets consolidation

> **Cross-boundary.** The sheets are read/written by the live app (`js/auth.js`,
> `js/flashcards.js`) via `backend/GoogleAppsScript.js`. The tab-merge below is a
> schema migration that MUST ship in lockstep with those app changes + a one-time
> data migration. Claude decided the design; **Codex executes.** Do not restructure
> the live tabs ahead of the app code — it breaks progress save/load mid-session.

## Current state (4 tabs)

| Tab | Real purpose | Key columns |
|-----|--------------|-------------|
| `UserProgress` | Word progress — **normal mode** | User, Word, WordId, Language, Correct, Wrong, LastCorrect, LastWrong, LastSeen, SchemaVersion, SrsStage |
| `Lyrics` | Word progress — **lyric/artist mode** (tab is misnamed; it is NOT a lyrics cache) | same schema as UserProgress |
| `ItemProgress` | Per-item progress (sense / MWE / clitic) | User, ItemId, ItemType, ParentWordId, Correct, Wrong, LastCorrect, LastWrong, LastSeen, SchemaVersion, SrsStage |
| `FlaggedWords` | Audit flags | User, Word, WordId, Language, Correct, Wrong, LastCorrect, LastWrong |

App routing today (the thing that makes the mode split a *tab* split):
`js/auth.js` and `js/flashcards.js` pick the sheet with
`activeArtist ? 'Lyrics' : 'UserProgress'` (see auth.js ~340/341/460/523,
flashcards.js ~1259).

## Decision: 4 → 2

### 1. `Progress` — one unified progress tab
Absorbs `UserProgress` + `Lyrics` + `ItemProgress`. The mode split and the
grain split both become columns, not tabs:

- `ItemType`: `word` | `sense` | `mwe` | `clitic` (word rows replace UserProgress/Lyrics; the rest replace ItemProgress).
- `Mode` (or reuse `Language`/an artist key): normal vs artist — replaces the UserProgress-vs-Lyrics tab split. The lyric/non-lyric hygiene survives as this column.
- `ParentWordId`: links item rows to their word row (empty for `ItemType=word`).
- Shared columns already common to all three: Correct, Wrong, LastCorrect, LastWrong, LastSeen, SchemaVersion, SrsStage.
- Word-level status becomes a **derived rollup** of its item rows where useful, but the `word` row still carries card-level signal (whole-card SRS, level estimates) that items can't represent — so it stays a real row, not purely derived.

Why: UserProgress and Lyrics are the *same grain* differing only by mode; keeping
two tabs bought hygiene a column now provides for free. ItemProgress is a superset
schema already, so one discriminated tab is natural.

### 2. `FlaggedWords` — kept, cleaned
Different concern; stays its own tab. Cleaned per the triage below.

## Migration work (Codex)
- **Apps Script** (`GoogleAppsScript.js`): route `save`/`load`/`bulkSave`/
  `saveItem`/`loadItems`/`delete`/`deleteItems` to the single `Progress` tab with
  `ItemType`/`Mode` filters; keep a `SchemaVersion` bump; one-time copy of
  `UserProgress`+`Lyrics`+`ItemProgress` rows into `Progress` (stamp ItemType/Mode),
  then retire the old tabs (keep as backup tabs until verified).
- **App** (`js/auth.js`, `js/flashcards.js`): replace the
  `activeArtist ? 'Lyrics' : 'UserProgress'` routing with one `Progress` sheet +
  a mode filter. Preserve level-estimate load/save.
- **Backend tools** (`backend/sync_sheets.py`, `push_sheets.py`): update the
  `SHEETS` list; note `push_sheets` currently supports only `UserProgress`/`Lyrics`.
- **Rollback**: keep the old tabs (renamed `*_legacy`) until a full session confirms
  progress round-trips in both modes.

## FlaggedWords hygiene (Claude decided; apply below)

Triaged all 206 flags (2026-07-27) against the rebuilt Bad Bunny deck. Full backup:
`backend/local/FlaggedWords.archive.2026-07-27.json`. Reviewable CSV shared with Josh.

- **Keep live (19):** 14 STILL_VALID (flagged meaning still on the card — real work:
  trapero, tequi, manín, date, papeles, kronix, …) + 5 NEWEST (saco, mira, sube,
  mama, anda — never touched).
- **Remove (187), backed up:** 117 unverified pre-overhaul flags (plain-word, no
  checkable meaning) + 39 orphaned-word-survives (ID broke in the overhaul) + 20
  orphaned-gone + 7 resolved (guagua/trinket, charro, chilla, vine, franco — fixed) +
  4 junk (`es0_curl_test` + 3 empty wordIds; delete outright).

`push_sheets.py` does not currently support the `FlaggedWords` sheet, and the
Apps Script delete path was built for progress rows, so the safe apply is either
(a) delete the non-keep rows in-sheet using the CSV buckets, or (b) extend
`push_sheets` to cover FlaggedWords first (it already timestamped-backs-up remote
before deleting). Nothing is lost either way — the full 206 are archived.
