"""Shared routing helpers for step_4a (normal + artist modes).

Provides:
  - Clitic pronoun stripping + gerund decomposition
  - Wiktionary clitic-data loader (base + attached pronouns + their roles)
  - SpanishDict parent inventory (which lemmas may own a card)
  - Three-tier clitic classification (clitic_merge / clitic_keep)
  - Morphological derivation resolver (diminutive / superlative)

Division of labour between the two dictionaries:

  * **Wiktionary** routes. Its `form-of` entries say which verb a clitic form
    belongs to, which pronouns are attached, and — via the `accusative` /
    `dative` / `object-*-person` / `reflexive` tags — what each pronoun is
    doing. That annotation is preserved end to end; the front end's
    `describeCliticForm()` depends on it.
  * **SpanishDict** owns the parent inventory. A clitic form may only be given
    a `-se` parent card when SpanishDict actually publishes a `-se` headword,
    and SpanishDict's own entry sizes break the tie in the one case morphology
    cannot decide (see `prefers_reflexive_parent`).
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

# Pronouns that agree in person with the subject and can therefore be
# reflexive. Spanish reflexives are NOT just `se` — `me`/`te`/`nos`/`os` are the
# 1s/2s/1p/2p members of the same paradigm, which is why a literal `"se" in
# clitics` test mis-files `alejarme` as a plain object form.
_REFLEXIVE_CLITICS = frozenset({"me", "te", "se", "nos", "os"})
# Third-person object pronouns, which can never be reflexive.
_ACCUSATIVE_CLITICS = frozenset({"lo", "la", "los", "las"})
_DATIVE_CLITICS = frozenset({"le", "les"})

# Person (and number) each agreeing pronoun demands of the subject.
CLITIC_PERSON = {"me": "1s", "te": "2s", "nos": "1p", "os": "2p"}


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

    Returns (base_infinitive, [attached clitics]) if decomposable, else None.
    E.g., 'dándote' → ('dar', ['te']), 'ahogándome' → ('ahogar', ['me']),
    'alejarte' → ('alejar', ['te']), 'dármelo' → ('dar', ['me', 'lo']).
    The clitic list is what lets the caller derive each pronoun's role
    positionally when Wiktionary has no entry for the form.

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
        return (decompose_infinitive_clitic(word, known_words)
                or decompose_imperative_clitic(word, known_words))

    clean = _strip_acute(remaining)
    if clean.endswith("ando"):
        infinitive = clean[:-4] + "ar"
    elif clean.endswith("iendo"):
        infinitive = clean[:-5] + "ir"
    elif clean.endswith("endo"):
        infinitive = clean[:-4] + "er"
    else:
        return (decompose_infinitive_clitic(word, known_words)
                or decompose_imperative_clitic(word, known_words))

    if infinitive in known_words:
        return (infinitive, list(clitics))
    return (decompose_infinitive_clitic(word, known_words)
            or decompose_imperative_clitic(word, known_words))


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
_conj_reverse = None         # {form: [{lemma, mood, tense, person}, ...]}
_verb_data_loaded = False


def _load_verb_evidence(conjugations_path=None, spanish_forms_path=None,
                        conj_reverse_path=None):
    """Lazily load the verb lookups the infinitive guard needs (once)."""
    global _verb_lemmas, _verb_pos, _conj_reverse, _verb_data_loaded
    if _verb_data_loaded:
        return
    _verb_data_loaded = True
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    layers = os.path.join(root, "Data", "Spanish", "layers")
    conj = conjugations_path or os.path.join(layers, "conjugations.json")
    forms = spanish_forms_path or os.path.join(layers, "spanish_forms.json")
    reverse = conj_reverse_path or os.path.join(layers,
                                                "conjugation_reverse.json")
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
    try:
        with open(reverse, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _conj_reverse = data
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

    Returns (base_infinitive, [attached clitics]) or None. E.g. 'alejarte' →
    ('alejar', ['te']), 'dármelo' → ('dar', ['me', 'lo']), 'ponerse' →
    ('poner', ['se']).

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
            return (candidate, list(clitics))
    return None


# ---------------------------------------------------------------------------
# Affirmative imperative + enclitic
# ---------------------------------------------------------------------------

# `conjugation_reverse.json` stores moods as Spanish strings ("imperativo",
# "indicativo", ...). The English spelling is accepted too so a future
# regenerated layer cannot silently switch the branch off.
_IMPERATIVE_MOODS = frozenset({"imperativo", "imperative"})
_AFFIRMATIVE_TENSES = frozenset({"afirmativo", "affirmative"})
_MIN_IMPERATIVE_STEM = 3
# Tags that mark a surface as an ordinary content word rather than a verb form.
# On the accent path these veto the decomposition: `escándalo` ("scandal") is
# tagged "noun,verb" and would otherwise strip to `escanda` + `lo`.
_NON_VERB_POS = frozenset({"noun", "adj", "adv", "name", "num", "pron"})


def _imperative_lemma(candidate):
    """Lemma of `candidate` when it is an affirmative imperative form.

    Deliberately mood-restricted: `conjugation_reverse` lists `lleva` as both
    `imperativo/afirmativo/2s` and `indicativo/presente/3s`, and only the first
    reading can host an enclitic. Accepting any finite form would let ordinary
    3s-present nouns-in-disguise through. `tense` must be `afirmativo` too —
    a negative imperative takes *pro*clitics ("no me lo lleves"), never
    enclitics.

    A 2s ("tú") reading wins over the 3s/3p ("usted"/"ustedes") ones when both
    exist, because it is overwhelmingly the commoner host and it breaks
    genuinely ambiguous stems the right way: `cree` is `crear` in the usted
    slot but `creer` in the tú slot, and `créeme` is "believe me".
    """
    _load_verb_evidence()
    if not _conj_reverse:
        return None
    fallback = None
    for analysis in _conj_reverse.get(candidate) or ():
        if not isinstance(analysis, dict):
            continue
        if str(analysis.get("mood", "")).strip().lower() not in _IMPERATIVE_MOODS:
            continue
        if str(analysis.get("tense", "")).strip().lower() not in _AFFIRMATIVE_TENSES:
            continue
        lemma = str(analysis.get("lemma", "")).strip().lower()
        if not lemma:
            continue
        if str(analysis.get("person", "")).strip().lower() == "2s":
            return lemma
        if fallback is None:
            fallback = lemma
    return fallback


def _imperative_host_allowed(word, host):
    """False when `word` is more plausibly an ordinary word than a clitic form.

    The imperative branch is the loosest of the three — its host is a short
    finite form, so plain nouns strip into real verbs: `combate` → `comba`
    (a form of `combar`), `parte` → `par`, `dale` → `da`. Two signals keep them
    out:

    * **Written accent.** An enclitic stack shifts the stress past the
      antepenult, so the host *must* take a written accent that the bare
      imperative does not have: `córtala`, `llévamelo`, `ándale`. That accent is
      positive morphological evidence, strong enough to override a merely
      *non-nominal* ambiguity (`ándale` is tagged "intj,verb"). It is not strong
      enough to override a noun/adjective reading: `escándalo` is "noun,verb"
      and must not become `escanda` + `lo`.
    * **Unambiguous verbhood otherwise.** With no accent to appeal to, the whole
      surface must be tagged exactly "verb" in `spanish_forms`. That rejects
      `combate`/`parte` ("noun,verb"), `arte` ("noun") and `dale`
      ("intj,verb"), and — by requiring a tag at all — every unknown surface.
    """
    _load_verb_evidence()
    wl = word.lower()
    # A surface that is *itself* a conjugated form is that form, not a host
    # plus enclitic: `ganase`/`mandase` are imperfect subjunctives, not
    # `gana`+`se`; `revelo` is 1s of `revelar`, not `reve`+`lo`; `fallaste` is
    # a preterite. `conjugation_reverse` never lists enclitic forms, so this
    # costs the branch nothing real (only genuinely ambiguous surfaces such as
    # `salte`, which is also `saltar`, are conceded to the simpler reading).
    if _conj_reverse and wl in _conj_reverse:
        return False
    pos = str((_verb_pos or {}).get(wl, "") or "").strip().lower()
    tags = {t.strip() for t in pos.split(",") if t.strip()}
    if _strip_acute(host) != host:
        return not (tags & _NON_VERB_POS)
    return tags == {"verb"}


def decompose_imperative_clitic(word, known_words):
    """Decompose an affirmative-imperative+enclitic form into its lemma.

    Returns (lemma, [attached clitics]) or None — the *infinitive*, matching
    `decompose_gerund_clitic` / `decompose_infinitive_clitic`, so every caller
    keeps getting a lemma it can hang a card on. E.g. 'córtala' → ('cortar',
    ['la']), 'llévamelo' → ('llevar', ['me', 'lo']), 'ándale' → ('andar',
    ['le']).

    Tried only after the gerund and infinitive branches fail. The host is the
    accentless remainder after up to two enclitics come off, resolved through
    `conjugation_reverse` and restricted to the imperative mood; see
    `_imperative_host_allowed` for the false-positive guard.
    """
    remaining = word.lower()
    clitics = []
    for _ in range(2):  # max 2 clitics (e.g. llévamelo)
        matched = False
        for pron in _CLITIC_PRONOUNS:
            if (remaining.endswith(pron)
                    and len(remaining) - len(pron) >= _MIN_IMPERATIVE_STEM):
                remaining = remaining[:-len(pron)]
                clitics.insert(0, pron)
                matched = True
                break
        if not matched:
            break
        candidate = _strip_acute(remaining)
        lemma = _imperative_lemma(candidate)
        if not lemma:
            continue
        if not _imperative_host_allowed(word, remaining):
            return None
        return (lemma, list(clitics))
    return None


# ---------------------------------------------------------------------------
# Clitic roles
# ---------------------------------------------------------------------------

def clitic_roles(clitics, reflexive=False, tags=()):
    """Grammatical role of every pronoun in an enclitic cluster.

    Returns a list of ``{"pronoun": str, "role": str}`` parallel to `clitics`,
    where role is one of ``reflexive`` / ``direct`` / ``indirect`` / ``object``
    (``object`` = a lone 1st/2nd-person pronoun whose case the surface form
    does not determine: `verte` is "see you", but nothing in the string says
    accusative rather than dative).

    Roles come from Wiktionary's own tags when the caller passes them, and are
    otherwise derived positionally. Spanish clitic clusters are strictly
    ordered **se > 2nd > 1st > 3rd**, so in a two-pronoun stack the last slot
    is the direct object and everything before it the indirect object —
    `dármelo` is me (indirect) + lo (direct), which is exactly how Wiktionary
    glosses it. This is the fallback used for forms our own
    `decompose_infinitive_clitic` found but Wiktionary has no entry for.
    """
    tagset = set(tags or ())
    n = len(clitics)
    out = []
    for i, cl in enumerate(clitics):
        if cl in _ACCUSATIVE_CLITICS:
            role = "direct"
        elif cl in _DATIVE_CLITICS:
            role = "indirect"
        elif n > 1 and i < n - 1:
            role = "indirect"          # cluster order: non-final slot is IO
        elif cl == "se" or (reflexive and cl in _REFLEXIVE_CLITICS):
            role = "reflexive"
        elif "accusative" in tagset:
            role = "direct"
        elif "dative" in tagset:
            role = "indirect"
        else:
            role = "object"
        out.append({"pronoun": cl, "role": role})
    return out


def is_reflexive_candidate(clitics):
    """True when the cluster *could* be reflexive: one agreeing pronoun only.

    A second object pronoun rules it out — `dármelo` has me as a dative object
    alongside accusative lo, so it belongs to `dar`, never to `darse`.
    """
    return len(clitics) == 1 and clitics[0] in _REFLEXIVE_CLITICS


# ---------------------------------------------------------------------------
# SpanishDict parent inventory
# ---------------------------------------------------------------------------

_SD_PARENTS_CACHE = {}


def load_spanishdict_parents(sd_dir=None):
    """Every lemma SpanishDict publishes a dictionary entry for.

    Returns ``{headword: sense_count}``. This is the *parent inventory*: a
    clitic form only gets a `-se` parent card when SpanishDict actually has a
    `-se` headword, so `alejar` and `alejarse` are two parents while a verb
    SpanishDict only lists plainly stays one. Reads the committed caches
    (`headword_cache.json`, `surface_cache.json`) — never scrapes.

    Headwords reached from a *different* query surface are vetted with
    `util_5c_spanishdict.is_plausible_headword`, the live fuzzy-headword guard,
    so a bad SpanishDict redirect cannot invent a parent. Keys of
    `headword_cache.json` are SpanishDict's own entry names and are trusted
    directly. Missing caches → empty dict, and every caller falls back to its
    previous behaviour.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sd_dir = sd_dir or os.path.join(root, "Data", "Spanish", "Senses", "spanishdict")
    if sd_dir in _SD_PARENTS_CACHE:
        return _SD_PARENTS_CACHE[sd_dir]

    try:
        import sys
        if os.path.join(root, "pipeline") not in sys.path:
            sys.path.insert(0, os.path.join(root, "pipeline"))
        from util_5c_spanishdict import is_plausible_headword
    except Exception:
        is_plausible_headword = None

    parents = {}

    def _absorb(query, payload, trust):
        for analysis in payload.get("dictionary_analyses") or []:
            hw = (analysis.get("headword") or "").strip().lower()
            if not hw:
                continue
            if not trust and hw != query and is_plausible_headword is not None:
                if not is_plausible_headword(query, hw):
                    continue
            count = len(analysis.get("senses") or [])
            if count >= parents.get(hw, -1):
                parents[hw] = count

    for filename, trust in (("headword_cache.json", True),
                            ("surface_cache.json", False)):
        path = os.path.join(sd_dir, filename)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for query, payload in data.items():
            if isinstance(payload, dict):
                _absorb((query or "").strip().lower(), payload, trust)

    _SD_PARENTS_CACHE[sd_dir] = parents
    return parents


def prefers_reflexive_parent(base, sd_parents):
    """Should an ambiguous infinitive/gerund enclitic take the `-se` parent?

    `alejarme` and `verte` are morphologically identical — infinitive + a lone
    person-agreeing pronoun — and no signal in either string says whether the
    pronoun is the subject reflexivised (`alejarse`, "to move away") or a plain
    object (`ver` + te, "to see you"). Person agreement, which settles the
    imperative cases, needs a subject an infinitive does not have.

    So SpanishDict breaks the tie with its own entry structure: the pronominal
    entry wins only when it is *richer* than the plain one. SpanishDict gives
    alejar 3 senses and alejarse 5 (pronominal is the main reading → promote),
    but ver 24 and verse 6, decir 16 and decirse 3, dar 38 and darse 9
    (pronominal is a minor sub-entry → keep the plain parent). Strictly
    greater, so a 1-vs-1 tie like amar/amarse stays plain.

    Returns False when SpanishDict has no `-se` headword at all.
    """
    if not sd_parents:
        return False
    reflexive = base + "se"
    if reflexive not in sd_parents:
        return False
    return sd_parents[reflexive] > sd_parents.get(base, 0)


def reflexive_parent(base, clitics, sd_parents, decided=None, known_lemmas=None):
    """The lemma a clitic form should hang under: `base` or `base + "se"`.

    `decided` is the caller's person-agreement verdict for hosts where it can
    be computed (True = the pronoun must be reflexive, False = it must be an
    object, None = undecidable, i.e. an infinitive or gerund). `se` is always
    reflexive.

    A *decided* reflexive takes the `-se` parent whenever SpanishDict or
    `known_lemmas` knows it; the SpanishDict cache only covers surfaces we have
    queried, so gating it on SpanishDict alone would demote forms that already
    resolve correctly. An *undecidable* host is the one case where a guess is
    silently wrong either way, so only SpanishDict may promote it, and only
    when its pronominal entry outweighs the plain one.
    """
    if not is_reflexive_candidate(clitics):
        return base
    reflexive = base + "se"
    if decided is True or clitics[0] == "se":
        if reflexive in (sd_parents or ()) or reflexive in (known_lemmas or ()):
            return reflexive
        return base
    if decided is False:
        return base
    return reflexive if prefers_reflexive_parent(base, sd_parents) else base


# ---------------------------------------------------------------------------
# Wiktionary clitic-data loader
# ---------------------------------------------------------------------------

_SUBJECT_PERSON_TAGS = {"first-person": "1", "second-person": "2",
                        "third-person": "3"}
_OBJECT_PERSON_TAGS = {"object-first-person": "1", "object-second-person": "2",
                       "object-third-person": "3"}
# Hosts whose subject person the form itself does not express.
_UNDECIDABLE_HOSTS = frozenset({"infinitive", "gerund", "participle"})


def _person_agreement(tags, clitics):
    """True/False/None: does the lone pronoun agree with the stated subject?

    Wiktionary spells out both sides for finite forms — `perdóname` is
    `second-person singular imperative` with `object-first-person
    object-singular`, so subject 2s vs object 1s: the pronoun is an object, and
    `perdonarse` would be wrong. `múdate` is 2s/2s and must be reflexive.
    Infinitives and gerunds carry no subject, so the question is undecidable
    and the caller falls back to the SpanishDict tie-break.
    """
    if not is_reflexive_candidate(clitics):
        return False
    if clitics[0] == "se":
        return True
    if tags & _UNDECIDABLE_HOSTS:
        return None
    subject = next((v for t, v in _SUBJECT_PERSON_TAGS.items() if t in tags), None)
    if subject is None:
        return None
    number = "p" if "plural" in tags else "s" if "singular" in tags else None
    obj = next((v for t, v in _OBJECT_PERSON_TAGS.items() if t in tags), None)
    obj_number = ("p" if "object-plural" in tags
                  else "s" if "object-singular" in tags else None)
    if obj is None:
        want = CLITIC_PERSON.get(clitics[0])
        if not want:
            return False
        obj, obj_number = want[0], want[1]
    if number is None or obj_number is None:
        return subject == obj
    return (subject, number) == (obj, obj_number)


def load_wiktionary_clitic_data(path):
    """Load clitic map + reflexive verbs + propn set from Wiktionary JSONL.

    Returns (word_set, all_propn, clitic_map, verbs_with_refl_senses):
      word_set: all lowercase word forms that have any entry.
      all_propn: words where EVERY entry has pos="name" (proper nouns).
      clitic_map: {clitic_word: info} for form-of entries with clitic pronouns
                  ("combined with"), where info is a dict:
                    base      — the verb the form belongs to
                    clitics   — attached pronouns, in surface order
                    roles     — [{"pronoun", "role"}] parallel to `clitics`
                    reflexive — True / False / None (None = undecidable host)
                    tags      — the raw Wiktionary tags, kept for debugging
      verbs_with_refl_senses: base verbs with non-form-of senses tagged
                              'reflexive' or 'pronominal'.

    `reflexive` is deliberately three-valued. The old code collapsed it to
    ``"reflexive" in tags or "se" in clitics``, which is a literal-`se` test:
    Spanish reflexives agree in person, so `alejarme` (me = 1s reflexive) came
    out False and merged onto the plain transitive `alejar`. Person agreement
    now decides wherever Wiktionary states the subject, and `None` marks the
    infinitive/gerund cases the string genuinely cannot settle.
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
                                       if isinstance(l, list)
                                       and l[0].lower() in _CLITIC_PRONOUNS]
                            if not base or base == wl or not clitics:
                                continue
                            if "reflexive" in tags:
                                is_refl = True
                            else:
                                is_refl = _person_agreement(tags, clitics)
                            clitic_map[wl] = {
                                "base": base,
                                "clitics": clitics,
                                "roles": clitic_roles(
                                    clitics, reflexive=bool(is_refl), tags=tags),
                                "reflexive": is_refl,
                                "tags": sorted(tags),
                            }

    words = set(word_poses.keys())
    all_propn = {w for w, poses in word_poses.items()
                 if poses and poses <= {"name"}}
    return words, all_propn, clitic_map, verbs_with_refl


# ---------------------------------------------------------------------------
# Three-tier clitic classification
# ---------------------------------------------------------------------------

def classify_clitics(words, clitic_map, verbs_with_refl, known_for_gerund,
                     sd_parents=None):
    """Build clitic_merge / clitic_orphans / clitic_keep / clitic_info.

    Args:
        words: set of lowercase surface forms to classify.
        clitic_map: from `load_wiktionary_clitic_data`.
        verbs_with_refl: from `load_wiktionary_clitic_data`. No longer gates
                    tier 3 — SpanishDict's parent inventory does — but kept in
                    the signature because callers report it.
        known_for_gerund: set of known Spanish forms used to validate
                          gerund-decomposition candidates (usually
                          `words | conj_forms | wikt_words`).
        sd_parents: from `load_spanishdict_parents`. Decides which lemmas may
                    own a card. Omit (or pass an empty dict) and the `-se`
                    promotion is disabled entirely — the pre-SpanishDict
                    behaviour, minus the literal-`se` misfiling.

    Returns (clitic_merge, clitic_orphans, clitic_keep, gerund_added, clitic_info):
      clitic_merge: {word: base_form}  (tier 1+2)
      clitic_orphans: [word]  (subset of clitic_merge mapped to a synthetic infinitive)
      clitic_keep: set[word]  (tier 3 — the form keeps its own card)
      gerund_added: int (count of programmatic gerund+clitic detections)
      clitic_info: {word: {parent, clitics, roles, reflexive, source}} — the
                   pronoun/role annotation, preserved for the deck so the front
                   end can keep describing each form.

    A form is kept as its own card (tier 3) when it routes to a `-se` parent
    SpanishDict publishes and the base has a Wiktionary reflexive sense. That
    replaces the old literal-`se` gate, under which `irse`/`ponerse` were kept
    but `alejarme`/`alejarte` silently merged into the plain transitive verb.
    """
    clitic_merge = {}
    clitic_orphans = []
    clitic_keep = set()
    clitic_info = {}

    def _place(w, base_inf, clitics, roles, is_refl, source):
        parent = reflexive_parent(base_inf, clitics, sd_parents, decided=is_refl,
                                  known_lemmas=known_for_gerund)
        reflexive = parent.endswith("se") and parent != base_inf
        if reflexive:
            roles = clitic_roles(clitics, reflexive=True)
        clitic_info[w] = {
            "parent": parent,
            "base": base_inf,
            "clitics": list(clitics),
            "roles": roles,
            "reflexive": reflexive,
            "source": source,
        }
        if reflexive:
            # Routed to a `-se` parent, so it is a pronominal use and belongs on
            # its own card rather than folded into the plain transitive verb.
            # The old gate was `is_refl and base_inf in verbs_with_refl`, with
            # `is_refl` meaning "the literal string 'se' is attached" — which
            # kept `irse`/`ponerse` but merged `alejarme` into `alejar`.
            clitic_keep.add(w)
            return
        stripped = strip_clitic_pronouns(w, clitics)
        if stripped in words:
            clitic_merge[w] = stripped
        elif parent in words:
            clitic_merge[w] = parent
        else:
            clitic_merge[w] = parent
            clitic_orphans.append(w)

    # Wiktionary-listed clitic forms (tier 1/2/3)
    for w in words:
        info = clitic_map.get(w)
        if not info:
            continue
        _place(w, info["base"], info["clitics"], info["roles"],
               info["reflexive"], "wiktionary")

    # Programmatic gerund+clitic detection (catches forms not in Wiktionary).
    # No Wiktionary entry means no tags, so roles are derived positionally and
    # person agreement is unknown — exactly the undecidable case.
    gerund_added = 0
    for w in words:
        if w in clitic_merge or w in clitic_keep:
            continue
        result = decompose_gerund_clitic(w, known_for_gerund)
        if not result:
            continue
        base_inf, clitics = result
        is_refl = True if clitics == ["se"] else None
        _place(w, base_inf, clitics, clitic_roles(clitics, reflexive=bool(is_refl)),
               is_refl, "decomposed")
        gerund_added += 1

    return clitic_merge, clitic_orphans, clitic_keep, gerund_added, clitic_info


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
