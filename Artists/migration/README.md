# Progress Migration

When vocabulary IDs change (hex length, hash algorithm, etc.), Google Sheets progress data needs to be migrated to match.

## How to migrate

1. **Export progress from Google Sheets** — copy-paste the Lyrics tab (including header) into `progress_input.txt` as tab-separated text.

2. **Run the migration script:**
   ```bash
   .venv/bin/python3 Artists/migration/migrate_progress.py
   ```

3. **Import back to Google Sheets** — open `progress_migrated.csv` and paste into the Lyrics tab, replacing all existing rows.

## What the script does

- Reads `progress_input.txt` (tab-separated, from Sheets)
- Maps old IDs to new IDs using the master vocabulary
- Handles two old ID formats:
  - **Rank-based** (just a number like `120`) — maps via array position in the pre-migration Bad Bunny vocab
  - **Hex-based** (`es1XXXX`, 4-char hex) — maps via the old vocab files stored in git
- Merges duplicate entries (same word from different eras): sums correct/wrong, keeps latest timestamps
- Outputs `progress_migrated.csv` and `progress_migrated.txt`

## If you change the ID format again

1. **Before making the change**, note the current git commit hash — this is your "last known good" ref for mapping old IDs.

2. **Update `OLD_VOCAB_GIT_REF`** in `migrate_progress.py` to that commit hash. This is how the script finds the old vocab files to map old IDs to word|lemma pairs.

3. **Update the ID parsing logic** in the script if the format of the WordId column changed (e.g., different prefix, different hex length).

4. **Export, run, import** as above.

## Files

| File | Purpose |
|------|---------|
| `progress_input.txt` | Raw export from Google Sheets (you provide this) |
| `progress_migrated.csv` | Migrated output ready to paste into Sheets |
| `progress_migrated.txt` | Same data, tab-separated |
| `migrate_progress.py` | The migration script |

## History

- **2026-04-05**: Migrated from 4-char hex IDs to 6-char master vocab IDs. Git ref for old format: `e80e680`. Also migrated rank-based IDs from the pre-hex era.
