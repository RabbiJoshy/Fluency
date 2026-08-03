#!/usr/bin/env python3
"""Benchmark an off-the-shelf Spanish masked LM for personalised sentence slots.

This is deliberately an inference-only experiment: it downloads/loads an existing
masked-language model, scores vocabulary fillers, and compares pseudo-likelihood
changes for the reviewed scale-v1 variants. It never trains or fine-tunes a model.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import subprocess
from pathlib import Path
from statistics import median
from typing import Any

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_REVIEW_DIR = SPANISH / "personalised_frame_expansions" / "2026-08-03_v1"
DEFAULT_OUTPUT = DEFAULT_REVIEW_DIR / "masked_lm_benchmark.json"
DEFAULT_REPORT = DEFAULT_REVIEW_DIR / "masked_lm_benchmark.md"
DEFAULT_MODEL = "dccuchile/bert-base-spanish-wwm-cased"
DEFAULT_REVISION = "c4d86612f51b4f46759c8390d1798c2febe71b93"
DEFAULT_CORPUS = SPANISH / "corpora" / "opensubtitles" / "OpenSubtitles.en-es.es"


SLOT_TESTS = [
    {
        "id": "show_possession_masc",
        "sentence": "¿Quieres ver mi [MASK] nuevo?",
        "probes": ["perro", "camión", "robot", "coche", "dinero", "verano"],
        "corpus_pattern": r"quieres ver (?:a )?mi ([[:alpha:]ÁÉÍÓÚÜÑáéíóúüñ]+)",
    },
    {
        "id": "expensive_masc",
        "sentence": "El [MASK] era muy caro.",
        "probes": ["edificio", "hotel", "coche", "perro", "verano", "dinero"],
        "corpus_pattern": r"el ([[:alpha:]ÁÉÍÓÚÜÑáéíóúüñ]+) era muy caro",
    },
    {
        "id": "pass_fem_object",
        "sentence": "¿Me puedes pasar esa [MASK]?",
        "probes": ["tarjeta", "botella", "cerveza", "escuela", "iglesia", "vida"],
        "corpus_pattern": r"(?:me )?puedes pasar esa ([[:alpha:]ÁÉÍÓÚÜÑáéíóúüñ]+)",
    },
    {
        "id": "location_masc",
        "sentence": "Si ellos están aquí, entonces, ¿quién está en el [MASK]?",
        "probes": ["hospital", "hotel", "edificio", "verano", "dinero", "perro"],
        "corpus_pattern": r"quién está en el ([[:alpha:]ÁÉÍÓÚÜÑáéíóúüñ]+)",
    },
    {
        "id": "hot_weather_breakfast_location",
        "sentence": "Cuando hace calor, nos gusta desayunar en la [MASK].",
        "probes": ["escuela", "iglesia", "casa", "cocina", "playa", "calle"],
        "corpus_pattern": r"desayunar en la ([[:alpha:]ÁÉÍÓÚÜÑáéíóúüñ]+)",
    },
    {
        "id": "purchase_without",
        "sentence": "No voy a comprarlo sin [MASK].",
        "probes": ["dinero", "permiso", "ayuda", "miedo", "verano", "perro"],
        "corpus_pattern": r"comprarlo sin ([[:alpha:]ÁÉÍÓÚÜÑáéíóúüñ]+)",
    },
]


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_report(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["reviewed_variant_summary"]
    lines = [
        "# Zero-training masked-filler benchmark",
        "",
        "## Headline",
        "",
        "The pretrained masked model is useful for proposing and ranking fillers inside a deliberately reusable slot, but not as a standalone sentence-quality gate.",
        "",
        f"- No training or fine-tuning was performed; model: `{payload['model']}` at revision `{payload['model_revision']}`.",
        f"- Ranked {payload['eligible_single_token_nouns']:,} single-token noun candidates from the first {payload['vocabulary_limit']:,} vocabulary entries.",
        f"- Source-relative sentence scoring separated accepted from rejected pilot variants with only {summary['pairwise_accuracy']:.1%} pairwise accuracy.",
        "- OpenSubtitles exact-construction counts are retained as an independent attestation signal, not treated as proof that an unattested filler is invalid.",
        "",
        "## Slot results",
        "",
        "| Construction | Top masked-model fillers | Top exact-corpus fillers | Probe ranks |",
        "|---|---|---|---|",
    ]
    for row in payload["slot_tests"]:
        model_top = ", ".join(item["word"] for item in row["top_fillers"][:10])
        corpus_top = ", ".join(
            f"{item['word']} ({item['count']})" for item in row["corpus"]["top_fillers"][:8]
        ) or "none"
        probes = ", ".join(
            f"{probe['word']}={probe['rank'] if probe['rank'] is not None else 'n/a'}"
            for probe in row["probes"]
        )
        lines.append(f"| {row['sentence']} | {model_top} | {corpus_top} | {probes} |")
    lines.extend([
        "",
        "## Decision",
        "",
        "Use masked-token rank as a cheap candidate-generator signal. Combine it with grammatical constraints and corpus construction evidence. Do not use whole-sentence pseudo-likelihood as the publication gate, and retain a semantic/naturalness review for combinations whose broader situation can be odd despite strong local probability.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def frame_id(target_id: str, candidate_id: str, generated_spanish: str) -> str:
    material = f"{target_id}:{candidate_id}:{generated_spanish}"
    return "scalev1-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def reviewed_variants(review_dir: Path) -> list[dict[str, Any]]:
    decisions = {
        row["frame_id"]: row
        for row in read_json(review_dir / "human_review.json").get("decisions") or []
    }
    output = []
    for record in load_jsonl(review_dir / "proposals.jsonl"):
        target = record["target"]
        for variant in record["proposal"].get("variants") or []:
            variant_id = frame_id(
                target["target_id"], str(variant.get("candidate_id")),
                str(variant.get("generated_spanish")),
            )
            decision = decisions.get(variant_id)
            if not decision:
                continue
            output.append({
                "frame_id": variant_id,
                "decision": decision["decision"],
                "review_reason": decision["reason"],
                "base_spanish": target["base_spanish"],
                "generated_spanish": variant["generated_spanish"],
                "replaced_spanish": variant["replaced_spanish"],
                "spanish_realization": variant["spanish_realization"],
                "reinforcement_word": variant["candidate_word"],
            })
    if set(decisions) != {row["frame_id"] for row in output}:
        raise ValueError("Could not reconstruct every reviewed scale-v1 variant")
    return output


class MaskedScorer:
    def __init__(self, model_name: str, revision: str, device: str) -> None:
        self.model_name = model_name
        self.revision = revision
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        self.model = AutoModelForMaskedLM.from_pretrained(
            model_name, revision=revision, use_safetensors=False
        )
        self.model.eval()
        self.device = torch.device(device)
        self.model.to(self.device)

    @torch.inference_mode()
    def pseudo_log_likelihood(self, sentence: str) -> float:
        encoded = self.tokenizer(sentence, return_tensors="pt")
        input_ids = encoded["input_ids"].to(self.device)
        attention = encoded["attention_mask"].to(self.device)
        special = self.tokenizer.get_special_tokens_mask(
            input_ids[0].tolist(), already_has_special_tokens=True
        )
        positions = [index for index, is_special in enumerate(special) if not is_special]
        if not positions:
            return float("nan")
        masked = input_ids.repeat(len(positions), 1)
        masked_attention = attention.repeat(len(positions), 1)
        rows = torch.arange(len(positions), device=self.device)
        cols = torch.tensor(positions, device=self.device)
        expected = masked[rows, cols].clone()
        masked[rows, cols] = self.tokenizer.mask_token_id
        logits = self.model(input_ids=masked, attention_mask=masked_attention).logits
        selected = logits[rows, cols].log_softmax(dim=-1)[rows, expected]
        return float(selected.mean().cpu())

    @torch.inference_mode()
    def slot_logits(self, sentence: str) -> torch.Tensor:
        rendered = sentence.replace("[MASK]", self.tokenizer.mask_token)
        encoded = self.tokenizer(rendered, return_tensors="pt")
        input_ids = encoded["input_ids"].to(self.device)
        positions = (input_ids[0] == self.tokenizer.mask_token_id).nonzero().flatten()
        if len(positions) != 1:
            raise ValueError(f"Expected exactly one mask: {sentence}")
        logits = self.model(
            input_ids=input_ids,
            attention_mask=encoded["attention_mask"].to(self.device),
        ).logits[0, int(positions[0])]
        return logits.log_softmax(dim=-1).cpu()

    def single_token_id(self, word: str) -> int | None:
        token_ids = self.tokenizer.encode(word, add_special_tokens=False)
        return token_ids[0] if len(token_ids) == 1 else None


def eligible_nouns(index: list[dict[str, Any]], scorer: MaskedScorer, limit: int) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for rank, entry in enumerate(index[:limit], 1):
        word = str(entry.get("word") or "")
        if (
            word.casefold() in seen
            or not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", word)
            or not any(meaning.get("pos") == "NOUN" for meaning in entry.get("meanings") or [])
        ):
            continue
        token_id = scorer.single_token_id(word)
        if token_id is None:
            continue
        seen.add(word.casefold())
        output.append({"word": word, "rank": rank, "token_id": token_id})
    return output


def slot_results(scorer: MaskedScorer, nouns: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    results = []
    noun_by_fold = {row["word"].casefold(): row for row in nouns}
    for test in SLOT_TESTS:
        log_probs = scorer.slot_logits(test["sentence"])
        ranked = sorted(nouns, key=lambda row: float(log_probs[row["token_id"]]), reverse=True)
        rank_by_word = {row["word"].casefold(): index for index, row in enumerate(ranked, 1)}
        probes = []
        for word in test["probes"]:
            noun = noun_by_fold.get(word.casefold())
            probes.append({
                "word": word,
                "eligible": noun is not None,
                "rank": rank_by_word.get(word.casefold()),
                "log_probability": (
                    float(log_probs[noun["token_id"]]) if noun is not None else None
                ),
            })
        results.append({
            "id": test["id"],
            "sentence": test["sentence"],
            "eligible_nouns": len(nouns),
            "top_fillers": [
                {
                    "word": row["word"],
                    "vocabulary_rank": row["rank"],
                    "log_probability": float(log_probs[row["token_id"]]),
                }
                for row in ranked[:top_k]
            ],
            "probes": probes,
        })
    return results


def corpus_results(corpus: Path, pattern: str, probes: list[str], top_k: int) -> dict[str, Any]:
    process = subprocess.run(
        ["rg", "-i", "-o", "-r", "$1", pattern, str(corpus)],
        check=False, capture_output=True, text=True,
    )
    if process.returncode not in (0, 1):
        raise RuntimeError(process.stderr.strip() or f"rg failed with {process.returncode}")
    counts = Counter(line.casefold() for line in process.stdout.splitlines() if line.strip())
    display = {}
    for line in process.stdout.splitlines():
        if line.strip():
            display.setdefault(line.casefold(), line)
    return {
        "pattern": pattern,
        "matches": sum(counts.values()),
        "distinct_fillers": len(counts),
        "top_fillers": [
            {"word": display[word], "count": count}
            for word, count in counts.most_common(top_k)
        ],
        "probe_counts": {word: counts[word.casefold()] for word in probes},
    }


def variant_results(scorer: MaskedScorer, variants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    for number, variant in enumerate(variants, 1):
        base_score = scorer.pseudo_log_likelihood(variant["base_spanish"])
        generated_score = scorer.pseudo_log_likelihood(variant["generated_spanish"])
        row = dict(variant)
        row.update({
            "base_mean_log_probability": base_score,
            "generated_mean_log_probability": generated_score,
            "delta": generated_score - base_score,
        })
        rows.append(row)
        print(f"Scored reviewed variant {number}/{len(variants)}: {variant['decision']}")

    accepted = [row["delta"] for row in rows if row["decision"] == "accept"]
    rejected = [row["delta"] for row in rows if row["decision"] == "reject"]
    pairwise = [good > bad for good in accepted for bad in rejected]
    summary = {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "accepted_median_delta": median(accepted),
        "rejected_median_delta": median(rejected),
        "pairwise_accuracy": sum(pairwise) / len(pairwise),
        "interpretation": (
            "pairwise_accuracy is the probability that a random human-accepted variant "
            "receives a better source-relative score than a random human-rejected variant"
        ),
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--review-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--vocabulary-limit", type=int, default=10_000)
    parser.add_argument("--top-k", type=int, default=25)
    args = parser.parse_args()

    torch.manual_seed(0)
    scorer = MaskedScorer(args.model, args.revision, args.device)
    index = read_json(SPANISH / "vocabulary.index.json")
    nouns = eligible_nouns(index, scorer, args.vocabulary_limit)
    print(f"Eligible single-token nouns: {len(nouns)}")
    slots = slot_results(scorer, nouns, args.top_k)
    for test, row in zip(SLOT_TESTS, slots):
        row["corpus"] = corpus_results(
            args.corpus, test["corpus_pattern"], test["probes"], args.top_k
        )
    reviewed = reviewed_variants(args.review_dir)
    variants, summary = variant_results(scorer, reviewed)
    payload = {
        "schema_version": 1,
        "training_performed": False,
        "model": args.model,
        "model_revision": args.revision,
        "device": str(scorer.device),
        "vocabulary_limit": args.vocabulary_limit,
        "eligible_single_token_nouns": len(nouns),
        "slot_tests": slots,
        "reviewed_variant_scores": variants,
        "reviewed_variant_summary": summary,
        "limitations": [
            "Single-mask filler ranking covers only vocabulary words represented by one model token.",
            "Masked-token probability measures contextual plausibility, not target-sense preservation.",
            "Pseudo-log-likelihood is evaluated on only 16 reviewed pilot variants.",
        ],
    }
    write_json(args.output, payload)
    write_report(args.report, payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {args.output.relative_to(ROOT)}")
    print(f"Wrote {args.report.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
