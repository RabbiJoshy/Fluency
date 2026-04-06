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
import sys
import argparse

from _artist_config import add_artist_arg, load_artist_config


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

def assemble_from_layers(layers_dir, mwe_path, master, curated_translations_path=None):
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
    cognates = load_layer(os.path.join(layers_dir, "cognates.json"), "cognates", required=False) or {}
    ranking = load_layer(os.path.join(layers_dir, "ranking.json"), "ranking", required=False)

    # Load MWE data
    mwe_index = {}
    if os.path.isfile(mwe_path):
        with open(mwe_path, "r", encoding="utf-8") as f:
            mwe_data = json.load(f)
        for mwe in mwe_data.get("mwes", []):
            expr = mwe["expression"]
            for token in expr.split():
                t = token.lower()
                if t not in mwe_index:
                    mwe_index[t] = []
                if not any(m["expression"] == expr for m in mwe_index[t]):
                    mwe_index[t].append({"expression": expr, "translation": mwe.get("translation", "")})
        print("  mwe_detected: %d MWEs" % len(mwe_data.get("mwes", [])))

    # Load curated translations
    curated = {}
    if curated_translations_path and os.path.isfile(curated_translations_path):
        with open(curated_translations_path, "r", encoding="utf-8") as f:
            curated = json.load(f)
        print("  curated_translations: %d overrides" % len(curated))
    # Also load shared curated
    shared_curated_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "shared", "curated_translations.json")
    if os.path.isfile(shared_curated_path):
        with open(shared_curated_path, "r", encoding="utf-8") as f:
            shared = json.load(f)
        for k, v in shared.items():
            if k not in curated:
                curated[k] = v

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

                # Apply curated override
                if word.lower() in curated:
                    translation = curated[word.lower()]

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
                        meaning_examples.append({
                            "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                            "song_name": raw_ex.get("title", ""),
                            "spanish": spanish,
                            "english": english,
                            "translation_source": source,
                        })

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
            if word.lower() in curated:
                translation = curated[word.lower()]
            all_examples = []
            for raw_ex in raw_examples:
                spanish = raw_ex.get("spanish", "")
                trans_info = translations.get(spanish, {})
                all_examples.append({
                    "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                    "song_name": raw_ex.get("title", ""),
                    "spanish": spanish,
                    "english": trans_info.get("english", ""),
                    "translation_source": trans_info.get("source", ""),
                })
            meanings.append({
                "pos": sense["pos"],
                "translation": translation,
                "frequency": "1.00",
                "examples": all_examples,
            })
        else:
            # No senses at all — fallback
            translation = curated.get(word.lower(), "")
            fallback_examples = []
            if raw_examples:
                raw_ex = raw_examples[0]
                spanish = raw_ex.get("spanish", "")
                trans_info = translations.get(spanish, {})
                fallback_examples.append({
                    "song": raw_ex["id"].split(":")[0] if ":" in raw_ex["id"] else raw_ex["id"],
                    "song_name": raw_ex.get("title", ""),
                    "spanish": spanish,
                    "english": trans_info.get("english", ""),
                    "translation_source": trans_info.get("source", ""),
                })
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

        # Apply cognate flag from layer
        cognate_key = "%s|%s" % (word, word_lemma)
        if cognate_key in cognates:
            entry["is_transparent_cognate"] = True

        entries.append(entry)

    # --- MWE annotation ---
    if mwe_index:
        # Build line_info from all raw examples for substring matching
        line_info = {}
        for word, exs in examples_raw.items():
            for ex in exs:
                line = ex.get("spanish", "")
                if line and line not in line_info:
                    sid = ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"]
                    line_info[line] = {"song_id": sid, "title": ex.get("title", "")}

        # Pre-compute MWE examples
        mwe_examples_cache = {}
        for w_lower, mwe_list in mwe_index.items():
            for mwe_entry in mwe_list:
                expr = mwe_entry["expression"]
                if expr in mwe_examples_cache:
                    continue
                expr_lower = expr.lower()
                found = []
                for line, info in line_info.items():
                    if expr_lower in line.lower():
                        trans_info = translations.get(line, {})
                        english = trans_info.get("english", "")
                        if english:
                            found.append({
                                "song": info["song_id"],
                                "song_name": info["title"],
                                "spanish": line,
                                "english": english,
                                "translation_source": trans_info.get("source", ""),
                            })
                            if len(found) >= 3:
                                break
                mwe_examples_cache[expr] = found

        mwe_count = 0
        for entry in entries:
            w_lower = entry["word"].lower()
            if w_lower in mwe_index:
                memberships = []
                for mwe_entry in mwe_index[w_lower]:
                    expr = mwe_entry["expression"]
                    memberships.append({
                        "expression": expr,
                        "translation": mwe_entry["translation"],
                        "examples": mwe_examples_cache.get(expr, []),
                    })
                entry["mwe_memberships"] = memberships
                mwe_count += 1
        print("  MWE annotation: %d entries" % mwe_count)

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
                "mwe_memberships": [],
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

        # Merge senses into master
        for meaning in entry.get("meanings", []):
            pos = meaning.get("pos", "X")
            translation = meaning.get("translation", "")
            exists = any(s["pos"] == pos and s["translation"] == translation for s in m["senses"])
            if not exists:
                m["senses"].append({"pos": pos, "translation": translation})
                new_senses += 1

        # Merge MWE memberships into master
        for mwe in entry.get("mwe_memberships", []):
            expr = mwe.get("expression", "")
            trans = mwe.get("translation", "")
            exists = any(
                e["expression"] == expr and e["translation"] == trans
                for e in m.get("mwe_memberships", [])
            )
            if not exists:
                m.setdefault("mwe_memberships", []).append({"expression": expr, "translation": trans})

    print("  Master: %d entries (+%d new), %d new senses" % (len(master), new_master, new_senses))

    # --- Apply ranking ---
    if ranking:
        order = ranking.get("order", [])
        easiness_data = ranking.get("easiness", {})

        if order:
            # Build ID -> entry lookup
            id_to_entry = {e["id"]: e for e in entries}
            sorted_entries = []
            for fid in order:
                if fid in id_to_entry:
                    sorted_entries.append(id_to_entry.pop(fid))
            # Append any entries not in the ranking (new words since last rank)
            for e in entries:
                if e["id"] in id_to_entry:
                    sorted_entries.append(e)
            entries = sorted_entries
            print("  Ranking applied: %d entries sorted" % len(entries))

        # Apply easiness scores and sort examples within meanings
        SENTINEL = 999999
        for entry in entries:
            fid = entry["id"]
            e_data = easiness_data.get(fid, {})
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

        mwe_examples = []
        for master_mwe in m.get("mwe_memberships", []):
            matched = []
            for entry_mwe in entry.get("mwe_memberships", []):
                if (entry_mwe.get("expression") == master_mwe["expression"]
                        and entry_mwe.get("translation") == master_mwe["translation"]):
                    matched = entry_mwe.get("examples", [])
                    break
            mwe_examples.append(matched)

        idx_entry = {
            "id": fid,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry.get("most_frequent_lemma_instance", False),
            "sense_frequencies": sense_freq,
        }
        if entry.get("variants"):
            idx_entry["variants"] = entry["variants"]
        index.append(idx_entry)

        ex_entry = {"m": sense_examples}
        if any(mwe_examples):
            ex_entry["w"] = mwe_examples
        examples[fid] = ex_entry

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)

    # Write updated master
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
    mwe_path = os.path.join(artist_dir, "data", "word_counts", "mwe_detected.json")
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
    entries, master = assemble_from_layers(layers_dir, mwe_path, master, curated_path)

    # Write monolith (debugging)
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("  Monolith: %d entries -> %s" % (len(entries), vocab_path))

    # Write split files
    write_split_files(entries, master, vocab_path, master_path)

    print("Done!")


if __name__ == "__main__":
    main()
