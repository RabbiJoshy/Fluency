#!/usr/bin/env python3
"""tool_8b_cognate_would_hide.py — blast-radius report for the cognate filter.

The shared `Data/Spanish/layers/cognates.json` layer carries an auto-generated
`cognate_score` per `word|lemma` (from step_7c's CogNet/similarity scorer). When
step_8b stamps it (only with --stamp-cognate-scores; OFF by default) the front
end hides every card scoring >= threshold (default 0.85, `excludeCognates` ON).
That scorer is noisy: it links high-frequency function words to English via junk
paths (estar|estar -> 1.0 via "star"), so enabling it would silently hide real
core vocabulary.

This tool answers "if I turned stamping on, what currently-visible cards would
disappear?" It is READ-ONLY. Run it before enabling --stamp-cognate-scores, and
use its buckets to decide what (if anything) to clean out of the layer first.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/tool_8b_cognate_would_hide.py \
        --artist-dir "Artists/spanish/Bad Bunny" [--threshold 0.85]
"""
import argparse
import glob
import json
import os

# Copulas / auxiliaries / high-frequency grammatical verbs the CogNet scorer
# mislabels — hiding any of these breaks the deck. Categorization only; the tool
# does not modify anything.
COPULA_AUX = {
    "estar", "ser", "haber", "ir", "tener", "hacer", "poder", "querer",
    "saber", "deber", "soler",
}
GRAMMATICAL = {  # possessives / prepositions / determiners that aren't vocabulary cognates
    "tuyo", "tuya", "mío", "mía", "suyo", "nuestro", "contra", "sin", "sobre",
    "cada", "tanto", "mismo",
}

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_index(artist_dir):
    # Prefer the live (unsuffixed) deck over parallel decks like *_wikt.
    cands = sorted(glob.glob(os.path.join(artist_dir, "*vocabulary.index.json")))
    live = [c for c in cands if "_" not in os.path.basename(c).replace("vocabulary.index.json", "")]
    return (live or cands or [None])[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artist-dir", required=True,
                    help='e.g. "Artists/spanish/Bad Bunny"')
    ap.add_argument("--index-path", default=None,
                    help="Override the auto-detected *vocabulary.index.json")
    ap.add_argument("--master-path", default=None,
                    help="Override the default {artist-parent}/vocabulary_master.json")
    ap.add_argument("--cognates-path",
                    default=os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "cognates.json"))
    ap.add_argument("--threshold", type=float, default=0.85,
                    help="Hide threshold (front-end default 0.85)")
    ap.add_argument("--top", type=int, default=40, help="Rows to print")
    ap.add_argument("--out", default=None,
                    help="Report JSON path (default {artist-dir}/data/reports/cognate_would_hide.json)")
    args = ap.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    index_path = args.index_path or find_index(artist_dir)
    if not index_path or not os.path.exists(index_path):
        raise SystemExit("Could not find a *vocabulary.index.json under %s" % artist_dir)
    master_path = args.master_path or os.path.join(os.path.dirname(artist_dir), "vocabulary_master.json")

    idx = _load(index_path)
    master = _load(master_path)
    cog = _load(args.cognates_path)
    mrows = master if isinstance(master, dict) else {r["id"]: r for r in master}

    def norm(o):
        if isinstance(o, (int, float)):
            return {"score": o}
        if o is True:
            return {"score": 1.0}
        return o or None

    would = []
    for r in idx:
        iid, cc = r.get("id"), r.get("corpus_count", 0)
        m = mrows.get(iid)
        if not m:
            continue
        # Currently visible = not already hidden by another signal.
        if (m.get("is_transparent_cognate") or m.get("is_english")
                or m.get("is_noise") or m.get("is_propernoun_corpus")):
            continue
        w = (m.get("word") or "").lower()
        lem = (m.get("lemma") or "").lower()
        obj = norm(cog.get("%s|%s" % (w, lem)))
        if not obj or obj.get("score", 0) < args.threshold:
            continue
        if lem in COPULA_AUX:
            bucket = "copula_aux"          # deck-breaking — never hide
        elif lem in GRAMMATICAL or (obj.get("score") == 1.0 and not obj.get("cognet")):
            bucket = "likely_false_positive"  # possessives / 1.0-no-cognet junk
        else:
            bucket = "likely_real_cognate"    # grande, mucho, problema... hiding is defensible
        would.append({
            "id": iid, "word": w, "lemma": lem, "corpus_count": cc,
            "score": obj.get("score"), "cognet": bool(obj.get("cognet")),
            "gemini": bool(obj.get("gemini")), "bucket": bucket,
        })

    would.sort(key=lambda x: -x["corpus_count"])
    by_bucket = {}
    for x in would:
        by_bucket.setdefault(x["bucket"], []).append(x)

    print("Would-hide report — %s" % os.path.basename(index_path))
    print("threshold >= %.2f | %d currently-visible cards would be hidden if "
          "--stamp-cognate-scores were on\n" % (args.threshold, len(would)))
    for b in ("copula_aux", "likely_false_positive", "likely_real_cognate"):
        rows = by_bucket.get(b, [])
        occ = sum(x["corpus_count"] for x in rows)
        print("  %-22s %4d cards / %5d occurrences" % (b, len(rows), occ))
    print("\n%5s  %-14s%-14s%6s  %-22s" % ("cc", "word", "lemma", "score", "bucket"))
    for x in would[:args.top]:
        print("%5d  %-14s%-14s%6.2f  %-22s" % (
            x["corpus_count"], x["word"], x["lemma"], x["score"], x["bucket"]))

    out = args.out or os.path.join(artist_dir, "data", "reports", "cognate_would_hide.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "index": os.path.basename(index_path),
            "threshold": args.threshold,
            "total_would_hide": len(would),
            "bucket_counts": {b: len(v) for b, v in by_bucket.items()},
            "cards": would,
        }, f, ensure_ascii=False, indent=2)
    print("\nReport -> %s" % out)


if __name__ == "__main__":
    main()
