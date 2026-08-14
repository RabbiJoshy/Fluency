#!/usr/bin/env python3
"""apply_surface_migration — stage the surface-ID migration into local Progress.

tool_migrate_surface_ids writes the re-keyed rows to
backend/local/surface_migration_progress.json, but push_sheets.py diffs against
backend/local/Progress.json. This applies one to the other so the existing,
dry-run-by-default, confirm-gated push path can do the actual upload — rather
than adding a second thing that writes to Sheets.

What it does to the local file:

  * removes the speech-mode word rows that were migrated (identified by the
    `_migrated_from` stamps, so nothing is guessed)
  * adds the re-keyed card rows under their surface IDs
  * adds one lemma item per old word|lemma card, preserving that history
  * leaves artist rows, meta rows, MWE and clitic rows completely alone

push_sheets will then show the old rows as deletions and the new ones as
upserts. That is the intended shape: the pre-migration state stays recoverable
from the timestamped backup and from git, not from dead rows in the sheet.

Usage:
    python3 backend/apply_surface_migration.py --dry-run
    python3 backend/apply_surface_migration.py
    python3 backend/push_sheets.py --sheet Progress      # review the diff
"""

import argparse
import json
import os
import shutil
from collections import Counter
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DIR = os.path.join(SCRIPT_DIR, 'local')
PROGRESS = os.path.join(LOCAL_DIR, 'Progress.json')
MIGRATION = os.path.join(LOCAL_DIR, 'surface_migration_progress.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--progress', default=PROGRESS)
    ap.add_argument('--migration', default=MIGRATION)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    with open(args.progress, encoding='utf-8') as f:
        payload = json.load(f)
    rows = payload['rows'] if isinstance(payload, dict) and 'rows' in payload else payload

    with open(args.migration, encoding='utf-8') as f:
        migration = json.load(f)
    cards = migration['cards']
    lemma_items = migration['lemmaItems']

    retired = {item['_migrated_from'] for item in lemma_items
               if item.get('_migrated_from')}
    kept = [r for r in rows if r.get('itemId') not in retired]
    removed = len(rows) - len(kept)

    clean_lemmas = [{k: v for k, v in item.items() if not k.startswith('_')}
                    for item in lemma_items]
    merged = kept + cards + clean_lemmas

    print('local Progress rows: %d' % len(rows))
    print('  retired (migrated away): %d' % removed)
    print('  card rows added:         %d' % len(cards))
    print('  lemma items added:       %d' % len(clean_lemmas))
    print('  result:                  %d rows' % len(merged))
    print('  by itemType: %s' % dict(Counter(r.get('itemType') for r in merged)))
    print('  by mode:     %s' % dict(Counter(r.get('mode') for r in merged)))

    if removed != len(retired):
        print('  NOTE: %d stamped old IDs but %d rows removed — some were already '
              'absent from the local pull' % (len(retired), removed))

    if args.dry_run:
        print('\n--dry-run: nothing written')
        return

    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')
    backup = os.path.join(LOCAL_DIR, 'Progress.pre_surface_migration.%s.json' % stamp)
    shutil.copy2(args.progress, backup)

    if isinstance(payload, dict) and 'rows' in payload:
        payload['rows'] = merged
        out = payload
    else:
        out = merged
    with open(args.progress, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)

    print('\nbacked up  -> %s' % backup)
    print('wrote      -> %s' % args.progress)
    print('\nNext: python3 backend/push_sheets.py --sheet Progress   (dry run)')


if __name__ == '__main__':
    main()
