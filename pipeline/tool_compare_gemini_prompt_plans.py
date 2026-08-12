#!/usr/bin/env python3
"""Compare two dry-run Gemini prompt plans without calling Gemini.

The comparison is semantic: reordering an unchanged sense menu is reported
separately from changes that would alter the information given to the model.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sense_map(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(sense_id): sense
        for sense_id, sense in zip(record.get("ids", []), record.get("senses", []))
    }


def examples_by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(example["id"]): example for example in record.get("examples", [])}


def route_labels(routing: dict[str, Any]) -> dict[str, list[str]]:
    labels: dict[str, list[str]] = {}

    def add(section: str, value: Any) -> None:
        if isinstance(value, list):
            for word in value:
                labels.setdefault(str(word), []).append(section)
        elif isinstance(value, dict):
            for name, child in value.items():
                add(f"{section}.{name}" if section else name, child)

    for key in ("exclude", "classifier", "sense_discovery", "clitic_merge"):
        if key in routing:
            add(key, routing[key])
    return labels


def menu_sense_count(menu: dict[str, Any], word: str) -> int | None:
    entries = menu.get(word)
    if not isinstance(entries, list):
        return None
    ids: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("senses"), dict):
            ids.update(str(sense_id) for sense_id in entry["senses"])
    return len(ids)


def transition_detail(
    word: str,
    routes: dict[str, list[str]],
    menu: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "routes": routes.get(word, []),
        "sense_count": menu_sense_count(menu, word),
        "in_inventory": word in inventory,
    }


def inventory_words(payload: Any) -> set[str]:
    if isinstance(payload, list):
        return {
            str(item.get("word"))
            for item in payload
            if isinstance(item, dict) and item.get("word")
        }
    if isinstance(payload, dict):
        return {str(word) for word in payload if not str(word).startswith("_")}
    return set()


def pos_by_example_id(examples: dict[str, Any], pos: dict[str, Any]) -> dict[tuple[str, str], Any]:
    result = {}
    for word, items in examples.items():
        if not isinstance(items, list):
            continue
        word_pos = pos.get(word, {}) if isinstance(pos.get(word), dict) else {}
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") is not None:
                result[(word, str(item["id"]))] = word_pos.get(str(index))
    return result


def example_differences(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = examples_by_id(before)
    new = examples_by_id(after)
    common = sorted(old.keys() & new.keys())
    fields = ("spanish", "english", "song", "pos")
    changed_fields = {
        field: [example_id for example_id in common if old[example_id].get(field) != new[example_id].get(field)]
        for field in fields
    }
    samples = []
    for example_id in common:
        changed = [field for field in fields if old[example_id].get(field) != new[example_id].get(field)]
        if changed:
            samples.append(
                {
                    "id": example_id,
                    "changed_fields": changed,
                    "before": {field: old[example_id].get(field) for field in changed},
                    "after": {field: new[example_id].get(field) for field in changed},
                }
            )
    return {
        "added_ids": sorted(new.keys() - old.keys()),
        "removed_ids": sorted(old.keys() - new.keys()),
        "changed_fields": changed_fields,
        "samples": samples[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-plan", type=Path, required=True)
    parser.add_argument("--after-plan", type=Path, required=True)
    parser.add_argument("--before-data", type=Path, required=True)
    parser.add_argument("--after-data", type=Path, required=True)
    parser.add_argument("--noise-claims", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before_plan = load_json(args.before_plan)
    after_plan = load_json(args.after_plan)
    before_records = {record["word"]: record for record in before_plan["records"]}
    after_records = {record["word"]: record for record in after_plan["records"]}

    before_routing = load_json(args.before_data / "known_vocab/word_routing.json")
    after_routing = load_json(args.after_data / "known_vocab/word_routing.json")
    before_routes = route_labels(before_routing)
    after_routes = route_labels(after_routing)
    before_menu = load_json(args.before_data / "layers/sense_menu/spanishdict.json")
    after_menu = load_json(args.after_data / "layers/sense_menu/spanishdict.json")
    before_inventory = inventory_words(load_json(args.before_data / "layers/word_inventory.json"))
    after_inventory = inventory_words(load_json(args.after_data / "layers/word_inventory.json"))

    noise_by_occurrence: dict[str, list[str]] = {}
    if args.noise_claims:
        with args.noise_claims.open(encoding="utf-8") as handle:
            for line in handle:
                claim = json.loads(line)
                occurrence_id = str(claim.get("subject", {}).get("id", ""))
                labels = claim.get("value", {}).get("labels", [])
                if occurrence_id and labels:
                    noise_by_occurrence[occurrence_id] = [str(label) for label in labels]

    exact_words: list[str] = []
    menu_reorder_only: list[str] = []
    true_menu_changes: list[str] = []
    changed_records: list[dict[str, Any]] = []
    field_word_counts: Counter[str] = Counter()

    for word in sorted(before_records.keys() & after_records.keys()):
        old = before_records[word]
        new = after_records[word]
        if old.get("prompt_sha256") == new.get("prompt_sha256"):
            exact_words.append(word)
            continue

        old_senses = sense_map(old)
        new_senses = sense_map(new)
        menu_content_changed = old_senses != new_senses
        menu_order_changed = old.get("ids", []) != new.get("ids", [])
        ex_diff = example_differences(old, new)
        examples_changed = bool(
            ex_diff["added_ids"]
            or ex_diff["removed_ids"]
            or any(ex_diff["changed_fields"].values())
        )
        scalar_fields = [
            field
            for field in ("word", "lemma", "abs", "allow_propose")
            if old.get(field) != new.get(field)
        ]

        if menu_content_changed:
            true_menu_changes.append(word)
            field_word_counts["sense_menu_content"] += 1
        elif menu_order_changed:
            field_word_counts["sense_menu_order"] += 1
        if examples_changed:
            field_word_counts["examples"] += 1
        for field, ids in ex_diff["changed_fields"].items():
            if ids:
                field_word_counts[f"example_{field}"] += 1
        if ex_diff["added_ids"] or ex_diff["removed_ids"]:
            field_word_counts["example_selection"] += 1
        for field in scalar_fields:
            field_word_counts[field] += 1

        if menu_order_changed and not menu_content_changed and not examples_changed and not scalar_fields:
            menu_reorder_only.append(word)
        else:
            changed_records.append(
                {
                    "word": word,
                    "menu_content_changed": menu_content_changed,
                    "menu_order_changed": menu_order_changed,
                    "sense_ids_before": old.get("ids", []),
                    "sense_ids_after": new.get("ids", []),
                    "scalar_fields_changed": scalar_fields,
                    "examples": ex_diff,
                }
            )

    removed_words = sorted(before_records.keys() - after_records.keys())
    added_words = sorted(after_records.keys() - before_records.keys())

    transitions = {
        "removed_from_prompt_queue": [
            {
                "word": word,
                "before": transition_detail(word, before_routes, before_menu, before_inventory),
                "after": transition_detail(word, after_routes, after_menu, after_inventory),
            }
            for word in removed_words
        ],
        "added_to_prompt_queue": [
            {
                "word": word,
                "before": transition_detail(word, before_routes, before_menu, before_inventory),
                "after": transition_detail(word, after_routes, after_menu, after_inventory),
            }
            for word in added_words
        ],
    }

    old_examples = load_json(args.before_data / "layers/examples_raw.json")
    new_examples = load_json(args.after_data / "layers/examples_raw.json")
    old_pos = load_json(args.before_data / "layers/example_pos.json")
    new_pos = load_json(args.after_data / "layers/example_pos.json")
    old_pos_by_id = pos_by_example_id(old_examples, old_pos)
    new_pos_by_id = pos_by_example_id(new_examples, new_pos)
    stable_pos_changes = [
        {
            "word": word,
            "example_id": example_id,
            "before": old_pos_by_id[(word, example_id)],
            "after": new_pos_by_id[(word, example_id)],
        }
        for word, example_id in sorted(old_pos_by_id.keys() & new_pos_by_id.keys())
        if old_pos_by_id[(word, example_id)] != new_pos_by_id[(word, example_id)]
    ]

    legacy_examples = {}
    migration_path = args.after_data / "evidence/migrations/legacy_example_ids.json"
    if migration_path.is_file():
        legacy_examples = load_json(migration_path).get("examples", {})
    occurrence_surface: dict[str, str] = {}
    normalized_forms: dict[str, list[str]] = {}
    profile_path = args.after_data / "evidence/profiles/current.json"
    if profile_path.is_file():
        profile = load_json(profile_path)
        ledger_run = profile.get("runs", {}).get("ledger")
        normalization_run = profile.get("runs", {}).get("normalization")
        if ledger_run:
            occurrence_path = args.after_data / f"evidence/ledger/runs/{ledger_run}/occurrences.jsonl"
            if occurrence_path.is_file():
                with occurrence_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        occurrence = json.loads(line)
                        occurrence_surface[str(occurrence["occurrence_id"])] = str(
                            occurrence.get("surface", "")
                        ).lower()
        if normalization_run:
            normalization_path = args.after_data / f"evidence/overlays/normalization/{normalization_run}.jsonl"
            if normalization_path.is_file():
                with normalization_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        claim = json.loads(line)
                        normalized_forms[str(claim.get("subject", {}).get("id", ""))] = [
                            str(unit.get("normalized_form", "")).lower()
                            for unit in claim.get("value", {}).get("analysis_units", [])
                        ]
    noise_linked_examples = []
    for word in sorted(set(old_examples) | set(new_examples)):
        old_by_id = {str(item["id"]): item for item in old_examples.get(word, [])}
        new_ids = {str(item["id"]) for item in new_examples.get(word, [])}
        for example_id in sorted(old_by_id.keys() - new_ids):
            item = old_by_id[example_id]
            occurrence_ids = item.get("occurrence_ids", []) or legacy_examples.get(
                example_id, {}
            ).get("occurrence_ids", [])
            target_occurrence_ids = [
                str(occurrence_id)
                for occurrence_id in occurrence_ids
                if occurrence_surface.get(str(occurrence_id)) == word.lower()
                or word.lower() in normalized_forms.get(str(occurrence_id), [])
            ]
            labels = sorted(
                {
                    label
                    for occurrence_id in target_occurrence_ids
                    for label in noise_by_occurrence.get(str(occurrence_id), [])
                }
            )
            if labels:
                noise_linked_examples.append(
                    {"word": word, "example_id": example_id, "labels": labels, "spanish": item.get("spanish")}
                )

    report = {
        "schema": "fluency.pre-sense-prompt-migration-audit/v1",
        "scope": "Bad Bunny deterministic rerun; no Gemini API call",
        "inputs": {
            "before_plan": str(args.before_plan),
            "after_plan": str(args.after_plan),
            "before_data": str(args.before_data),
            "after_data": str(args.after_data),
            "noise_claims": str(args.noise_claims) if args.noise_claims else None,
        },
        "summary": {
            "before_prompt_records": len(before_records),
            "after_prompt_records": len(after_records),
            "exact_prompt_records": len(exact_words),
            "pure_sense_menu_reorder_records": len(menu_reorder_only),
            "meaningfully_changed_common_records": len(changed_records),
            "removed_from_prompt_queue": len(removed_words),
            "added_to_prompt_queue": len(added_words),
            "change_field_word_counts": dict(sorted(field_word_counts.items())),
            "noise_linked_removed_raw_examples": len(noise_linked_examples),
            "stable_example_pos_changes": len(stable_pos_changes),
            "words_with_stable_example_pos_changes": len({row["word"] for row in stable_pos_changes}),
        },
        "exact_words": exact_words,
        "pure_sense_menu_reorder_words": menu_reorder_only,
        "true_sense_menu_change_words": true_menu_changes,
        "meaningfully_changed_records": changed_records,
        "transitions": transitions,
        "noise_linked_removed_raw_examples": noise_linked_examples,
        "stable_example_pos_changes": stable_pos_changes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
