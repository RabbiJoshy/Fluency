#!/usr/bin/env python3
"""
Step 3: Tokenise lyrics and count word frequencies.

Genius batch JSONs -> minimal "evidence" vocab JSON:

Each entry:
{
  "word": "que",
  "corpus_count": 6710,
  "examples": [
    {"id": "11292773:8", "line": "La vida es una fiesta que un día termina"},
    ...
  ]
}

Design goals:
- No CSV stage
- No lemma / rank / meanings / English fields
- Keep corpus frequency (corpus_count) + evidence examples only
- Examples limited by --max_examples per word
- Example selection is:
  - max 1 example per song per word (best-scoring line from that song)
  - global diversification so the same songs aren’t reused everywhere
  - conservative line quality filtering
- Tokenization: letters only with optional internal apostrophes (pa’, callaíta’)

Usage:
  ./.venv/bin/python "Bad Bunny/scripts/3_count_words.py" \
    --batch_glob "Bad Bunny/data/input/batches/batch_*.json" \
    --out "Bad Bunny/data/word_counts/vocab_evidence.json" \
    --max_examples 10 \
    --preview 5
"""

import argparse
import glob
import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

try:
    from lingua import Language, LanguageDetectorBuilder
    _LINGUA_AVAILABLE = True
except ImportError:
    _LINGUA_AVAILABLE = False


# ====== Tokenization & cleaning ======
LETTER_CLASS = r"A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
WORD_RE = re.compile(rf"[{LETTER_CLASS}]+(?:'[{LETTER_CLASS}]+)*'?")
SECTION_LINE_RE = re.compile(r"^\[.*\]$")
_ADLIB_RE = re.compile(r'\[[^\]]*\]|\([^\)]*\)')
FOOTER_MARKERS = ["You might also like", "Embed"]
BOILERPLATE_LINE_RE = re.compile(
    r'… Read More'              # Truncated Genius annotation paragraphs
    r'|^\u2026 Read More'       # Unicode ellipsis variant
    r'|\.\.\. Read More'        # ASCII ellipsis variant
    r'|^Letra de "[^"]*"'       # Genius page title format
    r'|^-\s*Mashup:'            # Mashup tracklists
)

# Helps pick more "sentence-like" lines
CONNECTORS = {
    "que", "pero", "si", "cuando", "porque", "aunque",
    "con", "sin", "me", "te", "se", "nos", "ya",
    "pa'", "pal", "pa", "al", "del", "la", "el", "los", "las"
}

# ====== Lingua English line filter ======
_MIN_TOKENS_FOR_LID = 4           # lines with fewer tokens skip lingua (unreliable on short text)
_EN_CONFIDENCE_THRESHOLD = 0.70   # confidence threshold for classifying a line as English


# Genius embeds Cyrillic lookalike characters inside words to break scrapers.
# Map each known offender to its Latin equivalent.
_HOMOGLYPHS = {
    "\u0435": "e",   # Cyrillic е → e  (most common: despеrté, movе’, etc.)
    "\u0430": "a",   # Cyrillic а → a
    "\u043E": "o",   # Cyrillic о → o
    "\u0440": "r",   # Cyrillic р → r
    "\u0441": "c",   # Cyrillic с → c  (NB: also appears in "Русский" metadata, harmless)
    "\u0445": "x",   # Cyrillic х → x
    "\u0456": "i",   # Cyrillic і → i  (Ukrainian)
}
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPHS)


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u2018", "’").replace("\u2019", "’").replace("`", "’")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.translate(_HOMOGLYPH_TABLE)   # strip Genius homoglyph obfuscation
    return s


def clean_genius_lyrics(raw: str) -> str:
    """
    Removes Genius boilerplate:
    - skips placeholder lyrics ("yet to be transcribed", instrumentals)
    - strips leading 'Lyrics' section + editorial description paragraph
    - removes [Chorus]/[Verse] lines
    - cuts off common footer markers
    """
    if not raw:
        return ""

    # Skip Genius placeholder pages (no real lyrics)
    if ("yet to be transcribed" in raw or "yet to be released" in raw
            or "This song is an instrumental" in raw
            or "letra completa" in raw.lower()
            or "disponible pronto" in raw.lower()):
        return ""

    text = normalize_text(raw)

    idx = text.find("Lyrics")
    if idx != -1:
        text = text[idx + len("Lyrics"):]
        text = text.lstrip(" \n\t-–—:")

    # Strip Genius editorial description that appears after the "Lyrics" marker.
    # Two forms:
    #   1. Description ending with "Read More\xa0\n" or "… Read More\xa0\n"
    #   2. Description ending at first blank line (double newline)
    # The description is always a single prose paragraph about the song.
    rm_match = re.search(r'(?:…|\.\.\.|\u2026)?\s*Read More[\xa0\s]*\n', text)
    if rm_match:
        text = text[rm_match.end():]
    else:
        # No "Read More" — check if first chunk looks like a Genius editorial
        # description (long prose paragraph before actual lyrics after a blank line).
        # These descriptions reference the song in third person and use specific
        # meta-language patterns.
        first_break = text.find("\n\n")
        if first_break > 0:
            first_chunk = text[:first_break]
            chunk_lower = first_chunk.lower()
            is_editorial = (
                len(first_chunk) > 80
                and any(p in chunk_lower for p in (
                    '"', '\u201c',  # quoted song titles
                    'es una canción', 'es el primer', 'es el segundo',
                    'es la canción', 'sirve como', 'álbum de estudio',
                    'fue lanzad', 'fue publicad', 'fue estrenada',
                    'canción inédita', 'es un tema', 'tema que abre',
                ))
            )
            if is_editorial:
                text = text[first_break:]

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
        if BOILERPLATE_LINE_RE.search(s):
            continue
        lines.append(s)

    return "\n".join(lines).strip()


def strip_adlibs(text):
    # type: (str) -> str
    """Remove bracketed/parenthetical content (ad-libs, echoes, section tags) for counting."""
    return _ADLIB_RE.sub('', text).strip()


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


def _is_english_line(detector, line_text: str) -> bool:
    """Return True if lingua detects the line as English above the confidence threshold."""
    confs = detector.compute_language_confidence_values(line_text)
    if confs and confs[0].language == Language.ENGLISH and confs[0].value >= _EN_CONFIDENCE_THRESHOLD:
        return True
    return False


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


def filter_excluded_songs(songs: List[Dict[str, Any]], artist_dir: str) -> List[Dict[str, Any]]:
    """Remove duplicates, non-Spanish songs, and placeholders using duplicate_songs.json."""
    dedup_path = os.path.join(artist_dir, "data", "input", "duplicate_songs.json")
    if not os.path.exists(dedup_path):
        return songs

    with open(dedup_path, "r", encoding="utf-8") as f:
        dedup = json.load(f)

    skip_ids = set(dedup.get("duplicates", {}).keys())
    skip_ids |= set(dedup.get("non_spanish", {}).get("songs", {}).keys())
    skip_ids |= set(dedup.get("non_songs", {}).get("songs", {}).keys())
    skip_ids |= set(str(x) for x in dedup.get("placeholders", []))

    before = len(songs)
    songs = [s for s in songs if str(s.get("id")) not in skip_ids]
    skipped = before - len(songs)
    if skipped:
        print(f"Filtered {skipped} excluded songs (duplicates/non-Spanish/placeholders/non-songs), "
              f"{len(songs)} remaining")
    return songs


# ====== Core pipeline ======
def build_counts_and_candidates(
    songs: List[Dict[str, Any]],
    lid_detector=None,
) -> Tuple[Counter, Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    """
    Returns:
    - counts[word] = total occurrences across corpus
    - candidates[word] = list of candidate context lines across songs
    - lid_stats = summary of lingua English line filtering
    """
    counts: Counter = Counter()
    candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    lid_stats = {"lines_total": 0, "lines_skipped": 0, "lines_below_min_tokens": 0}

    # N-gram tracking for MWE detection (counted per unique line, not per word)
    _PHRASE_SPLIT_RE = re.compile(r'[,;:!?¡¿()"—\-]+')
    ngram_unigrams: Counter = Counter()
    ngram_counts: Dict[int, Counter] = {n: Counter() for n in range(2, 6)}
    ngram_songs: Dict[str, set] = defaultdict(set)
    seen_lines: set = set()  # deduplicate lines for n-gram counting

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
            # Strip ad-libs/brackets for counting; keep original for examples
            count_text = strip_adlibs(line_text)
            toks = tokenize(count_text) if count_text else []
            if not toks:
                continue
            lid_stats["lines_total"] += 1
            if lid_detector is not None:
                if len(toks) >= _MIN_TOKENS_FOR_LID:
                    if _is_english_line(lid_detector, line_text):
                        lid_stats["lines_skipped"] += 1
                        continue
                else:
                    lid_stats["lines_below_min_tokens"] += 1
            lines.append((line_no, line_text, toks))
            counts.update(toks)

            # Count n-grams once per unique line text (use cleaned text)
            if count_text not in seen_lines:
                seen_lines.add(count_text)
                for chunk in _PHRASE_SPLIT_RE.split(count_text):
                    chunk_toks = tokenize(chunk)
                    for t in chunk_toks:
                        ngram_unigrams[t] += 1
                    for n in range(2, 6):
                        for i in range(len(chunk_toks) - n + 1):
                            ng = " ".join(chunk_toks[i:i + n])
                            ngram_counts[n][ng] += 1
                            ngram_songs[ng].add(song_id)

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

        # Fallback: words with no good-quality candidate still get their best line
        for line_no, line_text, toks in lines:
            s = score_line(toks)
            for w in set(toks):
                if w not in best_for_word:
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

    ngram_data = {
        "unigrams": ngram_unigrams,
        "counts": ngram_counts,
        "songs": ngram_songs,
    }
    return counts, candidates, lid_stats, ngram_data


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
    Build final list of entries: word, corpus_count, examples[{id,line,title}]
    """
    items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    out: List[Dict[str, Any]] = []
    for word, c in items:
        ex_list = []
        for ex in selected_examples.get(word, []):
            ex_list.append({
                "id": f"{ex.get('song_id')}:{ex.get('line_no')}",
                "line": ex.get("line_text", "") or "",
                "title": ex.get("song_title", "")  # ADD THIS LINE
            })
        out.append({
            "word": word,
            "corpus_count": c,
            "examples": ex_list
        })
    return out


# ====== MWE detection ======

PIPELINE_DIR = None  # Set from --artist-dir in main()

FUNCTION_WORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "a", "en", "con", "por", "para", "sin",
    "que", "y", "o", "e", "ni", "u",
    "me", "te", "se", "nos", "le", "les", "lo",
    "mi", "tu", "su", "mis", "tus", "sus",
    "es", "no", "ya", "si",
})

# PMI thresholds
MIN_PMI = 12.0
MIN_PMI_COUNT = 5
MIN_PMI_SONGS = 3


def _load_step_json(filename):
    """Load from Artists/shared/ (curated data)."""
    from _artist_config import SHARED_DIR
    path = os.path.join(SHARED_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if "entries" in data:
        return data["entries"]
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _is_all_function_words(ngram):
    return all(w in FUNCTION_WORDS for w in ngram.split())


def _is_repetition(ngram):
    words = ngram.split()
    return len(set(words)) == 1


def _dedup_conjugation_families(confirmed, families):
    family_best = {}
    no_family = []
    for m in confirmed:
        family = families.get(m["expression"])
        if family is None:
            no_family.append(m)
        else:
            if family not in family_best or m["count"] > family_best[family]["count"]:
                family_best[family] = m
    return no_family + list(family_best.values())


def detect_mwes(ngram_data):
    """Detect MWEs using curated matching + PMI on n-gram data from the counting pass."""
    curated_mwes = _load_step_json("curated_mwes.json")
    skip_mwes = frozenset(_load_step_json("skip_mwes.json"))
    conjugation_families = _load_step_json("conjugation_families.json")

    unigrams = ngram_data["unigrams"]
    ng_counts = ngram_data["counts"]
    ng_songs = ngram_data["songs"]

    # Build a flat lookup: expression -> count (across all n-gram sizes)
    all_counts = {}
    for n in range(2, 6):
        all_counts.update(ng_counts[n])

    # Match curated MWEs against actual corpus counts
    confirmed = []
    matched_keys = set()
    for expression, translation in curated_mwes.items():
        count = all_counts.get(expression, 0)
        tokens = expression.split()
        if count > 0 or len(tokens) >= 4:
            confirmed.append({
                "expression": expression,
                "translation": translation,
                "count": count,
            })
            matched_keys.add(expression)

    # PMI-based detection
    total_tokens = sum(unigrams.values())
    pmi_detected = []
    for n, counts in ng_counts.items():
        total_ngrams = sum(counts.values())
        if total_ngrams == 0:
            continue
        for ng, count in counts.items():
            if count < MIN_PMI_COUNT:
                continue
            if ng in matched_keys or ng in skip_mwes:
                continue
            num_songs = len(ng_songs.get(ng, set()))
            if num_songs < MIN_PMI_SONGS:
                continue
            if _is_all_function_words(ng):
                continue
            if _is_repetition(ng):
                continue
            p_ngram = count / total_ngrams
            p_independent = 1.0
            for w in ng.split():
                p_independent *= unigrams[w] / total_tokens
            if p_independent == 0:
                continue
            pmi = math.log2(p_ngram / p_independent)
            if pmi < MIN_PMI:
                continue
            pmi_detected.append({
                "expression": ng,
                "translation": None,
                "count": count,
                "pmi": round(pmi, 1),
                "num_songs": num_songs,
            })

    # Dedup overlapping n-grams: drop shorter if substring of longer with >= PMI
    pmi_detected.sort(key=lambda x: (-len(x["expression"].split()), -x["pmi"]))
    kept = []
    kept_exprs = []
    for r in pmi_detected:
        if not any(r["expression"] in longer for longer in kept_exprs):
            kept.append(r)
            kept_exprs.append(r["expression"])
    pmi_detected = sorted(kept, key=lambda x: -x["pmi"])

    # Post-process curated
    confirmed = [m for m in confirmed if m["expression"] not in skip_mwes]
    confirmed = _dedup_conjugation_families(confirmed, conjugation_families)
    confirmed.sort(key=lambda x: -x["count"])

    return confirmed, pmi_detected


def main():
    global PIPELINE_DIR

    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True, help="Path to artist data directory")
    ap.add_argument("--batch_glob", required=True, help='e.g. "Artists/Bad Bunny/data/input/batches/batch_*.json"')
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--mwe-out", default=None, help="MWE output JSON path (default: same dir as --out)")
    ap.add_argument("--max_examples", type=int, default=10, help="Maximum examples per word")
    ap.add_argument("--preview", type=int, default=0, help="Print first N entries after writing")
    ap.add_argument("--no-lid", action="store_true",
                    help="Disable lingua English line detection")

    args = ap.parse_args()
    PIPELINE_DIR = os.path.abspath(args.artist_dir)

    songs = iter_songs_from_batches(args.batch_glob)
    songs = filter_excluded_songs(songs, args.artist_dir)

    lid_detector = None
    if not args.no_lid:
        if _LINGUA_AVAILABLE:
            print("Building lingua detector (Spanish + English)...")
            lid_detector = LanguageDetectorBuilder.from_languages(
                Language.SPANISH, Language.ENGLISH
            ).build()
        else:
            print("WARNING: lingua not installed — skipping English line detection. "
                  "Install with: pip install lingua-language-detector")

    counts, candidates, lid_stats, ngram_data = build_counts_and_candidates(songs, lid_detector=lid_detector)
    selected = select_examples(counts, candidates, max_examples_per_word=args.max_examples)
    out_list = to_evidence_json(counts, selected)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(out_list):,} words -> {args.out}")
    if lid_stats["lines_skipped"] > 0:
        eligible = lid_stats["lines_total"] - lid_stats["lines_below_min_tokens"]
        pct = lid_stats["lines_skipped"] / eligible * 100 if eligible else 0
        print(f"  Lingua: {lid_stats['lines_skipped']:,} / {eligible:,} eligible lines "
              f"skipped as English ({pct:.1f}%)")
        print(f"  Lines below {_MIN_TOKENS_FOR_LID}-token minimum: "
              f"{lid_stats['lines_below_min_tokens']:,}")
    elif lid_detector is not None:
        print("  Lingua: no English lines detected")

    # MWE detection
    confirmed, pmi_detected = detect_mwes(ngram_data)
    mwe_out_path = args.mwe_out or os.path.join(os.path.dirname(args.out), "mwe_detected.json")
    mwe_output = {
        "mwes": [
            {"expression": m["expression"], "translation": m["translation"], "count": m["count"]}
            for m in confirmed
        ] + [
            {"expression": m["expression"], "translation": None, "count": m["count"],
             "pmi": m["pmi"], "num_songs": m["num_songs"]}
            for m in pmi_detected
        ],
        "candidates": [],  # Legacy field, no longer used
        "stats": {
            "confirmed_count": len(confirmed),
            "pmi_detected_count": len(pmi_detected),
        },
    }
    with open(mwe_out_path, "w", encoding="utf-8") as f:
        json.dump(mwe_output, f, ensure_ascii=False, indent=2)
    print(f"  MWE: {len(confirmed)} curated, {len(pmi_detected)} PMI-detected -> {mwe_out_path}")

    if confirmed:
        print("\n  Top 10 curated MWEs:")
        for m in confirmed[:10]:
            print(f"    {m['count']:4d}  {m['expression']:<25s}  {m['translation']}")
    if pmi_detected:
        print(f"\n  Top 10 PMI-detected (no translation):")
        for m in pmi_detected[:10]:
            print(f"    {m['count']:4d}  PMI={m['pmi']:5.1f}  songs={m['num_songs']:2d}  {m['expression']}")

    if args.preview and args.preview > 0:
        print("\n=== PREVIEW ===")
        print(json.dumps(out_list[:args.preview], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
