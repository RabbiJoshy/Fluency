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
    """Decompose a gerund+clitic or infinitive+clitic form into its infinitive.

    Returns (base_infinitive, is_reflexive) if decomposable, else None.
    E.g., 'dándote' → ('dar', False), 'ahogándome' → ('ahogar', False),
    'alejarte' → ('alejar', False), 'dármelo' → ('dar', False).

    Infinitive+enclitic needs no ending surgery — the enclitic is simply
    appended ('alejar' + 'te') — but a two-clitic stack takes a written
    accent ('dármelo'), which `_strip_acute` removes before the -ar/-er/-ir
    test. The infinitive must exist in `known_words`, which is what keeps
    accidental -te/-le nouns ('combate', 'animales') out.
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
        # The gerund stripper needs a 5+ char stem; short infinitives
        # ('verlo', 'darte') never get past it, so hand them straight over.
        return decompose_infinitive_clitic(word, known_words)

    clean = _strip_acute(remaining)
    if clean.endswith("ando"):
        infinitive = clean[:-4] + "ar"
    elif clean.endswith("iendo"):
        infinitive = clean[:-5] + "ir"
    elif clean.endswith("endo"):
        infinitive = clean[:-4] + "er"
    else:
        return decompose_infinitive_clitic(word, known_words)

    if infinitive in known_words:
        return (infinitive, "se" in clitics)
    return decompose_infinitive_clitic(word, known_words)


# Infinitives short enough to fall under `_MIN_INFINITIVE_LEN`. Without this
# list, `darme`/`verlo` would be dropped; with a length floor alone, nouns
# like `parte` would be mis-split into `par` + `te`.
_SHORT_INFINITIVES = frozenset({"ir", "dar", "ver", "ser", "oir"})
_MIN_INFINITIVE_LEN = 4

# Verb evidence for the infinitive branch.
#
# `known_words` is the union of every known Spanish *surface form*, so mere
# membership proves nothing about verbhood: stripping "nos" off `cuernos`
# leaves `cuer` and "te" off `fuerte` leaves `fuer`, both of which are real
# surface entries ending in -er, and both were merged as infinitives. The
# candidate must instead be a verb in its own right — either a lemma with a
# conjugation table, or tagged unambiguously as a verb by spanish_forms
# (`fuer` is "noun,verb", so requiring an exact "verb" tag rejects it).
#
# Fails CLOSED: if neither source can be read the infinitive branch simply
# does not fire, restoring the pre-existing gerund-only behaviour rather than
# admitting the false positives this guard exists to stop.
_verb_lemmas = None          # set of infinitives with a conjugation table
_verb_pos = None             # {form: pos-string} from spanish_forms
_verb_data_loaded = False


def _load_verb_evidence(conjugations_path=None, spanish_forms_path=None):
    """Lazily load the verb lookups the infinitive guard needs (once)."""
    global _verb_lemmas, _verb_pos, _verb_data_loaded
    if _verb_data_loaded:
        return
    _verb_data_loaded = True
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    layers = os.path.join(root, "Data", "Spanish", "layers")
    conj = conjugations_path or os.path.join(layers, "conjugations.json")
    forms = spanish_forms_path or os.path.join(layers, "spanish_forms.json")
    try:
        with open(conj, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _verb_lemmas = {k.lower() for k in data}
    except (OSError, ValueError):
        pass
    try:
        with open(forms, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _verb_pos = data
    except (OSError, ValueError):
        pass


def _is_known_infinitive(candidate):
    """True when `candidate` has real evidence of being a verb infinitive."""
    _load_verb_evidence()
    if _verb_lemmas and candidate in _verb_lemmas:
        return True
    if _verb_pos is not None:
        # Exact match only: an ambiguous "noun,verb" tag is not evidence.
        return str(_verb_pos.get(candidate, "")).strip().lower() == "verb"
    return False


def decompose_infinitive_clitic(word, known_words):
    """Decompose an infinitive+enclitic form into its infinitive.

    Returns (base_infinitive, is_reflexive) or None. E.g. 'alejarte' →
    ('alejar', False), 'dármelo' → ('dar', False), 'ponerse' → ('poner', True).

    Unlike the gerund case there is no ending to rebuild — the enclitic is
    appended to the bare infinitive — but a two-clitic stack adds a written
    accent ('dármelo'), so accents are stripped before the -ar/-er/-ir test.
    Four guards keep noun lookalikes out: the infinitive must be in
    `known_words`, must be at least `_MIN_INFINITIVE_LEN` characters (or a
    known short infinitive), each strip must leave a real stem behind, and
    `_is_known_infinitive` must find actual verb evidence for it — surface-form
    membership alone admits `cuernos`→`cuer` and `fuerte`→`fuer`.
    """
    remaining = word.lower()
    clitics = []
    for _ in range(2):  # max 2 clitics (e.g. dármelo)
        matched = False
        for pron in _CLITIC_PRONOUNS:
            if remaining.endswith(pron) and len(remaining) - len(pron) >= 3:
                remaining = remaining[:-len(pron)]
                clitics.insert(0, pron)
                matched = True
                break
        if not matched:
            break
        candidate = _strip_acute(remaining)
        if not candidate.endswith(("ar", "er", "ir")):
            continue
        if len(candidate) < _MIN_INFINITIVE_LEN and candidate not in _SHORT_INFINITIVES:
            continue
        if candidate in known_words and _is_known_infinitive(candidate):
            return (candidate, "se" in clitics)
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
    # Diminutives: -ecito family, singular (monosyllabic/short bases)
    ("ecito", 2, ("e", "", "o")),
    ("ecita", 2, ("a", "e", "")),
    # Diminutives: -cito family (bases ending in consonant)
    # Plural diminutives list singular base endings after the plural ones: the
    # singular lemma is often the only known form (fotitos -> foto). Gender is
    # tried before the opposite gender (papitas -> papa, not papo).
    ("citos", 3, ("es", "s", "", "o", "a", "e")),
    ("citas", 3, ("as", "s", "", "a", "o", "e")),
    ("cito", 3, ("", "e", "n")),
    ("cita", 3, ("a", "", "e")),
    # Diminutives: -ecito family, plural. Ordered after -cito so that the
    # longer-stem -cito reading still wins where it resolves (bebecitas ->
    # bebe, not bebo); -ecito only fires as the fallback (nietecitos -> nieto).
    ("ecitos", 2, ("es", "s", "", "o", "a", "e")),
    ("ecitas", 2, ("as", "es", "", "a", "o", "e")),
    # Diminutives: -ito/-ita
    ("itos", 3, ("os", "es", "s", "", "o", "a", "e")),
    ("itas", 3, ("as", "es", "s", "", "a", "o", "e")),
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
