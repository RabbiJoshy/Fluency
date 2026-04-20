#!/usr/bin/env python3
"""Shared SpanishDict extraction helpers."""

import json
import re
import threading
import time
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import requests


SPANISH_SENSES_DIR = Path(__file__).resolve().parents[1] / "Data" / "Spanish" / "Senses"
SPANISHDICT_DIR = SPANISH_SENSES_DIR / "spanishdict"
SPANISHDICT_SURFACE_CACHE = SPANISHDICT_DIR / "surface_cache.json"
SPANISHDICT_HEADWORD_CACHE = SPANISHDICT_DIR / "headword_cache.json"
SPANISHDICT_REDIRECTS = SPANISHDICT_DIR / "redirects.json"
SPANISHDICT_STATUS = SPANISHDICT_DIR / "status.json"
SPANISHDICT_PHRASES_CACHE = SPANISHDICT_DIR / "phrases_cache.json"
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


def build_menu_analyses(surface, surface_cache, headword_cache, include_redirects=True):
    """Build the analyses list for one surface word from the shared SpanishDict cache.

    Starts from the surface page's own dictionary_analyses, then optionally extends
    with headword redirects ("possible_results") — dedup'd by signature.

    Abbreviation-style headwords (`p.a.`, `e.g.`, …) are filtered out when the
    surface query itself has no dots — see ``_is_abbreviation_mismatch``.
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
    url = "https://www.spanishdict.com/translate/%s" % quote(word)
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
    return {
        "query": query,
        "dictionary_analyses": build_dictionary_analyses(query, rows, possible_results),
        "possible_results": possible_results,
    }


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
