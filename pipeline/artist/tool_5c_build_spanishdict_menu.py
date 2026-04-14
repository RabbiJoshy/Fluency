#!/usr/bin/env python3
"""Build a parallel SpanishDict sense menu for an artist.

Writes only:
  - sense_menu_spanishdict.json

This script does extraction only. It does not classify examples or write
assignments. That is handled by tool_6b_assign_spanishdict_senses.py.
"""

import argparse
import concurrent.futures
import json
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import requests

from util_1a_artist_config import add_artist_arg, load_artist_config, artist_sense_menu_path
from util_5c_sense_menu_format import flatten_analyses_with_ids, normalize_artist_sense_menu

_POS_MAP = {
    "noun": "NOUN",
    "plural noun": "NOUN",
    "proper noun": "PROPN",
    "verb": "VERB",
    "adjective": "ADJ",
    "adverb": "ADV",
    "pronoun": "PRON",
    "determiner": "DET",
    "article": "DET",
    "definite article": "DET",
    "indefinite article": "DET",
    "interjection": "INTJ",
    "preposition": "ADP",
    "conjunction": "CCONJ",
    "coordinating conjunction": "CCONJ",
    "subordinating conjunction": "CCONJ",
    "number": "NUM",
    "numeral": "NUM",
    "particle": "PART",
    "contraction": "CONTRACTION",
    "phrase": "PHRASE",
}


def normalize_pos(part):
    part = (part or "").strip().lower()
    if part in _POS_MAP:
        return _POS_MAP[part]
    if "noun" in part:
        return "NOUN"
    if "verb" in part:
        return "VERB"
    if "adjective" in part:
        return "ADJ"
    if "adverb" in part:
        return "ADV"
    if "pronoun" in part:
        return "PRON"
    if "article" in part:
        return "DET"
    if "determiner" in part:
        return "DET"
    if "interjection" in part:
        return "INTJ"
    if "preposition" in part:
        return "ADP"
    if "conjunction" in part:
        return "CCONJ"
    if "proper noun" in part:
        return "PROPN"
    if "number" in part or "numeral" in part:
        return "NUM"
    if "particle" in part:
        return "PART"
    if "contraction" in part:
        return "CONTRACTION"
    return "X"


def extract_component_data(html):
    match = re.search(r"SD_COMPONENT_DATA\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        raise ValueError("Cannot find SD_COMPONENT_DATA in SpanishDict HTML")
    return json.loads(match.group(1))


def fetch_spanishdict_component(session, word):
    url = "https://www.spanishdict.com/translate/%s" % quote(word)
    response = session.get(url, timeout=20)
    response.raise_for_status()
    return extract_component_data(response.text)


def build_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Fluency SpanishDict menu research/1.0",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def extract_translation_rows(component):
    props = component.get("sdDictionaryResultsProps") or {}
    entry = props.get("entry") or {}
    neodict = entry.get("neodict") or []
    entry_lang = props.get("entryLang") or entry.get("entryLang") or "es"

    rows = []
    for nd in neodict:
        for pos_group in nd.get("posGroups") or []:
            for sense in pos_group.get("senses") or []:
                part = ((sense.get("partOfSpeech") or {}).get("nameEn")) or ""
                for translation in sense.get("translations") or []:
                    examples = []
                    for example in translation.get("examples") or []:
                        if entry_lang == "es":
                            examples.append({
                                "original": example.get("textEs", ""),
                                "translated": example.get("textEn", ""),
                            })
                        else:
                            examples.append({
                                "original": example.get("textEn", ""),
                                "translated": example.get("textEs", ""),
                            })
                    rows.append({
                        "word": (sense.get("subheadword") or "").strip() or "",
                        "translation": (translation.get("translation") or "").strip(),
                        "part": part,
                        "context": (sense.get("context") or "").strip(),
                        "regions": [
                            region.get("nameEn", "")
                            for region in (sense.get("regions") or []) + (translation.get("regions") or [])
                            if region.get("nameEn")
                        ],
                        "examples": examples,
                    })
    return rows, component.get("dictionaryPossibleResults") or []


def infer_analysis_order(surface, analyses, possible_results):
    order_hint = []
    seen = set()
    for item in possible_results:
        lemma = (item.get("wordSource") or item.get("result") or "").strip()
        if lemma and lemma not in seen:
            seen.add(lemma)
            order_hint.append(lemma)
    if surface not in seen:
        order_hint.insert(0, surface)

    rank = {lemma: i for i, lemma in enumerate(order_hint)}
    return sorted(
        analyses,
        key=lambda a: (
            rank.get(a.get("lemma", ""), 10 ** 6),
            a.get("lemma", "") != surface,
            -len(a.get("senses", [])),
            a.get("lemma", ""),
        ),
    )


def build_analyses(surface, rows, possible_results):
    grouped = defaultdict(list)
    seen = defaultdict(set)

    for row in rows:
        headword = row.get("word") or surface
        sense = {
            "pos": normalize_pos(row.get("part")),
            "translation": row.get("translation") or "",
            "source": "spanishdict",
            "headword": headword,
        }
        if row.get("context"):
            sense["context"] = row["context"]
        if row.get("examples"):
            sense["examples"] = deepcopy(row["examples"][:2])
        if row.get("regions"):
            sense["regions"] = list(dict.fromkeys(row["regions"]))

        key = (sense["pos"], sense["translation"])
        if key in seen[headword]:
            continue
        seen[headword].add(key)
        grouped[headword].append(sense)

    analyses = [
        {"headword": headword, "senses": senses}
        for headword, senses in grouped.items()
        if senses
    ]
    return infer_analysis_order(surface, analyses, possible_results)


def load_json(path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_menu(path, menu):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=2)


def load_excluded_words(artist_dir):
    routing_path = artist_dir / "data" / "known_vocab" / "word_routing.json"
    routing = load_json(routing_path, {})
    exclude = routing.get("exclude", {}) if isinstance(routing, dict) else {}
    skipped = set()
    for category in ("english", "proper_nouns", "interjections", "low_frequency"):
        values = exclude.get(category, [])
        if isinstance(values, list):
            skipped.update(v for v in values if isinstance(v, str))
    return skipped


def fetch_word_analyses(word):
    session = build_session()
    component = fetch_spanishdict_component(session, word)
    rows, possible_results = extract_translation_rows(component)
    analyses = build_analyses(word, rows, possible_results)
    if not analyses:
        raise ValueError("No SpanishDict senses extracted")
    _, _, normalized_analyses = flatten_analyses_with_ids(analyses)
    return word, normalized_analyses


def main():
    parser = argparse.ArgumentParser(
        description="Build parallel SpanishDict menu for an artist")
    add_artist_arg(parser)
    parser.add_argument("--force", action="store_true",
                        help="Rebuild words even if they already exist in the menu")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process a specific surface word (repeatable)")
    parser.add_argument("--max-words", type=int, default=None,
                        help="Only process the first N eligible words")
    parser.add_argument("--workers", type=int, default=8,
                        help="Concurrent SpanishDict requests (default: 8)")
    parser.add_argument("--include-excluded", action="store_true",
                        help="Include step-4 excluded words instead of skipping them")
    parser.add_argument("--save-every", type=int, default=100,
                        help="Write partial progress every N completed fetches (default: 100)")
    args = parser.parse_args()

    artist_dir = Path(args.artist_dir).resolve()
    config = load_artist_config(str(artist_dir))
    layers_dir = artist_dir / "data" / "layers"
    menu_path = Path(artist_sense_menu_path(str(layers_dir), "spanishdict"))

    inventory = load_json(layers_dir / "word_inventory.json", [])
    existing_menu = normalize_artist_sense_menu(load_json(menu_path, {}))
    excluded_words = set() if args.include_excluded else load_excluded_words(artist_dir)

    requested_words = set(args.word or [])
    words = []
    skipped_excluded = 0
    for entry in inventory:
        word = (entry.get("word") or "").strip()
        if not word:
            continue
        if requested_words and word not in requested_words:
            continue
        if word in excluded_words:
            skipped_excluded += 1
            continue
        if not args.force and word in existing_menu:
            continue
        words.append(word)

    if args.max_words is not None:
        words = words[:args.max_words]

    print("SpanishDict menu builder")
    print("Artist: %s" % config.get("name", artist_dir.name))
    print("Eligible words: %d" % len(words))
    if skipped_excluded:
        print("Skipped excluded words: %d" % skipped_excluded)
    print("Workers: %d" % max(1, args.workers))
    print("Save every: %d" % max(1, args.save_every))
    print("Output: %s" % menu_path)

    if not words:
        print("Nothing to do.")
        return

    built = 0
    failed = 0
    processed = 0
    worker_count = max(1, args.workers)
    save_every = max(1, args.save_every)
    future_to_index = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        for index, word in enumerate(words, start=1):
            future_to_index[executor.submit(fetch_word_analyses, word)] = (index, word)

        for future in concurrent.futures.as_completed(future_to_index):
            index, word = future_to_index[future]
            try:
                resolved_word, normalized_analyses = future.result()
                existing_menu[resolved_word] = normalized_analyses
                built += 1
            except Exception as exc:
                failed += 1
                print("  [%d/%d] %s failed: %s" % (index, len(words), word, exc))
            processed += 1
            if processed % save_every == 0:
                save_menu(menu_path, existing_menu)
                print("  Saved partial progress at %d/%d" % (processed, len(words)))

    save_menu(menu_path, existing_menu)

    print("\nDone.")
    print("Built/updated words: %d" % built)
    print("Failed words: %d" % failed)
    print("Total menu words: %d" % len(existing_menu))


if __name__ == "__main__":
    main()
