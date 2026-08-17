#!/usr/bin/env python3
"""
step_8b_assemble_artist_vocabulary.py — Assemble final artist vocabulary from layer files.

Reads all layer files and the shared master vocabulary, then produces:
  - {Name}vocabulary.index.json  (compact: id, corpus_count, sense_frequencies)
  - {Name}vocabulary.examples.json (examples keyed by ID)
  - {Name}vocabulary.json (full monolith for debugging)

The index is aligned to master senses so joinWithMaster() in the front end
can reconstruct full entries.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_8b_assemble_artist_vocabulary.py --artist-dir Artists/BadBunny
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import argparse
from pathlib import Path

from util_1a_artist_config import (add_artist_arg, load_artist_config, load_shared_dict,
                            normalize_translation, METHOD_PRIORITY, best_method_priority,
                            artist_sense_menu_path, artist_sense_assignments_path,
                            artist_sense_assignments_lemma_path,
                            artist_unassigned_routing_path)
from util_5c_sense_menu_format import normalize_artist_sense_menu, resolve_analysis_for_assignments

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.artist.util_2b_evidence_view import (  # noqa: E402
    corpus_profile_fingerprint,
)
from pipeline.util_evidence_store import archive_json_artifact  # noqa: E402
from pipeline.util_pipeline_meta import make_meta, read_meta, write_sidecar  # noqa: E402
from pipeline.util_6a_assignment_format import (load_assignments, resolve_best_per_example,  # noqa: E402
                                                is_proper_noun_gloss, is_proper_noun_sense,
                                                carry_sense_tags, normalize_pos,
                                                index_examples_by_identity,
                                                resolve_example_reference,
                                                resolve_routing_references)
from pipeline.util_6a_prompt_registry import (  # noqa: E402
    CURRENT_SD_POLICY_ID, capability_tier, load_prompt_policy, load_registry,
)
from pipeline.util_6a_pos_menu_filter import example_matches_credited_artist  # noqa: E402
from pipeline.util_7a_lemma_split import (  # noqa: E402
    _is_phrase_only_self_analysis,
    plural_lemma_redirects,
)
from pipeline.util_pipeline_config import get_default_min_priority  # noqa: E402
from pipeline.util_sense_ids import (  # noqa: E402
    carry_sense_identity,
    make_generated_sense_id,
    merge_sense_identity,
)
from pipeline.util_identity_registry import (  # noqa: E402
    CardIdentityRegistry,
    SenseIdentityRegistry,
)
from pipeline.util_5c_spanishdict import (  # noqa: E402
    SPANISHDICT_SURFACE_CACHE,
    conjugation_lemma_from_possible_results,
)

STEP_VERSION = 17
STEP_VERSION_NOTES = {
    1: "monolith + index + examples + master update + clitic layer",
    2: "+ carry vocalist, Spotify-availability, and variant-title metadata into examples",
    3: "+ carry LRCLIB end_ms into final examples as end_timestamp_ms",
    4: "+ stamp pooled lemma evidence and package Gemini-free Speech fallbacks for Artist Extra",
    5: "+ carry exact artist MWE family counts, morphological variants, and source evidence",
    6: "+ assemble only translated/study-ready artist expressions; retain PMI and clitic "
       "discovery as upstream diagnostics",
    7: "+ preserve stable sense-menu IDs through meanings, sense cycles, and shared master; "
       "mint durable fallback IDs for legacy master-only senses",
    8: "+ assemble regular plural twins under one lemma and carry derivational relation metadata",
    9: "+ preserve per-song artist and Spotify track IDs for playlist playback",
    10: "+ resolve assigned and routed examples by persisted segment ID before legacy list index",
    11: "+ persist card identity independently from mutable surface/lemma analysis",
    12: "+ persist sense identity independently from mutable menu source, gloss, POS, and context labels",
    13: "+ carry exact occurrence surface into compact examples for evidence-backed highlighting",
    14: "+ require active-ledger lineage on compatibility inputs and archive final deck projections",
    15: "+ require Gemini 3.1+ model evidence by default and consume structured occurrence-drop overrides",
    16: "+ suppress common-noun fallback meanings when every occurrence exactly names its credited artist",
    17: "+ coalesce multiple analyses that resolve to one persistent card identity",
}
from util_8a_assembly_helpers import (make_surface_id,
                                     split_count_proportionally)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(os.path.dirname(os.path.dirname(SCRIPTS_DIR)), ".venv", "bin", "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


# Keyword-only threshold for unassigned flag (method priority at or below this = fallback)
KEYWORD_PRIORITY_THRESHOLD = 15  # keyword and pos-keyword

_EXAMPLE_PRIORITY_KEYS = (
    "vocalists", "sung_by_primary_artist", "spotify_available", "is_variant",
    "artist", "spotify_track_id",
)


def active_evidence_build_contract(artist_dir, sense_source="spanishdict"):
    """Validate and fingerprint the ledger-backed inputs used by assembly.

    Artists without an Evidence Store remain buildable during migration. Once
    a profile exists, however, silently assembling stale pre-ledger layers is
    forbidden: both inventory and examples must descend from the selected
    corpus profile.
    """
    artist_dir = Path(artist_dir).resolve()
    evidence_dir = artist_dir / "data" / "evidence"
    profile_path = evidence_dir / "profiles" / "current.json"
    if not profile_path.is_file():
        return {}
    with open(profile_path, encoding="utf-8") as handle:
        profile = json.load(handle)
    ledger_run = str((profile.get("runs") or {}).get("ledger") or "")
    if not ledger_run:
        raise ValueError("Active evidence profile has no ledger run: %s" % profile_path)
    expected_profile_hash = corpus_profile_fingerprint(profile)
    layers_dir = artist_dir / "data" / "layers"
    required = {
        "word_inventory": layers_dir / "word_inventory.json",
        "examples_raw": layers_dir / "examples_raw.json",
    }
    for label, path in required.items():
        meta = read_meta(path) or {}
        if str(meta.get("ledger_run") or "") != ledger_run:
            raise ValueError(
                "%s is not materialized from active ledger %s; rerun "
                "step_2e_materialize_corpus through step_5a_split_evidence" % (
                    label, ledger_run))
        if meta.get("corpus_profile_hash") != expected_profile_hash:
            raise ValueError(
                "%s is stale for the active corpus policy; rerun "
                "step_2e_materialize_corpus through step_5a_split_evidence" % label)

    candidate_paths = {
        **required,
        "example_pos": layers_dir / "example_pos.json",
        "sense_assignments_lemma": (
            layers_dir / "sense_assignments_lemma" / (sense_source + ".json")),
        "word_routing": artist_dir / "data" / "known_vocab" / "word_routing.json",
        "ranking": layers_dir / "ranking.json",
        "example_translations": layers_dir / "example_translations.json",
        "mwe_detected": artist_dir / "data" / "word_counts" / "mwe_detected.json",
    }
    layer_hashes = {
        label: hashlib.sha256(path.read_bytes()).hexdigest()
        for label, path in candidate_paths.items() if path.is_file()
    }
    return {
        "ledger_run": ledger_run,
        "corpus_profile_hash": expected_profile_hash,
        "excluded_labels": sorted(
            (((profile.get("policies") or {}).get("vocal_artifact") or {}).get(
                "excluded_labels") or [])),
        "layer_sha256": layer_hashes,
    }


def _copy_example_priority(raw_example, output_example):
    """Copy presentation/ranking metadata without affecting sense indices."""
    for key in _EXAMPLE_PRIORITY_KEYS:
        if key in raw_example:
            output_example[key] = raw_example[key]


def _copy_example_identity_evidence(raw_example, output_example):
    """Carry private evidence IDs until persistent sense identity resolves."""
    evidence_ids = list(raw_example.get("occurrence_ids") or [])
    if not evidence_ids:
        fallback = raw_example.get("segment_id") or raw_example.get("id")
        if fallback:
            evidence_ids.append(fallback)
    if evidence_ids:
        output_example["_identity_evidence"] = evidence_ids


def _copy_example_surface(raw_example, output_example, canonical_word=""):
    """Carry a non-canonical lyric spelling into the app-facing example.

    POS and sense assignment operate on ``canonical_word``; ``surface`` is the
    immutable occurrence spelling the learner actually sees. Keeping the two
    fields separate lets the frontend highlight an elision without treating it
    as a second card or reconstructing it heuristically from the sentence.
    """
    surface = str(raw_example.get("surface") or "").strip()
    canonical = str(canonical_word or "").strip()
    if surface and (not canonical or surface.casefold() != canonical.casefold()):
        output_example["surface"] = surface


def _copy_timestamp(timestamp_entry, output_example):
    if not timestamp_entry:
        return
    if timestamp_entry.get("ms") is not None:
        output_example["timestamp_ms"] = timestamp_entry["ms"]
    if timestamp_entry.get("end_ms") is not None:
        output_example["end_timestamp_ms"] = timestamp_entry["end_ms"]


_ECHO_DROPS_CACHE = None


def load_echo_drops():
    """{word: {example_id, ...}} from accepted `drop_occurrences` proposals.

    Echo reduplication is a property of an OCCURRENCE, not of a string: `over`
    is an ad-lib in "mover, -over" but an ordinary word in "game over" and the
    artist name "Lary Over" — only 1 of its 7 lines is an echo. Such a word must
    lose those lines without losing its card, so it is filtered here at render
    time rather than removed from examples_raw: sense assignments address
    examples by index, and deleting one would silently shift every later claim.
    """
    global _ECHO_DROPS_CACHE
    if _ECHO_DROPS_CACHE is not None:
        return _ECHO_DROPS_CACHE
    path = os.path.join(_PROJECT_ROOT, "Artists", "curations", "proposals.json")
    drops = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            ledger = json.load(f)
        for proposal in ledger.get("proposals", []):
            if proposal.get("status") != "accepted":
                continue
            operation = proposal.get("operation")
            structured_drop = (
                operation == "add_occurrence_override"
                and proposal.get("occurrence_action") == "drop")
            legacy_drop = (
                operation is None
                and proposal.get("proposed") == "drop_occurrences")
            if not (structured_drop or legacy_drop):
                continue
            ids = {i for i in (
                proposal.get("occurrence_ids")
                or proposal.get("echo_example_ids")
                or []) if i}
            if ids:
                drops.setdefault((proposal.get("word") or "").lower(), set()).update(ids)
    _ECHO_DROPS_CACHE = drops
    return drops


_LEMMA_OVERRIDES_CACHE = None


def load_lemma_overrides():
    """{word: lemma} from Artists/curations/lemma_overrides.json.

    Lemma is card identity — fullId derives from it and progress rows key off
    it — so a model never sets one directly. An accepted proposal is written to
    that file, where the value is diffable and revertible, and applied here.
    A word listed in `keep` is protected: its current lemma is correct and must
    survive even an accepted override.
    """
    global _LEMMA_OVERRIDES_CACHE
    if _LEMMA_OVERRIDES_CACHE is not None:
        return _LEMMA_OVERRIDES_CACHE
    path = os.path.join(_PROJECT_ROOT, "Artists", "curations", "lemma_overrides.json")
    overrides = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        protected = {w.lower() for w in doc.get("keep", [])}
        for word, lemma in (doc.get("overrides") or {}).items():
            key = (word or "").strip().lower()
            if key and lemma and key not in protected:
                overrides[key] = lemma
    _LEMMA_OVERRIDES_CACHE = overrides
    return overrides


def apply_lemma_override(word, lemma):
    """Curated lemma for `word` when one exists, else the computed lemma."""
    return load_lemma_overrides().get((word or "").lower(), lemma)


def is_dropped_example(word, raw_ex):
    """True when this exact occurrence was accepted as an ad-lib, not usage."""
    if not raw_ex:
        return False
    ids = load_echo_drops().get((word or "").lower())
    return bool(ids) and raw_ex.get("id") in ids


def _collect_sid_meta(raw_assignments, per_sense):
    """For each sense in ``per_sense``, pick inline metadata (pos/translation/
    lemma/source/...) from the highest-priority item claiming that sense.

    Per-example method resolution (``resolve_best_per_example``) returns only
    ``{sid: [{ex_idx, method}]}``; the gap-fill branch downstream still needs
    the original item's translation/pos/lemma fields for senses that aren't
    in the menu, so we look them up here from the raw dict form.
    """
    sid_meta = {}
    if not isinstance(raw_assignments, dict):
        return sid_meta
    for method, items in raw_assignments.items():
        prio = METHOD_PRIORITY.get(method, 0)
        for item in items or []:
            if not isinstance(item, dict):
                continue
            sid = item.get("sense")
            if not sid or sid not in per_sense:
                continue
            existing = sid_meta.get(sid)
            if existing is None or prio > existing[0]:
                meta = {k: v for k, v in item.items()
                        if k not in ("sense", "examples", "method", "bucket")}
                sid_meta[sid] = (prio, meta)
    return {sid: meta for sid, (_, meta) in sid_meta.items()}


def _ensure_sense_in_group(group, sid, meta):
    """Ensure a resolved sense id has a renderable slot in ``group``.

    Menu senses already live in ``group["sense_by_id"]``. Off-menu discoveries
    (gap-fill proposals — the classify-or-propose "menu is insufficient" verdict)
    do not, so their sense would be silently skipped at assembly even after
    winning per-example resolution. Synthesize a sense from the inline metadata
    (``translation``/``pos`` plus optional ``type``/``construction``) and append
    it to BOTH ``sense_by_id`` and ``word_senses`` in lockstep so the downstream
    ``sense_idx = keys().index(sid)`` lookup into ``word_senses`` stays aligned.

    Returns True if the sid is renderable (already present, or just synthesized),
    False when there is no inline gloss to render.
    """
    sense_by_id = group.get("sense_by_id")
    if not isinstance(sense_by_id, dict):
        return False
    if sid in sense_by_id:
        return True
    translation = (meta.get("translation") or "").strip() if meta else ""
    if not translation:
        return False
    synth = {"pos": normalize_pos(meta.get("pos")) or "X",
             "translation": meta.get("translation")}
    for k in ("type", "construction", "source", "lemma"):
        if meta.get(k):
            synth[k] = meta[k]
    sense_by_id[sid] = synth
    group.setdefault("word_senses", []).append(synth)
    return True


def _build_menu_free_groups(word, lemma_assignments, min_priority,
                            method_priorities, min_prompt_tier=0,
                            prompt_registry=None,
                            accepted_model_prompt_ids=None):
    """Materialize inline word|lemma assignments without a dictionary menu."""
    groups = []
    prefix = word + "|"
    for lemma_key, raw_group_assignments in (lemma_assignments or {}).items():
        if not lemma_key.startswith(prefix) or not raw_group_assignments:
            continue
        methods = (raw_group_assignments if isinstance(raw_group_assignments, dict)
                   else {"legacy": raw_group_assignments})
        per_sense = resolve_best_per_example(
            methods,
            min_priority=min_priority,
            method_priority=method_priorities,
            min_prompt_tier=min_prompt_tier,
            prompt_registry=prompt_registry,
            accepted_model_prompt_ids=accepted_model_prompt_ids,
        )
        sid_meta = _collect_sid_meta(methods, per_sense)
        group = {
            "lemma": lemma_key.split("|", 1)[1],
            "sense_by_id": {},
            "word_senses": [],
            "assignments": [],
        }
        for sid, ex_list in per_sense.items():
            if not _ensure_sense_in_group(group, sid, sid_meta.get(sid)):
                continue
            item = {
                "sense_idx": list(group["sense_by_id"].keys()).index(sid),
                "sense": sid,
                "examples": ex_list,
            }
            item.update(sid_meta.get(sid, {}))
            group["assignments"].append(item)
        if group["assignments"]:
            groups.append(group)
    return groups


# ---------------------------------------------------------------------------
# ID assignment (same logic as 6_llm_analyze.py)
# ---------------------------------------------------------------------------

def assign_ids_from_master(entries, master, registry_path=None, language="und",
                           surface_cards=False):
    """Assign card IDs through a persistent identity registry.

    With ``surface_cards``, the minted ID is a function of the surface alone.
    Every lemma of one surface therefore arrives at the same preferred ID, and
    the registry attaches each ``(surface, lemma)`` alias to that one card —
    which is what its own contract already allows, and what
    ``_coalesce_card_identities`` then merges into a single display row.
    The master-ID lookup is bypassed in that mode: reusing the old word|lemma
    ID would keep the split it is the point of the migration to remove.
    """
    wl_to_id = {}
    wl_to_ids = {}
    for mid, mentry in master.items():
        pair = (mentry["word"], mentry["lemma"])
        wl_to_id[pair] = mid
        wl_to_ids.setdefault(pair, []).append(mid)

    registry = CardIdentityRegistry.load(registry_path, language) if registry_path else None
    if registry:
        for pair, legacy_ids in wl_to_ids.items():
            # Some historical masters contain duplicate IDs for one word|lemma.
            # Preserve the registry's existing owner, or seed the same last-ID
            # winner the legacy builder used, and record every duplicate as an
            # explicit progress migration instead of crashing or renumbering.
            canonical_id = registry.resolve(
                pair[0], pair[1], allow_inference=False) or legacy_ids[-1]
            registry.seed(canonical_id, pair[0], pair[1])
            wl_to_id[pair] = canonical_id
            for duplicate_id in legacy_ids:
                if duplicate_id == canonical_id:
                    continue
                duplicate = registry.records.setdefault(duplicate_id, {
                    "card_id": duplicate_id,
                    "aliases": [],
                    "evidence_ids": [],
                })
                duplicate["status"] = "merged"
                duplicate["superseded_by"] = canonical_id
                migration = {
                    "kind": "legacy_duplicate",
                    "from": duplicate_id,
                    "to": canonical_id,
                    "reason": "duplicate word|lemma in materialized master",
                }
                if migration not in registry.migrations:
                    registry.migrations.append(migration)
        # The duplicate reconciliation above mutates records directly in one
        # bulk pass. Rebuild the registry's indexes once before assigning the
        # candidate deck instead of rescanning every record for every card.
        registry.invalidate_indexes()

    used = set(master.keys()) | (set(registry.records) if registry else set())
    claimed_ids = set()
    surface_counts = {}
    for candidate in entries:
        surface = str(candidate.get("word") or "").strip().lower()
        surface_counts[surface] = surface_counts.get(surface, 0) + 1
    for entry in entries:
        wl = (entry["word"], entry["lemma"])
        if surface_cards:
            surface = str(entry.get("word") or "").strip().lower()
            preferred_id = make_surface_id(surface, used)
        else:
            preferred_id = wl_to_id.get(wl)
        if preferred_id is None:
            h = hashlib.md5((entry["word"] + "|" + entry["lemma"]).encode("utf-8")).hexdigest()
            final_id = h[:6]
            if final_id in used:
                for start in range(0, len(h) - 5):
                    candidate = h[start:start + 6]
                    if candidate not in used:
                        final_id = candidate
                        break
                else:
                    val = int(final_id, 16) + 1
                    while format(val % 0xFFFFFF, '06x') in used:
                        val += 1
                    final_id = format(val % 0xFFFFFF, '06x')
            preferred_id = final_id

        evidence_ids = entry.pop("_identity_evidence", [])
        if registry:
            entry["id"] = registry.assign(
                entry["word"],
                entry["lemma"],
                evidence_ids=evidence_ids,
                preferred_id=preferred_id,
                claimed_ids=claimed_ids,
                allow_inference=(surface_counts.get(
                    str(entry.get("word") or "").strip().lower(), 0
                ) == 1),
            )
        else:
            entry["id"] = preferred_id
        used.add(entry["id"])
        claimed_ids.add(entry["id"])

    if registry:
        registry.save(registry_path)


def _coalesce_card_identities(entries, master):
    """Merge candidate analyses that the identity registry resolves to one card.

    A persistent card may intentionally own more than one historical
    ``surface|lemma`` alias.  Those aliases are evidence about one learner
    identity, not permission to emit duplicate index rows.  Preserve the
    master-aligned analysis as the display row and union the evidence from all
    aliases before master integration and split-file serialization.
    """
    grouped = {}
    order = []
    for entry in entries:
        card_id = entry.get("id")
        if card_id not in grouped:
            grouped[card_id] = []
            order.append(card_id)
        grouped[card_id].append(entry)

    def example_key(example):
        occurrence_ids = tuple(sorted(str(value) for value in
                                      (example.get("occurrence_ids") or []) if value))
        return (
            occurrence_ids,
            str(example.get("occurrence_id") or ""),
            str(example.get("ex_id") or example.get("id") or ""),
            str(example.get("segment_id") or ""),
            str(example.get("spanish") or example.get("text") or ""),
        )

    def meaning_ids(meaning):
        return {
            str(value) for value in
            [meaning.get("sense_id")] + list(meaning.get("sense_id_aliases") or [])
            if value
        }

    def meaning_key(meaning):
        return (
            normalize_pos(meaning.get("pos")),
            normalize_translation(meaning.get("translation", "")),
            str(meaning.get("context") or "").strip().casefold(),
            bool(meaning.get("unassigned")),
            str(meaning.get("cycle_pos") or ""),
        )

    merged_entries = []
    duplicate_rows = 0
    for card_id in order:
        candidates = grouped[card_id]
        if len(candidates) == 1:
            merged_entries.append(candidates[0])
            continue

        duplicate_rows += len(candidates) - 1
        canonical = master.get(card_id) or {}
        canonical_pair = (
            str(canonical.get("word") or "").casefold(),
            str(canonical.get("lemma") or "").casefold(),
        )
        primary = next((entry for entry in candidates if (
            str(entry.get("word") or "").casefold(),
            str(entry.get("lemma") or "").casefold(),
        ) == canonical_pair), None)
        if primary is None:
            primary = max(candidates, key=lambda entry: (
                sum(len(meaning.get("examples") or [])
                    for meaning in entry.get("meanings") or []),
                int(entry.get("corpus_count") or 0),
            ))

        for incoming in candidates:
            if incoming is primary:
                continue
            primary["corpus_count"] = (
                int(primary.get("corpus_count") or 0)
                + int(incoming.get("corpus_count") or 0)
            )
            for flag in ("is_english", "is_noise", "is_interjection",
                         "is_propernoun", "is_transparent_cognate"):
                primary[flag] = bool(primary.get(flag) or incoming.get(flag))
            for field in ("variants",):
                values = list(primary.get(field) or [])
                for value in incoming.get(field) or []:
                    if value not in values:
                        values.append(value)
                if values:
                    primary[field] = values
            if incoming.get("morphology"):
                incoming_morphology = incoming["morphology"]
                current_morphology = primary.get("morphology")
                if isinstance(incoming_morphology, dict):
                    if not isinstance(current_morphology, dict):
                        current_morphology = {}
                        primary["morphology"] = current_morphology
                    current_morphology.update(incoming_morphology)
                elif isinstance(incoming_morphology, list):
                    if not isinstance(current_morphology, list):
                        current_morphology = []
                        primary["morphology"] = current_morphology
                    for morphology in incoming_morphology:
                        if morphology not in current_morphology:
                            current_morphology.append(morphology)
            primary.setdefault("_sense_provenance", {}).update(
                incoming.get("_sense_provenance") or {})
            if (not primary.get("related_lemma") and incoming.get("related_lemma")
                    and incoming["related_lemma"] != primary.get("lemma")):
                primary["related_lemma"] = incoming["related_lemma"]

            for meaning in incoming.get("meanings") or []:
                ids = meaning_ids(meaning)
                match = next((existing for existing in primary.get("meanings") or []
                              if ((ids and ids & meaning_ids(existing))
                                  or meaning_key(existing) == meaning_key(meaning))), None)
                if match is None:
                    primary.setdefault("meanings", []).append(meaning)
                    continue
                aliases = list(match.get("sense_id_aliases") or [])
                for alias in meaning.get("sense_id_aliases") or []:
                    if alias not in aliases and alias != match.get("sense_id"):
                        aliases.append(alias)
                if meaning.get("sense_id") and meaning.get("sense_id") != match.get("sense_id"):
                    if meaning["sense_id"] not in aliases:
                        aliases.append(meaning["sense_id"])
                if aliases:
                    match["sense_id_aliases"] = aliases
                seen_examples = {example_key(example)
                                 for example in match.get("examples") or []}
                for example in meaning.get("examples") or []:
                    key = example_key(example)
                    if key not in seen_examples:
                        match.setdefault("examples", []).append(example)
                        seen_examples.add(key)

        frequency_meanings = [meaning for meaning in primary.get("meanings") or []
                              if "frequency" in meaning]
        total_examples = sum(len(meaning.get("examples") or [])
                             for meaning in frequency_meanings)
        if total_examples:
            for meaning in frequency_meanings:
                meaning["frequency"] = "%.2f" % (
                    len(meaning.get("examples") or []) / total_examples)
        if primary.get("related_lemma") == primary.get("lemma"):
            primary.pop("related_lemma", None)
        merged_entries.append(primary)

    if duplicate_rows:
        print("  Card identity coalescing: %d alias rows merged" % duplicate_rows)
    return merged_entries


def _card_registry_context(layers_dir):
    """Return the shared per-language registry path without assuming Spanish."""
    layers_path = Path(layers_dir).resolve()
    for parent in layers_path.parents:
        if parent.name != "Artists":
            continue
        relative = layers_path.relative_to(parent)
        if relative.parts:
            language = relative.parts[0].lower()
            return parent / relative.parts[0] / "evidence" / "registries" / "cards.json", language
    return layers_path / "evidence" / "registries" / "cards.json", "und"


def _stabilize_sense_identities(entries, master, registry_path, language):
    """Resolve mutable menu/gloss rows onto persistent per-card sense IDs."""
    registry = SenseIdentityRegistry.load(registry_path, language)
    for card_id, master_entry in master.items():
        for sense in master_entry.get("senses") or []:
            if sense.get("pos") in ("X", "SENSE_CYCLE"):
                continue
            sense_id = sense.get("sense_id") or make_generated_sense_id(
                "artist-master",
                card_id,
                master_entry.get("word"),
                master_entry.get("lemma"),
                sense.get("pos"),
                sense.get("translation"),
                sense.get("context"),
            )
            if not sense.get("sense_id"):
                sense["sense_id"] = sense_id
            registry.seed(
                sense_id,
                card_id,
                sense.get("pos"),
                sense.get("translation"),
                sense.get("context"),
                external_ids=sense.get("sense_id_aliases") or [],
            )

    for entry in entries:
        candidates = []
        candidate_meanings = []
        for meaning in entry.get("meanings") or []:
            evidence_ids = []
            for example in meaning.get("examples") or []:
                evidence_ids.extend(example.pop("_identity_evidence", []) or [])
            if (meaning.get("pos") in ("X", "SENSE_CYCLE")
                    or not (meaning.get("translation") or "").strip()):
                continue
            preferred_id = meaning.get("sense_id") or make_generated_sense_id(
                "artist-sense",
                entry.get("id"),
                meaning.get("pos"),
                meaning.get("translation"),
                meaning.get("context"),
            )
            candidates.append({
                "preferred_id": preferred_id,
                "external_ids": list(meaning.get("sense_id_aliases") or []),
                "pos": meaning.get("pos"),
                "translation": meaning.get("translation"),
                "context": meaning.get("context"),
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
            })
            candidate_meanings.append(meaning)

        resolved_ids = registry.reconcile(entry["id"], candidates)
        for meaning, candidate, canonical_id in zip(
                candidate_meanings, candidates, resolved_ids):
            aliases = list(dict.fromkeys(
                [meaning.get("sense_id"), candidate.get("preferred_id")]
                + list(meaning.get("sense_id_aliases") or [])
                + list(candidate.get("external_ids") or [])
            ))
            meaning["sense_id"] = canonical_id
            aliases = [value for value in aliases if value and value != canonical_id]
            if aliases:
                meaning["sense_id_aliases"] = aliases
            else:
                meaning.pop("sense_id_aliases", None)
    registry.save(registry_path)



# ---------------------------------------------------------------------------
# Layer loading
# ---------------------------------------------------------------------------

def load_layer(path, name, required=True):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = len(data)
        print("  %s: %d entries" % (name, count))
        return data
    if required:
        print("ERROR: Required layer not found: %s" % path)
        sys.exit(1)
    print("  %s: (not found, skipping)" % name)
    return None


# ---------------------------------------------------------------------------
# Wiktionary gloss normalization (--sense-source wiktionary only)
# ---------------------------------------------------------------------------
# Wiktionary's scraped glosses enumerate spelling/synonym variants inline
# ("to fulfil, to fulfill, to meet") and a handful of high-frequency verbs
# (tener and all its conjugations) carry a sense-menu translation string
# that already has a duplicated segment baked in, e.g.
#   "to have; to possess; to be (a condition or quality), to have; to possess"
# Sense IDs are content hashes of that exact string
# (util_5c_sense_menu_format.py), so the fix can't happen at the source —
# editing the menu would change the hash and orphan the Gemini
# classification already sitting in sense_assignments/wiktionary.json.
# Clean it up here at assemble time instead. spanishdict glosses are
# already card-sized and never pass through this (call site is gated on
# sense_source == "wiktionary").
_GLOSS_MAX_GROUPS = 3        # max '; '-separated clauses kept per gloss
_GLOSS_MAX_WORDS_PER_GROUP = 7  # word budget for a run of 3+ ', '-joined items
_GLOSS_QUOTES_RE = re.compile(u"[‘’“”]")


def _split_gloss_segments(text):
    """Split ``text`` on top-level '; ' and ', ' (never inside parens).

    Returns (items, delims) with len(delims) == len(items) - 1; delims[i] is
    the original separator between items[i] and items[i + 1].
    """
    items, delims = [], []
    buf = []
    depth = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and text.startswith("; ", i):
            items.append("".join(buf))
            delims.append("; ")
            buf = []
            i += 2
            continue
        if depth == 0 and text.startswith(", ", i):
            items.append("".join(buf))
            delims.append(", ")
            buf = []
            i += 2
            continue
        buf.append(ch)
        i += 1
    items.append("".join(buf))
    return [it.strip() for it in items], delims


def _gloss_key(segment):
    """Normalization key for duplicate/near-duplicate comparison."""
    k = _GLOSS_QUOTES_RE.sub("'", segment.strip().lower())
    k = re.sub(r"^to\s+", "", k)
    k = re.sub(r"[.,;:'\"]+$", "", k)
    return re.sub(r"\s+", " ", k).strip()


def _is_spelling_double(a, b):
    """True if a/b are the same word modulo a doubled final letter
    (fulfil/fulfill) — a plain British/American spelling variant."""
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(longer) - len(shorter) != 1 or len(longer) < 2:
        return False
    return longer[:-1] == shorter and longer[-1] == longer[-2]


def _dedup_gloss_segments(items, delims):
    """Drop exact/near-exact repeated segments, splicing the surrounding
    delimiters back together so the remaining segments still read naturally
    (the "to have; to possess ... to have; to possess" bug)."""
    kept_items, kept_delims = [], []
    seen_keys = []
    carry_delim = None
    for i, item in enumerate(items):
        key = _gloss_key(item)
        is_dup = any(key == k or _is_spelling_double(key, k) for k in seen_keys)
        if is_dup:
            if i < len(delims):
                carry_delim = delims[i]
            continue
        if kept_items:
            kept_delims.append(carry_delim if carry_delim is not None else delims[i - 1])
        kept_items.append(item)
        seen_keys.append(key)
        carry_delim = None
    return kept_items, kept_delims


def _group_by_semicolon(items, delims):
    """Partition a flat (items, delims) pair into groups at '; ' boundaries.
    Each group is (group_items, group_delims) where group_delims are the
    internal ', ' separators within that group."""
    groups = []
    cur_items = [items[0]] if items else []
    cur_delims = []
    for i, d in enumerate(delims):
        nxt = items[i + 1]
        if d == "; ":
            groups.append((cur_items, cur_delims))
            cur_items = [nxt]
            cur_delims = []
        else:
            cur_items.append(nxt)
            cur_delims.append(d)
    if cur_items:
        groups.append((cur_items, cur_delims))
    return groups


def _cap_words(items, delims, max_words):
    """Greedy left-to-right trim so the running word count stays within
    ``max_words``. Always keeps the first item whole and never splits an
    item mid-word; only drops trailing items."""
    if not items:
        return items, delims
    kept_items = [items[0]]
    kept_delims = []
    total_words = len(items[0].split())
    for i in range(1, len(items)):
        words = len(items[i].split())
        if total_words + words > max_words:
            break
        kept_delims.append(delims[i - 1])
        kept_items.append(items[i])
        total_words += words
    return kept_items, kept_delims


def _join_gloss(items, delims):
    out = items[0]
    for item, delim in zip(items[1:], delims):
        out += delim + item
    return out


def _clean_wiktionary_gloss(text):
    """Normalize a raw Wiktionary translation string for card display:
    dedupe repeated/near-duplicate segments, then cap overlong variant
    enumerations. See the module comment above for the motivating bug.
    """
    text = (text or "").strip()
    if not text:
        return text
    items, delims = _split_gloss_segments(text)
    if len(items) <= 1:
        return text

    items, delims = _dedup_gloss_segments(items, delims)
    if len(items) <= 1:
        return items[0] if items else text

    # Cap variant enumeration to something card-sized. '; '-separated
    # clauses are the primary distinct-meaning boundary in Wiktionary
    # glosses, so keep at most _GLOSS_MAX_GROUPS of them, biased toward the
    # first ("prefer keeping first semicolon group when trimming"). Within
    # a kept clause, only cap a genuine run of 3+ ', '-joined items — a
    # 2-item group (e.g. "in, it has been...since (a past period of time)")
    # is usually two distinct senses glued together, not a synonym run, and
    # dropping the second would misrepresent the word rather than trim
    # clutter.
    groups = _group_by_semicolon(items, delims)[:_GLOSS_MAX_GROUPS]
    parts = []
    for g_items, g_delims in groups:
        if len(g_items) > 2:
            g_items, g_delims = _cap_words(g_items, g_delims, _GLOSS_MAX_WORDS_PER_GROUP)
        parts.append(_join_gloss(g_items, g_delims))
    return "; ".join(parts)


def _normalize_wiktionary_senses(menu):
    """In-place: clean up every gloss in a wiktionary sense menu (see
    _clean_wiktionary_gloss). Only invoked for --sense-source wiktionary;
    spanishdict menus are already card-sized and untouched."""
    cleaned = 0
    for analyses in menu.values():
        for analysis in analyses:
            for s in (analysis.get("senses") or {}).values():
                t = s.get("translation")
                if not t:
                    continue
                nt = _clean_wiktionary_gloss(t)
                if nt != t:
                    s["translation"] = nt
                    cleaned += 1
    if cleaned:
        print("  wiktionary gloss normalization: cleaned %d senses" % cleaned)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def resolve_sense_provenance(raw_assignments, registry, min_prompt_tier=0,
                             accepted_model_prompt_ids=None,
                             prompt_preference=None):
    """Map each assigned sense_id to the provenance of its most trustworthy claim.

    Reads a word's ``{method: [items]}`` assignment dict and, per sense_id,
    picks the item with the highest capability_tier (registry lookup on
    ``prompt_id``), breaking ties by the most recent ``run_ts``. Returns
    ``{sense_id: {"prompt_id": str, "run_ts": str|None, "method": str,
    "model_proposed": bool}}``. ``model_proposed`` distinguishes definitions
    generated because the dictionary menu had a lexical gap from ordinary
    model selections among SpanishDict's supplied senses.

    This is the authoritative per-sense provenance source for the card, keyed by
    the stable sense_id — independent of the lossy (pos, translation) match and
    of which meaning-build path attached the examples.
    """
    best = {}
    if not isinstance(raw_assignments, dict):
        return {}
    for _method, items in raw_assignments.items():
        if (_method.endswith("-auto")
                or (_method.startswith("legacy-") and _method.endswith("-v1"))):
            continue
        for item in items or []:
            if not isinstance(item, dict):
                continue
            sid = item.get("sense")
            prompt_id = item.get("prompt_id")
            if not sid or not prompt_id:
                continue
            if accepted_model_prompt_ids is not None:
                if prompt_id not in accepted_model_prompt_ids:
                    continue
            elif capability_tier(prompt_id, registry) < min_prompt_tier:
                continue
            run_ts = item.get("run_ts") or ""
            if prompt_preference is not None:
                rank = (prompt_preference.get(prompt_id, -1), run_ts)
            else:
                rank = (capability_tier(prompt_id, registry), run_ts)
            cur = best.get(sid)
            if cur is None or rank > cur[0]:
                best[sid] = (rank, prompt_id, item.get("run_ts"), _method)
    return {
        sid: {
            "prompt_id": pid,
            "run_ts": rts,
            "method": method,
            "model_proposed": (
                method.startswith("lexical-gap-fill-") or method == "gap-fill"
            ),
        }
        for sid, (_rank, pid, rts, method) in best.items()
    }


def assemble_from_layers(layers_dir, master, curated_translations_path=None,
                         sense_source="wiktionary", skip_words_path=None,
                         emit_remainders=False, min_priority=0,
                         stamp_cognate_scores=False, min_prompt_tier=0,
                         prompt_policy_id=CURRENT_SD_POLICY_ID,
                         surface_cards=False):
    """Assemble vocabulary entries from layer files.

    Returns (entries, master) where entries is the full monolith list and
    master has been updated with new words/senses.

    When ``emit_remainders`` is False (default), any generated SENSE_CYCLE /
    unassigned meaning rows are dropped from each entry before serialization.
    Set to True to preserve the full remainder-bucket experience.

    ``min_priority`` (default 0) drops assignments whose method priority is
    below the threshold. Their examples become orphans and only appear if
    ``emit_remainders`` is also True.
    """
    # Load all layers
    print("Loading layers...")
    profile_path = os.path.join(
        os.path.dirname(layers_dir), "evidence", "profiles", "current.json")
    evidence_profile = load_layer(
        profile_path, "evidence_profile", required=False) or {}
    method_priorities = evidence_profile.get("method_priorities") or {}
    prompt_policy = load_prompt_policy(prompt_policy_id) if prompt_policy_id else {}
    if prompt_policy_id and not prompt_policy:
        raise ValueError("Unknown prompt acceptance policy: %s" % prompt_policy_id)
    accepted_model_prompt_ids = frozenset(
        prompt_policy.get("accepted_prompt_ids") or [])
    prompt_preference = {
        prompt_id: index
        for index, prompt_id in enumerate(prompt_policy.get("preference_order") or [])
    }
    inventory = load_layer(os.path.join(layers_dir, "word_inventory.json"), "word_inventory")
    examples_raw = load_layer(os.path.join(layers_dir, "examples_raw.json"), "examples_raw")
    translations = load_layer(os.path.join(layers_dir, "example_translations.json"), "example_translations")
    # Sense menu (definitions) + assignments (example→sense mappings)
    raw_menu = load_layer(
        artist_sense_menu_path(layers_dir, sense_source, prefer_new=False),
        "sense_menu", required=False,
    )
    senses = normalize_artist_sense_menu(raw_menu) if raw_menu else {}
    if sense_source == "wiktionary" and senses:
        _normalize_wiktionary_senses(senses)
    assignments_path = artist_sense_assignments_path(layers_dir, sense_source, prefer_new=False)
    if os.path.isfile(assignments_path):
        assignments = load_assignments(assignments_path)
        print("  sense_assignments: %d entries" % len(assignments))
    else:
        assignments = {}
        print("  sense_assignments: (not found, skipping)")
    lemma_assignments_path = artist_sense_assignments_lemma_path(layers_dir, sense_source, prefer_new=False)
    if os.path.isfile(lemma_assignments_path):
        lemma_assignments = load_assignments(lemma_assignments_path)
        print("  sense_assignments_lemma: %d entries" % len(lemma_assignments))
    else:
        lemma_assignments = {}
        print("  sense_assignments_lemma: (not found, skipping)")
    unassigned_routing_path = artist_unassigned_routing_path(layers_dir, sense_source)
    unassigned_routing = load_layer(unassigned_routing_path, "unassigned_routing", required=False) or {}
    unassigned_routing_evidence = load_layer(
        os.path.join(layers_dir, "unassigned_routing_evidence", sense_source + ".json"),
        "unassigned_routing_evidence", required=False,
    ) or {}

    # Auto-invoke: if menu exists but no assignments, run keyword assignment + lemma mapping
    if senses and not assignments:
        artist_dir = os.path.dirname(os.path.dirname(layers_dir))
        print("\n  No sense assignments found — auto-invoking keyword assignment...")
        kw_args = ["--artist-dir", artist_dir, "--keyword-only"]
        if sense_source == "spanishdict":
            kw_args.extend([
                "--sense-menu-file", "sense_menu/spanishdict.json",
                "--assignments-file", "sense_assignments/spanishdict.json",
                "--keyword-method-name", "spanishdict-keyword",
                "--auto-method-name", "spanishdict-auto",
                "--menu-source-label", "spanishdict",
            ])
        cmd = [PYTHON, os.path.join(os.path.dirname(SCRIPTS_DIR), "step_6b_assign_senses_local.py")] + kw_args
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("  WARNING: keyword assignment failed (exit code %d)" % result.returncode)
        else:
            # Run lemma mapping
            lemma_args = ["--artist-dir", artist_dir, "--sense-source", sense_source]
            cmd = [PYTHON, os.path.join(SCRIPTS_DIR, "step_7a_map_senses_to_lemmas.py")] + lemma_args
            subprocess.run(cmd)
            # Reload assignments
            assignments = load_assignments(assignments_path) if os.path.isfile(assignments_path) else {}
            lemma_assignments = load_assignments(lemma_assignments_path) if os.path.isfile(lemma_assignments_path) else {}
            print("  sense_assignments (auto): %d entries" % len(assignments))
            print("  sense_assignments_lemma (auto): %d entries" % len(lemma_assignments))
    # Shared layers at Data/Spanish/layers/ (project root from script location)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    shared_cognates = os.path.join(project_root, "Data", "Spanish", "layers", "cognates.json")
    cognates = load_layer(shared_cognates, "cognates (shared)", required=False) or {}
    conj_reverse_path = os.path.join(project_root, "Data", "Spanish", "layers", "conjugation_reverse.json")
    conj_reverse = load_layer(conj_reverse_path, "conjugation_reverse (shared)", required=False) or {}
    # Wiktionary-derived morphology layer (tool_4a_build_morphology_layer).
    # Same shape as conjugation_reverse — primary source for stamping
    # because Wiktionary covers ~42% more verb forms than verbecc on the
    # master vocab (voseo, regional slang, clitic bundles). Verbecc
    # remains the fallback for canonical-paradigm gaps Wiktionary skips.
    wikt_morph_path = os.path.join(project_root, "Data", "Spanish", "layers", "morphology.json")
    wikt_morph = load_layer(wikt_morph_path, "morphology (wiktionary, shared)", required=False) or {}
    # SpanishDict-derived synonyms/antonyms layer (tool_5e_build_synonyms_layer).
    # Keyed by lemma; value is {synonyms: [...], antonyms: [...]}. Optional —
    # runs without when the thesaurus cache hasn't been built yet.
    synonyms_path = os.path.join(project_root, "Data", "Spanish", "layers", "synonyms.json")
    synonyms_layer = load_layer(synonyms_path, "synonyms (spanishdict, shared)", required=False) or {}
    derivation_path = os.path.join(
        project_root, "Data", "Spanish", "layers", "derivational_relations.json")
    derivation_layer = load_layer(
        derivation_path, "derivational_relations (shared)", required=False) or {}
    derivation_relations = derivation_layer.get("relations", {}) \
        if isinstance(derivation_layer, dict) else {}
    if derivation_relations:
        print("  derivational relations available: %d lemmas" % len(derivation_relations))
    ranking = load_layer(os.path.join(layers_dir, "ranking.json"), "ranking", required=False)
    translation_scores = load_layer(os.path.join(layers_dir, "translation_scores.json"),
                                     "translation_scores", required=False) or {}
    lyrics_ts = load_layer(os.path.join(layers_dir, "lyrics_timestamps.json"), "lyrics_timestamps", required=False)
    ts_map = lyrics_ts.get("timestamps", {}) if lyrics_ts else {}
    example_pos = load_layer(os.path.join(layers_dir, "example_pos.json"), "example_pos", required=False) or {}

    # MWEs: shared layer at Data/Spanish/layers/mwe_phrases.json (all sources with provenance).
    # Keyed by word string (lowercase), e.g. {"que": [{expression, translation, source, ...}]}.
    shared_mwes_path = os.path.join(project_root, "Data", "Spanish", "layers", "mwe_phrases.json")
    mwe_by_word = load_layer(shared_mwes_path, "mwe_phrases (shared)", required=False) or {}

    # SpanishDict surface cache — source for `related_lemma` (the
    # morphological pointer SpanishDict attaches to lexicalised
    # conjugated-form headwords, e.g. hay → haber). See
    # util_5c_spanishdict.conjugation_lemma_from_possible_results.
    spanishdict_surface_cache = {}
    if SPANISHDICT_SURFACE_CACHE.exists():
        with open(SPANISHDICT_SURFACE_CACHE, "r", encoding="utf-8") as f:
            spanishdict_surface_cache = json.load(f)
        print(f"  spanishdict_surface_cache: {len(spanishdict_surface_cache)} entries")
    else:
        print("  spanishdict_surface_cache: (not found, related_lemma disabled)")

    # Artist-specific MWEs from the lyric counting pass (step_2a → mwe_detected.json).
    # Merged in-memory, not written back to the shared layer — these are per-artist
    # by construction (translated lexicon hits, morphology-constrained
    # constructions, and the small set of PMI candidates with an exact
    # dictionary translation). Untranslated PMI and clitic templates stay in
    # mwe_detected.json for review; they are not learner-facing rows.
    # layers_dir == {artist_dir}/data/layers; word_counts/ is its sibling.
    artist_detected_path = os.path.join(os.path.dirname(layers_dir), "word_counts", "mwe_detected.json")
    artist_mwes_added = 0
    if os.path.isfile(artist_detected_path):
        # Materialized MWE detections can outlive a curation edit.  Treat the
        # current curated/skip files as the authority at assembly time so a
        # removed phrase cannot remain learner-facing until the next complete
        # lyric scan. Construction templates remain independently sourced.
        curation_dir = os.path.join(project_root, "Artists", "curations")
        with open(os.path.join(curation_dir, "curated_mwes.json"),
                  encoding="utf-8") as f:
            current_curated_mwes = {
                key.casefold(): value for key, value in json.load(f).items()
                if not key.startswith("_")
            }
        with open(os.path.join(curation_dir, "skip_mwes.json"),
                  encoding="utf-8") as f:
            skip_payload = json.load(f)
        current_skip_mwes = {
            str(value).casefold() for value in skip_payload.get("entries", [])
        }
        with open(artist_detected_path, "r", encoding="utf-8") as f:
            detected = json.load(f)
        buckets = [
            ("artist-curated", detected.get("mwes") or []),
            ("artist-pmi",     detected.get("pmi_detected") or []),
        ]
        for source, items in buckets:
            for m in items:
                expr = (m.get("expression") or "").strip()
                translation = m.get("translation", "") or ""
                if source == "artist-curated":
                    expression_key = expr.casefold()
                    if (expression_key not in current_curated_mwes
                            or expression_key in current_skip_mwes):
                        continue
                    translation = current_curated_mwes[expression_key]
                if not expr or not translation:
                    continue
                entry = {
                    "expression": expr,
                    "translation": translation,
                    "count": m.get("count", 0) or 0,
                    "occurrence_count": m.get("occurrence_count", m.get("count", 0)) or 0,
                    "num_songs": m.get("num_songs", 0) or 0,
                    "source": m.get("source") or source,
                }
                if m.get("family"):
                    entry["family"] = m["family"]
                if m.get("variants"):
                    entry["variants"] = m["variants"]
                if m.get("variant_counts"):
                    entry["variant_counts"] = m["variant_counts"]
                if m.get("examples"):
                    entry["detected_examples"] = m["examples"]
                # Attach to every component token. If the token isn't in the
                # artist's vocab, the attachment is a no-op at annotation
                # time. If it is, the MWE shows up on that card.
                attachment_phrases = [expr]
                variants = m.get("variants") or []
                attachment_phrases.extend(
                    variants.keys() if isinstance(variants, dict) else variants)
                if m.get("family"):
                    attachment_phrases.append(m["family"])
                attachment_tokens = {
                    token
                    for phrase in attachment_phrases
                    for token in str(phrase).lower().split()
                }
                for token in attachment_tokens:
                    if not token or token == "[pron]":
                        continue
                    existing = mwe_by_word.setdefault(token, [])
                    if any((e.get("expression") or "").lower() == expr.lower()
                           and e.get("source") == entry["source"]
                           for e in existing):
                        continue
                    existing.append(entry)
                artist_mwes_added += 1
        print("  mwe_detected (artist): merged %d expressions into layer" % artist_mwes_added)

    # Load curated translations (artist-specific first, then shared as fallback)
    curated = {}
    if curated_translations_path and os.path.isfile(curated_translations_path):
        with open(curated_translations_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        curated = {k: v for k, v in raw.items() if not k.startswith("_")}
        print("  curated_translations (artist): %d overrides" % len(curated))
    # Load shared curated (tagged format, artist + shared modes)
    shared = load_shared_dict("curated_translations.json", modes=("shared", "artist"))
    for k, v in shared.items():
        if k not in curated:
            curated[k] = v
    if shared:
        print("  curated_translations (shared): %d entries" % len(shared))

    # Load word routing for clitic merge and flag categories
    routing_data = {}
    clitic_merge = {}  # word -> base_form
    clitic_orphans = set()  # orphan clitics mapped to synthetic infinitive
    skip_english = set()
    skip_propn = set()
    skip_noise = set()  # was skip_intj in schema_v1; bucket renamed interjections→noise
    skip_cognate = set()  # curated transparent cognates (baby, flow, haters…): routed to
                          # exclude.cognate but previously never flagged, so they leaked as
                          # visible junk cards with invented gap-fill glosses (baby = the
                          # deck's #1-frequency non-word). Flagging hides them via the
                          # excludeCognates toggle Josh runs with ON.
    if skip_words_path and os.path.isfile(skip_words_path):
        with open(skip_words_path, "r", encoding="utf-8") as f:
            routing_data = json.load(f)
        clitic_merge = routing_data.get("clitic_merge", {})
        clitic_orphans = set(routing_data.get("clitic_orphans", []))
        # Build flag sets from exclude categories
        exclude = routing_data.get("exclude", {})
        for w in exclude.get("english", []):
            skip_english.add(w.lower() if isinstance(w, str) else w)
        for w in exclude.get("proper_nouns", []):
            skip_propn.add(w.lower() if isinstance(w, str) else w)
        # schema_v2 renamed exclude.interjections → exclude.noise. Read both
        # so the builder works against pre-rerun word_routing.json files too.
        for w in exclude.get("noise", []) + exclude.get("interjections", []):
            skip_noise.add(w.lower() if isinstance(w, str) else w)
        for w in exclude.get("cognate", []):
            skip_cognate.add(w.lower() if isinstance(w, str) else w)
        if clitic_merge:
            print("  clitic_merge: %d words (%d orphans → synthetic infinitive)" %
                  (len(clitic_merge), len(clitic_orphans)))
        print("  routing flags: %d english, %d propn, %d noise, %d cognate" %
              (len(skip_english), len(skip_propn), len(skip_noise), len(skip_cognate)))

    # Unified tag store (word_tags.json, built by tool_4b_resolve_tags.py) —
    # per-word resolved `category` used to group Extra in the front end. Sits
    # in the same known_vocab dir as word_routing.json.
    word_categories = {}
    if skip_words_path:
        _wt = os.path.join(os.path.dirname(skip_words_path), "word_tags.json")
        if os.path.isfile(_wt):
            with open(_wt, "r", encoding="utf-8") as f:
                _tags = json.load(f)
            for _w, _v in _tags.items():
                if isinstance(_v, dict) and _v.get("category"):
                    word_categories[_w.lower()] = _v["category"]
            print("  word_tags: %d categorised" % len(word_categories))

    # Pre-process clitic merges: skip clitics from main deck, build separate
    # clitic data file (like MWEs). Base verb references clitic IDs; front-end
    # displays clitics as sub-entries.
    # Note: orphan clitics (base not in inventory) are handled upstream in
    # step 4a, which adds synthetic infinitive entries to the inventory and
    # transfers examples. By the time we get here, the base entry should exist.
    clitic_merged_words = set()  # words to skip in entry loop
    clitic_data = {}  # clitic_word -> {base_verb, senses, examples, ...}
    if clitic_merge:
        inv_by_word = {e["word"].lower(): e for e in inventory}
        for clitic_word, base_verb in clitic_merge.items():
            clitic_entry = inv_by_word.get(clitic_word)
            base_entry = inv_by_word.get(base_verb)
            if not clitic_entry or not base_entry:
                continue
            # Add clitic's corpus count to base
            base_entry["corpus_count"] = base_entry.get("corpus_count", 0) + clitic_entry.get("corpus_count", 0)
            # Build clitic's own sense data (resolved, self-contained)
            clitic_exs = examples_raw.get(clitic_word, [])
            clitic_assigns = assignments.get(clitic_word, {})
            # Look up senses for this clitic
            clitic_analysis = resolve_analysis_for_assignments(senses, clitic_word, clitic_assigns)
            clitic_senses_raw = clitic_analysis.get("senses")
            clitic_lemma = clitic_analysis.get("headword", clitic_analysis.get("lemma", clitic_word))
            # Build resolved examples with translations
            resolved_examples = []
            for ex in clitic_exs:
                spanish = ex.get("spanish", "")
                trans_info = translations.get(spanish, {})
                ex_dict = {
                    "song": ex["id"].split(":")[0] if ":" in ex.get("id", "") else ex.get("id", ""),
                    "song_name": ex.get("title", ""),
                    "spanish": spanish,
                    "english": trans_info.get("english", ""),
                }
                _copy_example_priority(ex, ex_dict)
                _copy_example_surface(ex, ex_dict, clitic_word)
                ts_entry = ts_map.get(ex.get("title", ""), {}).get(spanish)
                _copy_timestamp(ts_entry, ex_dict)
                resolved_examples.append(ex_dict)
            # Build resolved sense assignments
            resolved_assigns = {}
            if isinstance(clitic_assigns, dict):
                for method, items in clitic_assigns.items():
                    resolved_items = []
                    for item in items:
                        resolved = {"sense": item.get("sense")}
                        resolved["examples"] = [
                            i for i in item.get("examples", []) if i < len(resolved_examples)
                        ]
                        resolved_items.append(resolved)
                    resolved_assigns[method] = resolved_items
            # Get the best translation from senses, fall back to base verb
            translation = ""
            if clitic_senses_raw:
                first = (list(clitic_senses_raw.values())[0] if isinstance(clitic_senses_raw, dict)
                         else clitic_senses_raw[0] if clitic_senses_raw else None)
                if first:
                    translation = first.get("translation", "")
            if not translation:
                base_analysis = resolve_analysis_for_assignments(
                    senses, base_verb, assignments.get(base_verb, {}))
                base_senses = base_analysis.get("senses")
                if base_senses:
                    first_base = (list(base_senses.values())[0] if isinstance(base_senses, dict)
                                  else base_senses[0] if base_senses else None)
                    if first_base:
                        translation = first_base.get("translation", "")
            clitic_data[clitic_word] = {
                "base_verb": base_verb,
                "lemma": clitic_lemma,
                "corpus_count": clitic_entry.get("corpus_count", 0),
                "translation": translation,
                "assignments": resolved_assigns,
                "examples": resolved_examples,
            }
            # variants may be a list (legacy) or a {variant: count} dict (new
            # format from step_3a). Add the clitic surface as a key either way.
            variants = base_entry.get("variants")
            if isinstance(variants, dict):
                variants.setdefault(clitic_word, 0)
            elif isinstance(variants, list):
                if clitic_word not in variants:
                    variants.append(clitic_word)
            else:
                base_entry["variants"] = [clitic_word]
            clitic_merged_words.add(clitic_word.lower())
        print("  Clitic forms: %d skipped from deck, data preserved in clitic layer"
              % len(clitic_merged_words))

    # --- Assemble entries ---
    print("\nAssembling vocabulary...")
    entries = []
    # Provenance registry (prompt_id -> capability_tier/model/...). Loaded once;
    # used to pick the most trustworthy claim per sense for the card's info panel.
    prompt_registry = load_registry()

    for inv_entry in inventory:
        # Skip clitic forms that were merged into their base verb
        if inv_entry["word"].lower() in clitic_merged_words:
            continue
        word = inv_entry["word"]
        corpus_count = inv_entry.get("corpus_count", 0)
        display_form = inv_entry.get("display_form")
        variants = inv_entry.get("variants")

        analyses = senses.get(word, [])

        # Get sense assignments — handle both old (list) and new (dict-of-methods).
        # Per-example resolution happens per-group below; here we only compute
        # the word-level max priority, used as the SENSE_CYCLE gate (unchanged
        # semantics vs. old `best_method <= threshold` test, since best_method
        # was the max).
        raw_assignments = assignments.get(word, [])
        if isinstance(raw_assignments, dict) and raw_assignments:
            word_max_prio = max((METHOD_PRIORITY.get(m, 0) for m in raw_assignments.keys()),
                                default=0)
            has_word_assignments = True
        elif isinstance(raw_assignments, list) and raw_assignments:
            word_max_prio = 0
            has_word_assignments = True
        else:
            word_max_prio = 0
            has_word_assignments = False

        # Group assignments by analysis (lemma) using sense IDs
        grouped = []
        sid_to_group = {}
        for analysis in analyses:
            sense_map = analysis.get("senses", {}) if isinstance(analysis, dict) else {}
            group = {
                "lemma": analysis.get("headword", analysis.get("lemma", word)) if isinstance(analysis, dict) else word,
                "sense_by_id": sense_map if isinstance(sense_map, dict) else {},
                "word_senses": list(sense_map.values()) if isinstance(sense_map, dict) else [],
                "assignments": [],
                "_analysis": analysis if isinstance(analysis, dict) else {},
            }
            grouped.append(group)
            for sid in group["sense_by_id"]:
                sid_to_group[sid] = group

        # Keep the builder's groups identical to step 7a's canonical keys.
        # SpanishDict often supplies both besitos|besitos and
        # besitos|besito; both retain their sense IDs but share lemma besito.
        plural_redirect_map = plural_lemma_redirects(analyses)
        if plural_redirect_map:
            for g in grouped:
                g["lemma"] = plural_redirect_map.get(g["lemma"], g["lemma"])

        # Collapse reflexive/pronominal lemmas into base form when both exist
        # in this word's analysis set (mirrors util_7a_lemma_split logic).
        all_group_lemmas = {g["lemma"] for g in grouped}
        reflexive_redirects = {
            lem: lem[:-2] for lem in all_group_lemmas
            if lem.endswith("se") and lem[:-2] in all_group_lemmas
        }
        if reflexive_redirects:
            for g in grouped:
                if g["lemma"] in reflexive_redirects:
                    g["lemma"] = reflexive_redirects[g["lemma"]]

        # Collapse PHRASE-only self-analyses (lemma == word AND every sense
        # POS=PHRASE) into the first real lemma. Gated on the phrase predicate
        # so legitimate noun/adverb/interjection analyses whose canonical
        # lemma equals the surface (bebé, sangre, papa, así, ojalá…) survive.
        other_lemmas = [g["lemma"] for g in grouped if g["lemma"] != word]
        if other_lemmas:
            for g in grouped:
                if g["lemma"] == word and _is_phrase_only_self_analysis(word, g["_analysis"]):
                    g["lemma"] = other_lemmas[0]

        lemma_key_to_group = {}
        for g in grouped:
            key = "%s|%s" % (word, g["lemma"])
            if key in lemma_key_to_group:
                # Merge sense_by_id and word_senses from collapsed groups
                lemma_key_to_group[key]["sense_by_id"].update(g["sense_by_id"])
                lemma_key_to_group[key]["word_senses"].extend(g["word_senses"])
            else:
                lemma_key_to_group[key] = g
        for g in lemma_key_to_group.values():
            for sid in g["sense_by_id"]:
                sid_to_group[sid] = g

        # Surface off-menu discoveries whose inline lemma has no menu group.
        # gap-fill can invent a lemma the SpanishDict menu doesn't carry (e.g.
        # manín|manín, "my man", when the menu only knows the wrong manín|maní,
        # "peanut"). Without a group the proposal is orphaned. Create a bare
        # discovery group per uncovered word|lemma key so the resolution loop
        # below + _ensure_sense_in_group can synthesize and render the sense.
        # Gated on `grouped` (word HAS a menu): pure sense-discovery words keep
        # their existing fallback path unchanged.
        if lemma_assignments and grouped:
            _word_prefix = word + "|"
            for _lkey, _lval in lemma_assignments.items():
                if _lkey in lemma_key_to_group or not _lkey.startswith(_word_prefix):
                    continue
                if not isinstance(_lval, dict) or not _lval:
                    continue
                if not any(
                    (it.get("translation") or "").strip()
                    for items in _lval.values() for it in (items or [])
                    if isinstance(it, dict)
                ):
                    continue
                _orphan_group = {
                    "lemma": _lkey.split("|", 1)[1],
                    "sense_by_id": {},
                    "word_senses": [],
                    "assignments": [],
                    "_analysis": {},
                }
                lemma_key_to_group[_lkey] = _orphan_group
                # active_groups is built from `grouped`; add the orphan there
                # too (same object) so its emitted card isn't dropped.
                grouped.append(_orphan_group)

        if lemma_assignments and lemma_key_to_group:
            for lemma_key, group in lemma_key_to_group.items():
                raw_group_assignments = lemma_assignments.get(lemma_key, {})
                if isinstance(raw_group_assignments, dict) and raw_group_assignments:
                    per_sense = resolve_best_per_example(
                        raw_group_assignments,
                        min_priority=min_priority,
                        method_priority=method_priorities,
                        min_prompt_tier=min_prompt_tier,
                        prompt_registry=prompt_registry,
                        accepted_model_prompt_ids=accepted_model_prompt_ids,
                    )
                    sid_meta = _collect_sid_meta(raw_group_assignments, per_sense)
                elif isinstance(raw_group_assignments, list) and raw_group_assignments:
                    # Legacy flat-list fallback: treat as one pseudo-method.
                    as_dict = {"legacy": raw_group_assignments}
                    per_sense = resolve_best_per_example(
                        as_dict,
                        min_priority=min_priority,
                        method_priority=method_priorities,
                        min_prompt_tier=min_prompt_tier,
                        prompt_registry=prompt_registry,
                        accepted_model_prompt_ids=accepted_model_prompt_ids,
                    )
                    sid_meta = _collect_sid_meta(as_dict, per_sense)
                else:
                    continue
                for sid, ex_list in per_sense.items():
                    if not _ensure_sense_in_group(group, sid, sid_meta.get(sid)):
                        continue
                    entry = {
                        "sense_idx": list(group["sense_by_id"].keys()).index(sid),
                        "examples": ex_list,  # [{"ex_idx", "method"}]
                        "sense": sid,
                    }
                    entry.update(sid_meta.get(sid, {}))
                    group["assignments"].append(entry)
        elif has_word_assignments and grouped:
            if isinstance(raw_assignments, dict):
                per_sense = resolve_best_per_example(
                    raw_assignments,
                    min_priority=min_priority,
                    method_priority=method_priorities,
                    min_prompt_tier=min_prompt_tier,
                    prompt_registry=prompt_registry,
                    accepted_model_prompt_ids=accepted_model_prompt_ids,
                )
                sid_meta = _collect_sid_meta(raw_assignments, per_sense)
            else:
                as_dict = {"legacy": raw_assignments}
                per_sense = resolve_best_per_example(
                    as_dict,
                    min_priority=min_priority,
                    method_priority=method_priorities,
                    min_prompt_tier=min_prompt_tier,
                    prompt_registry=prompt_registry,
                    accepted_model_prompt_ids=accepted_model_prompt_ids,
                )
                sid_meta = _collect_sid_meta(as_dict, per_sense)
            for sid, ex_list in per_sense.items():
                group = sid_to_group.get(sid)
                if not group:
                    continue
                entry = {
                    "sense_idx": list(group["sense_by_id"].keys()).index(sid),
                    "examples": ex_list,
                    "sense": sid,
                }
                entry.update(sid_meta.get(sid, {}))
                group["assignments"].append(entry)
        elif not grouped:
            # A menu-free adapter may already have split its inline claims onto
            # word|lemma keys. Build those groups directly so its lemma is not
            # replaced by the surface word merely because no dictionary menu
            # exists.
            grouped = _build_menu_free_groups(
                word,
                lemma_assignments,
                min_priority,
                method_priorities,
                min_prompt_tier=min_prompt_tier,
                prompt_registry=prompt_registry,
                accepted_model_prompt_ids=accepted_model_prompt_ids,
            )

            if not grouped:
                fallback_analysis = resolve_analysis_for_assignments(
                    senses, word, raw_assignments)
                word_senses_raw = fallback_analysis.get("senses")
                # Build per-sense assignments preserving inline metadata (pos,
                # translation, lemma, source) — used by gap-fill without menu.
                fallback_assignments = []
                if isinstance(raw_assignments, dict) and raw_assignments:
                    per_sense = resolve_best_per_example(
                        raw_assignments,
                        min_priority=min_priority,
                        method_priority=method_priorities,
                        min_prompt_tier=min_prompt_tier,
                        prompt_registry=prompt_registry,
                        accepted_model_prompt_ids=accepted_model_prompt_ids,
                    )
                    sid_meta = _collect_sid_meta(raw_assignments, per_sense)
                    for sid, ex_list in per_sense.items():
                        entry = {"sense": sid, "examples": ex_list}
                        entry.update(sid_meta.get(sid, {}))
                        fallback_assignments.append(entry)
                elif isinstance(raw_assignments, list):
                    fallback_assignments = raw_assignments
                grouped = [{
                    "lemma": fallback_analysis.get(
                        "headword", fallback_analysis.get("lemma", word)),
                    "sense_by_id": (
                        word_senses_raw if isinstance(word_senses_raw, dict) else {}),
                    "word_senses": (
                        list(word_senses_raw.values())
                        if isinstance(word_senses_raw, dict)
                        else (word_senses_raw or [])),
                    "assignments": fallback_assignments,
                }]

        # Get raw examples for this word
        raw_examples = examples_raw.get(word, [])
        raw_examples_by_id = index_examples_by_identity(raw_examples)
        credited_artist_only = bool(raw_examples) and all(
            example_matches_credited_artist(word, example)
            for example in raw_examples
        )

        # Apply POS-based unassigned-example routing from step 7a.
        # For each group (analysis), attach the list of raw-example indices
        # that step 7a routed to that lemma_key based on spaCy POS matching.
        for g in grouped:
            lemma_key = "%s|%s" % (word, g.get("lemma", word))
            stable_rows = unassigned_routing_evidence.get(lemma_key)
            if stable_rows is not None:
                g["unassigned_ex_indices"] = resolve_routing_references(
                    stable_rows, raw_examples)
            else:
                g["unassigned_ex_indices"] = unassigned_routing.get(lemma_key, [])

        if has_word_assignments:
            # Emit a card if the group has either keyword assignments or
            # routed unassigned examples. A group with only routed
            # unassigned examples becomes a card with just a SENSE_CYCLE row.
            active_groups = [g for g in grouped
                             if g["assignments"] or g.get("unassigned_ex_indices")]
        else:
            active_groups = [g for g in grouped if g["word_senses"]]

        assigned_weights = [sum(len(a.get("examples", [])) for a in g["assignments"]) for g in active_groups]
        # If a group has no keyword assignments but has routed unassigned
        # examples, give it weight from those examples for corpus_count split.
        for i, g in enumerate(active_groups):
            if not assigned_weights[i] and g.get("unassigned_ex_indices"):
                assigned_weights[i] = len(g["unassigned_ex_indices"])
        if any(assigned_weights):
            group_counts = split_count_proportionally(corpus_count, assigned_weights)
        else:
            group_counts = [corpus_count] + [0] * max(0, len(active_groups) - 1)

        for g_idx, group in enumerate(active_groups or [{
            "lemma": word, "sense_by_id": {}, "word_senses": [], "assignments": []
        }]):
            word_lemma = apply_lemma_override(word, group.get("lemma", word))
            sense_by_id = group.get("sense_by_id")
            word_senses = group.get("word_senses")
            word_assignments = group.get("assignments", [])
            sense_ids = list(sense_by_id.keys()) if isinstance(sense_by_id, dict) else []

            # Build meanings
            meanings = []
            # Groups enter this branch if they have keyword assignments OR if
            # they received routed unassigned examples (POS-tag-based routing).
            # A group with only routed examples produces a SENSE_CYCLE-only card.
            if word_senses and (word_assignments or group.get("unassigned_ex_indices")):
                total_assigned = sum(len(a.get("examples", [])) for a in word_assignments)

                for assignment in word_assignments:
                    sense_idx = assignment["sense_idx"]
                    if sense_idx >= len(word_senses):
                        continue
                    sense = word_senses[sense_idx]
                    pos = sense["pos"]
                    translation = sense["translation"]

                    curated_key = "%s|%s" % (word.lower(), word_lemma)
                    if curated_key in curated and len(word_assignments) == 1:
                        translation = curated[curated_key]

                    ex_entries = assignment.get("examples", [])
                    meaning_examples = []
                    methods_in_meaning = set()
                    # Provenance candidates for the meaning-level stamp: (run_ts,
                    # prompt_id). The card surfaces which prompt/model produced
                    # this sense; pick the most recent run among contributing
                    # examples (ISO timestamps sort lexicographically).
                    prov_candidates = []
                    for entry in ex_entries:
                        # Post-refactor: entries are {"ex_idx", "method"} dicts
                        # so each example can carry its own per-example method.
                        # Tolerate the legacy raw-int form for old data.
                        if isinstance(entry, dict):
                            ex_idx = entry.get("ex_idx")
                            ex_method = entry.get("method")
                            ex_prompt_id = entry.get("prompt_id")
                            ex_run_ts = entry.get("run_ts")
                            ex_conf = entry.get("confidence")
                            ex_band = entry.get("band")
                        else:
                            ex_idx = entry
                            ex_method = None
                            ex_prompt_id = None
                            ex_run_ts = None
                            ex_conf = None
                            ex_band = None
                        raw_ex = resolve_example_reference(
                            entry, raw_examples, raw_examples_by_id)
                        if raw_ex is None:
                            continue
                        if is_dropped_example(word, raw_ex):
                            continue
                        spanish = raw_ex.get("spanish", "")
                        trans_info = translations.get(spanish, {})
                        english = trans_info.get("english", "")
                        source = trans_info.get("source", "")
                        ex_dict = {
                            "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                            "song_name": raw_ex.get("title", ""),
                            "spanish": spanish,
                            "english": english,
                            "translation_source": source,
                        }
                        # Stamp assignment method on each example so the
                        # front-end can show per-example highlights/borders.
                        if ex_method:
                            ex_dict["assignment_method"] = ex_method
                            methods_in_meaning.add(ex_method)
                        # Per-example provenance (which prompt/model produced
                        # this claim) — for the card's info panel.
                        if ex_prompt_id:
                            ex_dict["prompt_id"] = ex_prompt_id
                            if ex_run_ts:
                                ex_dict["run_ts"] = ex_run_ts
                            prov_candidates.append((ex_run_ts or "", ex_prompt_id, ex_run_ts))
                        # How sure the model was about THIS occurrence. Shown in
                        # the card's provenance panel next to the prompt id.
                        if ex_conf is not None:
                            ex_dict["confidence"] = ex_conf
                        if ex_band:
                            ex_dict["band"] = ex_band
                        score_entry = translation_scores.get(spanish, {})
                        if isinstance(score_entry, dict) and "score" in score_entry:
                            ex_dict["translation_quality"] = score_entry["score"]
                        _copy_example_priority(raw_ex, ex_dict)
                        _copy_example_identity_evidence(raw_ex, ex_dict)
                        _copy_example_surface(raw_ex, ex_dict, word)
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        _copy_timestamp(ts_entry, ex_dict)
                        meaning_examples.append(ex_dict)

                    meaning_examples.sort(
                        key=lambda e: e.get("translation_quality", 3), reverse=True)

                    freq = "%.2f" % (len(ex_entries) / total_assigned) if total_assigned > 0 else "1.00"
                    meaning = {
                        "pos": pos,
                        "translation": translation,
                        "frequency": freq,
                        "examples": meaning_examples,
                    }
                    carry_sense_identity(
                        meaning,
                        assignment.get("sense") or (
                            sense_ids[sense_idx] if sense_idx < len(sense_ids) else None
                        ),
                    )
                    src = sense.get("source")
                    if src:
                        meaning["source"] = src
                    # Carry the off-menu register tag (slang/regional/… and, from
                    # the next-run prompt, proper_noun) so the proper-noun guard
                    # below can route by an explicit type, not just gloss text.
                    stype = sense.get("type")
                    if stype:
                        meaning["type"] = stype
                    # Preserve the sub-sense context from the menu (e.g.
                    # SpanishDict's "to move fast" for correr→to run). The
                    # front end renders this as a subtitle/tag under the
                    # translation for richer disambiguation.
                    ctx = sense.get("context")
                    if ctx:
                        meaning["context"] = ctx
                    # Meaning-level stamp: only when every contributing method
                    # is keyword-tier (0 < prio <= KEYWORD_PRIORITY_THRESHOLD).
                    # Non-keyword methods in the same meaning suppress the
                    # low-trust caveat.
                    if methods_in_meaning and (
                        all(m.endswith("-auto") for m in methods_in_meaning)
                        or all(
                            0 < METHOD_PRIORITY.get(m, 0) <= KEYWORD_PRIORITY_THRESHOLD
                            for m in methods_in_meaning
                        )
                    ):
                        meaning["assignment_method"] = max(
                            methods_in_meaning,
                            key=lambda m: METHOD_PRIORITY.get(m, 0))
                    # Meaning-level provenance: the most recent run among the
                    # contributing examples. The card resolves prompt_id ->
                    # model/notes via config/prompt_registry.json.
                    if prov_candidates:
                        _, best_prompt_id, best_run_ts = max(prov_candidates)
                        meaning["prompt_id"] = best_prompt_id
                        if best_run_ts:
                            meaning["run_ts"] = best_run_ts
                    meanings.append(meaning)

                # If the word's highest-priority method is keyword-tier, add
                # SENSE_CYCLE remainder rows for unassigned examples.  Trusted
                # spaCy POS tags get their own POS-specific bucket.  Untrusted
                # or missing tags all fall into one universal bucket listing
                # every sense.  (Equivalent to the old `best_method <= threshold`
                # check since best_method was the max-priority method.)
                if 0 < word_max_prio <= KEYWORD_PRIORITY_THRESHOLD:
                    _routed_unassigned = group.get("unassigned_ex_indices") or []
                    word_pos_data = example_pos.get(word, {})
                    from collections import defaultdict as _defaultdict
                    TRUSTED_FILTER_POS = {"VERB", "NOUN", "ADJ", "ADV", "INTJ"}
                    UNIVERSAL_KEY = "_ALL"
                    pos_to_unassigned = _defaultdict(list)
                    for ex_idx in _routed_unassigned:
                        if ex_idx >= len(raw_examples):
                            continue
                        raw_ex = raw_examples[ex_idx]
                        if is_dropped_example(word, raw_ex):
                            continue
                        spanish = raw_ex.get("spanish", "")
                        trans_info = translations.get(spanish, {})
                        ex_dict = {
                            "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                            "song_name": raw_ex.get("title", ""),
                            "spanish": spanish,
                            "english": trans_info.get("english", ""),
                            "translation_source": trans_info.get("source", ""),
                        }
                        _copy_example_priority(raw_ex, ex_dict)
                        _copy_example_identity_evidence(raw_ex, ex_dict)
                        _copy_example_surface(raw_ex, ex_dict, word)
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        _copy_timestamp(ts_entry, ex_dict)
                        ex_pos = word_pos_data.get(str(ex_idx))
                        if ex_pos and ex_pos in TRUSTED_FILTER_POS:
                            pos_to_unassigned[ex_pos].append(ex_dict)
                        else:
                            pos_to_unassigned[UNIVERSAL_KEY].append(ex_dict)

                    # Build SENSE_CYCLE rows from this group's own senses.
                    # Unassigned examples for POS tags not covered by this
                    # group's senses were routed elsewhere (see
                    # route_unassigned_examples_to_groups).  Deduplicate by
                    # (pos, translation) for display.
                    all_word_senses_deduped = {}
                    for sense_idx, s in enumerate(word_senses):
                        key = (s.get("pos", ""), s.get("translation", ""))
                        if key not in all_word_senses_deduped:
                            sense_copy = dict(s)
                            if sense_idx < len(sense_ids):
                                carry_sense_identity(sense_copy, sense_ids[sense_idx])
                            all_word_senses_deduped[key] = sense_copy

                    for pos_key in sorted(pos_to_unassigned.keys()):
                        cycle_ex = pos_to_unassigned[pos_key]
                        if not cycle_ex:
                            continue
                        if pos_key == UNIVERSAL_KEY:
                            # Universal bucket: list every sense the word has
                            senses_for_pos = list(all_word_senses_deduped.values())
                            cycle_pos_label = "ANY"
                        else:
                            # Trusted POS bucket: only senses matching that POS
                            senses_for_pos = [s for (p, _t), s in all_word_senses_deduped.items()
                                              if p == pos_key]
                            if not senses_for_pos:
                                senses_for_pos = list(all_word_senses_deduped.values())
                            cycle_pos_label = pos_key

                        all_senses = []
                        for s in senses_for_pos:
                            sense_out = carry_sense_tags(
                                {"pos": normalize_pos(s["pos"]), "translation": s["translation"]}, s)
                            carry_sense_identity(
                                sense_out, s.get("sense_id"), s.get("sense_id_aliases") or [])
                            all_senses.append(sense_out)

                        # Always use SENSE_CYCLE pos so the master update
                        # (which skips SENSE_CYCLE) doesn't end up with a
                        # duplicate of an already-assigned sense.
                        meanings.append({
                            "pos": "SENSE_CYCLE",
                            "translation": senses_for_pos[0]["translation"],
                            "frequency": "0.00",
                            "examples": cycle_ex,
                            "unassigned": True,
                            "cycle_pos": cycle_pos_label,
                            "allSenses": all_senses,
                        })

            elif word_senses:
                # Senses exist but no assignments (or only keyword/auto).
                # Show assigned senses as normal rows; remaining senses
                # grouped by POS into SENSE_CYCLE rows.
                curated_key = "%s|%s" % (word.lower(), word_lemma)

                # Build resolved examples once
                all_examples = []
                for raw_ex in raw_examples:
                    if is_dropped_example(word, raw_ex):
                        continue
                    spanish = raw_ex.get("spanish", "")
                    trans_info = translations.get(spanish, {})
                    ex_dict = {
                        "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                        "song_name": raw_ex.get("title", ""),
                        "spanish": spanish,
                        "english": trans_info.get("english", ""),
                        "translation_source": trans_info.get("source", ""),
                    }
                    _copy_example_priority(raw_ex, ex_dict)
                    _copy_example_identity_evidence(raw_ex, ex_dict)
                    _copy_example_surface(raw_ex, ex_dict, word)
                    ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                    _copy_timestamp(ts_entry, ex_dict)
                    all_examples.append(ex_dict)

                if len(word_senses) == 1:
                    # Single sense — all examples on it (auto-level, not unassigned)
                    translation = word_senses[0]["translation"]
                    if curated_key in curated:
                        translation = curated[curated_key]
                    single_meaning = {
                        "pos": normalize_pos(word_senses[0]["pos"]),
                        "translation": translation,
                        "frequency": "1.00",
                        "examples": all_examples,
                    }
                    if sense_ids:
                        carry_sense_identity(single_meaning, sense_ids[0])
                    carry_sense_tags(single_meaning, word_senses[0])
                    src = word_senses[0].get("source")
                    if src:
                        single_meaning["source"] = src
                    meanings.append(single_meaning)
                else:
                    # Multiple senses, no confident assignment.
                    # Group remaining senses by POS into SENSE_CYCLE rows.
                    # Deduplicate senses by (pos, translation)
                    seen = set()
                    unique_senses = []
                    for sense_idx, s in enumerate(word_senses):
                        key = (s.get("pos", ""), s.get("translation", ""))
                        if key not in seen:
                            seen.add(key)
                            sense_copy = dict(s)
                            if sense_idx < len(sense_ids):
                                carry_sense_identity(sense_copy, sense_ids[sense_idx])
                            unique_senses.append(sense_copy)

                    # Group by POS
                    from collections import defaultdict as _defaultdict
                    pos_groups = _defaultdict(list)
                    for s in unique_senses:
                        pos_groups[s.get("pos", "X")].append(s)

                    # Distribute examples across POS groups (round-robin)
                    pos_list = sorted(pos_groups.keys())
                    for p_idx, pos_key in enumerate(pos_list):
                        senses_for_pos = pos_groups[pos_key]
                        cycle_examples = [ex for i, ex in enumerate(all_examples)
                                          if i % len(pos_list) == p_idx]
                        if not cycle_examples and all_examples:
                            cycle_examples = [all_examples[0]]

                        if len(senses_for_pos) == 1:
                            # Single sense for this POS — normal row, but unassigned
                            single_row = {
                                "pos": pos_key,
                                "translation": senses_for_pos[0]["translation"],
                                "frequency": "%.2f" % (1.0 / len(pos_list)),
                                "examples": cycle_examples,
                                "unassigned": True,
                            }
                            carry_sense_identity(
                                single_row,
                                senses_for_pos[0].get("sense_id"),
                                senses_for_pos[0].get("sense_id_aliases") or [],
                            )
                            src = senses_for_pos[0].get("source")
                            if src:
                                single_row["source"] = src
                            meanings.append(single_row)
                        else:
                            # Multiple senses for this POS — SENSE_CYCLE row
                            cycle_row = {
                                "pos": "SENSE_CYCLE",
                                "translation": senses_for_pos[0]["translation"],
                                "frequency": "%.2f" % (1.0 / len(pos_list)),
                                "examples": cycle_examples,
                                "unassigned": True,
                                "cycle_pos": pos_key,
                                "allSenses": [],
                            }
                            for s in senses_for_pos:
                                sense_out = carry_sense_tags(
                                    {"pos": normalize_pos(s["pos"]),
                                     "translation": s["translation"]}, s)
                                carry_sense_identity(
                                    sense_out,
                                    s.get("sense_id"),
                                    s.get("sense_id_aliases") or [],
                                )
                                cycle_row["allSenses"].append(sense_out)
                            meanings.append(cycle_row)
            elif word_assignments and any(a.get("translation") for a in word_assignments):
                total_assigned = sum(len(a.get("examples", [])) for a in word_assignments) or 1
                for assignment in word_assignments:
                    pos = assignment.get("pos", "X")
                    translation = assignment.get("translation", "")

                    curated_key = "%s|%s" % (word.lower(), word_lemma)
                    if curated_key in curated and len(word_assignments) == 1:
                        translation = curated[curated_key]

                    ex_entries = assignment.get("examples", [])
                    meaning_examples = []
                    methods_in_meaning = set()
                    prov_candidates = []
                    for entry in ex_entries:
                        if isinstance(entry, dict):
                            ex_idx = entry.get("ex_idx")
                            ex_method = entry.get("method")
                            ex_prompt_id = entry.get("prompt_id")
                            ex_run_ts = entry.get("run_ts")
                            ex_conf = entry.get("confidence")
                            ex_band = entry.get("band")
                        else:
                            ex_idx = entry
                            ex_method = None
                            ex_prompt_id = None
                            ex_run_ts = None
                            ex_conf = None
                            ex_band = None
                        raw_ex = resolve_example_reference(
                            entry, raw_examples, raw_examples_by_id)
                        if raw_ex is None:
                            continue
                        if is_dropped_example(word, raw_ex):
                            continue
                        spanish = raw_ex.get("spanish", "")
                        trans_info = translations.get(spanish, {})
                        ex_dict = {
                            "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                            "song_name": raw_ex.get("title", ""),
                            "spanish": spanish,
                            "english": trans_info.get("english", ""),
                            "translation_source": trans_info.get("source", ""),
                        }
                        if ex_method:
                            ex_dict["assignment_method"] = ex_method
                            methods_in_meaning.add(ex_method)
                        if ex_prompt_id:
                            ex_dict["prompt_id"] = ex_prompt_id
                            if ex_run_ts:
                                ex_dict["run_ts"] = ex_run_ts
                            prov_candidates.append((ex_run_ts or "", ex_prompt_id, ex_run_ts))
                        # How sure the model was about THIS occurrence. Shown in
                        # the card's provenance panel next to the prompt id.
                        if ex_conf is not None:
                            ex_dict["confidence"] = ex_conf
                        if ex_band:
                            ex_dict["band"] = ex_band
                        _copy_example_priority(raw_ex, ex_dict)
                        _copy_example_identity_evidence(raw_ex, ex_dict)
                        _copy_example_surface(raw_ex, ex_dict, word)
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        _copy_timestamp(ts_entry, ex_dict)
                        meaning_examples.append(ex_dict)
                    freq = "%.2f" % (len(ex_entries) / total_assigned) if total_assigned > 0 else "1.00"
                    meaning = {
                        "pos": normalize_pos(pos),
                        "translation": translation,
                        "frequency": freq,
                        "examples": meaning_examples,
                    }
                    carry_sense_identity(meaning, assignment.get("sense"))
                    carry_sense_tags(meaning, assignment)
                    src = assignment.get("source")
                    if src:
                        meaning["source"] = src
                    if methods_in_meaning and (
                        all(m.endswith("-auto") for m in methods_in_meaning)
                        or all(
                            0 < METHOD_PRIORITY.get(m, 0) <= KEYWORD_PRIORITY_THRESHOLD
                            for m in methods_in_meaning
                        )
                    ):
                        meaning["assignment_method"] = max(
                            methods_in_meaning,
                            key=lambda m: METHOD_PRIORITY.get(m, 0))
                    if prov_candidates:
                        _, best_prompt_id, best_run_ts = max(prov_candidates)
                        meaning["prompt_id"] = best_prompt_id
                        if best_run_ts:
                            meaning["run_ts"] = best_run_ts
                    meanings.append(meaning)
            else:
                curated_key = "%s|%s" % (word.lower(), word_lemma)
                translation = curated.get(curated_key, "")
                fallback_examples = []
                # First occurrence that is not an accepted ad-lib. A word whose
                # only line is an echo simply gets no fallback example.
                raw_ex = next((ex for ex in raw_examples
                               if not is_dropped_example(word, ex)), None)
                if raw_ex:
                    spanish = raw_ex.get("spanish", "")
                    trans_info = translations.get(spanish, {})
                    ex_dict = {
                        "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                        "song_name": raw_ex.get("title", ""),
                        "spanish": spanish,
                        "english": trans_info.get("english", ""),
                        "translation_source": trans_info.get("source", ""),
                    }
                    _copy_example_priority(raw_ex, ex_dict)
                    _copy_example_identity_evidence(raw_ex, ex_dict)
                    _copy_example_surface(raw_ex, ex_dict, word)
                    ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                    _copy_timestamp(ts_entry, ex_dict)
                    fallback_examples.append(ex_dict)
                meanings.append({
                    "pos": "X",
                    "translation": translation,
                    "frequency": "1.00",
                    "examples": fallback_examples,
                })

            # Morphology stamping. Wiktionary first (richer coverage —
            # voseo, regional slang, clitic bundles), verbecc fills the
            # canonical-paradigm gaps Wiktionary skips. Both lookups share
            # the {lemma, mood, tense, person} shape.
            morphology = None
            wl_lower = word.lower()
            lemma_lower = word_lemma.lower()
            if wl_lower != lemma_lower:
                matches = [
                    {"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                    for c in wikt_morph.get(wl_lower, [])
                    if c["lemma"] == lemma_lower
                ]
                if not matches and conj_reverse:
                    matches = [
                        {"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                        for c in conj_reverse.get(wl_lower, [])
                        if c["lemma"] == lemma_lower
                    ]
                if len(matches) == 1:
                    morphology = matches[0]
                elif len(matches) > 1:
                    morphology = matches
            elif wl_lower == lemma_lower:
                has_verb = word_senses and any(s.get("pos") == "VERB" for s in word_senses)
                if has_verb:
                    morphology = {"mood": "infinitivo"}

            # Proper-noun guard. Gemini sometimes recognises a name but, having
            # no tag slot, writes the category into the gloss ("proper noun",
            # "Name of a social media app") or (next-run prompt) stamps
            # type=proper_noun with a real description. Such a meaning is not a
            # teachable translation:
            #   - if the word also has real meanings, drop the proper-noun one;
            #   - if it's ONLY that, route the whole entry to Extra as a proper
            #     noun (keeping the description text) instead of the main deck.
            # Structural signals (type stamp, PROPN pos) are checked before the
            # gloss regex. Regex-first recognised only the useless label form
            # ("proper noun") and missed the good identifying gloss ("The
            # Beatles (band)"), so the better Gemini's answer the less likely
            # the word got tagged. See is_proper_noun_sense.
            def _is_propn_meaning(m):
                return is_proper_noun_sense(m)
            # "Real" has to mean teachable. A blank-translation POS=X sense is a
            # placeholder, not a meaning, and treating it as one would keep a
            # pure proper noun in the main deck showing an empty gloss while its
            # one informative line (the name description) was dropped.
            def _is_teachable_meaning(m):
                return bool((m.get("translation") or "").strip()) and m.get("pos") != "X"

            _propn_meanings = [m for m in meanings if _is_propn_meaning(m)]
            _force_propn = credited_artist_only
            if credited_artist_only:
                # A token that is the exact full credited performer name in
                # every occurrence is name evidence, not evidence for an
                # unrelated common-noun dictionary entry (Boza -> rope).
                meanings = _propn_meanings
            elif _propn_meanings:
                _real_meanings = [m for m in meanings
                                  if not _is_propn_meaning(m) and _is_teachable_meaning(m)]
                if _real_meanings:
                    meanings = _real_meanings          # keep real senses, drop the label
                else:
                    _force_propn = True                # pure proper noun → Extra

            has_wikt = bool(word_senses and word_assignments and isinstance(raw_assignments, dict))
            wl = word.lower()
            identity_evidence = []
            for assignment in word_assignments:
                for example_ref in assignment.get("examples") or []:
                    if not isinstance(example_ref, dict):
                        continue
                    identity_evidence.extend(example_ref.get("occurrence_ids") or [])
                    if not example_ref.get("occurrence_ids") and example_ref.get("ex_id"):
                        identity_evidence.append(example_ref["ex_id"])
            for routed_index in group.get("unassigned_ex_indices") or []:
                if not isinstance(routed_index, int) or not (0 <= routed_index < len(raw_examples)):
                    continue
                routed_example = raw_examples[routed_index]
                identity_evidence.extend(routed_example.get("occurrence_ids") or [])
                if not routed_example.get("occurrence_ids"):
                    routed_identity = routed_example.get("segment_id") or routed_example.get("id")
                    if routed_identity:
                        identity_evidence.append(routed_identity)
            entry = {
                "id": "",
                "word": word,
                "lemma": word_lemma,
                "meanings": meanings,
                "most_frequent_lemma_instance": True,
                "is_english": wl in skip_english,
                # is_noise is the schema_v2 name; is_interjection is kept as
                # an alias so master entries built before the rename and
                # consumers (front-end filter, tools) still see the flag.
                # Both fields carry identical truth values.
                "is_noise": wl in skip_noise,
                "is_interjection": wl in skip_noise,
                "is_propernoun": (wl in skip_propn) or _force_propn,
                "is_transparent_cognate": wl in skip_cognate,
                "corpus_count": group_counts[g_idx] if g_idx < len(group_counts) else 0,
                "_has_wikt_assignments": has_wikt,
                "_identity_evidence": list(dict.fromkeys(identity_evidence)),
            }
            # Unified tag category → front-end groups Extra by this.
            _cat = word_categories.get(wl)
            if (_cat == "unresolved" and word_assignments
                    and any(_is_teachable_meaning(m) for m in meanings)):
                # `unresolved` describes missing lexical evidence. Once a
                # deterministic/register assignment supplies a real meaning,
                # leaving the stale tag would hide a now-resolved word in the
                # Needs classification Extra group.
                _cat = "core"
            if _force_propn:
                # A Gemini-recognised proper noun with no routing tag yet — send
                # it to the Extra proper_noun group rather than the main deck.
                entry["extra_category"] = "proper_noun"
            elif _cat:
                entry["extra_category"] = _cat
            if display_form:
                entry["display_form"] = display_form
            if variants:
                entry["variants"] = variants
            if morphology:
                entry["morphology"] = morphology

            # Synonyms / antonyms — looked up by lemma since they're a
            # property of the lexeme. The same hablar entry serves every
            # surface form (hablo / habla / hablaste / …).
            syn_entry = synonyms_layer.get(lemma_lower) or {}
            if syn_entry.get("synonyms"):
                entry["synonyms"] = syn_entry["synonyms"]
            if syn_entry.get("antonyms"):
                entry["antonyms"] = syn_entry["antonyms"]
            # Derivational relation (diminutive / superlative / …). The layer
            # is keyed by lemma, so the lemma is the primary key. But a card
            # whose lemma is wrong or missing (e.g. `fotito` carrying a stale
            # fuzzy-scrape lemma `fotuto`) would silently lose a relation that
            # exists under its surface form — so fall back to the surface form.
            # The fallback is guarded: never stamp a relation whose base is the
            # card's own lemma or its own surface form (circular).
            derivation_relation = derivation_relations.get(lemma_lower)
            if not derivation_relation:
                fallback = derivation_relations.get(wl)
                if fallback:
                    base = (fallback.get("base_lemma") or "").lower()
                    if base and base != lemma_lower and base != wl:
                        derivation_relation = fallback
            if derivation_relation:
                entry["derivation_relation"] = derivation_relation

            # `related_lemma` — SpanishDict's morphological pointer when it
            # differs from the card's semantic lemma. Classic case: ``hay``
            # has ``lemma=hay`` (SD lexicalises "there is/are" as its own
            # headword) but ``related_lemma=haber`` (SD also flags it as a
            # conjugation of haber). Stamped on the entry here so
            # write_split_files reads it off without having to re-load the
            # surface cache separately.
            sd_entry = spanishdict_surface_cache.get(wl)
            if sd_entry:
                sd_conj = conjugation_lemma_from_possible_results(sd_entry)
                if sd_conj and sd_conj != (word_lemma or "").lower():
                    entry["related_lemma"] = sd_conj

            cognate_key = "%s|%s" % (word, word_lemma)
            cognate_obj = cognates.get(cognate_key)
            if isinstance(cognate_obj, (int, float)):
                cognate_obj = {"score": cognate_obj}
            elif cognate_obj is True:
                cognate_obj = {"score": 1.0}
            if cognate_obj:
                # The auto CogNet/similarity scorer produces junk for high-
                # frequency function words (estar|estar scores 1.0 via a false
                # "star" link), and cognate_score >= 0.85 hides the card in the
                # front end. Stamp it only when explicitly requested, so a
                # rebuild preserves live parity (the live index carries no
                # cognate_score) until the layer is cleaned — see the blast-
                # radius report in tool_8b_cognate_would_hide.py. The curated
                # is_transparent_cognate path (gemini flag) is ALWAYS kept: it's
                # the trustworthy signal already live on ~500 cards.
                if stamp_cognate_scores:
                    entry["cognate_score"] = cognate_obj["score"]
                    if cognate_obj.get("cognet"):
                        entry["cognet_cognate"] = True
                if cognate_obj.get("gemini"):
                    entry["is_transparent_cognate"] = True

            # Remainder-bucket toggle: drop SENSE_CYCLE / unassigned meaning
            # rows unless explicitly enabled. Keeps cards clean by default.
            if not emit_remainders and entry.get("meanings"):
                entry["meanings"] = [
                    m for m in entry["meanings"]
                    if m.get("pos") != "SENSE_CYCLE" and not m.get("unassigned")
                ]
                if not entry["meanings"]:
                    # Word had nothing BUT remainder rows — no useful card to
                    # build, skip the whole entry.
                    continue

            # Authoritative per-sense provenance keyed by stable sense_id, drawn
            # straight from the assignment layer (all word|lemma keys for this
            # surface, covering gap-fill orphan lemmas). write_split_files reads
            # it by master sense_id — robust to whichever path built the meaning.
            _prefix = "%s|" % word
            _entry_prov = {}
            for _lkey, _lval in lemma_assignments.items():
                if _lkey == "%s|%s" % (word, word_lemma) or _lkey.startswith(_prefix):
                    _entry_prov.update(resolve_sense_provenance(
                        _lval, prompt_registry,
                        min_prompt_tier=min_prompt_tier,
                        accepted_model_prompt_ids=accepted_model_prompt_ids,
                        prompt_preference=prompt_preference))
            if _entry_prov:
                entry["_sense_provenance"] = _entry_prov

            entries.append(entry)

    # --- Build MWE examples cache from lyrics ---
    # (Shared by both artist-specific and Wiktionary MWEs)
    line_info = {}
    for word, exs in examples_raw.items():
        for ex in exs:
            line = ex.get("spanish", "")
            if line and line not in line_info:
                sid = ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"]
                line_info[line] = {"song_id": sid, "title": ex.get("title", "")}
                for key in _EXAMPLE_PRIORITY_KEYS:
                    if key in ex:
                        line_info[line][key] = ex[key]

    # Unicode-aware word-boundary pattern: matches if character before/after
    # is NOT a Spanish letter (handles accented chars that \b misses)
    _SPANISH_LETTER = r'a-zA-ZáéíóúñüÁÉÍÓÚÑÜ'

    # Pattern entries from the clitic-placeholder bucket carry a "[PRON]" slot
    # that won't appear literally in any lyric line. When we see it, expand
    # to a regex alternation over the object/reflexive clitics so the same
    # function can surface example lines for "no [PRON] hagas" by matching
    # "no te hagas", "no me hagas", "no lo hagas", etc.
    _PRON_PLACEHOLDER_RE = re.compile(r'\[pron\]', re.IGNORECASE)
    _PRON_CLITIC_ALT = r'(?:me|te|se|le|les|nos|lo|la|los|las)'

    def _mwe_pattern(expression):
        tokens = str(expression or '').lower().split()
        body_parts = []
        for index, token in enumerate(tokens):
            if index:
                # Curated Caribbean forms often contain ``vo' a`` while the
                # original lyric displays ``vo'a``. Treat that one elision
                # boundary as optional whitespace; ordinary word boundaries
                # still require at least one space.
                separator = r'\s*' if tokens[index - 1].endswith(("'", "’")) else r'\s+'
                body_parts.append(separator)
            if _PRON_PLACEHOLDER_RE.fullmatch(token):
                body_parts.append(_PRON_CLITIC_ALT)
            else:
                body_parts.append(re.escape(token).replace("'", "['’]"))
        body = ''.join(body_parts)
        return re.compile(
            r'(?<![' + _SPANISH_LETTER + r'])' + body +
            r'(?![' + _SPANISH_LETTER + r'])',
            re.IGNORECASE,
        )

    def find_mwe_examples(expression, variants=None, detected_examples=None,
                          max_examples=3):
        """Return exact lyric evidence for a literal or morphological family."""
        variant_values = list((variants or {}).keys()) if isinstance(variants, dict) else list(variants or [])
        candidate_forms = []
        for value in [expression] + variant_values:
            value = str(value or '').strip()
            if value and value.lower() not in {form.lower() for form in candidate_forms}:
                candidate_forms.append(value)
        patterns = [(form, _mwe_pattern(form)) for form in candidate_forms]
        found = []
        seen = set()

        def append_example(line, info, matched_variant=None, matched_surface=None):
            key = line.strip().lower()
            if not key or key in seen:
                return
            seen.add(key)
            trans_info = translations.get(line, {})
            if isinstance(trans_info, str):
                english = trans_info
                translation_source = ""
            else:
                english = trans_info.get("english", "")
                translation_source = trans_info.get("source", "")
            ex_dict = {
                "song": info.get("song_id", ""),
                "song_name": info.get("title", ""),
                "spanish": line,
                "english": english,
            }
            if matched_variant:
                ex_dict["matched_variant"] = matched_variant
            if matched_surface:
                ex_dict["matched_surface"] = matched_surface
            if translation_source:
                ex_dict["translation_source"] = translation_source
            _copy_example_priority(info, ex_dict)
            ts_entry = ts_map.get(info.get("title", ""), {}).get(line)
            _copy_timestamp(ts_entry, ex_dict)
            found.append(ex_dict)

        # Artist detection now carries exact full-corpus evidence. Prefer it
        # over the old component-word sample, which could miss a valid phrase
        # merely because none of its words retained that particular line.
        for raw in detected_examples or []:
            line = raw.get("line") or raw.get("spanish") or ""
            if not line:
                continue
            raw_id = str(raw.get("id") or "")
            info = {
                "song_id": raw_id.split(":")[0] if ":" in raw_id else raw_id,
                "title": raw.get("title", ""),
            }
            for key in _EXAMPLE_PRIORITY_KEYS:
                if key in raw:
                    info[key] = raw[key]
            append_example(
                line, info, raw.get("matched_variant"), raw.get("matched_surface"))
            if len(found) >= max_examples:
                return found

        # Artist detection already supplied exact, full-corpus evidence. Do
        # not pad it with a looser component-word scan: that can turn a valid
        # dictionary phrase into the wrong construction (e.g. standalone
        # ``qué va`` versus ``qué va a pasar``).
        if found:
            return found

        for line, info in line_info.items():
            matched = next((form for form, pattern in patterns if pattern.search(line)), None)
            if matched:
                append_example(line, info, matched)
                if len(found) >= max_examples:
                    break
        return found

    # --- Mark most frequent lemma instance ---
    # Representative = highest raw corpus_count. NOTE: this misfires for
    # off-lemma homograph inflation — e.g. the `leer` card displays `lean`
    # because `lean` has corpus_count 24 (9/10 lines are the English drug
    # noun, only 1 is the verb "read"). Ranking by assigned-example evidence
    # instead was tried and REVERTED (2026-07-26): assigned counts are capped
    # per sense, so it can't distinguish `lean` (off-lemma) from `hacer`
    # (legit high-frequency, low-assignment) and it regressed ~80 lemmas
    # (hacer→hago, igual→iguales). The real fix is routing: separate the
    # English-loanword homograph so it never lands in `leer`'s group — then
    # this rule is correct. Tracked in TODO_PIPELINE.md (routing gate).
    lemma_groups = {}
    for entry in entries:
        lemma = entry.get("lemma", entry["word"]).lower()
        lemma_groups.setdefault(lemma, []).append(entry)
    for group in lemma_groups.values():
        for e in group:
            e["most_frequent_lemma_instance"] = False
        best = max(group, key=lambda e: e.get("corpus_count", 0))
        best["most_frequent_lemma_instance"] = True

    # --- Master vocabulary integration ---
    registry_path, registry_language = _card_registry_context(layers_dir)
    assign_ids_from_master(
        entries,
        master,
        registry_path=registry_path,
        language=registry_language,
        surface_cards=surface_cards,
    )
    entries = _coalesce_card_identities(entries, master)
    # Coalescing can combine corpus counts from aliases with different lemmas,
    # so re-elect each lemma family's representative from the final rows.
    lemma_groups = {}
    for entry in entries:
        lemma = entry.get("lemma", entry["word"]).lower()
        lemma_groups.setdefault(lemma, []).append(entry)
    for group in lemma_groups.values():
        for entry in group:
            entry["most_frequent_lemma_instance"] = False
        max(group, key=lambda entry: entry.get("corpus_count", 0))[
            "most_frequent_lemma_instance"] = True
    _stabilize_sense_identities(
        entries,
        master,
        registry_path.with_name("senses.json"),
        registry_language,
    )

    # Ensure each clitic has its own stub master entry so the clitic-layer
    # writer (below) can map clitic_word → master ID. Without this, only
    # clitics that happened to be in master from an earlier run are emitted;
    # any clitic detected fresh in this run gets dropped.
    if clitic_data:
        used_ids = set(master.keys())
        wl_existing = {(m["word"].lower(), m["lemma"].lower()) for m in master.values()}
        for clitic_word in clitic_data:
            key = (clitic_word.lower(), clitic_word.lower())
            if key in wl_existing:
                continue
            if surface_cards:
                # A clitic form is a surface like any other. Minting it from
                # word|lemma here is what left 492 six-hex IDs in an otherwise
                # re-keyed master, and it would also stop `soltarte` ever
                # matching the same surface in speech mode.
                cid = make_surface_id(clitic_word.lower(), used_ids)
            else:
                h = hashlib.md5(
                    (clitic_word + "|" + clitic_word).encode("utf-8")).hexdigest()
                cid = h[:6]
                if cid in used_ids:
                    for start in range(0, len(h) - 5):
                        cand = h[start:start + 6]
                        if cand not in used_ids:
                            cid = cand
                            break
            master[cid] = {
                "word": clitic_word,
                "lemma": clitic_word,
                "senses": [{"pos": "X", "translation": ""}],
                "is_english": False,
                "is_noise": False,
                "is_interjection": False,  # alias of is_noise; see schema_v2 notes
                "is_propernoun": False,
                "is_transparent_cognate": False,
                "display_form": None,
            }
            used_ids.add(cid)
            wl_existing.add(key)

    # Record merged clitic IDs on base verb master entries
    if clitic_data:
        wl_to_id = {}
        for mid, m in master.items():
            wl_to_id[(m["word"].lower(), m["lemma"].lower())] = mid
        for entry in entries:
            variants = entry.get("variants", [])
            if not variants:
                continue
            fid = entry["id"]
            merged_ids = {}
            for v in variants:
                # Clitic IDs use word|word or word|base as the key
                vid = wl_to_id.get((v.lower(), v.lower()))
                if not vid:
                    base = clitic_data.get(v, {}).get("base_verb", "")
                    vid = wl_to_id.get((v.lower(), base.lower()))
                if vid:
                    merged_ids[vid] = v
            if merged_ids:
                # is_noise / is_interjection are aliases (see schema_v2);
                # read either, write both so the master is consistent.
                noise_flag = entry.get("is_noise", entry.get("is_interjection", False))
                master.setdefault(fid, {
                    "word": entry["word"],
                    "lemma": entry["lemma"],
                    "senses": [],
                    "is_english": entry.get("is_english", False),
                    "is_noise": noise_flag,
                    "is_interjection": noise_flag,
                    "is_propernoun": entry.get("is_propernoun", False),
                    "is_transparent_cognate": entry.get("is_transparent_cognate", False),
                    "display_form": entry.get("display_form"),
                })
                master[fid].setdefault("merged_clitic_ids", {}).update(merged_ids)
                entry["merged_clitic_ids"] = merged_ids

    # Update master with new/updated entries
    new_master = 0
    new_senses = 0
    for entry in entries:
        fid = entry["id"]
        if fid not in master:
            # is_noise / is_interjection are aliases (see schema_v2 notes
            # above); read either, write both so the master is consistent.
            noise_flag = entry.get("is_noise", entry.get("is_interjection", False))
            master[fid] = {
                "word": entry["word"],
                "lemma": entry["lemma"],
                "senses": [],
                "is_english": entry.get("is_english", False),
                "is_noise": noise_flag,
                "is_interjection": noise_flag,
                "is_propernoun": entry.get("is_propernoun", False),
                "is_transparent_cognate": entry.get("is_transparent_cognate", False),
                "display_form": entry.get("display_form"),
            }
            new_master += 1

        m = master[fid]
        # Propagate flags TO master from current step-4 data.
        # For step-4-derived flags (is_english, is_noise, is_propernoun),
        # overwrite the master — the current routing data is authoritative and
        # stale True flags from previous builds must be cleared.
        # is_transparent_cognate is union-only (comes from cognates layer, not step 4).
        # is_noise/is_interjection mirror each other (schema_v2 alias).
        noise_flag = entry.get("is_noise", entry.get("is_interjection", False))
        m["is_english"] = entry.get("is_english", False)
        m["is_noise"] = noise_flag
        m["is_interjection"] = noise_flag
        m["is_propernoun"] = entry.get("is_propernoun", False)
        if entry.get("is_transparent_cognate", False):
            m["is_transparent_cognate"] = True
        # Only pull is_transparent_cognate from master (not step-4 derived)
        if m.get("is_transparent_cognate", False):
            entry["is_transparent_cognate"] = True
        if entry.get("display_form") and not m.get("display_form"):
            m["display_form"] = entry["display_form"]

        # Master senses are a union across artists — keyed by
        # (pos, normalized translation, normalized context). Context matters
        # because SpanishDict exposes sibling senses that share (pos, translation)
        # but disambiguate via the sub-sense context (e.g. decir "to say"
        # with contexts "to speak", "to give an opinion", "to be rumored").
        # Collapsing them loses the per-sense example buckets downstream.
        entry_meanings = entry.get("meanings", [])

        def _ctx_key(s):
            return (s.get("context") or "").strip().lower()

        # Canonicalise stored POS before keying. A master built before POS
        # normalization can hold a PROPER_NOUN sense that a freshly normalized
        # PROPN meaning would otherwise fail to match, appending a duplicate row
        # with the identical translation. Collapse any such twins in place.
        def _sense_key(s):
            return (normalize_pos(s.get("pos")),
                    normalize_translation(s.get("translation", "")),
                    _ctx_key(s))

        _deduped = []
        _seen = {}
        for s in m["senses"]:
            norm = normalize_pos(s.get("pos"))
            if norm and norm != s.get("pos"):
                s["pos"] = norm
            k = _sense_key(s)
            if k in _seen:
                merge_sense_identity(_seen[k], s)
                continue
            _seen[k] = s
            _deduped.append(s)
        m["senses"] = _deduped

        existing_keys = set(_seen.keys())
        existing_by_sense_id = {}
        for stored_sense in m["senses"]:
            for sense_id in [stored_sense.get("sense_id")] + list(
                    stored_sense.get("sense_id_aliases") or []):
                if sense_id:
                    existing_by_sense_id[sense_id] = stored_sense
        for meaning in entry_meanings:
            pos = normalize_pos(meaning.get("pos", "X")) or "X"
            if pos in ("X", "SENSE_CYCLE"):
                continue  # don't pollute master with fallback senses
            translation = meaning.get("translation", "")
            context = meaning.get("context")
            key = (pos, normalize_translation(translation), (context or "").strip().lower())
            incoming_ids = [meaning.get("sense_id")] + list(
                meaning.get("sense_id_aliases") or [])
            identity_match = next((
                existing_by_sense_id[sense_id]
                for sense_id in incoming_ids
                if sense_id in existing_by_sense_id
            ), None)
            if identity_match is not None:
                # Same persisted sense, revised label. The previous labels live
                # in the immutable menu/sense registry history; the active
                # master view should show the currently selected description.
                identity_match["pos"] = pos
                identity_match["translation"] = translation
                if context:
                    identity_match["context"] = context
                else:
                    identity_match.pop("context", None)
                if meaning.get("source"):
                    identity_match["source"] = meaning["source"]
                merge_sense_identity(identity_match, meaning)
                carry_sense_tags(identity_match, meaning)
                existing_keys.add(key)
                _seen[key] = identity_match
                for sense_id in incoming_ids:
                    if sense_id:
                        existing_by_sense_id[sense_id] = identity_match
                continue
            if key in existing_keys:
                existing_sense = _seen[key]
                merge_sense_identity(existing_sense, meaning)
                carry_sense_tags(existing_sense, meaning)
                if meaning.get("headword") and not existing_sense.get("headword"):
                    existing_sense["headword"] = meaning["headword"]
                continue
            s_entry = {"pos": pos, "translation": translation}
            carry_sense_identity(
                s_entry,
                meaning.get("sense_id"),
                meaning.get("sense_id_aliases") or [],
            )
            carry_sense_tags(s_entry, meaning)
            if context:
                s_entry["context"] = context
            src = meaning.get("source")
            if src:
                s_entry["source"] = src
            # SpanishDict's own headword for this sense. Without it the app has
            # no way to know that sense 915 of `mate` belongs to the lemma
            # `mate` and not to `matar`, so the card falls back to the upstream
            # inventory lemma and the two disagree. There must be one
            # lemmatisation, and the assigned sense is the one with evidence.
            hw = meaning.get("headword")
            if hw:
                s_entry["headword"] = hw
            m["senses"].append(s_entry)
            existing_keys.add(key)
            _seen[key] = s_entry
            for sense_id in [s_entry.get("sense_id")] + list(
                    s_entry.get("sense_id_aliases") or []):
                if sense_id:
                    existing_by_sense_id[sense_id] = s_entry
            new_senses += 1

    # Carry SpanishDict's headword onto every master sense, keyed by sense_id.
    # Done here as a post-pass rather than threaded through meaning construction
    # because there are several meaning-build paths and any one that missed it
    # would silently leave the card lemmatised by the upstream inventory layer
    # instead of by the sense that actually won -- which is how `mate` ended up
    # displaying lemma `matar` while its assigned sense is `mate`/NOUN
    # "checkmate". One lemmatisation, owned by the sense.
    _hw_by_sense_id = {}
    try:
        _raw_menu_hw = load_layer(
            artist_sense_menu_path(layers_dir, sense_source, prefer_new=False),
            "sense_menu", required=False) or {}
        for _w, _entries in (_raw_menu_hw or {}).items():
            for _e in (_entries or []):
                for _sid, _sv in ((_e or {}).get("senses") or {}).items():
                    if _sv.get("headword"):
                        _hw_by_sense_id[_sid] = _sv["headword"]
    except Exception as _exc:
        print("  (headword carry skipped: %s)" % _exc)
    _hw_set = 0
    for master_entry in master.values():
        for sense in master_entry.get("senses", []):
            if sense.get("headword"):
                continue
            for _sid in [sense.get("sense_id")] + list(sense.get("sense_id_aliases") or []):
                if _sid and _sid in _hw_by_sense_id:
                    sense["headword"] = _hw_by_sense_id[_sid]
                    _hw_set += 1
                    break
    if _hw_set:
        print("  Sense headwords carried onto master: %d" % _hw_set)

    # Some legacy union senses exist only in the shared master and therefore
    # have no current source-menu row to donate an ID. Mint a deterministic
    # fallback so every learnable artist sense has durable identity. If a
    # source ID becomes available in a future build, carry_sense_identity()
    # promotes it and retains this generated ID as a migration alias.
    generated_sense_ids = 0
    for master_entry in master.values():
        for sense in master_entry.get("senses", []):
            if sense.get("pos") in ("X", "SENSE_CYCLE") or sense.get("sense_id"):
                continue
            carry_sense_identity(
                sense,
                make_generated_sense_id(
                    "artist-master",
                    master_entry.get("word"),
                    master_entry.get("lemma"),
                    sense.get("pos"),
                    sense.get("translation"),
                    sense.get("context"),
                ),
            )
            generated_sense_ids += 1

    print("  Master: %d entries (+%d new), %d new senses, %d fallback IDs" % (
        len(master), new_master, new_senses, generated_sense_ids))

    # --- MWE annotation from shared layer (after IDs are assigned) ---
    MAX_MWES_PER_ENTRY = 10
    MAX_TRANSLATION_LEN = 100
    if mwe_by_word:
        mwe_examples_cache = {}
        mwe_count = 0
        for entry in entries:
            word_key = entry.get("word", "").lower()
            word_mwes = mwe_by_word.get(word_key, [])
            if not word_mwes:
                continue

            # Sort priority:
            #   0 — artist-sourced (curated or PMI from this artist's lyrics)
            #   1 — spanishdict (shared layer, scraped)
            #   2 — wiktionary / unclassified (shared layer, legacy)
            # Within each tier, higher count/corpus_freq wins.
            def mwe_sort_key(m):
                source = m.get("source") or ""
                if source.startswith("artist"):
                    priority = 0
                elif source == "spanishdict":
                    priority = 1
                else:
                    priority = 2
                freq = -(m.get("count", 0) or m.get("corpus_freq", 0))
                return (priority, freq)
            sorted_mwes = sorted(word_mwes, key=mwe_sort_key)

            memberships = []
            seen_exprs = set()
            for mwe in sorted_mwes:
                if len(memberships) >= MAX_MWES_PER_ENTRY:
                    break
                expr = mwe["expression"]
                if expr.lower() in seen_exprs:
                    continue

                # Expression rows are learner-facing teaching material. Raw
                # discovery candidates with no translation remain available
                # upstream, but do not consume one of the ten card slots.
                trans = mwe.get("translation") or ""
                if not trans:
                    continue
                seen_exprs.add(expr.lower())

                # Find lyric examples
                if expr not in mwe_examples_cache:
                    mwe_examples_cache[expr] = find_mwe_examples(
                        expr,
                        variants=mwe.get("variants"),
                        detected_examples=mwe.get("detected_examples"),
                    )

                # Truncate long translations
                if len(trans) > MAX_TRANSLATION_LEN:
                    parts = re.split(r'[;,]\s*', trans)
                    result = parts[0]
                    for part in parts[1:]:
                        candidate = result + ", " + part
                        if len(candidate) > MAX_TRANSLATION_LEN:
                            break
                        result = candidate
                    if len(result) > MAX_TRANSLATION_LEN:
                        result = result[:MAX_TRANSLATION_LEN - 3] + "..."
                    trans = result

                examples = mwe_examples_cache[expr]
                if not examples:
                    continue
                membership = {
                    "expression": expr,
                    "translation": trans,
                    "examples": examples,
                    "source": mwe.get("source", "wiktionary"),
                }
                for key in ("family", "variants", "variant_counts", "count",
                            "occurrence_count", "num_songs"):
                    if mwe.get(key) not in (None, "", [], {}):
                        membership[key] = mwe[key]
                # Two context tiers (see step_8a_assemble_vocabulary for the
                # canonical comment). ``context`` is real/scraped,
                # ``context_heuristic`` is regex-split from the quickdef.
                if mwe.get("context"):
                    membership["context"] = mwe["context"]
                if mwe.get("context_heuristic"):
                    membership["context_heuristic"] = mwe["context_heuristic"]
                memberships.append(membership)
            if memberships:
                entry["mwe_memberships"] = memberships
                mwe_count += 1
        print("  MWE annotation (shared layer): %d entries" % mwe_count)

    # --- Strip mwe_memberships from master (one-time cleanup) ---
    for m in master.values():
        m.pop("mwe_memberships", None)

    # --- Apply ranking ---
    if ranking:
        order = ranking.get("order", [])
        easiness_data = ranking.get("easiness", {})

        if order:
            # Ranking may be keyed by word (layer mode) or ID (legacy mode)
            # Try word-keyed first, fall back to ID-keyed
            word_to_entries = {}
            for e in entries:
                word_to_entries.setdefault(e["word"], []).append(e)
            id_to_entry = {e["id"]: e for e in entries}

            sorted_entries = []
            used = set()
            for key in order:
                if key in word_to_entries:
                    for entry in word_to_entries.get(key, []):
                        if id(entry) not in used:
                            sorted_entries.append(entry)
                            used.add(id(entry))
                    continue
                entry = id_to_entry.get(key)
                if entry and id(entry) not in used:
                    sorted_entries.append(entry)
                    used.add(id(entry))
            # Append any entries not in the ranking
            for e in entries:
                if id(e) not in used:
                    sorted_entries.append(e)
            entries = sorted_entries
            print("  Ranking applied: %d entries sorted" % len(entries))

        # Apply easiness scores and sort examples within meanings
        SENTINEL = 999999
        for entry in entries:
            # Easiness may be keyed by word or ID
            e_data = easiness_data.get(entry["word"], {}) or easiness_data.get(entry["id"], {})
            per_meaning = e_data.get("m", [])
            for m_idx, meaning in enumerate(entry.get("meanings", [])):
                examples = meaning.get("examples", [])
                if m_idx < len(per_meaning):
                    scores = per_meaning[m_idx]
                    for i, ex in enumerate(examples):
                        ex["easiness"] = scores[i] if i < len(scores) else SENTINEL
                else:
                    for ex in examples:
                        ex["easiness"] = SENTINEL
                examples.sort(key=lambda e: e.get("easiness", SENTINEL))
        print("  Easiness scores applied, examples sorted")

    return entries, master, clitic_data, examples_raw, translations, ts_map


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

def _example_line_key(example):
    return (example.get("target") or example.get("spanish") or "").strip().lower()


def _load_speech_fallbacks():
    """Return lemma -> compact, sense-labelled Speech examples.

    Artist Extra is deliberately a no-Gemini extension. Reuse the already
    assembled standard vocabulary instead of reclassifying one-off lyrics.
    The payload is independent of artist master-sense positions because the
    standard and artist sense arrays are allowed to evolve separately.
    """
    index_path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "vocabulary.index.json")
    examples_path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "vocabulary.examples.json")
    if not os.path.isfile(index_path) or not os.path.isfile(examples_path):
        return {}
    try:
        with open(index_path, encoding="utf-8") as f:
            speech_index = json.load(f)
        with open(examples_path, encoding="utf-8") as f:
            speech_examples = json.load(f)
    except (OSError, ValueError) as exc:
        print("  WARNING: Artist Extra Speech fallback unavailable: %s" % exc)
        return {}

    grouped = {}
    seen = {}
    for entry in speech_index:
        lemma = (entry.get("lemma") or entry.get("word") or "").strip().lower()
        if not lemma:
            continue
        split = speech_examples.get(entry.get("id"), {})
        buckets = split.get("m", []) if isinstance(split, dict) else []
        for meaning_index, meaning in enumerate(entry.get("meanings", [])):
            translation = (meaning.get("translation") or "").strip()
            if not translation or meaning_index >= len(buckets):
                continue
            examples = buckets[meaning_index] or []
            if not examples:
                continue
            pos = meaning.get("pos") or "X"
            context = meaning.get("context") or ""
            sense_key = (pos, translation.lower(), context.lower())
            lemma_senses = grouped.setdefault(lemma, {})
            if sense_key not in lemma_senses:
                sense = {"pos": pos, "translation": translation, "examples": []}
                if context:
                    sense["context"] = context
                lemma_senses[sense_key] = sense
                seen[(lemma, sense_key)] = set()
            sense = lemma_senses[sense_key]
            sense_seen = seen[(lemma, sense_key)]
            for raw_example in examples:
                key = _example_line_key(raw_example)
                if not key or key in sense_seen or len(sense["examples"]) >= 2:
                    continue
                sense_seen.add(key)
                example = dict(raw_example)
                example["source_mode"] = "speech"
                if entry.get("word"):
                    example["pooledFrom"] = entry["word"]
                sense["examples"].append(example)

    return {
        lemma: list(senses.values())[:6]
        for lemma, senses in grouped.items()
        if any(sense.get("examples") for sense in senses.values())
    }


def write_split_files(entries, master, vocab_path, master_path, clitic_data=None,
                      raw_examples=None, translations=None, timestamp_map=None,
                      build_contract=None):
    """Write compact index + examples aligned to master senses."""
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    index = []
    examples = {}
    raw_examples = raw_examples or {}
    translations = translations or {}
    timestamp_map = timestamp_map or {}
    speech_by_lemma = _load_speech_fallbacks()

    # Scope membership is a property of the lemma family, not the displayed
    # surface form. Count the same unique lyric lines used by pooled lemma
    # examples; if raw evidence is unavailable, fall back to summed corpus
    # counts so older/non-Spanish artist builds remain usable.
    lemma_lines = {}
    lemma_raw_examples = {}
    lemma_fallback_counts = {}
    for entry in entries:
        lemma = (entry.get("lemma") or entry.get("word") or "").strip().lower()
        if not lemma:
            continue
        lines = lemma_lines.setdefault(lemma, set())
        for example in raw_examples.get(entry.get("word", ""), []):
            key = _example_line_key(example)
            if key:
                lines.add(key)
                pooled = lemma_raw_examples.setdefault(lemma, [])
                if not any(_example_line_key(existing) == key for existing in pooled):
                    pooled.append(example)
        lemma_fallback_counts[lemma] = lemma_fallback_counts.get(lemma, 0) + int(entry.get("corpus_count") or 0)

    lemma_example_counts = {
        lemma: len(lines) if lines else lemma_fallback_counts.get(lemma, 0)
        for lemma, lines in lemma_lines.items()
    }

    # Build clitic lookup: base_verb_word -> [(clitic_word, clitic_info), ...]
    clitics_by_base = {}
    if clitic_data:
        for cword, cinfo in clitic_data.items():
            base = cinfo.get("base_verb", "")
            clitics_by_base.setdefault(base, []).append((cword, cinfo))

    for entry in entries:
        fid = entry.get("id")
        if not fid:
            continue
        m = master.get(fid)
        if not m:
            continue

        sense_freq = []
        sense_methods = []
        sense_prompt_ids = []
        sense_run_ts = []
        # Model confidence per sense, parallel to sense_prompt_ids. Emitted at
        # index level rather than left only on examples, because the card's
        # meaning is rebuilt from the index and anything not carried there is
        # invisible to the provenance panel.
        sense_confidence = []
        sense_band = []
        sense_model_proposed = []
        sense_examples = []
        total_ex = 0

        def _ctx_key(s):
            return (s.get("context") or "").strip().lower()

        # Provenance is keyed by stable sense_id, NOT by the (pos, translation,
        # context) string match used for examples below — that match is lossy
        # (cleaned/curated glosses drift) and misses the meaning-build paths that
        # never stamp prompt_id, dropping provenance on ~90% of assigned senses.
        # entry["_sense_provenance"] comes straight from the assignment layer.
        entry_prov = entry.get("_sense_provenance") or {}

        for sense in m.get("senses", []):
            sense_ctx = _ctx_key(sense)
            matching = None
            # First pass: exact match on (pos, translation, context).
            for meaning in entry.get("meanings", []):
                if (meaning.get("pos") == sense["pos"]
                        and meaning.get("translation") == sense["translation"]
                        and _ctx_key(meaning) == sense_ctx):
                    matching = meaning
                    break
            # Fallback: match on (pos, translation) only when the master sense
            # has no context. Avoids siblings with distinct contexts stealing
            # each other's examples.
            if matching is None and not sense_ctx:
                for meaning in entry.get("meanings", []):
                    if (meaning.get("pos") == sense["pos"]
                            and meaning.get("translation") == sense["translation"]
                            and not _ctx_key(meaning)):
                        matching = meaning
                        break
            exs = matching.get("examples", []) if matching else []
            sense_examples.append(exs)
            total_ex += len(exs)
            sense_methods.append(matching.get("assignment_method") if matching else None)
            # Best (highest) confidence among the examples assigned to this
            # sense, with the band that example carried. A sense is as trusted
            # as its strongest evidence.
            _pairs = [(e.get("confidence"), e.get("band")) for e in exs
                      if isinstance(e, dict) and e.get("confidence") is not None]
            if _pairs:
                _c, _b = max(_pairs, key=lambda pair: pair[0])
                sense_confidence.append(round(float(_c), 4))
                sense_band.append(_b)
            else:
                sense_confidence.append(None)
                sense_band.append(None)
            # Provenance aligned per-sense (parallel to sense_methods): which
            # prompt/model produced this sense, for the card's info panel.
            # Primary source is the authoritative layer map keyed by sense_id
            # (catches gap-fill discoveries whose id is the master id); fall back
            # to the string-matched meaning's own stamp (catches resolve-path
            # menu-pick meanings). Fallback-display senses (keyword-filtered or
            # unclassified) legitimately have neither -> None.
            _prov = entry_prov.get(sense.get("sense_id"))
            if _prov:
                sense_prompt_ids.append(_prov.get("prompt_id"))
                sense_run_ts.append(_prov.get("run_ts"))
                sense_model_proposed.append(bool(_prov.get("model_proposed")))
            elif matching and matching.get("prompt_id"):
                sense_prompt_ids.append(matching.get("prompt_id"))
                sense_run_ts.append(matching.get("run_ts"))
                _method = matching.get("assignment_method") or ""
                sense_model_proposed.append(
                    _method.startswith("lexical-gap-fill-") or _method == "gap-fill"
                )
            else:
                sense_prompt_ids.append(None)
                sense_run_ts.append(None)
                sense_model_proposed.append(False)

        for exs in sense_examples:
            sense_freq.append(round(len(exs) / total_ex, 2) if total_ex > 0 else 0)

        # MWE memberships from entry (Wiktionary + artist-specific, merged at build time)
        entry_mwes = entry.get("mwe_memberships", [])
        mwe_examples = [mwe.get("examples", []) for mwe in entry_mwes]

        idx_entry = {
            "id": fid,
            "corpus_count": entry.get("corpus_count", 0),
            "lemma_example_count": lemma_example_counts.get(
                (entry.get("lemma") or entry.get("word") or "").strip().lower(),
                entry.get("corpus_count", 0),
            ),
            "most_frequent_lemma_instance": entry.get("most_frequent_lemma_instance", False),
            "sense_frequencies": sense_freq,
        }
        # Routing is artist-local: the same surface may be a name/noise in one
        # corpus and ordinary Spanish in another. Carry the resolved category
        # in the artist index rather than relying on the shared master.
        if entry.get("extra_category"):
            idx_entry["extra_category"] = entry["extra_category"]
        if any(sense_methods):
            idx_entry["sense_methods"] = sense_methods
        if any(c is not None for c in sense_confidence):
            idx_entry["sense_confidence"] = sense_confidence
            idx_entry["sense_band"] = sense_band
        if any(sense_prompt_ids):
            idx_entry["sense_prompt_ids"] = sense_prompt_ids
        if any(sense_run_ts):
            idx_entry["sense_run_ts"] = sense_run_ts
        if any(sense_model_proposed):
            idx_entry["sense_model_proposed"] = sense_model_proposed
        if any(mg.get("unassigned") for mg in entry.get("meanings", [])):
            idx_entry["unassigned"] = True
        if entry.get("cognate_score") is not None:
            idx_entry["cognate_score"] = entry["cognate_score"]
        if entry.get("cognet_cognate"):
            idx_entry["cognet_cognate"] = True
        if entry.get("variants"):
            idx_entry["variants"] = entry["variants"]
        if entry.get("morphology"):
            idx_entry["morphology"] = entry["morphology"]
        if entry.get("synonyms"):
            idx_entry["synonyms"] = entry["synonyms"]
        if entry.get("antonyms"):
            idx_entry["antonyms"] = entry["antonyms"]
        # related_lemma was stamped earlier in assemble_from_layers where
        # the surface cache is loaded. Just pass it through here.
        if entry.get("related_lemma"):
            idx_entry["related_lemma"] = entry["related_lemma"]
        if entry.get("derivation_relation"):
            idx_entry["derivation_relation"] = entry["derivation_relation"]
        if entry_mwes:
            idx_entry["mwe_memberships"] = [
                {**{"expression": mwe["expression"],
                    "translation": mwe.get("translation", ""),
                    # Already stamped by the annotation pass above (which
                    # defaults the unstamped shared layer to "wiktionary"), so
                    # this fallback should never fire. Kept identical to that
                    # default so a hand-edited entry cannot mint a bogus
                    # artist/corpus provenance for a dictionary phrase.
                    "source": mwe.get("source") or "wiktionary"},
                 **{key: mwe[key] for key in (
                     "family", "variants", "variant_counts", "count",
                     "occurrence_count", "num_songs") if mwe.get(key) not in (None, "", [], {})},
                 **({"context": mwe["context"]} if mwe.get("context") else {}),
                 **({"context_heuristic": mwe["context_heuristic"]} if mwe.get("context_heuristic") else {})}
                for mwe in entry_mwes
            ]
        # Clitic memberships (parallel to MWEs)
        entry_clitics = clitics_by_base.get(entry.get("word", "").lower(), [])
        clitic_examples = []
        if entry_clitics:
            idx_entry["clitic_memberships"] = []
            for cword, cinfo in entry_clitics:
                idx_entry["clitic_memberships"].append({
                    "form": cword,
                    "translation": cinfo.get("translation", ""),
                    "corpus_count": cinfo.get("corpus_count", 0),
                })
                clitic_examples.append(cinfo.get("examples", []))
        # SENSE_CYCLE meanings (unassigned senses grouped by POS).
        # Single unassigned senses (NOUN, PRON, etc.) are already represented in the
        # master sense list via sense_frequencies, so they are NOT duplicated here.
        sense_cycle_meanings = [mg for mg in entry.get("meanings", []) if mg.get("pos") == "SENSE_CYCLE"]
        sense_cycle_examples = []
        if sense_cycle_meanings:
            idx_entry["sense_cycles"] = []
            for mg in sense_cycle_meanings:
                idx_entry["sense_cycles"].append({
                    "pos": "SENSE_CYCLE",
                    "cycle_pos": mg.get("cycle_pos", "X"),
                    "translation": mg.get("translation", ""),
                    "allSenses": mg.get("allSenses", []),
                })
                sense_cycle_examples.append(mg.get("examples", []))
        index.append(idx_entry)

        ex_entry = {"m": sense_examples}
        if any(mwe_examples):
            ex_entry["w"] = mwe_examples
        if any(clitic_examples):
            ex_entry["c"] = clitic_examples
        if any(sense_cycle_examples):
            ex_entry["s"] = sense_cycle_examples

        lemma_key = (entry.get("lemma") or entry.get("word") or "").strip().lower()
        if (int(entry.get("corpus_count") or 0) <= 1
                or lemma_example_counts.get(lemma_key, 0) <= 1):
            # Retain one-off surface evidence even when the lemma family is
            # recurring. Also cover an Extra lemma repeated several times in
            # one identical lyric line: its token count can exceed one even
            # though its unique-line evidence (the scope boundary) is one.
            extra_lyrics = []
            lyric_seen = set()
            source_raw_examples = raw_examples.get(entry.get("word", ""), [])
            if not source_raw_examples and lemma_example_counts.get(lemma_key, 0) <= 1:
                source_raw_examples = lemma_raw_examples.get(lemma_key, [])
            for raw_example in source_raw_examples:
                line = raw_example.get("spanish", "")
                key = line.strip().lower()
                if not key or key in lyric_seen:
                    continue
                lyric_seen.add(key)
                trans_info = translations.get(line, {})
                if isinstance(trans_info, str):
                    english = trans_info
                    translation_source = ""
                else:
                    english = trans_info.get("english", "")
                    translation_source = trans_info.get("source", "")
                formatted = {
                    "song": raw_example.get("id", "").split(":")[0],
                    "song_name": raw_example.get("title", ""),
                    "spanish": line,
                    "english": english,
                    "source_mode": "lyrics",
                }
                _copy_example_surface(raw_example, formatted, entry.get("word", ""))
                if translation_source:
                    formatted["translation_source"] = translation_source
                _copy_example_priority(raw_example, formatted)
                _copy_timestamp(timestamp_map.get(raw_example.get("title", ""), {}).get(line), formatted)
                extra_lyrics.append(formatted)
            if extra_lyrics:
                ex_entry["r"] = extra_lyrics
            speech_senses = speech_by_lemma.get(lemma_key, [])
            if speech_senses:
                ex_entry["p"] = speech_senses
        examples[fid] = ex_entry

    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    write_sidecar(index_path, make_meta(
        "assemble_artist_vocabulary", STEP_VERSION,
        extra=build_contract or None))
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)
    write_sidecar(examples_path, make_meta(
        "assemble_artist_vocabulary", STEP_VERSION,
        extra=build_contract or None))

    # Write updated master
    os.makedirs(os.path.dirname(master_path), exist_ok=True)
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False)
    write_sidecar(master_path, make_meta("assemble_artist_vocabulary", STEP_VERSION, extra={"output": "master"}))

    idx_size = os.path.getsize(index_path)
    ex_size = os.path.getsize(examples_path)
    print("  Split files written:")
    print("    %s: %s bytes" % (index_path, "{:,}".format(idx_size)))
    print("    %s: %s bytes" % (examples_path, "{:,}".format(ex_size)))
    print("  Master: %d entries -> %s" % (len(master), master_path))
    return {"index": index_path, "examples": examples_path}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build artist vocabulary from layers")
    add_artist_arg(parser)
    parser.add_argument("--master-path", type=str, default=None,
                        help="Path to shared master vocabulary (default: "
                             "Artists/<lang>/vocabulary_master.json, derived from --artist-dir)")
    parser.add_argument(
        "--sense-source", default="spanishdict",
        help="Sense adapter/source filename stem (default: spanishdict). Custom "
             "and menu-free sources are accepted when their assignment layer exists.",
    )
    parser.add_argument("--surface-cards", action="store_true",
                        help="Mint new card IDs from the surface form alone, "
                             "matching speech mode. Existing cards already "
                             "resolve to their surface ID once the registry "
                             "migration has run; this covers surfaces the "
                             "registry has not seen before.")
    parser.add_argument("--remainders", action="store_true",
                        help="Emit SENSE_CYCLE remainder buckets for unassigned examples "
                             "(default: off — cleaner cards, but unassigned examples are dropped)")
    parser.add_argument("--min-priority", type=int, default=None,
                        help="Drop assignments whose method priority is below N. "
                             "Dropped examples become orphans (eligible for remainders "
                             "when --remainders is on). Default comes from "
                             "config/config.json languages.<lang>.pipelineDefaults.minPriority "
                             "(Spanish: 50; unset languages: 0 = keep everything). "
                             "Useful values: 15 (skip keyword-tier), 30 (biencoder+), "
                             "50 (Gemini only).")
    parser.add_argument("--prompt-policy", default=CURRENT_SD_POLICY_ID,
                        help="Named prompt acceptance policy from "
                             "config/prompt_registry.json. Default: %s."
                             % CURRENT_SD_POLICY_ID)
    parser.add_argument("--min-prompt-tier", type=int, default=0,
                        help="Deprecated compatibility override for builds "
                             "without --prompt-policy. Numeric prompt tiers are "
                             "not used by the default Artist build.")
    parser.add_argument("--stamp-cognate-scores", action="store_true",
                        help="Stamp the auto cognate_score from the cognates.json "
                             "layer onto entries. OFF by default: that scorer "
                             "(CogNet/similarity) mislabels high-frequency function "
                             "words (e.g. estar=1.0), and the front end hides any "
                             "card scoring >= 0.85 — a fresh rebuild would silently "
                             "hide ~440 currently-visible cards incl. all of estar. "
                             "Leaving it off preserves live parity; the curated "
                             "is_transparent_cognate hides are unaffected. Run "
                             "tool_8b_cognate_would_hide.py to review the blast "
                             "radius before enabling.")
    parser.add_argument("--output-suffix", type=str, default="",
                        help="Append to output basenames (e.g. _wikt) so this run "
                             "writes a PARALLEL deck — monolith/index/examples/clitic "
                             "layer get the suffix, and --master-path defaults to "
                             "vocabulary_master{suffix}.json. The live deck files are "
                             "not touched. Used for the Wiktionary sense-port "
                             "comparison (docs/design/artist_sense_pipeline.md).")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    vocab_path = os.path.join(artist_dir, config["vocabulary_file"])
    if args.output_suffix:
        stem, ext = os.path.splitext(vocab_path)
        vocab_path = stem + args.output_suffix + ext

    # Resolve --min-priority default from language config (artist.json → language).
    # Spanish defaults to 50 (Gemini coverage); missing/unset languages default to 0.
    language = (config.get("language") or "spanish").lower()
    if args.min_priority is None:
        args.min_priority = get_default_min_priority(language, fallback=0)
        print("min-priority: %d (from config/config.json: languages.%s.pipelineDefaults)"
              % (args.min_priority, language))
    else:
        print("min-priority: %d (from --min-priority flag)" % args.min_priority)

    artists_dir = os.path.dirname(artist_dir)
    master_path = args.master_path or os.path.join(
        artists_dir, "vocabulary_master%s.json" % args.output_suffix)
    layers_dir = os.path.join(artist_dir, "data", "layers")
    curated_path = os.path.join(artist_dir, "data", "llm_analysis", "curated_translations.json")
    build_contract = active_evidence_build_contract(
        artist_dir, sense_source=args.sense_source)
    if build_contract:
        print("Evidence build contract: %s / %s" % (
            build_contract["ledger_run"], build_contract["corpus_profile_hash"]))

    # Load master
    master = {}
    if os.path.isfile(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            master = json.load(f)
        print("Loaded master: %d entries" % len(master))
    else:
        print("No master vocabulary — will create.")

    # Assemble from layers
    print("Sense source: %s" % args.sense_source)
    skip_words_path = os.path.join(artist_dir, "data", "known_vocab", "word_routing.json")
    entries, master, clitic_data, raw_examples, translations, timestamp_map = assemble_from_layers(
        layers_dir, master, curated_path,
        sense_source=args.sense_source,
        skip_words_path=skip_words_path,
        emit_remainders=args.remainders,
        min_priority=args.min_priority,
        min_prompt_tier=args.min_prompt_tier,
        prompt_policy_id=args.prompt_policy,
        stamp_cognate_scores=args.stamp_cognate_scores,
        surface_cards=args.surface_cards)

    # Write monolith (debugging)
    os.makedirs(os.path.dirname(vocab_path), exist_ok=True)
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    write_sidecar(vocab_path, make_meta(
        "assemble_artist_vocabulary", STEP_VERSION,
        extra=build_contract or None))
    print("  Monolith: %d entries -> %s" % (len(entries), vocab_path))

    # Write clitic layer file (MWE-style, keyed by hex ID)
    if clitic_data:
        master_wl_to_id = {}
        for mid, m in master.items():
            master_wl_to_id[(m["word"].lower(), m["lemma"].lower())] = mid
        clitic_by_id = {}
        id_migration = {}
        for clitic_word, info in clitic_data.items():
            base = info["base_verb"]
            clitic_id = master_wl_to_id.get((clitic_word, clitic_word))
            if not clitic_id:
                clitic_id = master_wl_to_id.get((clitic_word, base))
            base_id = master_wl_to_id.get((base, base))
            if clitic_id:
                info["id"] = clitic_id
                if base_id:
                    info["base_id"] = base_id
                    id_migration[clitic_id] = base_id
                clitic_by_id[clitic_id] = info
        clitic_path = os.path.join(layers_dir, "clitic_forms%s.json" % args.output_suffix)
        with open(clitic_path, "w", encoding="utf-8") as f:
            json.dump(clitic_by_id, f, ensure_ascii=False, indent=2)
        migration_path = os.path.join(layers_dir, "archive",
                                      "clitic_id_migration%s.json" % args.output_suffix)
        os.makedirs(os.path.dirname(migration_path), exist_ok=True)
        with open(migration_path, "w", encoding="utf-8") as f:
            json.dump(id_migration, f, ensure_ascii=False, indent=2)
        print("  Clitic forms: %d entries -> %s" % (len(clitic_by_id), clitic_path))
        print("  ID migration: %d mappings -> %s" % (len(id_migration), migration_path))

    # Write split files
    split_paths = write_split_files(
        entries, master, vocab_path, master_path, clitic_data,
        raw_examples=raw_examples,
        translations=translations,
        timestamp_map=timestamp_map,
        build_contract=build_contract,
    )

    if build_contract:
        evidence_dir = os.path.join(artist_dir, "data", "evidence")
        output_paths = {"monolith": vocab_path, **split_paths}
        for output_name, output_path in output_paths.items():
            with open(output_path, encoding="utf-8") as handle:
                output_payload = json.load(handle)
            archive_json_artifact(
                evidence_dir,
                "final_deck/%s" % output_name,
                output_payload,
                language=language,
                adapter={"name": "artist-step-8b", "version": STEP_VERSION},
                inputs=build_contract,
                config={
                    "sense_source": args.sense_source,
                    "min_priority": args.min_priority,
                    "remainders": bool(args.remainders),
                    "output_suffix": args.output_suffix,
                },
            )

    print("Done!")


if __name__ == "__main__":
    main()
