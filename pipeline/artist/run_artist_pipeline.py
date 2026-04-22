#!/usr/bin/env python3
"""
Pipeline orchestrator for artist vocabulary pipelines.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Bad Bunny"
    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Bad Bunny" --from-step 6
    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Rosalía" --dry-run

API key is read from .env (GEMINI_API_KEY=...) or --api-key flag.
"""

import argparse
import json
import os
import subprocess
import sys
import time


def _load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
ARTISTS_DIR = os.path.join(PROJECT_ROOT, "Artists")
PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")

_load_dotenv()


# ---------------------------------------------------------------------------
# Per-language defaults. Keeps step-list branching readable.
# ---------------------------------------------------------------------------
_LANG_DEFAULTS = {
    "spanish": {
        "spacy_model": "es_dep_news_trf",
        # Gemini is the go-to: Spanish builder uses min_priority: 50,
        # which only accepts priority-50 assignments (Gemini) + auto.
        # biencoder (priority 30) gets silently filtered out at build
        # time — running it as default made cards silently drop senses
        # when cache entries were wiped and biencoder filled the gap.
        # --classifier keyword stays available as the fast local option.
        "default_classifier": "gemini",
        "default_sense_source": "spanishdict",
        # Spanish uses pre-built SpanishDict cache; wiktionary menu is not
        # rebuilt per-artist. No step 5c in the list.
        "batch_glob_rel": os.path.join("data", "input", "batches", "batch_*.json"),
    },
    "french": {
        "spacy_model": "fr_dep_news_trf",
        "default_classifier": "keyword",
        "default_sense_source": "wiktionary",
        # French playlist-style: lyrics live in <artist>/lyrics/<lang>/*.json
        # (produced by research/2_download_lyrics.py + research/3_filter_language.py).
        "batch_glob_rel": os.path.join("lyrics", "french", "*.json"),
    },
}


def _base_args(artist_dir):
    return ["--artist-dir", artist_dir]

def _step_2_args(args, artist_dir):
    lang = args.language
    batch_glob = os.path.join(artist_dir, _LANG_DEFAULTS[lang]["batch_glob_rel"])
    return _base_args(artist_dir) + [
        "--batch_glob", batch_glob,
        "--out", os.path.join(artist_dir, "data", "word_counts", "vocab_evidence.json"),
        "--mwe-out", os.path.join(artist_dir, "data", "word_counts", "mwe_detected.json"),
    ]

def _step_2b_args(args, artist_dir):
    return _base_args(artist_dir) + ["--align"]

def _step_3_args(args, artist_dir):
    return _base_args(artist_dir) + ["--language", args.language]

def _step_4_args(args, artist_dir):
    return _base_args(artist_dir)

def _step_5_args(args, artist_dir):
    return _base_args(artist_dir)

def _step_5c_args(args, artist_dir):
    # Artist-mode wiktionary menu build (French first pass).
    return [
        "--language", args.language,
        "--sense-source", "wiktionary",
        "--artist-dir", artist_dir,
    ]

def _tag_pos_args(args, artist_dir):
    return _base_args(artist_dir) + ["--model", _spacy_model_for(args)]

def _step_6_args(args, artist_dir):
    a = _base_args(artist_dir) + ["--classifier", args.classifier]
    # Sense source: CLI override > language default.
    sense_source = getattr(args, "sense_source", None) or _LANG_DEFAULTS[args.language]["default_sense_source"]
    a.extend(["--sense-source", sense_source])
    if getattr(args, "gap_fill", None) is True:
        a.append("--gap-fill")
    elif getattr(args, "gap_fill", None) is False:
        a.append("--no-gap-fill")
    if getattr(args, "max_examples", None) is not None:
        a.extend(["--max-examples", str(args.max_examples)])
    if getattr(args, "force", False):
        a.append("--force")
    return a

def _step_7_args(args, artist_dir):
    return _base_args(artist_dir)

def _step_8_args(args, artist_dir):
    return _base_args(artist_dir)

def _build_args(args, artist_dir):
    # Step 8b needs the sense source explicitly; its own default is "spanishdict",
    # which is wrong for French runs.
    sense_source = getattr(args, "sense_source", None) or _LANG_DEFAULTS[args.language]["default_sense_source"]
    return _base_args(artist_dir) + ["--sense-source", sense_source]

def _step_2b_fr_args(args, artist_dir):
    return _base_args(artist_dir)


def _spacy_model_for(args):
    """Resolve spaCy model: --spacy-model override > artist.json spacy_model > language default."""
    override = getattr(args, "spacy_model", None)
    if override:
        return override
    from_config = getattr(args, "_artist_spacy_model", None)
    if from_config:
        return from_config
    return _LANG_DEFAULTS[args.language]["spacy_model"]


def _step_defs_spanish(vocab_file):
    """Full Spanish artist pipeline (unchanged from pre-refactor behaviour)."""
    return [
        {"num": 2, "label": "Tokenise, count words, detect MWEs",
         "script": "step_2a_count_words.py", "args_fn": _step_2_args,
         "input": None, "output": "data/word_counts/vocab_evidence.json", "needs_api_key": False},
        {"num": "2b", "label": "Scrape Genius translations",
         "script": "step_1b_scrape_translations.py", "args_fn": _step_2b_args,
         "input": None, "output": "data/input/translations/aligned_translations.json", "needs_api_key": False},
        {"num": 3, "label": "Merge elisions",
         "script": "step_3a_merge_elisions.py", "args_fn": _step_3_args,
         "input": "data/word_counts/vocab_evidence.json",
         "output": "data/elision_merge/vocab_evidence_merged.json", "needs_api_key": False},
        {"num": 4, "label": "Filter known vocabulary (reduce Gemini workload)",
         "script": "step_4a_filter_known_vocab.py", "args_fn": _step_4_args,
         "input": "data/elision_merge/vocab_evidence_merged.json",
         "output": "data/known_vocab/word_routing.json", "needs_api_key": False},
        {"num": 5, "label": "Split evidence into inventory + examples layers",
         "script": "step_5a_split_evidence.py", "args_fn": _step_5_args,
         "input": "data/elision_merge/vocab_evidence_merged.json",
         "output": "data/layers/word_inventory.json", "needs_api_key": False},
        {"num": "5b", "label": "Tag example POS (incremental, spaCy transformer)",
         "script": "../tool_6a_tag_example_pos.py", "args_fn": _tag_pos_args,
         "input": "data/layers/examples_raw.json",
         "output": "data/layers/example_pos.json", "needs_api_key": False},
        {"num": 6, "label": "Assign senses (bi-encoder + Gemini)",
         "script": "step_6a_assign_senses.py", "args_fn": _step_6_args,
         "input": "data/layers/word_inventory.json",
         "output": "data/layers/sense_assignments/wiktionary.json", "needs_api_key": False},
        {"num": "7a", "label": "Map senses to lemmas",
         "script": "step_7a_map_senses_to_lemmas.py", "args_fn": _step_7_args,
         "input": "data/layers/sense_assignments/wiktionary.json",
         "output": "data/layers/sense_assignments_lemma/wiktionary.json", "needs_api_key": False},
        {"num": "7b", "label": "Rerank -> layer",
         "script": "step_7b_rerank.py", "args_fn": _step_7_args,
         "input": "data/layers/word_inventory.json",
         "output": "data/layers/ranking.json", "needs_api_key": False},
        {"num": 8, "label": "Fetch LRC timestamps",
         "script": "step_8a_fetch_lrc_timestamps.py", "args_fn": _step_8_args,
         "input": "data/layers/examples_raw.json",
         "output": "data/layers/lyrics_timestamps.json", "needs_api_key": False},
        {"num": "build", "label": "Build vocabulary (assemble layers)",
         "script": "step_8b_assemble_artist_vocabulary.py", "args_fn": _build_args,
         "input": "data/layers/ranking.json",
         "output": vocab_file.rsplit(".", 1)[0] + ".index.json",
         "needs_api_key": False},
    ]


def _step_defs_french(vocab_file):
    """French first-pass pipeline (keyword-only, Wiktionary senses from kaikki-french).

    Dropped vs Spanish: 2b (no playlist-wide Genius alignment), 4 (no French
    word-routing), 7b (no French frequency list), 7c (no French cognate map).
    Added: 5c (build per-artist Wiktionary menu from kaikki-french).
    Step 3 still runs but with --language french (proclitic splitter).
    """
    return [
        {"num": 2, "label": "Tokenise, count words, detect MWEs",
         "script": "step_2a_count_words.py", "args_fn": _step_2_args,
         "input": None, "output": "data/word_counts/vocab_evidence.json", "needs_api_key": False},
        {"num": "2b", "label": "Align English translations to French lines",
         "script": "step_2b_align_translations_fr.py", "args_fn": _step_2b_fr_args,
         "input": None, "output": "data/layers/example_translations.json", "needs_api_key": False},
        {"num": 3, "label": "Merge elisions (French proclitic splitter)",
         "script": "step_3a_merge_elisions.py", "args_fn": _step_3_args,
         "input": "data/word_counts/vocab_evidence.json",
         "output": "data/elision_merge/vocab_evidence_merged.json", "needs_api_key": False},
        {"num": 5, "label": "Split evidence into inventory + examples layers",
         "script": "step_5a_split_evidence.py", "args_fn": _step_5_args,
         "input": "data/elision_merge/vocab_evidence_merged.json",
         "output": "data/layers/word_inventory.json", "needs_api_key": False},
        {"num": "5c", "label": "Build Wiktionary sense menu from kaikki-french",
         "script": "../step_5c_build_senses.py", "args_fn": _step_5c_args,
         "input": "data/layers/word_inventory.json",
         "output": "data/layers/sense_menu/wiktionary.json", "needs_api_key": False},
        {"num": "5b", "label": "Tag example POS (French spaCy)",
         "script": "../tool_6a_tag_example_pos.py", "args_fn": _tag_pos_args,
         "input": "data/layers/examples_raw.json",
         "output": "data/layers/example_pos.json", "needs_api_key": False},
        {"num": 6, "label": "Assign senses (keyword only)",
         "script": "step_6a_assign_senses.py", "args_fn": _step_6_args,
         "input": "data/layers/word_inventory.json",
         "output": "data/layers/sense_assignments/wiktionary.json", "needs_api_key": False},
        {"num": "7a", "label": "Map senses to lemmas",
         "script": "step_7a_map_senses_to_lemmas.py", "args_fn": _step_7_args,
         "input": "data/layers/sense_assignments/wiktionary.json",
         "output": "data/layers/sense_assignments_lemma/wiktionary.json", "needs_api_key": False},
        {"num": 8, "label": "Fetch LRC timestamps",
         "script": "step_8a_fetch_lrc_timestamps.py", "args_fn": _step_8_args,
         "input": "data/layers/examples_raw.json",
         "output": "data/layers/lyrics_timestamps.json", "needs_api_key": False},
        {"num": "build", "label": "Build vocabulary (assemble layers)",
         "script": "step_8b_assemble_artist_vocabulary.py", "args_fn": _build_args,
         "input": "data/layers/ranking.json",
         "output": vocab_file.rsplit(".", 1)[0] + ".index.json",
         "needs_api_key": False},
    ]


def build_steps(vocab_file, language="spanish"):
    if language == "french":
        return _step_defs_french(vocab_file)
    return _step_defs_spanish(vocab_file)


def parse_step(value, steps):
    for i, s in enumerate(steps):
        if str(s["num"]) == value:
            return i
    valid = ", ".join(str(s["num"]) for s in steps)
    print("ERROR: Unknown step '%s'. Valid steps: %s" % (value, valid))
    sys.exit(1)


def file_mtime(artist_dir, path):
    full = os.path.join(artist_dir, path) if not os.path.isabs(path) else path
    return os.path.getmtime(full) if os.path.exists(full) else 0


def run_step(step, args, artist_dir, dry_run=False):
    script_path = os.path.join(SCRIPTS_DIR, step["script"])
    extra_args = step["args_fn"](args, artist_dir)
    cmd = [PYTHON, script_path] + extra_args

    print("\n" + "=" * 60)
    print("Step %s: %s" % (step["num"], step["label"]))
    print("  Script: %s" % step["script"])

    if dry_run:
        print("  [DRY RUN] Would run: %s" % " ".join(cmd))
        return True

    print("  Running...")
    start = time.time()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    elapsed = time.time() - start

    if result.returncode == 0:
        print("  Done (%.1f seconds)" % elapsed)
        return True
    print("  FAILED with exit code %d (%.1f seconds)" % (result.returncode, elapsed))
    return False


def _discover_artists():
    """Walk Artists/<lang>/<name>/artist.json and return {name: full_path}.

    Artists live under a language subdirectory (Artists/spanish, Artists/french)
    since the 2026-04-18 restructure. Names are unique across languages; if a
    collision ever appears, the last one found wins (and we warn).
    """
    found = {}
    if not os.path.isdir(ARTISTS_DIR):
        return found
    for lang in sorted(os.listdir(ARTISTS_DIR)):
        lang_dir = os.path.join(ARTISTS_DIR, lang)
        if not os.path.isdir(lang_dir):
            continue
        for name in sorted(os.listdir(lang_dir)):
            artist_dir = os.path.join(lang_dir, name)
            if os.path.isfile(os.path.join(artist_dir, "artist.json")):
                if name in found:
                    print("WARNING: artist name '%s' exists under multiple languages; using %s"
                          % (name, artist_dir))
                found[name] = artist_dir
    return found


def main():
    available = _discover_artists()
    available_display = ", ".join(sorted(available.keys()))

    parser = argparse.ArgumentParser(
        description="Artist vocabulary pipeline orchestrator",
        epilog=("Available artists: %s" % available_display) if available_display else "")
    parser.add_argument("--artist", type=str, required=True,
                        help="Artist name (e.g. 'Bad Bunny') — resolved against Artists/<lang>/<name>/. "
                             "Accepts a full path (containing '/') as an override.")
    parser.add_argument("--api-key", type=str, default=os.environ.get("GEMINI_API_KEY", ""))
    parser.add_argument("--from-step", type=str, default=None)
    parser.add_argument("--to-step", type=str, default=None)
    parser.add_argument("--skip", type=str, nargs="*", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--classifier", choices=["keyword", "biencoder", "gemini"],
                        default=None,
                        help="Primary classifier for step 6. Defaults per language "
                             "(spanish=biencoder, french=keyword).")
    parser.add_argument("--spacy-model", default=None,
                        help="Override the spaCy model used for POS tagging + lemma mapping. "
                             "Defaults per language (spanish=es_dep_news_trf, french=fr_dep_news_trf), "
                             "and can be overridden by 'spacy_model' in artist.json.")
    parser.add_argument("--sense-source", choices=["wiktionary", "spanishdict"], default=None,
                        help="Override sense source for step 6. "
                             "Defaults per language (spanish=spanishdict, french=wiktionary).")
    gf = parser.add_mutually_exclusive_group()
    gf.add_argument("--gap-fill", dest="gap_fill", action="store_true", default=None,
                    help="Run Gemini gap-fill (default: on for gemini, off otherwise).")
    gf.add_argument("--no-gap-fill", dest="gap_fill", action="store_false",
                    help="Skip gap-fill.")
    parser.add_argument("--max-examples", type=int, default=None,
                        help="Per-word example cap sent to Gemini.")
    parser.add_argument("--words-only", action="store_true",
                        help="Step 6: run word analysis but skip sentence translation.")
    args = parser.parse_args()

    # Resolve artist name → directory. A value containing a path separator is
    # treated as an explicit path (lets callers pass Artists/french/XYZ or an
    # absolute path for one-off runs).
    if "/" in args.artist or os.path.isabs(args.artist):
        artist_dir = args.artist
    elif args.artist in available:
        artist_dir = available[args.artist]
    else:
        artist_dir = os.path.join(ARTISTS_DIR, args.artist)  # legacy fallback

    if not os.path.isdir(artist_dir):
        print("ERROR: Artist directory not found: %s" % artist_dir)
        if available_display:
            print("       Available: %s" % available_display)
        sys.exit(1)

    with open(os.path.join(artist_dir, "artist.json")) as f:
        config = json.load(f)

    # Language comes from artist.json (default: spanish for backward compat).
    language = config.get("language", "spanish")
    if language not in _LANG_DEFAULTS:
        print("ERROR: Unknown language '%s' in %s/artist.json. Supported: %s"
              % (language, artist_dir, ", ".join(_LANG_DEFAULTS)))
        sys.exit(1)
    args.language = language

    # Defaults per language, applied only if the caller didn't override.
    if args.classifier is None:
        args.classifier = _LANG_DEFAULTS[language]["default_classifier"]
    # spaCy model: CLI > artist.json > language default. Resolved by _spacy_model_for().
    args._artist_spacy_model = config.get("spacy_model")

    STEPS = build_steps(config["vocabulary_file"], language=language)

    start_idx = parse_step(args.from_step, STEPS) if args.from_step else 0
    end_idx = parse_step(args.to_step, STEPS) if args.to_step else len(STEPS) - 1
    skip_set = set(args.skip)
    steps_to_run = [s for s in STEPS[start_idx:end_idx + 1] if str(s["num"]) not in skip_set]

    # Gemini key is needed when the primary classifier is gemini, or when
    # gap-fill is enabled (explicitly or by default for gemini classifier).
    gap_fill_default_on = (args.classifier == "gemini")
    gap_fill_effective = args.gap_fill if args.gap_fill is not None else gap_fill_default_on
    gemini_needed = (args.classifier == "gemini" or gap_fill_effective)
    needs_key = any(s["needs_api_key"] for s in steps_to_run) and gemini_needed
    if needs_key and not args.api_key and not args.dry_run:
        print("ERROR: Steps %s require --api-key (or use --no-gemini)" %
              ", ".join(str(s["num"]) for s in steps_to_run if s["needs_api_key"]))
        sys.exit(1)

    print("%s Pipeline" % config["name"])
    print("=" * 60)
    print("Artist dir: %s" % artist_dir)
    print("Language:   %s" % language)
    print("Classifier: %s" % args.classifier)
    print("spaCy:      %s" % _spacy_model_for(args))
    print("Steps: %s" % " -> ".join(str(s["num"]) for s in steps_to_run))
    if args.dry_run:
        print("Mode: DRY RUN")

    # Freshness check
    print("\n--- File freshness ---")
    for step in STEPS:
        marker = ">>>" if step in steps_to_run else "   "
        out_path = os.path.join(artist_dir, step["output"]) if step["output"] else None
        if out_path and os.path.exists(out_path):
            age_h = (time.time() - os.path.getmtime(out_path)) / 3600
            age_str = "%.0f min ago" % (age_h * 60) if age_h < 1 else "%.1fh ago" % age_h if age_h < 24 else "%.0fd ago" % (age_h / 24)
            print("%s Step %s: %-35s  %s" % (marker, step["num"], step["output"], age_str))
        else:
            print("%s Step %s: %-35s  (missing)" % (marker, step["num"], step["output"] or "(none)"))

    total_start = time.time()
    for step in steps_to_run:
        if not run_step(step, args, artist_dir, dry_run=args.dry_run):
            print("\nAborting — step %s failed." % step["num"])
            sys.exit(1)

    print("\n" + "=" * 60)
    if args.dry_run:
        print("Dry run complete.")
    else:
        print("Pipeline complete! (%.1f minutes)" % ((time.time() - total_start) / 60))


if __name__ == "__main__":
    main()
