# Multi-agent collaboration — Claude ⇄ Codex

Two coding agents work this repo concurrently. This file defines who owns what and
how they stay out of each other's way. **Both agents read this** (AGENTS.md points
Codex here; CLAUDE.md points Claude here). If a task needs to cross the boundary,
that's fine — but do it by explicit agreement, not silently.

## Why the split exists

It is **not** a skill split — both agents are frontier coding models and either could
do either side. The split exists for two practical reasons only:
1. **Contention** — keep the two agents out of the same files (especially the shared
   front-end files that cause merge conflicts).
2. **Warm context** — each agent already has deep context in its side, so keeping to
   it avoids re-deriving state every session.
Tooling can override the direction: the pipeline needs the `.venv`, **Gemini API
keys**, and long-running jobs, so it lives with whichever agent's environment has them
(currently Claude).

## Ownership

### Codex — the product / app surface
- **Files:** `js/`, `css/`, `index.html`, `service-worker.js`, `config/dev_changelog.json`,
  `CODEX_CHANGES.md`, `TODO.md`.
- **Owns:** all UI/UX, artist-mode presentation, the multi-word-expression (MWE)
  overhaul **including its pipeline detection in `step_2a`** (it's a vertical Codex is
  mid-flight on — Claude stays out of MWE detection until Codex hands it back),
  per-sense progress (app + Google Apps Script), Extra-mode **presentation/grouping**,
  settings-menu cleanup.
- **Owns the cache-version bump** (`CACHE_NAME` + `ASSET_VERSION` + every `?v=` tag).
  Only Codex bumps these, because all the front-end files live on its side.
- **Backlog:** `TODO.md`.

### Claude — the pipeline / data engine
- **Files:** `pipeline/`, `Data/`, `Artists/` (data outputs), `docs/`, `TODO_PIPELINE.md`.
- **Owns:** pipeline correctness, sense-assignment quality, word routing
  (cognate / proper-noun / English / loanword / slang detection), scalability &
  parsimony (minimal Gemini), new-language onboarding (French, Dutch), new-artist
  onboarding, the normal-mode Spanish rerun, and tagging / per-morphology experiments.
- **Backlog:** `TODO_PIPELINE.md` (Claude edits only this; not `TODO.md`).

## The interface: the deck-JSON contract

The two sides meet only at the shape of the deck data the app consumes. When the
pipeline emits a **new or changed field** (group tags, word tags, per-sense keys, MWE
fields, etc.), Claude records it in `docs/pipeline_data_shapes.md` so Codex can render
it. Treat that doc as the API contract between engine and app.

## Coordination rules

1. **git:** `git pull --rebase` before every push; never force-push; don't both push in
   the same moment. On conflict in the other agent's file, stop and flag it — don't
   clobber.
2. **Cache versions:** only Codex bumps them (see above).
3. **TODO files:** each agent edits only its own (`TODO.md` = Codex, `TODO_PIPELINE.md`
   = Claude).
4. **Sense-ID stability (load-bearing):** sense IDs hash gloss text, so a pipeline
   rerun/menu change orphans them. Once **per-sense progress** ships, any Claude rerun
   MUST preserve sense IDs **or** emit a migration map — otherwise it wipes a user's
   per-sense progress. This is the one place the two tracks are genuinely coupled;
   agree the contract before running.
5. **User-visible data changes:** when a Claude data rebuild changes what the user sees,
   Claude notes it in `TODO_PIPELINE.md`; Codex folds it into `config/dev_changelog.json`
   (the user-facing changelog) since it owns that file.
