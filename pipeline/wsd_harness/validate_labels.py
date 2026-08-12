#!/usr/bin/env python3
"""Every label must name a word in the panel and sense ids that exist in its menu.
Catches transcription errors before they become permanent gold."""
import json, sys
from common import LABEL_DIR, load_menu, read_corpus

corpus = sys.argv[1] if len(sys.argv) > 1 else "spanishdict"
panel = {r["word"]: r for r in read_corpus(corpus)}
menu = load_menu("Bad Bunny" if corpus == "badbunny" else None)
rows = [json.loads(l) for l in open(LABEL_DIR / f"{corpus}.acceptable.jsonl") if l.strip()]
errs = []
for r in rows:
    w = r["word"]
    if w not in panel:
        errs.append(f"{w}: not in panel"); continue
    valid = set(menu.get(w, {}))
    bad = [s for s in r["acceptable"] if s not in valid]
    if bad:
        errs.append(f"{w}: sense ids not in menu: {bad}")
    if not r["acceptable"] and not r.get("no_answer"):
        errs.append(f"{w}: empty acceptable set and no no_answer flag")
dupes = [w for w in {r["word"] for r in rows} if sum(x["word"] == w for x in rows) > 1]
if dupes:
    errs.append(f"duplicate words: {dupes}")
gold_ok = sum(1 for r in rows if panel[r["word"]].get("gold") in r["acceptable"]
              for _ in [0] if r["word"] in panel)
print(f"{len(rows)} labels, {len(panel)} panel sentences, {len(rows)/len(panel):.0%} covered")
print(f"gold sense is inside my acceptable set: {gold_ok}/{len(rows)}")
print("ERRORS:" if errs else "no errors")
for e in errs: print("  " + e)
