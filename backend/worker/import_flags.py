#!/usr/bin/env python3
"""Port FlaggedWords rows from the audit sheet into the D1 `flags` table.

    .venv/bin/python3 backend/sync_sheets.py --sheet FlaggedWords --url "$APPS_SCRIPT_URL"
    python3 backend/worker/import_flags.py backend/local/FlaggedWords.json > flags.sql
    cd backend/worker && wrangler d1 execute fluency --remote --file=../../flags.sql

The sheet grew a column per attribute — 42 of them — because a spreadsheet has
nowhere else to put structure. Here the handful you actually filter on stay
columns and the rest become payload_json, which is how they were always used:
read whole while triaging, never queried individually.

Provenance is deliberately kept. A flag is only meaningful against the run that
produced the card, so runId / promptId / model / assignmentMethod travel with
it in the payload even when that run is long superseded.
"""

import argparse
import json
import sys

# Promoted to real columns: these are the axes triage actually filters on.
PROMOTED = {
    'User': 'user_id', 'FlaggedAt': 'created_at', 'WordId': 'word_id',
    'Language': 'language', 'Mode': 'mode', 'Source': 'source',
    'ReleaseId': 'release_id', 'Target': 'target', 'Category': 'category',
    'Note': 'note', 'FlagId': 'flag_id', 'Status': 'status',
    'ResolutionNote': 'resolution_note', 'ResolvedBy': 'resolved_by',
    'ResolvedAt': 'resolved_at', 'FixedInReleaseId': 'fixed_in_release',
}


def sql_str(value):
    if value is None or value == '':
        return "''"
    return "'" + str(value).replace("'", "''") + "'"


def parse_full_id(full_id):
    """"es1d6ffed1a" -> ("es", "lyrics", "d6ffed1a"). Mirrors parseFullId in store.js."""
    text = str(full_id or '')
    if len(text) < 4:
        return '', '', ''
    return text[:2], ('lyrics' if text[2] == '1' else 'speech'), text[3:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', help='FlaggedWords.json from sync_sheets.py')
    args = ap.parse_args()

    with open(args.dump) as fh:
        payload = json.load(fh)
    rows = payload['rows'] if isinstance(payload, dict) else payload

    emitted = 0
    skipped = 0
    for row in rows:
        user = row.get('user') or row.get('User') or ''
        if not user:
            skipped += 1
            continue
        # sync_sheets lowercases header names into camelCase keys.
        get = lambda *names: next(
            (row[n] for n in names if row.get(n) not in (None, '')), '')

        full_id = get('wordId', 'WordId', 'cardId', 'CardId')
        lang_code, mode, item_id = parse_full_id(full_id)
        created = get('flaggedAt', 'FlaggedAt')
        flag_id = get('flagId', 'FlagId') or f"legacy:{user}:{full_id}:{created}"

        # Everything not promoted to a column — including the whole provenance
        # block — is preserved verbatim so no information is lost in the port.
        promoted_keys = {k.lower() for k in PROMOTED}
        payload_json = {k: v for k, v in row.items()
                        if v not in (None, '') and k.lower() not in promoted_keys}

        values = ', '.join([
            sql_str(flag_id), sql_str(user), sql_str(created),
            sql_str(item_id), sql_str('word'), sql_str(lang_code),
            sql_str(get('language', 'Language')),
            sql_str(mode or get('mode', 'Mode')),
            sql_str(get('source', 'Source')), sql_str(get('releaseId', 'ReleaseId')),
            sql_str(get('target', 'Target')), sql_str(get('category', 'Category')),
            sql_str(get('note', 'Note')),
            sql_str(json.dumps(payload_json, ensure_ascii=False)),
            sql_str(get('status', 'Status') or 'open'),
            sql_str(get('resolvedAt', 'ResolvedAt')),
            sql_str(get('resolvedBy', 'ResolvedBy')),
            sql_str(get('fixedInReleaseId', 'FixedInReleaseId')),
        ])
        print(
            "INSERT OR REPLACE INTO flags (flag_id, user_id, created_at, item_id,"
            " item_type, lang_code, language, mode, source, release_id, target,"
            " category, note, payload_json, status, resolved_at, resolved_by,"
            f" fixed_in_release) VALUES ({values});")
        emitted += 1

    print(f"-- {emitted} flags emitted, {skipped} skipped (no user)", file=sys.stderr)
    print(f"imported {emitted} flags, skipped {skipped}", file=sys.stderr)


if __name__ == '__main__':
    main()
