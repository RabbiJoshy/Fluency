#!/usr/bin/env python3
"""
step_6b_assign_senses_local.py — Assign artist lyric examples to word senses using
local bi-encoder embeddings.

When an artist is run with --no-gemini (or senses come from the master via
another artist's Gemini run), lyric examples get dumped on the first sense.
This script uses bi-encoder cosine similarity to classify each lyric line
to the correct sense — the same approach used in normal-mode step_6a_assign_senses.py,
but adapted for artist layer file formats.

At artist scale (~600-3000 lines to classify), this runs in under 30 seconds.

Sense sources (in priority order):
  1. senses_gemini.json (this artist's Gemini analysis)
  2. sense_menu.json (normal-mode dictionary senses — unbiased fallback)
  3. Master vocabulary senses (last resort)

Classification methods (per example):
  - Bilingual bi-encoder (English + Spanish) — 84% accuracy
  - Spanish-only bi-encoder (multilingual model) — 72% accuracy
  - Keyword overlap fallback — ~70% accuracy, instant

Modes:
  --biencoder    Bi-encoder cosine similarity (default)
  --keyword-only Keyword overlap (instant, ~70% accuracy)

Usage (from project root):
    .venv/bin/python3 pipeline/step_6b_assign_senses_local.py                          # normal mode
    .venv/bin/python3 pipeline/step_6b_assign_senses_local.py --artist-dir Artists/Rosalia
    .venv/bin/python3 pipeline/step_6b_assign_senses_local.py --artist-dir "Artists/spanish/Bad Bunny" --keyword-only

Inputs (artist mode):
    {artist}/data/layers/word_inventory.json
    {artist}/data/layers/examples_raw.json                    ({word: [{spanish, surface, ...}]})
    {artist}/data/layers/example_translations.json
    {artist}/data/layers/senses_gemini.json                   (optional)
    {artist}/data/layers/sense_menu/wiktionary.json           (primary)
    Data/Spanish/layers/sense_menu/wiktionary.json            (shared fallback)

Inputs (normal mode):
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/examples_raw.json                     ({word: [{target, english, ...}]})
    Data/Spanish/layers/sense_menu/wiktionary.json

Outputs:
    {layers}/sense_assignments/{source}.json                  (merged, method-keyed)
    {layers}/sense_menu/{source}.json                         (if dialect senses appended)
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

# Make artist-only helpers importable when running in artist mode.
sys.path.insert(0, str(Path(__file__).resolve().parent / "artist"))
from util_1a_artist_config import (load_artist_config,
                           artist_sense_menu_path, artist_sense_assignments_path)
from util_6a_method_priority import METHOD_PRIORITY, best_method_priority
from util_6a_assignment_format import load_assignments, dump_assignments

from step_5c_build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses)
from util_5c_sense_paths import sense_menu_path, sense_assignments_path
from util_6a_pos_menu_filter import (
    filter_senses_by_pos,
    filter_senses_by_precomputed_pos,
    sense_compatible_with_example_pos,
    TRUSTED_FILTER_POS,
)
from util_5c_sense_menu_format import (
    normalize_artist_sense_menu, merge_analysis,
    collect_surface_analyses_from_shared_menu, flatten_analyses_with_ids,
    assign_analysis_sense_ids, extract_form_of_targets, extend_ids_for_extra_senses,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKTIONARY_SENSES_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "sense_menu" / "wiktionary.json"
# Backward-compat fallback to the pre-refactor flat location.
if not WIKTIONARY_SENSES_FILE.exists():
    _legacy = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "sense_menu.json"
    if _legacy.exists():
        WIKTIONARY_SENSES_FILE = _legacy
WIKTIONARY_RAW_PATH = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"

MIN_SENSE_FREQUENCY = 0.05
MAX_EXAMPLES_PER_WORD = 10
# Multilingual model: 84% bilingual, 72% Spanish-only (handles both)
CLASSIFY_MODEL = "paraphrase-multilingual-mpnet-base-v2"

_POS_LABELS = {
    "VERB": "verb", "NOUN": "noun", "ADJ": "adjective",
    "ADV": "adverb", "ADP": "preposition",
    "CCONJ": "conjunction", "PRON": "pronoun",
    "DET": "determiner", "INTJ": "interjection",
    "NUM": "numeral", "PART": "particle",
    "PHRASE": "phrase", "CONTRACTION": "contraction",
}


# ---------------------------------------------------------------------------
# Keyword overlap classifier (fallback)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z]+")
_STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
    "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
    "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "shall", "should",
    "up", "out", "if", "so", "no", "into", "over", "also", "its", "one",
    "e", "g", "etc", "very", "just", "about", "more", "some", "than",
}


def tokenize_english(text, keep=frozenset()):
    """Tokenize English text, removing stop words except those in *keep*."""
    stops = _STOP_WORDS - keep
    return {w for w in _WORD_RE.findall(text.lower()) if w not in stops
            and len(w) > 1}


MIN_KEYWORD_OVERLAP = 1  # minimum content-word overlap to count as a match


def classify_example_keyword(sentence_english, senses):
    # Collect all tokens that appear in any sense translation so they
    # are exempt from stop-word filtering.  This lets function-word
    # translations like "that" (que) or "but" (pero) survive.
    sense_tokens = set()
    for s in senses:
        sense_tokens.update(_WORD_RE.findall(s["translation"].lower()))
    keep = sense_tokens & _STOP_WORDS

    sentence_words = tokenize_english(sentence_english, keep=keep)
    scores = []
    for s in senses:
        sense_words = tokenize_english(s["translation"], keep=keep)
        scores.append(len(sentence_words & sense_words) if sense_words else 0)
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    best_score = scores[best_idx]
    if best_score < MIN_KEYWORD_OVERLAP:
        return None  # no confident match
    return best_idx


# ---------------------------------------------------------------------------
# Sense resolution (Gemini -> Wiktionary -> Master fallback)
# ---------------------------------------------------------------------------

def load_wiktionary_senses():
    """Load normal-mode Wiktionary senses as fallback."""
    if WIKTIONARY_SENSES_FILE.exists():
        with open(WIKTIONARY_SENSES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_senses(word, gemini_senses, wiktionary_senses, master):
    """Find senses for a word using priority: Gemini > Wiktionary > Master.

    Returns (senses_list, source_label) or (None, None) if no senses found.
    """
    # 1. Gemini senses (this artist's analysis)
    for key, s_list in gemini_senses.items():
        if key.startswith(word + "|"):
            return s_list, "gemini"

    # 2. Wiktionary senses (normal-mode dictionary — unbiased)
    for key, s_list in wiktionary_senses.items():
        if key.startswith(word + "|"):
            if len(s_list) >= 1:
                return s_list, "wiktionary"

    # 3. Master vocabulary senses (from other artists' Gemini runs)
    for mid, mentry in master.items():
        if mentry.get("word") == word and mentry.get("senses"):
            return mentry["senses"], "master"

    return None, None


# ---------------------------------------------------------------------------
# Bi-encoder classification
# ---------------------------------------------------------------------------

def classify_with_biencoder(work_items, output, translations, model_name=None):
    """Classify artist lyric examples using bi-encoder cosine similarity.

    Uses bilingual text (English + Spanish) when English translation is
    available, falls back to Spanish-only for untranslated examples.
    The multilingual mpnet model handles both.
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model_name = model_name or CLASSIFY_MODEL
    print("Loading classifier model '%s'..." % model_name)
    model = SentenceTransformer(model_name)

    # Collect all example texts — bilingual when possible, Spanish-only otherwise
    print("\nPreparing example texts...")
    example_texts = []
    example_map = []  # (work_idx, example_idx)
    bilingual_count = 0
    spanish_only_count = 0

    for wi, item in enumerate(work_items):
        word, senses, examples, keep_indices, source = item[:5]
        # Optional 7th element: pre-computed indices to actually classify.
        # If present, pos-auto has already claimed the excluded examples —
        # embedding them would waste compute on known-answer cases.
        classify_indices = item[6] if len(item) > 6 else None
        for ei, ex in enumerate(examples):
            if classify_indices is not None and ei not in classify_indices:
                continue
            spanish = ex.get("spanish", "")  # normalized (canonical word)
            original_spanish = ex.get("_original_spanish", spanish)  # for translation lookup
            trans_info = translations.get(original_spanish, {})
            english = trans_info.get("english", "")

            if english and spanish:
                text = "%s [Spanish: %s]" % (english, spanish)
                bilingual_count += 1
            elif spanish:
                text = spanish
                spanish_only_count += 1
            else:
                continue  # no text at all — skip

            example_texts.append(text)
            example_map.append((wi, ei))

    print("  %d examples to embed (%d bilingual, %d Spanish-only)" % (
        len(example_texts), bilingual_count, spanish_only_count))

    # Collect all sense texts (raw "pos: translation" — best for bi-encoder).
    # When a sense has a context disambiguator ("of clothing") we append it
    # so homographs embed with distinct semantics rather than collapsing on
    # identical translations.
    sense_texts = []
    sense_map = []  # (work_idx, original_sense_idx)
    for wi, item in enumerate(work_items):
        word, senses, examples, keep_indices, source = item[:5]
        for ki in keep_indices:
            s = senses[ki]
            label = _POS_LABELS.get(s["pos"], s["pos"])
            text = "%s: %s" % (label, s["translation"])
            ctx = s.get("context")
            if ctx:
                text += " (%s)" % ctx
            sense_texts.append(text)
            sense_map.append((wi, ki))
    print("  %d sense texts to embed" % len(sense_texts))

    if not example_texts:
        print("  No examples to classify")
        return

    # Embed in batch
    print("\nEmbedding examples...")
    t0 = time.time()
    example_embs = model.encode(example_texts, normalize_embeddings=True,
                                show_progress_bar=False, batch_size=64)
    print("  Done in %.1fs" % (time.time() - t0))

    print("Embedding senses...")
    t0 = time.time()
    sense_embs = model.encode(sense_texts, normalize_embeddings=True,
                              show_progress_bar=False, batch_size=64)
    print("  Done in %.1fs" % (time.time() - t0))

    # Build per-word sense embedding lookup
    word_sense_embs = defaultdict(list)
    for flat_idx, (wi, ki) in enumerate(sense_map):
        word_sense_embs[wi].append((ki, sense_embs[flat_idx]))

    # Build per-word example embedding lookup
    word_example_embs = defaultdict(list)
    for flat_idx, (wi, ei) in enumerate(example_map):
        word_example_embs[wi].append((ei, example_embs[flat_idx]))

    # Classify each word
    print("\nClassifying %d words by cosine similarity..." % len(work_items))
    t0 = time.time()
    for wi, item in enumerate(work_items):
        word, senses, examples, keep_indices, source = item[:5]
        id_list = item[5] if len(item) > 5 else None
        classify_indices = item[6] if len(item) > 6 else None

        sense_example_indices = [[] for _ in senses]

        ex_pairs = word_example_embs.get(wi, [])
        sn_pairs = word_sense_embs.get(wi, [])

        if ex_pairs and sn_pairs:
            ex_indices, ex_vecs = zip(*ex_pairs)
            sn_indices, sn_vecs = zip(*sn_pairs)
            sims = np.dot(np.array(ex_vecs), np.array(sn_vecs).T)

            for row, ei in enumerate(ex_indices):
                best_col = int(np.argmax(sims[row]))
                best_sense_idx = sn_indices[best_col]
                sense_example_indices[best_sense_idx].append(ei)

        # Any examples in classify_indices that didn't get embedded (no text
        # at all) go to the first sense. We skip examples already claimed by
        # pos-auto — those were explicitly excluded from classify_indices and
        # have their own assignment.
        embedded_indices = set(ei for ei, _ in ex_pairs)
        expected_indices = (set(classify_indices) if classify_indices is not None
                            else set(range(len(examples))))
        for ei in expected_indices:
            if ei not in embedded_indices:
                sense_example_indices[keep_indices[0] if keep_indices else 0].append(ei)

        # Frequency filter + output
        total_classified = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            if total_classified >= 5:
                freq = len(indices) / total_classified
                if freq < MIN_SENSE_FREQUENCY:
                    continue
            sid = id_list[i] if i < len(id_list) else id_list[0]
            assignments.append({"sense": sid, "examples": indices})
        # Only install a fallback blanket-claim when there's nothing else —
        # specifically, neither pos-auto (already in output[word]) nor any
        # biencoder result. Without this guard we'd stomp on pos-auto.
        if not assignments and not output.get(word):
            assignments = [{"sense": id_list[0], "examples": list(range(len(examples)))}]
        if assignments:
            output.setdefault(word, {})["biencoder"] = assignments

    elapsed = time.time() - t0
    print("  Done in %.1fs" % elapsed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assign example sentences to senses using local bi-encoder embeddings")
    parser.add_argument("--artist-dir", default=None,
                        help="Artist directory (e.g. Artists/spanish/Bad Bunny). "
                             "Omit for normal mode (Data/Spanish).")
    parser.add_argument("--language", choices=["spanish", "french"], default="spanish",
                        help="Target language for normal-mode paths (default: spanish). "
                             "Ignored when --artist-dir is set.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--biencoder", action="store_true", default=True,
                      help="Bi-encoder cosine similarity (default)")
    mode.add_argument("--keyword-only", action="store_true",
                      help="Keyword overlap (instant, ~70%% accuracy)")
    parser.add_argument("--model", type=str, default=CLASSIFY_MODEL,
                        help="Sentence-transformers model (default: %s)" % CLASSIFY_MODEL)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing sense_assignments.json")
    parser.add_argument("--normal-only", action="store_true",
                        help="Only classify words that exist in normal-mode senses. "
                             "Writes to sense_menu.json / sense_assignments_wiktionary.json")
    parser.add_argument("--sense-menu-file", type=str, default=None,
                        help="Alternative artist-layer menu file to read instead of normal-mode sense_menu.json")
    parser.add_argument("--assignments-file", type=str, default="sense_assignments/wiktionary.json",
                        help="Artist-layer assignments file to write (default: sense_assignments/wiktionary.json)")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process a specific surface word (repeatable)")
    parser.add_argument("--biencoder-method-name", type=str, default="biencoder",
                        help="Method key to use for bi-encoder assignments")
    parser.add_argument("--keyword-method-name", type=str, default="keyword",
                        help="Method key to use for keyword assignments")
    parser.add_argument("--auto-method-name", type=str, default="wiktionary-auto",
                        help="Method key to use for auto-assigned single-sense words")
    parser.add_argument("--menu-source-label", type=str, default="wiktionary",
                        help="Source label for reporting when using --sense-menu-file")
    parser.add_argument("--include-clitics", action="store_true",
                        help="Include clitic-merge words (skipped by default)")
    args = parser.parse_args()

    artist_dir = args.artist_dir
    is_artist = artist_dir is not None

    if is_artist:
        config = load_artist_config(artist_dir)
        layers_dir = Path(artist_dir) / "data" / "layers"
        mode_label = "Artist: %s" % config["name"]
        routing_path = Path(artist_dir) / "data" / "known_vocab" / "word_routing.json"
    else:
        lang_dir = args.language.capitalize()
        layers_dir = PROJECT_ROOT / "Data" / lang_dir / "layers"
        mode_label = "Normal mode (Data/%s)" % lang_dir
        routing_path = layers_dir / "word_routing.json"
        # Rebind module-level Wiktionary path globals for the chosen language so
        # downstream loaders (load_wiktionary, eswikt cache, etc.) hit the right files.
        global WIKTIONARY_SENSES_FILE, WIKTIONARY_RAW_PATH
        WIKTIONARY_SENSES_FILE = layers_dir / "sense_menu" / "wiktionary.json"
        if args.language == "spanish":
            WIKTIONARY_RAW_PATH = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"
        else:
            WIKTIONARY_RAW_PATH = PROJECT_ROOT / "Data" / lang_dir / "Senses" / "wiktionary" / f"kaikki-{args.language}.jsonl.gz"

    use_keyword = args.keyword_only
    method = "keyword overlap" if use_keyword else "bi-encoder"
    print("Sense matching (%s)" % method)
    print(mode_label)

    # Derive the source label from --menu-source-label (default "wiktionary").
    source = args.menu_source_label
    default_assignments_rel = "sense_assignments/%s.json" % source

    # Single unified assignments file (all methods merge into one)
    using_default_assignments = (
        args.assignments_file == default_assignments_rel
        or args.assignments_file == "sense_assignments/wiktionary.json"
    )
    if using_default_assignments:
        if is_artist:
            output_file = Path(artist_sense_assignments_path(str(layers_dir), source))
        else:
            output_file = sense_assignments_path(layers_dir, source)
    else:
        output_file = layers_dir / args.assignments_file

    if is_artist:
        senses_output_file = Path(artist_sense_menu_path(str(layers_dir), source))
    else:
        senses_output_file = sense_menu_path(layers_dir, source)

    # No early exit — priority checking handles skip logic per-word

    # Load inputs
    print("\nLoading layers...")
    with open(layers_dir / "word_inventory.json", encoding="utf-8") as f:
        inventory = json.load(f)
    print("  word_inventory: %d entries" % len(inventory))

    with open(layers_dir / "examples_raw.json", encoding="utf-8") as f:
        examples_data = json.load(f)
    print("  examples_raw: %d entries" % len(examples_data))

    # Normal-mode schema uses `target` (Spanish) + inline `english`. Downstream
    # code expects the artist schema (`spanish` + separate translations dict),
    # so shim the examples in place.
    if not is_artist:
        for _exs in examples_data.values():
            for _ex in _exs:
                if "spanish" not in _ex and "target" in _ex:
                    _ex["spanish"] = _ex["target"]

    gemini_senses = {}
    if is_artist:
        senses_path = layers_dir / "senses_gemini.json"
        if senses_path.exists():
            with open(senses_path, encoding="utf-8") as f:
                gemini_senses = json.load(f)
            print("  senses_gemini: %d entries" % len(gemini_senses))
        else:
            print("  senses_gemini: (not found)")

    translations = {}
    translations_path = layers_dir / "example_translations.json"
    if translations_path.exists():
        with open(translations_path, encoding="utf-8") as f:
            translations = json.load(f)
        print("  example_translations: %d entries" % len(translations))
    elif is_artist:
        print("  example_translations: (not found)")
    else:
        # Normal mode: translations live inline on each example record.
        for _exs in examples_data.values():
            for _ex in _exs:
                _spa = _ex.get("target") or _ex.get("spanish")
                _eng = _ex.get("english")
                if _spa and _eng:
                    translations[_spa] = {"english": _eng}
        print("  translations (inline from examples_raw): %d entries" % len(translations))

    example_pos = {}
    example_pos_path = layers_dir / "example_pos.json"
    if example_pos_path.exists():
        with open(example_pos_path, encoding="utf-8") as f:
            example_pos = json.load(f)
        example_pos.pop("_example_ids", None)
        print("  example_pos: %d words" % len(example_pos))
    else:
        print("  example_pos: (not found, spaCy fallback)")

    custom_menu_mode = bool(args.sense_menu_file)
    if custom_menu_mode:
        custom_menu_path = layers_dir / args.sense_menu_file
        if not custom_menu_path.exists():
            raise SystemExit("Alternative menu file not found: %s" % custom_menu_path)
        with open(custom_menu_path, encoding="utf-8") as f:
            wiktionary_senses = normalize_artist_sense_menu(json.load(f))
        print("  custom sense menu: %d entries (%s)" % (len(wiktionary_senses), custom_menu_path.name))
        wikt_index = {}
        wikt_redirects = {}
        eswikt_index = {}
        master = {}
    else:
        # Load Wiktionary (raw, full 118K entries)
        print("Loading English Wiktionary...")
        wikt_index, wikt_redirects = load_wiktionary(WIKTIONARY_RAW_PATH)

        # Also keep the normal-mode senses layer for backward compat
        wiktionary_senses = load_wiktionary_senses()
        if wiktionary_senses:
            print("  sense_menu (normal-mode): %d entries" % len(wiktionary_senses))

        # Load eswiktionary dialect senses (appended to menu)
        eswikt_index = {}
        import pickle as _pickle
        eswikt_cache = PROJECT_ROOT / "Data/Spanish/Senses/wiktionary/kaikki-eswiktionary-raw.jsonl.gz.eswikt_dialect.cache.pkl"
        if eswikt_cache.exists():
            with open(eswikt_cache, "rb") as f:
                _, eswikt_index = _pickle.load(f)
            print("  eswiktionary dialect senses: %d words" % len(eswikt_index))

        # Master vocabulary fallback only applies in artist mode.
        master = {}
        if is_artist:
            master_path = PROJECT_ROOT / "Artists" / "vocabulary_master.json"
            if master_path.exists():
                with open(master_path, encoding="utf-8") as f:
                    master = json.load(f)
                print("  vocabulary_master (fallback): %d entries" % len(master))

    # Load existing assignments for priority checking.
    # Drop entries whose sense IDs don't exist in the current menu — they're
    # stale from a prior run where the menu had different sense IDs (e.g.
    # before step_5c was rebuilt). Without this, a stale priority-10 keyword
    # entry blocks re-classification because 10 >= 10.
    existing_assigns = {}
    stale_dropped = 0
    if output_file.exists():
        existing_assigns = load_assignments(output_file)
        # Build current valid-id index: {word: set(sense_ids)}
        valid_ids_by_word = {}
        for _w, _analyses in wiktionary_senses.items():
            if not isinstance(_analyses, list):
                continue
            ids = set()
            for _a in _analyses:
                _senses = _a.get("senses", {}) if isinstance(_a, dict) else {}
                if isinstance(_senses, dict):
                    ids.update(_senses.keys())
            if ids:
                valid_ids_by_word[_w] = ids
        for _w, _method_map in list(existing_assigns.items()):
            if _w not in valid_ids_by_word:
                continue  # no menu entry to validate against; leave untouched
            valid_ids = valid_ids_by_word[_w]
            for _method in list(_method_map.keys()):
                fresh_items = [it for it in _method_map[_method]
                               if it.get("sense") in valid_ids]
                if len(fresh_items) != len(_method_map[_method]):
                    stale_dropped += len(_method_map[_method]) - len(fresh_items)
                    if fresh_items:
                        _method_map[_method] = fresh_items
                    else:
                        del _method_map[_method]
            if not _method_map:
                del existing_assigns[_w]
        if stale_dropped:
            print("  Dropped %d stale assignment items (sense IDs not in current menu)"
                  % stale_dropped)

    # Load word routing to skip excluded/clitic-merged words.
    # The biencoder/gemini sub-buckets in word_routing.json are metadata
    # only — the chosen classifier processes every learnable word.
    routing_skip = set()
    if routing_path.exists():
        with open(routing_path, encoding="utf-8") as f:
            routing = json.load(f)
        # Skip excluded words (junk)
        for cat_list in routing.get("exclude", {}).values():
            routing_skip.update(cat_list)
        # Skip merge-clitics (folded into base verb, don't need assignment)
        if not args.include_clitics:
            clitic_merge = routing.get("clitic_merge", {})
            if isinstance(clitic_merge, dict):
                routing_skip.update(clitic_merge.keys())
        print("  word_routing: skipping %d excluded + clitic-merge words" % len(routing_skip))

    my_method = args.keyword_method_name if use_keyword else args.biencoder_method_name
    my_priority = METHOD_PRIORITY.get(my_method, 0)
    requested_words = set(args.word or [])

    # Build work items for multi-sense words
    print("\nPreparing work items...")
    output = {}
    work_items = []  # (word, senses, examples, keep_indices, source)
    single_sense_count = 0
    no_senses_count = 0
    no_examples_count = 0
    skipped_priority = 0
    sense_sources = defaultdict(int)

    normal_only_senses = {}  # word -> analyses (for writing sense_menu.json)
    skipped_not_normal = 0

    skipped_routing = 0
    pos_filtered_count = 0
    pos_single_sense_count = 0
    for inv_entry in inventory:
        word = inv_entry["word"]

        if requested_words and word not in requested_words:
            continue

        # Skip words not routed to bi-encoder
        if word.lower() in routing_skip:
            skipped_routing += 1
            continue

        examples = examples_data.get(word, [])[:MAX_EXAMPLES_PER_WORD]

        # Normalize elided surface forms to canonical word for better
        # spaCy tagging and bi-encoder embedding. Keep original Spanish
        # as _original_spanish for translation lookup.
        for ex in examples:
            surface = ex.get("surface")
            if surface and surface.lower() != word.lower():
                spanish = ex.get("spanish", "")
                if spanish:
                    ex["_original_spanish"] = spanish
                    ex["spanish"] = re.sub(
                        re.escape(surface), word, spanish, count=1, flags=re.IGNORECASE)

        # Skip words with equal or higher priority assignments
        if word in existing_assigns and not args.force:
            existing_priority = best_method_priority(existing_assigns[word])
            if existing_priority >= my_priority:
                skipped_priority += 1
                continue

        # Sense mapping is surface-word-first. Lemmatization is a separate layer,
        # so the stable fallback identity here is lemma = word.
        lemma = word

        # In --normal-only mode: only process words in the normal-mode senses layer
        if args.normal_only:
            wikt_key = None
            for key in wiktionary_senses:
                if key.startswith(word + "|"):
                    wikt_key = key
                    break
            if not wikt_key:
                skipped_not_normal += 1
                continue

        # Build the candidate menu from all shared surface-form analyses first.
        shared_analyses = collect_surface_analyses_from_shared_menu(word, wiktionary_senses)
        if shared_analyses and not custom_menu_mode:
            present_lemmas = {a.get("headword", a.get("lemma", word)) for a in shared_analyses}
            for target_lemma in extract_form_of_targets(shared_analyses):
                if target_lemma in present_lemmas:
                    continue
                target_senses = lookup_senses(word, target_lemma, wikt_index, wikt_redirects)
                if not target_senses:
                    continue
                for s in target_senses:
                    s["translation"] = clean_translation(s["translation"])
                target_senses = merge_similar_senses(target_senses)
                if target_senses:
                    shared_analyses.append({"headword": target_lemma, "senses": target_senses})
                    present_lemmas.add(target_lemma)
        if shared_analyses:
            word_senses, id_list, normalized_analyses = flatten_analyses_with_ids(shared_analyses)
            if not custom_menu_mode:
                for analysis in normalized_analyses:
                    merge_analysis(normal_only_senses, word, analysis.get("headword", analysis.get("lemma")), analysis.get("senses", {}))
        else:
            word_senses = []
            id_list = []
        if not word_senses and not custom_menu_mode:
            en_senses = lookup_senses(word, lemma, wikt_index, wikt_redirects)
            if en_senses:
                for s in en_senses:
                    s["translation"] = clean_translation(s["translation"])
                en_senses = merge_similar_senses(en_senses)
            else:
                en_senses = []
            for s in en_senses:
                s_copy = dict(s)
                if "source" not in s_copy:
                    s_copy["source"] = "en-wikt"
                word_senses.append(s_copy)

        # Append eswiktionary dialect senses
        if not custom_menu_mode:
            for lookup in sorted(set([word, lemma])):
                for es_sense in eswikt_index.get(lookup, []):
                    word_senses.append({
                        "pos": es_sense["pos"],
                        "translation": es_sense["gloss_es"],
                        "source": "es-wikt",
                    })
        if id_list and len(word_senses) > len(id_list):
            id_list.extend(
                extend_ids_for_extra_senses(id_list, lemma, word_senses[len(id_list):])
            )

        if not word_senses:
            no_senses_count += 1
            continue

        source = args.menu_source_label if custom_menu_mode else "wiktionary"

        # Build ID map for new format output
        if not id_list:
            id_map = assign_analysis_sense_ids(lemma, word_senses)
            id_list = list(id_map.keys())
            if not custom_menu_mode:
                merge_analysis(normal_only_senses, word, None, id_map)

        sense_sources[source] += 1

        if not examples:
            no_examples_count += 1
            continue

        keep_indices = list(range(len(word_senses)))
        precomputed = {int(k): v for k, v in example_pos.get(word, {}).items()}
        if precomputed:
            pos_keep_indices, pos_stats = filter_senses_by_precomputed_pos(word_senses, precomputed)
        elif use_keyword:
            # Keyword-only mode: skip live spaCy fallback. Loading the
            # transformer model just for the ~1-2k words missing precomputed
            # POS adds ~15s for marginal quality. Precomputed POS is populated
            # by tool_6a_tag_example_pos.py — re-run that if you need coverage.
            pos_keep_indices, pos_stats = list(range(len(word_senses))), {"used": False}
        else:
            pos_keep_indices, pos_stats = filter_senses_by_pos(word, lemma, word_senses, examples)
        if pos_stats.get("used") and pos_stats.get("reduced"):
            keep_indices = pos_keep_indices
            pos_filtered_count += 1

        if len(keep_indices) == 1:
            single_sense_count += 1
            if len(word_senses) > 1:
                pos_single_sense_count += 1
            only_idx = keep_indices[0]
            output[word] = {args.auto_method_name: [{"sense": id_list[only_idx],
                                                     "examples": list(range(len(examples)))}]}
            continue

        if use_keyword:
            # Keyword fallback — process inline with per-example POS filtering.
            # For each example, restrict candidate senses to those matching the
            # example's POS tag.  This prevents e.g. a NOUN-tagged "vuelo" from
            # matching VERB senses like "volarse → to fly off".
            #
            # pos-auto short-circuit: when per-example POS narrows the menu to
            # exactly 1 compatible sense, we assign directly instead of calling
            # the keyword classifier. The keyword classifier has no English
            # stemming (``dances`` ≠ ``dance``) and silently returns None on a
            # miss, which used to cede the example to stale auto-blanket
            # claims. A trusted POS tag is a stronger signal than a zero
            # lexical overlap, so we commit.
            sense_example_indices = [[] for _ in word_senses]
            pos_auto_indices = [[] for _ in word_senses]
            for ex_idx, ex in enumerate(examples):
                # Per-example POS filter: narrow candidates for this example.
                # Trusted ex_pos (VERB/NOUN/ADJ/ADV/INTJ) narrows to exact POS.
                # Untrusted ex_pos (ADP/DET/PRON/...) still rules out trusted
                # mismatches (e.g. ADP-tagged example drops VERB senses).
                ex_pos = precomputed.get(ex_idx)
                if ex_pos:
                    pos_candidates = [i for i in keep_indices
                                      if sense_compatible_with_example_pos(
                                          word_senses[i].get("pos"), ex_pos)]
                    if not pos_candidates:
                        # POS observed but no matching senses — fall back to
                        # full keep_indices so keyword can still try
                        pos_candidates = keep_indices
                else:
                    pos_candidates = keep_indices

                # pos-auto: trusted single-candidate case — assign directly.
                if len(pos_candidates) == 1:
                    pos_auto_indices[pos_candidates[0]].append(ex_idx)
                    continue

                spanish = ex.get("_original_spanish", ex.get("spanish", ""))
                trans_info = translations.get(spanish, {})
                eng = trans_info.get("english", "")
                if not eng:
                    continue  # no translation — skip (don't force onto first sense)

                candidate_senses = [word_senses[i] for i in pos_candidates]
                local_idx = classify_example_keyword(eng, candidate_senses)
                if local_idx is None:
                    continue  # no confident keyword match — skip
                # Map back to original word_senses index
                orig_idx = pos_candidates[local_idx]
                sense_example_indices[orig_idx].append(ex_idx)

            total_classified = sum(len(idx) for idx in sense_example_indices)
            assignments = []
            for i, indices in enumerate(sense_example_indices):
                if not indices:
                    continue
                if total_classified >= 5 and len(indices) / total_classified < MIN_SENSE_FREQUENCY:
                    continue
                assignments.append({"sense": id_list[i], "examples": indices})
            pos_auto_assignments = [
                {"sense": id_list[i], "examples": indices}
                for i, indices in enumerate(pos_auto_indices) if indices
            ]
            word_methods = {}
            if pos_auto_assignments:
                word_methods["pos-auto"] = pos_auto_assignments
            if assignments:
                word_methods[args.keyword_method_name] = assignments
            if word_methods:
                output[word] = word_methods
            # else: no per-example POS-auto or keyword match — word gets no
            # assignment, examples fall to the remainder bucket in the builder.
        else:
            # Biencoder branch: apply the same per-example pos-auto
            # short-circuit before queueing. Single-POS-candidate examples
            # skip embedding entirely and get stamped ``pos-auto`` now;
            # only ambiguous-POS examples go through the encoder below.
            pos_auto_by_sense = {}  # sense_idx -> [example_idx]
            classify_indices = []
            for ex_idx in range(len(examples)):
                ex_pos = precomputed.get(ex_idx)
                if ex_pos:
                    pos_candidates = [i for i in keep_indices
                                      if sense_compatible_with_example_pos(
                                          word_senses[i].get("pos"), ex_pos)]
                    if not pos_candidates:
                        pos_candidates = keep_indices
                else:
                    pos_candidates = keep_indices
                if len(pos_candidates) == 1:
                    pos_auto_by_sense.setdefault(pos_candidates[0], []).append(ex_idx)
                else:
                    classify_indices.append(ex_idx)
            if pos_auto_by_sense:
                output[word] = {"pos-auto": [
                    {"sense": id_list[sidx], "examples": eis}
                    for sidx, eis in pos_auto_by_sense.items()
                ]}
            work_items.append((word, word_senses, examples, keep_indices,
                               source, id_list, classify_indices))

    if skipped_routing:
        print("  Skipped (excluded/gemini-routed): %d" % skipped_routing)
    if skipped_priority:
        print("  Skipped (higher-priority method exists): %d" % skipped_priority)
    if args.normal_only:
        print("  Skipped (not in normal mode): %d" % skipped_not_normal)
    if pos_filtered_count:
        print("  POS-filtered menus: %d" % pos_filtered_count)
    if pos_single_sense_count:
        print("  POS-resolved to single sense: %d" % pos_single_sense_count)
    print("  Single-sense (no classification): %d" % single_sense_count)
    print("  Multi-sense to classify: %d" % len(work_items))
    print("  No senses: %d" % no_senses_count)
    print("  No examples: %d" % no_examples_count)
    print("  Sense sources: %s" % dict(sense_sources))

    # Check translation coverage for multi-sense examples
    if work_items and not use_keyword:
        total_ex = sum(len(item[2]) for item in work_items)
        has_eng = 0
        for item in work_items:
            examples = item[2]
            for ex in examples:
                spanish = ex.get("spanish", "")
                if translations.get(spanish, {}).get("english"):
                    has_eng += 1
        spa_only = total_ex - has_eng
        print("  Classification breakdown: %d bilingual, %d Spanish-only" % (has_eng, spa_only))

    t0 = time.time()

    if work_items and not use_keyword:
        classify_with_biencoder(work_items, output, translations, model_name=args.model)
    elif use_keyword:
        print("\nKeyword classification done (instant)")

    # Merge with existing assignments (add biencoder alongside other methods).
    # With --force: first wipe this-method entries from existing so words
    # that fail to classify in the new run lose their stale assignments.
    if output_file.exists():
        existing = load_assignments(output_file)
        if args.force:
            wiped = 0
            for word, word_data in list(existing.items()):
                if isinstance(word_data, dict) and my_method in word_data:
                    del word_data[my_method]
                    wiped += 1
                    if not word_data:
                        del existing[word]
            if wiped:
                print("  --force: wiped %d stale '%s' entries" % (wiped, my_method))
        stale_auto_wiped = 0
        for word, word_data in output.items():
            if isinstance(word_data, dict):
                if word not in existing or not isinstance(existing[word], dict):
                    existing[word] = {}
                # Stale-auto cleanup: if the new write has any non-auto method
                # (priority > 0), drop any existing priority-0 auto entries.
                # Those blanket claims were correct only when the menu had a
                # single sense; a word that now earns a real classifier (or
                # pos-auto) stamp is multi-sense by construction and the old
                # auto blanket would silently outvote unassigned examples via
                # the build-time resolver.
                incoming_has_non_auto = any(
                    METHOD_PRIORITY.get(m, 0) > 0 for m in word_data
                )
                if incoming_has_non_auto:
                    for m in list(existing[word].keys()):
                        if METHOD_PRIORITY.get(m, 0) == 0:
                            existing[word].pop(m, None)
                            stale_auto_wiped += 1
                existing[word].update(word_data)
            else:
                existing[word] = word_data
        if stale_auto_wiped:
            print("  Dropped %d stale priority-0 auto entries (menu now multi-sense)"
                  % stale_auto_wiped)
        output = existing

    print("\nWriting %s..." % output_file)
    dump_assignments(output, output_file)

    # Write/merge the senses layer
    if senses_output_file and normal_only_senses:
        existing_senses = {}
        if senses_output_file.exists():
            with open(senses_output_file, encoding="utf-8") as f:
                existing_senses = normalize_artist_sense_menu(json.load(f))
        for word, analyses in normal_only_senses.items():
            for analysis in analyses:
                merge_analysis(existing_senses, word, analysis.get("headword", analysis.get("lemma")), analysis.get("senses", {}))
        print("Writing %s (%d entries)..." % (senses_output_file, len(existing_senses)))
        with open(senses_output_file, "w", encoding="utf-8") as f:
            json.dump(existing_senses, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0

    # Report
    from collections import Counter
    active = Counter(len(v) for v in output.values())
    print("\n" + "=" * 55)
    print("ARTIST SENSE ASSIGNMENT RESULTS (%s)" % method)
    print("=" * 55)
    print("Total assignments:         %6d" % len(output))
    print("Single sense:              %6d" % single_sense_count)
    print("Multi-sense (classified):  %6d" % len(work_items))
    print("No senses:                 %6d" % no_senses_count)
    print("No examples:               %6d" % no_examples_count)
    print("Elapsed:                   %.1fs" % elapsed)
    print()
    print("Sense sources:")
    for src in ("gemini", args.menu_source_label if custom_menu_mode else "wiktionary", "master"):
        if sense_sources.get(src):
            print("  %-12s %6d words" % (src, sense_sources[src]))
    print()
    print("Active senses per word:")
    for n in sorted(active):
        print("  %d senses: %6d words" % (n, active[n]))


if __name__ == "__main__":
    main()
