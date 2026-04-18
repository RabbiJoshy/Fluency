#!/usr/bin/env python3
"""Generate Wiktionary-based sense layers for an artist.

Produces two layer files in Artists/{lang}/{Name}/data/layers/:
  - senses_wiktionary_gemini.json      (word|lemma -> [{pos, translation, source}])
  - sense_assignments_wiktionary_gemini.json  (word -> [{sense_idx, examples, method}])

For single-sense words: auto-assigns all examples (no API call).
For multi-sense words: Flash Lite classifies examples to senses.
For zero-sense words: Flash Lite gap-fill proposes new senses.

Run from project root:
    .venv/bin/python3 pipeline/step_6c_assign_senses_gemini.py                          # normal mode
    .venv/bin/python3 pipeline/step_6c_assign_senses_gemini.py --artist-dir "Artists/spanish/Bad Bunny"
"""
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")

import argparse, gzip, json, os, re, sys, time
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Make artist-only helpers importable when running in artist mode.
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))

from step_5c_build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses)
from util_1a_artist_config import (load_artist_config,
                           artist_sense_menu_path, artist_sense_assignments_path,
                           load_dotenv_from_project_root)
from util_6a_method_priority import (METHOD_PRIORITY, best_method_priority,
                                     assign_sense_ids)
from util_6a_assignment_format import load_assignments, dump_assignments
from util_7a_lemma_split import merge_method_maps
from util_5c_sense_paths import sense_menu_path, sense_assignments_path
from util_6a_pos_menu_filter import (
    filter_senses_by_pos, filter_senses_by_precomputed_pos,
    sense_compatible_with_example_pos,
)
from util_5c_sense_menu_format import (
    normalize_artist_sense_menu, merge_analysis, get_analyses,
    collect_surface_analyses_from_shared_menu, flatten_analyses_with_ids,
    assign_analysis_sense_ids, extract_form_of_targets, extend_ids_for_extra_senses,
)
load_dotenv_from_project_root()


def _format_sense_line(idx, label, sense):
    """Format one candidate sense for a Gemini prompt.

    Adds `context` inline (in parentheses after the translation), and tacks
    a Wiktionary example onto a follow-up line when one is present. Both
    fields are optional — the formatter degrades gracefully to the old
    `"  idx. [POS] translation"` shape when the sense only carries the
    required keys.
    """
    base = "  %d. %s[%s] %s" % (idx, label, sense["pos"], sense["translation"])
    ctx = sense.get("context")
    if ctx:
        # Short contexts inline; keep the line compact enough to batch.
        base += " (%s)" % ctx[:80]
    register = sense.get("register") or []
    if register:
        base += " [%s]" % ",".join(register[:3])
    ex = sense.get("example") or {}
    target = (ex.get("target") or "").strip()
    english = (ex.get("english") or "").strip()
    if target and english:
        base += "\n     e.g. %s → %s" % (target[:80], english[:80])
    return base


# ---------------------------------------------------------------------------
# Spanish Wiktionary dialect supplement (inlined from bench_gapfill)
# ---------------------------------------------------------------------------
ESWIKT_FILE = PROJECT_ROOT / "Data/Spanish/Senses/wiktionary/kaikki-eswiktionary-raw.jsonl.gz"
DEFAULT_DIALECT_TAGS = {"Puerto-Rico", "Caribbean", "Cuba"}
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
BATCH_SIZE = 50
GAP_FILL_BATCH_SIZE = 10
# Default per-word example cap. Override with --max-examples. When re-running
# with a higher value, already-classified indices are preserved and only the
# new ones are sent to Gemini.
DEFAULT_MAX_EXAMPLES_PER_WORD = 10


def classify_batch_gemini(words_data, api_key, gemini_model):
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
            prompt_parts.append(_format_sense_line(si, label, s))
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
                model=gemini_model,
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


def gap_fill_gemini(word, lemma, senses, examples, api_key, gemini_model):
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
        ' flashcard translation and ONE best-guess lemma/headword.\n\n'
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
        '  "proposed_lemma": "<best-guess Spanish lemma/headword if proposing, else null>",\n'
        '  "examples_needing_new_sense": <count of examples that need the new sense, 0 if covered>\n'
        '}'
    ) % (word, lemma, word, "\n".join(lines), menu)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=gemini_model,
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


def gap_fill_batch_gemini(words_data, api_key, gemini_model):
    """Ask Gemini to propose or reuse one sense for a batch of gap-fill words."""
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt_parts = [
        "You are helping build a Spanish vocabulary flashcard app for learners.",
        "For each word below, decide whether the examples are covered by an existing",
        "dictionary sense menu. If not, propose ONE short flashcard-friendly sense.",
        "Return a JSON array with one object per word.",
        "",
    ]

    for wi, wd in enumerate(words_data, start=1):
        prompt_parts.append('--- Word %d: "%s" (lemma: %s) ---' % (
            wi, wd["word"], wd["lemma"]))
        if wd.get("senses"):
            prompt_parts.append("Candidate senses:")
            for si, s in enumerate(wd["senses"], start=1):
                label = "[ES] " if s.get("is_spanish") else ""
                prompt_parts.append(_format_sense_line(si, label, s))
        else:
            prompt_parts.append("Candidate senses: (none)")
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"], start=1):
            prompt_parts.append("  %d. %s | %s" % (
                ei, ex.get("spanish", ""), ex.get("english", "")))
        prompt_parts.append("")

    prompt_parts.append("Return JSON like:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "covered_by_existing": False,
        "best_sense_index": None,
        "english_translation": None,
        "proposed_sense": "short meaning",
        "proposed_pos": "NOUN",
        "proposed_lemma": "hablar"
    }], indent=2))

    prompt = "\n".join(prompt_parts)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: gap-fill batch parse error")
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


def normalize_assignment_methods(word_data, default_method):
    """Coerce legacy or malformed assignment payloads to {method: [items]}."""
    if isinstance(word_data, dict):
        return word_data
    if isinstance(word_data, list):
        return {default_method: word_data}
    return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate Wiktionary sense layers via Gemini Flash Lite")
    parser.add_argument("--artist-dir", default=None,
                        help="Artist directory (e.g. Artists/spanish/Bad Bunny). "
                             "Omit for normal mode (Data/Spanish).")
    parser.add_argument("--no-gemini", action="store_true",
                        help="Skip Gemini, use keyword classifier (free, lower accuracy)")
    parser.add_argument("--all-gemini", action="store_true",
                        help="Treat biencoder-routed words as Gemini candidates for this run")
    parser.add_argument("--force", action="store_true",
                        help="Re-classify all eligible words (ignore existing assignments)")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite",
                        help="Gemini model to use when Gemini is enabled")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--normal-slang-only", action="store_true",
                        help="Only process normal-mode words that have eswiktionary dialect senses")
    mode_group.add_argument("--new-only", action="store_true",
                        help="Only process non-normal-mode words with corpus_count > 1")
    parser.add_argument("--sense-menu-file", type=str, default=None,
                        help="Alternative artist-layer menu file to read instead of building from Wiktionary")
    parser.add_argument("--assignments-file", type=str, default="sense_assignments/wiktionary.json",
                        help="Artist-layer assignments file to write (default: sense_assignments/wiktionary.json)")
    parser.add_argument("--method-name", type=str, default=None,
                        help="Method key override for classified multi-sense words")
    parser.add_argument("--keyword-method-name", type=str, default=None,
                        help="Method key override when --no-gemini is used")
    parser.add_argument("--auto-method-name", type=str, default="wiktionary-auto",
                        help="Method key for auto-assigned single-sense words")
    parser.add_argument("--menu-source-label", type=str, default="wiktionary",
                        help="Source label for reporting with --sense-menu-file")
    parser.add_argument("--include-clitics", action="store_true",
                        help="Include clitic-merge words (skipped by default)")
    parser.add_argument("--skip-classification", action="store_true",
                        help="Skip multi-sense classification; only run gap-fill.")
    parser.add_argument("--skip-gap-fill", action="store_true",
                        help="Skip gap-fill for zero-sense words; only run classification.")
    parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES_PER_WORD,
                        help="Max examples per word to classify (default %d). "
                             "Re-running with a larger value picks up where the "
                             "previous run left off — already-classified example "
                             "indices for the same method are skipped and only "
                             "the new ones are sent to Gemini." %
                             DEFAULT_MAX_EXAMPLES_PER_WORD)
    args = parser.parse_args()
    if args.max_examples < 1:
        print("ERROR: --max-examples must be >= 1")
        sys.exit(1)

    is_artist = args.artist_dir is not None
    if is_artist:
        artist_dir = os.path.abspath(args.artist_dir)
        config = load_artist_config(artist_dir)
        layers_dir = os.path.join(artist_dir, "data", "layers")
    else:
        artist_dir = None
        config = {}
        layers_dir = str(PROJECT_ROOT / "Data" / "Spanish" / "layers")

    use_gemini = not args.no_gemini
    gemini_model = args.gemini_model
    custom_menu_mode = bool(args.sense_menu_file)
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

    # Normal-mode schema uses `target` (Spanish) + inline `english`. Downstream
    # code expects the artist schema (`spanish` + separate translations dict),
    # so shim the examples in place.
    if not is_artist:
        for _exs in examples_raw.values():
            for _ex in _exs:
                if "spanish" not in _ex and "target" in _ex:
                    _ex["spanish"] = _ex["target"]

    example_pos = {}
    example_pos_path = os.path.join(layers_dir, "example_pos.json")
    if os.path.isfile(example_pos_path):
        with open(example_pos_path) as f:
            example_pos = json.load(f)
        example_pos.pop("_example_ids", None)
        print("  example_pos: %d words" % len(example_pos))
    else:
        print("  example_pos: (not found, spaCy fallback)")

    translations_path = os.path.join(layers_dir, "example_translations.json")
    if os.path.isfile(translations_path):
        with open(translations_path) as f:
            translations = json.load(f)
    elif is_artist:
        raise SystemExit("example_translations.json not found: %s" % translations_path)
    else:
        # Normal mode: translations live inline on each example record.
        translations = {}
        for _exs in examples_raw.values():
            for _ex in _exs:
                _spa = _ex.get("target") or _ex.get("spanish")
                _eng = _ex.get("english")
                if _spa and _eng:
                    translations[_spa] = {"english": _eng}
        print("  translations (inline from examples_raw): %d entries" % len(translations))

    if custom_menu_mode:
        custom_menu_path = Path(layers_dir) / args.sense_menu_file
        if not custom_menu_path.exists():
            print("ERROR: Alternative sense menu not found: %s" % custom_menu_path)
            sys.exit(1)
        with open(custom_menu_path) as f:
            shared_wikt_menu = normalize_artist_sense_menu(json.load(f))
        wikt_index = {}
        redirects = {}
        eswikt_index = {}
        cache_path = None
        translation_cache = {}
        print("Loading alternative sense menu: %s (%d words)" % (
            custom_menu_path.name, len(shared_wikt_menu)))
    else:
        # Load Wiktionary
        print("Loading English Wiktionary...")
        wikt_path = PROJECT_ROOT / "Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz"
        wikt_index, redirects = load_wiktionary(wikt_path)

        # Shared Wiktionary menu. In artist mode this is the normal-mode menu
        # used as a fallback base; in normal mode it's our own output menu.
        if is_artist:
            shared_menu_candidates = [
                PROJECT_ROOT / "Data/Spanish/layers/sense_menu/wiktionary.json",
            ]
        else:
            shared_menu_candidates = [sense_menu_path(layers_dir, "wiktionary")]
        shared_wikt_menu = {}
        for cand in shared_menu_candidates:
            if Path(cand).exists():
                with open(cand) as f:
                    shared_wikt_menu = json.load(f)
                break

        # Dialect supplement (eswiktionary) is artist-specific: normal mode
        # already merges dialect senses into its menu at step 5c.
        if is_artist:
            dialect_tags = set(config.get("dialect_tags", DEFAULT_DIALECT_TAGS))
            print("Loading Spanish Wiktionary (dialect: %s)..." % ", ".join(sorted(dialect_tags)))
            eswikt_index = load_eswiktionary(ESWIKT_FILE, dialect_tags)

            # Translation cache for Spanish glosses
            cache_path = PROJECT_ROOT / "pipeline/artist/bench/.eswikt_translation_cache.json"
            translation_cache = {}
            if cache_path.exists():
                with open(cache_path) as f:
                    translation_cache = json.load(f)
            print("  %d cached Spanish→English translations" % len(translation_cache))
        else:
            eswikt_index = {}
            cache_path = None
            translation_cache = {}

    # ---------------------------------------------------------------------------
    # Process each word
    # ---------------------------------------------------------------------------
    senses_out = {}        # word -> [{lemma, senses}]
    assignments_out = {}   # word -> [{sense_idx, examples, method}]

    single_sense = 0
    multi_sense_queue = []  # (word, lemma, senses, examples_with_eng)
    no_senses_queue = []    # (word, lemma, examples_with_eng)
    no_examples = 0

    # Load word_routing.json for flag-based skipping (preferred, from step 4)
    if is_artist:
        routing_path = os.path.join(artist_dir, "data", "known_vocab", "word_routing.json")
    else:
        routing_path = os.path.join(layers_dir, "word_routing.json")
    skip_set = set()
    routing_data = {}
    if os.path.isfile(routing_path):
        with open(routing_path) as f:
            routing_data = json.load(f)
        exclude = routing_data.get("exclude", {})
        for cat in ("english", "proper_nouns", "interjections"):
            skip_set.update(exclude.get(cat, []))
        if not args.all_gemini:
            skip_set.update(routing_data.get("biencoder", {}).get("shared", []))
        # Skip merge-clitics (folded into base verb, don't need assignment)
        if not args.include_clitics:
            clitic_merge = routing_data.get("clitic_merge", {})
            if isinstance(clitic_merge, dict):
                skip_set.update(clitic_merge.keys())
        print("  Skip words (from step 4): %d" % len(skip_set))

    # Load master for flag lookups (fallback when skip_words.json absent).
    # Master vocabulary is artist-mode only.
    master_flags = {}
    if is_artist:
        artists_dir = os.path.dirname(artist_dir)
        master_path = os.path.join(artists_dir, "vocabulary_master.json")
        if os.path.isfile(master_path):
            with open(master_path) as f:
                for mid, mv in json.load(f).items():
                    wl = "%s|%s" % (mv["word"], mv.get("lemma", mv["word"]))
                    master_flags[wl] = mv

    skipped_flags = 0
    skipped_short = 0
    skipped_not_slang = 0
    skipped_priority = 0
    pos_filtered_count = 0
    pos_single_sense_count = 0

    # Load existing assignments for priority checking + gap-fill reuse
    existing_assigns = {}
    if args.assignments_file == "sense_assignments/wiktionary.json":
        if is_artist:
            assignments_path = artist_sense_assignments_path(layers_dir, "wiktionary")
        else:
            assignments_path = str(sense_assignments_path(layers_dir, "wiktionary"))
    else:
        assignments_path = os.path.join(layers_dir, args.assignments_file)
    if os.path.isfile(assignments_path):
        existing_assigns = load_assignments(assignments_path)

    if args.method_name and use_gemini:
        my_method = args.method_name
    elif args.keyword_method_name and not use_gemini:
        my_method = args.keyword_method_name
    elif custom_menu_mode and not use_gemini:
        my_method = "spanishdict-keyword"
    elif custom_menu_mode and "flash-lite" in gemini_model:
        my_method = "spanishdict-flash-lite"
    elif custom_menu_mode:
        my_method = "spanishdict-flash"
    elif not use_gemini:
        my_method = "keyword-wiktionary"
    elif "flash-lite" in gemini_model:
        my_method = "flash-lite-wiktionary"
    else:
        my_method = "flash-wiktionary"
    my_priority = METHOD_PRIORITY.get(my_method, 0)

    # For --normal-slang-only: load normal-mode senses
    normal_wl = set()
    if args.normal_slang_only:
        normal_senses_path = PROJECT_ROOT / "Data/Spanish/layers/sense_menu/wiktionary.json"
        if normal_senses_path.exists():
            with open(normal_senses_path) as f:
                normal_wl = set(json.load(f).keys())
            print("  Normal-mode senses: %d entries" % len(normal_wl))

    # For --new-only: use step 4's remaining list as whitelist
    new_only_words = set()
    if args.new_only:
        if os.path.isfile(routing_path):
            new_only_words = set(routing_data.get("gemini", []))
            if args.all_gemini:
                for value in routing_data.get("biencoder", {}).values():
                    if isinstance(value, list):
                        new_only_words.update(value)
                    elif isinstance(value, dict):
                        new_only_words.update(value.keys())
            print("  --new-only whitelist (from step 4): %d words" % len(new_only_words))
        else:
            print("  WARNING: word_routing.json not found — run step 4 first")
            sys.exit(1)

    print("\nProcessing %d words..." % len(inventory))

    for entry in inventory:
        word = entry["word"]
        lemma = word
        corpus_count = entry.get("corpus_count", 1)

        # Skip words flagged by step 4 (preferred) or master flags (fallback)
        if word in skip_set:
            skipped_flags += 1
            continue
        # Skip contractions (elision forms handled by step 3's merge).
        # We no longer blanket-skip len<=2 — that was a legacy cost-saver
        # that broke Gemini classification for core function words (de, no,
        # y, en, me, lo, el, se, te, mi, tu, un, a). word_routing.exclude
        # and the noise curation already handle genuine single-letter noise.
        if "'" in word:
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

        # Skip words claimed by a STRICTLY higher-priority method. For the same
        # method we used to also skip at word level; now that selection is
        # example-level, equal priority is handled by the covered-index filter
        # below instead.
        if word in existing_assigns and not args.force:
            existing_priority = best_method_priority(existing_assigns[word])
            if existing_priority > my_priority:
                skipped_priority += 1
                continue

        # Target window into the stable per-word examples list. Positional
        # indices are preserved across re-runs by step_5a_split_evidence, so
        # absolute indices are safe to store and re-use.
        all_exs = examples_raw.get(word, [])
        target_end = min(len(all_exs), args.max_examples)
        if target_end == 0:
            no_examples += 1
            continue

        # Which absolute indices is THIS method already responsible for?
        # Only same-method coverage counts — we want incrementality inside
        # gemini runs, but a prior biencoder assignment shouldn't block gemini
        # from doing its own pass.
        covered_abs = set()
        if not args.force and word in existing_assigns:
            for item in existing_assigns[word].get(my_method, []) or []:
                for abs_i in item.get("examples", []) or []:
                    if isinstance(abs_i, int):
                        covered_abs.add(abs_i)
            # Single-sense auto-assignment uses auto_method_name, not my_method.
            # Treat those as covered too so re-runs don't re-auto-assign them.
            for item in existing_assigns[word].get(args.auto_method_name, []) or []:
                for abs_i in item.get("examples", []) or []:
                    if isinstance(abs_i, int):
                        covered_abs.add(abs_i)

        # Build the (abs_idx, ex) list of NEW examples in the target window.
        selected = [(abs_i, all_exs[abs_i]) for abs_i in range(target_end)
                    if abs_i not in covered_abs]
        if not selected:
            # Target window fully covered by prior same-method work — nothing
            # to do. Any existing assignment is preserved untouched.
            skipped_priority += 1
            continue

        examples = []
        abs_indices = []
        for abs_i, ex in selected:
            spa = ex.get("spanish", "")
            # Normalize elided surface forms to canonical word for Gemini
            surface = ex.get("surface")
            if surface and surface.lower() != word.lower() and spa:
                spa = re.sub(re.escape(surface), word, spa, count=1, flags=re.IGNORECASE)
            original_spa = ex.get("spanish", "")  # original for translation lookup
            eng_obj = translations.get(original_spa)
            eng = eng_obj.get("english", "") if isinstance(eng_obj, dict) else (eng_obj or "")
            examples.append({"spanish": spa, "english": eng,
                             "song": ex.get("title", ""), "id": ex.get("id", "")})
            abs_indices.append(abs_i)

        if not examples:
            no_examples += 1
            continue

        precomputed = {int(k): v for k, v in example_pos.get(word, {}).items()}
        wl_key = "%s|%s" % (word, lemma)
        mf = master_flags.get(wl_key, {})
        if mf.get("is_english") or mf.get("is_propernoun") or mf.get("is_interjection"):
            skipped_flags += 1
            continue

        id_list = []
        # Build the candidate menu from all shared surface-form analyses first.
        if custom_menu_mode:
            shared_analyses = []
            for analysis in get_analyses(shared_wikt_menu, word):
                sense_map = analysis.get("senses", {})
                shared_analyses.append({
                    "headword": analysis.get("headword", analysis.get("lemma", word)),
                    "senses": list(deepcopy(sense_map).values()) if isinstance(sense_map, dict) else deepcopy(sense_map or []),
                })
        else:
            shared_analyses = collect_surface_analyses_from_shared_menu(word, shared_wikt_menu)
        if shared_analyses and not custom_menu_mode:
            present_lemmas = {a.get("headword", a.get("lemma", word)) for a in shared_analyses}
            for target_lemma in extract_form_of_targets(shared_analyses):
                if target_lemma in present_lemmas:
                    continue
                target_senses = lookup_senses(word, target_lemma, wikt_index, redirects)
                if not target_senses:
                    continue
                for s in target_senses:
                    s["translation"] = clean_translation(s["translation"])
                target_senses = merge_similar_senses(target_senses)
                if target_senses:
                    shared_analyses.append({"headword": target_lemma, "senses": target_senses})
                    present_lemmas.add(target_lemma)
        if shared_analyses:
            en_senses, id_list, normalized_analyses = flatten_analyses_with_ids(shared_analyses)
            if not custom_menu_mode:
                for analysis in normalized_analyses:
                    merge_analysis(senses_out, word, analysis.get("headword", analysis.get("lemma")), analysis.get("senses", {}))
        else:
            en_senses = []
        if not en_senses and not custom_menu_mode:
            en_senses = lookup_senses(word, lemma, wikt_index, redirects)
            if en_senses:
                for s in en_senses:
                    s["translation"] = clean_translation(s["translation"])
                en_senses = merge_similar_senses(en_senses)
            else:
                en_senses = []

        if custom_menu_mode:
            combined = en_senses
        else:
            combined = build_combined_senses(word, lemma, en_senses, eswikt_index,
                                             translation_cache)
        if id_list and len(combined) > len(id_list):
            id_list.extend(
                extend_ids_for_extra_senses(id_list, lemma, combined[len(id_list):])
            )

        if not combined:
            # No entry — queue for gap-fill for either Wiktionary or custom menu sources.
            if corpus_count > 1:
                no_senses_queue.append((word, lemma, examples, abs_indices))
            continue

        keep_indices = list(range(len(combined)))
        if precomputed:
            pos_keep_indices, pos_stats = filter_senses_by_precomputed_pos(combined, precomputed)
        else:
            pos_keep_indices, pos_stats = filter_senses_by_pos(word, lemma, combined, examples)
        if pos_stats.get("used") and pos_stats.get("reduced"):
            keep_indices = pos_keep_indices
            pos_filtered_count += 1

        if len(keep_indices) == 1:
            # Single sense: auto-assign the NEW examples (absolute indices).
            single_sense += 1
            if len(combined) > 1:
                pos_single_sense_count += 1
            filtered_combined = [combined[keep_indices[0]]]
            if shared_analyses:
                sid = id_list[keep_indices[0]]
            else:
                id_map = assign_analysis_sense_ids(lemma, filtered_combined)
                if not custom_menu_mode:
                    merge_analysis(senses_out, word, None, id_map)
                sid = list(id_map.keys())[0]
            assignments_out[word] = {args.auto_method_name: [{
                "sense": sid,
                "examples": list(abs_indices),
            }]}
        else:
            # Multi-sense at the word level. Before batching to Gemini, run a
            # per-example pos-auto pre-filter: examples whose trusted POS tag
            # narrows candidates to exactly 1 sense get assigned inline and
            # never see the API. Only ambiguous-POS examples are sent.
            #
            # Cost saving: across every language with a POS tagger and
            # polysemous menus, a large fraction of examples resolve on POS
            # alone — those used to burn prompt tokens re-confirming a
            # single candidate.
            filtered_combined = [combined[i] for i in keep_indices]
            filtered_ids = [id_list[i] for i in keep_indices] if shared_analyses else None
            if not shared_analyses and not custom_menu_mode:
                id_map = assign_analysis_sense_ids(lemma, filtered_combined)
                merge_analysis(senses_out, word, lemma, id_map)
                local_id_list = list(id_map.keys())
            else:
                local_id_list = filtered_ids or [id_list[i] for i in keep_indices]

            pos_auto_by_sense = {}  # local keep-index -> [abs_ex_idx]
            classify_local_indices = []  # positions within examples/abs_indices
            for local_pos, ex in enumerate(examples):
                abs_ex_idx = abs_indices[local_pos]
                ex_pos = precomputed.get(abs_ex_idx)
                if ex_pos:
                    pos_candidates = [k for k in range(len(keep_indices))
                                      if sense_compatible_with_example_pos(
                                          filtered_combined[k].get("pos"), ex_pos)]
                    if not pos_candidates:
                        pos_candidates = list(range(len(keep_indices)))
                else:
                    pos_candidates = list(range(len(keep_indices)))

                if len(pos_candidates) == 1:
                    pos_auto_by_sense.setdefault(pos_candidates[0], []).append(abs_ex_idx)
                else:
                    classify_local_indices.append(local_pos)

            if pos_auto_by_sense:
                assignments_out.setdefault(word, {})["pos-auto"] = [
                    {"sense": local_id_list[k], "examples": eis}
                    for k, eis in pos_auto_by_sense.items()
                ]
                pos_single_sense_count += 1

            # If pos-auto handled every example, nothing left for Gemini.
            if classify_local_indices:
                classify_examples = [examples[i] for i in classify_local_indices]
                classify_abs = [abs_indices[i] for i in classify_local_indices]
                multi_sense_queue.append((word, lemma, filtered_combined,
                                          classify_examples, filtered_ids,
                                          classify_abs))

    print("  Skipped (english/propn/intj): %d" % skipped_flags)
    print("  Skipped (short/contraction): %d" % skipped_short)
    if skipped_priority:
        print("  Skipped (higher-priority method): %d" % skipped_priority)
    if args.normal_slang_only:
        print("  Skipped (no eswikt or not in normal): %d" % skipped_not_slang)
    if args.new_only:
        print("  Skipped (normal-mode or freq<=1): %d" % skipped_not_slang)
    if pos_filtered_count:
        print("  POS-filtered menus: %d" % pos_filtered_count)
    if pos_single_sense_count:
        print("  POS-resolved to single sense: %d" % pos_single_sense_count)
    print("  No examples (skipped): %d" % no_examples)
    print("  Single-sense (auto-assigned): %d" % single_sense)
    print("  Multi-sense (need classifier): %d" % len(multi_sense_queue))
    print("  No sense menu entry (need gap-fill): %d" % len(no_senses_queue))

    # ---------------------------------------------------------------------------
    # Classify multi-sense words
    # ---------------------------------------------------------------------------
    if args.skip_classification:
        print("\n  Skipping multi-sense classification (--skip-classification)")
        multi_sense_queue = []
    if multi_sense_queue:
        print("\n" + "=" * 60)
        if use_gemini:
            print("CLASSIFYING %d multi-sense words (%s, batches of %d)" % (
                len(multi_sense_queue), gemini_model, BATCH_SIZE))
        else:
            print("CLASSIFYING %d multi-sense words (keyword fallback)" % len(multi_sense_queue))
        print("=" * 60)

        t_start = time.time()
        checkpoint_path = os.path.join(layers_dir, ".%s.checkpoint.json" % Path(args.assignments_file).stem)

        # Load checkpoint if exists
        done_words = set()
        if os.path.isfile(checkpoint_path):
            with open(checkpoint_path) as f:
                checkpoint = json.load(f)
            for word, word_data in checkpoint.get("assignments", {}).items():
                assignments_out[word] = normalize_assignment_methods(
                    word_data,
                    my_method,
                )
            done_words = set(checkpoint.get("done_words", []))
            print("  Resuming from checkpoint: %d words done" % len(done_words))

        if use_gemini:
            for batch_start in range(0, len(multi_sense_queue), BATCH_SIZE):
                batch = multi_sense_queue[batch_start:batch_start + BATCH_SIZE]
                # Skip batches where all words are already done
                batch = [tup for tup in batch if tup[0] not in done_words]
                if not batch:
                    continue
                batch_data = [{"word": w, "lemma": l, "senses": s,
                               "examples": ex}
                              for w, l, s, ex, ids, abs_idx in batch]
                batch_words = [tup[0] for tup in batch]
                print("  Batch %d: %s" % (
                    batch_start // BATCH_SIZE + 1, batch_words[:5]))

                results = classify_batch_gemini(batch_data, api_key, gemini_model)

                for i, (word, lemma, senses, examples, explicit_ids, abs_idx_list) in enumerate(batch):
                    id_list = explicit_ids or list(assign_analysis_sense_ids(lemma, senses).keys())

                    if results and i < len(results):
                        r = results[i]
                        raw_assigns = r.get("assignments", {})
                        # Group examples by sense ID, translating Gemini's
                        # 1-indexed local position back to the absolute index
                        # in examples_raw[word].
                        sense_buckets = {}
                        for ex_key, sense_idx in raw_assigns.items():
                            idx = int(sense_idx) if str(sense_idx).lstrip("-").isdigit() else 0
                            if idx < 0 or idx >= len(id_list):
                                idx = 0
                            sid = id_list[idx]
                            local_ex_idx = int(ex_key) - 1  # 1-indexed → 0-indexed local
                            if not (0 <= local_ex_idx < len(abs_idx_list)):
                                continue
                            abs_ex_idx = abs_idx_list[local_ex_idx]
                            sense_buckets.setdefault(sid, []).append(abs_ex_idx)

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
                                            "examples": list(abs_idx_list)}]
                        assignments_out[word] = {my_method: assignments}
                    else:
                        # Fallback: assign all to first sense (absolute indices)
                        assignments_out[word] = {my_method: [{
                            "sense": id_list[0] if id_list else "000",
                            "examples": list(abs_idx_list),
                        }]}
                    done_words.add(word)

                # Checkpoint after each batch
                with open(checkpoint_path, "w") as f:
                    json.dump({"assignments": assignments_out,
                               "done_words": sorted(done_words)}, f)
        else:
            # Keyword fallback
            for word, lemma, senses, examples, explicit_ids, abs_idx_list in multi_sense_queue:
                id_list = explicit_ids or list(assign_analysis_sense_ids(lemma, senses).keys())
                assigns = classify_keyword(examples, senses)
                sense_buckets = {}
                for ei, si in enumerate(assigns):
                    sid = id_list[si] if si < len(id_list) else id_list[0]
                    if not (0 <= ei < len(abs_idx_list)):
                        continue
                    sense_buckets.setdefault(sid, []).append(abs_idx_list[ei])
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
                                    "examples": list(abs_idx_list)}]
                assignments_out[word] = {my_method: assignments}

        elapsed = time.time() - t_start
        print("  Done (%.1fs)" % elapsed)

    # ---------------------------------------------------------------------------
    # Gap-fill for words without any usable sense menu
    # ---------------------------------------------------------------------------
    if args.skip_gap_fill:
        print("\n  Skipping gap-fill (--skip-gap-fill)")
        no_senses_queue = []
    if no_senses_queue and use_gemini:
        print("\n" + "=" * 60)
        print("GAP-FILL %d words without sense-menu entry" % len(no_senses_queue))
        print("=" * 60)

        # Check existing assignments for reusable gap-fill senses
        reused = 0
        need_gemini = []
        for word, lemma, examples, abs_idx_list in no_senses_queue:
            existing = existing_assigns.get(word, {})
            gf = existing.get("gap-fill", [])
            # Reuse if the existing gap-fill has inline sense definitions
            if gf and isinstance(gf[0], dict) and "pos" in gf[0]:
                # Reuse existing inline senses and union NEW example indices
                # onto the first entry (classifier has no way to route them to
                # a specific sense without another API call — first entry is
                # the conservative default).
                existing_covered = set()
                for entry in gf:
                    existing_covered.update(
                        int(i) for i in (entry.get("examples") or [])
                        if isinstance(i, int)
                    )
                new_abs = [i for i in abs_idx_list if i not in existing_covered]
                if new_abs:
                    gf[0]["examples"] = sorted(
                        set(int(i) for i in (gf[0].get("examples") or []) if isinstance(i, int))
                        | set(new_abs)
                    )
                assignments_out[word] = {"gap-fill": gf}
                reused += 1
            else:
                need_gemini.append((word, lemma, examples, abs_idx_list))

        if reused:
            print("  Reused %d existing gap-fill senses" % reused)

        t_start = time.time()
        proposed = 0
        for batch_start in range(0, len(need_gemini), GAP_FILL_BATCH_SIZE):
            batch = need_gemini[batch_start:batch_start + GAP_FILL_BATCH_SIZE]
            batch_words = [tup[0] for tup in batch]
            print("  Gap-fill batch %d: %s" % (
                batch_start // GAP_FILL_BATCH_SIZE + 1, batch_words[:5]))
            batch_data = [{
                "word": word,
                "lemma": lemma,
                "senses": [],
                "examples": examples,
            } for word, lemma, examples, abs_idx_list in batch]
            results = gap_fill_batch_gemini(batch_data, api_key, gemini_model)
            result_map = {}
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and item.get("word"):
                        result_map[item["word"]] = item

            for word, lemma, examples, abs_idx_list in batch:
                result = result_map.get(word)
                if result and result.get("proposed_sense"):
                    pos = result.get("proposed_pos", "NOUN")
                    trans = result["proposed_sense"]
                    sense_list = [{"pos": pos, "translation": trans,
                                   "source": "gap-fill"}]
                    id_map = assign_sense_ids(sense_list)
                    sid = list(id_map.keys())[0]
                    assignments_out[word] = {"gap-fill": [{
                        "sense": sid,
                        "pos": pos,
                        "translation": trans,
                        "lemma": result.get("proposed_lemma") or lemma,
                        "examples": list(abs_idx_list),
                    }]}
                    proposed += 1

        elapsed = time.time() - t_start
        print("  Proposed %d new senses (%.1fs)" % (proposed, elapsed))
    elif no_senses_queue:
        print("\nSkipping %d gap-fill words (--no-gemini)" % len(no_senses_queue))

    # ---------------------------------------------------------------------------
    # Write layer files (merge with existing)
    # ---------------------------------------------------------------------------
    if not custom_menu_mode:
        if is_artist:
            senses_path = artist_sense_menu_path(layers_dir, "wiktionary")
        else:
            senses_path = str(sense_menu_path(layers_dir, "wiktionary"))
        existing_senses = {}
        if os.path.isfile(senses_path):
            with open(senses_path, "r", encoding="utf-8") as f:
                existing_senses = normalize_artist_sense_menu(json.load(f))
        for word, analyses in senses_out.items():
            for analysis in analyses:
                merge_analysis(existing_senses, word, analysis.get("headword", analysis.get("lemma")), analysis.get("senses", {}))
        with open(senses_path, "w", encoding="utf-8") as f:
            json.dump(existing_senses, f, ensure_ascii=False, indent=2)
        print("\nWrote %s (%d entries, %d new)" % (senses_path, len(existing_senses), len(senses_out)))

    # Merge assignments with existing file.
    #
    # Incremental mode (the default): new items for the SAME method are unioned
    # with existing items via merge_method_maps — same sense ID wins its old
    # example list merged with the new one; new sense IDs are appended. Other
    # methods on the same word are preserved untouched.
    #
    # --force replaces the current method's entries wholesale (and still leaves
    # other methods alone).
    existing_assigns = {}
    if os.path.isfile(assignments_path):
        existing_assigns = load_assignments(assignments_path)
    stale_auto_wiped = 0
    for word, methods in assignments_out.items():
        if word not in existing_assigns or not isinstance(existing_assigns[word], dict):
            existing_assigns[word] = {}
        incoming = normalize_assignment_methods(methods, my_method)
        # Stale-auto cleanup: if the new write has any non-auto method
        # (priority > 0), drop any existing priority-0 auto entries. Those
        # blanket claims were valid only when the menu had a single sense;
        # a word now earning pos-auto / Gemini / gap-fill stamps is
        # multi-sense by construction and the old blanket would stealthily
        # outvote unassigned examples in the resolver.
        incoming_has_non_auto = any(
            METHOD_PRIORITY.get(m, 0) > 0 for m in incoming
        )
        if incoming_has_non_auto:
            for m in list(existing_assigns[word].keys()):
                if METHOD_PRIORITY.get(m, 0) == 0:
                    existing_assigns[word].pop(m, None)
                    stale_auto_wiped += 1
        if args.force:
            # Drop only the methods we're re-writing; keep others.
            for m in incoming.keys():
                existing_assigns[word].pop(m, None)
            existing_assigns[word].update(incoming)
        else:
            existing_assigns[word] = merge_method_maps(existing_assigns[word], incoming)
    if stale_auto_wiped:
        print("  Dropped %d stale priority-0 auto entries (menu now multi-sense)"
              % stale_auto_wiped)
    dump_assignments(existing_assigns, assignments_path)
    print("Wrote %s (%d entries, %d updated)" % (assignments_path, len(existing_assigns), len(assignments_out)))

    # Save translation cache updates
    if translation_cache and cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(translation_cache, f, ensure_ascii=False, indent=2)

    # Clean up checkpoint
    checkpoint_path = os.path.join(layers_dir, ".%s.checkpoint.json" % Path(args.assignments_file).stem)
    if os.path.isfile(checkpoint_path):
        os.remove(checkpoint_path)

    print("\nDone! Run build_artist_vocabulary.py to rebuild the vocabulary.")


if __name__ == "__main__":
    main()
