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
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402
from pipeline.util_6a_assignment_format import load_assignments, resolve_best_per_example  # noqa: E402

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "monolith + index + examples + master update + clitic layer",
}
from util_8a_assembly_helpers import split_count_proportionally

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(os.path.dirname(os.path.dirname(SCRIPTS_DIR)), ".venv", "bin", "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


# Keyword-only threshold for unassigned flag (method priority at or below this = fallback)
KEYWORD_PRIORITY_THRESHOLD = 15  # keyword and pos-keyword


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


# ---------------------------------------------------------------------------
# ID assignment (same logic as 6_llm_analyze.py)
# ---------------------------------------------------------------------------

def assign_ids_from_master(entries, master):
    """Assign 6-char hex IDs. Existing words reuse master IDs, new words get fresh ones."""
    wl_to_id = {}
    for mid, mentry in master.items():
        wl_to_id[(mentry["word"], mentry["lemma"])] = mid

    used = set(master.keys())
    for entry in entries:
        wl = (entry["word"], entry["lemma"])
        if wl in wl_to_id:
            entry["id"] = wl_to_id[wl]
        else:
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
            used.add(final_id)
            entry["id"] = final_id



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
# Assembly
# ---------------------------------------------------------------------------

def assemble_from_layers(layers_dir, master, curated_translations_path=None,
                         sense_source="wiktionary", skip_words_path=None,
                         emit_remainders=False, min_priority=0):
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
    inventory = load_layer(os.path.join(layers_dir, "word_inventory.json"), "word_inventory")
    examples_raw = load_layer(os.path.join(layers_dir, "examples_raw.json"), "examples_raw")
    translations = load_layer(os.path.join(layers_dir, "example_translations.json"), "example_translations")
    # Sense menu (definitions) + assignments (example→sense mappings)
    raw_menu = load_layer(
        artist_sense_menu_path(layers_dir, sense_source, prefer_new=False),
        "sense_menu", required=False,
    )
    senses = normalize_artist_sense_menu(raw_menu) if raw_menu else {}
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
    skip_intj = set()
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
        for w in exclude.get("interjections", []):
            skip_intj.add(w.lower() if isinstance(w, str) else w)
        if clitic_merge:
            print("  clitic_merge: %d words (%d orphans → synthetic infinitive)" %
                  (len(clitic_merge), len(clitic_orphans)))
        print("  routing flags: %d english, %d propn, %d intj" %
              (len(skip_english), len(skip_propn), len(skip_intj)))

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
                ts_entry = ts_map.get(ex.get("title", ""), {}).get(spanish)
                if ts_entry:
                    ex_dict["timestamp_ms"] = ts_entry["ms"]
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
            }
            grouped.append(group)
            for sid in group["sense_by_id"]:
                sid_to_group[sid] = group

        lemma_key_to_group = {"%s|%s" % (word, g["lemma"]): g for g in grouped}

        if lemma_assignments and lemma_key_to_group:
            for lemma_key, group in lemma_key_to_group.items():
                raw_group_assignments = lemma_assignments.get(lemma_key, {})
                if isinstance(raw_group_assignments, dict) and raw_group_assignments:
                    per_sense = resolve_best_per_example(raw_group_assignments, min_priority=min_priority)
                    sid_meta = _collect_sid_meta(raw_group_assignments, per_sense)
                elif isinstance(raw_group_assignments, list) and raw_group_assignments:
                    # Legacy flat-list fallback: treat as one pseudo-method.
                    as_dict = {"legacy": raw_group_assignments}
                    per_sense = resolve_best_per_example(as_dict, min_priority=min_priority)
                    sid_meta = _collect_sid_meta(as_dict, per_sense)
                else:
                    continue
                for sid, ex_list in per_sense.items():
                    if sid not in group["sense_by_id"]:
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
                per_sense = resolve_best_per_example(raw_assignments, min_priority=min_priority)
                sid_meta = _collect_sid_meta(raw_assignments, per_sense)
            else:
                as_dict = {"legacy": raw_assignments}
                per_sense = resolve_best_per_example(as_dict, min_priority=min_priority)
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
            fallback_analysis = resolve_analysis_for_assignments(senses, word, raw_assignments)
            word_senses_raw = fallback_analysis.get("senses")
            # Build per-sense assignments preserving inline metadata (pos,
            # translation, lemma, source) — used by the gap-fill branch when
            # there's no menu entry.
            fallback_assignments = []
            if isinstance(raw_assignments, dict) and raw_assignments:
                per_sense = resolve_best_per_example(raw_assignments, min_priority=min_priority)
                sid_meta = _collect_sid_meta(raw_assignments, per_sense)
                for sid, ex_list in per_sense.items():
                    entry = {"sense": sid, "examples": ex_list}
                    entry.update(sid_meta.get(sid, {}))
                    fallback_assignments.append(entry)
            elif isinstance(raw_assignments, list):
                fallback_assignments = raw_assignments
            grouped = [{
                "lemma": fallback_analysis.get("headword", fallback_analysis.get("lemma", word)),
                "sense_by_id": word_senses_raw if isinstance(word_senses_raw, dict) else {},
                "word_senses": list(word_senses_raw.values()) if isinstance(word_senses_raw, dict) else (word_senses_raw or []),
                "assignments": fallback_assignments,
            }]

        # Get raw examples for this word
        raw_examples = examples_raw.get(word, [])

        # Apply POS-based unassigned-example routing from step 7a.
        # For each group (analysis), attach the list of raw-example indices
        # that step 7a routed to that lemma_key based on spaCy POS matching.
        for g in grouped:
            lemma_key = "%s|%s" % (word, g.get("lemma", word))
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
            word_lemma = group.get("lemma", word)
            sense_by_id = group.get("sense_by_id")
            word_senses = group.get("word_senses")
            word_assignments = group.get("assignments", [])

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
                    for entry in ex_entries:
                        # Post-refactor: entries are {"ex_idx", "method"} dicts
                        # so each example can carry its own per-example method.
                        # Tolerate the legacy raw-int form for old data.
                        if isinstance(entry, dict):
                            ex_idx = entry.get("ex_idx")
                            ex_method = entry.get("method")
                        else:
                            ex_idx = entry
                            ex_method = None
                        if ex_idx is None or ex_idx >= len(raw_examples):
                            continue
                        raw_ex = raw_examples[ex_idx]
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
                        score_entry = translation_scores.get(spanish, {})
                        if isinstance(score_entry, dict) and "score" in score_entry:
                            ex_dict["translation_quality"] = score_entry["score"]
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        if ts_entry:
                            ex_dict["timestamp_ms"] = ts_entry["ms"]
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
                    src = sense.get("source")
                    if src:
                        meaning["source"] = src
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
                    if methods_in_meaning and all(
                        0 < METHOD_PRIORITY.get(m, 0) <= KEYWORD_PRIORITY_THRESHOLD
                        for m in methods_in_meaning
                    ):
                        meaning["assignment_method"] = max(
                            methods_in_meaning,
                            key=lambda m: METHOD_PRIORITY.get(m, 0))
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
                        spanish = raw_ex.get("spanish", "")
                        trans_info = translations.get(spanish, {})
                        ex_dict = {
                            "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                            "song_name": raw_ex.get("title", ""),
                            "spanish": spanish,
                            "english": trans_info.get("english", ""),
                            "translation_source": trans_info.get("source", ""),
                        }
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        if ts_entry:
                            ex_dict["timestamp_ms"] = ts_entry["ms"]
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
                    for s in word_senses:
                        key = (s.get("pos", ""), s.get("translation", ""))
                        if key not in all_word_senses_deduped:
                            all_word_senses_deduped[key] = s

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

                        all_senses = [{"pos": s["pos"], "translation": s["translation"]}
                                      for s in senses_for_pos]

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
                    spanish = raw_ex.get("spanish", "")
                    trans_info = translations.get(spanish, {})
                    ex_dict = {
                        "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                        "song_name": raw_ex.get("title", ""),
                        "spanish": spanish,
                        "english": trans_info.get("english", ""),
                        "translation_source": trans_info.get("source", ""),
                    }
                    ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                    if ts_entry:
                        ex_dict["timestamp_ms"] = ts_entry["ms"]
                    all_examples.append(ex_dict)

                if len(word_senses) == 1:
                    # Single sense — all examples on it (auto-level, not unassigned)
                    translation = word_senses[0]["translation"]
                    if curated_key in curated:
                        translation = curated[curated_key]
                    single_meaning = {
                        "pos": word_senses[0]["pos"],
                        "translation": translation,
                        "frequency": "1.00",
                        "examples": all_examples,
                    }
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
                    for s in word_senses:
                        key = (s.get("pos", ""), s.get("translation", ""))
                        if key not in seen:
                            seen.add(key)
                            unique_senses.append(s)

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
                            src = senses_for_pos[0].get("source")
                            if src:
                                single_row["source"] = src
                            meanings.append(single_row)
                        else:
                            # Multiple senses for this POS — SENSE_CYCLE row
                            meanings.append({
                                "pos": "SENSE_CYCLE",
                                "translation": senses_for_pos[0]["translation"],
                                "frequency": "%.2f" % (1.0 / len(pos_list)),
                                "examples": cycle_examples,
                                "unassigned": True,
                                "cycle_pos": pos_key,
                                "allSenses": [{"pos": s["pos"], "translation": s["translation"]}
                                              for s in senses_for_pos],
                        })
            elif word_assignments and any(a.get("translation") for a in word_assignments):
                total_assigned = sum(len(a.get("examples", [])) for a in word_assignments) or 1
                for assignment in word_assignments:
                    pos = assignment.get("pos", "X")
                    translation = assignment.get("translation", "")
                    ex_entries = assignment.get("examples", [])
                    meaning_examples = []
                    methods_in_meaning = set()
                    for entry in ex_entries:
                        if isinstance(entry, dict):
                            ex_idx = entry.get("ex_idx")
                            ex_method = entry.get("method")
                        else:
                            ex_idx = entry
                            ex_method = None
                        if ex_idx is None or ex_idx >= len(raw_examples):
                            continue
                        raw_ex = raw_examples[ex_idx]
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
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        if ts_entry:
                            ex_dict["timestamp_ms"] = ts_entry["ms"]
                        meaning_examples.append(ex_dict)
                    freq = "%.2f" % (len(ex_entries) / total_assigned) if total_assigned > 0 else "1.00"
                    meaning = {
                        "pos": pos,
                        "translation": translation,
                        "frequency": freq,
                        "examples": meaning_examples,
                    }
                    src = assignment.get("source")
                    if src:
                        meaning["source"] = src
                    if methods_in_meaning and all(
                        0 < METHOD_PRIORITY.get(m, 0) <= KEYWORD_PRIORITY_THRESHOLD
                        for m in methods_in_meaning
                    ):
                        meaning["assignment_method"] = max(
                            methods_in_meaning,
                            key=lambda m: METHOD_PRIORITY.get(m, 0))
                    meanings.append(meaning)
            else:
                curated_key = "%s|%s" % (word.lower(), word_lemma)
                translation = curated.get(curated_key, "")
                fallback_examples = []
                if raw_examples:
                    raw_ex = raw_examples[0]
                    spanish = raw_ex.get("spanish", "")
                    trans_info = translations.get(spanish, {})
                    ex_dict = {
                        "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                        "song_name": raw_ex.get("title", ""),
                        "spanish": spanish,
                        "english": trans_info.get("english", ""),
                        "translation_source": trans_info.get("source", ""),
                    }
                    ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                    if ts_entry:
                        ex_dict["timestamp_ms"] = ts_entry["ms"]
                    fallback_examples.append(ex_dict)
                meanings.append({
                    "pos": "X",
                    "translation": translation,
                    "frequency": "1.00",
                    "examples": fallback_examples,
                })

            morphology = None
            if word.lower() != word_lemma.lower() and conj_reverse:
                candidates = conj_reverse.get(word.lower(), [])
                matches = [{"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                           for c in candidates if c["lemma"] == word_lemma.lower()]
                if len(matches) == 1:
                    morphology = matches[0]
                elif len(matches) > 1:
                    morphology = matches
            elif word.lower() == word_lemma.lower():
                has_verb = word_senses and any(s.get("pos") == "VERB" for s in word_senses)
                if has_verb:
                    morphology = {"mood": "infinitivo"}

            has_wikt = bool(word_senses and word_assignments and isinstance(raw_assignments, dict))
            wl = word.lower()
            entry = {
                "id": "",
                "word": word,
                "lemma": word_lemma,
                "meanings": meanings,
                "most_frequent_lemma_instance": True,
                "is_english": wl in skip_english,
                "is_interjection": wl in skip_intj,
                "is_propernoun": wl in skip_propn,
                "is_transparent_cognate": False,
                "corpus_count": group_counts[g_idx] if g_idx < len(group_counts) else 0,
                "_has_wikt_assignments": has_wikt,
            }
            if display_form:
                entry["display_form"] = display_form
            if variants:
                entry["variants"] = variants
            if morphology:
                entry["morphology"] = morphology

            cognate_key = "%s|%s" % (word, word_lemma)
            cognate_obj = cognates.get(cognate_key)
            if isinstance(cognate_obj, (int, float)):
                cognate_obj = {"score": cognate_obj}
            elif cognate_obj is True:
                cognate_obj = {"score": 1.0}
            if cognate_obj:
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

    # Unicode-aware word-boundary pattern: matches if character before/after
    # is NOT a Spanish letter (handles accented chars that \b misses)
    _SPANISH_LETTER = r'a-zA-ZáéíóúñüÁÉÍÓÚÑÜ'

    def find_mwe_examples(expression, max_examples=3):
        """Find lyric lines containing an MWE expression (word-boundary match)."""
        expr_lower = expression.lower()
        pattern = re.compile(
            r'(?<![' + _SPANISH_LETTER + r'])' +
            re.escape(expr_lower) +
            r'(?![' + _SPANISH_LETTER + r'])',
            re.IGNORECASE,
        )
        found = []
        for line, info in line_info.items():
            if pattern.search(line):
                trans_info = translations.get(line, {})
                english = trans_info.get("english", "")
                if english:
                    ex_dict = {
                        "song": info["song_id"],
                        "song_name": info["title"],
                        "spanish": line,
                        "english": english,
                        "translation_source": trans_info.get("source", ""),
                    }
                    ts_entry = ts_map.get(info["title"], {}).get(line)
                    if ts_entry:
                        ex_dict["timestamp_ms"] = ts_entry["ms"]
                    found.append(ex_dict)
                    if len(found) >= max_examples:
                        break
        return found

    # --- Mark most frequent lemma instance ---
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
    assign_ids_from_master(entries, master)

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
            h = hashlib.md5((clitic_word + "|" + clitic_word).encode("utf-8")).hexdigest()
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
                "is_interjection": False,
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
                master.setdefault(fid, {
                    "word": entry["word"],
                    "lemma": entry["lemma"],
                    "senses": [],
                    "is_english": entry.get("is_english", False),
                    "is_interjection": entry.get("is_interjection", False),
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
            master[fid] = {
                "word": entry["word"],
                "lemma": entry["lemma"],
                "senses": [],
                "is_english": entry.get("is_english", False),
                "is_interjection": entry.get("is_interjection", False),
                "is_propernoun": entry.get("is_propernoun", False),
                "is_transparent_cognate": entry.get("is_transparent_cognate", False),
                "display_form": entry.get("display_form"),
            }
            new_master += 1

        m = master[fid]
        # Propagate flags TO master from current step-4 data.
        # For step-4-derived flags (is_english, is_interjection, is_propernoun),
        # overwrite the master — the current routing data is authoritative and
        # stale True flags from previous builds must be cleared.
        # is_transparent_cognate is union-only (comes from cognates layer, not step 4).
        for flag in ("is_english", "is_interjection", "is_propernoun"):
            m[flag] = entry.get(flag, False)
        if entry.get("is_transparent_cognate", False):
            m["is_transparent_cognate"] = True
        # Only pull is_transparent_cognate from master (not step-4 derived)
        if m.get("is_transparent_cognate", False):
            entry["is_transparent_cognate"] = True
        if entry.get("display_form") and not m.get("display_form"):
            m["display_form"] = entry["display_form"]

        # Update master senses. If this entry has Wiktionary assignments
        # (biencoder/flash-lite/gap-fill), replace master senses entirely —
        # those are higher quality than old Gemini step 6 senses.
        # Otherwise union (for entries with only old Gemini data).
        entry_meanings = entry.get("meanings", [])
        if entry.get("_has_wikt_assignments"):
            new_senses_list = []
            for m_ in entry_meanings:
                if m_.get("pos") in ("SENSE_CYCLE", "X"):
                    continue
                s_entry = {"pos": m_.get("pos", "X"), "translation": m_.get("translation", "")}
                src = m_.get("source")
                if src:
                    s_entry["source"] = src
                new_senses_list.append(s_entry)
            if new_senses_list:
                old_count = len(m["senses"])
                m["senses"] = new_senses_list
                new_senses += len(new_senses_list) - old_count
        else:
            for meaning in entry_meanings:
                pos = meaning.get("pos", "X")
                if pos in ("X", "SENSE_CYCLE"):
                    continue  # don't pollute master with fallback senses
                translation = meaning.get("translation", "")
                norm = normalize_translation(translation)
                exists = any(s["pos"] == pos and normalize_translation(s["translation"]) == norm for s in m["senses"])
                if not exists:
                    s_entry = {"pos": pos, "translation": translation}
                    src = meaning.get("source")
                    if src:
                        s_entry["source"] = src
                    m["senses"].append(s_entry)
                    new_senses += 1

    print("  Master: %d entries (+%d new), %d new senses" % (len(master), new_master, new_senses))

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

            # Sort: artist-sourced first (by count desc), then wiktionary (by corpus_freq desc)
            def mwe_sort_key(m):
                is_wikt = 1 if m.get("source") == "wiktionary" else 0
                freq = -(m.get("count", 0) or m.get("corpus_freq", 0))
                return (is_wikt, freq)
            sorted_mwes = sorted(word_mwes, key=mwe_sort_key)

            memberships = []
            seen_exprs = set()
            for mwe in sorted_mwes:
                if len(memberships) >= MAX_MWES_PER_ENTRY:
                    break
                expr = mwe["expression"]
                if expr.lower() in seen_exprs:
                    continue
                seen_exprs.add(expr.lower())

                # Find lyric examples
                if expr not in mwe_examples_cache:
                    mwe_examples_cache[expr] = find_mwe_examples(expr)

                # Truncate long translations
                trans = mwe.get("translation") or ""
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

                memberships.append({
                    "expression": expr,
                    "translation": trans,
                    "examples": mwe_examples_cache[expr],
                    "source": mwe.get("source", "wiktionary"),
                })
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

    return entries, master, clitic_data


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

def write_split_files(entries, master, vocab_path, master_path, clitic_data=None):
    """Write compact index + examples aligned to master senses."""
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    index = []
    examples = {}

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
        sense_examples = []
        total_ex = 0

        for sense in m.get("senses", []):
            matching = None
            for meaning in entry.get("meanings", []):
                if meaning.get("pos") == sense["pos"] and meaning.get("translation") == sense["translation"]:
                    matching = meaning
                    break
            exs = matching.get("examples", []) if matching else []
            sense_examples.append(exs)
            total_ex += len(exs)
            sense_methods.append(matching.get("assignment_method") if matching else None)

        for exs in sense_examples:
            sense_freq.append(round(len(exs) / total_ex, 2) if total_ex > 0 else 0)

        # MWE memberships from entry (Wiktionary + artist-specific, merged at build time)
        entry_mwes = entry.get("mwe_memberships", [])
        mwe_examples = [mwe.get("examples", []) for mwe in entry_mwes]

        idx_entry = {
            "id": fid,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry.get("most_frequent_lemma_instance", False),
            "sense_frequencies": sense_freq,
        }
        if any(sense_methods):
            idx_entry["sense_methods"] = sense_methods
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
        if entry_mwes:
            idx_entry["mwe_memberships"] = [
                {"expression": mwe["expression"], "translation": mwe.get("translation", ""),
                 "source": mwe.get("source", "artist")}
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
        examples[fid] = ex_entry

    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    write_sidecar(index_path, make_meta("assemble_artist_vocabulary", STEP_VERSION))
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)
    write_sidecar(examples_path, make_meta("assemble_artist_vocabulary", STEP_VERSION))

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build artist vocabulary from layers")
    add_artist_arg(parser)
    parser.add_argument("--master-path", type=str, default=None,
                        help="Path to shared master vocabulary (default: Artists/vocabulary_master.json)")
    parser.add_argument("--sense-source", choices=["gemini", "wiktionary", "wiktionary-gemini", "spanishdict"],
                        default="spanishdict",
                        help="Which sense layers to use (default: spanishdict)")
    parser.add_argument("--remainders", action="store_true",
                        help="Emit SENSE_CYCLE remainder buckets for unassigned examples "
                             "(default: off — cleaner cards, but unassigned examples are dropped)")
    parser.add_argument("--min-priority", type=int, default=0,
                        help="Drop assignments whose method priority is below N. "
                             "Dropped examples become orphans (eligible for remainders "
                             "when --remainders is on). Default 0 (keep everything). "
                             "Useful values: 15 (skip keyword-tier), 30 (biencoder+), "
                             "50 (Gemini only).")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    vocab_path = os.path.join(artist_dir, config["vocabulary_file"])

    artists_dir = os.path.dirname(artist_dir)
    master_path = args.master_path or os.path.join(artists_dir, "vocabulary_master.json")
    layers_dir = os.path.join(artist_dir, "data", "layers")
    curated_path = os.path.join(artist_dir, "data", "llm_analysis", "curated_translations.json")

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
    entries, master, clitic_data = assemble_from_layers(
        layers_dir, master, curated_path,
        sense_source=args.sense_source,
        skip_words_path=skip_words_path,
        emit_remainders=args.remainders,
        min_priority=args.min_priority)

    # Write monolith (debugging)
    os.makedirs(os.path.dirname(vocab_path), exist_ok=True)
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    write_sidecar(vocab_path, make_meta("assemble_artist_vocabulary", STEP_VERSION))
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
        clitic_path = os.path.join(layers_dir, "clitic_forms.json")
        with open(clitic_path, "w", encoding="utf-8") as f:
            json.dump(clitic_by_id, f, ensure_ascii=False, indent=2)
        migration_path = os.path.join(layers_dir, "archive", "clitic_id_migration.json")
        os.makedirs(os.path.dirname(migration_path), exist_ok=True)
        with open(migration_path, "w", encoding="utf-8") as f:
            json.dump(id_migration, f, ensure_ascii=False, indent=2)
        print("  Clitic forms: %d entries -> %s" % (len(clitic_by_id), clitic_path))
        print("  ID migration: %d mappings -> %s" % (len(id_migration), migration_path))

    # Write split files
    write_split_files(entries, master, vocab_path, master_path, clitic_data)

    print("Done!")


if __name__ == "__main__":
    main()
