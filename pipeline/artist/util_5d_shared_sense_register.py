"""Configurable cross-artist lexical sense registers.

Artists opt into one or more registers through ``artist.json``::

    {"sense_registers": ["reggaeton"]}

A register is a derived, provenance-rich inventory of *model-proposed lexical
senses* observed among its members.  It supplements SpanishDict rather than
replacing it: a later WSD run sees the established register senses as ordinary
closed-set candidates and proposes a new gloss only when none fits.

The derived files live at ``Artists/<language>/sense_registers/<name>.json``.
They are deterministic apart from source-file changes and safe to rebuild.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path

try:
    from util_5c_sense_menu_format import normalize_artist_sense_menu
    from util_6a_assignment_format import load_assignments, is_proper_noun_sense
except ImportError:  # pragma: no cover - package import in tests
    from ..util_5c_sense_menu_format import normalize_artist_sense_menu
    from ..util_6a_assignment_format import load_assignments, is_proper_noun_sense


SCHEMA_VERSION = 1
ALLOWED_LEXICAL_TYPES = frozenset({
    "slang", "regional", "figurative", "vulgar", "loanword",
})
_TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ]+", re.I)
_GLOSS_STOPWORDS = frozenset({
    "a", "an", "and", "for", "of", "or", "slang", "the", "to",
    "people", "person", "situation", "term", "word",
})
_CURRENT_PROMPT_PREFIXES = ("sd-lexical-v1-", "sd-lexical-v2-")


def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch)).strip()


def _gloss_tokens(gloss):
    tokens = []
    for token in _TOKEN_RE.findall(_fold(gloss)):
        if token in _GLOSS_STOPWORDS:
            continue
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return frozenset(tokens)


def _is_reusable_proposal(method, item):
    """Return whether an inline discovered sense may seed a shared register.

    Current named lexical prompts are eligible directly.  Older evidence is
    eligible only when it explicitly identified a lexical usage type (or the
    gloss itself says slang).  This imports useful historical slang such as
    feka/mari without turning every legacy free-form proposal into shared truth.
    """
    if not isinstance(item, dict):
        return False
    if not item.get("translation") or not item.get("pos"):
        return False
    if item.get("construction") or is_proper_noun_sense(item):
        return False
    prompt_id = str(item.get("prompt_id") or "")
    if prompt_id.startswith(_CURRENT_PROMPT_PREFIXES):
        return True
    usage_type = str(item.get("type") or "").strip().casefold()
    if usage_type in ALLOWED_LEXICAL_TYPES:
        return True
    return str(item.get("translation") or "").strip().casefold().startswith("slang ")


def _proposal_rows(artist_dir):
    assignment_path = artist_dir / "data/layers/sense_assignments/spanishdict.json"
    if not assignment_path.exists():
        return []
    config_path = artist_dir / "artist.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    artist_name = config.get("name") or artist_dir.name
    assignments = load_assignments(assignment_path)
    examples_path = artist_dir / "data/layers/examples_raw.json"
    examples_raw = (json.loads(examples_path.read_text(encoding="utf-8"))
                    if examples_path.exists() else {})
    rows = []
    for word, methods in assignments.items():
        if not isinstance(methods, dict):
            continue
        for method, items in methods.items():
            for item in items or []:
                if not _is_reusable_proposal(method, item):
                    continue
                refs = item.get("occurrence_refs") or []
                example_ids = item.get("example_ids") or []
                evidence_count = len({
                    ref.get("occurrence_id") for ref in refs
                    if isinstance(ref, dict) and ref.get("occurrence_id")
                }) or len(example_ids) or len(item.get("examples") or [])
                source_examples = []
                word_examples = examples_raw.get(word) or []
                for raw_index in item.get("examples") or []:
                    try:
                        example = word_examples[int(raw_index)]
                    except (IndexError, TypeError, ValueError):
                        continue
                    source_examples.append({key: example.get(key) for key in (
                        "id", "segment_id", "spanish",
                    ) if example.get(key)})
                rows.append({
                    "word": _fold(word),
                    "lemma": _fold(item.get("lemma") or word),
                    "pos": str(item.get("pos") or "").strip().upper(),
                    "translation": str(item.get("translation") or "").strip(),
                    "type": str(item.get("type") or "slang").strip().casefold(),
                    "artist": artist_name,
                    "method": method,
                    "prompt_id": item.get("prompt_id"),
                    "run_ts": item.get("run_ts"),
                    "evidence_count": evidence_count,
                    "example_ids": sorted(set(str(x) for x in example_ids if x)),
                    "occurrence_ids": sorted({
                        str(ref.get("occurrence_id")) for ref in refs
                        if isinstance(ref, dict) and ref.get("occurrence_id")
                    }),
                    "source_examples": source_examples,
                })
    return rows


def _cluster_rows(rows):
    """Cluster near-duplicate proposals for one word and POS.

    Glosses join when their meaningful-token Jaccard score is at least 0.25.
    This merges ``fake or inauthentic`` with ``fake or counterfeit`` and
    ``marijuana`` with ``slang for marijuana or weed`` while leaving unrelated
    homographs separate.  Clustering is transitive within the word/POS group.
    """
    clusters = []
    for row in sorted(rows, key=lambda r: (
            r["word"], r["pos"], len(r["translation"]), r["translation"].casefold(),
            r["artist"], r["method"])):
        tokens = _gloss_tokens(row["translation"])
        matches = []
        for index, cluster in enumerate(clusters):
            if cluster["word"] != row["word"] or cluster["pos"] != row["pos"]:
                continue
            union = cluster["tokens"] | tokens
            score = len(cluster["tokens"] & tokens) / len(union) if union else 0
            if score >= 0.25:
                matches.append(index)
        if not matches:
            clusters.append({
                "word": row["word"], "pos": row["pos"], "tokens": set(tokens),
                "rows": [row],
            })
            continue
        target = clusters[matches[0]]
        target["rows"].append(row)
        target["tokens"].update(tokens)
        for index in reversed(matches[1:]):
            other = clusters.pop(index)
            target["rows"].extend(other["rows"])
            target["tokens"].update(other["tokens"])
    return clusters


def _existing_id(existing, register, word, pos, tokens):
    for sense in ((existing.get("senses") or {}).get(word) or []):
        if sense.get("pos") != pos:
            continue
        old_tokens = _gloss_tokens(sense.get("translation"))
        union = old_tokens | tokens
        if union and len(old_tokens & tokens) / len(union) >= 0.25:
            return sense.get("id")
    digest = hashlib.sha256(
        (register + "|" + word + "|" + pos + "|" + " ".join(sorted(tokens))).encode("utf-8")
    ).hexdigest()[:12]
    return "register:%s:%s" % (register, digest)


def build_register(language_dir, register):
    """Build one register from all configured member artists."""
    language_dir = Path(language_dir)
    output_path = language_dir / "sense_registers" / (register + ".json")
    existing = {}
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))

    members = []
    rows = []
    for artist_dir in sorted(path for path in language_dir.iterdir() if path.is_dir()):
        config_path = artist_dir / "artist.json"
        if not config_path.exists():
            continue
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if register not in (config.get("sense_registers") or []):
            continue
        members.append(config.get("name") or artist_dir.name)
        rows.extend(_proposal_rows(artist_dir))

    senses = {}
    for cluster in _cluster_rows(rows):
        proposals = cluster["rows"]
        representative = min(
            proposals,
            key=lambda r: (len(r["translation"]), r["translation"].casefold(), r["artist"]),
        )
        common_tokens = set(_gloss_tokens(proposals[0]["translation"]))
        for proposal in proposals[1:]:
            common_tokens.intersection_update(_gloss_tokens(proposal["translation"]))
        canonical_translation = (
            next(iter(common_tokens))
            if len(common_tokens) == 1 and len(next(iter(common_tokens))) >= 4
            else representative["translation"]
        )
        artists = sorted({row["artist"] for row in proposals})
        evidence_count = sum(row["evidence_count"] for row in proposals)
        tokens = frozenset(cluster["tokens"])
        sense_id = _existing_id(
            existing, register, cluster["word"], cluster["pos"], tokens)
        provenance = []
        for row in sorted(proposals, key=lambda r: (
                r["artist"], r["method"], r.get("prompt_id") or "",
                r["translation"].casefold())):
            provenance.append({key: deepcopy(row.get(key)) for key in (
                "artist", "method", "prompt_id", "run_ts", "translation",
                "evidence_count", "example_ids", "occurrence_ids",
                "source_examples",
            ) if row.get(key) not in (None, [], "")})
        senses.setdefault(cluster["word"], []).append({
            "id": sense_id,
            "lemma": representative["lemma"],
            "pos": cluster["pos"],
            "translation": canonical_translation,
            "type": representative["type"],
            "supporting_artists": artists,
            "evidence_count": evidence_count,
            "provenance": provenance,
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "register": register,
        "language": language_dir.name,
        "members": sorted(members),
        "senses": {word: sorted(items, key=lambda s: (s["pos"], s["translation"]))
                   for word, items in sorted(senses.items())},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path, payload


def build_configured_registers(language_dir):
    """Rebuild every register named by any artist in a language directory."""
    language_dir = Path(language_dir)
    names = set()
    for config_path in language_dir.glob("*/artist.json"):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        names.update(config.get("sense_registers") or [])
    return [build_register(language_dir, name) for name in sorted(names)]


def apply_registers_to_menu(artist_dir, menu, inventory_words=None):
    """Merge an artist's configured register senses into a SpanishDict menu."""
    artist_dir = Path(artist_dir)
    config = json.loads((artist_dir / "artist.json").read_text(encoding="utf-8"))
    register_names = config.get("sense_registers") or []
    if not register_names:
        return normalize_artist_sense_menu(menu), 0
    allowed = {_fold(word) for word in inventory_words} if inventory_words is not None else None
    merged = normalize_artist_sense_menu(deepcopy(menu))
    # Re-materialize register rows on every run. This removes stale placements
    # from earlier register logic while preserving all provider senses.
    for word in list(merged):
        cleaned_analyses = []
        for analysis in merged[word]:
            senses = {
                sense_id: sense for sense_id, sense in (analysis.get("senses") or {}).items()
                if not (
                    sense.get("source") == "shared-sense-register"
                    and sense.get("register") in register_names
                )
            }
            if senses:
                analysis["senses"] = senses
                cleaned_analyses.append(analysis)
        if cleaned_analyses:
            merged[word] = cleaned_analyses
        else:
            merged.pop(word, None)
    added = 0
    for register in register_names:
        path = artist_dir.parent / "sense_registers" / (register + ".json")
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for word, senses in (payload.get("senses") or {}).items():
            if allowed is not None and _fold(word) not in allowed:
                continue
            analyses = merged.setdefault(word, [])
            for candidate in senses:
                sense_id = candidate["id"]
                if any(sense_id in (analysis.get("senses") or {}) for analysis in analyses):
                    continue
                headword = candidate.get("lemma") or word
                analysis = next((a for a in analyses
                                 if str(a.get("headword") or word).strip()
                                 == str(headword).strip()), None)
                if analysis is None:
                    analysis = {"headword": headword, "senses": {}}
                    analyses.append(analysis)
                analysis.setdefault("senses", {})[sense_id] = {
                    "pos": candidate["pos"],
                    "translation": candidate["translation"],
                    "source": "shared-sense-register",
                    "register": register,
                    "type": candidate.get("type"),
                    "supporting_artists": candidate.get("supporting_artists", []),
                    "evidence_count": candidate.get("evidence_count", 0),
                }
                added += 1
    return merged, added


def exact_register_assignments(artist_dir):
    """Reuse a register sense for an identical line seen under another artist.

    A Genius ``song_id:line`` identity is preferred; normalized full-line text
    is a backstop.  The assignment is emitted only when exactly one registered
    sense matches that target example, and same-artist provenance is ignored.
    """
    artist_dir = Path(artist_dir)
    config = json.loads((artist_dir / "artist.json").read_text(encoding="utf-8"))
    artist_name = config.get("name") or artist_dir.name
    examples_path = artist_dir / "data/layers/examples_raw.json"
    if not examples_path.exists():
        return {}
    examples_raw = json.loads(examples_path.read_text(encoding="utf-8"))
    candidates = {}
    for register in config.get("sense_registers") or []:
        path = artist_dir.parent / "sense_registers" / (register + ".json")
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for word, senses in (payload.get("senses") or {}).items():
            for sense in senses:
                source_ids = set()
                source_lines = set()
                source_artists = set()
                for provenance in sense.get("provenance") or []:
                    if _fold(provenance.get("artist")) == _fold(artist_name):
                        continue
                    source_artists.add(provenance.get("artist"))
                    for example in provenance.get("source_examples") or []:
                        if example.get("id"):
                            source_ids.add(str(example["id"]))
                        if example.get("spanish"):
                            source_lines.add(_fold(example["spanish"]))
                if source_ids or source_lines:
                    candidates.setdefault(word, []).append({
                        "sense": sense["id"], "register": register,
                        "source_ids": source_ids, "source_lines": source_lines,
                        "source_artists": sorted(a for a in source_artists if a),
                    })

    output = {}
    for word, examples in examples_raw.items():
        word_candidates = candidates.get(_fold(word)) or []
        by_sense = {}
        sources_by_sense = {}
        registers_by_sense = {}
        for index, example in enumerate(examples or []):
            example_id = str(example.get("id") or "")
            line = _fold(example.get("spanish") or example.get("target"))
            matches = [candidate for candidate in word_candidates if
                       (example_id and example_id in candidate["source_ids"])
                       or (line and line in candidate["source_lines"])]
            sense_ids = {candidate["sense"] for candidate in matches}
            if len(sense_ids) != 1:
                continue
            sense_id = next(iter(sense_ids))
            by_sense.setdefault(sense_id, []).append(index)
            for candidate in matches:
                if candidate["sense"] != sense_id:
                    continue
                sources_by_sense.setdefault(sense_id, set()).update(
                    candidate["source_artists"])
                registers_by_sense.setdefault(sense_id, set()).add(candidate["register"])
        if by_sense:
            output[word] = {"shared-register-auto": [{
                "sense": sense_id,
                "examples": indices,
                "registers": sorted(registers_by_sense.get(sense_id, set())),
                "supporting_artists": sorted(sources_by_sense.get(sense_id, set())),
            } for sense_id, indices in sorted(by_sense.items())]}
    return output
