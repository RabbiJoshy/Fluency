#!/usr/bin/env python3
"""
step_5c_build_senses.py — Build sense inventory from English Wiktionary (kaikki.org).

Downloads the Spanish extract from kaikki.org (English Wiktionary), then for
each word in vocabulary.json, looks up senses by lemma and produces a clean
sense inventory with POS + English translation.

Usage:
    python3 pipeline/step_5c_build_senses.py

Run from the project root (Fluency/).

Inputs:
    Data/Spanish/vocabulary.json                              — word list
    Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz   — Wiktionary extract

Output:
    Data/Spanish/layers/sense_menu.json  — {word: [{headword, senses: {id: {pos, translation}}}]}
"""

import gzip
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from util_5c_sense_menu_format import (
    assign_analysis_sense_ids, flatten_analyses_with_ids, normalize_artist_sense_menu,
)

# SpanishDict helpers (shared cache paths + menu assembly, both modes)
from util_5c_spanishdict import (
    SPANISHDICT_SURFACE_CACHE, SPANISHDICT_HEADWORD_CACHE, SPANISHDICT_STATUS,
    build_menu_analyses, load_json,
)

# Per-source path helpers
from util_5c_sense_paths import sense_menu_path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "wiktionary + spanishdict sense menus, cross-POS dedup, sense cap",
    2: "wiktionary: preserve raw_gloss/topics/qualifier/examples; derive context; "
       "follow form-of redirects alongside bare-form senses; comma form-of pattern; "
       "allow single-char glosses (je → I)",
}

# Bumped whenever the shape of the pickled load_wiktionary cache changes.
CACHE_SCHEMA_VERSION = 4

INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"
CONJ_REVERSE_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugation_reverse.json"
CONJ_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugations.json"
LAYERS_DIR = PROJECT_ROOT / "Data" / "Spanish" / "layers"

# Per-language defaults for --language {spanish,french}. Any of these paths
# can be missing (the kaikki file is the only one that strictly matters) —
# downstream loaders print warnings and degrade gracefully.
_LANGUAGE_PATHS = {
    "spanish": {
        "inventory": INVENTORY_FILE,
        "wiktionary": WIKT_FILE,
        "conj_reverse": CONJ_REVERSE_FILE,
        "conj": CONJ_FILE,
        "layers": LAYERS_DIR,
    },
    "french": {
        "inventory": PROJECT_ROOT / "Data" / "French" / "layers" / "word_inventory.json",
        "wiktionary": PROJECT_ROOT / "Data" / "French" / "Senses" / "wiktionary" / "kaikki-french.jsonl.gz",
        "conj_reverse": PROJECT_ROOT / "Data" / "French" / "layers" / "conjugation_reverse.json",
        "conj": PROJECT_ROOT / "Data" / "French" / "layers" / "conjugations.json",
        "layers": PROJECT_ROOT / "Data" / "French" / "layers",
    },
}

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
    "name": "PROPN",
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

# Kaikki's `tags` field mixes inflection markers with real semantic tags. We
# strip inflection markers when building the per-sense `register` list so the
# output only surfaces tags that help a learner (transitive/reflexive/slang/…).
INFLECTION_TAGS = frozenset({
    "form-of", "plural", "singular", "masculine", "feminine",
    "first-person", "second-person", "third-person",
    "subjunctive", "indicative", "present", "imperfect", "past",
    "historic", "future", "participle", "imperative", "conditional",
    "gerund", "infinitive", "object-first-person", "object-second-person",
    "object-third-person", "object-singular", "object-plural",
    "object-masculine", "object-feminine", "preterite",
    "accusative", "dative", "nominative", "genitive", "vocative",
    "with-voseo", "by-personal-gender", "invariable", "letter",
    "lowercase", "uppercase", "countable", "uncountable",
})

# A "context" disambiguator looks like "of clothing", "of food", "when used
# with à". We build it by peeling the leading parenthetical off `raw_gloss`,
# dropping any token already surfaced as a register/domain tag. The remainder
# is what distinguishes senses within a POS (cf. SpanishDict's `context`).
_LEADING_PAREN_RE = re.compile(r"^\s*\(([^)]+)\)\s*(.*)$", re.DOTALL)


def _context_from_raw_gloss(raw_gloss: str, tags: set, topics: list) -> str:
    """Return a short SpanishDict-style context string or ''.

    `raw_gloss` is Kaikki's full gloss including the leading parenthetical, e.g.
      "(transitive, of clothing) to put on"
    We strip terms already covered by `tags`/`topics` so the context carries
    only the novel disambiguator ("of clothing", not "transitive").
    """
    if not raw_gloss:
        return ""
    m = _LEADING_PAREN_RE.match(raw_gloss)
    if not m:
        return ""
    paren = m.group(1).strip()
    if not paren:
        return ""
    # Split by comma/semicolon, drop tokens already in tags/topics.
    known = {t.lower() for t in tags} | {t.lower() for t in topics}
    parts = [p.strip() for p in re.split(r"[,;]", paren) if p.strip()]
    kept = [p for p in parts if p.lower() not in known and not _is_region_tag(p)]
    return "; ".join(kept)


# Region tags Kaikki surfaces in `tags` look like "Quebec", "Louisiana", etc.
_REGION_RE = re.compile(
    r"^(Quebec|France|Belgium|Louisiana|Canada|North-America|Mexico|"
    r"El-Salvador|Argentina|Spain|Cuba|Colombia|Chile|Peru|Puerto-Rico)$"
)


def _is_region_tag(s: str) -> bool:
    return bool(_REGION_RE.match(s))


def _first_example_with_english(sense: dict) -> dict:
    """Pick the first Wiktionary example that has an English translation."""
    for ex in sense.get("examples", []):
        eng = (ex.get("english") or "").strip()
        target = (ex.get("text") or "").strip()
        if eng and target:
            return {"target": target, "english": eng}
    return None


def _append_redirect(redirects: dict, word: str, base: str) -> None:
    """Store form-of redirects as an ordered deduped list per word.

    A Wiktionary form like `suis` is the 1st-person of both `être` and
    `suivre`. The old behaviour (``redirects[word] = base``) silently kept
    only whichever Kaikki emitted last, which meant the menu lost `être`'s
    "to be" senses for `suis`. Keeping a list lets ``follow_redirects``
    collect from every base while preserving insertion order.
    """
    existing = redirects.get(word)
    if existing is None:
        redirects[word] = base
        return
    if isinstance(existing, str):
        if existing == base:
            return
        redirects[word] = [existing, base]
        return
    # list
    if base in existing:
        return
    existing.append(base)


def _iter_redirect_targets(value):
    """Yield redirect targets whether the stored value is a string or list."""
    if value is None:
        return
    if isinstance(value, str):
        yield value
    else:
        for v in value:
            if v:
                yield v

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
    # "plural of œil, eyes" → eyes  (French morphology uses comma here)
    # Constrained to lowercase head-word + a short trailing phrase to avoid
    # swallowing grammatical descriptions like "first-person singular of ...".
    re.compile(r'\bof\s+[\w\u00c0-\u024f]{1,20}?,\s*([a-z\u00c0-\u024f][\w\s,\u00c0-\u024f\'-]{1,60})$'),
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
            try:
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                # Cache format: (schema_version, index, redirects). Older pickles
                # used (index, redirects); we fall through to rebuild on mismatch.
                if (isinstance(data, tuple) and len(data) == 3
                        and data[0] == CACHE_SCHEMA_VERSION):
                    print(f"Loading Wiktionary from cache ({cache_path.name})...")
                    print(f"  {len(data[1])} unique lookup keys, {len(data[2])} form-of redirects")
                    return data[1], data[2]
                print(f"  Cache schema mismatch ({cache_path.name}) — rebuilding")
            except (EOFError, pickle.UnpicklingError, ValueError) as exc:
                print(f"  Cache unreadable ({exc}) — rebuilding")

    print(f"Loading Wiktionary from {path}...")
    index = defaultdict(list)
    redirects = {}  # form-of word → base lemma (e.g. amiga → amigo)
    reflexive_formofs = []  # (word, base) for reflexive form-of entries
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
                raw_tags = set(tags)  # original, for context extraction

                glosses = s.get("glosses", [])
                if not glosses:
                    continue
                gloss = glosses[0]
                raw_glosses_list = s.get("raw_glosses", []) or []
                raw_gloss = raw_glosses_list[0] if raw_glosses_list else gloss

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
                    elif "contraction" in tags:
                        # alt-of contractions (n'est, s'il, qu'il) carry structural
                        # info in the gloss itself ("contraction of ne + est (…)").
                        # Keep the gloss verbatim — clean_translation will trim it —
                        # so these apostrophized phrase-cards aren't sense-menu-empty.
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

                # Allow single-char glosses ("I", "y", "à"). Kaikki occasionally
                # emits empty glosses for stubs; those we do skip.
                if not gloss:
                    continue

                topics = list(s.get("topics", []) or [])
                qualifier = (s.get("qualifier") or "").strip()
                example = _first_example_with_english(s)

                # Register = semantic tags only. form-of is a morphology marker,
                # not a learner-facing register, so strip it too.
                register = sorted(
                    t for t in tags
                    if t not in INFLECTION_TAGS and t != "form-of"
                )

                # Context: peel the leading parenthetical off raw_gloss, minus
                # whatever tags/topics already cover. Fall back to qualifier
                # (Kaikki's free-text modifier) or the first topic.
                context = _context_from_raw_gloss(raw_gloss, raw_tags, topics)
                if not context and qualifier:
                    context = qualifier
                if not context and topics:
                    context = topics[0]

                sense_out = {
                    "gloss": gloss,
                    "tags": sorted(tags - {"form-of"}) if tags else [],
                }
                if context:
                    sense_out["context"] = context
                if register:
                    sense_out["register"] = register
                if example:
                    sense_out["example"] = example
                real_senses.append(sense_out)

            if not real_senses:
                # Build redirect for form-of entries: amiga → amigo, peor → malo
                for s in senses:
                    for fo in s.get("form_of", []):
                        base = fo.get("word", "").lower()
                        # Multi-clitic forms have descriptive text in form_of
                        # e.g. "hacer combined with indirect object te and lo"
                        # The links field always has the clean base verb at [0]
                        if " " in base:
                            links = s.get("links", [])
                            if links and isinstance(links[0], list):
                                base = links[0][0].lower()
                            else:
                                continue
                        if base and base != word:
                            # Multi-base support: Kaikki emits separate entries
                            # for form-of ambiguity (suis → être / suivre), and
                            # we want to collect senses from BOTH bases rather
                            # than silently picking whichever Kaikki lists last.
                            _append_redirect(redirects, word, base)
                            norm = strip_accents(word)
                            if norm != word:
                                _append_redirect(redirects, norm, base)
                            # Track reflexive form-of for post-processing
                            stags = set(s.get("tags", []))
                            links = s.get("links", [])
                            clitics = [l[0].lower() for l in links[1:]
                                       ] if len(links) > 1 else []
                            if "reflexive" in stags or "se" in clitics:
                                reflexive_formofs.append((word, base))
                skipped += 1
                continue

            entry = {"pos": mapped_pos, "senses": real_senses}
            index[word].append(entry)
            # Also index by accent-stripped form for fallback lookups
            norm = strip_accents(word)
            if norm != word:
                index[norm].append(entry)

    # Post-process: create real index entries for reflexive form-of words
    # whose base verb has reflexive-tagged senses (tier 3).
    # e.g. irse gets only ir's reflexive senses, not all 31.
    refl_created = 0
    for refl_word, base_verb in reflexive_formofs:
        base_entries = index.get(base_verb, [])
        if not base_entries:
            continue
        refl_senses = []
        pos = None
        for be in base_entries:
            for sense in be["senses"]:
                stags = set(sense.get("tags", []))
                if "reflexive" in stags or "pronominal" in stags:
                    refl_senses.append(sense)
                    if pos is None:
                        pos = be["pos"]
        if refl_senses:
            # Promote to real index entry with only reflexive senses.
            # _reflexive_of marker tells lookup_senses to skip the lemma
            # group (otherwise irse|ir would get all 31 ir senses too).
            refl_entry = {"pos": pos, "senses": refl_senses,
                          "_reflexive_of": base_verb}
            index[refl_word].append(refl_entry)
            norm = strip_accents(refl_word)
            if norm != refl_word:
                index[norm].append(refl_entry)
            redirects.pop(refl_word, None)
            redirects.pop(strip_accents(refl_word), None)
            refl_created += 1

    print(f"  {total} total entries, {skipped} skipped (no real senses)")
    print(f"  {len(index)} unique lookup keys, {len(redirects)} form-of redirects")
    print(f"  {len(reflexive_formofs)} reflexive form-of entries, {refl_created} promoted to own senses")
    result = dict(index), dict(redirects)

    if use_cache:
        import pickle
        print(f"  Caching to {cache_path.name}...")
        with open(cache_path, "wb") as f:
            pickle.dump((CACHE_SCHEMA_VERSION, result[0], result[1]), f)

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

    def follow_redirects(forms, redirects, index, max_hops=5):
        """Expand a list of lookup forms by following redirect chains.

        Follows form-of redirects up to max_hops until an indexed entry is
        found or the chain dead-ends. Avoids cycles. Supports multi-base
        redirects: a form like `suis` can fan out to both `être` and
        `suivre` — we enqueue all of them and chase each.
        """
        seen = set(forms)
        queue = list(forms)
        for f in queue:
            for target in _iter_redirect_targets(redirects.get(f)):
                if target in seen:
                    continue
                seen.add(target)
                queue.append(target)
                # Follow chain from this particular target
                current = target
                for _ in range(max_hops - 1):
                    if current in index:
                        break  # reached an indexed entry, stop this chain
                    next_targets = list(_iter_redirect_targets(redirects.get(current)))
                    if not next_targets:
                        break
                    # Pick the first unseen hop; if all seen, we're done.
                    nxt = next((t for t in next_targets if t not in seen), None)
                    if not nxt:
                        break
                    seen.add(nxt)
                    queue.append(nxt)
                    current = nxt
        return queue

    # Build groups of forms: primary (lemma), secondary (word if different)
    # We merge results from all matching groups
    groups = []
    # Group 1: lemma and its variants
    lemma_forms = [lemma.lower(), strip_accents(lemma.lower())]
    lemma_forms = follow_redirects(lemma_forms, redirects, wikt_index)
    groups.append(lemma_forms)
    # Group 2: word form and its variants (if different from lemma)
    word_has_own_entry = False
    if word.lower() != lemma.lower():
        word_forms = [word.lower(), strip_accents(word.lower())]
        word_forms = follow_redirects(word_forms, redirects, wikt_index)
        groups.append(word_forms)
        # Check if word has a _reflexive_of entry (tier 3 reflexive verb).
        # If so, use ONLY the word's senses — don't mix in the base verb's
        # full sense list from the lemma group.
        word_entries = wikt_index.get(word.lower(), [])
        if any(e.get("_reflexive_of") for e in word_entries):
            word_has_own_entry = True

    # Collect candidates from all groups. We deliberately do NOT stop at the
    # first form-with-entries within a group: French bare forms like `est`
    # have adj/noun entries (east) AND a form-of redirect to `être`, and we
    # want the verb senses merged in rather than masked by the bare entry.
    all_candidates = []
    for i, group in enumerate(groups):
        # Skip lemma group (i=0) if word has reflexive-of entry
        if word_has_own_entry and i == 0:
            continue
        for form in group:
            candidates = wikt_index.get(form)
            if candidates:
                all_candidates.extend(candidates)

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

            result = {
                "pos": pos,
                "translation": gloss,
                "source": "wiktionary",
            }
            if sense.get("context"):
                result["context"] = sense["context"]
            if sense.get("register"):
                result["register"] = list(sense["register"])
            if sense.get("example"):
                result["example"] = dict(sense["example"])
            results.append(result)
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
def _load_artist_excluded_words(artist_dir: Path, include_clitics: bool = False):
    """Read an artist's word_routing.json and return the set of words to skip.

    Matches the behaviour of the old artist/tool_5c_build_spanishdict_menu.py:
    skip the four exclude buckets and (by default) clitic_merge targets.
    """
    routing_path = artist_dir / "data" / "known_vocab" / "word_routing.json"
    routing = load_json(routing_path, {})
    exclude = routing.get("exclude", {}) if isinstance(routing, dict) else {}
    skipped = set()
    for category in ("english", "proper_nouns", "interjections", "low_frequency"):
        values = exclude.get(category, [])
        if isinstance(values, list):
            skipped.update(v for v in values if isinstance(v, str))
    if not include_clitics:
        clitic_merge = routing.get("clitic_merge", {})
        if isinstance(clitic_merge, dict):
            skipped.update(clitic_merge.keys())
    return skipped


def _artist_cache_state(artist_dir: Path):
    status = load_json(SPANISHDICT_STATUS, {"artists": {}})
    artist_key = str(Path(artist_dir).resolve())
    return (status.get("artists") or {}).get(artist_key) or {}


def build_spanishdict_menu(
    vocab,
    output_file,
    existing_menu=None,
    excluded_words=None,
    word_filter=None,
    max_words=None,
    force=False,
    include_redirects=True,
):
    """Build sense menu from SpanishDict shared caches.

    Normal-mode default: full rebuild from the inventory.
    Artist mode: pass `existing_menu` (incremental merge), `excluded_words` (skip
    routing exclusions), `word_filter` (subset by --word), `max_words`, and
    `force` (overwrite already-built words).
    """
    surface_cache = load_json(SPANISHDICT_SURFACE_CACHE, {})
    headword_cache = load_json(SPANISHDICT_HEADWORD_CACHE, {})
    print(f"  SpanishDict surface cache: {len(surface_cache)} entries")
    print(f"  SpanishDict headword cache: {len(headword_cache)} entries")

    if not surface_cache:
        print("ERROR: SpanishDict surface cache is empty or missing.")
        print(f"  Expected at: {SPANISHDICT_SURFACE_CACHE}")
        sys.exit(1)

    output = dict(existing_menu) if existing_menu else {}
    excluded_words = excluded_words or set()
    word_filter = set(word_filter) if word_filter else None

    eligible = []
    skipped_excluded = 0
    skipped_existing = 0
    skipped_uncached = 0
    for entry in vocab:
        word = (entry.get("word") or "").strip()
        if not word:
            continue
        if word_filter is not None and word not in word_filter:
            continue
        if word in excluded_words:
            skipped_excluded += 1
            continue
        if not force and word in output:
            skipped_existing += 1
            continue
        if word not in surface_cache:
            skipped_uncached += 1
            continue
        eligible.append(word)
    if max_words is not None:
        eligible = eligible[:max_words]

    matched = 0
    unmatched = 0
    total_senses = 0
    multi_analysis = 0
    for word in eligible:
        analyses = build_menu_analyses(
            word, surface_cache, headword_cache,
            include_redirects=include_redirects,
        )
        if not analyses:
            unmatched += 1
            continue
        _, _, normalized = flatten_analyses_with_ids(analyses)
        output[word] = normalized
        matched += 1
        total_senses += sum(len(a.get("senses", {})) for a in normalized)
        if len(normalized) >= 2:
            multi_analysis += 1

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    write_sidecar(output_file, make_meta("build_senses", STEP_VERSION, extra={"source": "spanishdict"}))

    # Report
    total = len(vocab)
    print(f"\n{'='*55}")
    print("SPANISHDICT SENSE MENU RESULTS")
    print(f"{'='*55}")
    print(f"Total vocabulary:    {total:>6}")
    print(f"Processed:           {len(eligible):>6}")
    print(f"Matched:             {matched:>6}")
    print(f"Unmatched:           {unmatched:>6}")
    if skipped_excluded:
        print(f"Skipped (excluded):  {skipped_excluded:>6}")
    if skipped_existing:
        print(f"Skipped (existing):  {skipped_existing:>6}")
    if skipped_uncached:
        print(f"Skipped (uncached):  {skipped_uncached:>6}")
    print(f"With 2+ analyses:    {multi_analysis:>6}  (homographs)")
    print(f"Total senses added:  {total_senses:>6}")
    print(f"Total menu entries:  {len(output):>6}")
    print()

    # Sample output
    print("Sample entries:")
    sample_words = ["banco", "tomar", "hacer", "tiempo", "como", "de"]
    for word in sample_words:
        if word in output:
            analyses = output[word]
            n = sum(len(a.get("senses", {})) for a in analyses)
            print(f"\n  {word} ({n} senses, {len(analyses)} analyses):")
            for a in analyses:
                print(f"    [{a.get('headword', '?')}]")
                for sid, s in (a.get("senses", {})).items():
                    print(f"      {s.get('pos', '?'):>8}  {s.get('translation', '')}")


def main():
    import argparse
    global INVENTORY_FILE, WIKT_FILE, CONJ_REVERSE_FILE, CONJ_FILE, LAYERS_DIR

    parser = argparse.ArgumentParser(description="Build sense menu from Wiktionary or SpanishDict")
    parser.add_argument("--sense-source", choices=("wiktionary", "spanishdict"),
                        default="spanishdict",
                        help="Sense dictionary source (default: spanishdict)")
    parser.add_argument("--language", choices=tuple(_LANGUAGE_PATHS.keys()),
                        default="spanish",
                        help="Target language; selects kaikki file + layer paths "
                             "(default: spanish). SpanishDict source is Spanish-only.")
    parser.add_argument("--wiktionary-file", default=None,
                        help="Override the kaikki JSONL path (default: per-language).")
    parser.add_argument("--artist-dir", default=None,
                        help="Build menu for an artist. spanishdict: reads artist inventory "
                             "and writes to artist layers. wiktionary: reads artist inventory, "
                             "writes to artist layers (normal-mode wiktionary flow w/ swapped paths). "
                             "Omit for normal-mode Data/{Lang}/layers.")
    # Artist-flow flags (no-ops in normal mode)
    parser.add_argument("--force", action="store_true",
                        help="Rebuild entries already present in the menu")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process a specific surface word (repeatable)")
    parser.add_argument("--max-words", type=int, default=None,
                        help="Only process the first N eligible words")
    parser.add_argument("--include-excluded", action="store_true",
                        help="Artist mode: include step-4 excluded words instead of skipping")
    parser.add_argument("--include-clitics", action="store_true",
                        help="Artist mode: include clitic_merge words (skipped by default)")
    parser.add_argument("--no-redirects", action="store_true",
                        help="Only use the direct surface-page dictionary analyses")
    parser.add_argument("--allow-incomplete-cache", action="store_true",
                        help="Artist mode: allow building from a partial shared cache")
    args = parser.parse_args()

    # ---------------------------------------------------------------
    # Resolve paths based on --language / --artist-dir / explicit overrides.
    # Everything downstream reads the module-level constants, so we rebind
    # them here (global) before any work happens. The normal-mode wiktionary
    # flow then Just Works™ with whatever language we pointed it at.
    # ---------------------------------------------------------------
    lang_paths = _LANGUAGE_PATHS[args.language]
    WIKT_FILE = Path(args.wiktionary_file) if args.wiktionary_file else lang_paths["wiktionary"]
    CONJ_REVERSE_FILE = lang_paths["conj_reverse"]
    CONJ_FILE = lang_paths["conj"]
    # Normal-mode inventory + layers defaults; artist mode overrides below.
    INVENTORY_FILE = lang_paths["inventory"]
    LAYERS_DIR = lang_paths["layers"]

    # Artist mode + wiktionary: rebind INVENTORY_FILE / LAYERS_DIR to the
    # artist's layer dir, then fall through to the normal wiktionary flow.
    # (SpanishDict artist mode is handled in its own dedicated branch below.)
    if args.artist_dir and args.sense_source == "wiktionary":
        artist_dir = Path(args.artist_dir).resolve()
        INVENTORY_FILE = artist_dir / "data" / "layers" / "word_inventory.json"
        LAYERS_DIR = artist_dir / "data" / "layers"
        print(f"Artist-mode Wiktionary build ({args.language}):")
        print(f"  inventory: {INVENTORY_FILE}")
        print(f"  wiktionary: {WIKT_FILE}")
        print(f"  output dir: {LAYERS_DIR}")
        # Clear artist_dir so the spanishdict artist branch below doesn't fire.
        args.artist_dir = None

    # Artist-mode SpanishDict branch
    if args.artist_dir:
        if args.sense_source != "spanishdict":
            print("ERROR: --artist-dir is only supported with --sense-source spanishdict or wiktionary.")
            sys.exit(2)

        artist_dir = Path(args.artist_dir).resolve()
        inventory_path = artist_dir / "data" / "layers" / "word_inventory.json"
        layers_dir = artist_dir / "data" / "layers"
        output_file = Path(sense_menu_path(layers_dir, "spanishdict"))

        print("Loading artist word inventory...")
        vocab = load_json(inventory_path, [])
        print(f"  {len(vocab)} entries ({inventory_path})")

        excluded = set() if args.include_excluded else _load_artist_excluded_words(
            artist_dir, include_clitics=args.include_clitics,
        )
        existing = normalize_artist_sense_menu(load_json(output_file, {}))

        is_full_build = not args.word and args.max_words is None
        if is_full_build and not args.allow_incomplete_cache:
            cache_state = _artist_cache_state(artist_dir)
            if cache_state.get("status") != "complete":
                print("ERROR: SpanishDict cache is not complete for this artist.")
                print("Run the shared cache phase first, e.g.:")
                print(f"  .venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py "
                      f"--artist-dir \"{artist_dir}\"")
                sys.exit(1)

        print("\nBuilding SpanishDict sense menu (artist mode)...")
        build_spanishdict_menu(
            vocab,
            output_file,
            existing_menu=existing,
            excluded_words=excluded,
            word_filter=args.word or None,
            max_words=args.max_words,
            force=args.force,
            include_redirects=not args.no_redirects,
        )
        return

    # Load normal-mode word inventory
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        vocab = json.load(f)
    print(f"  {len(vocab)} entries")

    if args.sense_source == "spanishdict":
        print("\nBuilding sense menu from SpanishDict...")
        output_file = sense_menu_path(LAYERS_DIR, "spanishdict")
        build_spanishdict_menu(
            vocab, output_file,
            force=args.force,
            word_filter=args.word or None,
            max_words=args.max_words,
            include_redirects=not args.no_redirects,
        )
        return

    if not WIKT_FILE.exists():
        print(f"ERROR: Wiktionary file not found: {WIKT_FILE}")
        # Generic hint based on the file we were trying to load.
        lang_title = args.language.capitalize()
        print("Download it with:")
        print(f'  curl -L -o "{WIKT_FILE}" \\')
        print(f'    "https://kaikki.org/dictionary/{lang_title}/kaikki.org-dictionary-{lang_title}.jsonl.gz"')
        sys.exit(1)

    # Load Wiktionary
    wikt_index, redirects = load_wiktionary(WIKT_FILE)

    # Load conjugation data (optional — generated by step_5b_build_conjugations.py)
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
        print("  (run step_5b_build_conjugations.py first to enable)")

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

    # Look up senses for each surface word, grouped by analysis (lemma)
    print("\nLooking up senses (with cleaning + merging)...")
    output = {}
    stats = {
        "matched": 0,
        "unmatched": 0,
        "multi_sense": 0,
        "multi_analysis": 0,
        "sense_counts": defaultdict(int),
        "total_raw": 0,
        "total_after_clean": 0,
        "total_final": 0,
        "verb_filtered": 0,
        "jehle_fallback": 0,
        "descriptive_filtered": 0,
    }
    unmatched_words = []

    def clean_sense_list(senses, word, lemma):
        """Run the full cleaning pipeline on a raw sense list for one lemma."""
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
            senses = senses_before_filter[:1]
        stats["descriptive_filtered"] += before_desc - len(senses)

        # Step 2: Exact dedup
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

        # Step 4: Deprioritize letter-name NOUN senses
        senses = _deprioritize_letter_senses(senses)

        # Step 5: Conjugation-based POS filtering (per-lemma)
        if conj_reverse:
            word_lower = word.lower()
            reverse_entries = conj_reverse.get(word_lower, [])
            is_confirmed_verb = any(
                e["lemma"] == lemma.lower() for e in reverse_entries
            )
            if not is_confirmed_verb and word_lower == lemma.lower():
                is_confirmed_verb = word_lower in conj_known_verbs

            if is_confirmed_verb:
                verb_senses = [s for s in senses if s["pos"] == "VERB"]
                if verb_senses:
                    non_verb_count = len(senses) - len(verb_senses)
                    if non_verb_count > 0:
                        stats["verb_filtered"] += 1
                    senses = verb_senses

        # Step 6: Cross-POS dedup
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

        return senses

    for entry in vocab:
        word = entry["word"]
        known_lemmas = entry.get("known_lemmas", [word])

        # Build analyses: one per known lemma
        analyses = []
        used_ids = set()
        word_matched = False

        for lemma in known_lemmas:
            senses = lookup_senses(word, lemma, wikt_index, redirects)

            if not senses:
                # Jehle translation fallback for verb lemmas
                if conj_translations:
                    lemma_lower = lemma.lower()
                    if lemma_lower in conj_translations:
                        senses = [{"pos": "VERB", "translation": conj_translations[lemma_lower], "source": "jehle"}]
                        stats["jehle_fallback"] += 1

            if not senses:
                continue

            senses = clean_sense_list(senses, word, lemma)
            if not senses:
                continue

            # Assign stable sense IDs for this analysis
            id_map = assign_analysis_sense_ids(lemma, senses, used_ids=used_ids)
            used_ids.update(id_map.keys())
            analyses.append({"headword": lemma, "senses": id_map})
            word_matched = True

        if analyses:
            output[word] = analyses
            stats["matched"] += 1
            total_senses = sum(len(a["senses"]) for a in analyses)
            stats["total_final"] += total_senses
            if total_senses >= 2:
                stats["multi_sense"] += 1
            if len(analyses) >= 2:
                stats["multi_analysis"] += 1
            stats["sense_counts"][min(total_senses, 6)] += 1
        else:
            stats["unmatched"] += 1
            unmatched_words.append(word)

    # Write output
    output_file = sense_menu_path(LAYERS_DIR, args.sense_source)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    write_sidecar(output_file, make_meta("build_senses", STEP_VERSION, extra={"source": args.sense_source}))

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
    print(f"With 2+ analyses:    {stats['multi_analysis']:>6}  (homographs)")
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
    sample_words = ["banco", "tomar", "pasar", "poder", "rico", "muñeca",
                    "hacer", "tiempo", "mejor", "bien", "de", "está", "como"]
    for word in sample_words:
        if word in output:
            analyses = output[word]
            total_n = sum(len(a["senses"]) for a in analyses)
            print(f"\n  {word} ({total_n} senses, {len(analyses)} analyses):")
            for a in analyses:
                print(f"    [{a['headword']}]")
                for sid, s in a["senses"].items():
                    print(f"      {s['pos']:>8}  {s['translation']}")


if __name__ == "__main__":
    main()
