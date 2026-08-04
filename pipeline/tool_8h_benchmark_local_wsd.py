#!/usr/bin/env python3
"""Benchmark a local multilingual reranker on the fixed Speech WSD panel.

This is deliberately a zero-training experiment.  For each marked Spanish
occurrence, the model ranks only the SpanishDict leaves available for that
surface.  The existing 60-row panel lets us measure whether the reranker
accepts valid exact-leaf candidates and rejects the known-bad string matches.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = (
    ROOT
    / "Data/Spanish/Intermediates/speech_alignment_benchmark/2026-08-03_v1/panel.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "Data/Spanish/Intermediates/speech_local_wsd_benchmark/2026-08-03_v1"
)
DEFAULT_MODEL = "Alibaba-NLP/gte-multilingual-reranker-base"
DEFAULT_REVISION = "a6258e9d2b1a11aa7bccdff9efde562bbca4393d"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def context_text(row: dict[str, Any], include_english: bool = False) -> str:
    text = (
        f"Determina el significado de la palabra objetivo «{row['surface']}» "
        f"en esta oración española: {row['spanish']}"
    )
    if include_english:
        text += f" Subtítulo inglés de apoyo, que puede contener ruido: {row['english']}"
    return text


def sense_text(sense: dict[str, Any], variant: str) -> str:
    definition = (
        f"{sense.get('headword', '')} ({sense.get('pos', '')}). "
        f"Traducción: {sense.get('translation') or '[sin traducción]'}. "
        f"Contexto del significado: {sense.get('context') or '[sin contexto]'}."
    )
    examples = sense.get("canonical_examples") or []
    example = examples[0].get("spanish", "") if examples else ""
    if variant == "definition":
        return definition
    if variant == "example":
        return f"Ejemplo de este significado: {example}" if example else definition
    if variant == "definition_example":
        suffix = f" Ejemplo de este significado: {example}" if example else ""
        return definition + suffix
    raise ValueError(f"Unknown variant: {variant}")


def classification_metrics(
    panel: list[dict[str, Any]], predictions: dict[str, str]
) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for row in panel:
        accepted = predictions[row["benchmark_id"]] == row["candidate_sense_id"]
        valid = bool(row["gold_valid_exact_leaf"])
        if accepted and valid:
            tp += 1
        elif accepted and not valid:
            fp += 1
        elif not accepted and not valid:
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "accepted": tp + fp,
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall_of_valid_candidates": round(recall, 6),
        "coverage_of_panel": round((tp + fp) / len(panel), 6),
    }


def run(args: argparse.Namespace) -> None:
    from sentence_transformers import CrossEncoder

    panel = read_jsonl(args.panel)
    model = CrossEncoder(
        args.model,
        revision=args.revision,
        trust_remote_code=True,
        local_files_only=args.local_files_only,
        device=args.device,
    )
    configurations = {
        "definition": ("definition", False),
        "example": ("example", False),
        "definition_example": ("definition_example", False),
        "definition_bilingual": ("definition", True),
        "definition_example_bilingual": ("definition_example", True),
    }
    all_rows: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    for variant, (sense_variant, include_english) in configurations.items():
        pairs: list[tuple[str, str]] = []
        owners: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in panel:
            query = context_text(row, include_english=include_english)
            for sense in row["allowed_senses"]:
                pairs.append((query, sense_text(sense, sense_variant)))
                owners.append((row, sense))

        started = time.perf_counter()
        scores = model.predict(
            pairs,
            batch_size=args.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
        )
        elapsed = time.perf_counter() - started
        grouped: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        source_rows: dict[str, dict[str, Any]] = {}
        for score, (row, sense) in zip(scores, owners):
            benchmark_id = row["benchmark_id"]
            source_rows[benchmark_id] = row
            grouped.setdefault(benchmark_id, []).append((float(score), sense))

        predictions: dict[str, str] = {}
        for benchmark_id, candidates in grouped.items():
            ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
            winner_score, winner = ranked[0]
            runner_up_score = ranked[1][0] if len(ranked) > 1 else None
            source = source_rows[benchmark_id]
            predictions[benchmark_id] = winner["sense_id"]
            all_rows.append(
                {
                    "benchmark_id": benchmark_id,
                    "variant": variant,
                    "predicted_sense_id": winner["sense_id"],
                    "predicted_translation": winner.get("translation", ""),
                    "predicted_context": winner.get("context", ""),
                    "score": winner_score,
                    "margin": (
                        winner_score - runner_up_score
                        if runner_up_score is not None
                        else None
                    ),
                    "candidate_sense_id": source["candidate_sense_id"],
                    "gold_valid_exact_leaf": source["gold_valid_exact_leaf"],
                    "candidate_accepted": winner["sense_id"]
                    == source["candidate_sense_id"],
                }
            )

        variant_metrics = classification_metrics(panel, predictions)
        variant_metrics.update(
            {
                "pairs_scored": len(pairs),
                "elapsed_seconds": round(elapsed, 3),
                "pairs_per_second": round(len(pairs) / elapsed, 3),
                "device": args.device,
            }
        )
        metrics[variant] = variant_metrics

    payload = {
        "model": args.model,
        "revision": args.revision,
        "panel": str(args.panel),
        "panel_size": len(panel),
        "gold_valid": sum(bool(row["gold_valid_exact_leaf"]) for row in panel),
        "gold_invalid": sum(not bool(row["gold_valid_exact_leaf"]) for row in panel),
        "metric_note": (
            "Precision/recall measure agreement with the audited candidate leaf; "
            "invalid rows do not yet have a structured replacement gold ID."
        ),
        "variants": metrics,
    }
    write_jsonl(args.output_dir / "predictions.jsonl", all_rows)
    write_json(args.output_dir / "metrics.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
