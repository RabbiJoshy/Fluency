#!/usr/bin/env python3
"""
bad_bunny_evidence_pipeline.py.py

Genius batch JSONs -> minimal "evidence" vocab JSON:

Each entry:
{
  "word": "que",
  "occurrences_ppm": 36382.761837,
  "examples": [
    {"id": "11292773:8", "line": "La vida es una fiesta que un día termina"},
    ...
  ]
}

Design goals:
- No CSV stage
- No lemma / rank / meanings / English fields
- Keep corpus frequency (occurrences_ppm) + evidence examples only
- Examples limited by --max_examples per word
- Example selection is:
  - max 1 example per song per word (best-scoring line from that song)
  - global diversification so the same songs aren’t reused everywhere
  - conservative line quality filtering
- Tokenization: letters only with optional internal apostrophes (pa', callaíta')

Usage:
  ./.venv/bin/python "Bad Bunny/bad_bunny_evidence_pipeline.py.py" \
    --batch_glob "Bad Bunny/bad_bunny_genius/batch_*.json" \
    --out "Bad Bunny/intermediates/2_vocab_evidence.json" \
    --max_examples 10 \
    --preview 5
"""

import argparse
import glob
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple


# ====== Tokenization & cleaning ======
LETTER_CLASS = r"A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
WORD_RE = re.compile(rf"[{LETTER_CLASS}]+(?:'[{LETTER_CLASS}]+)*'?")
SECTION_LINE_RE = re.compile(r"^\[.*\]$")
FOOTER_MARKERS = ["You might also like", "Embed"]

# Helps pick more "sentence-like" lines
CONNECTORS = {
    "que", "pero", "si", "cuando", "porque", "aunque",
    "con", "sin", "me", "te", "se", "nos", "ya",
    "pa'", "pal", "pa", "al", "del", "la", "el", "los", "las"
}


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = s.replace("–", "-").replace("—", "-")
    return s


def clean_genius_lyrics(raw: str) -> str:
    """
    Removes Genius boilerplate:
    - strips leading 'Lyrics' section
    - removes [Chorus]/[Verse] lines
    - cuts off common footer markers
    """
    if not raw:
        return ""
    text = normalize_text(raw)

    idx = text.find("Lyrics")
    if idx != -1:
        text = text[idx + len("Lyrics"):]
        text = text.lstrip(" \n\t-–—:")

    cut_positions = []
    for marker in FOOTER_MARKERS:
        j = text.find(marker)
        if j != -1:
            cut_positions.append(j)
    if cut_positions:
        text = text[:min(cut_positions)]

    lines: List[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if SECTION_LINE_RE.match(s):
            continue
        lines.append(s)

    return "\n".join(lines).strip()


def tokenize(line: str) -> List[str]:
    """letters only, optional internal apostrophes"""
    return [m.group(0).lower() for m in WORD_RE.finditer(line)]


def is_good_context_line(tokens: List[str]) -> bool:
    # conservative filtering
    if len(tokens) < 5:
        return False
    # repeated filler lines like "eh eh eh eh"
    if len(tokens) >= 6 and len(set(tokens)) <= 2:
        return False
    return True


def score_line(tokens: List[str]) -> int:
    # heuristic scoring to choose more helpful examples
    n = len(tokens)
    score = 0
    if 7 <= n <= 16:
        score += 3
    elif 5 <= n <= 20:
        score += 1
    if any(t in CONNECTORS for t in tokens):
        score += 1
    if n > 24:
        score -= 2
    return score


# ====== Input loader ======
def iter_songs_from_batches(batch_glob: str) -> List[Dict[str, Any]]:
    paths = sorted(glob.glob(batch_glob))
    if not paths:
        raise ValueError(f"No files matched --batch_glob {batch_glob}. cwd={os.getcwd()}")

    songs: List[Dict[str, Any]] = []
    for batch_i, path in enumerate(paths):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{path} did not contain a JSON list.")
        for s in data:
            if isinstance(s, dict):
                s["__batch"] = batch_i
                songs.append(s)
    return songs


# ====== Core pipeline ======
def build_counts_and_candidates(
    songs: List[Dict[str, Any]]
) -> Tuple[Counter, Dict[str, List[Dict[str, Any]]]]:
    """
    Returns:
    - counts[word] = total occurrences across corpus
    - candidates[word] = list of candidate context lines across songs
    """
    counts: Counter = Counter()
    candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for song in songs:
        raw_lyrics = song.get("lyrics")
        if not raw_lyrics:
            continue

        song_id = song.get("id")
        title = song.get("title") or ""
        batch_i = song.get("__batch", -1)

        clean = clean_genius_lyrics(raw_lyrics)
        if not clean:
            continue

        lines: List[Tuple[int, str, List[str]]] = []
        for line_no, line_text in enumerate(clean.split("\n"), start=1):
            line_text = line_text.strip()
            if not line_text:
                continue
            toks = tokenize(line_text)
            if not toks:
                continue
            lines.append((line_no, line_text, toks))
            counts.update(toks)

        # best line per word per song => enforces max 1 context per song per word
        best_for_word: Dict[str, Tuple[int, int, str]] = {}
        for line_no, line_text, toks in lines:
            if not is_good_context_line(toks):
                continue
            s = score_line(toks)
            for w in set(toks):
                prev = best_for_word.get(w)
                if prev is None or s > prev[0]:
                    best_for_word[w] = (s, line_no, line_text)

        for w, (s, line_no, line_text) in best_for_word.items():
            candidates[w].append({
                "score": s,
                "batch": batch_i,
                "song_id": song_id,
                "line_no": line_no,
                "line_text": line_text,
                "song_title": title,
            })

    return counts, candidates


def select_examples(
    counts: Counter,
    candidates: Dict[str, List[Dict[str, Any]]],
    max_examples_per_word: int
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Select up to max_examples_per_word per word.
    Prefers:
    - songs used less globally (diversification)
    - higher scoring lines
    """
    selected: Dict[str, List[Dict[str, Any]]] = {}
    global_song_use = Counter()

    words_by_freq = sorted(candidates.keys(), key=lambda w: (-counts[w], w))

    for w in words_by_freq:
        cands = candidates[w]
        cands_sorted = sorted(
            cands,
            key=lambda d: (global_song_use[d["song_id"]], -d["score"], d["batch"], str(d["song_id"]))
        )

        chosen: List[Dict[str, Any]] = []
        used_songs_for_word = set()

        for d in cands_sorted:
            if len(chosen) >= max_examples_per_word:
                break
            sid = d["song_id"]
            if sid in used_songs_for_word:
                continue
            used_songs_for_word.add(sid)
            chosen.append(d)

        for d in chosen:
            global_song_use[d["song_id"]] += 1

        # strip selection-only fields to keep output small
        for d in chosen:
            d.pop("score", None)
            d.pop("batch", None)
            # d.pop("song_title", None)  # COMMENT OUT OR REMOVE THIS LINE

        selected[w] = chosen

    return selected


def to_evidence_json(
    counts: Counter,
    selected_examples: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Build final list of entries: word, occurrences_ppm, examples[{id,line,title}]
    """
    total = sum(counts.values()) or 1
    items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    out: List[Dict[str, Any]] = []
    for word, c in items:
        ppm = (c / total) * 1_000_000.0
        ex_list = []
        for ex in selected_examples.get(word, []):
            ex_list.append({
                "id": f"{ex.get('song_id')}:{ex.get('line_no')}",
                "line": ex.get("line_text", "") or "",
                "title": ex.get("song_title", "")  # ADD THIS LINE
            })
        out.append({
            "word": word,
            "occurrences_ppm": ppm,
            "examples": ex_list
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch_glob", required=True, help='e.g. "Bad Bunny/bad_bunny_genius/batch_*.json"')
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--max_examples", type=int, default=10, help="Maximum examples per word")
    ap.add_argument("--preview", type=int, default=0, help="Print first N entries after writing")

    args = ap.parse_args()

    songs = iter_songs_from_batches(args.batch_glob)
    counts, candidates = build_counts_and_candidates(songs)
    selected = select_examples(counts, candidates, max_examples_per_word=args.max_examples)
    out_list = to_evidence_json(counts, selected)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)

    print(f"✅ Wrote {len(out_list):,} words -> {args.out}")

    if args.preview and args.preview > 0:
        print("\n=== PREVIEW ===")
        print(json.dumps(out_list[:args.preview], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
