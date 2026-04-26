#!/usr/bin/env python3
"""
Step 2: Tokenise lyrics and count word frequencies.

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
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

# Bump when counting logic, tokenization, or output schema changes in a way
# that invalidates existing vocab_evidence.json files.
STEP_VERSION = 3
STEP_VERSION_NOTES = {
    1: "lingua English filter + MWE detection + max-examples-per-word",
    2: "+ multi-word elision split with surface preservation on examples",
    3: "+ strip hyphen-chain ad-libs (ah-na-na, aca-ca-ca, Ba-Ba-Baila) "
       "before tokenization — prevents ad-lib stutters polluting short-"
       "token counts that later merge into real words via elision",
}

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

# Hyphen-chain ad-libs: 2+ short (≤3-char) hyphen-separated chunks. These
# are stylistic stutters / onomatopoeia / elongated syllables in lyrics —
# "ah-na-na", "woh-na-na-na", "ja-ja-ja", "aca-ca-ca-ca", "flo-flo",
# "preguntó-tó-tó-tó", "Mé-Mé-Métele", "Ba-Ba-Baila". Because WORD_RE
# tokenizes on hyphen boundaries each chunk would otherwise become a
# separate token, inflating the count of short fragments that, via the
# elision merge (na → nada, tó → todo, etc.), pollute real words' example
# lists with ad-lib lyrics. Stripping these sequences BEFORE WORD_RE
# runs removes them from counting entirely while leaving genuine short-
# word usage ("no sé na", "pa'l") untouched.
#
# Requires both sides of every hyphen to be ≤3 chars so long compounds
# like "ex-presidente" or "post-guerra" pass through unchanged.
_HYPHEN_ADLIB_RE = re.compile(
    rf"\b[{LETTER_CLASS}]{{1,3}}(?:-[{LETTER_CLASS}]{{1,3}}){{1,}}\b",
    re.IGNORECASE,
)


def strip_hyphen_adlibs(text: str) -> str:
    """Remove runs of 2+ short hyphen-separated tokens from ``text``."""
    return _HYPHEN_ADLIB_RE.sub(" ", text)
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
    """letters only, optional internal apostrophes.

    Strips hyphen-chain ad-libs ("ah-na-na-na", "Ba-Ba-Baila",
    "preguntó-tó-tó") before WORD_RE runs so stutters don't inflate the
    counts of their short fragments. See ``_HYPHEN_ADLIB_RE`` docstring.
    """
    line = strip_hyphen_adlibs(line)
    return [m.group(0).lower() for m in WORD_RE.finditer(line)]


# ====== Multi-word elision expansion ======
# Contractions like ``pa'l`` fuse two Spanish words ("para el"). Splitting at
# tokenize time routes each component to its own lemma while preserving the
# original lyric surface on each resulting token (so the UI can display
# "pa'l" as the source form on BOTH the `para` and `el` flashcards).

_MULTI_WORD_ELISIONS: Dict[str, List[str]] = {}


def load_multi_word_elisions(shared_dir: str) -> Dict[str, List[str]]:
    """Load shared multi-word elision table: surface → [expanded tokens]."""
    path = os.path.join(shared_dir, "multi_word_elisions.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries", {})
    out: Dict[str, List[str]] = {}
    for surface, expansion in entries.items():
        # values may be strings ("para el") or lists (["para","el"])
        if isinstance(expansion, str):
            toks = [t.lower() for t in expansion.split() if t]
        elif isinstance(expansion, list):
            toks = [str(t).lower() for t in expansion if t]
        else:
            continue
        if toks:
            out[surface.lower()] = toks
    return out


def expand_tokens(tokens: List[str], mwe_map: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    """Return [(normalized_token, source_surface), ...].

    For tokens in ``mwe_map``, emit each expanded word tagged with the original
    surface. Untouched tokens get ``source_surface == token``.
    """
    out: List[Tuple[str, str]] = []
    for t in tokens:
        if t in mwe_map:
            for expanded in mwe_map[t]:
                out.append((expanded, t))
        else:
            out.append((t, t))
    return out


# ====== Single-word elision normalization (for n-gram counting only) ======
#
# Step 3a merges elided surface forms into canonical lemmas (ve'→vez/ves,
# e'→es, lo'→los) at the WORD level. But MWE detection in this step counts
# n-grams BEFORE step 3a runs, so "otra ve'" and "otra vez" land in separate
# buckets and split each other's PMI / curated-match counts. This helper
# applies the same canonical mapping to n-gram tokens only — the per-word
# `counts` Counter (which feeds vocab_evidence.json) stays surface-level so
# step 3a's evidence-merging continues to work unchanged.
#
# Ambiguous elisions (currently just `ve'` → vez|ves) reuse step 3a's
# preceding-word heuristic. Inlined rather than imported to avoid a
# circular dependency through step_3a's verbecc-loading machinery.

# Each entry describes how to disambiguate one elided form using local context.
# `mode="preceding"` looks at the previous token (mirrors step_3a's heuristic
# for ve' → vez|ves). `mode="following"` looks at the next token, used for
# "vo'" where the elision_mapping default of vos (Argentine voseo) is wrong
# in Caribbean reggaeton corpora — `vo' a [inf]` is virtually always voy a.
_AMBIG_ELISIONS_NGRAM = {
    "ve'": {
        "mode": "preceding",
        "default": "ves",                     # verb (you see)
        "override": "vez",                    # noun (time/occurrence)
        "trigger": frozenset({
            "una", "otra", "cada", "tal", "última", "primera",
            "esta", "esa", "la", "qué", "alguna", "cualquier",
        }),
    },
    "vo'": {
        "mode": "following",
        "default": "vos",                     # Argentine voseo (rare here)
        "override": "voy",                    # Caribbean "voy a [inf]"
        # Trigger on "a" — by far the dominant Caribbean usage. We don't
        # check that what follows "a" is an infinitive because the n-gram
        # counter doesn't know POS at this stage; "vo' a [anything]" is
        # heavily skewed toward voy-a-construction in this corpus.
        "trigger": frozenset({"a"}),
    },
}


def load_elision_normalization(shared_dir: str) -> Dict[str, str]:
    """Load unambiguous single-word elision targets from elision_mapping.json.

    Returns ``{elided_form: target_word}`` for `elision_pair` and
    `elided_only` entries. Skips entries handled by `_AMBIG_ELISIONS_NGRAM`
    (preceding-word heuristic) and trivial same-word entries.
    """
    path = os.path.join(shared_dir, "elision_mapping.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: Dict[str, str] = {}
    for entry in data:
        if entry.get("action") != "merge":
            continue
        if entry.get("merge_type") not in ("elision_pair", "elided_only"):
            continue
        elided = entry.get("elided_word")
        target = entry.get("target_word")
        if not elided or not target or elided == target:
            continue
        elided_l = elided.lower()
        if elided_l in _AMBIG_ELISIONS_NGRAM:
            continue
        out[elided_l] = target.lower()
    return out


def normalize_ngram_tokens(tokens: List[str], simple_map: Dict[str, str]) -> List[str]:
    """Map elided tokens to canonical forms for n-gram counting.

    Input tokens are already lowercase + multi-word-elision-expanded.
    Ambiguous forms (`_AMBIG_ELISIONS_NGRAM`) use a context heuristic on the
    preceding or following token; unambiguous forms look up in `simple_map`;
    everything else passes through.
    """
    if not simple_map and not _AMBIG_ELISIONS_NGRAM:
        return tokens
    out: List[str] = []
    for i, t in enumerate(tokens):
        if t in _AMBIG_ELISIONS_NGRAM:
            amb = _AMBIG_ELISIONS_NGRAM[t]
            if amb["mode"] == "preceding":
                ctx = tokens[i - 1] if i > 0 else None
            else:  # "following"
                ctx = tokens[i + 1] if i + 1 < len(tokens) else None
            if ctx and ctx in amb["trigger"]:
                out.append(amb["override"])
            else:
                out.append(amb["default"])
        elif t in simple_map:
            out.append(simple_map[t])
        else:
            out.append(t)
    return out


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
    mwe_map: Dict[str, List[str]] = None,
    elision_map: Dict[str, str] = None,
) -> Tuple[Counter, Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    """
    Returns:
    - counts[word] = total occurrences across corpus
    - candidates[word] = list of candidate context lines across songs
    - lid_stats = summary of lingua English line filtering

    `elision_map` (optional) normalizes single-word elisions in the n-gram
    counting stream so phrases like "otra ve'" / "otra vez" share counts.
    Per-word `counts` is unaffected — step 3a still does that merge.
    """
    counts: Counter = Counter()
    candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    lid_stats = {"lines_total": 0, "lines_skipped": 0, "lines_below_min_tokens": 0,
                 "multi_word_splits": 0, "ngram_elision_subs": 0}
    mwe_map = mwe_map or {}
    elision_map = elision_map or {}

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

        # Each line element: (line_no, line_text, expanded_tokens, word_surfaces)
        # where expanded_tokens is List[(word, source_surface)] and
        # word_surfaces: Dict[word, source_surface] (first occurrence wins).
        lines: List[Tuple[int, str, List[Tuple[str, str]], Dict[str, str]]] = []
        for line_no, line_text in enumerate(clean.split("\n"), start=1):
            line_text = line_text.strip()
            if not line_text:
                continue
            # Strip ad-libs/brackets for counting; keep original for examples
            count_text = strip_adlibs(line_text)
            raw_toks = tokenize(count_text) if count_text else []
            if not raw_toks:
                continue
            # Apply multi-word elision splits (preserves surface on each token)
            expanded = expand_tokens(raw_toks, mwe_map) if mwe_map else [(t, t) for t in raw_toks]
            if mwe_map:
                lid_stats["multi_word_splits"] += sum(
                    1 for t in raw_toks if t in mwe_map
                )
            norm_toks = [w for w, _ in expanded]
            lid_stats["lines_total"] += 1
            if lid_detector is not None:
                if len(norm_toks) >= _MIN_TOKENS_FOR_LID:
                    if _is_english_line(lid_detector, line_text):
                        lid_stats["lines_skipped"] += 1
                        continue
                else:
                    lid_stats["lines_below_min_tokens"] += 1
            # word_surfaces: first surface seen for each normalized word on this line
            word_surfaces: Dict[str, str] = {}
            for w, surface in expanded:
                if w not in word_surfaces:
                    word_surfaces[w] = surface
            lines.append((line_no, line_text, expanded, word_surfaces))
            counts.update(norm_toks)

            # Count n-grams once per unique line text (use cleaned text).
            # N-gram detection uses EXPANDED + elision-normalized tokens so MWE
            # phrases align with the canonical vocabulary that step 3a will
            # later produce ("otra ve'" + "otra vez" share counts here).
            if count_text not in seen_lines:
                seen_lines.add(count_text)
                for chunk in _PHRASE_SPLIT_RE.split(count_text):
                    chunk_raw = tokenize(chunk)
                    chunk_toks = [w for w, _ in expand_tokens(chunk_raw, mwe_map)] if mwe_map else chunk_raw
                    if elision_map or _AMBIG_ELISIONS_NGRAM:
                        before = chunk_toks
                        chunk_toks = normalize_ngram_tokens(chunk_toks, elision_map)
                        lid_stats["ngram_elision_subs"] += sum(
                            1 for a, b in zip(before, chunk_toks) if a != b
                        )
                    for t in chunk_toks:
                        ngram_unigrams[t] += 1
                    for n in range(2, 6):
                        for i in range(len(chunk_toks) - n + 1):
                            ng = " ".join(chunk_toks[i:i + n])
                            ngram_counts[n][ng] += 1
                            ngram_songs[ng].add(song_id)

        # Top 3 distinct lines per word per song (for single-song words).
        # Two lines are "the same" if their tokenized text matches after
        # stripping adlibs — catches chorus repetitions with minor variations.
        MAX_PER_WORD_PER_SONG = 3
        # top_for_word[word] = list of (score, line_no, line_text, norm, surface)
        top_for_word = {}  # type: Dict[str, List[Tuple[int, int, str, str, str]]]

        # Pre-compute normalized forms once per line
        line_norms: List[str] = []
        for _ln, lt, _exp, _ws in lines:
            line_norms.append(" ".join(tokenize(strip_adlibs(lt))))

        for idx, (line_no, line_text, expanded, word_surfaces) in enumerate(lines):
            norm_toks = [w for w, _ in expanded]
            if not is_good_context_line(norm_toks):
                continue
            s = score_line(norm_toks)
            norm = line_norms[idx]
            for w in word_surfaces:
                surface = word_surfaces[w]
                entries = top_for_word.get(w)
                if entries is None:
                    top_for_word[w] = [(s, line_no, line_text, norm, surface)]
                    continue
                if any(n == norm for _, _, _, n, _ in entries):
                    for i, (es, eln, elt, en, esf) in enumerate(entries):
                        if en == norm and s > es:
                            entries[i] = (s, line_no, line_text, norm, surface)
                            break
                    continue
                if len(entries) < MAX_PER_WORD_PER_SONG:
                    entries.append((s, line_no, line_text, norm, surface))
                else:
                    worst_i = min(range(len(entries)), key=lambda i: entries[i][0])
                    if s > entries[worst_i][0]:
                        entries[worst_i] = (s, line_no, line_text, norm, surface)

        # Fallback: words with no good-quality candidate still get their best line
        for idx, (line_no, line_text, expanded, word_surfaces) in enumerate(lines):
            norm_toks = [w for w, _ in expanded]
            s = score_line(norm_toks)
            norm = line_norms[idx]
            for w, surface in word_surfaces.items():
                if w not in top_for_word:
                    top_for_word[w] = [(s, line_no, line_text, norm, surface)]

        for w, entries in top_for_word.items():
            for s, line_no, line_text, _norm, surface in entries:
                candidates[w].append({
                    "score": s,
                    "batch": batch_i,
                    "song_id": song_id,
                    "line_no": line_no,
                    "line_text": line_text,
                    "song_title": title,
                    "surface": surface,
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
        chosen_keys = set()  # (song_id, line_no) to track what's picked

        # Pass 1: one per unique song (prefer diversity)
        for d in cands_sorted:
            if len(chosen) >= max_examples_per_word:
                break
            sid = d["song_id"]
            if sid in used_songs_for_word:
                continue
            used_songs_for_word.add(sid)
            chosen.append(d)
            chosen_keys.add((sid, d["line_no"]))

        # Pass 2: fill from same-song candidates (up to 3 per song)
        if len(chosen) < max_examples_per_word:
            song_counts = Counter()  # type: Counter
            for d in chosen:
                song_counts[d["song_id"]] += 1
            remaining = sorted(
                [d for d in cands if (d["song_id"], d["line_no"]) not in chosen_keys],
                key=lambda d: -d["score"]
            )
            for d in remaining:
                if len(chosen) >= max_examples_per_word:
                    break
                sid = d["song_id"]
                if song_counts[sid] >= 3:
                    continue
                song_counts[sid] += 1
                chosen.append(d)

        for d in chosen:
            global_song_use[d["song_id"]] += 1

        # strip selection-only fields to keep output small
        for d in chosen:
            d.pop("score", None)
            d.pop("batch", None)
            # song_title + surface kept — used by step 3/6 and the front-end

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
            rec = {
                "id": f"{ex.get('song_id')}:{ex.get('line_no')}",
                "line": ex.get("line_text", "") or "",
                "title": ex.get("song_title", ""),
            }
            surface = ex.get("surface")
            if surface and surface != word:
                rec["surface"] = surface
            ex_list.append(rec)
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

# PMI thresholds. Tuned permissively so small corpora (e.g. Young Miko ~90
# songs) actually surface candidates. Larger corpora (Bad Bunny ~300 songs)
# produce more noise at these settings; the downstream skip_mwes curation
# absorbs that. If the noise becomes painful we can scale these by corpus
# size, but the simpler floor works as a starting point.
MIN_PMI = 15.0
MIN_PMI_COUNT = 4
MIN_PMI_SONGS = 3


def _load_step_json(filename):
    """Load from Artists/curations/ (curated data)."""
    from util_1a_artist_config import SHARED_DIR
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


def _canonicalize_phrase(expr: str, mwe_map: Dict[str, List[str]],
                         elision_map: Dict[str, str]) -> str:
    """Return the n-gram counter key the given phrase will match against.

    Applies the same pipeline as n-gram counting — tokenize, multi-word
    elision split, single-word elision normalization — so curated keys like
    "pa' que" or "pa'l carajo" find their merged-canonical bucket.
    """
    toks = tokenize(expr)
    if mwe_map:
        toks = [w for w, _ in expand_tokens(toks, mwe_map)]
    if elision_map or _AMBIG_ELISIONS_NGRAM:
        toks = normalize_ngram_tokens(toks, elision_map)
    return " ".join(toks)


def detect_mwes(ngram_data, wiktionary_exprs=None,
                mwe_map: Dict[str, List[str]] = None,
                elision_map: Dict[str, str] = None):
    """Detect MWEs using curated matching + PMI on n-gram data from the counting pass.
    wiktionary_exprs: frozenset of Wiktionary MWE expressions to exclude (already covered).
    """
    curated_mwes_raw = _load_step_json("curated_mwes.json")
    skip_mwes_raw = _load_step_json("skip_mwes.json")
    conjugation_families_raw = _load_step_json("conjugation_families.json")
    wiktionary_exprs = wiktionary_exprs or frozenset()
    mwe_map = mwe_map or {}
    elision_map = elision_map or {}

    # Normalize curated keys with the same pipeline as n-gram counting so
    # elided-form curations ("pa' que") match the canonical bucket
    # ("para que") that now holds their counts. When both elided and
    # canonical are curated, prefer the canonical entry.
    curated_mwes: Dict[str, str] = {}
    curated_aliases: Dict[str, set] = defaultdict(set)
    for expr, translation in curated_mwes_raw.items():
        canon = _canonicalize_phrase(expr, mwe_map, elision_map)
        curated_aliases[canon].add(expr)
        if canon not in curated_mwes:
            curated_mwes[canon] = translation
        elif expr == canon:
            # canonical form takes precedence when both variants are curated
            curated_mwes[canon] = translation

    # skip_mwes is matched against canonical n-gram keys, so normalize.
    skip_mwes = frozenset(_canonicalize_phrase(s, mwe_map, elision_map)
                          for s in skip_mwes_raw)
    # conjugation_families intentionally keeps original keys: the file groups
    # elided variants together for surface-form dedup, but n-gram normalization
    # has already merged those variants into a single canonical entry. If we
    # also normalized family keys, families like "to' (elision)" — which lump
    # otherwise-unrelated phrases (todas las, toda la, todo lo que) into one
    # bucket — would collapse them into a single survivor. Leaving the keys
    # elided means those families now match only their (rare) un-normalized
    # members, which is what we want post-merge.
    conjugation_families = conjugation_families_raw

    unigrams = ngram_data["unigrams"]
    ng_counts = ngram_data["counts"]
    ng_songs = ngram_data["songs"]

    # Build a flat lookup: expression -> count (across all n-gram sizes)
    all_counts = {}
    for n in range(2, 6):
        all_counts.update(ng_counts[n])

    # Match curated MWEs against actual corpus counts (canonical-keyed).
    # Skip curated entries already in Wiktionary unless they contain
    # elision markers (apostrophe) — keeps Caribbean forms like "pa' que".
    confirmed = []
    matched_keys = set()
    for expression, translation in curated_mwes.items():
        # Wiktionary-coverage check uses the original surface forms; if every
        # alias of this canonical form is already in Wiktionary AND none had
        # an apostrophe, skip.
        aliases = curated_aliases.get(expression, {expression})
        if all(a in wiktionary_exprs and "'" not in a for a in aliases):
            continue
        count = all_counts.get(expression, 0)
        tokens = expression.split()
        if count > 0 or len(tokens) >= 4:
            entry = {
                "expression": expression,
                "translation": translation,
                "count": count,
            }
            # Track the original surface variants this entry came from when
            # they differ from the canonical form (e.g. "pa' que" → "para que").
            variants = sorted(a for a in aliases if a != expression)
            if variants:
                entry["variants"] = variants
            confirmed.append(entry)
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
            if ng in matched_keys or ng in skip_mwes or ng in wiktionary_exprs:
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

    # Pattern detection: collapse object/reflexive clitics into a placeholder
    # so families like "no te hagas / no me hagas / no lo hagas" surface as
    # one "no [PRON] hagas" entry. These aren't fixed expressions — they're
    # grammatical templates with one variable slot. Useful pedagogically;
    # downstream consumers (step_8b) currently ignore this bucket.
    patterns = _detect_clitic_patterns(ng_counts, ng_songs, matched_keys,
                                       skip_mwes, wiktionary_exprs)

    return confirmed, pmi_detected, patterns


_CLITIC_PRONOUNS = frozenset({
    "me", "te", "se", "le", "nos", "les", "lo", "la", "los", "las",
})


def _detect_clitic_patterns(ng_counts, ng_songs, matched_keys, skip_mwes,
                            wiktionary_exprs):
    """Group n-grams into families differing only in their clitic-pronoun slot.

    Returns a list of pattern dicts, each with the placeholder-substituted
    surface, the merged total count, the variant-by-variant breakdown, the
    union of song IDs they appeared in, and the number of distinct variants.
    Limited to 3- and 4-grams with exactly one clitic slot, at least two
    variants, and no single variant dominating (≤80%).
    """
    families = defaultdict(lambda: Counter())
    family_songs: Dict[str, set] = defaultdict(set)
    for n in (3, 4):
        for ng, count in ng_counts[n].items():
            toks = ng.split()
            clitic_positions = [i for i, t in enumerate(toks) if t in _CLITIC_PRONOUNS]
            if len(clitic_positions) != 1:
                continue
            placeholder_toks = list(toks)
            placeholder_toks[clitic_positions[0]] = "[PRON]"
            # Skip if remaining content is all function words (low signal)
            content = [t for t in placeholder_toks if t != "[PRON]"]
            if all(w in FUNCTION_WORDS for w in content):
                continue
            key = " ".join(placeholder_toks)
            families[key][ng] += count
            family_songs[key].update(ng_songs.get(ng, set()))

    patterns = []
    for key, members in families.items():
        total = sum(members.values())
        if total < MIN_PMI_COUNT:
            continue
        if len(members) < 2:
            continue
        top_share = members.most_common(1)[0][1] / total
        if top_share > 0.80:
            continue
        # Skip if every variant is already a curated/PMI/wiktionary MWE
        # (the family doesn't add information beyond those entries).
        all_variants_known = all(
            (v in matched_keys or v in skip_mwes or v in wiktionary_exprs)
            for v in members
        )
        if all_variants_known:
            continue
        patterns.append({
            "pattern": key,
            "count": total,
            "num_variants": len(members),
            "num_songs": len(family_songs[key]),
            "variants": dict(members.most_common()),
        })
    patterns.sort(key=lambda p: -p["count"])
    return patterns


def main():
    global PIPELINE_DIR

    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True, help="Path to artist data directory")
    ap.add_argument("--batch_glob", required=True, help='e.g. "Artists/spanish/Bad Bunny/data/input/batches/batch_*.json"')
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

    # Load multi-word elisions curation so pa'l → para + el at tokenize time
    from util_1a_artist_config import SHARED_DIR
    mwe_map = load_multi_word_elisions(SHARED_DIR)
    if mwe_map:
        print(f"Loaded {len(mwe_map)} multi-word elision entries from {SHARED_DIR}/multi_word_elisions.json")

    # Load single-word elision targets so n-gram counts merge variant phrases
    # ("otra ve'" + "otra vez", "a vece'" + "a veces", etc.) before PMI runs.
    elision_map = load_elision_normalization(SHARED_DIR)
    if elision_map:
        print(f"Loaded {len(elision_map)} single-word elision targets for n-gram normalization")

    counts, candidates, lid_stats, ngram_data = build_counts_and_candidates(
        songs, lid_detector=lid_detector, mwe_map=mwe_map, elision_map=elision_map,
    )
    selected = select_examples(counts, candidates, max_examples_per_word=args.max_examples)
    out_list = to_evidence_json(counts, selected)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)
    write_sidecar(args.out, make_meta("count_words", STEP_VERSION))

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

    if lid_stats.get("multi_word_splits"):
        print(f"  Multi-word elision splits: {lid_stats['multi_word_splits']:,} tokens expanded")
    if lid_stats.get("ngram_elision_subs"):
        print(f"  N-gram elision normalizations: {lid_stats['ngram_elision_subs']:,} substitutions")

    # Load Wiktionary MWE expressions for filtering
    wikt_mwe_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "Data", "Spanish", "layers", "mwe_phrases.json")
    wiktionary_exprs = frozenset()
    if os.path.isfile(wikt_mwe_path):
        with open(wikt_mwe_path, "r", encoding="utf-8") as f:
            wikt_data = json.load(f)
        wiktionary_exprs = frozenset(
            mwe["expression"].lower()
            for mwes in wikt_data.values()
            for mwe in mwes
        )
        print(f"  Wiktionary MWE filter: {len(wiktionary_exprs)} expressions loaded")

    # MWE detection
    confirmed, pmi_detected, patterns = detect_mwes(
        ngram_data, wiktionary_exprs,
        mwe_map=mwe_map, elision_map=elision_map,
    )
    mwe_out_path = args.mwe_out or os.path.join(os.path.dirname(args.out), "mwe_detected.json")
    def _confirmed_to_out(m):
        rec = {
            "expression": m["expression"],
            "translation": m["translation"],
            "count": m["count"],
        }
        if m.get("variants"):
            rec["variants"] = m["variants"]
        return rec

    mwe_output = {
        "mwes": [_confirmed_to_out(m) for m in confirmed] + [
            {"expression": m["expression"], "translation": None, "count": m["count"],
             "pmi": m["pmi"], "num_songs": m["num_songs"]}
            for m in pmi_detected
        ],
        "patterns": patterns,
        "candidates": [],  # Legacy field, no longer used
        "stats": {
            "confirmed_count": len(confirmed),
            "pmi_detected_count": len(pmi_detected),
            "patterns_count": len(patterns),
        },
    }
    os.makedirs(os.path.dirname(mwe_out_path), exist_ok=True)
    with open(mwe_out_path, "w", encoding="utf-8") as f:
        json.dump(mwe_output, f, ensure_ascii=False, indent=2)
    print(f"  MWE: {len(confirmed)} curated, {len(pmi_detected)} PMI-detected, "
          f"{len(patterns)} clitic-patterns -> {mwe_out_path}")

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
