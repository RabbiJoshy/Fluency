# Fluency — Codex Instructions

**Read `COLLABORATION.md` first.** Two agents work this repo concurrently. Codex owns the
**product/app surface** (`js/`, `css/`, `index.html`, `service-worker.js`,
`config/dev_changelog.json`, `CODEX_CHANGES.md`, `TODO.md`) and the cache-version bumps;
Claude owns the **pipeline/data engine** (`pipeline/`, `Data/`, `Artists/`, `docs/`,
`TODO_PIPELINE.md`). Stay on Codex's side unless a cross-boundary task is explicitly agreed.

Read `CLAUDE.md` next. It is the repository-wide architecture and workflow reference even when the active coding agent is Codex. Then read the nearest scoped `CLAUDE.md` for the files being changed (`js/CLAUDE.md`, `pipeline/CLAUDE.md`, `Artists/CLAUDE.md`, and so on).

Before continuing work previously touched by Codex, read `CODEX_CHANGES.md`. After every completed Codex task:

1. Prepend a concise entry under **Codex task history** with the date, final commit hash, behavior changed, important decisions, verification, and cache version when applicable.
2. Keep unresolved design notes under **Open handoff notes** until they are implemented or deliberately rejected.
3. Continue to follow the normal project requirements in `CLAUDE.md`: update `config/dev_changelog.json` for user-visible/data changes, bump front-end cache versions in lockstep, pull with rebase before pushing, and never force-push.

`CODEX_CHANGES.md` is a cross-model handoff, not a replacement for git, `TODO.md`, or the developer changelog.
