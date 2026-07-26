#!/usr/bin/env python3
"""Unified tag resolver — the single source of truth for word categories.

Every word accumulates tag ASSERTIONS from any stage (routing rules today;
Gemini / cleanup later), each with a source. This resolver aggregates all
current evidence for an artist and resolves it to one effective `category` per
word, honouring MANUAL OVERRIDES at the top of the priority hierarchy (so a
human correction always beats the rules without changing any logic).

Priority (highest first):
    manual override  >  proper_noun  >  loanword  >  english  >  cognate
                     >  noise  >  single_occurrence  >  core

Output: data/known_vocab/word_tags.json
    {word: {category, corpus_count, tags: [{tag, source}]}}

Manual overrides live in Artists/curations/tag_overrides.json (same shape the
dashboard's "Export corrections" produces): {word: {should_be: [tags]}}. The
first should_be entry becomes the forced category.

Usage:
  .venv/bin/python3 pipeline/artist/tool_4b_resolve_tags.py --artist-dir "Artists/spanish/Bad Bunny"
"""
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "artist"))
import tool_4a_tag_dashboard as DASH  # reuse its evidence gatherer

# category resolution order (first match wins, after manual override)
PRIORITY = ["proper_noun", "loanword", "english", "cognate", "noise",
            "single_occurrence", "core"]


def _load(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d if d is not None else {}


def _source_from_dashboard_row(r):
    """Turn a dashboard evidence row into (tags, base_category)."""
    tags = []
    b = r.get("bucket", "")
    if r.get("loanword"):
        tags.append({"tag": "loanword", "source": "english_loanwords"})
    if r.get("en50k") and not r.get("spanish_form"):
        tags.append({"tag": "english", "source": "en_50k_not_es"})
    if r.get("word_eq_trans"):
        tags.append({"tag": "word_eq_translation", "source": "sense_menu"})
    if b == "exclude.proper_nouns":
        tags.append({"tag": "proper_noun", "source": "routing"})
    elif b == "exclude.cognate":
        tags.append({"tag": "cognate", "source": "routing"})
    elif b == "exclude.english":
        tags.append({"tag": "english", "source": "routing"})
    elif b == "exclude.noise":
        tags.append({"tag": "noise", "source": "routing"})
    # base category derived from the routing bucket (already incorporates the
    # loanword/en-not-es/word==translation detectors we ran).
    if b == "exclude.proper_nouns":
        base = "proper_noun"
    elif b == "exclude.english":
        base = "loanword" if r.get("loanword") else "english"
    elif b == "exclude.cognate":
        base = "cognate"
    elif b == "exclude.noise":
        base = "noise"
    else:
        base = "core"  # classifier / sense_discovery = learnable Main vocab
    return tags, base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True)
    args = ap.parse_args()
    adir = os.path.abspath(args.artist_dir)

    src = next((s for s in DASH.discover_sources()
                if os.path.abspath(s["routing"]).startswith(adir)), None)
    if not src:
        print("No routing source for", adir)
        return
    rows, _ = DASH.gather(src, DASH._load_en50k())

    overrides = _load(os.path.join(adir, "..", "..", "curations", "tag_overrides.json"), {})

    out = {}
    for r in rows:
        w = r["word"]
        tags, base = _source_from_dashboard_row(r)
        # NOTE: membership is by TAG, not frequency. A one-off real Spanish
        # word (alguna, adelante) is still `core` → Main. "appears once" is not
        # an Extra criterion — many one-offs are standard vocab or lemma-mapping
        # misses that should merge to a recurring lemma.
        # manual override wins
        ov = overrides.get(w) or overrides.get(w.lower())
        if ov and ov.get("should_be"):
            forced = ov["should_be"][0]
            tags.append({"tag": forced, "source": "manual_override"})
            category = forced
        else:
            category = base
        out[w] = {"category": category, "corpus_count": r.get("count", 0), "tags": tags}

    outp = os.path.join(adir, "data", "known_vocab", "word_tags.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    from collections import Counter
    dist = Counter(v["category"] for v in out.values())
    print("Wrote %s (%d words)" % (outp, len(out)))
    for c, n in dist.most_common():
        print("  %-18s %d" % (c, n))


if __name__ == "__main__":
    main()
