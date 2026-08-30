#!/usr/bin/env python3
"""Convert a Sheets Progress dump into SQL for D1.

Reads the JSON written by backend/sync_sheets.py and emits INSERT statements
for backend/worker/migrations/0001_init.sql.

The row_key it computes is a port of progressRowKey() in
backend/GoogleAppsScript.js:326, matched by rowKey() in src/index.js. All three
must agree or an upsert will insert where it should update.

The Progress tab had no uniqueness constraint, so the dump can contain several
rows sharing a key. findProgressRow() returned the first match, so the first
occurrence is what the app has been reading; that is the one kept here. Any
collapsed duplicates are reported so they can be inspected before loading.

Usage:
    python3 backend/worker/seed.py backend/local/Progress.json > seed.sql
    python3 backend/worker/seed.py backend/local/Progress.json --report
"""

import argparse
import json
import sys
from collections import Counter

ITEM_TYPES = ("sense", "mwe", "clitic", "lemma")


def normalize_mode(mode, item_id):
    if mode in ("normal", "artist", "all"):
        return mode
    text = str(item_id or "")
    if len(text) > 2 and text[2] == "1":
        return "artist"
    if len(text) > 2 and text[2] == "0":
        return "normal"
    return "normal"


def normalize_item_type(item_type):
    value = str(item_type or "").lower()
    if value in ("expression", "mwe"):
        return "mwe"
    if value in ("sense", "clitic", "word", "meta"):
        return value
    return value or "sense"


def row_key(row):
    user = str(row.get("user") or "")
    item_id = str(row.get("itemId") or "")
    item_type = normalize_item_type(row.get("itemType"))
    mode = normalize_mode(row.get("mode"), row.get("parentWordId") or item_id)
    if item_type == "meta":
        return "|".join([user, item_type, mode, str(row.get("source") or ""),
                         str(row.get("language") or ""), str(row.get("label") or ""),
                         item_id])
    return "|".join([user, item_type, mode, item_id])


def sql_str(value):
    if value is None:
        return "''"
    return "'" + str(value).replace("'", "''") + "'"


def sql_int(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", help="Progress.json from backend/sync_sheets.py")
    ap.add_argument("--report", action="store_true",
                    help="print a summary to stderr instead of emitting SQL")
    args = ap.parse_args()

    with open(args.dump) as fh:
        payload = json.load(fh)
    rows = payload["rows"] if isinstance(payload, dict) else payload

    seen = {}
    dupes = Counter()
    for row in rows:
        if not row.get("user"):
            continue
        key = row_key(row)
        if key in seen:
            dupes[key] += 1
            continue          # first occurrence wins, as findProgressRow did
        seen[key] = row

    users = Counter(r.get("user") for r in seen.values())
    types = Counter(normalize_item_type(r.get("itemType")) for r in seen.values())

    print(f"rows in dump:     {len(rows)}", file=sys.stderr)
    print(f"unique row_keys:  {len(seen)}", file=sys.stderr)
    print(f"duplicates dropped: {sum(dupes.values())} across {len(dupes)} keys",
          file=sys.stderr)
    print(f"users:            {dict(users)}", file=sys.stderr)
    print(f"item types:       {dict(types)}", file=sys.stderr)
    if dupes:
        print("\nmost-duplicated keys:", file=sys.stderr)
        for key, count in dupes.most_common(10):
            print(f"  {count + 1}x  {key}", file=sys.stderr)

    if args.report:
        return

    print("BEGIN TRANSACTION;")
    for key, row in seen.items():
        item_type = normalize_item_type(row.get("itemType"))
        mode = normalize_mode(row.get("mode"), row.get("parentWordId") or row.get("itemId"))
        values = ", ".join([
            sql_str(key),
            sql_str(row.get("user")),
            sql_str(row.get("itemId")),
            sql_str(item_type),
            sql_str(mode),
            sql_str(row.get("source") or ""),
            sql_str(row.get("parentWordId") or ""),
            sql_str(row.get("label") or ""),
            sql_str(row.get("language") or ""),
            sql_int(row.get("correct")),
            sql_int(row.get("wrong")),
            sql_str(row.get("lastCorrect") or ""),
            sql_str(row.get("lastWrong") or ""),
            sql_str(row.get("lastSeen") or ""),
            sql_int(row.get("schemaVersion") or 4),
            sql_str("" if row.get("srsStage") in (None, "") else row.get("srsStage")),
            sql_str(row.get("value") or ""),
        ])
        print(f"INSERT OR REPLACE INTO progress VALUES ({values});")
    print("COMMIT;")


if __name__ == "__main__":
    main()
