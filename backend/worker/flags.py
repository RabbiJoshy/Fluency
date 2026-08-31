#!/usr/bin/env python3
"""Read and triage flags now that D1 holds them.

Flags are written to D1 and mirrored to the Apps Script FlaggedWords tab, so
the spreadsheet still shows everything — but the sheet is an export now, not
the store. This is the tool for querying the store directly.

    python3 backend/worker/flags.py                     # open flags, newest first
    python3 backend/worker/flags.py --status all
    python3 backend/worker/flags.py --target sense --limit 50
    python3 backend/worker/flags.py --json > flags.json

The ~29 per-attribute columns the sheet needed are one payload_json column
here: they are a snapshot of how the card looked when flagged, read whole
during triage and never filtered on. What you filter on stayed a column.
"""

import argparse
import json
import os
import sys
import urllib.request

DEFAULT_URL = 'https://fluency-api.rabbijoshy.workers.dev'
# Cloudflare's bot check 403s urllib's default agent (error 1010).
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def call(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read())
    if not body.get('success'):
        sys.exit(f"backend error: {body.get('message')}")
    return body.get('data') or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=os.environ.get('FLUENCY_BACKEND_URL', DEFAULT_URL))
    ap.add_argument('--status', default='open',
                    help="open | accepted | rejected | fixed | all (default: open)")
    ap.add_argument('--target', help='filter by what was flagged (sense, example, …)')
    ap.add_argument('--category', help='filter by problem category')
    ap.add_argument('--limit', type=int, default=25)
    ap.add_argument('--json', action='store_true', help='emit raw JSON instead of a table')
    args = ap.parse_args()

    data = call(args.url, {'action': 'dump', 'sheet': 'Flags'})
    headers = data.get('headers', [])
    rows = [dict(zip(headers, row)) for row in data.get('rows', [])]

    if args.status != 'all':
        rows = [r for r in rows if r.get('Status') == args.status]
    if args.target:
        rows = [r for r in rows if r.get('Target') == args.target]
    if args.category:
        rows = [r for r in rows if r.get('Category') == args.category]
    rows = rows[:args.limit]

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if not rows:
        print(f"No flags matching status={args.status}"
              + (f" target={args.target}" if args.target else ""))
        return

    print(f"{'created':<21} {'mode':<7} {'target':<12} {'category':<16} item")
    print('-' * 88)
    for row in rows:
        print(f"{str(row.get('CreatedAt',''))[:19]:<21} {row.get('Mode',''):<7} "
              f"{row.get('Target',''):<12} {row.get('Category',''):<16} {row.get('ItemId','')}")
        note = (row.get('Note') or '').strip()
        if note:
            print(f"{'':<21} note: {note[:70]}")
    print(f"\n{len(rows)} flag(s). --json for the full payload of each.")


if __name__ == '__main__':
    main()
