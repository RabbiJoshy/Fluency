#!/usr/bin/env python3
"""Snapshot and restore the Spanish layer state, so a rerun can be undone whole.

The layers are interdependent: restoring individual archived files gives you a
state that never existed (assignments from one run, lemma map from another). This
captures everything at once and puts it back exactly.

    python3 pipeline/tool_snapshot_layers.py snapshot --label pre_rerun
    python3 pipeline/tool_snapshot_layers.py list
    python3 pipeline/tool_snapshot_layers.py verify <name>
    python3 pipeline/tool_snapshot_layers.py restore <name>

Notes
-----
* On APFS this uses copy-on-write clones (``cp -c``), so a snapshot is instant and
  costs almost no disk until a file is actually rewritten.
* ``sense_vectors/`` is excluded: it is a rebuildable embedding cache, already
  gitignored, and the largest thing here.
* The manifest records a sha256 per file AND the current ``{id: (word, lemma)}``
  map from vocabulary.json. Word IDs are ``md5(word|lemma)[:6]`` and learner
  progress is keyed on them, so a rerun that moves an ID silently orphans a card.
  ``verify`` reports moved IDs against the live deck; that is the check that
  matters, not the file hashes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SNAP_ROOT = REPO / "Data/Spanish/Intermediates/snapshots"

# What counts as "the layer state". Paths are relative to the repo root.
INCLUDE = [
    "Data/Spanish/layers",
    "Data/Spanish/vocabulary.json",
    "Data/Spanish/vocabulary.index.json",
    "Data/Spanish/vocabulary.examples.json",
    "Data/Spanish/runs",
]
EXCLUDE_DIRS = {"sense_vectors", "__pycache__"}
VOCAB = "Data/Spanish/vocabulary.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(rel: str):
    """Every file under an included path, skipping excluded directories."""
    root = REPO / rel
    if root.is_file():
        yield root
        return
    if not root.exists():
        return
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if EXCLUDE_DIRS & set(p.relative_to(root).parts):
            continue
        yield p


def id_map() -> dict:
    """{word_id: [word, lemma]} from the live deck — the progress-critical map."""
    p = REPO / VOCAB
    if not p.exists():
        return {}
    out = {}
    for e in json.load(p.open(encoding="utf-8")):
        if isinstance(e, dict) and e.get("id"):
            out[e["id"]] = [e.get("word"), e.get("lemma")]
    return out


def clone(src: Path, dst: Path) -> None:
    """APFS copy-on-write clone, falling back to a real copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["cp", "-c", str(src), str(dst)], check=True,
                       capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.copy2(src, dst)


def cmd_snapshot(args):
    name = (args.name or
            f"{dt.date.today().isoformat()}_{args.label or 'snapshot'}")
    dest = SNAP_ROOT / name
    if dest.exists():
        sys.exit(f"{dest} already exists — pick another --label or delete it")
    dest.mkdir(parents=True)

    files, total = {}, 0
    for rel in INCLUDE:
        for p in walk(rel):
            r = str(p.relative_to(REPO))
            clone(p, dest / "tree" / r)
            files[r] = {"sha256": sha256(p), "bytes": p.stat().st_size}
            total += files[r]["bytes"]
            if len(files) % 20 == 0:
                print(f"  {len(files)} files...", end="\r", flush=True)

    ids = id_map()
    manifest = {
        "name": name,
        "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": args.label or "",
        "note": args.note or "",
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "included": INCLUDE,
        "excluded_dirs": sorted(EXCLUDE_DIRS),
        "file_count": len(files),
        "total_bytes": total,
        "word_ids": len(ids),
        "files": files,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (dest / "word_ids.json").write_text(
        json.dumps(ids, ensure_ascii=False), encoding="utf-8")
    print(f"\nsnapshot {name}")
    print(f"  {len(files):,} files, {total/1e6:.0f} MB, {len(ids):,} word IDs")
    print(f"  -> {dest}")


def load(name: str):
    dest = SNAP_ROOT / name
    mp = dest / "manifest.json"
    if not mp.exists():
        sys.exit(f"no snapshot named {name} (looked in {SNAP_ROOT})")
    return dest, json.loads(mp.read_text(encoding="utf-8"))


def cmd_list(args):
    if not SNAP_ROOT.exists():
        return print("no snapshots yet")
    for d in sorted(SNAP_ROOT.iterdir()):
        mp = d / "manifest.json"
        if not mp.exists():
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        print(f"{m['name']:<34} {m['created'][:16]}  "
              f"{m['file_count']:>5} files  {m['total_bytes']/1e6:>6.0f} MB  "
              f"{m.get('note','')}")


def cmd_verify(args):
    dest, m = load(args.name)
    bad = miss = 0
    for rel, meta in m["files"].items():
        p = dest / "tree" / rel
        if not p.exists():
            miss += 1
            continue
        if sha256(p) != meta["sha256"]:
            print(f"  CORRUPT in snapshot: {rel}")
            bad += 1
    print(f"snapshot {m['name']}: {len(m['files'])} files, "
          f"{bad} corrupt, {miss} missing")

    # the check that actually matters: did any live word ID move?
    saved = json.loads((dest / "word_ids.json").read_text(encoding="utf-8"))
    live = id_map()
    if not live:
        return print("  (no live vocabulary.json to compare word IDs against)")
    gone = [i for i in saved if i not in live]
    changed = [i for i in saved if i in live and live[i] != saved[i]]
    print(f"  word IDs: {len(saved):,} in snapshot, {len(live):,} live, "
          f"{len(gone):,} gone, {len(changed):,} remapped")
    for i in (gone + changed)[:10]:
        print(f"    {i}: {saved[i]} -> {live.get(i, 'MISSING')}")
    if gone or changed:
        print("  ^ these cards would lose their progress")
    return 1 if (bad or miss) else 0


def cmd_restore(args):
    dest, m = load(args.name)
    if not args.yes:
        print(f"restore {m['name']} ({m['created']}) over the live tree?")
        print(f"  {m['file_count']:,} files, {m['total_bytes']/1e6:.0f} MB")
        print("  Anything currently in those paths and NOT in the snapshot is DELETED.")
        if input("  type 'restore' to continue: ").strip() != "restore":
            sys.exit("aborted")

    # remove live files under the included paths that the snapshot does not have,
    # so the result is the snapshot exactly, not a merge
    keep = set(m["files"])
    removed = 0
    for rel in m["included"]:
        for p in walk(rel):
            if str(p.relative_to(REPO)) not in keep:
                p.unlink()
                removed += 1

    written = 0
    for rel in m["files"]:
        src = dest / "tree" / rel
        tgt = REPO / rel
        if tgt.exists():
            tgt.unlink()
        clone(src, tgt)
        written += 1
    print(f"restored {written:,} files, removed {removed} that were not in the "
          f"snapshot")

    bad = [rel for rel, meta in m["files"].items()
           if sha256(REPO / rel) != meta["sha256"]]
    print("verify: all files match" if not bad else f"MISMATCH on {len(bad)} files")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--label"); s.add_argument("--name")
    s.add_argument("--note", default=""); s.set_defaults(fn=cmd_snapshot)
    s = sub.add_parser("list"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("verify"); s.add_argument("name"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("restore"); s.add_argument("name")
    s.add_argument("--yes", action="store_true"); s.set_defaults(fn=cmd_restore)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
