#!/usr/bin/env python3
"""tool_5c_invalidate_backwards_entries.py

Targeted cleanup for SpanishDict surface-cache entries that were fetched
WITHOUT the ``?langFrom=es`` hint and came back reversed (English-source
instead of Spanish-source). Classic symptom: the card for ``has`` shows
headword ``have`` and translations like ``tener``.

Running this tool:

1. Scans the existing surface_cache.
2. Flags entries whose translations look Spanish (= we got the English
   headword for a word that ought to have been Spanish-source).
3. Either prints them (dry run) or:
   a. Removes flagged entries from the shared surface cache so the
      next ``tool_5c_build_spanishdict_cache.py`` run refetches them
      through the fixed URL, and
   b. Wipes matching keys from every ``sense_assignments`` file it
      finds — both normal-mode
      (``Data/Spanish/layers/sense_assignments/...``) and per-artist
      (``Artists/*/*/data/layers/sense_assignments/...``). Otherwise
      step_6c's coverage check would skip those examples on the next
      Gemini run and leave stale assignments referencing sense IDs
      that no longer exist in the rebuilt menu.

The surface cache is shared across normal + artist modes, so the
fix propagates to every mode as soon as the cache is refetched.

Why not bump STEP_VERSION on the cache builder? Because STEP_VERSION=3
would invalidate all ~13k cache entries and trigger ~3h of scraping,
almost all of which would just refetch to identical data. The vast
majority of legacy entries are fine; only the ~100-400 "accidentally
English" ones need refetching.

Detection heuristics (any of):
  A. Translation contains Spanish-only chars (á, é, í, ó, ú, ñ, ü).
     High confidence — those characters don't appear in English words.
  B. A translation token matches a known Spanish infinitive from
     ``conjugations.json`` AND the entry's headword is NOT one of the
     query word's known morphological lemmas in ``word_inventory``.
     Catches ``has → have/tener`` (tener is an infinitive, ``have`` is
     not haber) while leaving ``sonaría → sonar/sonar`` alone (sonar
     IS sonaría's known lemma, so the entry is forward even though
     ``sonar`` is also a Spanish infinitive).
  C. entry_lang is explicitly "en" (ironclad signal for entries that
     have the field at all).

Usage (from repo root):

    # Dry run — prints what would be invalidated, touches nothing.
    .venv/bin/python3 pipeline/tool_5c_invalidate_backwards_entries.py

    # Actually delete the flagged cache entries (takes a backup first).
    .venv/bin/python3 pipeline/tool_5c_invalidate_backwards_entries.py --execute

    # Manually skip specific words (for false-positive cases).
    .venv/bin/python3 pipeline/tool_5c_invalidate_backwards_entries.py --execute --skip sonar meter

Then refetch them through the fixed URL:

    .venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py \
        --inventory-file Data/Spanish/layers/word_inventory.json

Only the deleted entries get re-fetched — STEP_VERSION didn't change,
so the ~13k good entries stay put.
"""

import argparse
import glob
import json
import re
import shutil
import sys
from pathlib import Path
from util_5c_spanishdict import SPANISHDICT_SURFACE_CACHE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONJUGATIONS_PATH = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugations.json"
INVENTORY_PATH = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
# Sense-assignment files to wipe for invalidated words so step_6c
# re-classifies their examples against the new (correct) sense menu.
# Lemma-keyed file is also cleared because stale word-keyed entries
# would otherwise propagate there on the next step_7a run.
#
# Covers BOTH modes:
#   * Normal mode:   Data/Spanish/layers/sense_assignments/...
#   * Artist mode:   Artists/{lang}/{Name}/data/layers/sense_assignments/...
# The surface_cache is shared, so a backwards entry there poisons
# every artist pipeline that looks up the word. Wiping both families
# keeps the rebuild path clean for both.
_NORMAL_ASSIGNMENT_FILES = [
    PROJECT_ROOT / "Data" / "Spanish" / "layers" / "sense_assignments" / "spanishdict.json",
    PROJECT_ROOT / "Data" / "Spanish" / "layers" / "sense_assignments_lemma" / "spanishdict.json",
]
_ARTISTS_DIR = PROJECT_ROOT / "Artists"


def _artist_assignment_files():
    """Find every per-artist sense_assignments spanishdict.json in the repo."""
    if not _ARTISTS_DIR.exists():
        return []
    patterns = [
        "*/*/data/layers/sense_assignments/spanishdict.json",
        "*/*/data/layers/sense_assignments_lemma/spanishdict.json",
    ]
    out = []
    for pat in patterns:
        out.extend(Path(p) for p in glob.glob(str(_ARTISTS_DIR / pat)))
    return sorted(out)


def _collect_assignment_files():
    return list(_NORMAL_ASSIGNMENT_FILES) + _artist_assignment_files()

SPANISH_CHARS_RE = re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ]")
# Tokens are letters only; strip punctuation + spaces.
TOKEN_RE = re.compile(r"[a-zA-Z]+(?:[áéíóúñüÁÉÍÓÚÑÜa-zA-Z]*)", re.UNICODE)


def load_known_spanish_infinitives():
    """Return the set of Spanish infinitives (plus -se reflexive variants)
    from ``conjugations.json`` keys.

    The reflexive suffix is added programmatically because
    ``conjugations.json`` only stores non-reflexive bases. Without the
    -se variants, translations like ``imaginarse`` / ``figurarse`` /
    ``creerse`` / ``venirse`` read as English and an obviously-backwards
    entry like ``imagine → imaginarse`` escapes the filter.
    """
    if not CONJUGATIONS_PATH.exists():
        return set()
    with open(CONJUGATIONS_PATH, encoding="utf-8") as f:
        bases = {k.lower() for k in json.load(f).keys()}
    out = set(bases)
    for b in bases:
        out.add(b + "se")
    return out


def load_spanish_word_set(word_lemmas):
    """Return a set of Spanish word-forms known to appear in the corpus.

    Built from the inventory: every entry's surface word and its
    ``known_lemmas`` contribute. Used to catch Spanish adjectives /
    nouns / adverbs that don't carry diacritics and aren't infinitives
    (``tarde``, ``atrasado``, ``retrasado``, ``difunto`` in translations
    of ``late``, for example). An inventory-membership signal isn't
    conclusive on its own — many forms coincide with English words —
    but counted alongside Spanish-char and infinitive signals it
    correctly flags entries whose translations are mostly Spanish
    content words.
    """
    out = set()
    for word, lemmas in word_lemmas.items():
        if word:
            out.add(word)
        for lm in lemmas:
            if lm:
                out.add(lm)
    return out


def load_word_lemma_map():
    """Return ``{word: [known_lemmas]}`` from ``word_inventory.json``.

    Used to decide whether a cache entry's headword is one of the
    morphologically-valid lemmas for the query word — if it is, the
    entry is forward (even if the translations happen to share form
    with a Spanish infinitive).
    """
    if not INVENTORY_PATH.exists():
        return {}
    with open(INVENTORY_PATH, encoding="utf-8") as f:
        inventory = json.load(f)
    out = {}
    for entry in inventory or []:
        if not isinstance(entry, dict):
            continue
        word = (entry.get("word") or "").strip().lower()
        lemmas = entry.get("known_lemmas") or []
        if word:
            out[word] = [lm.lower() for lm in lemmas if isinstance(lm, str)]
    return out


def _tokens(text):
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text or "")]


def flag_entry(word, entry, infinitives, word_lemmas, spanish_words=None):
    """Return ``(is_backwards, reason)``.

    ``word`` is the cache key (lowercase). ``entry`` is the surface
    cache row. ``infinitives`` + ``word_lemmas`` are loaded once.

    Heuristic: flag if the MAJORITY of the entry's senses have
    translations that look Spanish. Using a per-sense count instead of
    "any sense" eliminates the false positive where a forward entry
    has one loanword translation with Spanish accents (café has a
    translation "café" among "coffee/coffee shop/brown"; novia has
    "fiancée" among "bride/girlfriend/fiancée"). Those entries are
    actually correct — Spanish → English — but contain one loanword
    output that triggered the naive "any Spanish char" rule.

    "Looks Spanish" per sense:
      * translation contains Spanish-only chars (á é í ó ú ñ ü), OR
      * translation contains a Spanish infinitive token (from
        conjugations.json) and the entry's headword is NOT one of the
        query word's morphological lemmas — blocks the sonaría→sonar
        false positive (headword "sonar" IS sonaría's known lemma).
    """
    if not isinstance(entry, dict):
        return False, ""

    lang = (entry.get("entry_lang") or "").strip()
    if lang == "es":
        return False, ""
    if lang and lang != "es":
        return True, f"entry_lang={lang!r}"

    analyses = entry.get("dictionary_analyses") or []
    if not analyses:
        return False, ""

    known_lemmas = set(word_lemmas.get(word, []))

    total_senses = 0
    spanish_senses = 0
    first_reason = ""

    for a in analyses:
        headword = (a.get("headword") or "").strip().lower()
        # Exclude the headword itself from translation-token matching.
        # That's the narrow fix for sonaría → sonar → sonar (headword
        # "sonar" happens to be both a Spanish infinitive AND the query's
        # known lemma, so counting the identity-translation as Spanish
        # would wrongly flag a forward entry). Using a blanket
        # ``headword_is_known_lemma`` gate was too aggressive — it also
        # skipped genuine backwards entries like ``okay`` (known_lemmas
        # = [okay], headword = okay) whose translations "bien / bueno /
        # vale" don't match the headword but ARE Spanish.
        exclude_tokens = {word}
        if headword:
            exclude_tokens.add(headword)
        senses = a.get("senses") or []
        for s in senses:
            tr = s.get("translation") or ""
            if not tr:
                continue
            total_senses += 1
            is_spanish = False
            reason = ""
            if SPANISH_CHARS_RE.search(tr):
                is_spanish = True
                reason = f"{tr!r} contains Spanish char"
            else:
                for tok in _tokens(tr):
                    if tok in exclude_tokens:
                        continue
                    if tok in infinitives:
                        is_spanish = True
                        reason = f"{tr!r} contains Spanish infinitive {tok!r}"
                        break
                    if spanish_words and len(tok) >= 4 and tok in spanish_words:
                        # Inventory-membership as a weaker fallback for
                        # content words that don't carry diacritics and
                        # aren't infinitives (tarde, atrasado, difunto).
                        # 4-char gate avoids short English-Spanish
                        # homographs (de, la, el, un, en).
                        is_spanish = True
                        reason = f"{tr!r} contains Spanish word {tok!r}"
                        break
            if is_spanish:
                spanish_senses += 1
                if not first_reason:
                    first_reason = reason

    if total_senses == 0:
        return False, ""
    # Majority of senses look Spanish → the entry is a backwards
    # translation (English headword, Spanish glosses). One stray
    # loanword in an otherwise-English entry doesn't trip this.
    if spanish_senses * 2 > total_senses:
        return True, f"{spanish_senses}/{total_senses} senses look Spanish ({first_reason})"
    return False, ""


def main():
    parser = argparse.ArgumentParser(
        description="Invalidate backwards SpanishDict surface-cache entries"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete flagged entries from the cache. "
                             "Without this flag the tool is a dry run — nothing "
                             "is modified on disk.")
    parser.add_argument("--skip", nargs="*", default=[],
                        help="Cache keys to leave alone even if flagged "
                             "(for false-positive handling).")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip writing surface_cache.json.bak before editing.")
    parser.add_argument("--limit-print", type=int, default=40,
                        help="How many flagged entries to print as a sample (default: 40).")
    args = parser.parse_args()

    skip = {s.lower() for s in (args.skip or [])}

    if not SPANISHDICT_SURFACE_CACHE.exists():
        print(f"ERROR: surface cache not found at {SPANISHDICT_SURFACE_CACHE}")
        sys.exit(1)

    with open(SPANISHDICT_SURFACE_CACHE, encoding="utf-8") as f:
        cache = json.load(f)
    print(f"Loaded surface cache: {len(cache)} entries")

    infinitives = load_known_spanish_infinitives()
    print(f"Loaded {len(infinitives)} Spanish infinitives (incl. -se reflexive)")
    word_lemmas = load_word_lemma_map()
    print(f"Loaded {len(word_lemmas)} word→lemmas mappings from word_inventory.json")
    spanish_words = load_spanish_word_set(word_lemmas)
    print(f"Spanish word set (inventory words + lemmas): {len(spanish_words)} forms")

    flagged = []
    for word, entry in cache.items():
        if word in skip:
            continue
        is_back, reason = flag_entry(word, entry, infinitives, word_lemmas, spanish_words)
        if is_back:
            flagged.append((word, entry, reason))

    print(f"\nFlagged as backwards: {len(flagged)}")
    if skip:
        print(f"Manually skipped: {len(skip)} ({sorted(skip)[:20]}{'...' if len(skip) > 20 else ''})")

    if not flagged:
        print("Nothing to do.")
        return

    print(f"\nSample (first {args.limit_print}):")
    for word, entry, reason in flagged[: args.limit_print]:
        hw = ""
        analyses = entry.get("dictionary_analyses") or []
        if analyses:
            hw = analyses[0].get("headword", "")
        print(f"  {word!r:22}  headword={hw!r:22}  {reason}")

    if not args.execute:
        print("\nDry run — no changes made.")
        print("Re-run with --execute to delete these entries.")
        return

    # Back up before editing.
    if not args.no_backup:
        backup_path = SPANISHDICT_SURFACE_CACHE.with_suffix(
            SPANISHDICT_SURFACE_CACHE.suffix + ".bak"
        )
        shutil.copy2(SPANISHDICT_SURFACE_CACHE, backup_path)
        print(f"\nBacked up surface cache → {backup_path}")

    for word, _, _ in flagged:
        cache.pop(word, None)

    with open(SPANISHDICT_SURFACE_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"Deleted {len(flagged)} surface-cache entries. Cache now has {len(cache)} entries.")

    # Also wipe sense_assignments entries so step_6c will re-classify
    # these words' examples against the new (Spanish-source) sense menu.
    # Otherwise step_6c's `covered_abs` check thinks the examples are
    # already classified and skips them, leaving assignments that
    # reference sense IDs that no longer exist in the new menu.
    # Covers both normal-mode and per-artist files.
    flagged_words = {w for w, _, _ in flagged}
    assignment_files = _collect_assignment_files()
    total_keys_wiped = 0
    files_touched = 0
    for path in assignment_files:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            assignments = json.load(f)
        before = len(assignments)
        # Assignments are keyed by ``word`` in the word-keyed file and
        # ``word|lemma`` in the lemma-keyed file. Match on the word
        # prefix (before any ``|``).
        removed_keys = [k for k in assignments if k.split("|", 1)[0] in flagged_words]
        for k in removed_keys:
            assignments.pop(k, None)
        if removed_keys:
            if not args.no_backup:
                bak = path.with_suffix(path.suffix + ".bak")
                shutil.copy2(path, bak)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(assignments, f, ensure_ascii=False, indent=2)
            # Show a short relative path so the log reads cleanly
            # across normal + many-artist cases.
            try:
                rel = path.relative_to(PROJECT_ROOT)
            except ValueError:
                rel = path
            print(f"  Wiped {len(removed_keys)} keys from {rel} "
                  f"({before} → {len(assignments)})")
            total_keys_wiped += len(removed_keys)
            files_touched += 1
    if files_touched:
        print(f"  Total: {total_keys_wiped} assignment keys wiped across "
              f"{files_touched} file(s).")

    print("\nNext: run tool_5c_build_spanishdict_cache to refetch through the "
          "corrected URL (only the deleted entries will be fetched):")
    print("    .venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py \\")
    print("        --inventory-file Data/Spanish/layers/word_inventory.json")
    print("\nThen rebuild normal-mode sense menu + Gemini + assembly:")
    print("    .venv/bin/python3 pipeline/step_5c_build_senses.py --sense-source spanishdict")
    print("    .venv/bin/python3 pipeline/step_6a_assign_senses.py --classifier gemini")
    print("    .venv/bin/python3 pipeline/step_7a_map_senses_to_lemmas.py --sense-source spanishdict")
    print("    .venv/bin/python3 pipeline/step_8a_assemble_vocabulary.py")
    print("\nAnd for each artist (re-runs Gemini on wiped words, then rebuilds):")
    print('    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Bad Bunny"  --from-step 6')
    print('    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Rosalía"    --from-step 6')
    print('    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Young Miko" --from-step 6')


if __name__ == "__main__":
    main()
