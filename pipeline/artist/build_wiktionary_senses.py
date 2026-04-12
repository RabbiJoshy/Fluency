#!/usr/bin/env python3
"""Generate Wiktionary-based sense layers for an artist.

Produces two layer files in Artists/{Name}/data/layers/:
  - senses_wiktionary_gemini.json      (word|lemma -> [{pos, translation, source}])
  - sense_assignments_wiktionary_gemini.json  (word -> [{sense_idx, examples, method}])

For single-sense words: auto-assigns all examples (no API call).
For multi-sense words: Flash Lite classifies examples to senses.
For zero-sense words: Flash Lite gap-fill proposes new senses.

Run from project root:
    .venv/bin/python3 pipeline/artist/build_wiktionary_senses.py --artist-dir "Artists/Bad Bunny"
"""
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")

import argparse, gzip, json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))

from build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses)
from _artist_config import (add_artist_arg, load_artist_config,
                           load_dotenv_from_project_root, assign_sense_ids,
                           METHOD_PRIORITY, best_method_priority)
load_dotenv_from_project_root()

# ---------------------------------------------------------------------------
# Spanish Wiktionary dialect supplement (inlined from bench_gapfill)
# ---------------------------------------------------------------------------
ESWIKT_FILE = PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-eswiktionary-raw.jsonl.gz"
DIALECT_TAGS = {"Puerto-Rico", "Caribbean", "Cuba"}
_ESWIKT_POS_MAP = {
    "noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV",
    "intj": "INTJ", "phrase": "PHRASE", "name": "PROPN",
}


def load_eswiktionary(path, dialect_tags):
    """Load Spanish Wiktionary, filtering to dialect-tagged senses. Pickle-cached."""
    import pickle
    cache_path = Path(str(path) + ".eswikt_dialect.cache.pkl")
    cache_key = tuple(sorted(dialect_tags))
    if cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
        with open(cache_path, "rb") as f:
            cached_key, index = pickle.load(f)
        if cached_key == cache_key:
            print("  %d words with dialect senses (cached)" % len(index))
            return index

    index = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("lang_code") != "es":
                continue
            word = obj.get("word", "")
            raw_pos = obj.get("pos", "")
            pos = _ESWIKT_POS_MAP.get(raw_pos)
            if not pos:
                continue
            for s in obj.get("senses", []):
                tags = set(s.get("tags", []))
                if not (tags & dialect_tags):
                    continue
                glosses = s.get("glosses", [])
                if not glosses:
                    continue
                if "form-of" in tags:
                    continue
                index.setdefault(word, []).append({
                    "pos": pos,
                    "gloss_es": glosses[0],
                    "tags": sorted(tags & dialect_tags),
                })
    with open(cache_path, "wb") as f:
        pickle.dump((cache_key, index), f)
    print("  %d words with dialect senses" % len(index))
    return index


def build_combined_senses(word, lemma, en_senses, eswikt_index, translation_cache):
    """Combine English + Spanish Wiktionary senses into one menu."""
    combined = []
    for s in en_senses:
        combined.append({
            "pos": s["pos"],
            "translation": s["translation"],
            "source": "en-wikt",
        })
    for lookup in sorted(set([word, lemma])):
        for s in eswikt_index.get(lookup, []):
            gloss_es = s["gloss_es"]
            cached = translation_cache.get(gloss_es)
            combined.append({
                "pos": s["pos"],
                "translation": cached if cached else gloss_es,
                "source": "es-wikt",
                "gloss_es": gloss_es,
                "is_spanish": cached is None,
            })
    return combined


# ---------------------------------------------------------------------------
# Flash Lite classification (batch)
# ---------------------------------------------------------------------------
BATCH_SIZE = 15


def classify_batch_gemini(words_data, api_key):
    """Classify examples to senses for a batch of multi-sense words.

    Returns list of per-word assignment lists: [{sense_idx, examples, method}]
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt_parts = [
        "You are classifying Spanish vocabulary from song lyrics.",
        "For each word below, assign each numbered example to the best-matching"
        " sense (0-indexed). If both an English sense and a Spanish [ES] sense"
        " cover the same meaning, prefer the English one.",
        "",
        "Substitution test: for each example, mentally substitute the sense"
        " definition into the English translation. Does it still convey the"
        " right meaning? If not, try other senses. Pick the sense whose"
        " definition makes the substituted sentence make sense, even if the"
        " translator used a different English word.",
        "Example: 'I have the shaved bug' + sense 'penis' — substituting"
        " 'penis' makes more sense than 'bug' in this context → pick 'penis'.",
        "",
    ]

    for wi, wd in enumerate(words_data):
        prompt_parts.append('--- Word %d: "%s" (lemma: %s) ---' % (
            wi + 1, wd["word"], wd["lemma"]))
        prompt_parts.append("Senses:")
        for si, s in enumerate(wd["senses"]):
            label = "[ES] " if s.get("is_spanish") else ""
            prompt_parts.append("  %d. %s[%s] %s" % (si, label, s["pos"],
                                                      s["translation"]))
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"]):
            spa = ex.get("spanish", "")
            eng = ex.get("english", "")
            prompt_parts.append("  %d. %s | %s" % (ei + 1, spa, eng))
        prompt_parts.append("")

    prompt_parts.append("Return a JSON array with one object per word:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "assignments": {"1": 0, "2": 1},
    }], indent=2))

    prompt = "\n".join(prompt_parts)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: batch parse error")
            print("    Raw: %s" % (response.text[:500] if response.text else "None"))
            return None
        except Exception as e:
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (attempt + 1, str(e)[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


def gap_fill_gemini(word, lemma, senses, examples, api_key):
    """Ask Gemini: pick a sense or propose a new one. Returns result dict."""
    from google import genai
    client = genai.Client(api_key=api_key)

    menu_lines = []
    for i, s in enumerate(senses):
        label = "[ES] " if s.get("is_spanish") else ""
        menu_lines.append("%d. %s[%s] %s" % (i + 1, label, s["pos"],
                                              s["translation"]))
    menu = "\n".join(menu_lines)

    lines = []
    for i, ex in enumerate(examples):
        eng = ex.get("english", "")
        spa = ex.get("spanish", "")
        lines.append("%d. %s | %s" % (i + 1, spa, eng))

    prompt = (
        'You are helping build a Spanish vocabulary flashcard app for learners.'
        ' The word is "%s" (lemma: %s).\n\n'
        'Step 1: Read these example lyrics and determine what "%s" actually'
        ' means in this artist\'s usage:\n%s\n\n'
        'Step 2: Check whether any of these dictionary senses is close enough'
        ' that a learner reading it on a flashcard would understand the word'
        ' in these lyrics.\n'
        'If both an English sense and a Spanish [ES] sense cover the same'
        ' meaning, prefer the English one.\n%s\n\n'
        'Test each sense: take the English translation of one example lyric'
        ' and substitute the dictionary definition for the word. Write out'
        ' the substituted sentence. Does it still convey what the artist'
        ' means?\n\n'
        'If the best sense passes this test, the word is covered — even if'
        ' the usage is more figurative or intense. Flashcard space is limited,'
        ' so don\'t propose new senses when existing ones work.\n\n'
        'Step 3: If NO sense passes the substitution test, propose ONE short'
        ' flashcard translation.\n\n'
        'Return JSON:\n'
        '{\n'
        '  "actual_meaning": "<what the word means in these lyrics, 2-5 words>",\n'
        '  "substitution_example": "<pick one English lyric and substitute the best dictionary definition>",\n'
        '  "substitution_works": <true if the substituted sentence conveys the right meaning>,\n'
        '  "covered_by_existing": <true if substitution works, false if not>,\n'
        '  "best_sense_index": <1-indexed number of the best matching sense, or null>,\n'
        '  "english_translation": "<if best sense is Spanish [ES], provide 2-5 word English translation; else null>",\n'
        '  "proposed_sense": "<short flashcard-friendly English translation if not covered, else null>",\n'
        '  "proposed_pos": "<POS tag if proposing: NOUN/VERB/ADJ/ADV/INTJ, else null>",\n'
        '  "examples_needing_new_sense": <count of examples that need the new sense, 0 if covered>\n'
        '}'
    ) % (word, lemma, word, "\n".join(lines), menu)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: gap-fill parse error")
            return None
        except Exception as e:
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (attempt + 1, str(e)[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


# ---------------------------------------------------------------------------
# Keyword fallback classifier
# ---------------------------------------------------------------------------
def classify_keyword(examples, senses):
    """Keyword overlap classifier — instant, no API. Returns list of sense indices."""
    import re
    _WORD_RE = re.compile(r"[a-z]+")
    _STOP = {"a", "an", "the", "to", "of", "in", "on", "at", "for", "is",
             "it", "be", "as", "or", "by", "and", "not", "with", "from",
             "that", "this", "but", "are", "was", "were", "i", "me", "my",
             "you", "he", "she", "we", "they", "do", "does", "did", "has",
             "have", "had", "will", "would", "can", "could"}

    def tokenize(text):
        return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 1}

    assignments = []
    for ex in examples:
        eng = ex.get("english", "")
        ex_words = tokenize(eng)
        best_idx = 0
        best_score = 0
        for si, s in enumerate(senses):
            sense_words = tokenize(s["translation"])
            score = len(ex_words & sense_words) if sense_words else 0
            if score > best_score:
                best_score = score
                best_idx = si
        assignments.append(best_idx)
    return assignments


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate Wiktionary sense layers for an artist")
    add_artist_arg(parser)
    parser.add_argument("--no-gemini", action="store_true",
                        help="Skip Gemini, use keyword classifier (free, lower accuracy)")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--normal-slang-only", action="store_true",
                        help="Only process normal-mode words that have eswiktionary dialect senses")
    mode_group.add_argument("--new-only", action="store_true",
                        help="Only process non-normal-mode words with corpus_count > 1")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    layers_dir = os.path.join(artist_dir, "data", "layers")

    use_gemini = not args.no_gemini
    if use_gemini:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("ERROR: Set GEMINI_API_KEY env var (or use --no-gemini)")
            sys.exit(1)
    else:
        api_key = None

    # Load word inventory + examples + translations
    print("Loading layers...")
    with open(os.path.join(layers_dir, "word_inventory.json")) as f:
        inventory = json.load(f)
    print("  %d words in inventory" % len(inventory))

    with open(os.path.join(layers_dir, "examples_raw.json")) as f:
        examples_raw = json.load(f)

    translations_path = os.path.join(layers_dir, "example_translations.json")
    with open(translations_path) as f:
        translations = json.load(f)

    # Build word→lemma map from sense menu (and archived senses_gemini if present)
    word_to_lemma = {}
    sense_menu_path = os.path.join(layers_dir, "sense_menu.json")
    if os.path.isfile(sense_menu_path):
        with open(sense_menu_path) as f:
            for key in json.load(f):
                parts = key.split("|", 1)
                if len(parts) == 2:
                    word_to_lemma[parts[0]] = parts[1]
    # Fallback: old senses_gemini.json if it exists
    senses_gemini_path = os.path.join(layers_dir, "senses_gemini.json")
    if os.path.isfile(senses_gemini_path):
        with open(senses_gemini_path) as f:
            for key in json.load(f):
                parts = key.split("|", 1)
                if len(parts) == 2 and parts[0] not in word_to_lemma:
                    word_to_lemma[parts[0]] = parts[1]

    # Load Wiktionary
    print("Loading English Wiktionary...")
    wikt_path = PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz"
    wikt_index, redirects = load_wiktionary(wikt_path)

    print("Loading Spanish Wiktionary (dialect: %s)..." % ", ".join(sorted(DIALECT_TAGS)))
    eswikt_index = load_eswiktionary(ESWIKT_FILE, DIALECT_TAGS)

    # Translation cache for Spanish glosses
    cache_path = PROJECT_ROOT / "pipeline/artist/bench/.eswikt_translation_cache.json"
    translation_cache = {}
    if cache_path.exists():
        with open(cache_path) as f:
            translation_cache = json.load(f)
    print("  %d cached Spanish→English translations" % len(translation_cache))

    # ---------------------------------------------------------------------------
    # Process each word
    # ---------------------------------------------------------------------------
    senses_out = {}        # word|lemma -> [{pos, translation, source}]
    assignments_out = {}   # word -> [{sense_idx, examples, method}]

    single_sense = 0
    multi_sense_queue = []  # (word, lemma, senses, examples_with_eng)
    no_senses_queue = []    # (word, lemma, examples_with_eng)
    no_examples = 0

    # Load word_routing.json for flag-based skipping (preferred, from step 4)
    routing_path = os.path.join(artist_dir, "data", "known_vocab", "word_routing.json")
    skip_set = set()
    routing_data = {}
    if os.path.isfile(routing_path):
        with open(routing_path) as f:
            routing_data = json.load(f)
        exclude = routing_data.get("exclude", {})
        for cat in ("english", "proper_nouns", "interjections"):
            skip_set.update(exclude.get(cat, []))
        skip_set.update(routing_data.get("biencoder", {}).get("shared", []))
        print("  Skip words (from step 4): %d" % len(skip_set))

    # Load master for flag lookups (fallback when skip_words.json absent)
    artists_dir = os.path.dirname(artist_dir)
    master_path = os.path.join(artists_dir, "vocabulary_master.json")
    master_flags = {}
    if os.path.isfile(master_path):
        with open(master_path) as f:
            for mid, mv in json.load(f).items():
                wl = "%s|%s" % (mv["word"], mv.get("lemma", mv["word"]))
                master_flags[wl] = mv

    skipped_flags = 0
    skipped_short = 0
    skipped_not_slang = 0
    skipped_priority = 0

    # Load existing assignments for priority checking + gap-fill reuse
    existing_assigns = {}
    assignments_path = os.path.join(layers_dir, "sense_assignments.json")
    if os.path.isfile(assignments_path):
        with open(assignments_path, "r", encoding="utf-8") as f:
            existing_assigns = json.load(f)

    my_method = "keyword-wiktionary" if not use_gemini else "flash-lite-wiktionary"
    my_priority = METHOD_PRIORITY.get(my_method, 0)

    # For --normal-slang-only: load normal-mode senses
    normal_wl = set()
    if args.normal_slang_only:
        normal_senses_path = PROJECT_ROOT / "Data/Spanish/layers/sense_menu.json"
        if normal_senses_path.exists():
            with open(normal_senses_path) as f:
                normal_wl = set(json.load(f).keys())
            print("  Normal-mode senses: %d entries" % len(normal_wl))

    # For --new-only: use step 4's remaining list as whitelist
    new_only_words = set()
    if args.new_only:
        if os.path.isfile(routing_path):
            new_only_words = set(routing_data.get("gemini", []))
            print("  --new-only whitelist (from step 4): %d words" % len(new_only_words))
        else:
            print("  WARNING: word_routing.json not found — run step 4 first")
            sys.exit(1)

    print("\nProcessing %d words..." % len(inventory))

    for entry in inventory:
        word = entry["word"]
        lemma = word_to_lemma.get(word, word)
        wl_key = "%s|%s" % (word, lemma)
        corpus_count = entry.get("corpus_count", 1)

        # Skip words flagged by step 4 (preferred) or master flags (fallback)
        if word in skip_set:
            skipped_flags += 1
            continue
        mf = master_flags.get(wl_key, {})
        if mf.get("is_english") or mf.get("is_propernoun") or mf.get("is_interjection"):
            skipped_flags += 1
            continue

        # Skip very short words and contractions
        if len(word) <= 2 or "'" in word:
            skipped_short += 1
            continue

        # --normal-slang-only: only process words in normal mode that have eswiktionary senses
        if args.normal_slang_only:
            if wl_key not in normal_wl:
                skipped_not_slang += 1
                continue
            has_eswikt = bool(eswikt_index.get(word) or eswikt_index.get(lemma))
            if not has_eswikt:
                skipped_not_slang += 1
                continue

        # --new-only: only process words in step 4's remaining list
        if args.new_only:
            if word not in new_only_words:
                skipped_not_slang += 1
                continue

        # Skip words with equal or higher priority assignments
        if word in existing_assigns:
            existing_priority = best_method_priority(existing_assigns[word])
            if existing_priority >= my_priority:
                skipped_priority += 1
                continue

        # Get examples with English translations
        raw_exs = examples_raw.get(word, [])
        examples = []
        for ex in raw_exs:
            spa = ex.get("spanish", "")
            eng_obj = translations.get(spa)
            eng = eng_obj.get("english", "") if isinstance(eng_obj, dict) else (eng_obj or "")
            examples.append({"spanish": spa, "english": eng,
                             "song": ex.get("title", ""), "id": ex.get("id", "")})

        if not examples:
            no_examples += 1
            continue

        # Look up Wiktionary senses
        en_senses = lookup_senses(word, lemma, wikt_index, redirects)
        if en_senses:
            for s in en_senses:
                s["translation"] = clean_translation(s["translation"])
            en_senses = merge_similar_senses(en_senses)
        else:
            en_senses = []

        combined = build_combined_senses(word, lemma, en_senses, eswikt_index,
                                         translation_cache)

        if not combined:
            # No Wiktionary entry — queue for gap-fill (only if used more than once)
            if corpus_count > 1:
                no_senses_queue.append((word, lemma, examples))
            continue

        if len(combined) == 1:
            # Single sense: auto-assign all examples
            single_sense += 1
            id_map = assign_sense_ids(combined)
            senses_out[wl_key] = id_map
            sid = list(id_map.keys())[0]
            assignments_out[word] = {"wiktionary-auto": [{
                "sense": sid,
                "examples": list(range(len(examples))),
            }]}
        else:
            # Multi-sense: queue for classification
            multi_sense_queue.append((word, lemma, combined, examples))
            senses_out[wl_key] = assign_sense_ids(combined)

    print("  Skipped (english/propn/intj): %d" % skipped_flags)
    print("  Skipped (short/contraction): %d" % skipped_short)
    if skipped_priority:
        print("  Skipped (higher-priority method): %d" % skipped_priority)
    if args.normal_slang_only:
        print("  Skipped (no eswikt or not in normal): %d" % skipped_not_slang)
    if args.new_only:
        print("  Skipped (normal-mode or freq<=1): %d" % skipped_not_slang)
    print("  No examples (skipped): %d" % no_examples)
    print("  Single-sense (auto-assigned): %d" % single_sense)
    print("  Multi-sense (need classifier): %d" % len(multi_sense_queue))
    print("  No Wiktionary entry (need gap-fill): %d" % len(no_senses_queue))

    # ---------------------------------------------------------------------------
    # Classify multi-sense words
    # ---------------------------------------------------------------------------
    if multi_sense_queue:
        print("\n" + "=" * 60)
        if use_gemini:
            print("CLASSIFYING %d multi-sense words (Flash Lite, batches of %d)" % (
                len(multi_sense_queue), BATCH_SIZE))
        else:
            print("CLASSIFYING %d multi-sense words (keyword fallback)" % len(multi_sense_queue))
        print("=" * 60)

        t_start = time.time()
        checkpoint_path = os.path.join(layers_dir, ".wikt_classify_checkpoint.json")

        # Load checkpoint if exists
        done_words = set()
        if os.path.isfile(checkpoint_path):
            with open(checkpoint_path) as f:
                checkpoint = json.load(f)
            assignments_out.update(checkpoint.get("assignments", {}))
            done_words = set(checkpoint.get("done_words", []))
            print("  Resuming from checkpoint: %d words done" % len(done_words))

        if use_gemini:
            for batch_start in range(0, len(multi_sense_queue), BATCH_SIZE):
                batch = multi_sense_queue[batch_start:batch_start + BATCH_SIZE]
                # Skip batches where all words are already done
                batch = [(w, l, s, ex) for w, l, s, ex in batch if w not in done_words]
                if not batch:
                    continue
                batch_data = [{"word": w, "lemma": l, "senses": s,
                               "examples": ex[:20]}
                              for w, l, s, ex in batch]
                batch_words = [w for w, _, _, _ in batch]
                print("  Batch %d: %s" % (
                    batch_start // BATCH_SIZE + 1, batch_words[:5]))

                results = classify_batch_gemini(batch_data, api_key)

                for i, (word, lemma, senses, examples) in enumerate(batch):
                    wl_key = "%s|%s" % (word, lemma)
                    id_map = senses_out.get(wl_key, {})
                    id_list = list(id_map.keys())  # positional → sense_id

                    if results and i < len(results):
                        r = results[i]
                        raw_assigns = r.get("assignments", {})
                        # Group examples by sense ID
                        sense_buckets = {}
                        for ex_key, sense_idx in raw_assigns.items():
                            idx = int(sense_idx) if str(sense_idx).lstrip("-").isdigit() else 0
                            if idx < 0 or idx >= len(id_list):
                                idx = 0
                            sid = id_list[idx]
                            sense_buckets.setdefault(sid, []).append(
                                int(ex_key) - 1)  # 1-indexed → 0-indexed

                        assignments = []
                        total = sum(len(v) for v in sense_buckets.values())
                        for sid in sorted(sense_buckets):
                            ex_indices = sorted(sense_buckets[sid])
                            freq = len(ex_indices) / total if total else 0
                            if total >= 5 and freq < 0.05:
                                continue
                            assignments.append({
                                "sense": sid,
                                "examples": ex_indices,
                            })
                        if not assignments:
                            assignments = [{"sense": id_list[0],
                                            "examples": list(range(len(examples)))}]
                        assignments_out[word] = {"flash-lite-wiktionary": assignments}
                    else:
                        # Fallback: assign all to first sense
                        assignments_out[word] = {"flash-lite-wiktionary": [{
                            "sense": id_list[0] if id_list else "000",
                            "examples": list(range(len(examples))),
                        }]}
                    done_words.add(word)

                # Checkpoint after each batch
                with open(checkpoint_path, "w") as f:
                    json.dump({"assignments": assignments_out,
                               "done_words": sorted(done_words)}, f)
        else:
            # Keyword fallback
            for word, lemma, senses, examples in multi_sense_queue:
                wl_key = "%s|%s" % (word, lemma)
                id_map = senses_out.get(wl_key, {})
                id_list = list(id_map.keys())
                assigns = classify_keyword(examples, senses)
                sense_buckets = {}
                for ei, si in enumerate(assigns):
                    sid = id_list[si] if si < len(id_list) else id_list[0]
                    sense_buckets.setdefault(sid, []).append(ei)
                assignments = []
                total = len(assigns)
                for sid in sorted(sense_buckets):
                    ex_indices = sorted(sense_buckets[sid])
                    freq = len(ex_indices) / total if total else 0
                    if total >= 5 and freq < 0.05:
                        continue
                    assignments.append({
                        "sense": sid,
                        "examples": ex_indices,
                    })
                if not assignments:
                    assignments = [{"sense": id_list[0],
                                    "examples": list(range(len(examples)))}]
                assignments_out[word] = {"keyword-wiktionary": assignments}

        elapsed = time.time() - t_start
        print("  Done (%.1fs)" % elapsed)

    # ---------------------------------------------------------------------------
    # Gap-fill for words without Wiktionary senses
    # ---------------------------------------------------------------------------
    if no_senses_queue and use_gemini:
        print("\n" + "=" * 60)
        print("GAP-FILL %d words without Wiktionary entry" % len(no_senses_queue))
        print("=" * 60)

        # Check existing assignments for reusable gap-fill senses
        reused = 0
        need_gemini = []
        for word, lemma, examples in no_senses_queue:
            existing = existing_assigns.get(word, {})
            gf = existing.get("gap-fill", [])
            # Reuse if the existing gap-fill has inline sense definitions
            if gf and isinstance(gf[0], dict) and "pos" in gf[0]:
                # Reuse existing inline senses, reassign all examples
                for entry in gf:
                    entry["examples"] = list(range(len(examples)))
                assignments_out[word] = {"gap-fill": gf}
                reused += 1
            else:
                need_gemini.append((word, lemma, examples))

        if reused:
            print("  Reused %d existing gap-fill senses" % reused)

        t_start = time.time()
        proposed = 0
        for word, lemma, examples in need_gemini:
            wl_key = "%s|%s" % (word, lemma)
            result = gap_fill_gemini(word, lemma, [], examples[:20], api_key)
            if result and result.get("proposed_sense"):
                pos = result.get("proposed_pos", "NOUN")
                trans = result["proposed_sense"]
                sense_list = [{"pos": pos, "translation": trans,
                               "source": "gap-fill"}]
                id_map = assign_sense_ids(sense_list)
                # Gap-fill senses stay inline in assignments, not in menu
                sid = list(id_map.keys())[0]
                assignments_out[word] = {"gap-fill": [{
                    "sense": sid,
                    "pos": pos,
                    "translation": trans,
                    "examples": list(range(len(examples))),
                }]}
                proposed += 1
            else:
                # No sense proposed — still record the word with empty senses
                # so the builder can fall back to curated translations
                pass

        elapsed = time.time() - t_start
        print("  Proposed %d new senses (%.1fs)" % (proposed, elapsed))
    elif no_senses_queue:
        print("\nSkipping %d gap-fill words (--no-gemini)" % len(no_senses_queue))

    # ---------------------------------------------------------------------------
    # Write layer files (merge with existing)
    # ---------------------------------------------------------------------------
    senses_path = os.path.join(layers_dir, "sense_menu.json")
    assignments_path = os.path.join(layers_dir, "sense_assignments.json")

    # Merge senses with existing file
    existing_senses = {}
    if os.path.isfile(senses_path):
        with open(senses_path, "r", encoding="utf-8") as f:
            existing_senses = json.load(f)
    existing_senses.update(senses_out)
    with open(senses_path, "w", encoding="utf-8") as f:
        json.dump(existing_senses, f, ensure_ascii=False, indent=2)
    print("\nWrote %s (%d entries, %d new)" % (senses_path, len(existing_senses), len(senses_out)))

    # Merge assignments with existing file
    existing_assigns = {}
    if os.path.isfile(assignments_path):
        with open(assignments_path, "r", encoding="utf-8") as f:
            existing_assigns = json.load(f)
    for word, methods in assignments_out.items():
        if word not in existing_assigns or not isinstance(existing_assigns[word], dict):
            existing_assigns[word] = {}
        existing_assigns[word].update(methods)
    with open(assignments_path, "w", encoding="utf-8") as f:
        json.dump(existing_assigns, f, ensure_ascii=False, indent=2)
    print("Wrote %s (%d entries, %d updated)" % (assignments_path, len(existing_assigns), len(assignments_out)))

    # Save translation cache updates
    if translation_cache:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(translation_cache, f, ensure_ascii=False, indent=2)

    # Clean up checkpoint
    checkpoint_path = os.path.join(layers_dir, ".wikt_classify_checkpoint.json")
    if os.path.isfile(checkpoint_path):
        os.remove(checkpoint_path)

    print("\nDone! Run build_artist_vocabulary.py to rebuild the vocabulary.")


if __name__ == "__main__":
    main()
