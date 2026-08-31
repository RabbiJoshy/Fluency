# Fluency API — Cloudflare Worker + D1

**Live:** https://fluency-api.rabbijoshy.workers.dev

Replaces `backend/GoogleAppsScript.js` for progress and song sets. Same JSON
protocol, so `js/auth.js` and `js/sync-queue.js` are untouched — the only app
change is the URL in `backend/secrets.json`.

Flag writes (`sheet: 'FlaggedWords'`) are **proxied to the Apps Script
deployment**, so the FlaggedWords audit tab keeps working exactly as now.

## Why

The Apps Script read the **entire sheet** on every request and filtered in
JavaScript (`GoogleAppsScript.js:503`), so each user paid for every other
user's rows. Writes were read-modify-write with no `LockService` outside the
migration paths (`upsertProgressRow`, `GoogleAppsScript.js:355`), so
concurrent saves could lose updates — five duplicate rows in the live sheet,
three with conflicting content, are that bug's fingerprint.

Measured against the live Apps Script, same data, same actions:

| Call | Apps Script | Worker (live) | Speedup |
|---|---|---|---|
| `load` JST (6,144 cards) | 4,857 ms | 892 ms | 5x |
| same, gzip as a browser sends | — | **265 ms**, 129 KB | ~18x |
| `load` JST normal | 4,917 ms | 247 ms | 20x |
| `load` JSTA | 4,486 ms | 95 ms | 47x |
| `loadItems` JST (3,338) | 4,210 ms | 173 ms | 24x |
| `capabilities` (no data) | 1,667 ms | 68 ms | 25x |

The uncompressed `load` figure is dominated by shipping 1.4 MB; browsers send
`Accept-Encoding: gzip` and get 129 KB. On the database itself the query is
~3 ms and stays ~3 ms at ten users' worth of rows (`EXPLAIN QUERY PLAN` shows
`SEARCH ... USING INDEX`, not `SCAN`), so the cost no longer grows with the
number of people using the app.

## Prerequisites

`wrangler` needs Node, which is **not currently installed on this machine**:

```bash
brew install node
```

Then a free Cloudflare account, and:

```bash
npm install -g wrangler
wrangler login
```

## Deploy

**1. Create the database** and paste the printed `database_id` into `wrangler.toml`:

```bash
cd backend/worker && wrangler d1 create fluency
```

**2. Apply the schema:**

```bash
cd backend/worker && wrangler d1 migrations apply fluency --remote
```

**3. Seed from the existing Sheets dump.** Refresh it first if it's stale
(`python3 backend/sync_sheets.py`), then:

```bash
python3 backend/worker/seed.py backend/local/Progress.json > /tmp/seed.sql
```

```bash
cd backend/worker && wrangler d1 execute fluency --remote --file=/tmp/seed.sql
```

**4. Point flag traffic at the existing Apps Script** (paste the `/exec` URL
from `backend/secrets.json` when prompted):

```bash
cd backend/worker && wrangler secret put SHEETS_URL
```

**5. Deploy:**

```bash
cd backend/worker && wrangler deploy
```

## Verify before switching

`smoke_test.sh` runs the read-only actions the client uses. Nothing is written:

```bash
backend/worker/smoke_test.sh https://fluency-api.rabbijoshy.workers.dev JST
```

Expected for `JST`: 6,144 progress, 17 meta, 3,338 items. For `JSTA`: 24
progress, 77 items, 1 song set. Regenerate these from the dump with
`python3 backend/worker/seed.py backend/local/Progress.json --report`.

The Worker was diffed against the live Apps Script by comparing the keyed maps
`js/auth.js` actually builds. Every action matches except one card, `chavos`,
where the sheet holds two conflicting duplicates: Sheets returns the older
row, this backend returns the newer one. That is deliberate — see the dedupe
note in `seed.py`.

**Scripting against it:** Cloudflare's bot check returns `403 error code 1010`
to requests with a non-browser `User-Agent` (Python's `urllib` default is
blocked; curl's is not). Send a normal browser UA from any script. Browsers
are unaffected.

## Swap the pointer

Change `googleScriptUrl` in `backend/secrets.json` to the Worker URL, commit,
and push. GitHub Pages redeploys and clients pick it up.

## Rollback

The two stores share a schema and a wire format, so moving data back is
mechanical. Dump D1 through the normal sync tool, then push it into the sheet:

```bash
.venv/bin/python3 backend/sync_sheets.py --sheet Progress --url https://fluency-api.rabbijoshy.workers.dev
```

```bash
.venv/bin/python3 backend/push_sheets.py --sheet Progress
```

The second command is a **dry run** and prints the changeset; add `--confirm`
to apply it. `--url` (or `FLUENCY_BACKEND_URL`) overrides `secrets.json`, which
is what lets you read one backend and write the other after the swap.

Then put the old URL back in `secrets.json`. The Apps Script deployment stays
live and untouched throughout, so it remains a working fallback.

Verified end to end: dumping D1 this way produces headers identical to a Sheets
dump, and the only differing rows are the six this migration deliberately drops
(five duplicate keys, one row with no user) plus the `chavos` dedupe.

The one thing a rollback does overwrite is edits made **directly in the
spreadsheet** after the swap — the push takes D1 as the source of truth for
the Progress tab. Flags are unaffected; they live only in Sheets.

## Watch it run

```bash
cd backend/worker && wrangler tail
```

## Free-tier headroom

At 10 users (~65k rows) this uses roughly 1.3% of D1's daily row-read
allowance and ~2 MB of the 5 GB storage. Workers allow 100k requests/day.

## Schema

Progress is event-sourced. Three tables replace what the single spreadsheet-shaped
`progress` table used to do:

| Table | Role |
|---|---|
| `review_events` | Immutable facts. The system of record. Append-only. |
| `item_state` | Derived read model. Rebuildable from events. Carries `due_at`. |
| `user_meta` | Settings that were never progress (level-done, level estimates). |
| `flags` | Card-quality reports. The audit sheet is an export now, not the store. |

**Mode is a column.** It used to be the third character of every id — `es0…`
speech, `es1…` lyrics — which is why the old client had `normalizeMode()`
reading `id[2]` and `crossModeProgressId()` flipping that character to find the
same word in the other mode. Storage now keeps `lang_code`, `mode` and a bare
`item_id`; the composite id is reconstructed only at the wire boundary, so the
client sees exactly what it always saw. Cross-mode lookup is a query, not a
string transform.

**`idempotency_key` is UNIQUE** and events insert with `OR IGNORE`. The sync
queue already generates that key, so a replayed write is a no-op at the
database level — the same failure class that silently dropped answers when a
transient 403 parked the queue.

**`due_at` is materialised.** The client still loads everything and decides
locally, but `{"action":"loadDue","user":"JST"}` is the query that replaces
walking every card in JavaScript once the scheduler is built.

### What the backfill could and could not recover

The old table held counters and only the *last* correct/wrong timestamps — the
individual answers were never recorded. So the backfill writes at most two seed
events per item (`origin='synthetic'`) rather than inventing ~11k timestamps
that would be fabricated precision. Pre-cutover totals live in `item_state`;
`review_events` is complete from the cutover forward.

`progress` is deliberately left in place as a frozen snapshot. Nothing writes
to it any more.

### Verified at cutover

Every read path returned byte-identical results to the previous backend on the
same data — `load` (all modes, per mode, and the legacy `UserProgress` /
`Lyrics` sheet names), `loadItems`, `loadSongSets`, meta and level estimates.
Writes were checked for event derivation, replay idempotency (a repeated
`idempotencyKey` produces no second event), and correct expansion when the
offline queue coalesces several answers into one write.

## Triaging flags

```bash
python3 backend/worker/flags.py --status open
```

## Not migrated

- **FlaggedWords** — stays in Sheets, proxied. The audit workflow is the
  spreadsheet UI.
- **Initials collisions** — `js/auth.js` still identifies users by 2–4 letters,
  so two users sharing initials share rows. Unchanged by this migration and
  worth fixing separately before more people join.
