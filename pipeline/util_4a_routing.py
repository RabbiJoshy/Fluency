"""Shared routing helpers for step_4a (normal + artist modes).

Provides:
  - Clitic pronoun stripping + gerund decomposition
  - Wiktionary clitic-data loader
  - Three-tier clitic classification (clitic_merge / clitic_keep)
  - Morphological derivation resolver (diminutive / superlative)
"""

import gzip
import json
import os
import unicodedata


# ---------------------------------------------------------------------------
# Clitic pronouns
# ---------------------------------------------------------------------------

# Longest first to avoid partial matches.
_CLITIC_PRONOUNS = ("nos", "les", "los", "las", "me", "te", "se", "lo", "la", "le")


def _strip_acute(s):
    """Strip acute accents only (á→a), preserving ñ and ü."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if c != "\u0301")


def strip_clitic_pronouns(word, clitic_list=None):
    """Strip clitic pronouns from end of word and return accentless base form.

    If `clitic_list` is given (from Wiktionary links), strip those specific
    pronouns in reverse order. Otherwise try all `_CLITIC_PRONOUNS` (up to 2
    iterations).
    """
    remaining = word.lower()
    if clitic_list:
        for cl in reversed(clitic_list):
            if remaining.endswith(cl) and len(remaining) > len(cl):
                remaining = remaining[:-len(cl)]
    else:
        for _ in range(2):
            for cl in _CLITIC_PRONOUNS:
                if remaining.endswith(cl) and len(remaining) > len(cl):
                    remaining = remaining[:-len(cl)]
                    break
    return _strip_acute(remaining)


def decompose_gerund_clitic(word, known_words):
    """Decompose a gerund+clitic form into base infinitive.

    Returns (base_infinitive, is_reflexive) if decomposable, else None.
    E.g., 'dándote' → ('dar', False), 'ahogándome' → ('ahogar', False).
    """
    wl = word.lower()
    remaining = wl
    clitics = []
    for _ in range(2):  # max 2 clitics (e.g. haciéndomelo)
        matched = False
        for pron in _CLITIC_PRONOUNS:
            if remaining.endswith(pron) and len(remaining) > len(pron) + 4:
                remaining = remaining[:-len(pron)]
                clitics.insert(0, pron)
                matched = True
                break
        if not matched:
            break

    if not clitics:
        return None

    clean = _strip_acute(remaining)
    if clean.endswith("ando"):
        infinitive = clean[:-4] + "ar"
    elif clean.endswith("iendo"):
        infinitive = clean[:-5] + "ir"
    elif clean.endswith("endo"):
        infinitive = clean[:-4] + "er"
    else:
        return None

    if infinitive in known_words:
        return (infinitive, "se" in clitics)
    return None


# ---------------------------------------------------------------------------
# Wiktionary clitic-data loader
# ---------------------------------------------------------------------------

def load_wiktionary_clitic_data(path):
    """Load clitic map + reflexive verbs + propn set from Wiktionary JSONL.

    Returns (word_set, all_propn, clitic_map, verbs_with_refl_senses):
      word_set: all lowercase word forms that have any entry.
      all_propn: words where EVERY entry has pos="name" (proper nouns).
      clitic_map: {clitic_word: (base_verb, [clitics], is_reflexive)} for
                  form-of entries with clitic pronouns ("combined with").
      verbs_with_refl_senses: base verbs with non-form-of senses tagged
                              'reflexive' or 'pronominal'.
    """
    from collections import defaultdict
    word_poses = defaultdict(set)
    clitic_map = {}
    verbs_with_refl = set()
    if not os.path.exists(path):
        return set(), set(), {}, set()

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            w = entry.get("word", "")
            if not w:
                continue
            wl = w.lower()
            raw_pos = entry.get("pos", "")
            word_poses[wl].add(raw_pos)
            for s in entry.get("senses", []):
                tags = set(s.get("tags", []))
                if raw_pos == "verb" and "form-of" not in tags:
                    if "reflexive" in tags or "pronominal" in tags:
                        verbs_with_refl.add(wl)
                if "form-of" in tags:
                    gloss = (s.get("glosses") or [""])[0]
                    if "combined with" in gloss:
                        links = s.get("links", [])
                        if links and isinstance(links[0], list):
                            base = links[0][0].lower()
                            clitics = [l[0].lower() for l in links[1:]
                                       if isinstance(l, list)]
                            is_refl = "reflexive" in tags or "se" in clitics
                            if base and base != wl:
                                clitic_map[wl] = (base, clitics, is_refl)

    words = set(word_poses.keys())
    all_propn = {w for w, poses in word_poses.items()
                 if poses and poses <= {"name"}}
    return words, all_propn, clitic_map, verbs_with_refl


# ---------------------------------------------------------------------------
# Three-tier clitic classification
# ---------------------------------------------------------------------------

def classify_clitics(words, clitic_map, verbs_with_refl, known_for_gerund):
    """Build clitic_merge / clitic_orphans / clitic_keep for `words`.

    Args:
        words: set of lowercase surface forms to classify.
        clitic_map: from `load_wiktionary_clitic_data`.
        verbs_with_refl: from `load_wiktionary_clitic_data`.
        known_for_gerund: set of known Spanish forms used to validate
                          gerund-decomposition candidates (usually
                          `words | conj_forms | wikt_words`).

    Returns (clitic_merge, clitic_orphans, clitic_keep, gerund_added):
      clitic_merge: {word: base_form}  (tier 1+2)
      clitic_orphans: [word]  (subset of clitic_merge mapped to a synthetic infinitive)
      clitic_keep: set[word]  (tier 3)
      gerund_added: int (count of programmatic gerund+clitic detections)
    """
    clitic_merge = {}
    clitic_orphans = []
    clitic_keep = set()

    # Wiktionary-listed clitic forms (tier 1/2/3)
    for w in words:
        if w not in clitic_map:
            continue
        base_inf, clitics, is_refl = clitic_map[w]
        if is_refl and base_inf in verbs_with_refl:
            clitic_keep.add(w)
            continue
        stripped = strip_clitic_pronouns(w, clitics)
        if stripped in words:
            clitic_merge[w] = stripped
        else:
            clitic_merge[w] = base_inf
            clitic_orphans.append(w)

    # Programmatic gerund+clitic detection (catches forms not in Wiktionary)
    gerund_added = 0
    for w in words:
        if w in clitic_merge or w in clitic_keep:
            continue
        result = decompose_gerund_clitic(w, known_for_gerund)
        if not result:
            continue
        base_inf, is_refl = result
        if is_refl and base_inf in verbs_with_refl:
            clitic_keep.add(w)
        else:
            stripped = strip_clitic_pronouns(w)
            if stripped in words:
                clitic_merge[w] = stripped
            else:
                clitic_merge[w] = base_inf
                clitic_orphans.append(w)
        gerund_added += 1

    return clitic_merge, clitic_orphans, clitic_keep, gerund_added


# ---------------------------------------------------------------------------
# Morphological derivation (diminutive / superlative)
# ---------------------------------------------------------------------------

# (suffix, min_stem_length, replacement_endings). Longer suffixes first.
_DERIVATION_RULES = [
    # Superlatives
    ("ísimos", 3, ("os", "o")),
    ("ísimas", 3, ("as", "a")),
    ("ísimo", 3, ("o", "")),
    ("ísima", 3, ("a", "")),
    # Diminutives: -ecito family (monosyllabic/short bases)
    ("ecitos", 2, ("es", "s", "")),
    ("ecitas", 2, ("as", "es", "")),
    ("ecito", 2, ("e", "", "o")),
    ("ecita", 2, ("a", "e", "")),
    # Diminutives: -cito family (bases ending in consonant)
    ("citos", 3, ("es", "s", "")),
    ("citas", 3, ("as", "s", "")),
    ("cito", 3, ("", "e", "n")),
    ("cita", 3, ("a", "", "e")),
    # Diminutives: -ito/-ita
    ("itos", 3, ("os", "es", "s", "")),
    ("itas", 3, ("as", "es", "s", "")),
    ("ito", 3, ("o", "e", "")),
    ("ita", 3, ("a", "e", "")),
    # Diminutives: -illo/-illa
    ("illos", 3, ("os", "es")),
    ("illas", 3, ("as", "es")),
    ("illo", 3, ("o", "e", "")),
    ("illa", 3, ("a", "e", "")),
]


def resolve_derivation(word, known_words):
    """Resolve a Spanish diminutive/superlative to its base form.

    Returns the base form if found in known_words, else None. Handles
    orthographic alternations (qu→c, gu→g) and accents.
    """
    wl = word.lower()
    for suffix, min_stem, endings in _DERIVATION_RULES:
        if not wl.endswith(suffix):
            continue
        stem = wl[:-len(suffix)]
        if len(stem) < min_stem:
            continue
        for ending in endings:
            bare = stem + ending
            stripped = _strip_acute(stem) + ending
            candidates = {bare, stripped}
            # qu → c before back vowels (chiquito → chico)
            if stem.endswith("qu") and ending and ending[0] in "oa":
                candidates.add(stem[:-2] + "c" + ending)
                candidates.add(_strip_acute(stem[:-2]) + "c" + ending)
            # gu → g before back vowels (amiguita → amiga)
            if stem.endswith("gu") and ending and ending[0] in "oa":
                candidates.add(stem[:-2] + "g" + ending)
                candidates.add(_strip_acute(stem[:-2]) + "g" + ending)
            for c in candidates:
                if c in known_words:
                    return c
    return None
