#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
2b_split_lang_and_junk_lingua.py

Post-stage-2 audit-friendly splitter:
- Spanish vs English vs Mixed vs Junk
- line-level language ID (Lingua), then voting per word
- deterministic heuristics for junk/adlibs/scrape artifacts

Expected input:
- A dict keyed by word (or lemma), each value contains examples/contexts lines somewhere.
  This script tries common keys: ["contexts", "examples", "evidence", "lines"].

Output:
- <out_prefix>_es.json
- <out_prefix>_en.json
- <out_prefix>_mixed.json
- <out_prefix>_junk.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lingua import Language, LanguageDetectorBuilder

# -------------------------
# Config / heuristics
# -------------------------

GENIUS_JUNK_PATTERNS = [
    r"\bread more\b",
    r"\byou might also like\b",
    r"\bembed\b",
    r"\btranslation\b",
    r"\btranscript\b",
]

# Common ad-libs / vocables (extend as you see them)
VOCABLES = {
    "oh", "uh", "ouh", "ooh", "woo", "wooh", "yeah", "yea", "yah", "ayy", "ay",
    "eh", "mm", "mmm", "hah", "haha", "la", "na", "nan", "lalala", "nanan",
}

WORD_CHARS_RE = re.compile(r"^[\wÀ-ÿ'’-]+$", re.UNICODE)  # includes accents + apostrophes
REPEATED_CHAR_RE = re.compile(r"(.)\1{3,}")  # aaaa, oooo, !!!! etc.
HAS_LETTER_RE = re.compile(r"[A-Za-zÀ-ÿ]", re.UNICODE)


@dataclass
class LidLine:
    text: str
    detected: str  # "es" | "en" | "unknown"
    confidence: Optional[float] = None


@dataclass
class LidMeta:
    n_considered: int
    votes_es: int
    votes_en: int
    votes_unknown: int
    es_ratio: float
    en_ratio: float
    threshold: float
    decision: str  # "es" | "en" | "mixed" | "junk"
    lines: List[LidLine]
    junk_reasons: List[str]


# -------------------------
# Helpers
# -------------------------

def normalize_token(token: str) -> str:
    t = token.strip().lower()
    # normalize curly apostrophes
    t = t.replace("’", "'").replace("´", "'").replace("`", "'")
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

    # Very short tokens
    if len(t) <= 1:
        reasons.append("too_short")

    # Contains no letters at all (numbers/punct only)
    if not HAS_LETTER_RE.search(t):
        reasons.append("no_letters")

    # Not composed of reasonable word characters (e.g., lots of symbols)
    if not WORD_CHARS_RE.match(t):
        reasons.append("non_word_chars")

    # Repeated characters
    if REPEATED_CHAR_RE.search(t):
        reasons.append("repeated_chars")

    # Known vocables/adlibs
    if t in VOCABLES:
        reasons.append("vocable")

    # If 2+ reasons, call it junk; or if certain strong reasons
    strong = {"empty_token", "no_letters"}
    if any(r in strong for r in reasons):
        return True, reasons

    return (len(reasons) >= 2), reasons


def line_is_junk(line: str) -> Tuple[bool, List[str]]:
    """
    Line-level junk patterns: Genius boilerplate, empty, etc.
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

    return (len(reasons) > 0 and ("empty_line" in reasons or "genius_junk" in " ".join(reasons))), reasons


def extract_lines(item: Any) -> List[str]:
    """
    Try to pull lyric lines out of common structures.
    Supports:
      - item["contexts"] = [{"line_text": "..."}...]
      - item["examples"] = [{"line_text": "..."}...]
      - item["contexts"] = ["...","..."]
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
                    # common keys
                    for lk in ("line_text", "text", "line", "lyric", "sentence"):
                        if lk in x and isinstance(x[lk], str):
                            lines.append(x[lk])
                            break
            if lines:
                return lines

    return []


def build_detector() -> Any:
    # Restrict to Spanish + English for your use case (faster, clearer)
    return LanguageDetectorBuilder.from_languages(Language.SPANISH, Language.ENGLISH).build()


def detect_line(detector: Any, line: str) -> LidLine:
    """
    Detect language of a line.
    If Lingua can't decide, mark unknown.
    Try to include a confidence if API supports it.
    """
    text = (line or "").strip()

    # Lingua method names vary slightly by version; handle robustly
    detected_lang = None
    confidence = None

    # Preferred: confidences
    if hasattr(detector, "compute_language_confidence_values"):
        confs = detector.compute_language_confidence_values(text)
        # confs is typically a list of objects with .language and .value
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
    Returns (bucket, lid_meta)
    """
    junk_token, token_reasons = is_gibberish_token(token)

    raw_lines = extract_lines(item)
    usable_lines: List[str] = []
    junk_reasons: List[str] = list(token_reasons)

    if not raw_lines:
        junk_reasons.append("no_context_lines")
        # If no context, we can't LID vote; treat as junk (auditable)
        meta = LidMeta(
            n_considered=0,
            votes_es=0,
            votes_en=0,
            votes_unknown=0,
            es_ratio=0.0,
            en_ratio=0.0,
            threshold=threshold,
            decision="junk",
            lines=[],
            junk_reasons=junk_reasons,
        )
        return "junk", meta

    # Filter/collect up to max_lines usable lines
    lines_meta: List[LidLine] = []
    for ln in raw_lines:
        if len(usable_lines) >= max_lines:
            break
        is_j, reasons = line_is_junk(ln)
        if is_j:
            junk_reasons.extend(reasons)
            continue
        usable_lines.append(ln)

    # If none usable, mark junk
    if not usable_lines:
        junk_reasons.append("no_usable_lines_after_filter")
        meta = LidMeta(
            n_considered=0,
            votes_es=0,
            votes_en=0,
            votes_unknown=0,
            es_ratio=0.0,
            en_ratio=0.0,
            threshold=threshold,
            decision="junk",
            lines=[],
            junk_reasons=junk_reasons,
        )
        return "junk", meta

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

    # Decide bucket based on voting
    decision = "mixed"
    if es_ratio >= threshold:
        decision = "es"
    elif en_ratio >= threshold:
        decision = "en"
    else:
        decision = "mixed"

    # If token looks like junk AND we don’t have strong language evidence, mark junk
    if junk_token and decision != "es" and decision != "en":
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
    )
    return decision, meta


# -------------------------
# Main
# -------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to 2_vocab_evidence.json")
    ap.add_argument("--out_dir", default=".", help="Output directory")
    ap.add_argument("--out_prefix", default="2b_vocab_split", help="Output file prefix")
    ap.add_argument("--max_lines", type=int, default=5, help="Max context lines per word for voting")
    ap.add_argument("--threshold", type=float, default=0.7, help="Vote threshold for es/en (0..1)")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected input JSON to be a dict keyed by token/word.")

    detector = build_detector()

    buckets: Dict[str, Dict[str, Any]] = {
        "es": {},
        "en": {},
        "mixed": {},
        "junk": {},
    }

    for token, item in data.items():
        if not isinstance(item, dict):
            # keep auditable
            buckets["junk"][token] = {
                "original": item,
                "lid_meta": asdict(LidMeta(
                    n_considered=0, votes_es=0, votes_en=0, votes_unknown=0,
                    es_ratio=0.0, en_ratio=0.0, threshold=args.threshold,
                    decision="junk", lines=[], junk_reasons=["value_not_dict"]
                ))
            }
            continue

        decision, meta = classify_word(
            token=token,
            item=item,
            detector=detector,
            max_lines=args.max_lines,
            threshold=args.threshold,
        )

        # Attach metadata but keep original fields intact
        out_item = dict(item)
        out_item["lid_meta"] = asdict(meta)

        buckets[decision][token] = out_item

    def dump(name: str, obj: Any) -> None:
        p = out_dir / f"{args.out_prefix}_{name}.json"
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {p} ({len(obj)} items)")

    dump("es", buckets["es"])
    dump("en", buckets["en"])
    dump("mixed", buckets["mixed"])
    dump("junk", buckets["junk"])


if __name__ == "__main__":
    main()
