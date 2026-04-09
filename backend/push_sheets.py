#!/usr/bin/env python3
"""Push local JSON progress data back to Google Sheets.

Compares local JSON against a fresh pull from Sheets and pushes only the
differences. Dry-run by default — requires --confirm AND interactive "yes"
to actually modify anything.

Usage:
    python3 backend/push_sheets.py                          # dry-run both sheets
    python3 backend/push_sheets.py --sheet UserProgress     # dry-run one sheet
    python3 backend/push_sheets.py --confirm                # push changes (with prompt)
    python3 backend/push_sheets.py --replace --confirm      # also delete remote-only rows
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = os.path.join(SCRIPT_DIR, 'secrets.json')
LOCAL_DIR = os.path.join(SCRIPT_DIR, 'local')
BACKUP_DIR = os.path.join(LOCAL_DIR, 'backups')
SHEETS = ['UserProgress', 'Lyrics']
HEADER_KEYS = ['user', 'word', 'wordId', 'language', 'correct', 'wrong', 'lastCorrect', 'lastWrong']


def load_script_url():
    try:
        with open(SECRETS_PATH) as f:
            secrets = json.load(f)
        url = secrets.get('googleScriptUrl')
        if not url:
            print(f"Error: 'googleScriptUrl' not found in {SECRETS_PATH}")
            sys.exit(1)
        return url
    except FileNotFoundError:
        print(f"Error: {SECRETS_PATH} not found.")
        sys.exit(1)


def post_json(script_url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        script_url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"Error: {e}")
        sys.exit(1)


def load_local(sheet_name):
    path = os.path.join(LOCAL_DIR, f'{sheet_name}.json')
    if not os.path.exists(path):
        print(f"Error: {path} not found. Run sync_sheets.py first.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def dump_remote(script_url, sheet_name):
    body = post_json(script_url, {'action': 'dump', 'sheet': sheet_name})
    if not body.get('success'):
        print(f"API error: {body.get('message')}")
        sys.exit(1)
    rows = []
    for raw_row in body['data']['rows']:
        obj = {}
        for i, val in enumerate(raw_row):
            key = HEADER_KEYS[i] if i < len(HEADER_KEYS) else f'col{i}'
            obj[key] = val
        rows.append(obj)
    return rows


def backup_remote(sheet_name, remote_rows):
    """Save a timestamped backup of the remote state before pushing."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(BACKUP_DIR, f'{sheet_name}_{ts}.json')
    data = {
        'backed_up_at': datetime.utcnow().isoformat() + 'Z',
        'sheet': sheet_name,
        'row_count': len(remote_rows),
        'rows': remote_rows,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Backed up remote state → {path}")
    return path


def row_key(row):
    return f"{row.get('user', '')}|{row.get('wordId', '')}"


def rows_differ(local_row, remote_row):
    for k in HEADER_KEYS:
        lv = local_row.get(k, '')
        rv = remote_row.get(k, '')
        if str(lv) != str(rv):
            return True
    return False


def compute_changeset(local_rows, remote_rows):
    remote_map = {row_key(r): r for r in remote_rows}
    local_map = {row_key(r): r for r in local_rows}

    to_upsert = []
    for key, local_row in local_map.items():
        remote_row = remote_map.get(key)
        if remote_row is None or rows_differ(local_row, remote_row):
            to_upsert.append(local_row)

    to_delete = []
    for key in remote_map:
        if key not in local_map:
            to_delete.append(remote_map[key])

    return to_upsert, to_delete


def print_changeset(sheet_name, to_upsert, to_delete, remote_count, local_count):
    print(f"\n  {sheet_name}: {remote_count} remote rows, {local_count} local rows")
    if to_upsert:
        print(f"    Upsert {len(to_upsert)} rows:")
        for r in to_upsert[:10]:
            print(f"      {r.get('user', '?')}/{r.get('wordId', '?')} — {r.get('word', '?')}"
                  f" (correct={r.get('correct', 0)}, wrong={r.get('wrong', 0)})")
        if len(to_upsert) > 10:
            print(f"      ... and {len(to_upsert) - 10} more")
    if to_delete:
        print(f"    Delete {len(to_delete)} rows:")
        for r in to_delete[:10]:
            print(f"      {r.get('user', '?')}/{r.get('wordId', '?')} — {r.get('word', '?')}")
        if len(to_delete) > 10:
            print(f"      ... and {len(to_delete) - 10} more")
    if not to_upsert and not to_delete:
        print(f"    No changes")


def main():
    parser = argparse.ArgumentParser(description='Push local JSON data back to Google Sheets')
    parser.add_argument('--sheet', choices=SHEETS, help='Push only this sheet (default: both)')
    parser.add_argument('--confirm', action='store_true', help='Actually push (default: dry-run)')
    parser.add_argument('--replace', action='store_true',
                        help='Replace entire sheet with local data (deletes remote-only rows)')
    args = parser.parse_args()

    sheets = [args.sheet] if args.sheet else SHEETS
    script_url = load_script_url()

    all_changesets = {}

    for sheet_name in sheets:
        local_data = load_local(sheet_name)
        local_rows = local_data.get('rows', [])

        print(f"Fetching current {sheet_name} from Sheets...")
        remote_rows = dump_remote(script_url, sheet_name)

        to_upsert, to_delete = compute_changeset(local_rows, remote_rows)

        if not args.replace:
            to_delete = []

        print_changeset(sheet_name, to_upsert, to_delete, len(remote_rows), len(local_rows))
        all_changesets[sheet_name] = (to_upsert, to_delete, remote_rows)

    # Check if there's anything to do
    total_changes = sum(len(u) + len(d) for u, d, _ in all_changesets.values())

    if total_changes == 0:
        print("\nNothing to push.")
        return

    if not args.confirm:
        print("\nDry run — no changes made. Use --confirm to push.")
        return

    # Interactive confirmation gate
    print(f"\n{'='*60}")
    print(f"  ABOUT TO MODIFY GOOGLE SHEETS")
    print(f"  Total: {total_changes} row(s) will be changed")
    print(f"{'='*60}")
    answer = input("\n  Type 'yes' to proceed: ").strip().lower()
    if answer != 'yes':
        print("  Aborted.")
        return

    # Backup remote state before pushing
    for sheet_name, (to_upsert, to_delete, remote_rows) in all_changesets.items():
        if not to_upsert and not to_delete:
            continue

        backup_remote(sheet_name, remote_rows)

        if to_upsert:
            print(f"  Pushing {len(to_upsert)} rows to {sheet_name}...")
            result = post_json(script_url, {
                'action': 'bulkSave',
                'sheet': sheet_name,
                'rows': to_upsert
            })
            if result.get('success'):
                print(f"    {result['message']}")
            else:
                print(f"    Error: {result.get('message')}")

        if to_delete:
            print(f"  Deleting {len(to_delete)} rows from {sheet_name}...")
            for row in to_delete:
                post_json(script_url, {
                    'action': 'delete',
                    'user': row['user'],
                    'wordId': row['wordId'],
                    'sheet': sheet_name
                })
            print(f"    Deleted {len(to_delete)} rows")

    print("\nDone.")


if __name__ == '__main__':
    main()
