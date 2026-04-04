#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
2b_split_lang_and_junk_lingua.py

Post-stage-2 audit-friendly splitter:
- Spanish vs English vs Mixed vs Junk vs No-Evidence
- line-level language ID (Lingua), then voting per word
- deterministic heuristics for junk/adlibs/scrape artifacts
- token-level English word list to catch loanwords in Spanish context
- Genius annotation/description line detection

Input:
  A JSON list of dicts, each with:
    {"word": "...", "occurrences_ppm": ..., "examples": [{"id": "...", "line": "...", "title": "..."}]}

Output (all lists, same schema as input + lid_meta):
  <out_prefix>_es.json       — Spanish vocabulary candidates
  <out_prefix>_en.json       — English tokens
  <out_prefix>_mixed.json    — code-switched / uncertain
  <out_prefix>_junk.json     — sounds, non-words, garbage
  <out_prefix>_noevidence.json — real-looking tokens with no usable example lines
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lingua import Language, LanguageDetectorBuilder

# -------------------------------------------------------------------------
# Config / heuristics
# -------------------------------------------------------------------------

# Genius scraping artifacts (line-level)
GENIUS_JUNK_PATTERNS = [
    r"\bread more\b",
    r"\byou might also like\b",
    r"\bembed\b",
    r"\btranslation[s]?\b",
    r"\btranscript\b",
    r"\bcontributor",
    r"\blyrics?\b$",           # trailing "Lyrics" at end of line
]

# Genius annotation / description line patterns
# These are metadata lines that leak through from Genius, not actual lyrics
GENIUS_DESCRIPTION_PATTERNS = [
    r"es (?:el|la|una?|los|las) (?:nombre|canción|tema|sencillo|colaboración|segundo|primer|tercer|cuart)",
    r"(?:lanzad[oa]|estrenada?|publicad[oa]) (?:en|el|por)",
    r"hace referencia a",
    r"(?:primer|segund|tercer|cuart|quint)\w+ (?:sencillo|tema|track)",
    r"del álbum",
    r"junto (?:a|con) (?:el|la|los|las)",
    r"exponentes del género",
    r"(?:puertorriqueñ|colombian|dominican|estadounidense)[oa]s?",
    r"se (?:estrenó|lanzó|publicó|reveló)",
]

# Common ad-libs / vocables
VOCABLES = {
    "oh", "uh", "ouh", "ooh", "woo", "wooh", "yeah", "yea", "yah", "ayy", "ay",
    "eh", "mm", "mmm", "hah", "haha", "la", "na", "nan", "lalala", "nanan",
    "ey", "eya", "yeh", "yeh-eh", "wuh", "wouh", "prr", "brrr", "prrr", "grrr", "rrr",
    "skrr", "skrt", "brr", "grr", "ra", "ra'", "wow",
    "ah", "aah", "oah", "uah", "jaja", "jajaja", "ja",
    "tra", "tra'", "tra-tra", "pa-pa", "ra-ta-ta",
}

# ---- Token-level English word list ----
# Words that are English and NOT Spanish homographs.
# We intentionally EXCLUDE words that are valid in both languages:
#   no, me, a, te, se, son, sin, solo, come, real, pan, den, etc.
# IMPORTANT: "he" is EXCLUDED — it's the Spanish conjugation of "haber" (yo he visto).
# This list catches English loanwords that appear in Spanish-context lines.
ENGLISH_ONLY_WORDS = {
    # pronouns / determiners (NOT "he" — Spanish haber)
    "i", "you", "she", "we", "they", "it", "my", "your", "his", "her",
    "our", "their", "its", "this", "that", "these", "those",
    # articles / prepositions / conjunctions
    "the", "and", "but", "or", "for", "with", "from", "into", "about",
    "between", "through", "after", "before", "during", "without", "against",
    "of", "at", "by", "on", "in", "to", "up", "out", "off", "over", "down",
    # verbs (NOT "go" — could be interjection, NOT "be" — short/ambiguous)
    "is", "am", "are", "was", "were", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "can", "could", "may", "might", "must",
    "got", "get", "getting", "going", "gone", "went",
    "know", "knew", "known", "said", "say", "says", "tell", "told",
    "think", "thought", "see", "saw", "seen", "look", "looked",
    "want", "wanted", "need", "needed", "like", "liked",
    "give", "gave", "take", "took", "taken", "put", "let",
    "keep", "kept", "run", "running",
    # common adjectives
    "big", "little", "old", "new", "good", "bad", "great",
    "right", "left", "high", "low", "long", "short",
    "hard", "soft", "hot", "cold", "fast", "slow",
    # common nouns / slang frequent in reggaeton/trap
    "baby", "bitch", "nigga", "niggas", "gang", "ice", "drip",
    "swag", "flex", "thug", "dope", "plug", "cash", "money",
    "shit", "fuck", "damn", "ass", "hoe", "bro",
    "girl", "boy", "man", "woman", "people", "world",
    "life", "time", "day", "night", "way", "thing", "place",
    "game", "play", "player", "club", "vibe", "vibes",
    "freestyle", "remix", "beat", "hook", "verse",
    # genre / music loanwords used in reggaeton/trap
    "flow", "trap", "freestyle", "feat", "featuring",
    "shawty", "shorty", "homie", "dawg",
    # other frequent English in BB corpus
    "party", "body", "still", "just", "even", "much",
    "only", "very", "really", "never", "always", "here", "there",
    "now", "then", "when", "where", "what", "who", "how", "why",
    "not", "don't", "can't", "won't", "ain't", "didn't",
    "show", "stop", "back", "down", "calm",
    "believe", "trust", "feel", "feeling",
    "bunny",  # proper noun but always English context
}

# Spanish function words that should NEVER be classified as junk
# even if they're short or look like vocables
SPANISH_FUNCTION_WORDS = {
    "a", "al", "de", "del", "el", "en", "es", "la", "le", "lo", "me",
    "mi", "ni", "no", "o", "pa", "se", "si", "sí", "su", "te", "tu",
    "tú", "un", "va", "ve", "vi", "ya", "yo", "e", "y", "u",
    "pa'", "to'", "e'", "ma'", "na'",
}

WORD_CHARS_RE = re.compile(r"^[\wÀ-ÿ''\-]+$", re.UNICODE)
REPEATED_CHAR_RE = re.compile(r"(.)\1{3,}")  # aaaa, oooo, etc.
HAS_LETTER_RE = re.compile(r"[A-Za-zÀ-ÿ]", re.UNICODE)
HAS_SPANISH_DIACRITIC_RE = re.compile(r"[áéíóúüñ]", re.IGNORECASE)


# -------------------------------------------------------------------------
# Data classes
# -------------------------------------------------------------------------

@dataclass
class LidLine:
    text: str
    detected: str   # "es" | "en" | "unknown"
    confidence: Optional[float] = None
    is_description: bool = False


@dataclass
class LidMeta:
    n_considered: int
    votes_es: int
    votes_en: int
    votes_unknown: int
    es_ratio: float
    en_ratio: float
    threshold: float
    decision: str          # "es" | "en" | "mixed" | "junk" | "no_evidence"
    lines: List[LidLine] = field(default_factory=list)
    junk_reasons: List[str] = field(default_factory=list)
    english_word_override: bool = False
    description_lines_removed: int = 0


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def normalize_token(token: str) -> str:
    t = token.strip().lower()
    t = t.replace("\u2019", "'").replace("\u00b4", "'").replace("`", "'")
    return t


def is_gibberish_token(token: str) -> Tuple[bool, List[str]]:
    """
    Token-level junk heuristics (not language; just garbage/adlibs/non-words).
    Returns (is_junk, reasons).
    """
    reasons: List[str] = []
    t = normalize_token(token)

    if not t:
        return True, ["empty_token"]

    # Protect Spanish function words from false junk classification
    if t in SPANISH_FUNCTION_WORDS:
        return False, []

    # Very short tokens (single char that isn't a known function word)
    if len(t) <= 1:
        reasons.append("too_short")

    # Contains no letters at all
    if not HAS_LETTER_RE.search(t):
        reasons.append("no_letters")

    # Not composed of reasonable word characters
    if not WORD_CHARS_RE.match(t):
        reasons.append("non_word_chars")

    # Repeated characters (4+)
    if REPEATED_CHAR_RE.search(t):
        reasons.append("repeated_chars")

    # Known vocables/adlibs
    if t in VOCABLES:
        reasons.append("vocable")

    # Strong reasons → always junk
    strong = {"empty_token", "no_letters"}
    if any(r in strong for r in reasons):
        return True, reasons

    # Single strong signal for vocables — don't require 2 reasons
    if "vocable" in reasons:
        return True, reasons

    return (len(reasons) >= 2), reasons


def line_is_genius_description(line: str) -> bool:
    """
    Detect Genius annotation / song description lines that aren't lyrics.
    These are metadata lines that leak through from Genius.
    """
    low = (line or "").strip().lower()
    if not low:
        return False

    # Description lines tend to be longer than lyrics
    # and match annotation patterns
    for pat in GENIUS_DESCRIPTION_PATTERNS:
        if re.search(pat, low):
            return True

    return False


def line_is_junk(line: str) -> Tuple[bool, List[str]]:
    """
    Line-level junk patterns: Genius boilerplate, empty, descriptions, etc.
    """
    reasons: List[str] = []
    s = (line or "").strip()
    if not s:
        return True, ["empty_line"]

    low = s.lower()

    for pat in GENIUS_JUNK_PATTERNS:
        if re.search(pat, low):
            reasons.append(f"genius_junk:{pat}")

    # If it's extremely short, it's often useless for LID voting
    if len(s) < 4:
        reasons.append("line_too_short")

    # Genius description lines (annotation metadata, not lyrics)
    if line_is_genius_description(s):
        reasons.append("genius_description")

    # Check for Genius junk or empty
    is_junk = (
        "empty_line" in reasons
        or any("genius_junk" in r for r in reasons)
        or "genius_description" in reasons
    )
    return is_junk, reasons


def extract_lines(item: Any) -> List[str]:
    """
    Pull lyric lines out of the evidence entry.
    Handles both list-of-strings and list-of-dicts structures.
    """
    if not isinstance(item, dict):
        return []

    for key in ("contexts", "examples", "evidence", "lines"):
        if key not in item:
            continue
        v = item[key]

        if isinstance(v, list):
            lines: List[str] = []
            for x in v:
                if isinstance(x, str):
                    lines.append(x)
                elif isinstance(x, dict):
                    for lk in ("line_text", "text", "line", "lyric", "sentence"):
                        if lk in x and isinstance(x[lk], str):
                            lines.append(x[lk])
                            break
            if lines:
                return lines

    return []


def build_detector() -> Any:
    """Build Lingua detector restricted to Spanish + English."""
    return LanguageDetectorBuilder.from_languages(
        Language.SPANISH, Language.ENGLISH
    ).build()


def detect_line(detector: Any, line: str) -> LidLine:
    """
    Detect language of a line using Lingua.
    Returns LidLine with detected language and confidence.
    """
    text = (line or "").strip()

    detected_lang = None
    confidence = None

    if hasattr(detector, "compute_language_confidence_values"):
        confs = detector.compute_language_confidence_values(text)
        if confs:
            top = confs[0]
            detected_lang = getattr(top, "language", None)
            confidence = float(getattr(top, "value", 0.0)) if hasattr(top, "value") else None
    else:
        detected_lang = detector.detect_language_of(text)

    if detected_lang == Language.SPANISH:
        return LidLine(text=text, detected="es", confidence=confidence)
    if detected_lang == Language.ENGLISH:
        return LidLine(text=text, detected="en", confidence=confidence)

    return LidLine(text=text, detected="unknown", confidence=confidence)


def classify_word(
    token: str,
    item: Dict[str, Any],
    detector: Any,
    max_lines: int,
    threshold: float,
) -> Tuple[str, LidMeta]:
    """
    Classify a word into es/en/mixed/junk/no_evidence.

    Strategy:
    1. Check token-level junk heuristics
    2. Check if token is a known English-only word (override)
    3. Extract and filter example lines (remove junk + Genius descriptions)
    4. Run line-level LID voting on remaining lines
    5. Apply threshold-based decision with English override
    """
    t = normalize_token(token)
    junk_token, token_reasons = is_gibberish_token(token)

    # --- English word list check ---
    is_known_english = t in ENGLISH_ONLY_WORDS
    # Tokens with Spanish diacritics are never English
    if HAS_SPANISH_DIACRITIC_RE.search(t):
        is_known_english = False

    raw_lines = extract_lines(item)
    junk_reasons: List[str] = list(token_reasons)

    # --- No examples at all ---
    if not raw_lines:
        # If the token looks like a real word (not junk), use no_evidence
        # so it can be manually reviewed rather than lost
        if junk_token:
            junk_reasons.append("no_context_lines")
            decision = "junk"
        else:
            junk_reasons.append("no_context_lines")
            decision = "no_evidence"

        meta = LidMeta(
            n_considered=0, votes_es=0, votes_en=0, votes_unknown=0,
            es_ratio=0.0, en_ratio=0.0, threshold=threshold,
            decision=decision, lines=[], junk_reasons=junk_reasons,
            english_word_override=is_known_english,
        )
        # Even with no evidence, if it's a known English word, classify as English
        if is_known_english and not junk_token:
            meta.decision = "en"
            meta.english_word_override = True
            return "en", meta
        return decision, meta

    # --- Filter lines ---
    usable_lines: List[str] = []
    lines_meta: List[LidLine] = []
    description_lines_removed = 0

    for ln in raw_lines:
        if len(usable_lines) >= max_lines:
            break
        is_j, reasons = line_is_junk(ln)
        if is_j:
            junk_reasons.extend(reasons)
            if "genius_description" in reasons:
                description_lines_removed += 1
            continue
        usable_lines.append(ln)

    # --- No usable lines after filtering ---
    if not usable_lines:
        if junk_token:
            junk_reasons.append("no_usable_lines_after_filter")
            decision = "junk"
        else:
            junk_reasons.append("no_usable_lines_after_filter")
            decision = "no_evidence"

        meta = LidMeta(
            n_considered=0, votes_es=0, votes_en=0, votes_unknown=0,
            es_ratio=0.0, en_ratio=0.0, threshold=threshold,
            decision=decision, lines=[], junk_reasons=junk_reasons,
            english_word_override=is_known_english,
            description_lines_removed=description_lines_removed,
        )
        if is_known_english and not junk_token:
            meta.decision = "en"
            meta.english_word_override = True
            return "en", meta
        return decision, meta

    # --- LID voting ---
    votes_es = votes_en = votes_unk = 0
    for ln in usable_lines:
        ll = detect_line(detector, ln)
        lines_meta.append(ll)
        if ll.detected == "es":
            votes_es += 1
        elif ll.detected == "en":
            votes_en += 1
        else:
            votes_unk += 1

    n = votes_es + votes_en + votes_unk
    es_ratio = (votes_es / n) if n else 0.0
    en_ratio = (votes_en / n) if n else 0.0

    # --- Decision ---
    decision = "mixed"
    if es_ratio >= threshold:
        decision = "es"
    elif en_ratio >= threshold:
        decision = "en"

    # --- English word override ---
    # If token is a known English-only word and line voting says "es" or "mixed",
    # that's because English loanwords appear inside Spanish lines.
    # Override to "en" — these are not Spanish vocabulary.
    if is_known_english and decision != "en":
        decision = "en"

    # --- Junk override ---
    # Vocables are always junk regardless of line voting.
    # They appear in Spanish lines but are not Spanish vocabulary.
    if junk_token and "vocable" in token_reasons:
        decision = "junk"
        junk_reasons.append("vocable_override")
    # Other junk tokens: only override if no strong language vote
    elif junk_token and decision == "mixed":
        decision = "junk"
        junk_reasons.append("token_junk_and_no_strong_language_vote")

    meta = LidMeta(
        n_considered=n,
        votes_es=votes_es,
        votes_en=votes_en,
        votes_unknown=votes_unk,
        es_ratio=es_ratio,
        en_ratio=en_ratio,
        threshold=threshold,
        decision=decision,
        lines=lines_meta,
        junk_reasons=sorted(set(junk_reasons)),
        english_word_override=is_known_english,
        description_lines_removed=description_lines_removed,
    )
    return decision, meta


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Split stage-2 vocab evidence into es/en/mixed/junk/noevidence buckets."
    )
    ap.add_argument("--input", required=True, help="Path to 2_vocab_evidence.json")
    ap.add_argument("--out_dir", default=None,
                    help="Output directory (default: same as input file)")
    ap.add_argument("--out_prefix", default="2_vocab_evidence",
                    help="Output file prefix (default: 2_vocab_evidence)")
    ap.add_argument("--max_lines", type=int, default=5,
                    help="Max context lines per word for voting (default: 5)")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="Vote threshold for es/en (default: 0.6)")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out_dir) if args.out_dir else in_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load input (supports both list and dict formats) ---
    raw = json.loads(in_path.read_text(encoding="utf-8"))

    if isinstance(raw, list):
        # List of {"word": ..., "occurrences_ppm": ..., "examples": [...]}
        data: Dict[str, Dict[str, Any]] = {}
        for entry in raw:
            if isinstance(entry, dict) and "word" in entry:
                data[entry["word"]] = entry
            else:
                print(f"  WARNING: skipping non-dict or missing 'word': {str(entry)[:80]}")
    elif isinstance(raw, dict):
        data = raw
    else:
        raise ValueError(f"Expected input JSON to be a list or dict, got {type(raw).__name__}")

    print(f"Loaded {len(data)} words from {in_path}")

    detector = build_detector()
    print("Lingua detector built (Spanish + English)")

    # --- Buckets (lists, not dicts — matching input format) ---
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "es": [],
        "en": [],
        "mixed": [],
        "junk": [],
        "no_evidence": [],
    }

    # Counters for summary
    english_overrides = 0
    description_removals = 0

    for i, (token, item) in enumerate(data.items()):
        if (i + 1) % 2000 == 0:
            print(f"  ... processed {i + 1}/{len(data)} words")

        if not isinstance(item, dict):
            entry = {
                "word": token,
                "lid_meta": asdict(LidMeta(
                    n_considered=0, votes_es=0, votes_en=0, votes_unknown=0,
                    es_ratio=0.0, en_ratio=0.0, threshold=args.threshold,
                    decision="junk", lines=[], junk_reasons=["value_not_dict"]
                ))
            }
            buckets["junk"].append(entry)
            continue

        decision, meta = classify_word(
            token=token,
            item=item,
            detector=detector,
            max_lines=args.max_lines,
            threshold=args.threshold,
        )

        if meta.english_word_override:
            english_overrides += 1
        description_removals += meta.description_lines_removed

        # Build output entry: keep all original fields + attach lid_meta
        out_item = dict(item)
        out_item["lid_meta"] = asdict(meta)

        buckets[decision].append(out_item)

    # --- Write outputs ---
    def dump(name: str, items: List[Dict[str, Any]]) -> None:
        # Sort by frequency descending for convenience
        items.sort(key=lambda x: -x.get("occurrences_ppm", 0))
        p = out_dir / f"{args.out_prefix}_{name}.json"
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        total_ppm = sum(x.get("occurrences_ppm", 0) for x in items)
        print(f"  {name:12s}: {len(items):6d} words  ({total_ppm:10.0f} ppm)  -> {p.name}")

    print(f"\n=== Results (threshold={args.threshold}) ===")
    dump("es", buckets["es"])
    dump("en", buckets["en"])
    dump("mixed", buckets["mixed"])
    dump("junk", buckets["junk"])
    dump("noevidence", buckets["no_evidence"])

    print(f"\n  English word-list overrides: {english_overrides}")
    print(f"  Genius description lines removed: {description_removals}")

    # --- Show top items per bucket for quick sanity check ---
    for name in ("es", "en", "mixed", "junk", "no_evidence"):
        items = buckets[name]
        if not items:
            continue
        print(f"\n--- Top 15 {name} ---")
        for item in items[:15]:
            word = item.get("word", "???")
            ppm = item.get("occurrences_ppm", 0)
            meta = item.get("lid_meta", {})
            override = " [EN-OVERRIDE]" if meta.get("english_word_override") else ""
            jr = meta.get("junk_reasons", [])
            jr_str = f"  reasons={jr}" if jr else ""
            print(f"  {word:20s}  ppm={ppm:8.0f}  es={meta.get('es_ratio', 0):.2f}  "
                  f"en={meta.get('en_ratio', 0):.2f}{override}{jr_str}")


if __name__ == "__main__":
    main()
