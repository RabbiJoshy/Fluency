#!/usr/bin/env python3
"""tool_8b_rebuild_diff.py — compare a sandbox rebuild against the live deck.

The live artist deck is a stale positional snapshot; a rebuild (`step_8b
--output-suffix _sandbox`, then `tool_8c --master ..._sandbox.json`) fixes the
homograph survivors, recovers orphaned words, and re-aligns senses — but it also
re-keys nothing it shouldn't. This tool diffs LIVE vs SANDBOX so the rebuild can
be reviewed BEFORE it's promoted over the live files. READ-ONLY.

It answers the questions that decide "is this better, or just different?":
  - Did the homograph survivors get fixed?  (para/como/todo/cara/fue…)
  - Which words does the rebuild recover (had no card) / lose (regressions)?
  - Do any cards you have progress on change ID?  (progress-migration risk)
  - Did the tool_8c curations re-apply to the sandbox master?
  - Are the P2/P4 flag fixes present (no cognate_score; baby/flow hidden)?

Usage (from project root, after building the sandbox):
    .venv/bin/python3 pipeline/artist/tool_8b_rebuild_diff.py \
        --artist-dir "Artists/spanish/Bad Bunny" --suffix _sandbox

Self-test (no rebuild needed — diffs live against itself, everything zero):
    ... --suffix ""
"""
import argparse
import glob
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPOTLIGHT = ["para", "como", "todo", "cara", "fue", "fui", "fuiste",
             "camino", "baja", "cuenta", "puesto", "piso"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stem(artist_dir):
    cands = sorted(glob.glob(os.path.join(artist_dir, "*vocabulary.index.json")))
    live = [c for c in cands
            if os.path.basename(c).replace("vocabulary.index.json", "").count("_") == 0]
    p = (live or cands or [None])[0]
    if not p:
        raise SystemExit("No *vocabulary.index.json under %s" % artist_dir)
    return os.path.basename(p)[:-len(".index.json")]  # e.g. "BadBunnyvocabulary"


def _mrows(master):
    return master if isinstance(master, dict) else {r["id"]: r for r in master}


def _gloss(entry):
    s = entry.get("senses") or entry.get("meanings") or []
    if not s:
        return ""
    return s[0].get("translation") or s[0].get("meaning") or ""


def load_deck(artist_dir, stem, suffix):
    idx = _load(os.path.join(artist_dir, "%s%s.index.json" % (stem, suffix)))
    master = _mrows(_load(os.path.join(
        os.path.dirname(artist_dir), "vocabulary_master%s.json" % suffix)))
    cc = {r["id"]: r.get("corpus_count", 0) for r in idx}
    # renderable = index id joins a master entry with a non-blank first gloss
    render = {}
    for r in idx:
        e = master.get(r["id"])
        if e and _gloss(e).strip():
            render[r["id"]] = e
    return {"idx": idx, "master": master, "cc": cc, "render": render}


def wl(e):
    return ((e.get("word") or "").lower(), (e.get("lemma") or "").lower())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artist-dir", required=True)
    ap.add_argument("--suffix", required=True,
                    help='sandbox suffix, e.g. "_sandbox" ("" self-tests live vs live)')
    ap.add_argument("--out", default=None, help="progress id-migration JSON path")
    args = ap.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    stem = _stem(artist_dir)
    live = load_deck(artist_dir, stem, "")
    new = load_deck(artist_dir, stem, args.suffix)

    print("=" * 70)
    print("REBUILD DIFF — %s  (live  vs  %s%s)" % (stem, stem, args.suffix or " [self]"))
    print("=" * 70)
    print("\n[1] Card counts")
    print("  master entries : live %6d   new %6d" % (len(live["master"]), len(new["master"])))
    print("  index rows     : live %6d   new %6d" % (len(live["idx"]), len(new["idx"])))
    print("  renderable     : live %6d   new %6d" % (len(live["render"]), len(new["render"])))

    # --- [2] Homograph spotlight -----------------------------------------
    def cards_for(deck, word):
        out = []
        for iid, e in deck["render"].items():
            if (e.get("word") or "").lower() == word:
                out.append((deck["cc"].get(iid, 0), "%s|%s" % (e["word"], e["lemma"]), _gloss(e)))
        return sorted(out, reverse=True)
    print("\n[2] Homograph / lemma spotlight (the survivor cards)")
    for w in SPOTLIGHT:
        lc, nc = cards_for(live, w), cards_for(new, w)
        if not lc and not nc:
            continue
        def fmt(cs):
            return " ; ".join("%s=%r(n%d)" % (k, g[:22], cc) for cc, k, g in cs) or "—"
        flag = "  <-- CHANGED" if fmt(lc) != fmt(nc) else ""
        print("  %-8s live: %s" % (w, fmt(lc)))
        print("  %-8s  new: %s%s" % ("", fmt(nc), flag))

    # --- [3]/[4] recovered & lost renderable (word,lemma) ----------------
    live_wl = {wl(e) for e in live["render"].values()}
    new_wl = {wl(e) for e in new["render"].values()}
    new_by_wl = {}
    for iid, e in new["render"].items():
        new_by_wl.setdefault(wl(e), (new["cc"].get(iid, 0), iid))
    recovered = sorted(((new_by_wl[k][0], k) for k in (new_wl - live_wl)), reverse=True)
    live_by_wl = {}
    for iid, e in live["render"].items():
        live_by_wl.setdefault(wl(e), (live["cc"].get(iid, 0), iid))
    lost = sorted(((live_by_wl[k][0], k) for k in (live_wl - new_wl)), reverse=True)
    print("\n[3] RECOVERED words (renderable in new, not in live): %d" % len(recovered))
    for cc, (w, l) in recovered[:20]:
        print("      +%-5d %s|%s" % (cc, w, l))
    print("\n[4] LOST words (renderable in live, not in new — REGRESSIONS to check): %d" % len(lost))
    for cc, (w, l) in lost[:20]:
        print("      -%-5d %s|%s" % (cc, w, l))

    # --- [5] progress id-migration risk ----------------------------------
    # Progress is keyed to the LIVE index id. For every renderable live card,
    # does its (word,lemma) resolve to a DIFFERENT id in the new master?
    new_wl_to_id = {}
    for mid, e in new["master"].items():
        new_wl_to_id.setdefault(wl(e), mid)
    migration = {}
    for iid, e in live["render"].items():
        # If the card's own id still exists in the new master, progress carries
        # over unchanged — no migration (handles duplicate (word,lemma) safely).
        if iid in new["master"]:
            continue
        nid = new_wl_to_id.get(wl(e))
        if nid and nid != iid:
            migration[iid] = nid
    print("\n[5] Progress id-migration: %d renderable live cards change id" % len(migration))
    if migration:
        out = args.out or os.path.join(artist_dir, "data", "reports",
                                       "progress_id_migration%s.json" % args.suffix)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(migration, f, ensure_ascii=False, indent=2)
        print("      -> %s  (apply to progress + FlaggedWords before promoting)" % out)
        for old, nw in list(migration.items())[:8]:
            e = live["render"][old]
            print("      %s -> %s  (%s|%s)" % (old, nw, e["word"], e["lemma"]))
    else:
        print("      none — progress carries over unchanged (id reuse worked).")

    # --- [6] curation re-application spot-check --------------------------
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "t8c", os.path.join(PROJECT_ROOT, "pipeline", "tool_8c_patch_master_curated.py"))
        t8c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t8c)
        checked = applied = missing = 0
        misses = []
        for o in t8c.OVERRIDES:
            e = new["master"].get(o["key"])
            if not e or e.get("word") != o["word"]:
                continue
            checked += 1
            ok = True
            if o.get("lemma") and e.get("lemma") != o["lemma"]:
                ok = False
            for si, fields in (o.get("senses") or {}).items():
                senses = e.get("senses") or []
                si = int(si)
                if si >= len(senses):
                    ok = False; break
                for fld, val in fields.items():
                    if senses[si].get(fld) != val:
                        ok = False
            applied += ok
            if not ok and len(misses) < 8:
                misses.append("%s(%s)" % (o["word"], o["key"]))
        print("\n[6] tool_8c curation re-application: %d/%d overrides matched in new master"
              % (applied, checked))
        if misses:
            print("      NOT matched (re-run tool_8c --master, or sense layout shifted): "
                  + ", ".join(misses))
    except Exception as ex:  # pragma: no cover
        print("\n[6] curation check skipped: %s" % ex)

    # --- [7] P2/P4 flag checks -------------------------------------------
    new_cog_scores = sum(1 for r in new["idx"] if r.get("cognate_score") is not None)
    def hidden_cog(deck, word):
        for e in deck["master"].values():
            if (e.get("word") or "").lower() == word:
                return e.get("is_transparent_cognate", False)
        return None
    print("\n[7] P2/P4 flag checks (new deck)")
    print("      cognate_score stamped on index rows: %d  (expect 0 — P2 default off)"
          % new_cog_scores)
    for w in ("baby", "flow", "haters"):
        print("      %-8s is_transparent_cognate: %s  (expect True — P4)" % (w, hidden_cog(new, w)))

    print("\n" + "=" * 70)
    verdict = []
    if lost:
        verdict.append("%d LOST words — inspect before promoting" % len(lost))
    if migration:
        verdict.append("%d id changes — apply migration to progress first" % len(migration))
    if new_cog_scores:
        verdict.append("cognate_score present — P2 not applied (did you pass --stamp-cognate-scores?)")
    print("VERDICT: " + ("OK to review for promotion" if not verdict else " | ".join(verdict)))
    print("=" * 70)


if __name__ == "__main__":
    main()
