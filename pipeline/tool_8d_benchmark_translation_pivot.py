#!/usr/bin/env python3
"""Pilot bilingual-pivot routing into stable SpanishDict sense groups.

This is a deliberately bounded experiment, not a production WSD system. It
reservoir-samples aligned OpenSubtitles occurrences of a handful of ambiguous
Spanish surface forms and applies high-precision English lexical cues. Unknown
and conflicting cases abstain. The active deck and immutable runs are untouched.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import random
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_CORPUS = SPANISH / "corpora" / "opensubtitles"
DEFAULT_MENU = SPANISH / "layers" / "sense_menu" / "spanishdict.json"
DEFAULT_OUTPUT = (
    SPANISH / "Intermediates" / "translation_pivot_pilot" / "2026-08-03_v1"
)


PILOT: dict[str, dict[str, Any]] = {
    "banco": {
        "forms": ["banco", "bancos"],
        "groups": [
            {"id": "seat", "sense_ids": ["64a", "807", "63b", "c83", "b1c"],
             "cues": [r"\bbenches?\b", r"\bpews?\b", r"\bstools?\b", r"\bdesks?\b", r"\bworkbenches?\b"]},
            {"id": "finance", "sense_ids": ["18e"],
             "cues": [r"\bbanks?\b", r"\bbanker(?:s)?\b", r"\bbanking\b"]},
            {"id": "blood_bank", "sense_ids": ["18e6"], "cues": [r"\bblood banks?\b"]},
            {"id": "fish", "sense_ids": ["9e6", "f9e"],
             "cues": [r"\b(?:schools?|shoals?) of (?:fish|tuna)\b"]},
            {"id": "mound", "sense_ids": ["18e63"],
             "cues": [r"\bbanks? of (?:clouds?|fog|sand|seaweed|snow)\b"]},
        ],
    },
    "cola": {
        "forms": ["cola", "colas"],
        "groups": [
            {"id": "tail", "sense_ids": ["237", "2378"], "cues": [r"\btails?\b"]},
            {"id": "queue", "sense_ids": ["b9b", "ff3"], "cues": [r"\bqueues?\b", r"\bwaiting lines?\b", r"\bline up\b"]},
            {"id": "dress_train", "sense_ids": ["885"], "cues": [r"\btrain of (?:my|the|her|his|your) dress\b", r"\bdress(?:'s)? train\b"]},
            {"id": "caboose", "sense_ids": ["801"], "cues": [r"\bcabooses?\b"]},
            {"id": "glue", "sense_ids": ["2a6"], "cues": [r"\bglue\b", r"\badhesive\b"]},
            {"id": "soda", "sense_ids": ["88b"], "cues": [r"\bsodas?\b"]},
            {"id": "buttocks", "sense_ids": ["99e", "095", "10d"], "cues": [r"\bbutts?\b", r"\bbums?\b", r"\bbuttocks\b"]},
            {"id": "penis", "sense_ids": ["a42", "939"], "cues": [r"\bweenies?\b", r"\bwill(?:y|ies)\b"]},
        ],
    },
    "cura": {
        "forms": ["cura", "curas"],
        "groups": [
            {"id": "priest", "sense_ids": ["875"], "cues": [r"\bpriests?\b", r"\bclergym(?:a|e)n\b"]},
            {"id": "cure_or_treatment", "sense_ids": ["b94", "74f"],
             "cues": [r"\bcures?\b", r"\btreatments?\b", r"\bremed(?:y|ies)\b"]},
        ],
    },
    "vela": {
        "forms": ["vela", "velas"],
        "groups": [
            {"id": "candle", "sense_ids": ["5d0"], "cues": [r"\bcandles?\b"]},
            {"id": "sail_or_sailing", "sense_ids": ["a65", "186"],
             "cues": [r"\bsails?\b", r"\bsailing\b"]},
            {"id": "snot", "sense_ids": ["8fc"], "cues": [r"\bsnot\b", r"\bmucus\b"]},
        ],
    },
    "planta": {
        "forms": ["planta", "plantas"],
        "groups": [
            {"id": "botanical_plant", "sense_ids": ["3f3"],
             "cues": [r"\bplants?\b.{0,30}\b(?:garden|grow|growing|leaves|pots?|water)\b", r"\b(?:garden|green|growing|house|potted|water)\b.{0,30}\bplants?\b"]},
            {"id": "factory_plant", "sense_ids": ["3f31"],
             "cues": [r"\b(?:assembly|chemical|industrial|manufacturing|nuclear|power|purification|treatment) plants?\b", r"\bplants?\b.{0,30}\b(?:factory|production|workers?)\b"]},
            {"id": "staff", "sense_ids": ["868"], "cues": [r"\bstaff\b", r"\bpersonnel\b"]},
            {"id": "floor", "sense_ids": ["ac4", "795", "df9"],
             "cues": [r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|top|ground|upper|lower) floors?\b", r"\bfloors?\b.{0,20}\b(?:building|elevator|lift|stairs?|up|down)\b", r"\b(?:stories|storeys) (?:high|tall)\b"]},
            {"id": "plan", "sense_ids": ["522"], "cues": [r"\bbuilding plans?\b", r"\bfloor plans?\b"]},
            {"id": "sole", "sense_ids": ["0a6"], "cues": [r"\bsoles? (?:of|on) (?:my|the|her|his|your) (?:feet|foot)\b"]},
        ],
    },
    "sierra": {
        "forms": ["sierra", "sierras"],
        "groups": [
            {"id": "mountains", "sense_ids": ["391", "5f9"],
             "cues": [r"\bmountain ranges?\b", r"\bmountains?\b", r"\bsierras?\b"]},
            {"id": "saw", "sense_ids": ["995"], "cues": [r"\bsaws?\b", r"\bsawing\b"]},
        ],
    },
    "radio": {
        "forms": ["radio", "radios"],
        "groups": [
            {"id": "radio", "sense_ids": ["835", "8350"],
             "cues": [r"\bradios?\b", r"\bradioed\b", r"\bradioing\b"]},
            {"id": "radius", "sense_ids": ["bad", "bada"], "cues": [r"\bradi(?:us|i)\b"]},
            {"id": "radium", "sense_ids": ["8c9"], "cues": [r"\bradium\b"]},
            {"id": "spoke", "sense_ids": ["f60"], "cues": [r"\bwheel spokes?\b", r"\bspokes? of (?:a|my|the) (?:bike|bicycle|wheel)\b"]},
        ],
    },
}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def compile_pilot(menu: dict[str, Any]) -> dict[str, dict[str, Any]]:
    compiled: dict[str, dict[str, Any]] = {}
    for word, config in PILOT.items():
        menu_senses: dict[str, Any] = {}
        for entry in menu.get(word) or []:
            if entry.get("headword") == word:
                menu_senses.update(entry.get("senses") or {})
        configured_ids = {
            sense_id for group in config["groups"] for sense_id in group["sense_ids"]
        }
        missing = configured_ids - set(menu_senses)
        if missing:
            raise ValueError(f"{word}: missing SpanishDict sense IDs: {sorted(missing)}")
        form_pattern = re.compile(
            r"(?<!\w)(?:" + "|".join(map(re.escape, config["forms"])) + r")(?!\w)",
            re.IGNORECASE,
        )
        groups = []
        for group in config["groups"]:
            groups.append({
                **group,
                "patterns": [re.compile(cue, re.IGNORECASE) for cue in group["cues"]],
                "senses": [
                    {
                        "sense_id": sense_id,
                        "translation": menu_senses[sense_id].get("translation"),
                        "context": menu_senses[sense_id].get("context"),
                    }
                    for sense_id in group["sense_ids"]
                ],
            })
        compiled[word] = {**config, "form_pattern": form_pattern, "groups": groups}
    return compiled


def sample_pairs(
    corpus_dir: Path,
    compiled: dict[str, dict[str, Any]],
    sample_size: int,
    seed: int,
) -> tuple[dict[str, list[dict[str, Any]]], Counter[str], int]:
    samples = {word: [] for word in compiled}
    seen: Counter[str] = Counter()
    rng = random.Random(seed)
    spanish_path = corpus_dir / "OpenSubtitles.en-es.es"
    english_path = corpus_dir / "OpenSubtitles.en-es.en"
    ids_path = corpus_dir / "OpenSubtitles.en-es.ids"
    with (
        spanish_path.open(encoding="utf-8", errors="replace") as spanish_handle,
        english_path.open(encoding="utf-8", errors="replace") as english_handle,
        ids_path.open(encoding="utf-8", errors="replace") as ids_handle,
    ):
        line_count = 0
        for line_count, (spanish, english, source_ids) in enumerate(
            zip(spanish_handle, english_handle, ids_handle), 1
        ):
            spanish = spanish.rstrip("\n")
            for word, config in compiled.items():
                if not config["form_pattern"].search(spanish):
                    continue
                seen[word] += 1
                record = {
                    "corpus_line": line_count,
                    "source_ids": source_ids.rstrip("\n"),
                    "spanish": spanish,
                    "english": english.rstrip("\n"),
                }
                reservoir = samples[word]
                if len(reservoir) < sample_size:
                    reservoir.append(record)
                else:
                    replacement = rng.randrange(seen[word])
                    if replacement < sample_size:
                        reservoir[replacement] = record
            if line_count % 10_000_000 == 0:
                print(f"scanned {line_count:,} aligned lines", flush=True)
    return samples, seen, line_count


def classify(english: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
    matches = []
    for group in groups:
        matched_cues = []
        for pattern in group["patterns"]:
            match = pattern.search(english)
            if match:
                matched_cues.append(match.group(0))
        if matched_cues:
            matches.append((group, matched_cues))
    if not matches:
        return {"status": "abstain", "reason": "no_english_cue"}
    # A more specific phrase wins over a nested generic cue (e.g. blood bank > bank).
    longest = max(max(len(cue) for cue in cues) for _, cues in matches)
    winners = [
        (group, cues) for group, cues in matches
        if max(len(cue) for cue in cues) == longest
    ]
    if len(winners) != 1:
        return {
            "status": "abstain",
            "reason": "conflicting_english_cues",
            "matched_groups": [group["id"] for group, _ in winners],
        }
    group, cues = winners[0]
    return {
        "status": "classified",
        "group_id": group["id"],
        "sense_ids": group["sense_ids"],
        "matched_cues": cues,
    }


def prominence_band(share: float) -> str:
    if share >= 0.55:
        return "dominant"
    if share >= 0.20:
        return "common"
    if share >= 0.05:
        return "occasional"
    return "rare_or_unseen"


def build_payload(
    compiled: dict[str, dict[str, Any]],
    samples: dict[str, list[dict[str, Any]]],
    seen: Counter[str],
    lines_scanned: int,
    sample_size: int,
    seed: int,
) -> dict[str, Any]:
    results = []
    all_records = []
    for word, records in samples.items():
        counts: Counter[str] = Counter()
        classified = 0
        for record in records:
            decision = classify(record["english"], compiled[word]["groups"])
            record.update({"word": word, "decision": decision})
            all_records.append(record)
            if decision["status"] == "classified":
                classified += 1
                counts[decision["group_id"]] += 1
        groups = []
        denominator = len(records)
        for group in compiled[word]["groups"]:
            count = counts[group["id"]]
            share = count / denominator if denominator else 0.0
            groups.append({
                "group_id": group["id"],
                "sense_ids": group["sense_ids"],
                "senses": group["senses"],
                "count": count,
                "share_of_all_sampled_occurrences": share,
                "share_of_classified_occurrences": count / classified if classified else 0.0,
                "provisional_band": prominence_band(share),
            })
        groups.sort(key=lambda row: (-row["count"], row["group_id"]))
        results.append({
            "word": word,
            "matching_corpus_occurrences": seen[word],
            "sampled": denominator,
            "classified": classified,
            "coverage": classified / denominator if denominator else 0.0,
            "groups": groups,
        })
    all_records.sort(key=lambda row: (row["word"], row["corpus_line"]))
    return {
        "experiment": "translation_pivot_pilot_v1",
        "method": "random aligned occurrences; deterministic English cues; explicit abstention",
        "limitations": [
            "Surface-form samples include POS and lemma ambiguity.",
            "Lexical cues test high-precision coverage, not full WSD recall.",
            "OpenSubtitles measures conversational subtitle usage, not all Spanish registers.",
            "Translation-equivalent SpanishDict leaves are retained as grouped stable IDs.",
        ],
        "seed": seed,
        "requested_sample_size_per_word": sample_size,
        "aligned_lines_scanned": lines_scanned,
        "results": results,
        "records": all_records,
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Translation-pivot WSD pilot",
        "",
        "Random occurrences of seven ambiguous Spanish surface forms were sampled from aligned OpenSubtitles. English lexical evidence routes only high-confidence cases; everything else abstains.",
        "",
        "| Word | Corpus occurrences | Sample | Classified | Coverage | Leading routed groups |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for result in payload["results"]:
        leading = ", ".join(
            f"{group['group_id']} {group['share_of_all_sampled_occurrences']:.0%}"
            for group in result["groups"] if group["count"]
        ) or "none"
        lines.append(
            f"| {result['word']} | {result['matching_corpus_occurrences']:,} | "
            f"{result['sampled']} | {result['classified']} | {result['coverage']:.1%} | {leading} |"
        )
    lines.extend([
        "",
        "## Interpretation guardrails",
        "",
        "- Shares use all sampled surface occurrences as the denominator, so abstention cannot inflate a sense.",
        "- `rare_or_unseen` means rare or unseen by this high-precision subtitle test, not proven rare in Spanish.",
        "- The attached JSON retains every sampled bilingual line, corpus source ID, decision, matched cue and SpanishDict sense ID for audit.",
        "- This pilot must be manually audited before its bands are treated as evidence.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--menu", type=Path, default=DEFAULT_MENU)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260803)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    compiled = compile_pilot(read_json(args.menu))
    samples, seen, lines_scanned = sample_pairs(
        args.corpus_dir, compiled, args.sample_size, args.seed
    )
    payload = build_payload(
        compiled, samples, seen, lines_scanned, args.sample_size, args.seed
    )
    write_json(args.output_dir / "results.json", payload)
    write_report(args.output_dir / "headline.md", payload)
    print(f"wrote {args.output_dir / 'results.json'}")
    print(f"wrote {args.output_dir / 'headline.md'}")


if __name__ == "__main__":
    main()
