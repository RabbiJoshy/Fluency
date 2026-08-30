# Fluency API — Cloudflare Worker + D1

Replaces `backend/GoogleAppsScript.js` for progress and song sets. Same JSON
protocol, so `js/auth.js` and `js/sync-queue.js` are untouched — the only app
change is the URL in `backend/secrets.json`.

Flag writes (`sheet: 'FlaggedWords'`) are **proxied to the Apps Script
deployment**, so the FlaggedWords audit tab keeps working exactly as now.

## Why

The Apps Script read the **entire sheet** on every request and filtered in
JavaScript (`GoogleAppsScript.js:503`), so each user paid for every other
user's rows — cost grew with total rows, not with your own. Writes were
read-modify-write with no `LockService` outside the migration paths
(`upsertProgressRow`, `GoogleAppsScript.js:355`), so concurrent saves could
lose updates.

Measured on the seeded data, the D1 query cost is flat:

| Rows in table | `load` for one user | Upsert key lookup |
|---|---|---|
| 6,561 (1 user) | **3.07 ms** | 0.004 ms |
| 65,610 (10 users) | **3.11 ms** | 0.004 ms |

`idx_progress_user_type` turns the load into a range scan over one user's rows
(`EXPLAIN QUERY PLAN` reports `SEARCH ... USING INDEX`, not `SCAN`), so a tenth
user costs the first nine nothing.

**On the Apps Script side, only one figure is verified:** a `GET` health check
that touches no data at all takes **~1.5 s**. Actual `POST` latency could not
be measured from the command line — Google returns an HTML interstitial to
curl rather than running the script — so treat any figure for a real `load`
as unmeasured. The argument for migrating rests on the full-scan and
missing-lock behaviour in the source, both of which are plain to read, not on
a latency benchmark.

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

`smoke_test.sh` runs the read-only actions the client uses. Nothing is written,
and the app still points at Sheets while you run it:

```bash
backend/worker/smoke_test.sh "https://fluency-api.<subdomain>.workers.dev" JST
```

Note that you **cannot** diff this against the Apps Script backend from the
command line — Google serves curl an HTML interstitial instead of running the
script on POST. So check the Worker's output against the counts seeded from the
dump instead. For user `JST` it should report:

| Call | Expected |
|---|---|
| `load` (all modes) | 3,247 progress · 17 meta |
| `load` mode=normal | 459 progress |
| `load` mode=artist | 2,788 progress |
| `loadItems` | 3,297 items |

Regenerate these any time from the seeded database rather than trusting the
table above:

```bash
python3 backend/worker/seed.py backend/local/Progress.json --report
```

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
