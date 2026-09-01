#!/usr/bin/env python3
"""Check the live backend end to end.

    python3 backend/worker/verify.py            # health, totals, recent activity
    python3 backend/worker/verify.py --user JST

The useful test is: answer a few cards in the app, then run this. The words you
just answered should appear under "most recent answers" within a second or two.
That proves the whole chain — app, sync queue, Worker, D1 — is live.
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

DEFAULT_URL = 'https://fluency-api.rabbijoshy.workers.dev'
# Cloudflare's bot check 403s urllib's default agent (error 1010).
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def call(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', 'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    if not body.get('success'):
        sys.exit(f"  backend error: {body.get('message')}")
    return body.get('data') or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=os.environ.get('FLUENCY_BACKEND_URL', DEFAULT_URL))
    ap.add_argument('--user', default='JST')
    args = ap.parse_args()

    req = urllib.request.Request(args.url, headers={'User-Agent': UA})
    health = json.loads(urllib.request.urlopen(req, timeout=60).read())
    print(f"backend   {health.get('message')}")
    print(f"storage   {health.get('storage')}")

    progress = call(args.url, {'action': 'load', 'user': args.user})
    items = call(args.url, {'action': 'loadItems', 'user': args.user})
    due = call(args.url, {'action': 'loadDue', 'user': args.user, 'limit': 500})

    print(f"\nuser {args.user}")
    print(f"  cards with progress   {len(progress['progress']):>6}")
    print(f"  sparse items          {len(items['items']):>6}")
    print(f"  settings rows         {len(progress['meta']):>6}")
    print(f"  due right now         {due['count']:>6}")

    rows = sorted((r for r in progress['progress'] if r.get('lastSeen')),
                  key=lambda r: r['lastSeen'], reverse=True)[:8]
    print("\nmost recent answers (newest first)")
    if not rows:
        print("  none recorded yet")
    now = datetime.now(timezone.utc)
    for r in rows:
        try:
            seen = datetime.fromisoformat(r['lastSeen'].replace('Z', '+00:00'))
            mins = (now - seen).total_seconds() / 60
            ago = f"{mins:.0f}m ago" if mins < 90 else f"{mins/60:.1f}h ago"
        except ValueError:
            ago = r['lastSeen']
        mark = '✓' if r['wrong'] == 0 else f"{r['correct']}✓/{r['wrong']}✗"
        print(f"  {ago:>10}  {r['word'][:22]:<22} {mark:<8} {r['mode']}")

    print("\nAnswer a few cards in the app, wait a moment, then re-run this —")
    print("those words should appear at the top of the list above.")


if __name__ == '__main__':
    main()
