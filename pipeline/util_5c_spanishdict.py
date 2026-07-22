#!/usr/bin/env python3
"""Shared SpanishDict extraction helpers."""

import json
import re
import threading
import time
import unicodedata
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import requests


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LAYERS_DIR = _PROJECT_ROOT / "Data" / "Spanish" / "layers"
SPANISH_FORMS_PATH = _LAYERS_DIR / "spanish_forms.json"
CONJ_REVERSE_PATH = _LAYERS_DIR / "conjugation_reverse.json"

SPANISH_SENSES_DIR = Path(__file__).resolve().parents[1] / "Data" / "Spanish" / "Senses"
SPANISHDICT_DIR = SPANISH_SENSES_DIR / "spanishdict"
SPANISHDICT_SURFACE_CACHE = SPANISHDICT_DIR / "surface_cache.json"
SPANISHDICT_HEADWORD_CACHE = SPANISHDICT_DIR / "headword_cache.json"
SPANISHDICT_REDIRECTS = SPANISHDICT_DIR / "redirects.json"
SPANISHDICT_STATUS = SPANISHDICT_DIR / "status.json"
SPANISHDICT_PHRASES_CACHE = SPANISHDICT_DIR / "phrases_cache.json"
SPANISHDICT_THESAURUS_CACHE = SPANISHDICT_DIR / "thesaurus_cache.json"
REQUEST_DELAY_SECONDS = 0.35

_request_lock = threading.Lock()
_last_request_at = 0.0

_POS_MAP = {
    "noun": "NOUN",
    "plural noun": "NOUN",
    "proper noun": "PROPN",
    "verb": "VERB",
    "adjective": "ADJ",
    "adverb": "ADV",
    "pronoun": "PRON",
    "determiner": "DET",
    "article": "DET",
    "definite article": "DET",
    "indefinite article": "DET",
    "interjection": "INTJ",
    "preposition": "ADP",
    "conjunction": "CCONJ",
    "coordinating conjunction": "CCONJ",
    "subordinating conjunction": "CCONJ",
    "number": "NUM",
    "numeral": "NUM",
    "particle": "PART",
    "contraction": "CONTRACTION",
    "phrase": "PHRASE",
    "abbreviation": "NOUN",
    "symbol": "NOUN",
    "unit": "NOUN",
    "letter": "NOUN",
    "letter name": "NOUN",
}


def normalize_pos(part):
    part = (part or "").strip().lower()
    if part in _POS_MAP:
        return _POS_MAP[part]
    if "noun" in part:
        return "NOUN"
    if "verb" in part:
        return "VERB"
    if "adjective" in part:
        return "ADJ"
    if "adverb" in part:
        return "ADV"
    if "pronoun" in part:
        return "PRON"
    if "article" in part or "determiner" in part:
        return "DET"
    if "interjection" in part:
        return "INTJ"
    if "preposition" in part:
        return "ADP"
    if "conjunction" in part:
        return "CCONJ"
    if "proper noun" in part:
        return "PROPN"
    if "number" in part or "numeral" in part:
        return "NUM"
    if "particle" in part:
        return "PART"
    if "contraction" in part:
        return "CONTRACTION"
    if "abbreviation" in part or "symbol" in part or "unit" in part:
        return "NOUN"
    if "letter" in part:
        return "NOUN"
    return "X"


def load_json(path, default):
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


# ---------------------------------------------------------------------------
# Menu assembly — previously lived in pipeline/artist/tool_5c_build_spanishdict_menu.py.
# Moved here so both normal-mode step_5c_build_senses.py and the artist flow share
# one implementation.
# ---------------------------------------------------------------------------

def normalize_cached_analyses(analyses):
    """Coerce SpanishDict cache analysis blocks into {headword, senses:[...]} dicts."""
    out = []
    for analysis in analyses or []:
        senses = analysis.get("senses") or []
        if isinstance(senses, dict):
            senses = list(senses.values())
        out.append({
            "headword": analysis.get("headword"),
            "senses": [deepcopy(s) for s in senses if isinstance(s, dict)],
        })
    return out


def analysis_signature(analysis):
    """Canonical signature of an analysis for dedup (headword + sorted sense triples)."""
    senses = analysis.get("senses") or []
    if isinstance(senses, dict):
        senses = senses.values()
    normalized = []
    for sense in senses:
        normalized.append((
            sense.get("pos", ""),
            sense.get("translation", ""),
            sense.get("context", ""),
        ))
    normalized.sort()
    return (
        analysis.get("headword"),
        tuple(normalized),
    )


def _is_abbreviation_mismatch(surface, headword):
    """True when SpanishDict's fuzzy match returned an abbreviation.

    Our corpus queries are letters only (WORD_RE in step_2a strips
    punctuation except apostrophes). If the returned headword contains
    periods (`p.a.`, `e.g.`, `m.n.`, …) but the surface query doesn't,
    SpanishDict's fuzzy-match has substituted an abbreviation for a
    real word — e.g. `pa'` (elision of `para`) returned `p.a.` ("per
    annum"), which then produced a bogus "dad" / "yearly" card. Filter
    those matches out.
    """
    if not headword:
        return False
    if "." in (surface or ""):
        return False  # caller genuinely queried an abbreviation — allow
    return "." in headword


def is_phrase_only_analysis(analysis):
    """True when every sense in the analysis is tagged ``pos: 'PHRASE'``.

    SpanishDict tags phrasebook glosses (single-translation idiomatic
    lines such as "he's" / "she's" / "it's" for the surface ``está``)
    with ``pos: 'PHRASE'``, distinct from the lexical POS tags
    (``NOUN``, ``VERB``, ``ADJ``, …) that real lemma entries carry. An
    analysis whose senses are *all* PHRASE is, by SD's own taxonomy,
    not asserting lemma status — it's just supplying a translation
    gloss for the surface as a phrase.

    Used by :func:`build_menu_analyses` to suppress spurious self-
    headword analyses (``está→está``, ``estoy→estoy``, ``pongan→pongan``,
    …) when SD also offers a real morphological pointer (``estar``,
    ``estar``, ``poner``, …) via ``possible_results``.

    The corresponding *lexicalised* exception is ``hay``: its self-
    headword senses are tagged ``pos: 'VERB'`` ("there is", "there
    are"), so this returns ``False`` and the self-headword survives —
    which is the intended behaviour, since SD genuinely treats ``hay``
    as its own dictionary entry.
    """
    senses = analysis.get("senses") or []
    if isinstance(senses, dict):
        senses = list(senses.values())
    real_senses = [s for s in senses if isinstance(s, dict)]
    if not real_senses:
        return False
    return all((s.get("pos") or "").strip().upper() == "PHRASE" for s in real_senses)


# ---------------------------------------------------------------------------
# Headword plausibility guard.
#
# SpanishDict's surface→headword resolver fuzzy-matches unknown slang to
# whichever dictionary headword is closest by edit distance, and it happily
# crosses into its English dictionary. Uncaught, these become a card's lemma
# plus a reverse-direction (English-headword) gloss:
#
#   perse   → purse   (English)   revol → revolt (English)   lary → lazy (EN)
#   tranquilita → tranquility (EN)   cel → cal   totito → torito   (wrong ES)
#
# The guard rejects an analysis whose ``headword`` is not a plausible
# lexical/morphological relative of the queried ``surface``. A rejected
# analysis is quarantined out of the menu; if a surface loses *all* of its
# analyses it drops out of the sense menu entirely, which is exactly how the
# pipeline already represents "no usable menu" — step_5c counts it as
# ``unmatched`` and step_6c later routes it to gap-fill / sense_discovery
# (an invented sense keyed on the surface), instead of carrying the bogus
# headword forward as the lemma. See docs/design/artist_pipeline_quality_audit.md
# stage-4 F1/F3 and stage-6 F0/F3.
# ---------------------------------------------------------------------------

# Minimum shared (deaccented) leading characters for the secondary prefix
# check. 3 rejects cel/cal (share "c") and totito/torito (share "to") while
# keeping normal plurals/gender forms (canciones/canción, buena/bueno).
_MIN_PREFIX = 3

_spanish_forms_deac = None       # set of deaccented known Spanish surface forms
_conj_reverse_deac = None        # {deaccented form: set(deaccented lemma)}
_guard_data_loaded = False       # False until a load attempt succeeds


def _deaccent(text):
    """Lowercase and strip combining accents (NFD → drop Mn)."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _load_guard_data(spanish_forms_path=None, conj_reverse_path=None):
    """Lazily load the inflection lookups the guard needs (once per process).

    Builds two module-level caches from the large canonical layer files:

    * ``_spanish_forms_deac`` — the set of every known Spanish surface form,
      deaccented, used to answer "is this headword a real Spanish word at
      all?" (the perse→purse / revol→revolt English-intrusion signal).
    * ``_conj_reverse_deac`` — ``{form: {lemma, ...}}`` from verbecc's reverse
      conjugation table, used to answer "is this surface a known conjugation
      of this headword?" as a backstop to SpanishDict's own conjugation flag.

    Fail-open: if the files can't be read the guard is disabled (keeps every
    analysis) rather than risk over-quarantining a real deck.
    """
    global _spanish_forms_deac, _conj_reverse_deac, _guard_data_loaded
    if _guard_data_loaded:
        return
    forms_path = Path(spanish_forms_path) if spanish_forms_path else SPANISH_FORMS_PATH
    conj_path = Path(conj_reverse_path) if conj_reverse_path else CONJ_REVERSE_PATH

    forms_deac = set()
    conj_deac = {}
    try:
        with open(forms_path, "r", encoding="utf-8") as f:
            for form in json.load(f).keys():
                forms_deac.add(_deaccent(form))
    except (OSError, ValueError):
        # Fail-open: leave guard disabled if the canonical forms file is
        # unreadable, so we never silently gut a menu on missing data.
        _spanish_forms_deac = None
        _conj_reverse_deac = None
        _guard_data_loaded = True
        return

    try:
        with open(conj_path, "r", encoding="utf-8") as f:
            for form, entries in json.load(f).items():
                lemmas = {
                    _deaccent(e.get("lemma"))
                    for e in (entries or [])
                    if isinstance(e, dict) and e.get("lemma")
                }
                if lemmas:
                    conj_deac.setdefault(_deaccent(form), set()).update(lemmas)
    except (OSError, ValueError):
        conj_deac = {}  # conjugation backstop optional; forms set is enough

    _spanish_forms_deac = forms_deac
    _conj_reverse_deac = conj_deac
    _guard_data_loaded = True


def _common_prefix_len(a, b):
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _surface_conjugation_lemmas(possible_results):
    """Deaccented lemma set that SpanishDict flags this surface as a
    conjugation/inflection of (from ``possible_results`` heuristics)."""
    lemmas = set()
    for result in possible_results or []:
        if not isinstance(result, dict):
            continue
        if (result.get("heuristic") or "").strip().lower() not in {"conjugation", "inflection"}:
            continue
        hw = (result.get("headword") or "").strip()
        if hw:
            lemmas.add(_deaccent(hw))
    return lemmas


def is_plausible_headword(surface, headword, surface_relation="", conj_lemmas=None):
    """True when ``headword`` is a plausible lemma for the queried ``surface``.

    Trusts, in order (any one keeps the analysis):

    1. **Self-headword** — deaccented surface == headword (canción→canción,
       gato→gato). SpanishDict's own dictionary entry for the word.
    2. **SpanishDict conjugation/inflection flag** — the analysis is a
       redirect SD itself tagged ``conjugation``/``inflection``
       (``surface_relation``), or the headword matches a conjugation pointer
       in ``conj_lemmas`` (incl. reflexive extensions: vuelvo→volver keeps
       volver *and* volverse). This is why legit stem-changing conjugations
       survive despite sharing little prefix — per the task, we trust SD's
       morphology and never reject a conjugation-marked analysis.
    3. **Reverse conjugation table** — verbecc lists ``surface`` as a form of
       ``headword`` (backstop for legacy cache entries with no SD pointer).
    4. **Real Spanish word + shared prefix** — the headword is a known
       Spanish form AND shares ``_MIN_PREFIX`` deaccented leading chars with
       the surface. The Spanish-word gate is what rejects revol→revolt (revol
       *is* a prefix of revolt, but revolt is English), while the prefix gate
       rejects cel→cal and totito→torito (Spanish headwords, no real relation).

    Fail-open: if the guard data never loaded, returns True (keep everything).
    """
    _load_guard_data()
    if _spanish_forms_deac is None:
        return True  # guard disabled — data unavailable

    headword = (headword or "").strip()
    if not headword:
        return True  # empty headword: nothing to vet; leave to other filters

    s = _deaccent(surface)
    h = _deaccent(headword)

    # 1. Self-headword.
    if s == h:
        return True

    # 2. SpanishDict-asserted conjugation / inflection — trusted outright.
    if (surface_relation or "").strip().lower() in {"conjugation", "inflection"}:
        return True
    for lemma in (conj_lemmas or ()):
        # exact, or reflexive/pronominal extension either direction
        # (volver ↔ volverse), so SD's pointer vouches for both entries.
        if h == lemma or h.startswith(lemma) or lemma.startswith(h):
            return True

    # 3. Reverse conjugation table backstop.
    if h in (_conj_reverse_deac.get(s) or ()):
        return True

    # 3b. Spanish z→ces orthographic plural (luz→luces, voz→voces, pez→peces,
    # vez→veces). These share only a 2-char prefix so the prefix check below
    # would wrongly reject them; the alternation is a fixed, unambiguous rule.
    # SpanishDict usually flags them with an ``inflection`` pointer (caught by
    # #2), but legacy cache entries without one land here.
    if h.endswith("z") and s == h[:-1] + "ces":
        return True

    # 4. Real Spanish word AND a meaningful shared prefix.
    if h in _spanish_forms_deac:
        threshold = min(_MIN_PREFIX, len(s), len(h))
        if threshold and _common_prefix_len(s, h) >= threshold:
            return True

    return False


def build_menu_analyses(surface, surface_cache, headword_cache, include_redirects=True,
                        quarantine=None):
    """Build the analyses list for one surface word from the shared SpanishDict cache.

    Starts from the surface page's own dictionary_analyses, then optionally extends
    with headword redirects ("possible_results") — dedup'd by signature.

    Abbreviation-style headwords (`p.a.`, `e.g.`, …) are filtered out when the
    surface query itself has no dots — see ``_is_abbreviation_mismatch``.

    Spurious self-headword PHRASE-only analyses are filtered out when SD also
    flagged this surface as a ``heuristic: "conjugation"`` of a real verb — see
    :func:`is_phrase_only_analysis`. The classic case is ``está``: SD lists a
    self-headword whose 10 senses are all ``pos: 'PHRASE'`` (phrasebook glosses
    "he's" / "she's" / "it's"), plus a conjugation pointer to ``estar``. We
    drop the self-headword and keep the ``estar`` analysis, so the resulting
    sense menu, sense assignment, lemma map, and master vocabulary all use
    ``estar`` — the same lemma normal mode picks via the frequency CSV. The
    filter only fires when a non-self conjugation analysis is available, so it
    can never empty an otherwise-populated menu.

    Finally, each analysis is run through :func:`is_plausible_headword`. SD's
    fuzzy matcher resolves unknown slang to implausible headwords (perse→purse,
    revol→revolt, cel→cal, totito→torito); those analyses are quarantined out
    so the bogus headword never becomes the card's lemma. When ``quarantine``
    is a list, each rejected analysis is appended as ``{surface, headword,
    reason}`` for provenance; otherwise it is simply dropped. If a surface
    loses *all* analyses this way it falls out of the menu entirely — the same
    "no usable menu" state that routes the word to gap-fill / sense_discovery.
    """
    surface_entry = surface_cache.get(surface) or {}
    analyses = [
        a for a in normalize_cached_analyses(surface_entry.get("dictionary_analyses") or [])
        if not _is_abbreviation_mismatch(surface, a.get("headword"))
    ]
    seen_headwords = {a.get("headword") for a in analyses if a.get("headword")}
    seen_signatures = {analysis_signature(a) for a in analyses}

    if include_redirects:
        for result in surface_entry.get("possible_results") or []:
            headword = (result.get("headword") or "").strip()
            if not headword or headword in seen_headwords:
                continue
            if _is_abbreviation_mismatch(surface, headword):
                continue
            headword_entry = headword_cache.get(headword) or {}
            headword_analyses = normalize_cached_analyses(headword_entry.get("dictionary_analyses") or [])
            for analysis in headword_analyses:
                if not analysis.get("headword"):
                    analysis["headword"] = headword
                analysis["surface_relation"] = result.get("heuristic", "")
                analysis["surface_from"] = surface
                sig = analysis_signature(analysis)
                if sig in seen_signatures:
                    continue
                analyses.append(analysis)
                seen_headwords.add(analysis.get("headword"))
                seen_signatures.add(sig)

    # Drop spurious self-headword PHRASE-only analyses when SD itself offers a
    # real morphological alternative. See :func:`is_phrase_only_analysis` for
    # the rationale and the ``hay`` carve-out (which has VERB senses, not
    # PHRASE-only, so the filter doesn't fire).
    has_conjugation_alternative = any(
        a.get("surface_relation") == "conjugation"
        and (a.get("headword") or "").strip().lower() != surface.lower()
        for a in analyses
    )
    if has_conjugation_alternative:
        analyses = [
            a for a in analyses
            if not (
                (a.get("headword") or "").strip().lower() == surface.lower()
                and is_phrase_only_analysis(a)
            )
        ]

    # Plausibility guard: quarantine analyses whose headword is an implausible
    # fuzzy match for the surface (English intrusions + wrong-Spanish fuzz).
    # SD's own conjugation pointers vouch for legit stem-changing paradigms.
    conj_lemmas = _surface_conjugation_lemmas(surface_entry.get("possible_results"))
    kept = []
    for a in analyses:
        if is_plausible_headword(
            surface, a.get("headword"),
            surface_relation=a.get("surface_relation", ""),
            conj_lemmas=conj_lemmas,
        ):
            kept.append(a)
        elif quarantine is not None:
            quarantine.append({
                "surface": surface,
                "headword": (a.get("headword") or "").strip(),
                "reason": "implausible_fuzzy_headword",
            })
    analyses = kept

    return analyses


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def build_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Fluency SpanishDict cache builder/1.0",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def throttle_request():
    global _last_request_at
    with _request_lock:
        now = time.time()
        wait = REQUEST_DELAY_SECONDS - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def extract_component_data(html):
    match = re.search(r"SD_COMPONENT_DATA\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        raise ValueError("Cannot find SD_COMPONENT_DATA in SpanishDict HTML")
    return json.loads(match.group(1))


def fetch_spanishdict_component(session, word):
    # ``?langFrom=es`` forces Spanish-source mode. Without it,
    # SpanishDict guesses the direction from the surface word and picks
    # English-source for words like "has" / "dice" — handing us a
    # backwards entry (headword is the English word, translations are
    # Spanish). This scraper is Spanish-only, so forcing the direction
    # is always the correct behaviour.
    url = "https://www.spanishdict.com/translate/%s?langFrom=es" % quote(word)
    last_exc = None
    for attempt in range(5):
        try:
            throttle_request()
            response = session.get(url, timeout=20)
            response.raise_for_status()
            return extract_component_data(response.text)
        except requests.HTTPError as exc:
            last_exc = exc
            code = getattr(exc.response, "status_code", None)
            if code in (429, 503):
                retry_after = getattr(exc.response, "headers", {}).get("Retry-After")
                try:
                    wait = min(int(retry_after), 60) if retry_after else min(5 * (2 ** attempt), 60)
                except ValueError:
                    wait = min(5 * (2 ** attempt), 60)
                time.sleep(wait)
                continue
            raise
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(min(3 * (2 ** attempt), 30))
    raise last_exc


def fetch_spanishdict_thesaurus(session, word):
    """Fetch SpanishDict's per-word thesaurus page and return SD_COMPONENT_DATA.

    The page is at ``/thesaurus/<word>`` and is Spanish-only, so we don't
    need ``?langFrom=es`` here. The redux blob lives under the same
    ``SD_COMPONENT_DATA`` marker as the dictionary page; ``thesaurusProps``
    holds the headword id, linked words, senses, and senseLinks (the
    relationship graph). Returns ``None`` when the page has no thesaurus
    data — SD serves a generic "no results" page for those, with
    ``thesaurusProps`` either missing or empty.
    """
    url = "https://www.spanishdict.com/thesaurus/%s" % quote(word)
    last_exc = None
    for attempt in range(5):
        try:
            throttle_request()
            response = session.get(url, timeout=20)
            response.raise_for_status()
            return extract_component_data(response.text)
        except requests.HTTPError as exc:
            last_exc = exc
            code = getattr(exc.response, "status_code", None)
            if code == 404:
                return None
            if code in (429, 503):
                retry_after = getattr(exc.response, "headers", {}).get("Retry-After")
                try:
                    wait = min(int(retry_after), 60) if retry_after else min(5 * (2 ** attempt), 60)
                except ValueError:
                    wait = min(5 * (2 ** attempt), 60)
                time.sleep(wait)
                continue
            raise
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(min(3 * (2 ** attempt), 30))
    raise last_exc


def extract_thesaurus_payload(component):
    """Strip ``thesaurusProps`` to the fields the layer builder uses.

    The raw payload includes editor-only fields (``senseEditHost``) and
    fields the builder doesn't need (``examples``, ``translations``).
    Cache only the join inputs so the on-disk file stays small.
    Returns ``None`` when the page has no usable thesaurus content.
    """
    if not isinstance(component, dict):
        return None
    tp = component.get("thesaurusProps") or {}
    headword = tp.get("headword") or {}
    sense_links = tp.get("senseLinks") or []
    senses = tp.get("senses") or []
    linked_words = tp.get("linkedWords") or []
    if not headword or not sense_links or not senses:
        return None
    return {
        "headword": {"id": headword.get("id"), "source": headword.get("source")},
        "senses": [
            {
                "id": s.get("id"),
                "wordId": s.get("wordId"),
                "partOfSpeechId": s.get("partOfSpeechId"),
                "contextEn": s.get("contextEn") or "",
                "contextEs": s.get("contextEs") or "",
            }
            for s in senses
        ],
        "linkedWords": [
            {"id": w.get("id"), "source": w.get("source")}
            for w in linked_words
        ],
        "senseLinks": [
            {
                "relationship": link.get("relationship"),
                "senseLinkA": link.get("senseLinkA"),
                "senseLinkB": link.get("senseLinkB"),
            }
            for link in sense_links
        ],
    }


def extract_translation_rows(component):
    props = component.get("sdDictionaryResultsProps") or {}
    entry = props.get("entry") or {}
    neodict = entry.get("neodict") or []
    entry_lang = props.get("entryLang") or entry.get("entryLang") or "es"

    rows = []
    for nd in neodict:
        for pos_group in nd.get("posGroups") or []:
            for sense in pos_group.get("senses") or []:
                part = ((sense.get("partOfSpeech") or {}).get("nameEn")) or ""
                for translation in sense.get("translations") or []:
                    examples = []
                    for example in translation.get("examples") or []:
                        if entry_lang == "es":
                            examples.append({
                                "original": example.get("textEs", ""),
                                "translated": example.get("textEn", ""),
                            })
                        else:
                            examples.append({
                                "original": example.get("textEn", ""),
                                "translated": example.get("textEs", ""),
                            })
                    rows.append({
                        "headword": (sense.get("subheadword") or "").strip() or "",
                        "translation": (translation.get("translation") or "").strip(),
                        "part": part,
                        "context": (sense.get("context") or "").strip(),
                        "regions": [
                            region.get("nameEn", "")
                            for region in (sense.get("regions") or []) + (translation.get("regions") or [])
                            if region.get("nameEn")
                        ],
                        "examples": examples,
                    })
    return rows


def extract_possible_results(component):
    out = []
    for item in component.get("dictionaryPossibleResults") or []:
        heuristic = (item.get("resultHeuristic") or "").strip()
        word_source = (item.get("wordSource") or "").strip()
        result = (item.get("result") or "").strip()
        if heuristic in {"conjugation", "inflection"} and word_source:
            headword = word_source
        else:
            headword = result or word_source
        if not headword:
            continue
        part = item.get("partOfSpeech") or {}
        pos_name = ""
        if isinstance(part, dict):
            pos_name = part.get("nameEn", "") or part.get("nameEs", "")
        pos = normalize_pos(pos_name)
        if pos == "X" and heuristic in {"conjugation", "inflection"}:
            pos = "VERB"
        out.append({
            "headword": headword,
            "word_source": word_source,
            "result": result,
            "heuristic": heuristic,
            "inflection_type": (item.get("inflectionType") or "").strip(),
            "translation": (item.get("translation1") or "").strip(),
            "pos": pos,
        })
    return out


def should_keep_possible_result(surface, result):
    headword = (result.get("headword") or "").strip()
    written_form = (result.get("result") or "").strip()
    if not headword:
        return False
    if written_form != surface:
        return False
    if "." in headword:
        return False
    if len(headword) > 1 and headword.isupper():
        return False
    return True


def infer_analysis_order(surface, analyses, possible_results):
    order_hint = []
    seen = set()
    for item in possible_results:
        headword = (item.get("headword") or "").strip()
        if headword and headword not in seen:
            seen.add(headword)
            order_hint.append(headword)
    if surface not in seen:
        order_hint.insert(0, surface)

    rank = {headword: i for i, headword in enumerate(order_hint)}
    return sorted(
        analyses,
        key=lambda a: (
            rank.get(a.get("headword", ""), 10 ** 6),
            a.get("headword", "") != surface,
            -len(a.get("senses", [])),
            a.get("headword", ""),
        ),
    )


def build_dictionary_analyses(surface, rows, possible_results):
    grouped = defaultdict(list)
    seen = defaultdict(set)

    for row in rows:
        headword = row.get("headword") or surface
        sense = {
            "pos": normalize_pos(row.get("part")),
            "translation": row.get("translation") or "",
            "source": "spanishdict",
            "headword": headword,
        }
        if row.get("context"):
            sense["context"] = row["context"]
        if row.get("examples"):
            sense["examples"] = deepcopy(row["examples"][:2])
        if row.get("regions"):
            sense["regions"] = list(dict.fromkeys(row["regions"]))
        key = (
            sense["pos"],
            sense["translation"],
            sense.get("context", ""),
        )
        if key in seen[headword]:
            continue
        seen[headword].add(key)
        grouped[headword].append(sense)

    analyses = [
        {"headword": headword, "senses": senses}
        for headword, senses in grouped.items()
        if senses
    ]
    return infer_analysis_order(surface, analyses, possible_results)


def build_surface_entry(query, component):
    rows = extract_translation_rows(component)
    possible_results = extract_possible_results(component)
    # entry_lang tells us which direction SpanishDict resolved the
    # query in. With the scraper now forcing ``?langFrom=es`` this
    # should always be "es"; we stash it on the cache entry anyway as
    # a defensive signal so the builder can skip any legacy backwards
    # entries that predate the fix.
    props = component.get("sdDictionaryResultsProps") or {}
    entry = props.get("entry") or {}
    entry_lang = (props.get("entryLang") or entry.get("entryLang") or "").strip()
    return {
        "query": query,
        "entry_lang": entry_lang,
        "dictionary_analyses": build_dictionary_analyses(query, rows, possible_results),
        "possible_results": possible_results,
    }


def conjugation_lemma_from_possible_results(entry):
    """Return the morphological lemma SpanishDict flagged this surface as,
    or ``None``.

    SpanishDict's surface-lookup response has two parallel views:

    * ``dictionary_analyses[].headword`` — the lexicalised dictionary
      entry for the surface word (e.g. ``hay`` has its own headword
      because the "there is/are" meaning is lexicalised; ``vino``-the-
      noun gets its own headword even though ``vino`` is also a
      conjugation of ``venir``).
    * ``possible_results`` — a flat list of disambiguation hints tagged
      by ``heuristic``. Rows with ``heuristic: "conjugation"`` are
      explicit morphological pointers: "this surface is a conjugation
      of VERB", independent of any dictionary entry.

    This helper returns the conjugation pointer's headword, handling:

    * multiple duplicate pointers (e.g. ``habla`` lists ``hablar`` three
      times) — dedupe, take first.
    * multi-verb ambiguity (``fue`` / ``fui`` point to both ``ser`` and
      ``ir``) — prefer the pointer whose headword matches the
      ``dictionary_analyses`` headword (that's SpanishDict's own
      default pick), else fall back to the first.
    * pure-noun cases (no conjugation pointer) — return ``None``.

    The caller decides what to do with the result — the usual pattern
    is: if the card's semantic lemma differs from this morphological
    pointer, stamp a separate ``related_lemma`` field on the card so
    the UI can surface the related paradigm without collapsing the
    card's semantic identity.
    """
    if not isinstance(entry, dict):
        return None
    possibles = entry.get("possible_results") or []
    seen = set()
    conj_lemmas = []
    for row in possibles:
        if not isinstance(row, dict) or row.get("heuristic") != "conjugation":
            continue
        hw = (row.get("headword") or "").strip()
        if hw and hw not in seen:
            seen.add(hw)
            conj_lemmas.append(hw)
    if not conj_lemmas:
        return None
    if len(conj_lemmas) == 1:
        return conj_lemmas[0]
    # Multi-pointer ambiguity — tie-break with the dictionary headword.
    analyses = entry.get("dictionary_analyses") or []
    if analyses:
        dict_hw = (analyses[0].get("headword") or "").strip()
        if dict_hw and dict_hw in seen:
            return dict_hw
    return conj_lemmas[0]


_MWE_UOTFI_RE = re.compile(
    r"^\s*Used other than figuratively or idiomatically:\s*see[^.]*\.\s*",
    re.IGNORECASE,
)
_MWE_USED_PREFIX_RE = re.compile(r"^\s*(Used [^:]+?):\s*", re.IGNORECASE)


def split_mwe_translation(trans):
    """Parse a raw MWE translation string into ``(primary, context)``.

    The SpanishDict ``quickdef`` strings bundle three things in one line:
    the translation itself, a Wiktionary-style parenthetical note, and the
    occasional boilerplate prefix. This helper unbundles them so the UI can
    render ``translation`` bold and ``context`` dim (the same pattern sense
    rows already use).

    Rules, in order:
      1. Strip ``Used other than figuratively or idiomatically: see X, Y.``
         (pure Wiktionary noise).
      2. If the string starts with ``Used [for/to/as] X: Y``, promote ``Y``
         to primary and keep ``Used [for/to/as] X`` as context.
      3. If what remains matches ``PRIMARY (CONTEXT)`` with balanced parens,
         split at the last balanced paren group.

    Returns ``(primary, context)``. ``context`` is ``None`` when no split
    applies. The raw string is returned unchanged as ``primary`` in the
    fallback case.
    """
    if not isinstance(trans, str) or not trans.strip():
        return trans or "", None

    s = _MWE_UOTFI_RE.sub("", trans).strip()
    if not s:
        return "", None

    context = None
    m = _MWE_USED_PREFIX_RE.match(s)
    if m:
        context = m.group(1).strip()
        s = s[m.end():].strip()
        if not s:
            return context, None

    # Find a trailing ``(...)`` with balanced parens that actually closes the
    # string. ``re`` alone can't balance, so walk from the last ``)`` back.
    if s.endswith(")"):
        depth = 0
        start = -1
        for i in range(len(s) - 1, -1, -1):
            c = s[i]
            if c == ")":
                depth += 1
            elif c == "(":
                depth -= 1
                if depth == 0:
                    start = i
                    break
        if start > 0:
            before = s[:start].rstrip()
            inside = s[start + 1:-1].strip()
            # Only split when both sides are non-trivial — avoids mangling
            # entries that are just a single ``(note)``.
            if before and inside:
                extra = inside
                context = (context + "; " + extra) if context else extra
                s = before

    return s, context


def extract_phrases(component):
    """Extract phrase data from SpanishDict component (separate from senses).

    The ``translation`` field keeps the raw ``quickdef`` string so the on-disk
    phrase cache stays lossless. Callers that render MWEs (builders + UI) run
    ``split_mwe_translation`` to peel off the parenthetical context.
    """
    raw = component.get("phrases")
    if not raw or not isinstance(raw, list):
        return []
    return [
        {"expression": p["source"], "translation": p.get("quickdef", "")}
        for p in raw
        if isinstance(p, dict) and p.get("source")
    ]
