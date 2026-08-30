"""Collapse a backend reply to a stable one-line-per-field summary for diffing."""
import json
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    print("  <non-JSON reply>")
    sys.exit()

print("  success={0}  message={1}".format(payload.get("success"), payload.get("message")))
for key, value in sorted((payload.get("data") or {}).items()):
    if isinstance(value, (list, dict)):
        print("    {0}: {1} items".format(key, len(value)))
    else:
        print("    {0}: {1}".format(key, value))
