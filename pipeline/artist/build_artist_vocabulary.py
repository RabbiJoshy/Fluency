#!/usr/bin/env python3
"""
build_artist_vocabulary.py — Assemble final artist vocabulary from layer files.

Reads all layer files and the shared master vocabulary, then produces:
  - {Name}vocabulary.index.json  (compact: id, corpus_count, sense_frequencies)
  - {Name}vocabulary.examples.json (examples keyed by ID)
  - {Name}vocabulary.json (full monolith for debugging)

The index is aligned to master senses so joinWithMaster() in the front end
can reconstruct full entries.

Usage (from project root):
    .venv/bin/python3 Artists/scripts/build_artist_vocabulary.py --artist-dir Artists/BadBunny
"""

import hashlib
import json
import os
import re
import sys
import argparse

from _artist_config import (add_artist_arg, load_artist_config, load_shared_dict,
                            normalize_translation, METHOD_PRIORITY, best_method_priority)


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
                         sense_source="wiktionary", skip_words_path=None):
    """Assemble vocabulary entries from layer files.

    Returns (entries, master) where entries is the full monolith list and
    master has been updated with new words/senses.
    """
    # Load all layers
    print("Loading layers...")
    inventory = load_layer(os.path.join(layers_dir, "word_inventory.json"), "word_inventory")
    examples_raw = load_layer(os.path.join(layers_dir, "examples_raw.json"), "examples_raw")
    translations = load_layer(os.path.join(layers_dir, "example_translations.json"), "example_translations")
    if sense_source == "wiktionary":
        senses_file = "senses_wiktionary.json"
        assign_file = "sense_assignments_wiktionary.json"
    elif sense_source == "wiktionary-gemini":
        senses_file = "senses_wiktionary_gemini.json"
        assign_file = "sense_assignments_wiktionary_gemini.json"
    else:
        senses_file = "senses_gemini.json"
        assign_file = "sense_assignments.json"
    senses = load_layer(os.path.join(layers_dir, senses_file), senses_file,
                        required=False)
    assignments = load_layer(os.path.join(layers_dir, assign_file), assign_file,
                             required=False)
    # Fallback to gemini layers if wiktionary not found
    if senses is None or assignments is None:
        if sense_source == "wiktionary":
            print("  Wiktionary layers not found, falling back to gemini layers")
        senses = load_layer(os.path.join(layers_dir, "senses_gemini.json"), "senses_gemini")
        assignments = load_layer(os.path.join(layers_dir, "sense_assignments.json"), "sense_assignments")
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

    # MWEs: shared layer at Data/Spanish/layers/mwe_phrases.json (all sources with provenance)
    shared_mwes_path = os.path.join(project_root, "Data", "Spanish", "layers", "mwe_phrases.json")
    mwe_by_id = load_layer(shared_mwes_path, "mwe_phrases (shared)", required=False) or {}

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

    # Load skip_words for clitic merge and flag categories
    skip_data = {}
    clitic_merge = {}  # word -> base_verb
    skip_english = set()
    skip_propn = set()
    skip_intj = set()
    if skip_words_path and os.path.isfile(skip_words_path):
        with open(skip_words_path, "r", encoding="utf-8") as f:
            skip_data = json.load(f)
        clitic_merge = skip_data.get("clitic_merge", {})
        # Build flag sets from skip categories
        for w in skip_data.get("english", []):
            skip_english.add(w.lower() if isinstance(w, str) else w.get("word", "").lower())
        for w in skip_data.get("proper_nouns_detected", []):
            skip_propn.add(w.lower() if isinstance(w, str) else w.get("word", "").lower())
        for w in skip_data.get("interjections_detected", []):
            skip_intj.add(w.lower() if isinstance(w, str) else w.get("word", "").lower())
        if clitic_merge:
            print("  clitic_merge: %d words to fold into base verbs" % len(clitic_merge))
        print("  skip_words flags: %d english, %d propn, %d intj" %
              (len(skip_english), len(skip_propn), len(skip_intj)))

    # Pre-process clitic merges: skip clitics from main deck, build separate
    # clitic data file (like MWEs). Base verb references clitic IDs; front-end
    # displays clitics as sub-entries.
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
            clitic_senses_raw = None
            clitic_lemma = clitic_word
            for skey, sdata in senses.items():
                if skey.startswith(clitic_word + "|"):
                    clitic_senses_raw = sdata
                    clitic_lemma = skey.split("|", 1)[1]
                    break
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
            # Get the best translation from senses
            translation = ""
            if clitic_senses_raw:
                first = (list(clitic_senses_raw.values())[0] if isinstance(clitic_senses_raw, dict)
                         else clitic_senses_raw[0] if clitic_senses_raw else None)
                if first:
                    translation = first.get("translation", "")
            clitic_data[clitic_word] = {
                "base_verb": base_verb,
                "lemma": clitic_lemma,
                "corpus_count": clitic_entry.get("corpus_count", 0),
                "translation": translation,
                "assignments": resolved_assigns,
                "examples": resolved_examples,
            }
            base_entry.setdefault("variants", []).append(clitic_word)
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

        # Look up senses — handle both old (list) and new (dict-of-IDs) format
        word_senses_raw = None
        word_lemma = word  # default
        for key, s_data in senses.items():
            if key.startswith(word + "|"):
                word_senses_raw = s_data
                word_lemma = key.split("|", 1)[1]
                break

        # Normalize to (sense_list, sense_by_id) for both formats
        sense_by_id = None
        if isinstance(word_senses_raw, dict):
            # New format: {sense_id: {pos, translation, ...}}
            sense_by_id = word_senses_raw
            word_senses = list(word_senses_raw.values())
        elif isinstance(word_senses_raw, list):
            # Old format: [{pos, translation, ...}]
            word_senses = word_senses_raw
        else:
            word_senses = None

        # Get sense assignments — handle both old (list) and new (dict-of-methods)
        raw_assignments = assignments.get(word, [])
        if isinstance(raw_assignments, dict):
            # New format: {method: [{sense, examples}]}
            # Pick best available method by priority (from _artist_config.py)
            best_method = max(raw_assignments.keys(),
                              key=lambda m: METHOD_PRIORITY.get(m, -1))
            word_assignments = []
            for a in raw_assignments[best_method]:
                sid = a.get("sense")
                if sense_by_id and sid in sense_by_id:
                    word_assignments.append({
                        "sense_idx": list(sense_by_id.keys()).index(sid),
                        "examples": a.get("examples", []),
                        "method": best_method,
                    })
        else:
            # Old format: [{sense_idx, examples, method}]
            word_assignments = raw_assignments

        # Get raw examples for this word
        raw_examples = examples_raw.get(word, [])

        # Build meanings
        meanings = []
        if word_senses and word_assignments:
            total_assigned = sum(len(a.get("examples", [])) for a in word_assignments)

            for assignment in word_assignments:
                sense_idx = assignment["sense_idx"]
                if sense_idx >= len(word_senses):
                    continue
                sense = word_senses[sense_idx]
                pos = sense["pos"]
                translation = sense["translation"]

                # Apply curated override only for single-sense words.
                # Multi-sense Wiktionary assignments have per-sense translations
                # that are more specific than a blanket curated override.
                curated_key = "%s|%s" % (word.lower(), word_lemma)
                if curated_key in curated and len(word_assignments) == 1:
                    translation = curated[curated_key]

                # Gather examples
                example_indices = assignment.get("examples", [])
                meaning_examples = []
                for ex_idx in example_indices:
                    if ex_idx < len(raw_examples):
                        raw_ex = raw_examples[ex_idx]
                        spanish = raw_ex.get("spanish", "")
                        # Look up translation
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
                        # Attach translation quality score if available
                        score_entry = translation_scores.get(spanish, {})
                        if isinstance(score_entry, dict) and "score" in score_entry:
                            ex_dict["translation_quality"] = score_entry["score"]
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        if ts_entry:
                            ex_dict["timestamp_ms"] = ts_entry["ms"]
                        meaning_examples.append(ex_dict)

                # Sort examples by translation quality (highest first)
                meaning_examples.sort(
                    key=lambda e: e.get("translation_quality", 3), reverse=True)

                freq = "%.2f" % (len(example_indices) / total_assigned) if total_assigned > 0 else "1.00"
                meanings.append({
                    "pos": pos,
                    "translation": translation,
                    "frequency": freq,
                    "examples": meaning_examples,
                })
        elif word_senses:
            # Senses exist but no assignments — put all examples on first sense
            sense = word_senses[0]
            translation = sense["translation"]
            curated_key = "%s|%s" % (word.lower(), word_lemma)
            if curated_key in curated:
                translation = curated[curated_key]
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
            meanings.append({
                "pos": sense["pos"],
                "translation": translation,
                "frequency": "1.00",
                "examples": all_examples,
            })
        else:
            # No senses at all — fallback
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

        # Morphology from conjugation reverse lookup
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
            # Tag infinitives: word == lemma and has a VERB sense
            has_verb = word_senses and any(s.get("pos") == "VERB" for s in word_senses)
            if has_verb:
                morphology = {"mood": "infinitivo"}

        # Build the entry
        # Set flags from step 4 skip_words (current run) instead of stale master
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
            "corpus_count": corpus_count,
            "_has_wikt_assignments": has_wikt,
        }
        if display_form:
            entry["display_form"] = display_form
        if variants:
            entry["variants"] = variants
        if morphology:
            entry["morphology"] = morphology

        # Apply cognate signals from layer (object per entry)
        cognate_key = "%s|%s" % (word, word_lemma)
        cognate_obj = cognates.get(cognate_key)
        # Backward compat: old format stores bare float or True
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
        # Propagate flags TO master for cross-artist benefit.
        # Flags on entry are set from step 4 skip_words (current data),
        # NOT pulled from stale master. is_transparent_cognate comes from
        # the cognates layer, so still union that from master.
        for flag in ("is_english", "is_interjection", "is_propernoun", "is_transparent_cognate"):
            if entry.get(flag, False):
                m[flag] = True
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
            new_senses_list = [{"pos": m_.get("pos", "X"), "translation": m_.get("translation", "")}
                               for m_ in entry_meanings]
            if new_senses_list:
                old_count = len(m["senses"])
                m["senses"] = new_senses_list
                new_senses += len(new_senses_list) - old_count
        else:
            for meaning in entry_meanings:
                pos = meaning.get("pos", "X")
                translation = meaning.get("translation", "")
                norm = normalize_translation(translation)
                exists = any(s["pos"] == pos and normalize_translation(s["translation"]) == norm for s in m["senses"])
                if not exists:
                    m["senses"].append({"pos": pos, "translation": translation})
                    new_senses += 1

    print("  Master: %d entries (+%d new), %d new senses" % (len(master), new_master, new_senses))

    # --- MWE annotation from shared layer (after IDs are assigned) ---
    MAX_MWES_PER_ENTRY = 10
    MAX_TRANSLATION_LEN = 100
    if mwe_by_id:
        mwe_examples_cache = {}
        mwe_count = 0
        for entry in entries:
            fid = entry["id"]
            word_mwes = mwe_by_id.get(fid, [])
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
            word_to_entry = {e["word"]: e for e in entries}
            id_to_entry = {e["id"]: e for e in entries}

            sorted_entries = []
            used = set()
            for key in order:
                entry = word_to_entry.get(key) or id_to_entry.get(key)
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
        index.append(idx_entry)

        ex_entry = {"m": sense_examples}
        if any(mwe_examples):
            ex_entry["w"] = mwe_examples
        if any(clitic_examples):
            ex_entry["c"] = clitic_examples
        examples[fid] = ex_entry

    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)

    # Write updated master
    os.makedirs(os.path.dirname(master_path), exist_ok=True)
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False)

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
    parser.add_argument("--sense-source", choices=["gemini", "wiktionary", "wiktionary-gemini"],
                        default="wiktionary",
                        help="Which sense layers to use (default: wiktionary)")
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
    skip_words_path = os.path.join(artist_dir, "data", "known_vocab", "skip_words.json")
    entries, master, clitic_data = assemble_from_layers(
        layers_dir, master, curated_path,
        sense_source=args.sense_source,
        skip_words_path=skip_words_path)

    # Write monolith (debugging)
    os.makedirs(os.path.dirname(vocab_path), exist_ok=True)
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
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
