#!/usr/bin/env python3
"""
build_senses.py — Build sense inventory from English Wiktionary (kaikki.org).

Downloads the Spanish extract from kaikki.org (English Wiktionary), then for
each word in vocabulary.json, looks up senses by lemma and produces a clean
sense inventory with POS + English translation.

Usage:
    python3 pipeline/build_senses.py

Run from the project root (Fluency/).

Inputs:
    Data/Spanish/vocabulary.json                              — word list
    Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz   — Wiktionary extract

Output:
    Data/Spanish/senses_wiktionary.json  — {word|lemma: [{pos, translation}, ...]}
"""

import gzip
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"
CONJ_REVERSE_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugation_reverse.json"
CONJ_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugations.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "senses_wiktionary.json"

# ---------------------------------------------------------------------------
# POS mapping: Wiktionary pos -> project UPOS-style tags
# ---------------------------------------------------------------------------
POS_MAP = {
    "noun": "NOUN",
    "verb": "VERB",
    "adj": "ADJ",
    "adv": "ADV",
    "prep": "ADP",
    "prep_phrase": "ADP",
    "conj": "CCONJ",
    "pron": "PRON",
    "det": "DET",
    "article": "DET",
    "intj": "INTJ",
    "num": "NUM",
    "particle": "PART",
    "phrase": "PHRASE",
    "contraction": "CONTRACTION",
}

# Tags that indicate a sense we should skip entirely
SKIP_TAGS = {
    "archaic", "obsolete", "rare", "historical", "dated",
    "abbreviation", "ellipsis",
}

# Regex to extract useful translation from alt-of glosses like:
# "contraction of a + el, literally "at the, to the"" → "at the, to the"
# "apocopic form of mucho; very" → "very"
# "apocopic form of malo bad; evil" → "bad; evil"
_ALT_OF_PATTERNS = [
    # "literally "X"" or 'literally "X"'
    re.compile(r'literally\s+[\u0022\u201c]([^\u0022\u201c\u201d]+)[\u0022\u201d]'),
    # "form of X; translation" (semicolon separates)
    re.compile(r'form of\s+\S+\s*;\s*(.+)'),
    # "form of X Y" where Y doesn't look like a gloss qualifier
    re.compile(r'form of\s+\S+\s+(.+)'),
    # "contraction of X, literally "Y""
    re.compile(r'[\u0022\u201c]([^\u0022\u201c\u201d]+)[\u0022\u201d]'),
]

# form-of senses are skipped UNLESS they contain a useful gloss in parens
# e.g. 'female equivalent of muñeco ("doll")' → extract "doll"

# Regional tags we keep (they're valid senses, just regional)
# But we note them for possible later filtering

MAX_SENSES_PER_POS = 5
MAX_SENSES_TOTAL = 8

# Descriptive/encyclopedic senses that aren't real translations.
# e.g. "used to express wishes" (así), "The name of the Latin script letter D" (de)
_DESCRIPTIVE_SENSE_RE = re.compile(
    r"^("
    r"used to\b"
    r"|a public\b"
    r"|the name of\b"
    r"|expression\b"
    r"|indicating\b"
    r"|stressed in\b"
    r"|feminine\b"
    r"|masculine\b"
    r"|said of\b"
    r"|placed before\b"
    r"|placed after\b"
    r"|an? [a-z]+ (of|that|which|used|for)\b"
    r")",
    re.IGNORECASE,
)

# Words that start a parenthetical clarification (not an essential object)
_CLARIFICATION_STARTERS = {
    "used", "especially", "usually", "often", "expressing", "indicating",
    "introducing", "denotes", "denoting", "state", "adverbial", "in", "for",
    "with", "as", "when", "because", "can", "may", "e.g.", "i.e.",
    "including", "similar", "sometimes", "literally", "figuratively",
    "by", "from", "implies", "also", "regarded",
    "accusative", "dative", "genitive", "nominative", "declined",
    "apocopic", "conjugated", "inflected", "preceded",
}

# Match balanced parenthetical content (handles one level of nesting)
_PAREN_RE = re.compile(r'\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)')

# Stop words for sense merging (shared content-word extraction)
_MERGE_STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
    "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
    "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "shall", "should",
    "up", "out", "if", "so", "no", "into", "over", "also", "its", "one",
}
_WORD_RE = re.compile(r"[a-z]+")

# Regex to extract useful gloss from form-of entries like:
# 'female equivalent of muñeco ("doll")' → "doll"
# Patterns to extract useful English from form-of glosses, tried in order:
_FORM_OF_PATTERNS = [
    # "female equivalent of muñeco ("doll")" → doll
    re.compile(r'[\u0022\u201c\u201d]([^\u0022\u201c\u201d]+)[\u0022\u201c\u201d]'),
    # "female equivalent of muchacho: girl, young lady" → girl, young lady
    # "comparative degree of malo: worse" → worse
    # "dative of nosotros: to us, for us" → to us, for us
    # "accusative of él and usted: him, you" → him, you
    # "dative of ellos and ellas: to them" → to them
    re.compile(r'\bof\s+.{1,30}?:\s*(.+)'),
    # "accusative of ellas; them" → them (semicolon variant)
    # "dative of ellos and ellas; to them, for them" → to them, for them
    re.compile(r'\bof\s+.{1,30}?;\s*(.+)'),
    # "female equivalent of amigo, friend" → friend
    re.compile(r'equivalent of\s+\w+,\s*(.+)'),
]


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------
def strip_accents(s: str) -> str:
    """Remove diacritics for accent-normalized matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


# ---------------------------------------------------------------------------
# Load Wiktionary index: word -> [{pos, senses: [{gloss, tags}]}]
# ---------------------------------------------------------------------------
def load_wiktionary(path: Path, use_cache: bool = True) -> dict:
    """
    Load kaikki.org JSONL and build a lookup dict.
    Keys = lowercase word AND accent-stripped word.
    Value = list of (pos, [senses]) tuples.

    Caches the parsed index as a pickle next to the JSONL for fast reloads.
    """
    import pickle
    cache_path = Path(str(path) + ".cache.pkl")
    if use_cache and cache_path.exists():
        if cache_path.stat().st_mtime >= path.stat().st_mtime:
            print(f"Loading Wiktionary from cache ({cache_path.name})...")
            with open(cache_path, "rb") as f:
                data = pickle.load(f)
            print(f"  {len(data[0])} unique lookup keys, {len(data[1])} form-of redirects")
            return data

    print(f"Loading Wiktionary from {path}...")
    index = defaultdict(list)
    redirects = {}  # form-of word → base lemma (e.g. amiga → amigo)
    total = 0
    skipped = 0

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            total += 1
            item = json.loads(line)
            word = item.get("word", "").lower()
            raw_pos = item.get("pos", "")
            mapped_pos = POS_MAP.get(raw_pos)

            if not word or not mapped_pos:
                continue

            senses = item.get("senses", [])
            real_senses = []
            for s in senses:
                tags = set(s.get("tags", []))

                glosses = s.get("glosses", [])
                if not glosses:
                    continue
                gloss = glosses[0]

                # Handle alt-of first (before SKIP_TAGS) so we can rescue
                # useful glosses like 'contraction of a + el, literally "at the, to the"'
                # even when other skip tags (e.g. abbreviation) are present.
                if "alt-of" in tags:
                    extracted = None
                    for pattern in _ALT_OF_PATTERNS:
                        m = pattern.search(gloss)
                        if m:
                            extracted = m.group(1).strip()
                            break
                    if extracted:
                        gloss = extracted
                        # Clear skip tags so this sense survives
                        tags = tags - SKIP_TAGS
                    else:
                        # Pure alt-of with no extractable translation, skip
                        continue

                # Skip senses with disqualifying tags (but handle form-of specially)
                if tags & SKIP_TAGS:
                    continue

                # Handle form-of: extract the useful part if present
                if "form-of" in tags:
                    extracted = None
                    for pattern in _FORM_OF_PATTERNS:
                        m = pattern.search(gloss)
                        if m:
                            extracted = m.group(1).strip()
                            break
                    if extracted:
                        gloss = extracted
                    else:
                        # Pure inflection reference (e.g. "feminine singular of bueno"), skip
                        continue

                if len(gloss) < 2:
                    continue

                real_senses.append({
                    "gloss": gloss,
                    "tags": sorted(tags - {"form-of"}) if tags else [],
                })

            if not real_senses:
                # Build redirect for form-of entries: amiga → amigo, peor → malo
                for s in senses:
                    for fo in s.get("form_of", []):
                        base = fo.get("word", "").lower()
                        if base and base != word:
                            redirects[word] = base
                            norm = strip_accents(word)
                            if norm != word:
                                redirects[norm] = base
                skipped += 1
                continue

            entry = {"pos": mapped_pos, "senses": real_senses}
            index[word].append(entry)
            # Also index by accent-stripped form for fallback lookups
            norm = strip_accents(word)
            if norm != word:
                index[norm].append(entry)

    print(f"  {total} total entries, {skipped} skipped (no real senses)")
    print(f"  {len(index)} unique lookup keys, {len(redirects)} form-of redirects")
    result = dict(index), dict(redirects)

    if use_cache:
        import pickle
        print(f"  Caching to {cache_path.name}...")
        with open(cache_path, "wb") as f:
            pickle.dump(result, f)

    return result


# ---------------------------------------------------------------------------
# Look up senses for a vocabulary entry
# ---------------------------------------------------------------------------
def lookup_senses(word: str, lemma: str, wikt_index: dict,
                   redirects: dict = None) -> list[dict]:
    """
    Look up senses for a word, merging results from both word and lemma.
    e.g. llama|llamar → verb senses from "llamar" + noun senses from "llama".
    Falls back to accent-stripped forms and form-of redirects.
    Returns list of {pos, translation} dicts.
    """
    redirects = redirects or {}

    # Build groups of forms: primary (lemma), secondary (word if different)
    # We merge results from all matching groups
    groups = []
    # Group 1: lemma and its variants
    lemma_forms = [lemma.lower(), strip_accents(lemma.lower())]
    for f in list(lemma_forms):
        if f in redirects:
            lemma_forms.append(redirects[f])
    groups.append(lemma_forms)
    # Group 2: word form and its variants (if different from lemma)
    if word.lower() != lemma.lower():
        word_forms = [word.lower(), strip_accents(word.lower())]
        for f in list(word_forms):
            if f in redirects:
                word_forms.append(redirects[f])
        groups.append(word_forms)

    # Collect candidates from all groups
    all_candidates = []
    for group in groups:
        for form in group:
            candidates = wikt_index.get(form)
            if candidates:
                all_candidates.extend(candidates)
                break  # found for this group, move to next

    if not all_candidates:
        return []

    candidates = all_candidates

    results = []
    seen = set()  # (pos, normalized_gloss) to dedup

    for entry in candidates:
        pos = entry["pos"]
        count_for_pos = sum(1 for r in results if r["pos"] == pos)

        for sense in entry["senses"]:
            if count_for_pos >= MAX_SENSES_PER_POS:
                break

            gloss = sense["gloss"]

            # Normalize for dedup: lowercase, strip parens
            norm_key = (pos, gloss.lower().split("(")[0].strip())
            if norm_key in seen:
                continue
            seen.add(norm_key)

            results.append({
                "pos": pos,
                "translation": gloss,
                "source": "wiktionary",
            })
            count_for_pos += 1

    return results


# ---------------------------------------------------------------------------
# Translation cleaning: strip verbose Wiktionary glosses for flashcard use
# ---------------------------------------------------------------------------
def clean_translation(gloss: str) -> str:
    """
    Trim a Wiktionary gloss to flashcard-friendly length.
    0. Extract translation from "grammar description: actual translation" pattern.
    1. Strip trailing parenthetical clarifications (keep essential objects).
    2. Truncate comma-separated synonym chains (keep first 3).
    3. Strip semicolon-separated usage notes.
    """
    text = gloss.strip()

    # --- Step 0: Extract translation from "long description: translation" or
    # "long description; translation" patterns ---
    # e.g. "neuter definite article...: the, that which is" → "the, that which is"
    # e.g. "second person pronoun in singular tense; you" → "you"
    # Only when the part before the separator is clearly descriptive (long) and
    # the part after is a short translation.
    for sep in (": ", "; "):
        if sep in text:
            sep_idx = text.index(sep)
            before = text[:sep_idx]
            after = text[sep_idx + len(sep):].strip()
            if len(before) > 30 and 0 < len(after) < 50:
                text = after
                break

    # --- Step 1: Strip parenthetical clarifications (anywhere in gloss) ---
    # Process right-to-left so indices stay valid
    matches = list(_PAREN_RE.finditer(text))
    for m in reversed(matches):
        inner = m.group(1).strip()
        first_word = inner.split()[0].lower().rstrip(".,;:") if inner else ""

        if len(inner) > 30:
            strip_it = True
        elif "etc" in inner.lower() or "e.g." in inner.lower() or "i.e." in inner.lower():
            strip_it = True
        elif first_word in _CLARIFICATION_STARTERS:
            strip_it = True
        elif first_word in ("a", "an", "the") and len(inner) < 25:
            # Essential object like "(a decision)" — keep
            strip_it = False
        else:
            strip_it = True

        if strip_it:
            text = text[:m.start()] + text[m.end():]
    text = text.strip()

    # --- Step 2: Truncate comma-separated synonym chains ---
    parts = text.split(", ")
    if len(parts) >= 4:
        text = ", ".join(parts[:3])

    # --- Step 3: Strip semicolon usage notes ---
    semi_parts = text.split("; ")
    if len(semi_parts) > 1:
        kept = []
        for part in semi_parts:
            first_word = part.strip().split()[0].lower().rstrip(".,;:") if part.strip() else ""
            if first_word in _CLARIFICATION_STARTERS:
                break  # Drop this part and everything after
            # Truncate comma chains within each semicolon segment
            sub = part.split(", ")
            if len(sub) >= 3:
                part = ", ".join(sub[:2])
            kept.append(part)
        if len(kept) >= 4:
            kept = kept[:3]
        text = "; ".join(kept)

    # Safety: never return empty
    text = text.strip().rstrip(",;")
    return text if text else gloss


# ---------------------------------------------------------------------------
# Sense merging: collapse near-duplicate senses within the same POS
# ---------------------------------------------------------------------------
def _content_words(text: str) -> set:
    """Extract content words from a translation for similarity comparison."""
    # Strip parenthetical content
    text = text.split("(")[0]
    return {w for w in _WORD_RE.findall(text.lower())
            if w not in _MERGE_STOP_WORDS and len(w) > 1}


def merge_similar_senses(senses: list) -> list:
    """
    Merge near-duplicate senses within the same POS using Jaccard similarity
    on content words. Picks the shortest translation as representative.
    """
    if len(senses) <= 1:
        return senses

    # Group by POS
    groups = defaultdict(list)
    for i, s in enumerate(senses):
        groups[s["pos"]].append((i, s))

    merged = []
    for pos, members in groups.items():
        if len(members) <= 1:
            merged.append(members[0][1])
            continue

        # Compute content words for each sense
        words = [_content_words(s["translation"]) for _, s in members]

        # Union-find for clustering
        parent = list(range(len(members)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                ti = members[i][1]["translation"].lower().strip()
                tj = members[j][1]["translation"].lower().strip()
                wi, wj = words[i], words[j]
                if not wi and not wj:
                    # Both have empty content words (stop-word-only translations
                    # like "with", "on", "to"). Only merge if literally identical.
                    if ti == tj:
                        union(i, j)
                    continue
                union_size = len(wi | wj)
                if union_size == 0:
                    continue
                jaccard = len(wi & wj) / union_size
                if jaccard >= 0.3:
                    union(i, j)

        # Collect clusters and pick representative (shortest translation)
        clusters = defaultdict(list)
        for i in range(len(members)):
            clusters[find(i)].append(i)

        for cluster_indices in clusters.values():
            if len(cluster_indices) == 1:
                merged.append(members[cluster_indices[0]][1])
                continue
            # Combine synonyms from all cluster members into one sense.
            # Start with the longest translation, then append unique terms
            # from others.
            base_idx = max(cluster_indices,
                           key=lambda i: len(members[i][1]["translation"]))
            base_sense = dict(members[base_idx][1])  # copy
            base_terms = [t.strip().lower()
                          for t in base_sense["translation"].split(",")]
            base_terms_set = set(base_terms)
            combined = base_sense["translation"]
            for ci in cluster_indices:
                if ci == base_idx:
                    continue
                other = members[ci][1]["translation"]
                for term in other.split(","):
                    term_clean = term.strip()
                    if term_clean.lower() not in base_terms_set and term_clean:
                        combined += ", " + term_clean
                        base_terms_set.add(term_clean.lower())
            base_sense["translation"] = combined
            merged.append(base_sense)

    # Preserve original POS ordering
    pos_order = []
    seen_pos = set()
    for s in senses:
        if s["pos"] not in seen_pos:
            pos_order.append(s["pos"])
            seen_pos.add(s["pos"])

    merged.sort(key=lambda s: pos_order.index(s["pos"]))
    return merged


# ---------------------------------------------------------------------------
# Stemming + divergence detection for gap-fill triggering
# ---------------------------------------------------------------------------
_STEM_SUFFIXES = [
    ("ying", 1, "y"),   # lying → ly (then +y)
    ("ies", 3, "y"),    # carries → carry
    ("ied", 3, "y"),    # carried → carry
    ("ing", 3, ""),     # putting → putt → put (handled by min-length)
    ("tion", 4, "te"),  # attraction → attracte ≈ attract (close enough for overlap)
    ("ness", 4, ""),    # sadness → sad
    ("ment", 4, ""),    # movement → move
    ("ally", 4, "al"),  # physically → physical
    ("ly", 2, ""),      # intensely → intense
    ("ed", 2, ""),      # placed → plac ≈ place
    ("er", 2, ""),      # harder → hard
    ("es", 2, ""),      # places → plac
    ("s", 1, ""),       # cats → cat
]


def stem_en(word: str) -> str:
    """Minimal English suffix stripper for overlap comparison.

    Not a real stemmer — just strips common suffixes so that
    'puts'/'putting'/'put' and 'attractive'/'attract' converge.
    """
    w = word.lower()
    for suffix, min_stem, replacement in _STEM_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= min_stem:
            return w[:-len(suffix)] + replacement
    return w


def stemmed_content_words(text: str) -> set:
    """Extract stemmed content words from English text."""
    return {stem_en(w) for w in _WORD_RE.findall(text.lower())
            if w not in _MERGE_STOP_WORDS and len(w) > 1}


def content_word_overlap(text_a: str, text_b: str) -> bool:
    """Check if two English texts share any stemmed content words.

    Used by gap-fill divergence detection: if actual_meaning shares a word
    with the Wiktionary sense translation, the sense probably covers the usage.
    """
    a = stemmed_content_words(text_a)
    b = stemmed_content_words(text_b)
    if not a or not b:
        return False  # empty content → can't confirm overlap
    return bool(a & b)


# ---------------------------------------------------------------------------
# Sense reordering: deprioritize letter-name and meta-linguistic senses
# ---------------------------------------------------------------------------
_LETTER_PATTERNS = re.compile(
    r'\b(letter|script|alphabet|latin|greek|cyrillic|name of the)\b', re.IGNORECASE
)

# POS tags for function words — these should rank above letter-name NOUNs
_FUNCTION_POS = {"ADP", "DET", "PRON", "CCONJ", "PART", "ADV", "CONTRACTION"}


def _deprioritize_letter_senses(senses: list) -> list:
    """
    Move NOUN senses about letter names to the end, but only when better
    function-word senses exist. Prevents "de" → NOUN "letter D" ranking
    above ADP "of".
    """
    if len(senses) <= 1:
        return senses

    has_function_sense = any(s["pos"] in _FUNCTION_POS for s in senses)
    if not has_function_sense:
        return senses

    normal = []
    demoted = []
    for s in senses:
        if s["pos"] == "NOUN" and _LETTER_PATTERNS.search(s["translation"]):
            demoted.append(s)
        else:
            normal.append(s)

    return normal + demoted if demoted else senses


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not WIKT_FILE.exists():
        print(f"ERROR: Wiktionary file not found: {WIKT_FILE}")
        print("Download it with:")
        print('  curl -L -o Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz \\')
        print('    "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl.gz"')
        sys.exit(1)

    # Load word inventory
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        vocab = json.load(f)
    print(f"  {len(vocab)} entries")

    # Load Wiktionary
    wikt_index, redirects = load_wiktionary(WIKT_FILE)

    # Load conjugation data (optional — generated by build_conjugations.py)
    conj_reverse = {}
    conj_translations = {}
    conj_known_verbs = set()  # All infinitives that have conjugation data
    if CONJ_REVERSE_FILE.exists():
        print("Loading conjugation reverse lookup...")
        with open(CONJ_REVERSE_FILE, encoding="utf-8") as f:
            conj_reverse = json.load(f)
        print(f"  {len(conj_reverse)} conjugated forms")
    else:
        print("No conjugation_reverse.json found — skipping verb POS filtering")
        print("  (run build_conjugations.py first to enable)")

    if CONJ_FILE.exists():
        print("Loading conjugation data...")
        with open(CONJ_FILE, encoding="utf-8") as f:
            conj_data = json.load(f)
        conj_known_verbs = set(conj_data.keys())
        conj_translations = {
            k: v["translation"] for k, v in conj_data.items()
            if "translation" in v
        }
        print(f"  {len(conj_known_verbs)} known verb infinitives")
        print(f"  {len(conj_translations)} with Jehle translations")

    # Look up senses for each vocab word
    print("\nLooking up senses (with cleaning + merging)...")
    output = {}
    stats = {
        "matched": 0,
        "unmatched": 0,
        "multi_sense": 0,
        "sense_counts": defaultdict(int),
        "total_raw": 0,
        "total_after_clean": 0,
        "total_final": 0,
        "verb_filtered": 0,
        "jehle_fallback": 0,
        "descriptive_filtered": 0,
    }
    unmatched_words = []

    for entry in vocab:
        word = entry["word"]
        lemma = entry.get("lemma", word)
        key = f"{word}|{lemma}"

        senses = lookup_senses(word, lemma, wikt_index, redirects)

        if senses:
            stats["total_raw"] += len(senses)

            # Step 1: Clean translations (preserve raw as detail if changed)
            for s in senses:
                raw = s["translation"]
                s["translation"] = clean_translation(raw)
                if s["translation"] != raw:
                    s["detail"] = raw

            # Step 1b: Filter descriptive/encyclopedic senses
            before_desc = len(senses)
            senses_before_filter = list(senses)
            senses = [s for s in senses
                       if not _DESCRIPTIVE_SENSE_RE.match(s["translation"])]
            if not senses:
                # Don't remove ALL senses — keep first original
                senses = senses_before_filter[:1]
            stats["descriptive_filtered"] += before_desc - len(senses)

            # Step 2: Exact dedup (cleaning may collapse previously-distinct glosses)
            seen = set()
            deduped = []
            for s in senses:
                dedup_key = (s["pos"], s["translation"].lower())
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    deduped.append(s)
            senses = deduped
            stats["total_after_clean"] += len(senses)

            # Step 3: Merge near-duplicate senses
            senses = merge_similar_senses(senses)

            # Step 4: Deprioritize letter-name / meta-linguistic NOUN senses
            # e.g. NOUN "The name of the Latin script letter D/d." should rank
            # below ADP "of" for the word "de"
            senses = _deprioritize_letter_senses(senses)

            # Step 5: Conjugation-based POS filtering
            # If conjugation data confirms this is a verb entry (word is a
            # conjugated form of lemma), remove non-VERB senses entirely.
            # e.g. como|comer should only have VERB senses, not CCONJ/ADV/ADP
            # from "como" the conjunction.
            if conj_reverse:
                word_lower = word.lower()
                reverse_entries = conj_reverse.get(word_lower, [])
                is_confirmed_verb = any(
                    e["lemma"] == lemma.lower() for e in reverse_entries
                )
                # Also confirm if word == lemma and lemma is a known infinitive
                if not is_confirmed_verb and word_lower == lemma.lower():
                    is_confirmed_verb = word_lower in conj_known_verbs

                if is_confirmed_verb:
                    verb_senses = [s for s in senses if s["pos"] == "VERB"]
                    if verb_senses:
                        non_verb_count = len(senses) - len(verb_senses)
                        if non_verb_count > 0:
                            stats["verb_filtered"] += 1
                        senses = verb_senses

            # Step 6: Cross-POS dedup — if the same translation appears under
            # multiple POS (e.g. "as" as ADV, CCONJ, ADP), keep only the first.
            # Fewer senses = better embedding classification accuracy.
            seen_trans = set()
            cross_deduped = []
            for s in senses:
                norm = s["translation"].lower().strip().split("(")[0].strip()
                if norm in seen_trans:
                    continue
                seen_trans.add(norm)
                cross_deduped.append(s)
            senses = cross_deduped

            # Step 7: Total sense cap
            if len(senses) > MAX_SENSES_TOTAL:
                senses = senses[:MAX_SENSES_TOTAL]

            stats["total_final"] += len(senses)

            output[key] = senses
            stats["matched"] += 1
            n = len(senses)
            if n >= 2:
                stats["multi_sense"] += 1
            stats["sense_counts"][min(n, 6)] += 1  # bucket 6+
        else:
            # No Wiktionary senses — try Jehle translation fallback for verbs
            if conj_translations:
                lemma_lower = lemma.lower()
                if lemma_lower in conj_translations:
                    senses = [{"pos": "VERB", "translation": conj_translations[lemma_lower], "source": "jehle"}]
                    output[key] = senses
                    stats["matched"] += 1
                    stats["jehle_fallback"] += 1
                    stats["sense_counts"][1] += 1
                    stats["total_final"] += 1
                    continue

            stats["unmatched"] += 1
            unmatched_words.append(key)

    # Write output
    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Report
    total = len(vocab)
    print(f"\n{'='*55}")
    print("SENSE DISCOVERY RESULTS")
    print(f"{'='*55}")
    print(f"Total vocabulary:    {total:>6}")
    print(f"Matched in Wikt:     {stats['matched']:>6}  ({100*stats['matched']/total:.1f}%)")
    print(f"  Jehle fallback:    {stats['jehle_fallback']:>6}")
    print(f"Unmatched:           {stats['unmatched']:>6}  ({100*stats['unmatched']/total:.1f}%)")
    print(f"With 2+ senses:      {stats['multi_sense']:>6}  ({100*stats['multi_sense']/total:.1f}%)")
    print(f"Descriptive filter:  {stats['descriptive_filtered']:>6}  (encyclopedic senses removed)")
    print(f"Verb POS filtered:   {stats['verb_filtered']:>6}  (non-VERB senses removed)")
    print()
    raw = stats["total_raw"]
    after_clean = stats["total_after_clean"]
    final = stats["total_final"]
    print(f"Sense pipeline:      {raw} raw → {after_clean} after clean/dedup → {final} after merge")
    print(f"  Removed by clean:  {raw - after_clean:>6}")
    print(f"  Removed by merge:  {after_clean - final:>6}")
    print()
    print("Sense count distribution:")
    for n in sorted(stats["sense_counts"]):
        label = f"{n}+" if n == 6 else str(n)
        count = stats["sense_counts"][n]
        print(f"  {label} senses: {count:>6} words")
    print()

    # Show sample unmatched
    if unmatched_words:
        sample = unmatched_words[:30]
        print(f"Sample unmatched words ({len(unmatched_words)} total):")
        for w in sample:
            print(f"  {w}")

    # Show a few polysemous examples
    print()
    print("Sample multi-sense entries:")
    examples = ["banco|banco", "tomar|tomar", "pasar|pasar", "poder|poder",
                "rico|rico", "muñeca|muñeca", "hacer|hacer",
                "tiempo|tiempo", "mejor|mejor", "bien|bien", "de|de",
                "está|estar", "como|como"]
    for key in examples:
        if key in output:
            senses = output[key]
            print(f"\n  {key} ({len(senses)} senses):")
            for s in senses:
                print(f"    {s['pos']:>8}  {s['translation']}")


if __name__ == "__main__":
    main()
