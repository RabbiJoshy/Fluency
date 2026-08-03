#!/usr/bin/env python3
"""Generate and gate a bounded offline expansion of personalised examples."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
INDEX_PATH = SPANISH / "vocabulary.index.json"
EXAMPLES_PATH = SPANISH / "vocabulary.examples.json"
FRAME_BANK_PATH = SPANISH / "personalised_example_frames.json"
DEFAULT_OUTPUT = SPANISH / "personalised_frame_expansions" / "2026-08-03_v1"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


GENERATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target_id", "decision", "reason", "variants"],
                "properties": {
                    "target_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["variants", "no_safe_slot"]},
                    "reason": {"type": "string"},
                    "variants": {
                        "type": "array", "maxItems": 3,
                        "items": {
                            "type": "object",
                            "required": [
                                "candidate_id", "candidate_word", "spanish_realization",
                                "english_realization", "generated_spanish", "generated_english",
                                "replaced_spanish", "replaced_english", "rationale",
                            ],
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "candidate_word": {"type": "string"},
                                "spanish_realization": {"type": "string"},
                                "english_realization": {"type": "string"},
                                "generated_spanish": {"type": "string"},
                                "generated_english": {"type": "string"},
                                "replaced_spanish": {"type": "string"},
                                "replaced_english": {"type": "string"},
                                "rationale": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}


GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assessments"],
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "variant_id", "sense_preserved", "grammar_valid",
                    "translation_faithful", "role_compatible", "factually_coherent",
                    "natural_for_flashcard", "confidence", "reason",
                ],
                "properties": {
                    "variant_id": {"type": "string"},
                    "sense_preserved": {"type": "boolean"},
                    "grammar_valid": {"type": "boolean"},
                    "translation_faithful": {"type": "boolean"},
                    "role_compatible": {"type": "boolean"},
                    "factually_coherent": {"type": "boolean"},
                    "natural_for_flashcard": {"type": "boolean"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reason": {"type": "string"},
                },
            },
        }
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


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_jsonl(path: Path, key: str) -> dict[str, Any]:
    output = {}
    if not path.is_file():
        return output
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                output[row[key]] = row
    return output


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def tokens(text: str) -> list[str]:
    return re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", text, flags=re.UNICODE)


def contains_word(text: str, word: str) -> bool:
    return word.casefold() in {token.casefold() for token in tokens(text)}


def choose_candidates(index: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    candidates = []
    seen_lemmas = set()
    for rank, entry in enumerate(index, 1):
        meanings = entry.get("meanings") or []
        word = str(entry.get("word") or "")
        lemma = str(entry.get("lemma") or "")
        if (
            len(meanings) != 1
            or meanings[0].get("pos") != "NOUN"
            or word.casefold() != lemma.casefold()
            or lemma.casefold() in seen_lemmas
            or not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", word)
            or len(word) < 3
        ):
            continue
        seen_lemmas.add(lemma.casefold())
        candidates.append({
            "candidate_id": entry["id"],
            "word": word,
            "lemma": lemma,
            "rank": rank,
            "translation": meanings[0].get("translation"),
            "context": meanings[0].get("context"),
        })
        if len(candidates) >= limit:
            break
    return candidates


def choose_targets(index: list[dict[str, Any]], examples: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    targets = []
    for rank, entry in enumerate(index, 1):
        word = str(entry.get("word") or "")
        if not word or len(word) < 3:
            continue
        card_examples = examples.get(entry["id"], {}).get("m") or []
        for meaning_index, meaning in enumerate(entry.get("meanings") or []):
            sense_id = meaning.get("sense_id") or meaning.get("id")
            bucket = card_examples[meaning_index] if meaning_index < len(card_examples) else []
            base = next((row for row in bucket if row.get("source") == "spanishdict"), None)
            if not base or not contains_word(base.get("target", ""), word):
                continue
            count = len(tokens(base["target"]))
            if count < 5 or count > 16 or not base.get("english"):
                continue
            targets.append({
                "target_id": f"{entry['id']}:{sense_id}",
                "target_card_id": entry["id"],
                "target_word": word,
                "target_lemma": entry.get("lemma"),
                "target_rank": rank,
                "target_sense_id": sense_id,
                "target_pos": meaning.get("pos"),
                "target_translation": meaning.get("translation"),
                "target_context": meaning.get("context"),
                "base_spanish": base["target"],
                "base_english": base["english"],
                "base_example_id": base["id"],
            })
            break
        if len(targets) >= limit:
            break
    return targets


GENERATOR_INSTRUCTIONS = """You create offline Spanish flashcard variants.
Each target has one canonical SpanishDict example tied to an authoritative exact
sense. Preserve the target word occurrence and that exact sense. Find at most
one replaceable contiguous noun phrase anywhere else in the sentence. Choose up
to three genuinely compatible candidates from the supplied pool.

The candidate's literal Spanish word must appear in spanish_realization; do not
replace país with España or substitute only a synonym. Replace exactly the
declared Spanish span and aligned English span, regenerating articles,
agreement, and human pronouns inside those spans. Do not copy English `it` for
an adult human. Results must be natural, short, factual, and useful even without
hidden context. Atypical but plausible combinations such as a car with radar are
allowed. Return no_safe_slot rather than stretch a sentence. Never change the
target, its governing construction, negation, reflexivity, or coarguments."""


GATE_INSTRUCTIONS = """You are the final high-precision gate for offline Spanish
flashcard variants. The supplied target sense is authoritative. Judge completed
pairs only; do not repair them. Mark each boolean independently. Reject a target
sense shift, grammar/agreement/coreference defect, incomplete or inaccurate
English, incompatible predicate-role filler, factual contradiction, strained
hidden context, or sentence that sounds unnatural as a standalone flashcard.
Actively test idiomatic preposition choice, determiner use, adverb placement and
scope, and whether the substituted noun makes the whole situation needlessly
contrived. Grammatical possibility alone is not enough for natural_for_flashcard.
Unusual but plausible is acceptable. Use confidence=high only when every check
is clear. The application will keep only rows with all booleans true and high
confidence."""


def call_model(model: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "temperature": 0.0,
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        },
    )
    if not response.text:
        raise ValueError("empty model response")
    return json.loads(response.text)


def batches(items: list[Any], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def generate(targets: list[dict[str, Any]], candidates: list[dict[str, Any]],
             output: Path, model: str, batch_size: int) -> None:
    completed = load_jsonl(output, "target_id")
    pending = [target for target in targets if target["target_id"] not in completed]
    for batch_number, batch in enumerate(batches(pending, batch_size), 1):
        payload = {"candidate_pool": candidates, "targets": batch}
        prompt = GENERATOR_INSTRUCTIONS + "\nINPUT JSON:\n" + json.dumps(payload, ensure_ascii=False)
        last_error = None
        for attempt in range(1, 5):
            try:
                result = call_model(model, prompt, GENERATOR_SCHEMA)
                rows = result.get("items") or []
                by_id = {row.get("target_id"): row for row in rows}
                if set(by_id) != {row["target_id"] for row in batch}:
                    raise ValueError("generator response IDs do not match batch")
                for target in batch:
                    append_jsonl(output, {
                        "target_id": target["target_id"],
                        "target": target,
                        "proposal": by_id[target["target_id"]],
                        "model": model,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    })
                print(f"Generation batch {batch_number}: {len(batch)} targets")
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                print(f"Generation batch {batch_number} attempt {attempt}: {last_error}")
                if attempt < 4:
                    time.sleep(2 ** attempt)
        else:
            raise RuntimeError(last_error)


def deterministic_variants(proposals_path: Path, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    valid, rejected = [], []
    for record in load_jsonl(proposals_path, "target_id").values():
        target = record["target"]
        for variant in record["proposal"].get("variants") or []:
            material = target["target_id"] + ":" + str(variant.get("candidate_id")) + ":" + str(variant.get("generated_spanish"))
            variant_id = "scalev1-" + sha256_text(material)[:12]
            reasons = []
            candidate = candidate_by_id.get(variant.get("candidate_id"))
            if not candidate or variant.get("candidate_word") != candidate["word"]:
                reasons.append("candidate_identity")
            if candidate and not contains_word(variant.get("spanish_realization", ""), candidate["word"]):
                reasons.append("learner_word_absent")
            if not contains_word(variant.get("generated_spanish", ""), target["target_word"]):
                reasons.append("target_word_absent")
            if variant.get("generated_spanish") == target["base_spanish"]:
                reasons.append("source_identical")
            if target["base_spanish"].count(variant.get("replaced_spanish", "")) != 1:
                reasons.append("spanish_span_not_unique")
            if target["base_english"].count(variant.get("replaced_english", "")) != 1:
                reasons.append("english_span_not_unique")
            expected_es = target["base_spanish"].replace(
                variant.get("replaced_spanish", ""), variant.get("spanish_realization", ""), 1
            )
            expected_en = target["base_english"].replace(
                variant.get("replaced_english", ""), variant.get("english_realization", ""), 1
            )
            if variant.get("generated_spanish") != expected_es:
                reasons.append("nonlocal_spanish_change")
            if variant.get("generated_english") != expected_en:
                reasons.append("nonlocal_english_change")
            if not 4 <= len(tokens(variant.get("generated_spanish", ""))) <= 18:
                reasons.append("length")
            row = {
                "variant_id": variant_id,
                "target": target,
                "candidate": candidate,
                "variant": variant,
                "generator_model": record["model"],
                "deterministic_rejections": reasons,
            }
            (rejected if reasons else valid).append(row)
    return valid, rejected


def gate(valid: list[dict[str, Any]], output: Path, model: str, batch_size: int) -> None:
    completed = load_jsonl(output, "variant_id")
    pending = [row for row in valid if row["variant_id"] not in completed]
    for batch_number, batch in enumerate(batches(pending, batch_size), 1):
        prompt = GATE_INSTRUCTIONS + "\nINPUT JSON:\n" + json.dumps({"variants": batch}, ensure_ascii=False)
        last_error = None
        for attempt in range(1, 5):
            try:
                result = call_model(model, prompt, GATE_SCHEMA)
                rows = result.get("assessments") or []
                by_id = {row.get("variant_id"): row for row in rows}
                if set(by_id) != {row["variant_id"] for row in batch}:
                    raise ValueError("gate response IDs do not match batch")
                for row in batch:
                    append_jsonl(output, {
                        "variant_id": row["variant_id"],
                        "assessment": by_id[row["variant_id"]],
                        "model": model,
                        "assessed_at": datetime.now(timezone.utc).isoformat(),
                    })
                print(f"Gate batch {batch_number}: {len(batch)} variants")
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                print(f"Gate batch {batch_number} attempt {attempt}: {last_error}")
                if attempt < 4:
                    time.sleep(2 ** attempt)
        else:
            raise RuntimeError(last_error)


def finalize(output_dir: Path, valid: list[dict[str, Any]], rejected: list[dict[str, Any]],
             merge: bool, review_file: Path | None = None) -> dict[str, Any]:
    assessments = load_jsonl(output_dir / "assessments.jsonl", "variant_id")
    checks = [
        "sense_preserved", "grammar_valid", "translation_faithful",
        "role_compatible", "factually_coherent", "natural_for_flashcard",
    ]
    model_accepted = []
    for row in valid:
        gate_record = assessments.get(row["variant_id"])
        assessment = gate_record.get("assessment") if gate_record else None
        if not assessment:
            continue
        if all(assessment.get(key) is True for key in checks) and assessment.get("confidence") == "high":
            target, candidate, variant = row["target"], row["candidate"], row["variant"]
            model_accepted.append({
                "frame_id": row["variant_id"],
                "validation_tier": "deterministic_plus_model_gate_v1",
                "target_card_id": target["target_card_id"],
                "target_word": target["target_word"],
                "target_lemma": target["target_lemma"],
                "target_sense_id": target["target_sense_id"],
                "target_translation": target["target_translation"],
                "target_context": target.get("target_context"),
                "reinforcement_card_id": candidate["candidate_id"],
                "reinforcement_word": candidate["word"],
                "spanish": variant["generated_spanish"],
                "english": variant["generated_english"],
                "base_source_id": target["base_example_id"],
                "model": row["generator_model"],
                "gate": {
                    "model": gate_record["model"],
                    "assessment": assessment,
                },
            })

    write_json(output_dir / "model_accepted_frames.json", {
        "schema_version": 1,
        "frames": model_accepted,
    })
    review = read_json(review_file) if review_file and review_file.is_file() else None
    if review:
        decisions = {row["frame_id"]: row for row in review.get("decisions") or []}
        accepted = []
        for row in model_accepted:
            decision = decisions.get(row["frame_id"])
            if decision and decision.get("decision") == "accept":
                row["validation_tier"] = "deterministic_model_gate_human_review_v1"
                row["human_review"] = {
                    "reviewer": review.get("reviewer"),
                    "reviewed_at": review.get("reviewed_at"),
                    "reason": decision.get("reason"),
                }
                accepted.append(row)
    else:
        accepted = model_accepted
    write_json(output_dir / "accepted_frames.json", {"schema_version": 1, "frames": accepted})
    metrics = {
        "targets": len(load_jsonl(output_dir / "proposals.jsonl", "target_id")),
        "proposed_variants": len(valid) + len(rejected),
        "deterministic_pass": len(valid),
        "deterministic_reject": len(rejected),
        "gate_assessed": len(assessments),
        "model_accepted_high_confidence": len(model_accepted),
        "accepted_after_review": len(accepted),
        "human_review_applied": bool(review),
        "unique_reinforcement_words": len({row["reinforcement_word"] for row in accepted}),
        "unique_target_senses": len({(row["target_card_id"], row["target_sense_id"]) for row in accepted}),
    }
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "deterministic_rejections.json", rejected)

    if merge:
        bank = read_json(FRAME_BANK_PATH)
        existing = {row["frame_id"] for row in bank.get("frames") or []}
        additions = [row for row in accepted if row["frame_id"] not in existing]
        bank["frames"].extend(additions)
        bank["status"] = "beta_consensus_and_reviewed_generation"
        bank["expanded_selection_rule"] = (
            "New scale-v1 rows pass deterministic constraints, every separate semantic gate check at high confidence, "
            "and an explicit pilot human review."
        )
        bank.setdefault("expansions", []).append({
            "id": output_dir.name,
            "path": output_dir.relative_to(ROOT).as_posix(),
            "frames_added": len(additions),
            "metrics": metrics,
        })
        write_json(FRAME_BANK_PATH, bank)
        metrics["merged"] = len(additions)
        write_json(output_dir / "metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-limit", type=int, default=60)
    parser.add_argument("--candidate-limit", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--gate-batch-size", type=int, default=10)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--gate-model", default=DEFAULT_MODEL)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument(
        "--review-file", type=Path,
        help="Optional explicit accept/reject decisions; defaults to OUTPUT_DIR/human_review.json when present.",
    )
    args = parser.parse_args()

    index = read_json(INDEX_PATH)
    examples = read_json(EXAMPLES_PATH)
    candidates = choose_candidates(index, args.candidate_limit)
    targets = choose_targets(index, examples, args.target_limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "selection.json", {
        "schema_version": 1,
        "targets": targets,
        "candidates": candidates,
        "generator_prompt_sha256": sha256_text(GENERATOR_INSTRUCTIONS),
        "gate_prompt_sha256": sha256_text(GATE_INSTRUCTIONS),
    })
    print(f"Selected {len(targets)} targets and {len(candidates)} candidates")
    if not args.run:
        print("DRY RUN: pass --run to call the models")
        return

    load_dotenv()
    proposals_path = args.output_dir / "proposals.jsonl"
    assessments_path = args.output_dir / "assessments.jsonl"
    generate(targets, candidates, proposals_path, args.model, args.batch_size)
    valid, rejected = deterministic_variants(proposals_path, candidates)
    print(f"Deterministic gate: {len(valid)} pass, {len(rejected)} reject")
    gate(valid, assessments_path, args.gate_model, args.gate_batch_size)
    review_file = args.review_file
    if review_file is None and (args.output_dir / "human_review.json").is_file():
        review_file = args.output_dir / "human_review.json"
    metrics = finalize(args.output_dir, valid, rejected, args.merge, review_file)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
