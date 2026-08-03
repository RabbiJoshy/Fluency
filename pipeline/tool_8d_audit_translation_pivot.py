#!/usr/bin/env python3
"""Contextually audit the translation-pivot pilot with a small LLM batch.

The model may select only an existing pilot sense group or OTHER_OR_UNCLEAR.
It never changes the SpanishDict inventory and never writes to an active run.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PILOT_DIR = (
    ROOT / "Data" / "Spanish" / "Intermediates" /
    "translation_pivot_pilot" / "2026-08-03_v1"
)
DEFAULT_MODEL = "gemini-3.5-flash-lite"
OTHER = "OTHER_OR_UNCLEAR"


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        return api_key
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("GEMINI_API_KEY is not configured")


def audit_sample(
    payload: dict[str, Any], classified_per_word: int, abstained_per_word: int
) -> list[dict[str, Any]]:
    output = []
    for result in payload["results"]:
        word = result["word"]
        records = [record for record in payload["records"] if record["word"] == word]
        classified = [
            record for record in records
            if record["decision"]["status"] == "classified"
        ]
        abstained = [
            record for record in records
            if record["decision"]["status"] == "abstain"
        ]
        # Stable pseudo-random ordering over an already-random reservoir sample.
        key = lambda record: (record["corpus_line"] % 997, record["corpus_line"])
        chosen = (
            sorted(classified, key=key)[:classified_per_word]
            + sorted(abstained, key=key)[:abstained_per_word]
        )
        for index, record in enumerate(chosen, 1):
            output.append({
                "example_id": f"{word}:{index}",
                "word": word,
                "corpus_line": record["corpus_line"],
                "source_ids": record["source_ids"],
                "spanish": record["spanish"],
                "english": record["english"],
                "lexical_decision": record["decision"],
            })
    return output


def prompt_for(
    pilot_payload: dict[str, Any], examples: list[dict[str, Any]]
) -> str:
    menus = []
    result_by_word = {result["word"]: result for result in pilot_payload["results"]}
    for word in result_by_word:
        groups = []
        for group in result_by_word[word]["groups"]:
            senses = "; ".join(
                f"{sense['sense_id']}={sense['translation']}"
                + (f" ({sense['context']})" if sense.get("context") else "")
                for sense in group["senses"]
            )
            groups.append(f"  {group['group_id']}: {senses}")
        menus.append(f"WORD {word}\n" + "\n".join(groups))
    lines = []
    for example in examples:
        lines.append(
            f"{example['example_id']} | ES: {example['spanish']} | EN: {example['english']}"
        )
    schema_example = [{
        "example_id": "banco:1",
        "group_id": "finance",
        "confidence": "high",
        "reason": "financial institution",
    }]
    return "\n".join([
        "Route each occurrence of the named Spanish surface form to one allowed SpanishDict sense group.",
        "The Spanish sentence is authoritative. English is translation evidence, not a keyword rule.",
        f"Use {OTHER} for a proper name, a different lemma/POS, an idiom or meaning not covered by the menu, bad alignment, or genuine uncertainty.",
        "Treat each listed dictionary context as a strict boundary: for example, an animal/clothing tail does not cover the tail of a missile or aircraft.",
        "Do not force an answer. Do not infer a literal sense merely because the English translation contains its gloss.",
        "Confidence must be high, medium, or low. Keep reason under 12 words.",
        "",
        "ALLOWED MENUS",
        "\n\n".join(menus),
        "",
        "EXAMPLES",
        "\n".join(lines),
        "",
        "Return a JSON array in this shape and preserve every example_id exactly:",
        json.dumps(schema_example, ensure_ascii=False),
    ])


def call_gemini(model: str, prompt: str) -> list[dict[str, Any]]:
    from google import genai

    client = genai.Client(api_key=load_api_key())
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"temperature": 0.0, "response_mime_type": "application/json"},
    )
    parsed = json.loads(response.text)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON array from Gemini")
    return parsed


def validate_and_merge(
    pilot_payload: dict[str, Any],
    examples: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed: dict[str, set[str]] = {}
    sense_to_group: dict[str, dict[str, str]] = {}
    for result in pilot_payload["results"]:
        allowed[result["word"]] = {
            group["group_id"] for group in result["groups"]
        } | {OTHER}
        sense_to_group[result["word"]] = {
            sense_id: group["group_id"]
            for group in result["groups"]
            for sense_id in group["sense_ids"]
        }
    by_id = {decision.get("example_id"): decision for decision in decisions}
    expected_ids = {example["example_id"] for example in examples}
    if set(by_id) != expected_ids:
        missing = sorted(expected_ids - set(by_id))
        extra = sorted(set(by_id) - expected_ids)
        raise ValueError(f"Gemini ID mismatch; missing={missing}, extra={extra}")
    output = []
    for example in examples:
        decision = by_id[example["example_id"]]
        group_id = decision.get("group_id")
        if group_id in sense_to_group[example["word"]]:
            decision = {
                **decision,
                "returned_sense_id": group_id,
                "group_id": sense_to_group[example["word"]][group_id],
            }
            group_id = decision["group_id"]
        if group_id not in allowed[example["word"]]:
            raise ValueError(f"Invalid group for {example['example_id']}: {group_id}")
        if decision.get("confidence") not in {"high", "medium", "low"}:
            raise ValueError(f"Invalid confidence for {example['example_id']}")
        output.append({**example, "contextual_decision": decision})
    return output


def build_summary(records: list[dict[str, Any]], model: str) -> dict[str, Any]:
    comparison: Counter[str] = Counter()
    by_word: dict[str, Counter[str]] = {}
    for record in records:
        lexical = record["lexical_decision"]
        contextual = record["contextual_decision"]["group_id"]
        if lexical["status"] == "classified":
            comparison[
                "agreed" if lexical["group_id"] == contextual else "overridden_or_rejected"
            ] += 1
        else:
            comparison[
                "abstention_retained" if contextual == OTHER else "abstention_resolved"
            ] += 1
        by_word.setdefault(record["word"], Counter())[contextual] += 1
    return {
        "experiment": "translation_pivot_contextual_audit_v1",
        "model": model,
        "role": "offline contextual router constrained to stable SpanishDict groups",
        "warning": "Model decisions are a second signal, not human gold labels.",
        "comparison": dict(comparison),
        "by_word": {word: dict(counts) for word, counts in by_word.items()},
        "records": records,
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    comparison = payload["comparison"]
    lines = [
        "# Contextual audit of translation-pivot routing",
        "",
        f"Model: `{payload['model']}`. The model could select only an existing SpanishDict teaching group or `{OTHER}`.",
        "",
        f"- Lexical classifications retained: {comparison.get('agreed', 0)}",
        f"- Lexical classifications overridden/rejected: {comparison.get('overridden_or_rejected', 0)}",
        f"- Lexical abstentions contextually resolved: {comparison.get('abstention_resolved', 0)}",
        f"- Lexical abstentions retained: {comparison.get('abstention_retained', 0)}",
        "- These are model comparisons, not accuracy measurements; human review remains the deciding test.",
        "",
        "## Overrides and rejections",
        "",
        "| Word | Spanish | English | Lexical | Contextual | Confidence | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in payload["records"]:
        lexical = record["lexical_decision"]
        contextual = record["contextual_decision"]
        lexical_group = lexical.get("group_id", "ABSTAIN")
        if lexical_group == contextual["group_id"]:
            continue
        cells = [
            record["word"], record["spanish"], record["english"], lexical_group,
            contextual["group_id"], contextual["confidence"], contextual["reason"],
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "/") for cell in cells) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, default=DEFAULT_PILOT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--classified-per-word", type=int, default=10)
    parser.add_argument("--abstained-per-word", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pilot_payload = read_json(args.pilot_dir / "results.json")
    examples = audit_sample(
        pilot_payload, args.classified_per_word, args.abstained_per_word
    )
    decisions = call_gemini(args.model, prompt_for(pilot_payload, examples))
    records = validate_and_merge(pilot_payload, examples, decisions)
    payload = build_summary(records, args.model)
    write_json(args.pilot_dir / "contextual_audit.json", payload)
    write_report(args.pilot_dir / "contextual_audit.md", payload)
    print(f"wrote {args.pilot_dir / 'contextual_audit.json'}")
    print(f"wrote {args.pilot_dir / 'contextual_audit.md'}")


if __name__ == "__main__":
    main()
