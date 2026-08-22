#!/usr/bin/env python3
"""Pull Progress, provenance-aware flags, or saved song sets to local JSON.

Usage:
    python3 backend/sync_sheets.py                    # pull both sheets
    python3 backend/sync_sheets.py --sheet Progress  # pull one sheet
    python3 backend/sync_sheets.py --diff             # show changes since last pull
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
SHEETS = ['Progress', 'FlaggedWords']
PULLABLE_SHEETS = SHEETS + ['SongSets']
HEADER_KEYS = {
    'user': 'user',
    'itemid': 'itemId',
    'itemtype': 'itemType',
    'mode': 'mode',
    'source': 'source',
    'parentwordid': 'parentWordId',
    'label': 'label',
    'word': 'word',
    'wordid': 'wordId',
    'language': 'language',
    'correct': 'correct',
    'wrong': 'wrong',
    'lastcorrect': 'lastCorrect',
    'lastwrong': 'lastWrong',
    'lastseen': 'lastSeen',
    'schemaversion': 'schemaVersion',
    'srsstage': 'srsStage',
    'value': 'value',
    # FlaggedWords schema v4 — each audit attribute is its own column instead of
    # being buried in the rendered report blob.
    'flaggedat': 'flaggedAt',
    'lemma': 'lemma',
    'cardid': 'cardId',
    'fieldpath': 'fieldPath',
    'target': 'target',
    'category': 'category',
    'sensepos': 'sensePos',
    'senseid': 'senseId',
    'sensegloss': 'senseGloss',
    'context': 'context',
    'example': 'example',
    'translation': 'translation',
    'song': 'song',
    'exampleassignment': 'exampleAssignment',
    'translationsource': 'translationSource',
    'senseassignment': 'senseAssignment',
    'requestedtag': 'requestedTag',
    'note': 'note',
    'report': 'report',
    'releaseid': 'releaseId',
    'runid': 'runId',
    'runtimestamp': 'runTimestamp',
    'promptid': 'promptId',
    'model': 'model',
    'assignmentmethod': 'assignmentMethod',
    'provenancejson': 'provenanceJson',
    'flagid': 'flagId',
    'clientbuild': 'clientBuild',
    'exampleid': 'exampleId',
    'sourcerecordid': 'sourceRecordId',
    'status': 'status',
    'resolutionnote': 'resolutionNote',
    'resolvedby': 'resolvedBy',
    'resolvedat': 'resolvedAt',
    'fixedinreleaseid': 'fixedInReleaseId',
    'setid': 'setId',
    'name': 'name',
    'songidsjson': 'songIdsJson',
    'updatedat': 'updatedAt',
    'artistslugsjson': 'artistSlugsJson',
}


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
        print(f"Error: {SECRETS_PATH} not found. Copy secrets.template.json and fill in the URL.")
        sys.exit(1)


def dump_sheet(script_url, sheet_name):
    payload = json.dumps({'action': 'dump', 'sheet': sheet_name}).encode()
    req = urllib.request.Request(
        script_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"Error fetching {sheet_name}: {e}")
        sys.exit(1)

    if not body.get('success'):
        print(f"API error for {sheet_name}: {body.get('message', 'unknown')}")
        sys.exit(1)

    return body['data']


def rows_to_objects(headers, rows):
    keys = [HEADER_KEYS.get(str(header).lower(), f'col{i}')
            for i, header in enumerate(headers or [])]
    result = []
    for row in rows:
        obj = {}
        for i, val in enumerate(row):
            key = keys[i] if i < len(keys) else f'col{i}'
            obj[key] = val
        result.append(obj)
    return result


def save_local(sheet_name, headers, rows):
    os.makedirs(LOCAL_DIR, exist_ok=True)
    out_path = os.path.join(LOCAL_DIR, f'{sheet_name}.json')
    data = {
        'pulled_at': datetime.utcnow().isoformat() + 'Z',
        'sheet': sheet_name,
        'row_count': len(rows),
        'headers': headers,
        'rows': rows_to_objects(headers, rows),
    }
    with open(out_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out_path


def load_previous(sheet_name):
    path = os.path.join(LOCAL_DIR, f'{sheet_name}.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def show_diff(sheet_name, old_data, new_rows):
    if old_data is None:
        print(f"  {sheet_name}: no previous pull to compare against")
        return

    def row_id(row):
        if sheet_name == 'SongSets':
            return '|'.join((str(row.get('user', '')), str(row.get('source', '')),
                             str(row.get('setId', ''))))
        if sheet_name != 'Progress':
            return str(row.get('flagId', '')) or f"{row.get('user', '')}|{row.get('wordId', '')}"
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
    old_ids = {row_id(r) for r in old_data.get('rows', []) if row_id(r)}
    new_ids = {row_id(r) for r in new_rows if row_id(r)}

    added = new_ids - old_ids
    removed = old_ids - new_ids
    old_count = old_data.get('row_count', len(old_data.get('rows', [])))
    new_count = len(new_rows)

    print(f"  {sheet_name}: {old_count} → {new_count} rows ({new_count - old_count:+d})")
    if added:
        print(f"    Added ({len(added)}): {', '.join(sorted(added)[:10])}{'...' if len(added) > 10 else ''}")
    if removed:
        print(f"    Removed ({len(removed)}): {', '.join(sorted(removed)[:10])}{'...' if len(removed) > 10 else ''}")
    if not added and not removed:
        # Check for value changes
        old_map = {row_id(r): r for r in old_data.get('rows', []) if row_id(r)}
        changed = 0
        for r in new_rows:
            wid = row_id(r)
            if wid and wid in old_map and r != old_map[wid]:
                changed += 1
        if changed:
            print(f"    {changed} rows modified")
        else:
            print(f"    No changes")


def main():
    parser = argparse.ArgumentParser(description='Pull Google Sheets progress data to local JSON')
    parser.add_argument('--sheet', choices=PULLABLE_SHEETS,
                        help='Pull one sheet (default: Progress and FlaggedWords)')
    parser.add_argument('--diff', action='store_true', help='Show changes since last pull')
    args = parser.parse_args()

    sheets = [args.sheet] if args.sheet else SHEETS
    script_url = load_script_url()

    for sheet_name in sheets:
        print(f"Pulling {sheet_name}...")

        # Load previous data before overwriting (for diff)
        old_data = load_previous(sheet_name) if args.diff else None

        raw = dump_sheet(script_url, sheet_name)
        headers = raw.get('headers', [])
        rows = raw.get('rows', [])
        new_rows = rows_to_objects(headers, rows)

        if args.diff:
            show_diff(sheet_name, old_data, new_rows)

        out_path = save_local(sheet_name, headers, rows)
        print(f"  Saved {len(rows)} rows → {out_path}")

    print("Done.")


if __name__ == '__main__':
    main()
