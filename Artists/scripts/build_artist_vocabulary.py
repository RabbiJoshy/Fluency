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

from _artist_config import add_artist_arg, load_artist_config, load_shared_dict, normalize_translation


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

def assemble_from_layers(layers_dir, master, curated_translations_path=None):
    """Assemble vocabulary entries from layer files.

    Returns (entries, master) where entries is the full monolith list and
    master has been updated with new words/senses.
    """
    # Load all layers
    print("Loading layers...")
    inventory = load_layer(os.path.join(layers_dir, "word_inventory.json"), "word_inventory")
    examples_raw = load_layer(os.path.join(layers_dir, "examples_raw.json"), "examples_raw")
    translations = load_layer(os.path.join(layers_dir, "example_translations.json"), "example_translations")
    senses = load_layer(os.path.join(layers_dir, "senses_gemini.json"), "senses_gemini")
    assignments = load_layer(os.path.join(layers_dir, "sense_assignments.json"), "sense_assignments")
    # Shared layers at Data/Spanish/layers/ (project root from script location)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    shared_cognates = os.path.join(project_root, "Data", "Spanish", "layers", "cognates.json")
    cognates = load_layer(shared_cognates, "cognates (shared)", required=False) or {}
    ranking = load_layer(os.path.join(layers_dir, "ranking.json"), "ranking", required=False)
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

    # --- Assemble entries ---
    print("\nAssembling vocabulary...")
    entries = []

    for inv_entry in inventory:
        word = inv_entry["word"]
        corpus_count = inv_entry.get("corpus_count", 0)
        display_form = inv_entry.get("display_form")
        variants = inv_entry.get("variants")

        # Look up senses
        # Try word|lemma keys — we need to find the right key since lemma comes from senses
        word_senses = None
        word_lemma = word  # default
        for key, s_list in senses.items():
            if key.startswith(word + "|"):
                word_senses = s_list
                word_lemma = key.split("|", 1)[1]
                break

        # Get sense assignments for this word
        word_assignments = assignments.get(word, [])

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

                # Apply curated override (keyed by word|lemma)
                curated_key = "%s|%s" % (word.lower(), word_lemma)
                if curated_key in curated:
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
                        ts_entry = ts_map.get(raw_ex.get("title", ""), {}).get(spanish)
                        if ts_entry:
                            ex_dict["timestamp_ms"] = ts_entry["ms"]
                        meaning_examples.append(ex_dict)

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

        # Build the entry
        # Get flags from senses_gemini key or master (flags come through master)
        entry = {
            "id": "",
            "word": word,
            "lemma": word_lemma,
            "meanings": meanings,
            "most_frequent_lemma_instance": True,
            "is_english": False,
            "is_interjection": False,
            "is_propernoun": False,
            "is_transparent_cognate": False,
            "corpus_count": corpus_count,
        }
        if display_form:
            entry["display_form"] = display_form
        if variants:
            entry["variants"] = variants

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
        # Union flags
        for flag in ("is_english", "is_interjection", "is_propernoun", "is_transparent_cognate"):
            if entry.get(flag, False):
                m[flag] = True
            # Also pull flags FROM master to entry
            if m.get(flag, False):
                entry[flag] = True
        if entry.get("display_form") and not m.get("display_form"):
            m["display_form"] = entry["display_form"]

        # Merge senses into master (normalized matching to avoid near-duplicates)
        for meaning in entry.get("meanings", []):
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

    return entries, master


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

def write_split_files(entries, master, vocab_path, master_path):
    """Write compact index + examples aligned to master senses."""
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    index = []
    examples = {}

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
        if entry_mwes:
            idx_entry["mwe_memberships"] = [
                {"expression": mwe["expression"], "translation": mwe.get("translation", ""),
                 "source": mwe.get("source", "artist")}
                for mwe in entry_mwes
            ]
        index.append(idx_entry)

        ex_entry = {"m": sense_examples}
        if any(mwe_examples):
            ex_entry["w"] = mwe_examples
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
    entries, master = assemble_from_layers(layers_dir, master, curated_path)

    # Write monolith (debugging)
    os.makedirs(os.path.dirname(vocab_path), exist_ok=True)
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("  Monolith: %d entries -> %s" % (len(entries), vocab_path))

    # Write split files
    write_split_files(entries, master, vocab_path, master_path)

    print("Done!")


if __name__ == "__main__":
    main()
