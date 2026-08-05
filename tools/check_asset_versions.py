#!/usr/bin/env python3
"""
check_asset_versions.py — every ?v= tag must agree with ASSET_VERSION.

Why this exists
---------------
The ES module cache keys by resolved URL, so `state.js?v=A` and `state.js?v=B`
are two different modules: two fetches, two executions of top-level code, two
copies of anything the module holds. When only some tags get bumped, the app
runs a mixture of old and new code and the file on disk looks correct while the
browser plainly disagrees.

That is exactly what happened on 2026-08-05. Bumps were done by replacing the
*previous* version string, so tags already reading an older value never matched
and never moved: 19 module-to-module imports sat on 20260803c/e while main.js
had advanced to 20260805g, leaving three separate instances of state.js alive
at once. The same class of bug hid every CSS change for a day, because
css/style.css carried no tag at all and the service worker's precache kept
serving it from the browser's disk cache.

Run before committing any ?v= change:

    python3 tools/check_asset_versions.py

Exit status is non-zero when anything disagrees, so it also works as a
pre-commit hook or CI step.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_WORKER = PROJECT_ROOT / "service-worker.js"
TAG_RE = re.compile(r"\?v=(\d{8}[a-z])")
CONST_RE = re.compile(r"ASSET_VERSION = '(\d{8}[a-z])'")


def scanned_files():
    yield from sorted((PROJECT_ROOT / "js").glob("*.js"))
    yield PROJECT_ROOT / "index.html"
    yield SERVICE_WORKER


def main():
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    match = CONST_RE.search(source)
    if not match:
        print("FAIL: service-worker.js has no ASSET_VERSION constant to check against")
        return 1
    expected = match.group(1)

    problems = []
    counted = 0
    for path in scanned_files():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(PROJECT_ROOT)

        for number, line in enumerate(text.splitlines(), 1):
            for tag in TAG_RE.findall(line):
                counted += 1
                if tag != expected:
                    problems.append(f"{relative}:{number}: ?v={tag} (expected {expected})")

        # A second ASSET_VERSION lives in flashcards.js for its lazy imports.
        for number, line in enumerate(text.splitlines(), 1):
            found = CONST_RE.search(line)
            if found and found.group(1) != expected:
                problems.append(
                    f"{relative}:{number}: ASSET_VERSION = '{found.group(1)}' "
                    f"(expected {expected})")

    # The stylesheet is the asset that has to carry a tag and historically did
    # not, so check it by name rather than trusting it to appear above.
    index_html = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    if re.search(r'href="css/style\.css"', index_html):
        problems.append("index.html: css/style.css is linked with no ?v= tag")

    if problems:
        print(f"FAIL: {len(problems)} asset version problem(s), expected {expected}\n")
        for problem in problems:
            print(f"  {problem}")
        print("\nBump every tag by pattern, not by previous value:")
        print(r"  find js index.html service-worker.js -type f "
              r"-exec sed -i '' -E 's/\?v=[0-9]{8}[a-z]/?v=NEW/g' {} +")
        return 1

    print(f"OK: {counted} ?v= tags all agree with ASSET_VERSION {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
