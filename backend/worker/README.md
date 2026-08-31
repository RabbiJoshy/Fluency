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

**Rollback** is putting the old URL back — the Apps Script deployment stays
live and untouched, so Sheets remains a working fallback. Progress written to
D1 after the swap won't be in the sheet, so re-dump with
`backend/worker/seed.py` in reverse if you ever need to go back for real.

## Watch it run

```bash
cd backend/worker && wrangler tail
```

## Free-tier headroom

At 10 users (~65k rows) this uses roughly 1.3% of D1's daily row-read
allowance and ~2 MB of the 5 GB storage. Workers allow 100k requests/day.

## Keeping the three key definitions in sync

`row_key` is the port of `progressRowKey()` (`GoogleAppsScript.js:326`). It is
written in three places that must agree, or upserts will insert where they
should update:

- `migrations/0001_init.sql` (documented)
- `src/index.js` → `rowKey()`
- `seed.py` → `row_key()`

## Not migrated

- **FlaggedWords** — stays in Sheets, proxied. The audit workflow is the
  spreadsheet UI.
- **Initials collisions** — `js/auth.js` still identifies users by 2–4 letters,
  so two users sharing initials share rows. Unchanged by this migration and
  worth fixing separately before more people join.
