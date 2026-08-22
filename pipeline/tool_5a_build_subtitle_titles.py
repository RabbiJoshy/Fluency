#!/usr/bin/env python3
"""Resolve OpenSubtitles title_ids to human titles, offline.

Speech-mode examples carry `provenance.title_id` -- an OpenSubtitles id that is
the IMDb tconst without the `tt` prefix or zero padding (1256446 -> tt1256446).
The card had nothing to show for "where is this line from", which is the speech
equivalent of the song name an artist card prints.

Reads the IMDb dump already on disk (Data/Spanish/corpora/imdb/title.basics.tsv.gz,
gitignored, ~225 MB) and writes only the titles this corpus actually cites, so
the layer stays small and no lookup happens at build time.

76% of what this corpus cites is a TV EPISODE, and `title.basics` gives an
episode only its own title -- *Voir Dire*, *The Dog*, *Episode #1.7* -- which
names nothing a learner recognises. The episode-to-series link lives in a
separate dump, `title.episode.tsv.gz`. When that file is present each episode
also resolves its parent series and its season/episode numbers, and the layer
carries `series` so the card can read `Series -- Episode`. Without it the tool
behaves exactly as before rather than failing.

    curl -o Data/Spanish/corpora/imdb/title.episode.tsv.gz \\
        https://datasets.imdbws.com/title.episode.tsv.gz

    python3 pipeline/tool_5a_build_subtitle_titles.py --language spanish
"""
import argparse
import gzip
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read_basics(imdb, wanted_tconsts):
    """{tconst: (title, year, kind)} for the tconsts asked for."""
    found = {}
    with gzip.open(imdb, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.split("\t")
            if p[0] not in wanted_tconsts:
                continue
            found[p[0]] = (p[2], None if p[5] == "\\N" else p[5], p[1])
            if len(found) == len(wanted_tconsts):
                break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", default="spanish")
    ap.add_argument("--imdb", default="")
    ap.add_argument("--episodes", default="",
                    help="path to title.episode.tsv.gz. Defaults to the same "
                         "IMDb directory; absent means episodes keep their own "
                         "titles and no series is resolved.")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    lang = a.language.capitalize()
    layers = REPO / f"Data/{lang}/layers"
    imdb_dir = REPO / f"Data/{lang}/corpora/imdb"
    imdb = Path(a.imdb) if a.imdb else imdb_dir / "title.basics.tsv.gz"
    episodes_path = Path(a.episodes) if a.episodes else imdb_dir / "title.episode.tsv.gz"
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
    basics = _read_basics(imdb, set(keys))
    found = {}
    for tconst, (title, year, kind) in basics.items():
        found[keys[tconst]] = {"title": title, "year": year, "type": kind}

    n_episodes = sum(1 for v in found.values() if v["type"] == "tvEpisode")
    if n_episodes and episodes_path.exists():
        episode_tconsts = {tconst for tconst, v in basics.items()
                           if v[2] == "tvEpisode"}
        parents = {}
        with gzip.open(episodes_path, "rt", encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if p[0] not in episode_tconsts:
                    continue
                parents[p[0]] = (p[1],
                                 None if p[2] == "\\N" else p[2],
                                 None if p[3] == "\\N" else p[3])
                if len(parents) == len(episode_tconsts):
                    break
        series_basics = _read_basics(imdb, {v[0] for v in parents.values()})
        resolved = 0
        for tconst, (parent, season, number) in parents.items():
            meta = series_basics.get(parent)
            if not meta:
                continue
            entry = found[keys[tconst]]
            entry["series"] = meta[0]
            # The series' start year is more useful on a card than the
            # episode's own air year, but the episode year is what dates the
            # line, so both are kept and the builder chooses.
            entry["series_year"] = meta[1]
            if season:
                entry["season"] = season
            if number:
                entry["episode"] = number
            resolved += 1
        print(f"  {resolved:,} of {n_episodes:,} episodes resolved to a series")
    elif n_episodes:
        print(f"  {n_episodes:,} episodes have no series: {episodes_path.name} "
              f"not present. Download it to name the show:\n"
              f"    curl -o {episodes_path} "
              f"https://datasets.imdbws.com/title.episode.tsv.gz")

    out.write_text(json.dumps(found, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"resolved {len(found):,} of {len(want):,} -> {out.relative_to(REPO)}")
    for t, v in list(found.items())[:3]:
        label = f"{v['series']} — {v['title']}" if v.get("series") else v["title"]
        print(f"   {t} -> {label} ({v['year']}) [{v['type']}]")


if __name__ == "__main__":
    main()
