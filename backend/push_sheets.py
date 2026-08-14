#!/usr/bin/env python3
"""Push local unified Progress data or opt-in flags back to Google Sheets.

Compares local JSON against a fresh pull from Sheets and pushes only the
differences. Dry-run by default — requires --confirm AND interactive "yes"
to actually modify anything.

Usage:
    python3 backend/push_sheets.py                          # dry-run Progress
    python3 backend/push_sheets.py --sheet Progress         # dry-run progress
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
# Default "push everything" set — progress sheets only, so a bare invocation
# never touches the flags sheet.
SHEETS = ['Progress']
# FlaggedWords is opt-in via an explicit --sheet FlaggedWords, since pushing it
# is a curation action, not routine progress sync. --replace deletes remote flags
# absent from local. Its schema is v2 (FLAG_KEYS), no longer the progress-shaped
# eight columns.
PUSHABLE_SHEETS = SHEETS + ['FlaggedWords']
PROGRESS_KEYS = [
    'user', 'itemId', 'itemType', 'mode', 'source', 'parentWordId', 'label',
    'language', 'correct', 'wrong', 'lastCorrect', 'lastWrong', 'lastSeen',
    'schemaVersion', 'srsStage', 'value'
]
# Local-JSON key names (what sync_sheets.py writes), used for diffing. The
# Word column arrives as `word`; it is renamed to `wordText` only at send time,
# because the backend reserves the `word` payload key for the v1 report-blob
# contract. See flag_push_payload().
FLAG_KEYS = [
    'user', 'flaggedAt', 'word', 'lemma', 'language', 'wordId', 'cardId',
    'fieldPath', 'target', 'category', 'sensePos', 'senseId', 'senseGloss',
    'context', 'example', 'translation', 'song', 'exampleAssignment',
    'translationSource', 'senseAssignment', 'requestedTag', 'note', 'report',
    'schemaVersion'
]
HEADER_ALIASES = {
    'user': 'user', 'itemid': 'itemId', 'itemtype': 'itemType', 'mode': 'mode',
    'source': 'source', 'parentwordid': 'parentWordId', 'label': 'label',
    'word': 'word', 'wordid': 'wordId', 'language': 'language',
    'correct': 'correct', 'wrong': 'wrong', 'lastcorrect': 'lastCorrect',
    'lastwrong': 'lastWrong', 'lastseen': 'lastSeen',
    'schemaversion': 'schemaVersion', 'srsstage': 'srsStage', 'value': 'value',
    # FlaggedWords v2. The sheet's Word column maps to `wordText` because the
    # backend reserves the `word` payload key for the v1 report-blob contract.
    'flaggedat': 'flaggedAt', 'lemma': 'lemma', 'cardid': 'cardId',
    'fieldpath': 'fieldPath', 'target': 'target', 'category': 'category',
    'sensepos': 'sensePos', 'senseid': 'senseId', 'sensegloss': 'senseGloss',
    'context': 'context', 'example': 'example', 'translation': 'translation',
    'song': 'song', 'exampleassignment': 'exampleAssignment',
    'translationsource': 'translationSource',
    'senseassignment': 'senseAssignment', 'requestedtag': 'requestedTag',
    'note': 'note', 'report': 'report'
}


def sheet_keys(sheet_name):
    return PROGRESS_KEYS if sheet_name == 'Progress' else FLAG_KEYS


def flag_push_payload(row):
    """Rename the local `word` field to the backend's `wordText` parameter.

    saveFlaggedWord/buildFlagRow accept `word` only as the v1 fallback, where it
    held the whole rendered report. Sending a bare headword under that key would
    overwrite the row's Report column with it.
    """
    payload = {k: v for k, v in row.items() if k != 'word'}
    word_text = row.get('wordText', row.get('word', ''))
    if word_text != '':
        payload['wordText'] = word_text
    return payload


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


BULK_CHUNK = 50   # rows per bulkSave request


def post_json(script_url, payload, timeout=60):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        script_url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    headers = body['data'].get('headers', [])
    keys = [HEADER_ALIASES.get(str(header).lower(), f'col{i}')
            for i, header in enumerate(headers)]
    rows = []
    for raw_row in body['data']['rows']:
        obj = {}
        for i, val in enumerate(raw_row):
            key = keys[i] if i < len(keys) else f'col{i}'
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


def row_key(row, sheet_name):
    if sheet_name == 'Progress':
        item_type = str(row.get('itemType', 'sense')).lower()
        if item_type == 'expression':
            item_type = 'mwe'
        mode = str(row.get('mode', 'normal'))
        if item_type == 'meta':
            return '|'.join((
                str(row.get('user', '')), item_type, mode,
                str(row.get('source', '')), str(row.get('language', '')),
                str(row.get('label', '')), str(row.get('itemId', ''))
            ))
        return '|'.join((str(row.get('user', '')), item_type, mode,
                         str(row.get('itemId', ''))))
    return f"{row.get('user', '')}|{row.get('wordId', '')}"


def rows_differ(local_row, remote_row, sheet_name):
    for k in sheet_keys(sheet_name):
        lv = local_row.get(k, '')
        rv = remote_row.get(k, '')
        if str(lv) != str(rv):
            return True
    return False


def compute_changeset(local_rows, remote_rows, sheet_name):
    remote_map = {row_key(r, sheet_name): r for r in remote_rows}
    local_map = {row_key(r, sheet_name): r for r in local_rows}

    to_upsert = []
    for key, local_row in local_map.items():
        remote_row = remote_map.get(key)
        if remote_row is None or rows_differ(local_row, remote_row, sheet_name):
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
            row_id = r.get('itemId') or r.get('wordId', '?')
            label = r.get('label') or r.get('word', '?')
            print(f"      {r.get('user', '?')}/{row_id} — {label}"
                  f" (correct={r.get('correct', 0)}, wrong={r.get('wrong', 0)})")
        if len(to_upsert) > 10:
            print(f"      ... and {len(to_upsert) - 10} more")
    if to_delete:
        print(f"    Delete {len(to_delete)} rows:")
        for r in to_delete[:10]:
            row_id = r.get('itemId') or r.get('wordId', '?')
            label = r.get('label') or r.get('word', '?')
            print(f"      {r.get('user', '?')}/{row_id} — {label}")
        if len(to_delete) > 10:
            print(f"      ... and {len(to_delete) - 10} more")
    if not to_upsert and not to_delete:
        print(f"    No changes")


def main():
    parser = argparse.ArgumentParser(description='Push local JSON data back to Google Sheets')
    parser.add_argument('--sheet', choices=PUSHABLE_SHEETS,
                        help='Push only this sheet (default: the progress sheets). '
                             'FlaggedWords is opt-in and only via this flag.')
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

        to_upsert, to_delete = compute_changeset(local_rows, remote_rows, sheet_name)

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
            rows_payload = ([flag_push_payload(r) for r in to_upsert]
                            if sheet_name == 'FlaggedWords' else to_upsert)
            # Chunked: Apps Script spends ~2.4s per row, so one request for
            # 400+ rows blows through both the client timeout and Apps Script's
            # own 6-minute execution ceiling — and a timeout there leaves a
            # partial write with no report of how far it got. Each chunk is its
            # own request; the changeset is recomputed on the next run, so an
            # interrupted push resumes rather than duplicating.
            written = 0
            for start in range(0, len(rows_payload), BULK_CHUNK):
                chunk = rows_payload[start:start + BULK_CHUNK]
                result = post_json(script_url, {
                    'action': 'bulkSave',
                    'sheet': sheet_name,
                    'rows': chunk
                }, timeout=300)
                if result.get('success'):
                    written += len(chunk)
                    print(f"    {written}/{len(rows_payload)} — {result['message']}",
                          flush=True)
                else:
                    print(f"    Error after {written}/{len(rows_payload)}: "
                          f"{result.get('message')}")
                    break

        if to_delete:
            print(f"  Deleting {len(to_delete)} rows from {sheet_name} "
                  f"(one API call each — this can take a minute)...")
            ok = 0
            failures = []
            for i, row in enumerate(to_delete, 1):
                if sheet_name == 'Progress':
                    result = post_json(script_url, {
                        'action': 'deleteRow',
                        'sheet': sheet_name,
                        'user': row['user'],
                        'itemId': row.get('itemId'),
                        'itemType': row.get('itemType'),
                        'mode': row.get('mode', 'normal'),
                        'source': row.get('source', ''),
                        'parentWordId': row.get('parentWordId', ''),
                        'label': row.get('label', ''),
                        'language': row.get('language', '')
                    })
                else:
                    result = post_json(script_url, {
                        'action': 'delete',
                        'user': row['user'],
                        'wordId': row.get('wordId'),
                        'sheet': sheet_name
                    })
                if result.get('success'):
                    ok += 1
                else:
                    failures.append((row.get('itemId') or row.get('wordId', ''), result.get('message')))
                if i % 25 == 0:
                    print(f"    ... {i}/{len(to_delete)}")
            print(f"    Deleted {ok}/{len(to_delete)} rows"
                  + (f"; {len(failures)} failed" if failures else ""))
            for wid, msg in failures[:10]:
                print(f"      FAILED {wid}: {msg}")

    print("\nDone.")


if __name__ == '__main__':
    main()
