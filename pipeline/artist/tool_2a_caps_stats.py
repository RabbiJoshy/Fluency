#!/usr/bin/env python3
"""Per-word capitalization stats over ALL occurrences (for proper-noun routing).

step_2a lowercases at tokenization, discarding case. This scans the raw Genius
batches (case preserved, cleaned with step_2a's own cleaner) and records, per
word, how often it appears Capitalized MID-SENTENCE (line-initial caps are
ambiguous — sentence starts — so they're excluded from the rate). Computed over
every occurrence, NOT the capped example sample, so it never violates the
"counts must not be example-gated" rule.

cap_rate = capitalized-mid-sentence / total-mid-sentence occurrences. A high rate
means the surface is used as a proper noun (Miami/Benito/York → ~1.0), a low rate
means a common word (sol/amor → ~0.0); the middle band (~0.3-0.6) is a genuine
name/word homograph (Rico) that needs per-use handling.

Writes data/layers/caps_stats.json: {word: {total, midcap, firstcap, cap_rate}}.

Usage:
  .venv/bin/python3 pipeline/artist/tool_2a_caps_stats.py --artist-dir "Artists/spanish/Bad Bunny"
"""
import argparse, json, glob, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "artist"))
import step_2a_count_words as S2  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True)
    args = ap.parse_args()
    adir = os.path.abspath(args.artist_dir)
    batches = sorted(glob.glob(os.path.join(adir, "data", "input", "batches", "batch_*.json")))

    total = defaultdict(int)
    midcap = defaultdict(int)
    firstcap = defaultdict(int)
    for f in batches:
        try:
            songs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for song in songs:
            raw = song.get("lyrics", "") if isinstance(song, dict) else ""
            try:
                cleaned = S2.clean_genius_lyrics(raw)
            except Exception:
                cleaned = raw
            text = cleaned if isinstance(cleaned, str) else (
                "\n".join(cleaned) if isinstance(cleaned, list) else str(cleaned))
            for line in text.split("\n"):
                toks = [m.group(0) for m in S2.WORD_RE.finditer(line)]
                for i, tok in enumerate(toks):
                    wl = tok.lower()
                    total[wl] += 1
                    if tok[:1].isupper():
                        (firstcap if i == 0 else midcap)[wl] += 1

    stats = {}
    for w, t in total.items():
        mid_total = t - firstcap[w]              # mid-sentence occurrences only
        rate = (midcap[w] / mid_total) if mid_total > 0 else 0.0
        stats[w] = {
            "total": t, "midcap": midcap[w], "firstcap": firstcap[w],
            "cap_rate": round(rate, 3),
        }
    out = os.path.join(adir, "data", "layers", "caps_stats.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    hi = sum(1 for s in stats.values() if s["cap_rate"] >= 0.65 and (s["total"] - s["firstcap"]) >= 3)
    print("Wrote %s (%d words, %d with cap_rate>=0.65 & >=3 mid occ)" % (out, len(stats), hi))


if __name__ == "__main__":
    main()
