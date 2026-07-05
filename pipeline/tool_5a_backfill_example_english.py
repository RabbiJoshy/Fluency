#!/usr/bin/env python3
"""tool_5a_backfill_example_english.py — fill empty English translations on
artist example lines via one batched Gemini Flash-Lite pass.

~318 example rows on visible cards have a Spanish lyric line but no English
(Genius had no translation for those lines). Surgical: only rows with empty
`english` are touched, existing translations are never overwritten, and the
examples files are id-keyed (no positional coupling to the master), so
in-place writes are safe.

Needs GEMINI_API_KEY in the environment. Costs a fraction of a cent
(Flash-Lite, ~320 short lines). Run from project root:

    .venv/bin/python3 pipeline/tool_5a_backfill_example_english.py            # dry run (lists rows)
    .venv/bin/python3 pipeline/tool_5a_backfill_example_english.py --apply    # translate + write
"""
import argparse
import json
import os
import sys

EXAMPLES_FILES = [
    "Artists/spanish/Bad Bunny/BadBunnyvocabulary.examples.json",
    "Artists/spanish/Young Miko/YoungMikovocabulary.examples.json",
    "Artists/spanish/Rosalía/Rosaliavocabulary.examples.json",
]
MODEL = "gemini-2.5-flash-lite"
BATCH = 80  # lines per request

PROMPT = """Translate these Spanish song-lyric lines to natural, informal English.
They are reggaeton/pop lyrics: keep slang casual, keep English code-switches as-is,
do not censor. Return STRICT JSON: an array of strings, one translation per input
line, same order, same length. No commentary.

Lines:
{lines}"""


def iter_empty_rows(data):
    for node in data.values():
        for group in (node.get("m") or []):
            rows = group if isinstance(group, list) else [group]
            for row in rows:
                es = (row.get("spanish") or "").strip()
                if es and not (row.get("english") or "").strip():
                    yield row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="call Gemini and write files")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()

    files = {}
    todo = []  # (row_ref)
    for path in EXAMPLES_FILES:
        if not os.path.isfile(path):
            print("missing:", path)
            continue
        with open(path, encoding="utf-8") as f:
            files[path] = json.load(f)
        rows = list(iter_empty_rows(files[path]))
        print("%-60s %d empty-english rows" % (os.path.basename(path), len(rows)))
        todo.extend(rows)

    # Dedupe identical Spanish lines (choruses repeat) — translate once.
    unique = {}
    for row in todo:
        unique.setdefault(row["spanish"].strip(), []).append(row)
    print("total rows: %d (%d unique lines)" % (len(todo), len(unique)))

    if not args.apply:
        for es in list(unique)[:15]:
            print("   ", es[:90])
        print("\nDry run — pass --apply to translate and write.")
        return

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set")
    from google import genai
    client = genai.Client(api_key=api_key)

    lines = list(unique.keys())
    translated = {}
    for start in range(0, len(lines), BATCH):
        chunk = lines[start:start + BATCH]
        numbered = "\n".join("%d. %s" % (i + 1, l) for i, l in enumerate(chunk))
        resp = client.models.generate_content(
            model=args.model,
            contents=PROMPT.format(lines=numbered),
            config={"response_mime_type": "application/json"},
        )
        out = json.loads(resp.text)
        if not isinstance(out, list) or len(out) != len(chunk):
            sys.exit("batch %d: expected %d translations, got %r" %
                     (start // BATCH, len(chunk), type(out)))
        for es, en in zip(chunk, out):
            translated[es] = (en or "").strip()
        print("  batch %d/%d ok" % (start // BATCH + 1, (len(lines) + BATCH - 1) // BATCH))

    filled = 0
    for es, rows in unique.items():
        en = translated.get(es, "")
        if not en:
            continue
        for row in rows:
            row["english"] = en
            row["translation_source"] = "gemini-backfill"
            filled += 1

    for path, data in files.items():
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    print("filled %d rows; wrote %d files" % (filled, len(files)))


if __name__ == "__main__":
    main()
