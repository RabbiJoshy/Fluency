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
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402
from pipeline.util_evidence_store import archive_json_artifact  # noqa: E402

# Bump when counting logic, tokenization, or output schema changes in a way
# that invalidates existing vocab_evidence.json files.
STEP_VERSION = 13
STEP_VERSION_NOTES = {
    1: "lingua English filter + MWE detection + max-examples-per-word",
    2: "+ multi-word elision split with surface preservation on examples",
    3: "+ strip hyphen-chain ad-libs (ah-na-na, aca-ca-ca, Ba-Ba-Baila) "
       "before tokenization — prevents ad-lib stutters polluting short-"
       "token counts that later merge into real words via elision",
    4: "+ count each normalized lyric line once per song — repeated choruses "
       "no longer inflate word/MWE frequency, while the same line in a "
       "different song remains independent",
    5: "+ retain the complete set of corpus song IDs per word so distinct-song "
       "ranking is independent of the capped example selection",
    6: "+ preserve named Genius section vocalists on retained lyric examples",
    7: "+ pool curated morphological expression families on unique lyric-line evidence "
       "and retain exact MWE matches for deterministic artist assembly",
    8: "+ match translated phrase lexicons and explicit lemma/construction templates; "
       "keep untranslated PMI/pattern discovery out of learner-facing rows",
    9: "+ dual-write the language-agnostic segment/occurrence evidence ledger and "
       "attach stable segment/occurrence references to legacy teaching examples",
    10: "+ retain non-counting/ad-lib-only source lines and the exact legacy "
        "surface/batch metadata needed for behavior-neutral profile materialization",
    11: "+ preserve source song order and align Unicode-scanner tokens with the "
        "historical tokenizer for exact ledger materialization parity",
    12: "+ align one-letter legacy tokens embedded inside Unicode source words",
    13: "+ write fully restored elision forms into ledger normalization claims "
        "before vocal-artifact, routing, POS and WSD layers",
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


# Caribbean/PR leading-apostrophe aphesis: the elided form drops the first
# syllable and marks it with a LEADING apostrophe ('tamos = estamos, 'e = de).
# WORD_RE can't keep a leading apostrophe, so these were beheaded to a bare token
# (tamos/e) that collides with an unrelated word — tamo="fluff", e="and". Expand
# them to the full form at the SOURCE, before WORD_RE, so the count lands on the
# real word. Fires only on a genuine leading apostrophe (not preceded by a
# letter), so internal/trailing forms (pa'l, hijo') are untouched. Straight and
# curly apostrophes both match (normalize_text emits curly). Examples keep the
# raw elided line — only the count/word identity is corrected.
_LEADING_ELISIONS = {
    "tamos": "estamos", "tamo": "estamos", "taba": "estaba", "tabas": "estabas",
    "toy": "estoy", "tá": "está", "tás": "estás", "tan": "están", "tán": "están",
    "onde": "donde", "el": "del", "e": "de",
}
_LEADING_ELISION_RE = re.compile(
    r"(?<![" + LETTER_CLASS + r"])['’]("
    + "|".join(sorted(_LEADING_ELISIONS, key=len, reverse=True))
    + r")(?![" + LETTER_CLASS + r"])",
    re.IGNORECASE,
)


def _expand_leading_elisions(line: str) -> str:
    return _LEADING_ELISION_RE.sub(
        lambda m: _LEADING_ELISIONS[m.group(1).lower()], line)


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
    # Genius injects invisible whitespace substitutes (U+2005/205F/200A/3000)
    # and zero-width chars as anti-scrape obfuscation; map to a plain space (or
    # drop) so tokenization, line matching, and exact translation lookups agree.
    s = (s.replace("\u2005", " ").replace("\u205f", " ")
          .replace("\u200a", " ").replace("\u3000", " ")
          .replace("\u200b", "").replace("\ufeff", ""))
    s = s.translate(_HOMOGLYPH_TABLE)   # strip Genius homoglyph obfuscation
    return s


_VOCALIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\+|/|\b(?:y|x)\b|\b(?:feat|ft)\.?)\s*",
    re.IGNORECASE,
)


def parse_section_vocalists(section_line: str) -> List[str]:
    """Return explicitly named performers from a Genius section header.

    Generic headers such as ``[Coro]`` deliberately return an empty list; we
    never infer a singer when Genius did not name one.
    """
    inner = section_line.strip()[1:-1].strip()
    if ":" not in inner:
        return []
    names = inner.split(":", 1)[1].strip()
    if not names:
        return []
    return [part.strip(" -–—()") for part in _VOCALIST_SPLIT_RE.split(names)
            if part.strip(" -–—()")]


def _normalized_artist_name(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def clean_genius_lyrics(raw: str, with_sections: bool = False):
    """
    Removes Genius boilerplate:
    - skips placeholder lyrics ("yet to be transcribed", instrumentals)
    - strips leading 'Lyrics' section + editorial description paragraph
    - removes [Chorus]/[Verse] lines
    - cuts off common footer markers
    """
    if not raw:
        return [] if with_sections else ""

    # Skip Genius placeholder pages (no real lyrics)
    if ("yet to be transcribed" in raw or "yet to be released" in raw
            or "This song is an instrumental" in raw):
        return [] if with_sections else ""
    # "letra completa … disponible pronto" is a SOFT marker: it can sit on a page
    # that also carries a genuine leaked-track transcription (e.g. "No Prometo
    # Nada"). Defer the drop decision until after cleaning — only treat the page
    # as a placeholder when little real content survives (checked at return).
    _soft_placeholder = ("letra completa" in raw.lower()
                         or "disponible pronto" in raw.lower())

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
    rm_match = re.search(r'(?:…|\.\.\.|\u2026)?\s*Read More\b[^\n]*\n?', text[:2000])
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

    lines = []
    current_vocalists: List[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if SECTION_LINE_RE.match(s):
            current_vocalists = parse_section_vocalists(s)
            continue
        if BOILERPLATE_LINE_RE.search(s):
            continue
        lines.append((s, list(current_vocalists)) if with_sections else s)

    if _soft_placeholder and len(lines) < 8:
        return [] if with_sections else ""
    return lines if with_sections else "\n".join(lines).strip()


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
    line = _expand_leading_elisions(line)
    line = strip_hyphen_adlibs(line)
    return [m.group(0).lower() for m in WORD_RE.finditer(line)]


def tokenize_with_surfaces(line: str) -> List[Tuple[str, str]]:
    """Return canonical counting tokens alongside their displayed surfaces.

    ``tokenize()`` intentionally expands leading aphesis before matching, but
    expression evidence also needs the exact lyric spelling for highlighting.
    Recover that spelling here while applying the same canonical identity.
    """
    line = strip_hyphen_adlibs(line)
    out = []
    for match in WORD_RE.finditer(line):
        raw = match.group(0).lower()
        canonical = raw
        surface = raw
        if match.start() > 0 and line[match.start() - 1] in "'’":
            before = line[match.start() - 2] if match.start() > 1 else ""
            if (not before or not re.match(r"[" + LETTER_CLASS + r"]", before)):
                # A source may mark both the leading aphesis and the dropped
                # final consonant (``'Tamo'``). Match the leading-elision key
                # without the trailing marker, then retain that marker so this
                # projection stays byte-for-byte compatible with tokenize().
                lookup = raw.rstrip("'’")
                suffix = raw[len(lookup):]
                expanded = _LEADING_ELISIONS.get(lookup)
                if expanded:
                    canonical = expanded + suffix
                    surface = line[match.start() - 1] + raw
        out.append((canonical, surface))
    return out


def extract_exact_surface(surface: str, line: str) -> Optional[str]:
    """Return the literal displayed span, or ``None`` if punctuation split it."""
    tokens = str(surface or "").split()
    if not tokens:
        return None
    parts = []
    for index, token in enumerate(tokens):
        if index:
            parts.append(r"\s*" if tokens[index - 1].endswith(("'", "’")) else r"\s+")
        parts.append(re.escape(token).replace("'", "['’]"))
    pattern = re.compile(
        r"(?<![" + LETTER_CLASS + r"0-9])(" + "".join(parts) + r")(?![" +
        LETTER_CLASS + r"0-9])",
        re.IGNORECASE,
    )
    match = pattern.search(line)
    return match.group(1) if match else None


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


# ====== Single-word elision normalization ======
#
# Canonical restoration now happens here, at ingestion, so every later layer
# sees the same clean analysis form. Step 3a remains as an idempotent
# compatibility projection and audit guard for older ledgers.
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


_PLURAL_CONTEXT = frozenset({
    "los", "unos", "mis", "tus", "sus", "estos", "esos", "aquellos",
})


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _contextual_internal_elision(tokens: List[str], index: int, known_forms):
    """Resolve only locally licensed ambiguous/internal Spanish elisions.

    Candidate generation remains dictionary-constrained.  Context is used for
    the two common collisions where a dropped ``s`` competes with an
    infinitive/noun, and for a plural whose slang singular exists but whose
    generated plural is absent from spanish_forms.  Otherwise we abstain.
    """
    try:
        from step_3a_merge_elisions import internal_apos_candidates
    except ImportError:
        from pipeline.artist.step_3a_merge_elisions import internal_apos_candidates

    word = tokens[index]
    previous = tokens[index - 1] if index > 0 else None
    candidates = internal_apos_candidates(word, known_forms)

    # menos e'perado -> menos esperado.  Do not choose between esperado and
    # the rare emperado without an adjective-licensing context.
    if previous in {"menos", "más", "tan", "lo"} and "esperado" in candidates:
        return "esperado"

    # que llega'te / te pasa'te: the local syntax requires a finite verb, not
    # llegarte/pasarte.  Restrict this to the distinctive -a'te spelling and
    # an explicit finite-verb licensor.
    normalized = word.replace("\u2019", "'")
    if normalized.endswith("a'te") and previous in {"que", "te"}:
        finite = normalized.replace("a'te", "aste")
        if finite in candidates:
            return finite

    # los tíguere' -> tigueres.  The lexical table knows the accentless slang
    # singular ``tiguere`` but not every plural.  A plural determiner supplies
    # the missing agreement evidence; without it the rule abstains.
    if normalized.endswith("'") and previous in _PLURAL_CONTEXT:
        stem = _strip_accents(normalized[:-1])
        if stem in known_forms:
            return stem + "s"
    return None


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


def normalize_analysis_tokens(tokens: List[str], simple_map: Dict[str, str],
                              known_forms=None) -> List[str]:
    """Canonical forms used by every downstream occurrence-level layer.

    This is the ledger-facing counterpart to step 3's compatibility merge.
    It runs before vocal-artifact, routing, POS and WSD claims are produced,
    while the raw occurrence continues to preserve the exact lyric surface.
    """
    try:
        from step_3a_merge_elisions import (
            bare_d_elision_canonical, d_elision_canonical,
            d_elision_ext_canonical, double_elision_canonical,
            internal_apos_restore, load_spanish_forms, trailing_apos_restore,
        )
    except ImportError:  # package import in tests
        from pipeline.artist.step_3a_merge_elisions import (
            bare_d_elision_canonical, d_elision_canonical,
            d_elision_ext_canonical, double_elision_canonical,
            internal_apos_restore, load_spanish_forms, trailing_apos_restore,
        )
    known = known_forms if known_forms is not None else load_spanish_forms()
    normalized = normalize_ngram_tokens(tokens, simple_map)
    out = []
    for index, (original, mapped) in enumerate(zip(tokens, normalized)):
        # An explicit/contextual mapping may itself land on another elided
        # form (metío' → metíos). Apply the same safe second-hop rule used
        # by step 3 so the ledger stores the final canonical form (metidos).
        if mapped != original:
            chained = bare_d_elision_canonical(mapped, known)
            out.append(chained[0] if chained else mapped)
            continue
        result = (double_elision_canonical(mapped, known)
                  or d_elision_canonical(mapped))
        if result:
            out.append(result[0])
            continue
        extended = d_elision_ext_canonical(mapped, known)
        if extended:
            out.append(extended[0])
            continue
        contextual = _contextual_internal_elision(normalized, index, known)
        if contextual:
            out.append(contextual)
            continue
        result = (bare_d_elision_canonical(mapped, known)
                  or trailing_apos_restore(mapped, known)
                  or internal_apos_restore(mapped, known))
        out.append(result[0] if result else mapped)
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
        for song_i, s in enumerate(data):
            if isinstance(s, dict):
                s["__batch"] = batch_i
                s["__song_order"] = song_i
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
    primary_artist: str = "",
    ledger=None,
    analysis_language: str = "spanish",
) -> Tuple[Counter, Dict[str, List[Dict[str, Any]]], Dict[str, int], Dict[str, Any], Dict[str, set]]:
    """
    Returns:
    - counts[word] = total occurrences across corpus
    - candidates[word] = list of candidate context lines across songs
    - lid_stats = summary of lingua English line filtering
    - ngram_data = counters used by MWE detection
    - word_songs[word] = every distinct corpus song containing the word

    `elision_map` (optional) normalizes single-word elisions at ingestion so
    counts, the ledger, n-grams, artifact classification, routing, POS, menus,
    and WSD all consume the same restored analysis forms.
    """
    counts: Counter = Counter()
    candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    word_songs: Dict[str, set] = defaultdict(set)
    lid_stats = {"lines_total": 0, "lines_skipped": 0, "lines_below_min_tokens": 0,
                 "duplicate_lines": 0, "multi_word_splits": 0,
                 "ngram_elision_subs": 0}
    mwe_map = mwe_map or {}
    elision_map = elision_map or {}
    analysis_known_forms = None
    if ledger is not None and analysis_language == "spanish":
        try:
            from step_3a_merge_elisions import load_spanish_forms
        except ImportError:  # package import in tests
            from pipeline.artist.step_3a_merge_elisions import load_spanish_forms
        analysis_known_forms = load_spanish_forms()

    # N-gram tracking for MWE detection (counted per unique line, not per word)
    _PHRASE_SPLIT_RE = re.compile(r'[,;:!?¡¿()"—\-]+')
    ngram_unigrams: Counter = Counter()
    ngram_counts: Dict[int, Counter] = {n: Counter() for n in range(2, 6)}
    ngram_songs: Dict[str, set] = defaultdict(set)
    # Full counts and retained teaching examples must share one evidence
    # basis. Keep the unique (song, normalised full line) keys for every
    # observed n-gram, plus a small exact-example sample that step 8b can use
    # without hoping the expression survived a component word's example cap.
    ngram_lines: Dict[str, set] = defaultdict(set)
    ngram_examples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    MAX_MWE_EXAMPLES = 8
    for song in songs:
        raw_lyrics = song.get("lyrics")
        if not raw_lyrics:
            continue

        song_id = song.get("id")
        title = song.get("title") or ""
        batch_i = song.get("__batch", -1)
        song_order = song.get("__song_order", -1)

        clean_rows = clean_genius_lyrics(raw_lyrics, with_sections=True)
        if not clean_rows:
            continue

        # Repeated chorus/refrain lines contribute once within this song.
        # Reset for every song: a shared line in two different songs is two
        # independent pieces of corpus evidence and must count twice.
        seen_count_lines: set = set()

        # Each line element: (line_no, line_text, expanded_tokens,
        # word_surfaces, vocalists, sung_by_primary_artist)
        # where expanded_tokens is List[(word, source_surface)] and
        # word_surfaces: Dict[word, source_surface] (first occurrence wins).
        lines = []
        primary_name = _normalized_artist_name(primary_artist)
        for line_no, (line_text, vocalists) in enumerate(clean_rows, start=1):
            line_text = line_text.strip()
            if not line_text:
                continue
            # Strip ad-libs/brackets for counting; keep original for examples
            count_text = strip_adlibs(line_text)
            raw_toks = tokenize(count_text) if count_text else []
            # Apply multi-word elision splits (preserves surface on each token)
            expanded = expand_tokens(raw_toks, mwe_map) if mwe_map else [(t, t) for t in raw_toks]
            if mwe_map:
                lid_stats["multi_word_splits"] += sum(
                    1 for t in raw_toks if t in mwe_map
                )
            # Restoration is the first mutable linguistic layer. Counts,
            # examples, routing, POS, menus and WSD all consume these forms;
            # the paired source surface remains untouched for display/audit.
            restored_tokens = (
                normalize_analysis_tokens(
                    [w for w, _surface in expanded], elision_map,
                    known_forms=analysis_known_forms)
                if analysis_language == "spanish"
                else [w for w, _surface in expanded]
            )
            expanded = [
                (restored, surface)
                for restored, (_word, surface) in zip(restored_tokens, expanded)
            ]
            norm_toks = [w for w, _ in expanded]
            normalized_vocalists = {_normalized_artist_name(name) for name in vocalists}
            sung_by_primary = bool(primary_name and any(
                primary_name == singer or primary_name in singer
                for singer in normalized_vocalists
            ))
            if raw_toks:
                lid_stats["lines_total"] += 1
            excluded_as_english = False
            if raw_toks and lid_detector is not None:
                if len(norm_toks) >= _MIN_TOKENS_FOR_LID:
                    if _is_english_line(lid_detector, line_text):
                        lid_stats["lines_skipped"] += 1
                        excluded_as_english = True
                else:
                    lid_stats["lines_below_min_tokens"] += 1
            if ledger is not None:
                ledger_tokens = []
                raw_ledger_tokens = tokenize_with_surfaces(count_text)
                grouped_forms = [
                    list(mwe_map.get(canonical, [canonical]))
                    for canonical, _surface in raw_ledger_tokens
                ]
                flat_forms = [form for forms in grouped_forms for form in forms]
                normalized_forms = (
                    normalize_analysis_tokens(
                        flat_forms, elision_map, known_forms=analysis_known_forms)
                    if analysis_language == "spanish" else flat_forms
                )
                offset = 0
                for (canonical, source_surface), forms in zip(
                        raw_ledger_tokens, grouped_forms):
                    restored = normalized_forms[offset:offset + len(forms)]
                    offset += len(forms)
                    ledger_tokens.append({
                        "surface": source_surface,
                        "forms": restored,
                        "legacy_surface": canonical,
                    })
                ledger.observe_line(
                    song_id,
                    title,
                    line_no,
                    line_text,
                    ledger_tokens,
                    included=not excluded_as_english,
                    exclusion_reason=("english_line" if excluded_as_english else None),
                    vocalists=vocalists,
                    sung_by_primary_artist=sung_by_primary,
                    batch_index=batch_i,
                    song_order=song_order,
                )
            # Ad-lib-only and other currently non-counting lines still belong
            # in the immutable source ledger so later classifiers can inspect
            # them. They simply have no active normalization units yet.
            if not raw_toks:
                continue
            if excluded_as_english:
                continue
            # word_surfaces: first surface seen for each normalized word on this line
            word_surfaces: Dict[str, str] = {}
            for w, surface in expanded:
                if w not in word_surfaces:
                    word_surfaces[w] = surface
            lines.append((line_no, line_text, expanded, word_surfaces,
                          vocalists, sung_by_primary))

            # Use the normalized tokens that actually feed the counter as the
            # exact-line key. This makes capitalization, punctuation, and
            # bracket-only ad-lib differences irrelevant to corpus frequency.
            count_line_key = " ".join(norm_toks)
            if count_line_key in seen_count_lines:
                lid_stats["duplicate_lines"] += 1
                continue
            seen_count_lines.add(count_line_key)
            counts.update(norm_toks)
            if song_id is not None:
                for word in set(norm_toks):
                    word_songs[word].add(str(song_id))

            # Count n-grams from the same once-per-song line basis.
            # N-gram detection uses EXPANDED + elision-normalized tokens so MWE
            # phrases align with the canonical vocabulary that step 3a will
            # later produce ("otra ve'" + "otra vez" share counts here).
            for chunk in _PHRASE_SPLIT_RE.split(count_text):
                chunk_source_tokens = tokenize_with_surfaces(chunk)
                # Preserve each canonical token's original surface and source
                # token index. Multi-word elisions such as ``vo'a`` expand to
                # two counting tokens but must collapse back to one displayed
                # match for exact lyric highlighting downstream.
                chunk_expanded = []
                for raw_index, (raw_token, source_surface) in enumerate(chunk_source_tokens):
                    expanded_words = mwe_map.get(raw_token, [raw_token]) if mwe_map else [raw_token]
                    chunk_expanded.extend(
                        (word, source_surface, raw_index)
                        for word in expanded_words
                    )
                chunk_toks = [word for word, _surface, _raw_index in chunk_expanded]
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
                        evidence_key = (str(song_id or ""), count_line_key)
                        if evidence_key not in ngram_lines[ng]:
                            ngram_lines[ng].add(evidence_key)
                            if len(ngram_examples[ng]) < MAX_MWE_EXAMPLES:
                                surface_parts = []
                                last_raw_index = None
                                for _word, surface, raw_index in chunk_expanded[i:i + n]:
                                    if raw_index != last_raw_index:
                                        surface_parts.append(surface)
                                        last_raw_index = raw_index
                                evidence = {
                                    "id": f"{song_id}:{line_no}",
                                    "line": line_text,
                                    "title": title,
                                    "matched_variant": ng,
                                    "matched_surface": " ".join(surface_parts),
                                }
                                if ledger is not None:
                                    evidence.update(ledger.example_refs(
                                        song_id, title, line_no, line_text,
                                        chunk_toks[i],
                                    ))
                                if vocalists:
                                    evidence["vocalists"] = list(vocalists)
                                    evidence["sung_by_primary_artist"] = sung_by_primary
                                ngram_examples[ng].append(evidence)

        # Top 3 distinct lines per word per song (for single-song words).
        # Two lines are "the same" if their tokenized text matches after
        # stripping adlibs — catches chorus repetitions with minor variations.
        MAX_PER_WORD_PER_SONG = 3
        # top_for_word[word] = list of
        # (score, line_no, line_text, norm, surface, vocalists, primary_singer)
        top_for_word = {}

        # Pre-compute normalized forms once per line
        line_norms: List[str] = []
        for _ln, lt, _exp, _ws, _vocalists, _primary in lines:
            line_norms.append(" ".join(tokenize(strip_adlibs(lt))))

        for idx, (line_no, line_text, expanded, word_surfaces,
                  vocalists, sung_by_primary) in enumerate(lines):
            norm_toks = [w for w, _ in expanded]
            if not is_good_context_line(norm_toks):
                continue
            s = score_line(norm_toks)
            norm = line_norms[idx]
            for w in word_surfaces:
                surface = word_surfaces[w]
                entries = top_for_word.get(w)
                if entries is None:
                    top_for_word[w] = [(s, line_no, line_text, norm, surface,
                                        vocalists, sung_by_primary)]
                    continue
                if any(entry[3] == norm for entry in entries):
                    for i, (es, eln, elt, en, esf, ev, ep) in enumerate(entries):
                        if en == norm and s > es:
                            entries[i] = (s, line_no, line_text, norm, surface,
                                          vocalists, sung_by_primary)
                            break
                    continue
                if len(entries) < MAX_PER_WORD_PER_SONG:
                    entries.append((s, line_no, line_text, norm, surface,
                                    vocalists, sung_by_primary))
                else:
                    worst_i = min(range(len(entries)), key=lambda i: entries[i][0])
                    if s > entries[worst_i][0]:
                        entries[worst_i] = (s, line_no, line_text, norm, surface,
                                            vocalists, sung_by_primary)

        # Fallback: words with no good-quality candidate still get their best line
        for idx, (line_no, line_text, expanded, word_surfaces,
                  vocalists, sung_by_primary) in enumerate(lines):
            norm_toks = [w for w, _ in expanded]
            s = score_line(norm_toks)
            norm = line_norms[idx]
            for w, surface in word_surfaces.items():
                if w not in top_for_word:
                    top_for_word[w] = [(s, line_no, line_text, norm, surface,
                                        vocalists, sung_by_primary)]

        for w, entries in top_for_word.items():
            for (s, line_no, line_text, _norm, surface,
                 vocalists, sung_by_primary) in entries:
                candidate = {
                    "score": s,
                    "batch": batch_i,
                    "song_id": song_id,
                    "line_no": line_no,
                    "line_text": line_text,
                    "song_title": title,
                    "surface": surface,
                }
                if ledger is not None:
                    candidate.update(ledger.example_refs(
                        song_id, title, line_no, line_text, w,
                    ))
                if vocalists:
                    candidate["vocalists"] = vocalists
                    candidate["sung_by_primary_artist"] = sung_by_primary
                candidates[w].append(candidate)

    ngram_data = {
        "unigrams": ngram_unigrams,
        "counts": ngram_counts,
        "songs": ngram_songs,
        "lines": ngram_lines,
        "examples": ngram_examples,
    }
    return counts, candidates, lid_stats, ngram_data, word_songs


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
    selected_examples: Dict[str, List[Dict[str, Any]]],
    word_songs: Dict[str, set],
) -> List[Dict[str, Any]]:
    """
    Build final list of entries with exact corpus-level song provenance.
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
            if ex.get("vocalists"):
                rec["vocalists"] = ex["vocalists"]
                rec["sung_by_primary_artist"] = bool(ex.get("sung_by_primary_artist"))
            if ex.get("segment_id"):
                rec["segment_id"] = ex["segment_id"]
            if ex.get("occurrence_ids"):
                rec["occurrence_ids"] = list(ex["occurrence_ids"])
            ex_list.append(rec)
        song_ids = sorted(word_songs.get(word, set()), key=str)
        out.append({
            "word": word,
            "corpus_count": c,
            "song_count": len(song_ids),
            "song_ids": song_ids,
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
    "yo", "tú", "tu", "él", "ella", "ello", "ellos", "ellas",
    "usted", "ustedes", "vos", "nosotros", "nosotras",
    "esto", "eso", "aquello", "todo", "toda", "todos", "todas",
})

# PMI thresholds. Tuned permissively so small corpora (e.g. Young Miko ~90
# songs) actually surface candidates. Larger corpora (Bad Bunny ~300 songs)
# produce more noise at these settings; the downstream skip_mwes curation
# absorbs that. If the noise becomes painful we can scale these by corpus
# size, but the simpler floor works as a starting point.
MIN_PMI = 15.0
MIN_PMI_COUNT = 4
MIN_PMI_SONGS = 3
_PMI_BOILERPLATE_FRAGMENTS = (
    "letra completa estará disponible",
    "lyrics will be available",
    "you might also like",
)
_PMI_ENGLISH_TAG_WORDS = frozenset({
    "available", "baby", "carbon", "fiber", "full", "hear", "lyrics",
    "music", "soon", "this",
})


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


def _is_pmi_noise(ngram):
    lowered = str(ngram or "").lower()
    tokens = set(lowered.split())
    if any(fragment in lowered for fragment in _PMI_BOILERPLATE_FRAGMENTS):
        return True
    if "letra" in tokens and ({"completa", "disponible", "pronto"} & tokens):
        return True
    if {"completa", "disponible"}.issubset(tokens):
        return True
    if "disponible" in tokens and ({"pronto", "momento"} & tokens):
        return True
    if len(tokens & _PMI_ENGLISH_TAG_WORDS) >= 2:
        return True
    # Initialisms and tokenisation debris such as ``en p r`` are not useful
    # learner expressions, even when repeated across releases.
    return any(len(token) == 1 for token in lowered.split())


def _pool_construction_families(confirmed, families, ngram_data):
    """Collapse curated inflected variants on their exact line union.

    The old implementation kept only the most frequent spelling in a family,
    so ``voy a`` silently discarded evidence for ``va a``, ``vas a``, etc.
    Keep one familiar surface label but carry every observed variant, the
    unique lyric-line union, and the distinct-song union. Overlapping variants
    such as ``sé que`` / ``yo sé que`` therefore count a lyric line once.
    """
    line_sets = ngram_data.get("lines", {})
    song_sets = ngram_data.get("songs", {})
    grouped = defaultdict(list)
    no_family = []
    for item in confirmed:
        family = families.get(item["expression"])
        if family is None:
            no_family.append(item)
        else:
            grouped[family].append(item)

    pooled = []
    for family, members in grouped.items():
        representative = max(members, key=lambda item: item.get("count", 0))
        result = dict(representative)
        family_lines = set()
        family_songs = set()
        member_example_groups = []
        variants = []
        variant_counts = {}
        occurrence_count = 0
        for member in members:
            expr = member["expression"]
            if expr not in variants:
                variants.append(expr)
            for alias in member.get("variants", []):
                if alias not in variants:
                    variants.append(alias)
            lines = set(line_sets.get(expr, set()))
            family_lines.update(lines)
            family_songs.update(song_sets.get(expr, set()))
            variant_counts[expr] = len(lines)
            occurrence_count += int(member.get("occurrence_count", member.get("count", 0)) or 0)
            member_example_groups.append([dict(example) for example in member.get("examples", [])])

        # Sample across variants before taking a second line from any one
        # surface. Otherwise a frequent representative such as ``voy a``
        # consumes the entire five-example cap and the pooled family never
        # demonstrates that ``va a`` / ``vas a`` were recognised too.
        family_examples = []
        seen_examples = set()
        max_group_size = max((len(group) for group in member_example_groups), default=0)
        for example_index in range(max_group_size):
            for group in member_example_groups:
                if example_index >= len(group):
                    continue
                example = group[example_index]
                key = (example.get("id"), example.get("line"))
                if key in seen_examples:
                    continue
                seen_examples.add(key)
                family_examples.append(example)
                if len(family_examples) >= 5:
                    break
            if len(family_examples) >= 5:
                break

        result["family"] = family
        result["variants"] = variants
        result["variant_counts"] = variant_counts
        result["count"] = len(family_lines)
        result["occurrence_count"] = occurrence_count
        result["num_songs"] = len({song for song in family_songs if song is not None})
        result["examples"] = family_examples[:5]
        pooled.append(result)
    return no_family + pooled


def _has_lemma(form: str, lemma: str, conjugation_reverse: Dict[str, Any]) -> bool:
    return any(
        str(analysis.get("lemma") or "").lower() == lemma
        for analysis in conjugation_reverse.get(form, [])
        if isinstance(analysis, dict)
    )


def _has_nonfinite_form(form: str, requested: str,
                        conjugation_reverse: Dict[str, Any]) -> bool:
    requested = str(requested or "").lower()
    analyses = list(conjugation_reverse.get(form, []))
    # Caribbean lyrics frequently drop the infinitive's final r: ``caga'``
    # for ``cagar``, ``bebe'`` for ``beber``. This inference is safe here
    # because it only runs in a template slot that explicitly requires a
    # non-finite verb and the reconstructed form must exist in morphology.
    if requested == "infinitivo" and str(form).endswith(("'", "’")):
        analyses.extend(conjugation_reverse.get(str(form)[:-1] + "r", []))
    return any(
        requested in {
            str(analysis.get("mood") or "").lower(),
            str(analysis.get("tense") or "").lower(),
        }
        for analysis in analyses
        if isinstance(analysis, dict)
    )


def _detect_construction_templates(ngram_data, templates,
                                   conjugation_reverse, exact_examples):
    """Match explicit grammatical constructions against morphology.

    This is deliberately template-driven rather than a blanket lemmatisation
    of every high-PMI n-gram. In particular, ``ir + a`` is accepted only when
    the following token is an actual infinitive, preventing location phrases
    such as ``voy a casa`` from inflating the future construction.
    """
    ng_counts = ngram_data.get("counts", {})
    ng_lines = ngram_data.get("lines", {})
    ng_songs = ngram_data.get("songs", {})
    constructions = []
    covered_keys = set()

    for template in templates or []:
        if not isinstance(template, dict):
            continue
        kind = template.get("kind")
        lemma = str(template.get("lemma") or "").lower()
        link = str(template.get("link") or "").lower()
        family = str(template.get("family") or "").strip()
        translation = str(template.get("translation") or "").strip()
        if not (kind and lemma and link and family and translation):
            continue

        n = 3 if kind == "verb_link_nonfinite" else 2
        members = []
        for expression, occurrence_count in ng_counts.get(n, {}).items():
            tokens = expression.split()
            if len(tokens) != n or tokens[1] != link:
                continue
            if not _has_lemma(tokens[0], lemma, conjugation_reverse):
                continue
            if kind == "verb_link_nonfinite" and not _has_nonfinite_form(
                    tokens[2], template.get("nonfinite"), conjugation_reverse):
                continue
            members.append({
                "expression": expression,
                "prefix": " ".join(tokens[:2]),
                "occurrence_count": int(occurrence_count or 0),
                "lines": set(ng_lines.get(expression, set())),
                "songs": set(ng_songs.get(expression, set())),
                "examples": exact_examples(expression),
            })

        if not members:
            continue

        family_lines = set()
        family_songs = set()
        variant_lines = defaultdict(set)
        occurrence_count = 0
        example_groups = []
        for member in members:
            covered_keys.add(member["expression"])
            family_lines.update(member["lines"])
            family_songs.update(member["songs"])
            variant_lines[member["prefix"]].update(member["lines"])
            occurrence_count += member["occurrence_count"]
            if member["examples"]:
                example_groups.append(member["examples"])

        # Demonstrate different inflected prefixes before repeating one form.
        examples = []
        seen_examples = set()
        max_group = max((len(group) for group in example_groups), default=0)
        for example_index in range(max_group):
            for group in example_groups:
                if example_index >= len(group):
                    continue
                example = dict(group[example_index])
                key = (example.get("id"), example.get("line"))
                if key in seen_examples:
                    continue
                seen_examples.add(key)
                examples.append(example)
                if len(examples) >= 5:
                    break
            if len(examples) >= 5:
                break

        variants = sorted(
            variant_lines,
            key=lambda variant: (-len(variant_lines[variant]), variant),
        )
        covered_keys.update(variants)
        constructions.append({
            "expression": family,
            "translation": translation,
            "family": family,
            "variants": variants,
            "variant_counts": {
                variant: len(variant_lines[variant]) for variant in variants
            },
            "count": len(family_lines),
            "occurrence_count": occurrence_count,
            "num_songs": len({song for song in family_songs if song is not None}),
            "examples": examples,
            "source": "artist-construction",
            "_line_keys": family_lines,
            "_verb_lemma": lemma,
            "_shadow_standalone": bool(template.get("shadow_standalone")),
        })

    constructions.sort(key=lambda item: -item["count"])
    return constructions, covered_keys


def _remove_construction_shadowed_hits(items, constructions, ngram_data,
                                       conjugation_reverse, mwe_map):
    """Remove standalone-verb evidence that is really a longer construction.

    ``me voy`` is a valid expression, but a line containing ``me voy a beber``
    should teach ``ir a + infinitive`` rather than inflate “I'm leaving”. The
    same conservative subtraction applies to any shorter expression whose
    final verb belongs to one of the explicit construction templates.
    """
    ng_lines = ngram_data.get("lines", {})

    def example_line_key(example):
        song_id = str(example.get("id") or "").split(":", 1)[0]
        tokens = tokenize(strip_adlibs(example.get("line") or ""))
        if mwe_map:
            tokens = [word for word, _surface in expand_tokens(tokens, mwe_map)]
        return song_id, " ".join(tokens)

    filtered = []
    for item in items:
        expression = item.get("expression", "")
        tokens = expression.split()
        if not tokens:
            continue
        blocked = set()
        for construction in constructions:
            if not construction.get("_shadow_standalone"):
                continue
            lemma = construction.get("_verb_lemma")
            if lemma and _has_lemma(tokens[-1], lemma, conjugation_reverse):
                blocked.update(construction.get("_line_keys", set()))
        if not blocked:
            filtered.append(item)
            continue

        remaining = set(ng_lines.get(expression, set())) - blocked
        if not remaining:
            continue
        result = dict(item)
        result["count"] = len(remaining)
        result["occurrence_count"] = len(remaining)
        result["num_songs"] = len({song for song, _line in remaining if song})
        result["examples"] = [
            example for example in item.get("examples", [])
            if example_line_key(example) in remaining
        ]
        filtered.append(result)
    return filtered


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
                elision_map: Dict[str, str] = None,
                fallback_translations=None,
                conjugation_reverse=None):
    """Detect MWEs using curated matching + PMI on n-gram data from the counting pass.
    wiktionary_exprs: frozenset of Wiktionary MWE expressions to exclude (already covered).
    """
    curated_mwes_raw = _load_step_json("curated_mwes.json")
    skip_mwes_raw = _load_step_json("skip_mwes.json")
    conjugation_families_raw = _load_step_json("conjugation_families.json")
    construction_templates = _load_step_json("construction_templates.json")
    wiktionary_exprs = wiktionary_exprs or frozenset()
    mwe_map = mwe_map or {}
    elision_map = elision_map or {}
    fallback_translations = fallback_translations or {}
    conjugation_reverse = conjugation_reverse or {}

    def normalize_payload_map(raw_map):
        normalized = {}
        for raw_expression, raw_payload in raw_map.items():
            expression = _canonicalize_phrase(raw_expression, mwe_map, elision_map)
            if not expression:
                continue
            payload = raw_payload if isinstance(raw_payload, dict) else {
                "translation": raw_payload,
            }
            translation = str(payload.get("translation") or "").strip()
            if not translation:
                continue
            normalized.setdefault(expression, {
                "translation": translation,
                "source": payload.get("source") or "",
            })
        return normalized

    fallback_translations = normalize_payload_map(fallback_translations)

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
    ng_lines = ngram_data.get("lines", {})
    ng_examples = ngram_data.get("examples", {})

    def exact_examples(expression):
        exact = []
        for raw in ng_examples.get(expression, []):
            matched_surface = extract_exact_surface(
                raw.get("matched_surface", ""), raw.get("line", ""))
            if not matched_surface:
                continue
            example = dict(raw)
            example["matched_surface"] = matched_surface
            exact.append(example)
            if len(exact) >= 5:
                break
        return exact

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
        aliases = curated_aliases.get(expression, {expression})
        count = all_counts.get(expression, 0)
        tokens = expression.split()
        if count > 0 or len(tokens) >= 4:
            line_count = len(ng_lines.get(expression, set()))
            entry = {
                "expression": expression,
                "translation": translation,
                "count": line_count,
                "occurrence_count": count,
                "num_songs": len({song for song in ng_songs.get(expression, set()) if song is not None}),
                "examples": exact_examples(expression),
                "source": "artist-curated",
            }
            # Track the original surface variants this entry came from when
            # they differ from the canonical form (e.g. "pa' que" → "para que").
            variants = sorted(a for a in aliases if a != expression)
            if variants:
                entry["variants"] = variants
            confirmed.append(entry)
            matched_keys.add(expression)

    constructions, construction_keys = _detect_construction_templates(
        ngram_data, construction_templates, conjugation_reverse, exact_examples)
    matched_keys.update(construction_keys)

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
            if _is_pmi_noise(ng):
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
            translated = fallback_translations.get(ng, {})
            pmi_detected.append({
                "expression": ng,
                "translation": translated.get("translation"),
                "count": len(ng_lines.get(ng, set())),
                "occurrence_count": count,
                "pmi": round(pmi, 1),
                "num_songs": num_songs,
                "examples": exact_examples(ng),
                "source": "artist-pmi-lexicon" if translated else "artist-pmi-candidate",
            })

    # Dedup overlapping n-grams: drop shorter if substring of longer with >= PMI
    pmi_detected.sort(key=lambda x: (
        0 if x.get("translation") else 1,
        -len(x["expression"].split()),
        -x["pmi"],
    ))
    kept = []
    kept_exprs = []
    for r in pmi_detected:
        if not any(r["expression"] in longer for longer in kept_exprs):
            kept.append(r)
            kept_exprs.append(r["expression"])
    pmi_detected = sorted(kept, key=lambda x: -x["pmi"])
    translated_pmi = [item for item in pmi_detected if item.get("translation")]
    pmi_candidates = [item for item in pmi_detected if not item.get("translation")]

    # Post-process curated
    confirmed = [m for m in confirmed if m["expression"] not in skip_mwes]
    confirmed = _remove_construction_shadowed_hits(
        confirmed, constructions, ngram_data, conjugation_reverse, mwe_map)
    confirmed = _pool_construction_families(
        confirmed, conjugation_families, ngram_data)
    # Explicit morphology-constrained templates supersede shorter/manual
    # variants. This is what removes the old unconstrained ``voy a`` count.
    def covered_by_construction(item):
        expression = item.get("expression", "")
        return any(
            expression == prefix or expression.endswith(" " + prefix)
            for prefix in construction_keys
        )
    confirmed = [item for item in confirmed if not covered_by_construction(item)]
    confirmed.extend(constructions)
    confirmed.sort(key=lambda x: -x["count"])

    # Pattern detection: collapse object/reflexive clitics into a placeholder
    # so families like "no te hagas / no me hagas / no lo hagas" surface as
    # one "no [PRON] hagas" entry. These aren't fixed expressions — they're
    # grammatical templates with one variable slot. Useful pedagogically;
    # step 8b carries the retained high-signal templates into expression rows.
    patterns = _detect_clitic_patterns(
        ng_counts, ng_songs, matched_keys, skip_mwes, wiktionary_exprs,
        ngram_lines=ng_lines, ngram_examples=ng_examples)

    return confirmed, translated_pmi, patterns, pmi_candidates


_CLITIC_PRONOUNS = frozenset({
    "me", "te", "se", "le", "nos", "les", "lo", "la", "los", "las",
})


def _detect_clitic_patterns(ng_counts, ng_songs, matched_keys, skip_mwes,
                            wiktionary_exprs, ngram_lines=None,
                            ngram_examples=None):
    """Group n-grams into families differing only in their clitic-pronoun slot.

    Returns a list of pattern dicts, each with the placeholder-substituted
    surface, the merged total count, the variant-by-variant breakdown, the
    union of song IDs they appeared in, and the number of distinct variants.
    Limited to 3- and 4-grams with exactly one clitic slot, at least two
    variants, and no single variant dominating (≤80%).
    """
    families = defaultdict(lambda: Counter())
    family_songs: Dict[str, set] = defaultdict(set)
    ngram_lines = ngram_lines or {}
    ngram_examples = ngram_examples or {}
    for n in (3, 4):
        for ng, count in ng_counts[n].items():
            toks = ng.split()
            clitic_positions = [i for i, t in enumerate(toks) if t in _CLITIC_PRONOUNS]
            if len(clitic_positions) != 1:
                continue
            placeholder_toks = list(toks)
            slot_index = clitic_positions[0]
            placeholder_toks[slot_index] = "[PRON]"
            # Skip if remaining content is all function words (low signal)
            content = [t for t in placeholder_toks if t != "[PRON]"]
            if all(w in FUNCTION_WORDS for w in content):
                continue
            # A pronoun-ending fragment such as ``que yo [PRON]`` is not a
            # learnable construction. Require a lexical token after the slot;
            # this retains useful families such as ``no [PRON] hagas`` while
            # dropping the broad prefixes that dominated the old output.
            if not any(token not in FUNCTION_WORDS
                       for token in toks[slot_index + 1:]):
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
        # No top-variant cap. Patterns where one form dominates (e.g.
        # "no te hagas" 24 / "no me hagas" 3 / "no lo hagas" 2) are still
        # pedagogically useful — the dominant form anchors the template
        # and the smaller variants reveal the slot's flexibility.
        # Skip if every variant is already a curated/PMI/wiktionary MWE
        # (the family doesn't add information beyond those entries).
        all_variants_known = all(
            (v in matched_keys or v in skip_mwes or v in wiktionary_exprs)
            for v in members
        )
        if all_variants_known:
            continue
        family_lines = set()
        examples = []
        seen_examples = set()
        for variant in members:
            family_lines.update(ngram_lines.get(variant, set()))
            for example in ngram_examples.get(variant, []):
                matched_surface = extract_exact_surface(
                    example.get("matched_surface", ""), example.get("line", ""))
                if not matched_surface:
                    continue
                example_key = (example.get("id"), example.get("line"))
                if example_key in seen_examples:
                    continue
                seen_examples.add(example_key)
                tagged = dict(example)
                tagged["matched_variant"] = variant
                tagged["matched_surface"] = matched_surface
                examples.append(tagged)
        patterns.append({
            # Use ``expression`` (not ``pattern``) so step_8b can iterate this
            # bucket alongside ``mwes`` / ``pmi_detected`` with one schema.
            # The placeholder string is the user-facing display ("no [PRON] hagas")
            # and the variants dict carries the surface forms that collapsed.
            "expression": key,
            "count": len(family_lines),
            "occurrence_count": total,
            "num_variants": len(members),
            "num_songs": len(family_songs[key]),
            "variants": dict(members.most_common()),
            "examples": examples[:5],
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
    from util_1a_artist_config import SHARED_DIR, load_artist_config
    mwe_map = load_multi_word_elisions(SHARED_DIR)
    if mwe_map:
        print(f"Loaded {len(mwe_map)} multi-word elision entries from {SHARED_DIR}/multi_word_elisions.json")

    # Load single-word elision targets so n-gram counts merge variant phrases
    # ("otra ve'" + "otra vez", "a vece'" + "a veces", etc.) before PMI runs.
    elision_map = load_elision_normalization(SHARED_DIR)
    if elision_map:
        print(f"Loaded {len(elision_map)} single-word elision targets for n-gram normalization")

    artist_config = load_artist_config(args.artist_dir)
    from util_2a_corpus_ledger import ArtistCorpusLedger
    ledger = ArtistCorpusLedger(
        args.artist_dir,
        artist_config.get("language") or "und",
        artist_name=artist_config.get("name", ""),
    )
    counts, candidates, lid_stats, ngram_data, word_songs = build_counts_and_candidates(
        songs, lid_detector=lid_detector, mwe_map=mwe_map, elision_map=elision_map,
        primary_artist=artist_config.get("name", ""),
        ledger=ledger,
        analysis_language=(artist_config.get("language") or "spanish"),
    )
    selected = select_examples(counts, candidates, max_examples_per_word=args.max_examples)
    out_list = to_evidence_json(counts, selected, word_songs)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)
    write_sidecar(args.out, make_meta("count_words", STEP_VERSION))

    ledger_summary = ledger.finalize(config={
        "step_version": STEP_VERSION,
        "language": artist_config.get("language") or "und",
        "line_detection": not args.no_lid,
        "max_examples": args.max_examples,
        "multi_word_elisions": mwe_map,
    })
    archive_json_artifact(
        os.path.join(args.artist_dir, "data", "evidence"),
        "vocab_evidence_baseline",
        out_list,
        language=artist_config.get("language") or "und",
        adapter={"name": "artist-step-2a-baseline", "version": STEP_VERSION},
        inputs={"ledger_run": ledger_summary["run_id"]},
        config={"max_examples": args.max_examples},
    )

    print(f"Wrote {len(out_list):,} words -> {args.out}")
    print(
        "  Evidence ledger: %(segments)d segments, %(occurrences)d occurrences, "
        "%(tombstones)d tombstones -> %(run_id)s" % ledger_summary
    )
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
    if lid_stats.get("duplicate_lines"):
        print(f"  Repeated lyric lines excluded from counts: {lid_stats['duplicate_lines']:,}")
    if lid_stats.get("ngram_elision_subs"):
        print(f"  N-gram elision normalizations: {lid_stats['ngram_elision_subs']:,} substitutions")

    # Load Wiktionary MWE expressions for filtering
    wikt_mwe_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "Data", "Spanish", "layers", "mwe_phrases.json")
    wiktionary_exprs = frozenset()
    known_mwes = {}
    if os.path.isfile(wikt_mwe_path):
        with open(wikt_mwe_path, "r", encoding="utf-8") as f:
            wikt_data = json.load(f)
        wiktionary_exprs = frozenset(
            mwe["expression"].lower()
            for mwes in wikt_data.values()
            for mwe in mwes
        )
        for mwes in wikt_data.values():
            for mwe in mwes:
                expression = str(mwe.get("expression") or "").lower().strip()
                translation = str(mwe.get("translation") or "").strip()
                if expression and translation:
                    known_mwes.setdefault(expression, {
                        "translation": translation,
                        "source": mwe.get("source") or "shared",
                    })
        print(f"  Shared MWE lexicon: {len(wiktionary_exprs)} expressions, "
              f"{len(known_mwes)} translated")

    # SpanishDict's broader phrase cache is not trusted as an automatic seed:
    # it is used only when an independently strong PMI candidate exactly
    # matches a translated phrase. This avoids importing its long noisy tail.
    fallback_translations = dict(known_mwes)
    spanishdict_phrases_path = os.path.join(
        PROJECT_ROOT, "Data", "Spanish", "Senses", "spanishdict", "phrases_cache.json")
    if os.path.isfile(spanishdict_phrases_path):
        with open(spanishdict_phrases_path, "r", encoding="utf-8") as f:
            spanishdict_phrases = json.load(f)
        for phrases in spanishdict_phrases.values():
            for phrase in phrases:
                expression = str(phrase.get("expression") or "").lower().strip()
                translation = str(phrase.get("translation") or "").strip()
                if expression and translation:
                    fallback_translations.setdefault(expression, {
                        "translation": translation,
                        "source": "spanishdict",
                    })
        print(f"  SpanishDict PMI translation fallback: "
              f"{len(fallback_translations)} expressions")

    conjugation_reverse = {}
    conjugation_reverse_path = os.path.join(
        PROJECT_ROOT, "Data", "Spanish", "layers", "conjugation_reverse.json")
    if os.path.isfile(conjugation_reverse_path):
        with open(conjugation_reverse_path, "r", encoding="utf-8") as f:
            conjugation_reverse = json.load(f)
        print(f"  Construction morphology: {len(conjugation_reverse)} forms")

    # MWE detection
    confirmed, pmi_detected, patterns, pmi_candidates = detect_mwes(
        ngram_data, wiktionary_exprs,
        mwe_map=mwe_map, elision_map=elision_map,
        fallback_translations=fallback_translations,
        conjugation_reverse=conjugation_reverse,
    )
    mwe_out_path = args.mwe_out or os.path.join(os.path.dirname(args.out), "mwe_detected.json")
    def _confirmed_to_out(m):
        rec = {
            "expression": m["expression"],
            "translation": m["translation"],
            "count": m["count"],
            "occurrence_count": m.get("occurrence_count", m["count"]),
            "num_songs": m.get("num_songs", 0),
            "examples": m.get("examples", []),
        }
        if m.get("variants"):
            rec["variants"] = m["variants"]
        if m.get("variant_counts"):
            rec["variant_counts"] = m["variant_counts"]
        if m.get("family"):
            rec["family"] = m["family"]
        if m.get("source"):
            rec["source"] = m["source"]
        return rec

    pmi_output = [
            {"expression": m["expression"], "translation": m.get("translation"), "count": m["count"],
             "occurrence_count": m.get("occurrence_count", m["count"]),
             "pmi": m["pmi"], "num_songs": m["num_songs"],
             "examples": m.get("examples", []), "source": m.get("source", "artist-pmi-lexicon")}
            for m in pmi_detected
        ]
    candidate_output = [
            {"expression": m["expression"], "count": m["count"],
             "occurrence_count": m.get("occurrence_count", m["count"]),
             "pmi": m["pmi"], "num_songs": m["num_songs"],
             "examples": m.get("examples", [])}
            for m in pmi_candidates
        ]
    mwe_output = {
        "mwes": [_confirmed_to_out(m) for m in confirmed],
        "pmi_detected": pmi_output,
        "patterns": patterns,
        "candidates": candidate_output,
        "stats": {
            "confirmed_count": len(confirmed),
            "pmi_detected_count": len(pmi_detected),
            "patterns_count": len(patterns),
            "candidate_count": len(pmi_candidates),
        },
    }
    os.makedirs(os.path.dirname(mwe_out_path), exist_ok=True)
    with open(mwe_out_path, "w", encoding="utf-8") as f:
        json.dump(mwe_output, f, ensure_ascii=False, indent=2)
    archive_json_artifact(
        os.path.join(args.artist_dir, "data", "evidence"),
        "mwe_detection_baseline",
        mwe_output,
        language=artist_config.get("language") or "und",
        adapter={"name": "artist-step-2a-mwe", "version": STEP_VERSION},
        inputs={"ledger_run": ledger_summary["run_id"]},
        config={"mwe_schema": 1},
    )
    print(f"  MWE: {len(confirmed)} translated/constructed, "
          f"{len(pmi_detected)} translated PMI, {len(pmi_candidates)} review candidates, "
          f"{len(patterns)} clitic diagnostics -> {mwe_out_path}")

    if confirmed:
        print("\n  Top 10 study-ready expressions:")
        for m in confirmed[:10]:
            print(f"    {m['count']:4d}  {m['expression']:<25s}  {m['translation']}")
    if pmi_detected:
        print(f"\n  Translated PMI expressions:")
        for m in pmi_detected[:10]:
            print(f"    {m['count']:4d}  PMI={m['pmi']:5.1f}  songs={m['num_songs']:2d}  "
                  f"{m['expression']} — {m['translation']}")

    if args.preview and args.preview > 0:
        print("\n=== PREVIEW ===")
        print(json.dumps(out_list[:args.preview], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
