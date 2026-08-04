#!/usr/bin/env python3
"""Tiny exact-inventory WSD fine-tune using SpanishDict canonical examples.

The model sees a marked Spanish usage and one candidate SpanishDict definition,
then predicts match/non-match.  Canonical examples supply positive labels and
sibling leaves of the same surface supply hard negatives.  The external 60-row
Speech panel is evaluation-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Iterable

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from tool_8h_benchmark_local_wsd import classification_metrics, sense_text


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_MENU = SPANISH / "layers" / "sense_menu" / "spanishdict.json"
DEFAULT_PANEL = (
    SPANISH
    / "Intermediates/speech_alignment_benchmark/2026-08-03_v1/panel.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    SPANISH / "Intermediates/speech_local_wsd_finetune/2026-08-03_v1"
)
DEFAULT_MODEL = "bert-base-multilingual-cased"
DEFAULT_REVISION = "3f076fdb1ab68d5b2880cb87a0886f315b8146f8"


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def stable_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def query_text(
    surface: str, spanish: str, english: str = "", include_english: bool = False
) -> str:
    text = (
        f"Determina el significado de la palabra objetivo «{surface}» "
        f"en esta oración española: {spanish}"
    )
    if include_english and english:
        text += f" Subtítulo inglés de apoyo: {english}"
    return text


def flatten_training_senses(menu: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_surface: dict[str, dict[str, dict[str, Any]]] = {}
    for surface, analyses in menu.items():
        if not isinstance(analyses, list):
            continue
        leaves = by_surface.setdefault(surface, {})
        for analysis in analyses:
            headword = analysis.get("headword") or surface
            for sense_id, sense in (analysis.get("senses") or {}).items():
                examples = [
                    {
                        "spanish": example.get("original") or "",
                        "english": example.get("translated") or "",
                    }
                    for example in (sense.get("examples") or [])
                    if example.get("original")
                ]
                leaves.setdefault(
                    sense_id,
                    {
                        "sense_id": sense_id,
                        "headword": headword,
                        "pos": sense.get("pos") or "",
                        "translation": sense.get("translation") or "",
                        "context": sense.get("context") or "",
                        "canonical_examples": examples[:1],
                    },
                )
    return {surface: list(leaves.values()) for surface, leaves in by_surface.items()}


def build_training_pairs(
    menu: dict[str, Any],
    priority_surfaces: set[str],
    max_positives: int,
    negatives_per_positive: int,
) -> tuple[list[tuple[str, str, int]], dict[str, Any]]:
    by_surface = flatten_training_senses(menu)
    positives: list[tuple[str, dict[str, Any], list[dict[str, Any]]]] = []
    for surface, senses in by_surface.items():
        if len(senses) < 2:
            continue
        for sense in senses:
            if sense.get("canonical_examples"):
                positives.append((surface, sense, senses))
    positives.sort(
        key=lambda item: (
            0 if item[0] in priority_surfaces else 1,
            stable_key(item[0], item[1]["sense_id"]),
        )
    )
    selected = positives[:max_positives]
    pairs: list[tuple[str, str, int]] = []
    priority_count = 0
    bilingual_count = 0
    for surface, positive, siblings in selected:
        if surface in priority_surfaces:
            priority_count += 1
        example = positive["canonical_examples"][0]
        include_english = int(stable_key(surface, positive["sense_id"])[-1], 16) % 2 == 0
        if include_english and example.get("english"):
            bilingual_count += 1
        query = query_text(
            surface,
            example["spanish"],
            example.get("english", ""),
            include_english=include_english,
        )
        pairs.append((query, sense_text(positive, "definition"), 1))
        negatives = [s for s in siblings if s["sense_id"] != positive["sense_id"]]
        negatives.sort(key=lambda sense: stable_key(surface, positive["sense_id"], sense["sense_id"]))
        for negative in negatives[:negatives_per_positive]:
            pairs.append((query, sense_text(negative, "definition"), 0))
    random.Random(17).shuffle(pairs)
    return pairs, {
        "available_positives": len(positives),
        "selected_positives": len(selected),
        "priority_surface_positives": priority_count,
        "bilingual_training_queries": bilingual_count,
        "negatives_per_positive": negatives_per_positive,
        "training_pairs": len(pairs),
    }


class PairDataset(Dataset):
    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[str, str, int]:
        return self.rows[index]


def freeze_lower_bert_layers(model: Any, frozen_layers: int) -> None:
    for parameter in model.bert.embeddings.parameters():
        parameter.requires_grad = False
    for layer in model.bert.encoder.layer[:frozen_layers]:
        for parameter in layer.parameters():
            parameter.requires_grad = False


def evaluate(
    model: Any,
    tokenizer: Any,
    panel: list[dict[str, Any]],
    device: torch.device,
    batch_size: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model.eval()
    results: dict[str, Any] = {}
    output_rows: list[dict[str, Any]] = []
    for variant, bilingual in (("spanish_only", False), ("bilingual", True)):
        pairs: list[tuple[str, str]] = []
        owners: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in panel:
            query = query_text(
                row["surface"], row["spanish"], row.get("english", ""), bilingual
            )
            for sense in row["allowed_senses"]:
                pairs.append((query, sense_text(sense, "definition")))
                owners.append((row, sense))
        scores: list[float] = []
        started = time.perf_counter()
        with torch.inference_mode():
            for start in range(0, len(pairs), batch_size):
                batch = pairs[start : start + batch_size]
                encoded = tokenizer(
                    [item[0] for item in batch],
                    [item[1] for item in batch],
                    padding=True,
                    truncation=True,
                    max_length=192,
                    return_tensors="pt",
                ).to(device)
                logits = model(**encoded).logits
                scores.extend(torch.softmax(logits, dim=-1)[:, 1].cpu().tolist())
        elapsed = time.perf_counter() - started
        grouped: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        sources: dict[str, dict[str, Any]] = {}
        for score, (row, sense) in zip(scores, owners):
            grouped.setdefault(row["benchmark_id"], []).append((score, sense))
            sources[row["benchmark_id"]] = row
        predictions: dict[str, str] = {}
        for benchmark_id, candidates in grouped.items():
            ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
            winner_score, winner = ranked[0]
            runner_up = ranked[1][0] if len(ranked) > 1 else None
            source = sources[benchmark_id]
            predictions[benchmark_id] = winner["sense_id"]
            output_rows.append(
                {
                    "benchmark_id": benchmark_id,
                    "variant": variant,
                    "predicted_sense_id": winner["sense_id"],
                    "predicted_translation": winner.get("translation", ""),
                    "predicted_context": winner.get("context", ""),
                    "score": winner_score,
                    "margin": winner_score - runner_up if runner_up is not None else None,
                    "candidate_sense_id": source["candidate_sense_id"],
                    "gold_valid_exact_leaf": source["gold_valid_exact_leaf"],
                    "candidate_accepted": winner["sense_id"] == source["candidate_sense_id"],
                }
            )
        variant_metrics = classification_metrics(panel, predictions)
        variant_metrics.update(
            {
                "pairs_scored": len(pairs),
                "elapsed_seconds": round(elapsed, 3),
                "pairs_per_second": round(len(pairs) / elapsed, 3),
            }
        )
        results[variant] = variant_metrics
    return results, output_rows


def run(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    panel = read_jsonl(args.panel)
    priority_surfaces = {row["surface"] for row in panel}
    training_pairs, training_stats = build_training_pairs(
        read_json(args.menu),
        priority_surfaces,
        args.max_positives,
        args.negatives_per_positive,
    )
    print(json.dumps(training_stats, indent=2), flush=True)

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, revision=args.revision, local_files_only=args.local_files_only
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        revision=args.revision,
        local_files_only=args.local_files_only,
        num_labels=2,
    )
    freeze_lower_bert_layers(model, args.frozen_layers)
    model.to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad), lr=args.learning_rate
    )

    def collate(batch: list[tuple[str, str, int]]) -> dict[str, torch.Tensor]:
        encoded = tokenizer(
            [item[0] for item in batch],
            [item[1] for item in batch],
            padding=True,
            truncation=True,
            max_length=args.max_length,
            return_tensors="pt",
        )
        encoded["labels"] = torch.tensor([item[2] for item in batch], dtype=torch.long)
        return encoded

    loader = DataLoader(
        PairDataset(training_pairs),
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate,
    )
    started = time.perf_counter()
    losses: list[float] = []
    for epoch in range(args.epochs):
        model.train()
        for step, batch in enumerate(loader, 1):
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            output = model(**batch)
            output.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(output.loss.detach().cpu()))
            if step == 1 or step % 25 == 0 or step == len(loader):
                recent = losses[-25:]
                print(
                    f"epoch {epoch + 1}/{args.epochs} step {step}/{len(loader)} "
                    f"loss {sum(recent) / len(recent):.4f}",
                    flush=True,
                )
    training_seconds = time.perf_counter() - started
    metrics, predictions = evaluate(
        model, tokenizer, panel, device, args.eval_batch_size
    )
    payload = {
        "model": args.model,
        "revision": args.revision,
        "device": args.device,
        "panel_size": len(panel),
        "gold_valid": sum(bool(row["gold_valid_exact_leaf"]) for row in panel),
        "gold_invalid": sum(not bool(row["gold_valid_exact_leaf"]) for row in panel),
        "training": {
            **training_stats,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "frozen_layers": args.frozen_layers,
            "trainable_parameters": trainable,
            "total_parameters": total,
            "training_seconds": round(training_seconds, 3),
            "final_recent_loss": round(sum(losses[-25:]) / min(25, len(losses)), 6),
        },
        "variants": metrics,
        "metric_note": (
            "Precision/recall measure agreement with the audited candidate leaf; "
            "invalid rows do not yet have a structured replacement gold ID."
        ),
    }
    write_jsonl(args.output_dir / "predictions.jsonl", predictions)
    write_json(args.output_dir / "metrics.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--menu", type=Path, default=DEFAULT_MENU)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--max-positives", type=int, default=5000)
    parser.add_argument("--negatives-per-positive", type=int, default=2)
    parser.add_argument("--frozen-layers", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--eval-batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=192)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--seed", type=int, default=17)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
