#!/usr/bin/env python3
"""Resolve OpenSubtitles title_ids to human titles, offline.

Speech-mode examples carry `provenance.title_id` -- an OpenSubtitles id that is
the IMDb tconst without the `tt` prefix or zero padding (1256446 -> tt1256446).
The card had nothing to show for "where is this line from", which is the speech
equivalent of the song name an artist card prints.

Reads the IMDb dump already on disk (Data/Spanish/corpora/imdb/title.basics.tsv.gz,
gitignored, ~225 MB) and writes only the titles this corpus actually cites, so
the layer stays small and no lookup happens at build time.

    python3 pipeline/tool_5a_build_subtitle_titles.py --language spanish
"""
import argparse
import gzip
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", default="spanish")
    ap.add_argument("--imdb", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    lang = a.language.capitalize()
    layers = REPO / f"Data/{lang}/layers"
    imdb = Path(a.imdb) if a.imdb else REPO / f"Data/{lang}/corpora/imdb/title.basics.tsv.gz"
    out = Path(a.out) if a.out else layers / "subtitle_titles.json"

    examples = json.loads((layers / "examples_raw.json").read_text(encoding="utf-8"))
    want = set()
    for entries in examples.values():
        for e in entries:
            tid = ((e.get("provenance") or {}).get("title_id") or "").strip()
            if tid.isdigit():
                want.add(tid)
    print(f"{len(want):,} distinct title_ids cited by the corpus")
    if not imdb.exists():
        raise SystemExit(f"IMDb dump not found at {imdb}")

    keys = {f"tt{int(t):07d}": t for t in want}
    found = {}
    with gzip.open(imdb, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.split("\t")
            tid = keys.get(p[0])
            if tid is None:
                continue
            title, year, kind = p[2], p[5], p[1]
            found[tid] = {"title": title, "year": None if year == "\\N" else year,
                          "type": kind}
            if len(found) == len(keys):
                break
    out.write_text(json.dumps(found, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"resolved {len(found):,} of {len(want):,} -> {out.relative_to(REPO)}")
    for t, v in list(found.items())[:3]:
        print(f"   {t} -> {v['title']} ({v['year']}) [{v['type']}]")


if __name__ == "__main__":
    main()
