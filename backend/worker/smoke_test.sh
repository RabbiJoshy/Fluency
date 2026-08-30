#!/usr/bin/env bash
# Smoke test: runs the read-only actions the client uses against a backend
# speaking the Fluency JSON protocol, and summarises each reply for eyeballing.
# Writes nothing, so it is safe to run while the app still points elsewhere.
#
#   ./smoke_test.sh https://fluency-api.<subdomain>.workers.dev JST
#
# This cannot be diffed against the Apps Script backend: Google serves curl an
# HTML interstitial instead of running the script on POST. Check the output
# against the row counts in README.md ("Verify before switching") instead.
set -euo pipefail
URL="${1:?usage: smoke_test.sh <backend-url> [user]}"
USER_ID="${2:-JST}"
SUMMARIZE="$(cd "$(dirname "$0")" && pwd)/_summarize.py"

post() {
  curl -s -L -X POST -H 'Content-Type: application/json' -d "$2" "$URL" \
    | python3 "$SUMMARIZE"
}

echo "== capabilities"; post "$URL" '{"action":"capabilities"}'
echo "== load (all modes)"; post "$URL" "{\"action\":\"load\",\"user\":\"$USER_ID\"}"
echo "== load (normal)"; post "$URL" "{\"action\":\"load\",\"user\":\"$USER_ID\",\"mode\":\"normal\"}"
echo "== load (artist)"; post "$URL" "{\"action\":\"load\",\"user\":\"$USER_ID\",\"mode\":\"artist\"}"
echo "== loadItems"; post "$URL" "{\"action\":\"loadItems\",\"user\":\"$USER_ID\"}"
echo "== loadSongSets"; post "$URL" "{\"action\":\"loadSongSets\",\"user\":\"$USER_ID\"}"
