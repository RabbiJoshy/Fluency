#!/usr/bin/env python3
"""
Step 3: Normalize elision variants in vocab_evidence.json before sense assignment.

Language-aware (`--language {spanish,french}`, default `spanish`).

### Spanish (`--language spanish`, default)

Three merge families handled here (all preserve `surface` on each example so
the front-end can render the original lyric form):

1. Explicit mapping (`elision_mapping.json`): manual and auto-generated
   `elided_only` / `elision_pair` / `same_word_dup` entries.
2. D-elision regex family: Caribbean dropped-d past participles and
   derivatives in masculine/feminine × singular/plural:
       -a'o  -> -ado   (burla'o -> burlado)
       -a'a  -> -ada   (pega'a  -> pegada)
       -a'os -> -ados  (pega'os -> pegados)
       -a'as -> -adas  (moja'as -> mojadas)
       -í'o  -> -ido   (jodí'o  -> jodido)
       -í'a  -> -ida   (prendí'a-> prendida)
       -í'os -> -idos  (escondí'os-> escondidos)
       -í'as -> -idas  (mordí'as-> mordidas)
3. Trailing-apostrophe tiebreaker: for `word'` not covered above, try
   restoring a dropped final consonant (`s`, `d`, `z`, `r`, `l`, `n`) and
   merge if exactly one candidate exists in normal_vocab.

Also ambiguous: `ve'` splits per-example into `vez` (noun) vs `ves` (verb)
using the preceding-word disambiguator.

### French (`--language french`)

Splits leading apostrophe clitics that the step-2 tokenizer keeps glued to
the next word (French writes `l'amour` as one orthographic token). The
clitic is dropped; its counts and examples merge into the bare base word.
The original surface form is preserved on each example.

Handled proclitics: `l' j' d' qu' n' m' s' t' c' jusqu' puisqu' lorsqu'`
(plus their capitalized and curly-apostrophe variants).

Input:  data/word_counts/vocab_evidence.json
Output: data/elision_merge/vocab_evidence_merged.json

Usage:
  .venv/bin/python3 pipeline/artist/step_3a_merge_elisions.py --artist-dir "Artists/spanish/Bad Bunny"
  .venv/bin/python3 pipeline/artist/step_3a_merge_elisions.py --artist-dir "Artists/french/TestPlaylist" --language french
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

import argparse
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_1a_artist_config import SHARED_DIR

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import (  # noqa: E402
    dependency_metadata,
    make_meta,
    write_sidecar,
)
from pipeline.util_evidence_store import archive_json_artifact  # noqa: E402

STEP_VERSION = 12
STEP_VERSION_NOTES = {
    1: "s-elision + d-elision merge with corpus_count summing",
    2: "+ plural/feminine d-elision, double-elision chain (-ao' → -ao → -ado), trailing-apos tiebreaker",
    3: "+ --language flag, French proclitic splitter (l'/j'/d'/qu' etc.)",
    4: "french: consult Wiktionary phrase/contraction index; promote known apos "
       "forms (c'est, j'ai, qu'il, n'est, s'il, …) to own entries instead of "
       "stripping them into a verb form",
    5: "french: Tier C — split colloquial proclitic+function-word forms "
       "(m'le, qu'le, j'suis, j'me) into two words instead of dumping counts "
       "onto the tail. Counts and examples flow to both halves.",
    6: "+ union full-corpus song IDs while merging variants so song_count remains "
       "exact after elision normalization",
    7: "+ apostrophe-less d-elision (metíos → metidos), guarded so it only "
       "fires when the surface is not itself a known Spanish form",
    8: "+ extended d-elision families, each validated against spanish_forms and "
       "labelled separately (d_elision_unaccented: meti'o → metido; "
       "d_elision_u_final: acostumbra'u → acostumbrado; d_elision_diminutive: "
       "apreta'íto → apretadito; d_elision_ustem: desnu'a → desnuda). "
       "double_elision now also chains through the extended + bare rules "
       "(apretaíto' → apretadito). Trailing-apostrophe tiebreaker unchanged.",
    9: "+ archive every content-distinct normalization output as an immutable evidence run",
    10: "+ propagate ledger and corpus-profile dependency fingerprints",
    11: "+ restore apostrophe-less diminutive d-elisions when the generated "
        "inflection is absent from spanish_forms but its base adjective exists",
    12: "+ conservative internal-apostrophe restoration: accept only a unique "
        "known Spanish candidate, including k→c transcription variants",
}

# ---------------------------------------------------------------------------
# French proclitics the step-2 tokenizer glues onto the following word.
# Listed longest-first so `jusqu'` is matched before `qu'`.
# ---------------------------------------------------------------------------
FRENCH_PROCLITICS = (
    "puisqu", "lorsqu", "jusqu",
    "qu", "l", "d", "j", "n", "m", "s", "t", "c",
)
_FRENCH_APOS = "'\u2019"  # straight + curly
_FRENCH_PROCLITIC_RE = re.compile(
    r"^(" + "|".join(FRENCH_PROCLITICS) + r")[" + _FRENCH_APOS + r"](.+)$",
    re.IGNORECASE,
)

# Proclitic → standard expansion. `l'` is omitted (gender-ambiguous le/la;
# Tier B handles the content-word case correctly and the function-word case
# is vanishingly rare). `jusqu'/lorsqu'/puisqu'` expand to their bare forms
# but those are rarely followed by function-word tails in the data; we keep
# them here for completeness.
_FRENCH_PROCLITIC_EXPANSION = {
    "j": "je", "m": "me", "t": "te", "s": "se", "n": "ne",
    "d": "de", "c": "ce", "qu": "que",
    "jusqu": "jusque", "lorsqu": "lorsque", "puisqu": "puisque",
}

# French function words. When an apostrophized form's tail is one of these,
# the form is colloquial shorthand for `proclitic + function-word` rather
# than `proclitic + content-word` (e.g. `m'le` = me le, `qu'le` = que le,
# `j'suis` = je suis). Distributing counts to both halves preserves real
# data and surfaces the line on both cards.
#
# Limit to short, high-frequency function words: pronouns, articles,
# conjugated être/avoir. Keeping the set tight prevents accidental splits
# of colloquial content-word contractions (which should stay Tier B).
_FRENCH_FUNCTION_WORD_TAILS = frozenset({
    # pronouns / articles
    "je", "me", "te", "se", "le", "la", "les", "lui", "leur", "en", "y",
    "ce", "que", "qui",
    # être (to be) — present tense
    "suis", "es", "est", "sommes", "etes", "sont",
    # avoir (to have) — present tense
    "ai", "as", "a", "avons", "avez", "ont",
    # very short imperfect forms that frequently fuse
    "etais", "etait",
})


def french_strip_proclitic(word):
    """If `word` starts with a French proclitic + apostrophe, return the
    stripped tail; else None.

    Examples:
      l'amour      -> amour
      j'aime       -> aime
      qu'il        -> il
      jusqu'à      -> à
      L'Amour      -> amour (lowercased)
    """
    m = _FRENCH_PROCLITIC_RE.match(word)
    if not m:
        return None
    tail = m.group(2).lower().strip()
    # Guard: don't split if tail is empty or just an apostrophe (malformed).
    if not tail or all(ch in _FRENCH_APOS for ch in tail):
        return None
    return tail


def french_split_to_function_words(word):
    """Tier C: colloquial `proclitic + function-word` forms.

    Returns ``(expanded_proclitic, tail)`` when ``word`` looks like
    `X'Y` with Y a French function word (m'le, qu'le, j'suis, j'me,
    s'est, t'en, j'ai, …), else None.

    Caller uses the result to distribute counts to BOTH halves instead
    of dumping them on the tail via Tier B. Tail function words get
    extra evidence; the proclitic's expanded form (je/me/que/…) gets
    counted and picks up the example too. `l'` is excluded here because
    its expansion is ambiguous (le vs la) and its common content-word
    case (`l'amour`) is handled correctly by Tier B already.
    """
    m = _FRENCH_PROCLITIC_RE.match(word)
    if not m:
        return None
    proclitic = m.group(1).lower()
    tail = m.group(2).lower().strip()
    if not tail or all(ch in _FRENCH_APOS for ch in tail):
        return None
    expanded = _FRENCH_PROCLITIC_EXPANSION.get(proclitic)
    if not expanded:
        return None
    if tail not in _FRENCH_FUNCTION_WORD_TAILS:
        return None
    return expanded, tail


# ---------------------------------------------------------------------------
# French apostrophized phrase/contraction index (Wiktionary-driven tiering).
#
# Wiktionary gives dedicated entries to stable apostrophized chunks like
# `c'est` (it is), `j'ai` (I have), `qu'il`, `s'il`, `n'est`, `m'a`, …. Those
# deserve their own cards — the old "strip everything" rule was merging
# `c'est` into `est`, which is why the sense menu for a 293-count verb form
# was showing "[ADJ] east". We consult this index before stripping: if a form
# is here, it survives as its own entry; otherwise we fall through to the
# original proclitic splitter (the right call for `l'amour`, `j'aime`, …).
# ---------------------------------------------------------------------------

# POS tags we accept as "this apostrophized form is a real lexical unit".
# `contraction` covers c'est/n'est/m'a/qu'il/s'il/…; `phrase` covers j'ai,
# s'il vous plaît, je m'appelle, etc.; the function-word POS tags catch
# `d'`/`qu'` apocopic forms that Wiktionary classifies as adverb/preposition.
_FRENCH_APOS_PHRASE_POS = frozenset((
    "phrase", "contraction", "proverb",
    "adv", "prep", "intj", "conj", "pron",
))

# Cache pickle schema version for the French apos-phrase index.
_APOS_CACHE_VERSION = 1
_FRENCH_APOS_NORM_RE = re.compile(r"\u2019")


def _normalize_apos(word):
    """Normalize curly apostrophes to straight so the index keys join cleanly."""
    return _FRENCH_APOS_NORM_RE.sub("'", word.lower())


def load_french_apos_phrases(kaikki_path):
    """Scan the French kaikki dump for apostrophized phrase/contraction entries.

    Returns ``{normalized_word: (pos, cleaned_gloss_line)}``. The gloss is
    the first sense's gloss verbatim (for diagnostic printing); step_5c
    does its own proper cleaning when it builds the sense menu, so this is
    not the learner-facing text.

    Pickle-cached alongside the kaikki file so subsequent runs are instant.
    """
    import gzip
    import pickle
    cache_path = Path(str(kaikki_path) + ".apos_phrases.cache.pkl")
    if cache_path.exists() and cache_path.stat().st_mtime >= Path(kaikki_path).stat().st_mtime:
        try:
            with open(cache_path, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, tuple) and len(data) == 2 and data[0] == _APOS_CACHE_VERSION:
                return data[1]
        except (EOFError, pickle.UnpicklingError, ValueError):
            pass  # Rebuild below.

    if not os.path.exists(kaikki_path):
        print(f"  (no French kaikki file at {kaikki_path}; skipping phrase tier)")
        return {}

    print(f"  Scanning French kaikki for apostrophized phrase entries ({kaikki_path.name})...")
    index = {}
    with gzip.open(kaikki_path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            word = (item.get("word") or "").lower()
            pos = item.get("pos") or ""
            if not word or pos not in _FRENCH_APOS_PHRASE_POS:
                continue
            if "'" not in word and "\u2019" not in word:
                continue
            senses = item.get("senses") or []
            gloss = ""
            for s in senses:
                glosses = s.get("glosses") or []
                if glosses:
                    gloss = glosses[0][:120]
                    break
            key = _normalize_apos(word)
            # First-seen wins. Multiple POS entries for the same apostrophized
            # word (e.g. `il y a` as prep and as verb) all resolve to the same
            # cue for step_3a; the richer sense menu lookup happens in step_5c.
            index.setdefault(key, (pos, gloss))

    with open(cache_path, "wb") as f:
        pickle.dump((_APOS_CACHE_VERSION, index), f)
    print(f"    {len(index)} apostrophized phrase/contraction entries indexed")
    return index

PIPELINE_DIR = None
IN_PATH = None
OUT_PATH = None
MAPPING_PATH = None
MAX_EXAMPLES = 10

# ---------------------------------------------------------------------------
# D-elision patterns: masc/fem × sing/pl. Ordered longest-suffix-first so
# '-a'os'/'-í'as' are matched before '-a'o'/'-í'a'.
# ---------------------------------------------------------------------------
D_ELISION_RULES = [
    (re.compile(r"^(.+)a'os$"), "ados"),
    (re.compile(r"^(.+)a'as$"), "adas"),
    (re.compile(r"^(.+)í'os$"), "idos"),
    (re.compile(r"^(.+)í'as$"), "idas"),
    (re.compile(r"^(.+)a'o$"), "ado"),
    (re.compile(r"^(.+)a'a$"), "ada"),
    (re.compile(r"^(.+)í'o$"), "ido"),
    (re.compile(r"^(.+)í'a$"), "ida"),
]

D_ELISION_EXCEPTIONS = frozenset()

# ---------------------------------------------------------------------------
# Extended d-elision families (v8). Same phenomenon as D_ELISION_RULES — an
# intervocalic /d/ dropped in the lyric — but three spellings the original
# rules miss:
#
#   * unaccented -i' spellings. The originals require a written accent
#     (`metí'o`), but Genius transcribes `meti'o` / `perdi'o` / `lambi'a`
#     just as often.
#   * the Caribbean u-final variant of -ado: `acostumbra'u`, `monta'u`.
#   * a diminutive stacked on top of the elision (`apreta'íto`,
#     `calla'íta`, `para'ita`, `desnu'itos`), plus plain u-stem forms
#     (`desnu'a` → desnuda).
#
# Unlike the trailing-apostrophe tiebreaker, these are unambiguous: the
# apostrophe sits between two vowels, so only /d/ can have been dropped.
# Every restoration is still validated against spanish_forms before it is
# emitted, so a nonsense stem can never invent a lemma. Ordered
# longest-suffix-first (plural before singular).
_EXT_APOS = "['’]"


def _ext(suffix_re, restored, family):
    return (re.compile(r"^(.+)" + suffix_re + r"$"), restored, family)


D_ELISION_EXT_RULES = [
    # -- diminutive stacked on the elision: apreta'íto -> apretadito ---------
    _ext("a" + _EXT_APOS + "[íi]tos", "aditos", "d_elision_diminutive"),
    _ext("a" + _EXT_APOS + "[íi]tas", "aditas", "d_elision_diminutive"),
    _ext("a" + _EXT_APOS + "[íi]to", "adito", "d_elision_diminutive"),
    _ext("a" + _EXT_APOS + "[íi]ta", "adita", "d_elision_diminutive"),
    _ext("u" + _EXT_APOS + "[íi]tos", "uditos", "d_elision_diminutive"),
    _ext("u" + _EXT_APOS + "[íi]tas", "uditas", "d_elision_diminutive"),
    _ext("u" + _EXT_APOS + "[íi]to", "udito", "d_elision_diminutive"),
    _ext("u" + _EXT_APOS + "[íi]ta", "udita", "d_elision_diminutive"),
    _ext("[íi]" + _EXT_APOS + "[íi]tos", "iditos", "d_elision_diminutive"),
    _ext("[íi]" + _EXT_APOS + "[íi]tas", "iditas", "d_elision_diminutive"),
    _ext("[íi]" + _EXT_APOS + "[íi]to", "idito", "d_elision_diminutive"),
    _ext("[íi]" + _EXT_APOS + "[íi]ta", "idita", "d_elision_diminutive"),
    # -- Caribbean u-final -ado: acostumbra'u -> acostumbrado ---------------
    _ext("a" + _EXT_APOS + "us", "ados", "d_elision_u_final"),
    _ext("a" + _EXT_APOS + "u", "ado", "d_elision_u_final"),
    # -- unaccented -i' spellings: meti'o -> metido -------------------------
    _ext("i" + _EXT_APOS + "os", "idos", "d_elision_unaccented"),
    _ext("i" + _EXT_APOS + "as", "idas", "d_elision_unaccented"),
    _ext("i" + _EXT_APOS + "o", "ido", "d_elision_unaccented"),
    _ext("i" + _EXT_APOS + "a", "ida", "d_elision_unaccented"),
    # -- u-stem forms: desnu'a -> desnuda -----------------------------------
    _ext("u" + _EXT_APOS + "os", "udos", "d_elision_ustem"),
    _ext("u" + _EXT_APOS + "as", "udas", "d_elision_ustem"),
    _ext("u" + _EXT_APOS + "o", "udo", "d_elision_ustem"),
    _ext("u" + _EXT_APOS + "a", "uda", "d_elision_ustem"),
]

# Apostrophe-less d-elision. The rules above all require the apostrophe the
# lyric usually keeps (arrebata'o), but Genius transcriptions frequently drop
# it too, leaving a bare `metíos` / `arrebataos` / `exagerao`. Those never match
# above, so real past participles fall through to sense_discovery and Gemini is
# asked to invent a meaning for a word Spanish already has.
#
# These patterns are far more dangerous than the apostrophe'd ones, because
# `-ía`/`-ías`/`-ás` are also ordinary imperfect and future endings: unguarded,
# they rewrite estás→estadas, vía→vida, quería→querida. bare_d_elision_canonical
# therefore fires ONLY when the surface is not itself a known Spanish form and
# the restored candidate is one. On the Bad Bunny corpus that is 43 recoveries
# with zero false positives; without the guard it is 135 corruptions.
D_ELISION_BARE_DIMINUTIVE_RULES = [
    (re.compile(r"^(.+)aítas$"), "aditas", "ado"),
    (re.compile(r"^(.+)aítos$"), "aditos", "ado"),
    (re.compile(r"^(.+)aíta$"), "adita", "ado"),
    (re.compile(r"^(.+)aíto$"), "adito", "ado"),
]

D_ELISION_BARE_RULES = [
    (re.compile(r"^(.+)íos$"), "idos"),
    (re.compile(r"^(.+)ías$"), "idas"),
    (re.compile(r"^(.+)aos$"), "ados"),
    (re.compile(r"^(.+)ás$"), "adas"),
    (re.compile(r"^(.+)ío$"), "ido"),
    (re.compile(r"^(.+)ía$"), "ida"),
    (re.compile(r"^(.+)ao$"), "ado"),
]

# Trailing-apostrophe consonant candidates (s-elision is most common; others
# cover verda' → verdad, die' → diez, comé' → comer).
_TRAILING_APOS_RESTORES = ("s", "d", "z", "r", "l", "n")
# Internal omissions are less phonologically constrained than final Caribbean
# consonant deletion (e'perado could spell esperado or the rare emperado).
# Generate the full consonant set, then let the known-form + uniqueness gates
# do the conservative work.
_INTERNAL_APOS_RESTORES = tuple("bcdfghjklmnñpqrstvwxyz")
_SPANISH_APOSTROPHES = ("'", "\u2019")

# ---------------------------------------------------------------------------
# Ambiguous elisions — split per-example using the preceding word
# ---------------------------------------------------------------------------
DISAMBIG_METHOD = "preceding_word"

AMBIGUOUS_ELISIONS = {
    "ve'": {
        "noun_target": "vez",
        "verb_target": "ves",
        "noun_preceding": frozenset({
            "una", "otra", "cada", "tal", "última", "primera",
            "esta", "esa", "la", "qué", "alguna", "cualquier",
        }),
        "noun_pos": frozenset({"NOUN"}),
    },
}

_TOKENIZE_RE = re.compile(r"[\w''\u2019]+", re.UNICODE)
_spacy_nlp = None


def _get_spacy_trf():
    global _spacy_nlp
    if _spacy_nlp is None:
        import spacy
        _spacy_nlp = spacy.load("es_dep_news_trf")
    return _spacy_nlp


def _preceding_word(line, target_form):
    tokens = _TOKENIZE_RE.findall(line.lower())
    for i, tok in enumerate(tokens):
        if tok == target_form and i > 0:
            return tokens[i - 1]
    return None


def _disambiguate_example(amb, word, line):
    if DISAMBIG_METHOD == "spacy_trf":
        nlp = _get_spacy_trf()
        doc = nlp(line)
        for tok in doc:
            if tok.text.lower().rstrip("'\u2019") == word.rstrip("'\u2019"):
                if tok.pos_ in amb["noun_pos"]:
                    return amb["noun_target"]
                return amb["verb_target"]
        return amb["verb_target"]

    prev = _preceding_word(line, word)
    if prev in amb["noun_preceding"]:
        return amb["noun_target"]
    return amb["verb_target"]


def d_elision_canonical(word):
    """If word is a d-elision (any masc/fem × sing/pl form), return
    (canonical, display) else None.
    """
    if word in D_ELISION_EXCEPTIONS:
        return None
    for pattern, suffix in D_ELISION_RULES:
        m = pattern.match(word)
        if m:
            return (m.group(1) + suffix, word)
    return None


def bare_d_elision_canonical(word, known_set):
    """Apostrophe-less d-elision: `metíos` → `metidos`, `exagerao` → `exagerado`.

    Deliberately conservative, because the bare patterns collide with ordinary
    imperfect/future endings. Both guards are required:

    * the surface must NOT already be a known Spanish form — that alone spares
      estás, vía, quería, mía, sabía and 130 others; and
    * the restored candidate MUST be a known Spanish form, so a nonsense stem
      can never invent a lemma.

    Returns (canonical, display) or None.
    """
    if not known_set or word in D_ELISION_EXCEPTIONS or word in known_set:
        return None
    # Generated diminutive gender/number forms are incomplete in
    # spanish_forms. The accented `aít-` signature is specific enough to
    # restore when its ordinary -ado base exists (mojaítas → mojaditas,
    # with mojado validating the stem).
    for pattern, suffix, base_suffix in D_ELISION_BARE_DIMINUTIVE_RULES:
        match = pattern.match(word)
        if match and match.group(1) + base_suffix in known_set:
            return (match.group(1) + suffix, word)
    for pattern, suffix in D_ELISION_BARE_RULES:
        m = pattern.match(word)
        if m:
            candidate = m.group(1) + suffix
            if candidate in known_set:
                return (candidate, word)
    return None


def d_elision_ext_canonical(word, known_set):
    """Extended d-elision families (unaccented -i', -a'u, diminutive, u-stem).

    Returns ``(canonical, display, family)`` or None. Unlike
    :func:`d_elision_canonical`, every restoration is validated against the
    canonical Spanish form table, because these patterns are looser: only a
    candidate Spanish already has is emitted, so a nonsense stem can never
    invent a lemma. `family` is carried into the merge_type/stats label so
    each rule set stays auditable and revertible on its own.
    """
    if not known_set or word in D_ELISION_EXCEPTIONS:
        return None
    for pattern, suffix, family in D_ELISION_EXT_RULES:
        m = pattern.match(word)
        if m:
            candidate = m.group(1) + suffix
            if candidate in known_set:
                return (candidate, word, family)
            # spanish_forms deliberately contains attested/generated ordinary
            # forms, not every productive diminutive.  The apostrophe pattern
            # itself is specific, so validate the stem against its base
            # adjective just as the apostrophe-less rule does.  This recovers
            # moja'íta -> mojadita without accepting an arbitrary invented
            # target.
            if family == "d_elision_diminutive":
                diminutive = re.match(r"^(.+)(ad|id|ud)it(?:o|a|os|as)$", candidate)
                if diminutive:
                    base = diminutive.group(1) + diminutive.group(2) + "o"
                    if base in known_set:
                        return (candidate, word, family)
    return None


def double_elision_canonical(word, known_set=None):
    """Chain: `parao'` → `parao` → `parado`, `apretaíto'` → `apretadito`.

    A word ending in `'` where the stripped stem is itself a d-elision target.
    When `known_set` is supplied the stripped stem is also run through the
    extended and bare (apostrophe-less) d-elision rules — both validate their
    own output — so `apretaíto'` no longer stops halfway.
    Returns (canonical, display) or None. Display is the original double-elided
    form.
    """
    if not word.endswith("'"):
        return None
    stripped = word[:-1]
    d = d_elision_canonical(stripped)
    if d:
        return (d[0], word)
    if known_set:
        ext = d_elision_ext_canonical(stripped, known_set)
        if ext:
            return (ext[0], word)
        bare = bare_d_elision_canonical(stripped, known_set)
        if bare:
            return (bare[0], word)
    return None


def trailing_apos_restore(word, known_set):
    """For a `word'` form not covered by other rules, try restoring a dropped
    final consonant (s/d/z/r/l/n). Returns (canonical, display) or None.

    A single hit wins outright. When several restorations are known words the
    surface form alone cannot separate them, so frequency decides: a
    fourfold-dominant candidate wins (this is what resolves the z/s and d/s
    transcription pairs, cruz/crus and usted/ustes), and anything closer than
    that abstains and is left for step 4. ma' -> mas/mal/mar abstains here;
    note that it is instead resolved upstream by the static elision mapping,
    which never sees the line.
    """
    if not word.endswith("'") or len(word) < 3:
        return None
    stem = word[:-1]
    if stem.casefold() in load_shared_lexemes():
        return None
    hits = [stem + c for c in _TRAILING_APOS_RESTORES if (stem + c) in known_set]
    frequencies = load_surface_frequency()
    shared_lexemes = load_shared_lexemes()
    registered_hits = [hit for hit in hits if hit.casefold() in shared_lexemes]
    if len(registered_hits) == 1:
        return (registered_hits[0], word)
    if len(hits) == 1:
        # Broad form tables contain synthetic/foreign curiosities.  A fallback
        # restoration must also have real corpus support.
        if (frequencies.get(hits[0].casefold(), 0) > 0
                or hits[0].casefold() in shared_lexemes):
            return (hits[0], word)
        return None
    if len(hits) > 1:
        ranked = sorted(
            ((frequencies.get(hit.casefold(), 0), hit) for hit in hits),
            reverse=True,
        )
        best_frequency, best = ranked[0]
        runner_up = ranked[1][0]
        # Fourfold dominance is intentionally conservative: it fixes obvious
        # feliz/felis and usted/ustes cases but leaves real homographs to WSD.
        if best_frequency > 0 and best_frequency >= max(4 * runner_up, 20):
            return (best, word)
    return None


def internal_apos_candidates(word, known_set):
    """Return minimal one-consonant restorations that are known Spanish.

    Unlike the legacy generated mapping, this does not guess a suffix.  It
    inserts one commonly elided consonant exactly where the transcription put
    the apostrophe and returns every candidate present in ``known_set``.
    A conservative orthographic variant also maps ``k`` to ``c`` before the
    lookup (``discoteka'`` -> ``discotecas``); it is harmless unless the final
    restored spelling is independently known Spanish.
    """
    if not known_set:
        return []
    normalized = word.replace("\u2019", "'")
    if normalized.count("'") != 1 or len(normalized) < 3:
        return []
    apos_index = normalized.index("'")
    bare = normalized.replace("'", "")
    bases = {bare}
    if "k" in bare:
        bases.add(bare.replace("k", "c"))
    hits = {
        base[:apos_index] + consonant + base[apos_index:]
        for base in bases
        for consonant in _INTERNAL_APOS_RESTORES
        if base[:apos_index] + consonant + base[apos_index:] in known_set
    }
    return sorted(hits)


def internal_apos_restore(word, known_set):
    """Restore an apostrophe-position consonant only when the result is unique."""
    hits = internal_apos_candidates(word, known_set)
    if len(hits) == 1:
        return (hits[0], word)
    return None


def load_merge_targets(mapping_path):
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    targets = {}
    for r in mapping:
        if r["action"] != "merge":
            continue
        if r["merge_type"] == "elision_pair":
            targets[r["elided_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
            targets[r["full_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
        elif r["merge_type"] == "elided_only":
            targets[r["elided_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
    return targets


def load_known_vocab():
    """Known-Spanish set backing the trailing-apos tiebreaker.

    This used to read Data/Spanish/vocabulary.json, which no longer exists —
    the deck moved to the split vocabulary.index.json / vocabulary.examples.json
    format and the monolithic file is gitignored. The loader returned an empty
    set on any current checkout, silently disabling the tiebreaker: 191 elided
    forms survived as their own Bad Bunny cards (vengamo', estuviésemo',
    virtude') instead of merging into vengamos / estuviésemos / virtudes.

    It now uses spanish_forms.json, the same canonical "is this Spanish?" table
    step_4a consults. The split deck index is NOT a workable substitute for the
    original file: it holds ~9.4k mostly-lemma entries and recovers 0 of the 191,
    because the needed targets are inflected forms that were never deck cards.
    spanish_forms recovers 65.

    Widening the set cannot disturb an existing merge: the tiebreaker only runs
    after the explicit mapping, d-elision and double-elision rules have all
    declined, so it can add merges but never override one.
    """
    return load_spanish_forms()


_spanish_forms_cache = None
_surface_frequency_cache = None
_shared_lexeme_cache = None


def load_spanish_forms():
    """Canonical 'is this a Spanish form?' set — the same source step_4a uses.

    Needed by the bare d-elision rule, whose safety depends entirely on knowing
    which surfaces are already real Spanish (estás, vía, quería). A deck-shaped
    word list is not sufficient for that; the full form table is.
    """
    global _spanish_forms_cache
    if _spanish_forms_cache is None:
        path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers", "spanish_forms.json")
        if not os.path.isfile(path):
            _spanish_forms_cache = frozenset()
        else:
            with open(path, "r", encoding="utf-8") as f:
                _spanish_forms_cache = frozenset(json.load(f))
    return _spanish_forms_cache


def load_surface_frequency():
    """Return the frequency list used to break ambiguous restorations.

    ``spanish_forms`` is deliberately broad and contains rare names, foreign
    forms and generated inflections.  Treating every member as equally likely
    caused ``feli' -> felis`` and ``uste' -> ustes``.  The corpus wordlist lets
    us choose only when one candidate is strongly attested; otherwise the
    normalizer abstains and leaves the occurrence for later classification.
    """
    global _surface_frequency_cache
    if _surface_frequency_cache is None:
        path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "es_50k_wordlist.txt")
        frequencies = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            frequencies[parts[0].casefold()] = int(parts[1])
                        except ValueError:
                            continue
        _surface_frequency_cache = frequencies
    return _surface_frequency_cache


def load_shared_lexemes():
    """Known artist lexemes whose apostrophe is stylistic, not restorative.

    A registered lexical item such as Puerto Rican ``mai'`` must remain
    ``mai``; the existence of obscure dictionary form ``mais`` is not evidence
    that the lyric dropped an ``s``.  Only headwords already accepted into the
    artist master or a shared register receive this protection.
    """
    global _shared_lexeme_cache
    if _shared_lexeme_cache is None:
        lexemes = set()
        master_path = os.path.join(_PROJECT_ROOT, "Artists", "spanish",
                                   "vocabulary_master.json")
        if os.path.isfile(master_path):
            with open(master_path, encoding="utf-8") as handle:
                for card in json.load(handle).values():
                    lexemes.add(str(card.get("word") or "").casefold())
                    lexemes.add(str(card.get("lemma") or "").casefold())
        register_dir = os.path.join(_PROJECT_ROOT, "Artists", "spanish",
                                    "sense_registers")
        if os.path.isdir(register_dir):
            for filename in os.listdir(register_dir):
                if not filename.endswith(".json") or filename == "policy.json":
                    continue
                with open(os.path.join(register_dir, filename), encoding="utf-8") as handle:
                    lexemes.update((json.load(handle).get("senses") or {}).keys())
        _shared_lexeme_cache = frozenset(word for word in lexemes if word)
    return _shared_lexeme_cache


def merge_evidence(data, targets, known_vocab):
    """Merge entries. Returns a new list. Each example carries `surface`."""
    groups = defaultdict(lambda: {"count": 0, "examples": [], "display_form": None,
                                  "variants": {}, "song_ids": set()})

    stats = {"mapping": 0, "d_elision": 0, "d_elision_unaccented": 0,
             "d_elision_u_final": 0, "d_elision_diminutive": 0,
             "d_elision_ustem": 0, "double_elision": 0, "trailing_apos": 0,
             "bare_d_elision": 0, "unmerged": 0}

    for entry in data:
        word = entry["word"]
        count = entry.get("corpus_count", 0)
        examples = entry.get("examples", [])
        entry_song_ids = set(str(sid) for sid in entry.get("song_ids", []))
        if not entry_song_ids:
            entry_song_ids = {
                ex["id"].split(":")[0] for ex in examples if ex.get("id")
            }

        # Ambiguous elisions: split per example
        if word in AMBIGUOUS_ELISIONS and word in targets:
            amb = AMBIGUOUS_ELISIONS[word]
            display = targets[word]["display_form"]
            target_example_counts = defaultdict(int)
            assigned_song_ids = set()
            for ex in examples:
                key = _disambiguate_example(amb, word, ex.get("line", ""))
                groups[key]["display_form"] = display
                ex["surface"] = word
                groups[key]["examples"].append(ex)
                target_example_counts[key] += 1
                if ex.get("id"):
                    song_id = ex["id"].split(":")[0]
                    groups[key]["song_ids"].add(song_id)
                    assigned_song_ids.add(song_id)
            n_examples = len(examples)
            if n_examples > 0:
                for tgt, ex_count in target_example_counts.items():
                    proportional = round(count * ex_count / n_examples)
                    groups[tgt]["count"] += proportional
                    groups[tgt]["variants"][word] = (
                        groups[tgt]["variants"].get(word, 0) + proportional
                    )
            else:
                fallback = amb["verb_target"]
                groups[fallback]["count"] += count
                groups[fallback]["variants"][word] = (
                    groups[fallback]["variants"].get(word, 0) + count
                )
            # The capped examples cannot disambiguate every corpus song. Keep
            # observed noun/verb allocations and conservatively route unseen
            # songs to the same verb fallback used for unrepresented counts.
            groups[amb["verb_target"]]["song_ids"].update(entry_song_ids - assigned_song_ids)
            stats["mapping"] += 1
            continue

        key = None
        display = None
        source = "unmerged"

        if word in targets:
            t = targets[word]
            key = t["target_word"]
            display = t["display_form"]
            source = "mapping"
        else:
            # Try d-elision (plural/feminine/masculine)
            d = d_elision_canonical(word)
            if d:
                key, display = d[0], d[1]
                source = "d_elision"
            else:
                # Extended d-elision families (unaccented -i', -a'u,
                # diminutive, u-stem). Validated, so they run before the
                # looser trailing-apostrophe tiebreaker.
                ext = d_elision_ext_canonical(word, load_spanish_forms())
                if ext:
                    key, display, source = ext[0], ext[1], ext[2]
                # Try double-elision: parao' → parado
                elif (dd := double_elision_canonical(word, load_spanish_forms())):
                    key, display = dd[0], dd[1]
                    source = "double_elision"
                else:
                    # Try trailing-apos tiebreaker
                    tap = (trailing_apos_restore(word, known_vocab)
                           or internal_apos_restore(word, known_vocab))
                    if tap:
                        key, display = tap[0], tap[1]
                        source = "trailing_apos"
                    else:
                        # Last resort: apostrophe-less d-elision. Runs after
                        # every other rule so it can never pre-empt one, and
                        # only touches words nothing else claimed.
                        bare = bare_d_elision_canonical(word, load_spanish_forms())
                        if bare:
                            key, display = bare[0], bare[1]
                            source = "bare_d_elision"

        # A resolved target can itself still be an apostrophe-less d-elision:
        # the mapping restores metío' -> metíos, which is not a Spanish word
        # either. Normalise the key so the chain lands on metidos rather than
        # stopping halfway. Display keeps the original lyric surface.
        if key is not None:
            bare_key = bare_d_elision_canonical(key, load_spanish_forms())
            if bare_key:
                key = bare_key[0]

        if key is None:
            key = word
            display = word
            source = "unmerged"

        stats[source] = stats.get(source, 0) + 1

        if groups[key]["display_form"] is None:
            groups[key]["display_form"] = display

        for ex in examples:
            ex["surface"] = ex.get("surface", word)  # preserve pre-existing surface from step 2a

        groups[key]["count"] += count
        groups[key]["song_ids"].update(entry_song_ids)
        groups[key]["examples"].extend(examples)
        groups[key]["variants"][word] = groups[key]["variants"].get(word, 0) + count

    # Build output, deduplicating examples by song
    out = []
    for word, g in groups.items():
        seen_songs = set()
        deduped = []
        for ex in g["examples"]:
            song_id = ex["id"].split(":")[0] if "id" in ex else None
            if song_id and song_id in seen_songs:
                continue
            if song_id:
                seen_songs.add(song_id)
            deduped.append(ex)

        entry = {
            "word": word,
            "corpus_count": g["count"],
            "song_count": len(g["song_ids"]),
            "song_ids": sorted(g["song_ids"], key=str),
            "examples": deduped[:MAX_EXAMPLES],
        }
        if g["display_form"] and g["display_form"] != word:
            entry["display_form"] = g["display_form"]
        if len(g["variants"]) >= 2:
            entry["variants"] = g["variants"]

        out.append(entry)

    out.sort(key=lambda e: -e["corpus_count"])
    return out, stats


def merge_evidence_french(data, apos_phrase_index=None):
    """French elision handling.

    Tiering (checked in order; first match wins):
      Tier A — `apos_phrase_index` says this apostrophized form has a
               dedicated Wiktionary entry (c'est, j'ai, qu'il, n'est, s'il,
               m'a, t'as, jusqu'au, …). Keep as its own entry; the sense
               menu built in step_5c will use the phrase/contraction gloss.
      Tier C — `french_split_to_function_words` recognises a colloquial
               `proclitic + function-word` fusion (m'le=me+le, qu'le=que+le,
               j'suis=je+suis, j'me=je+me, t'en=te+en). Counts and examples
               flow to BOTH halves; no standalone m'le entry survives. This
               rescues rap-heavy corpora where these forms would otherwise
               dump counts onto a single article/pronoun and surface as
               noisy count-1 variant chips.
      Tier B — `french_strip_proclitic` recognises a proclitic + content-word
               tail (l'amour, j'aime, l'autre, d'un). Strip the proclitic,
               merge counts/examples into the bare tail (original behaviour).
      Tier D — non-apostrophe tokens fall through as-is.

    ``apos_phrase_index`` is the dict returned by ``load_french_apos_phrases``.
    Passing ``None`` disables Tier A and falls back to pre-tier-4 behaviour
    (useful for tests).
    """
    groups = defaultdict(lambda: {"count": 0, "examples": [], "display_form": None,
                                  "variants": {}, "song_ids": set()})
    stats = {"apos_phrase_kept": 0, "function_word_split": 0,
             "proclitic_split": 0, "unmerged": 0}
    apos_phrase_index = apos_phrase_index or {}
    phrase_hits = []  # (word, pos, gloss, count) for reporting
    split_hits = []   # (word, expanded, tail, count) for reporting

    def _add_to_group(key, display, examples, count, source_word, song_ids):
        """Accumulate count/examples/variant under a group key."""
        if groups[key]["display_form"] is None:
            groups[key]["display_form"] = display
        for ex in examples:
            ex["surface"] = ex.get("surface", source_word)
        groups[key]["count"] += count
        groups[key]["song_ids"].update(song_ids)
        groups[key]["examples"].extend(examples)
        groups[key]["variants"][source_word] = (
            groups[key]["variants"].get(source_word, 0) + count
        )

    for entry in data:
        word = entry["word"]
        count = entry.get("corpus_count", 0)
        examples = entry.get("examples", [])
        song_ids = set(str(sid) for sid in entry.get("song_ids", []))
        if not song_ids:
            song_ids = {ex["id"].split(":")[0] for ex in examples if ex.get("id")}

        is_apos = ("'" in word) or ("\u2019" in word)

        # Tier A: Wiktionary knows this apostrophized form as a lexical unit.
        apos_hit = apos_phrase_index.get(_normalize_apos(word)) if is_apos else None
        if apos_hit is not None:
            source = "apos_phrase_kept"
            stats[source] = stats.get(source, 0) + 1
            phrase_hits.append((word, apos_hit[0], apos_hit[1], count))
            _add_to_group(word, word, examples, count, word, song_ids)
            continue

        # Tier C: proclitic + function-word. Split into two words.
        split = french_split_to_function_words(word) if is_apos else None
        if split is not None:
            expanded, tail = split
            source = "function_word_split"
            stats[source] = stats.get(source, 0) + 1
            split_hits.append((word, expanded, tail, count))
            # Same count to both halves — the corpus line counts as one
            # instance of each word, just fused orthographically. Examples
            # are shared (a copy per half keeps surface/id intact for each).
            _add_to_group(expanded, expanded, examples, count, word, song_ids)
            _add_to_group(tail, tail, list(examples), count, word, song_ids)
            continue

        # Tier B: proclitic + content-word. Strip proclitic, merge onto tail.
        tail = french_strip_proclitic(word) if is_apos else None
        if tail is not None:
            source = "proclitic_split"
            stats[source] = stats.get(source, 0) + 1
            _add_to_group(tail, word, examples, count, word, song_ids)
            continue

        # Tier D: plain word, no apostrophe machinery applies.
        stats["unmerged"] = stats.get("unmerged", 0) + 1
        _add_to_group(word, word, examples, count, word, song_ids)

    # Build output (dedup by song — matches Spanish behaviour)
    out = []
    for word, g in groups.items():
        seen_songs = set()
        deduped = []
        for ex in g["examples"]:
            song_id = ex["id"].split(":")[0] if "id" in ex else None
            if song_id and song_id in seen_songs:
                continue
            if song_id:
                seen_songs.add(song_id)
            deduped.append(ex)

        entry = {
            "word": word,
            "corpus_count": g["count"],
            "song_count": len(g["song_ids"]),
            "song_ids": sorted(g["song_ids"], key=str),
            "examples": deduped[:MAX_EXAMPLES],
        }
        if g["display_form"] and g["display_form"] != word:
            entry["display_form"] = g["display_form"]
        if len(g["variants"]) >= 2:
            entry["variants"] = g["variants"]
        out.append(entry)

    out.sort(key=lambda e: -e["corpus_count"])
    return out, stats


def main():
    global PIPELINE_DIR, IN_PATH, OUT_PATH, MAPPING_PATH

    parser = argparse.ArgumentParser(description="Step 3: Merge elisions and normalize variants")
    parser.add_argument("--artist-dir", required=True, help="Path to artist data directory")
    parser.add_argument("--language", choices=("spanish", "french"), default="spanish",
                        help="Language-specific normalization (default: spanish)")
    args = parser.parse_args()

    PIPELINE_DIR = os.path.abspath(args.artist_dir)
    IN_PATH = Path(os.path.join(PIPELINE_DIR, "data", "word_counts", "vocab_evidence.json"))
    OUT_PATH = Path(os.path.join(PIPELINE_DIR, "data", "elision_merge", "vocab_evidence_merged.json"))
    MAPPING_PATH = Path(os.path.join(SHARED_DIR, "elision_mapping.json"))

    print(f"Loading {IN_PATH} ...")
    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {len(data)} entries")

    # French: simpler flow, no Spanish-specific loading.
    if args.language == "french":
        print(f"Language: french (apos-phrase tier + proclitic splitter)")
        french_kaikki_path = Path(
            os.path.join(_PROJECT_ROOT, "Data", "French", "Senses",
                         "wiktionary", "kaikki-french.jsonl.gz")
        )
        apos_index = load_french_apos_phrases(french_kaikki_path)
        merged, stats = merge_evidence_french(data, apos_phrase_index=apos_index)

        os.makedirs(os.path.dirname(str(OUT_PATH)), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        upstream = dependency_metadata(IN_PATH)
        write_sidecar(OUT_PATH, make_meta("merge_elisions", STEP_VERSION,
                                          extra={**upstream, "language": "french",
                                                 "apos_phrase_index_size": len(apos_index)}))
        archive_json_artifact(
            Path(PIPELINE_DIR) / "data" / "evidence",
            "elision_normalization",
            merged,
            language=args.language,
            adapter={"name": "artist-step-3a", "version": STEP_VERSION},
            inputs=upstream,
            config={"apos_phrase_index_size": len(apos_index)},
        )

        print(f"\nWrote {len(merged)} entries -> {OUT_PATH}")
        print(f"  Reduced by {len(data) - len(merged)} entries")
        print(f"  Merge sources:")
        for k in ("apos_phrase_kept", "function_word_split",
                  "proclitic_split", "unmerged"):
            print(f"    {k}: {stats.get(k, 0)}")
        print("\n=== Top 20 merged entries ===")
        for e in merged[:20]:
            df = e.get("display_form", "")
            display = f" (display: {df})" if df else ""
            print(f"  {e['word']}{display} — {e['corpus_count']} occurrences, {len(e['examples'])} examples")
        return

    # Spanish (default)
    print(f"Loading merge mapping from {MAPPING_PATH} ...")
    targets = load_merge_targets(MAPPING_PATH)
    print(f"  {len(targets)} words have merge targets")

    print("Loading normal-mode vocabulary for trailing-apos tiebreaker ...")
    known_vocab = load_known_vocab()
    print(f"  {len(known_vocab)} canonical forms")

    merged, stats = merge_evidence(data, targets, known_vocab)

    os.makedirs(os.path.dirname(str(OUT_PATH)), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    upstream = dependency_metadata(IN_PATH)
    write_sidecar(OUT_PATH, make_meta(
        "merge_elisions", STEP_VERSION, extra=upstream))
    archive_json_artifact(
        Path(PIPELINE_DIR) / "data" / "evidence",
        "elision_normalization",
        merged,
        language=args.language,
        adapter={"name": "artist-step-3a", "version": STEP_VERSION},
        inputs=upstream,
        config={"ambiguous_elision_method": DISAMBIG_METHOD},
    )

    print(f"\nWrote {len(merged)} entries -> {OUT_PATH}")
    print(f"  Reduced by {len(data) - len(merged)} entries")
    print(f"  Merge sources:")
    for k in ("mapping", "d_elision", "d_elision_unaccented", "d_elision_u_final",
              "d_elision_diminutive", "d_elision_ustem", "double_elision",
              "trailing_apos", "bare_d_elision", "unmerged"):
        print(f"    {k}: {stats.get(k, 0)}")
    if AMBIGUOUS_ELISIONS:
        print(f"  Ambiguous elision method: {DISAMBIG_METHOD}")

    # Report ambiguous elision splits
    for amb_word, amb in AMBIGUOUS_ELISIONS.items():
        noun_t = amb["noun_target"]
        verb_t = amb["verb_target"]
        noun_entry = next((e for e in merged if e["word"] == noun_t), None)
        verb_entry = next((e for e in merged if e["word"] == verb_t), None)
        noun_from_amb = 0
        verb_from_amb = 0
        if noun_entry and noun_entry.get("variants"):
            noun_from_amb = noun_entry["variants"].get(amb_word, 0)
        if verb_entry and verb_entry.get("variants"):
            verb_from_amb = verb_entry["variants"].get(amb_word, 0)
        if noun_from_amb or verb_from_amb:
            print(f"  Ambiguous '{amb_word}' split: "
                  f"{noun_from_amb} → {noun_t}, {verb_from_amb} → {verb_t}")

    print("\n=== Top 20 merged entries ===")
    for e in merged[:20]:
        df = e.get("display_form", "")
        display = f" (display: {df})" if df else ""
        print(f"  {e['word']}{display} — {e['corpus_count']} occurrences, {len(e['examples'])} examples")


if __name__ == "__main__":
    main()
