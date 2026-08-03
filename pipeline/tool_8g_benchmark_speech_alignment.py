#!/usr/bin/env python3
"""Benchmark word alignment + semantic WSD on the retained Speech candidates.

This is deliberately bounded.  It evaluates a fixed, manually reviewed set of
60 polysemous string-match candidates.  No corpus-wide rerun or app/deck change
is performed.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable

from tool_8f_run_speech_string_audit import (
    ENGLISH_TOKEN_RE,
    SPANISH_TOKEN_RE,
    flatten_menu,
    normalize_tokens,
)


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_AUDIT = SPANISH / "Intermediates" / "speech_string_audit" / "2026-08-03_v1"
DEFAULT_INDEX = SPANISH / "vocabulary.index.json"
DEFAULT_MENU = SPANISH / "layers" / "sense_menu" / "spanishdict.json"
DEFAULT_OUTPUT = (
    SPANISH / "Intermediates" / "speech_alignment_benchmark" / "2026-08-03_v1"
)
DEFAULT_MODEL = "gemini-3.5-flash-lite"
OTHER = "OTHER_OR_UNCLEAR"
PANEL_SIZE = 60


# Gold was recorded before running SimAlign or the semantic gate.  The panel is
# deterministic: the first 60 SHA-256-ranked assigned candidates from surfaces
# with more than one SpanishDict leaf.  False means that the proposed exact leaf
# does not describe the marked Spanish token in this occurrence.
REJECTED_GOLD: dict[str, str] = {
    "antes|28744267": "bad alignment; suedes does not translate antes",
    "daba|33517783": "press translates presionaba, while daba means gave",
    "pecho|31841988": "shoved translates metieron, while pecho is chest",
    "caerá|48996735": "sets translates se oculte, while caerá means will fall",
    "informado|26910713": "find out is another clause; informado means informed/posted",
    "hicimos|24611728": "prepare translates prepararlos, while hicimos means did",
    "daremos|2142249": "yield relates liberar; daremos means we will give",
    "pago|13536912": "target is present I pay, not the proposed paid-for leaf",
    "salvo|6806104": "passed translates pasa, while salvo means except",
    "buscó|6202637": "looked dashing is not buscar in the proposed search sense",
    "códigos|47591341": "passwords translates contraseñas, while códigos means codes",
    "pondría|51686346": "idiomatic state change is not the to-ship context",
    "vales|51499961": "won translates gané, while vales means vouchers",
    "carga|59062461": "blame translates culparía, while carga means burden",
    "ningun|11167287": "nobody describes the speaker; ningún modifies mocoso",
    "imposible|8442060": "difficult translates difícil; proposed insufferable leaf is wrong",
    "maría|41183981": "grass translates hierba; María is a proper name",
    "cabrones|29424961": "butt buddies is an insult, not the friend leaf for cabrones",
    "derecho|8034718": "dues is an English idiom; derecho means right here",
    "fines|7716166": "fines means purposes; proposed conclusion leaf is wrong",
}


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


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def panel_key(row: dict[str, Any]) -> str:
    return f"{row['surface']}|{row['corpus_line']}"


def candidate_hash(row: dict[str, Any]) -> str:
    decision = row["decision"]
    material = (
        f"{row['surface']}|{decision['sense_id']}|{row['corpus_line']}"
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def canonical_senses(menu: dict[str, Any], surface: str) -> dict[str, dict[str, Any]]:
    result = {}
    for analysis in menu.get(surface) or []:
        headword = analysis.get("headword") or surface
        for sense_id, sense in (analysis.get("senses") or {}).items():
            examples = [
                {
                    "spanish": example.get("original"),
                    "english": example.get("translated"),
                }
                for example in (sense.get("examples") or [])
                if example.get("original") and example.get("translated")
            ]
            result.setdefault(sense_id, {
                "sense_id": sense_id,
                "headword": headword,
                "pos": sense.get("pos"),
                "translation": sense.get("translation") or "",
                "context": sense.get("context"),
                "regions": sense.get("regions") or [],
                "canonical_examples": examples[:1],
            })
    return result


def prepare(args: argparse.Namespace) -> None:
    if args.output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark: {args.output_dir}")
    index = read_json(args.index)
    menu = read_json(args.menu)
    surfaces = {str(row.get("word") or "").casefold() for row in index if row.get("word")}
    menu_senses = flatten_menu(menu, surfaces)
    poly = {surface for surface, senses in menu_senses.items() if len(senses) > 1}
    candidates = [
        row for row in read_jsonl(args.audit_dir / "audit_samples.jsonl")
        if row.get("decision", {}).get("status") == "assigned"
        and row.get("surface") in poly
    ]
    selected = sorted(candidates, key=candidate_hash)[:PANEL_SIZE]
    selected_keys = {panel_key(row) for row in selected}
    if not set(REJECTED_GOLD) <= selected_keys:
        missing = sorted(set(REJECTED_GOLD) - selected_keys)
        raise RuntimeError(f"Gold keys no longer match deterministic panel: {missing}")

    panel = []
    for row in selected:
        key = panel_key(row)
        candidate_sense_id = row["decision"]["sense_id"]
        allowed = canonical_senses(menu, row["surface"])
        if candidate_sense_id not in allowed:
            raise RuntimeError(f"Missing candidate sense {key}: {candidate_sense_id}")
        panel.append({
            "benchmark_id": key,
            "surface": row["surface"],
            "corpus_line": row["corpus_line"],
            "spanish": row["spanish"],
            "english": row["english"],
            "matched_cues": row["decision"].get("matched_cues") or [],
            "candidate_sense_id": candidate_sense_id,
            "candidate_sense": allowed[candidate_sense_id],
            "allowed_senses": list(allowed.values()),
            "gold_valid_exact_leaf": key not in REJECTED_GOLD,
            "gold_note": REJECTED_GOLD.get(key, "exact leaf fits the marked token usage"),
        })
    args.output_dir.mkdir(parents=True)
    write_jsonl(args.output_dir / "panel.jsonl", panel)
    write_json(args.output_dir / "manifest.json", {
        "schema_version": 1,
        "status": "prepared",
        "panel_method": "first 60 SHA-256-ranked retained assignments from polysemous surfaces",
        "gold_recorded_before_predictions": True,
        "panel_size": len(panel),
        "gold_valid": sum(row["gold_valid_exact_leaf"] for row in panel),
        "gold_invalid": sum(not row["gold_valid_exact_leaf"] for row in panel),
        "source_audit": str(args.audit_dir.relative_to(ROOT)),
    })
    print(f"Prepared {len(panel)} rows: {args.output_dir / 'panel.jsonl'}")


def sequence_starts(sequence: tuple[str, ...], subsequence: tuple[str, ...]) -> list[int]:
    if not subsequence:
        return []
    return [
        index for index in range(len(sequence) - len(subsequence) + 1)
        if sequence[index:index + len(subsequence)] == subsequence
    ]


def span_indices(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> set[int]:
    result = set()
    for start in sequence_starts(tokens, phrase):
        result.update(range(start, start + len(phrase)))
    return result


def alignment_decision(
    row: dict[str, Any], alignments: dict[str, list[tuple[int, int]]]
) -> dict[str, Any]:
    spanish_tokens = normalize_tokens(row["spanish"], SPANISH_TOKEN_RE)
    english_tokens = normalize_tokens(row["english"], ENGLISH_TOKEN_RE)
    surface_tokens = normalize_tokens(row["surface"], SPANISH_TOKEN_RE)
    target_indices = span_indices(spanish_tokens, surface_tokens)
    cue_indices = set()
    for cue in row["matched_cues"]:
        cue_indices |= span_indices(
            english_tokens, normalize_tokens(cue, ENGLISH_TOKEN_RE)
        )
    methods = {}
    for method, pairs in alignments.items():
        hits = [
            [source, target] for source, target in pairs
            if source in target_indices and target in cue_indices
        ]
        methods[method] = {
            "accept": bool(hits),
            "target_to_cue_pairs": hits,
        }
    return {
        "spanish_tokens": spanish_tokens,
        "english_tokens": english_tokens,
        "target_indices": sorted(target_indices),
        "cue_indices": sorted(cue_indices),
        "methods": methods,
    }


def align(args: argparse.Namespace) -> None:
    from simalign import SentenceAligner

    panel = read_jsonl(args.output_dir / "panel.jsonl")
    aligner = SentenceAligner(
        model=args.aligner_model,
        token_type="bpe",
        matching_methods="mai",
        device="cpu",
    )
    output = []
    started = time.monotonic()
    for index, row in enumerate(panel, 1):
        spanish_tokens = list(normalize_tokens(row["spanish"], SPANISH_TOKEN_RE))
        english_tokens = list(normalize_tokens(row["english"], ENGLISH_TOKEN_RE))
        raw = aligner.get_word_aligns(spanish_tokens, english_tokens)
        output.append({
            "benchmark_id": row["benchmark_id"],
            "aligner": {
                "package": "simalign",
                "model": aligner.model,
                "layer": 8,
            },
            "decision": alignment_decision(row, raw),
        })
        print(f"\raligned {index}/{len(panel)}", end="", flush=True)
    print(f" in {time.monotonic() - started:.1f}s")
    write_jsonl(args.output_dir / "alignments.jsonl", output)


def semantic_prompt(rows: list[dict[str, Any]]) -> str:
    items = []
    for row in rows:
        senses = [
            {
                "sense_id": sense["sense_id"],
                "headword": sense["headword"],
                "pos": sense["pos"],
                "translation": sense["translation"],
                "context": sense.get("context"),
                "regions": sense.get("regions") or [],
                "canonical_example": (sense.get("canonical_examples") or [None])[0],
            }
            for sense in row["allowed_senses"]
        ]
        items.append({
            "benchmark_id": row["benchmark_id"],
            "target_surface": row["surface"],
            "spanish_sentence": row["spanish"],
            "english_alignment": row["english"],
            "allowed_spanishdict_senses": senses,
        })
    return "\n".join([
        "Perform exact closed-set Spanish word-sense disambiguation.",
        "For each item, classify only the TARGET SURFACE token in the Spanish sentence.",
        "The Spanish sentence is authoritative. English is supporting sentence-level evidence and may translate another token; never attach an English word merely because it appears.",
        "Choose one listed SpanishDict sense only when its full translation AND context describe this occurrence. Otherwise choose OTHER_OR_UNCLEAR.",
        "Do not collapse translation-equivalent leaves. Proper-name, different-lemma, bad-alignment, and unlisted uses must be OTHER_OR_UNCLEAR.",
        "Confidence is high, medium, or low. Use high only when the exact leaf is unambiguous.",
        "Return JSON only as an array with one row per benchmark_id:",
        '[{"benchmark_id":"...","sense_id":"listed ID or OTHER_OR_UNCLEAR","confidence":"high|medium|low","reason":"under 16 words"}]',
        "",
        json.dumps(items, ensure_ascii=False),
    ])


def load_api_key() -> str:
    value = os.environ.get("GEMINI_API_KEY")
    if value:
        return value
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("GEMINI_API_KEY is not configured")


def call_semantic_model(model: str, prompt: str) -> list[dict[str, Any]]:
    from google import genai

    client = genai.Client(api_key=load_api_key())
    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
            parsed = json.loads(response.text)
            if isinstance(parsed, dict):
                parsed = parsed.get("decisions") or parsed.get("assignments")
            if not isinstance(parsed, list):
                raise ValueError("Semantic gate did not return a JSON array")
            return parsed
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError("Semantic gate failed after retries") from last_error


def semantic(args: argparse.Namespace) -> None:
    panel = read_jsonl(args.output_dir / "panel.jsonl")
    output_path = args.output_dir / "semantic.jsonl"
    existing = read_jsonl(output_path) if output_path.is_file() else []
    complete = {row["benchmark_id"] for row in existing}
    pending = [row for row in panel if row["benchmark_id"] not in complete]
    by_id = {row["benchmark_id"]: row for row in panel}
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start:start + args.batch_size]
        raw = call_semantic_model(args.model, semantic_prompt(batch))
        raw_by_id = {str(row.get("benchmark_id")): row for row in raw}
        if set(raw_by_id) != {row["benchmark_id"] for row in batch}:
            raise ValueError("Semantic response benchmark IDs do not match batch")
        normalized = []
        for item in batch:
            row = raw_by_id[item["benchmark_id"]]
            sense_id = str(row.get("sense_id") or OTHER)
            confidence = str(row.get("confidence") or "low").lower()
            allowed = {sense["sense_id"] for sense in by_id[item["benchmark_id"]]["allowed_senses"]}
            if sense_id != OTHER and sense_id not in allowed:
                raise ValueError(f"Invalid sense {sense_id} for {item['benchmark_id']}")
            if confidence not in {"high", "medium", "low"}:
                raise ValueError(f"Invalid confidence for {item['benchmark_id']}")
            normalized.append({
                "benchmark_id": item["benchmark_id"],
                "model": args.model,
                "sense_id": sense_id,
                "confidence": confidence,
                "reason": str(row.get("reason") or "")[:240],
            })
        append_jsonl(output_path, normalized)
        print(f"semantic decisions {len(existing) + start + len(normalized)}/{len(panel)}")


def classification_metrics(panel: list[dict[str, Any]], accepts: dict[str, bool]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for row in panel:
        predicted = bool(accepts.get(row["benchmark_id"], False))
        gold = bool(row["gold_valid_exact_leaf"])
        if predicted and gold:
            tp += 1
        elif predicted and not gold:
            fp += 1
        elif not predicted and not gold:
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
        "passes_95_percent_precision_gate": precision >= 0.95,
    }


def score(args: argparse.Namespace) -> None:
    panel = read_jsonl(args.output_dir / "panel.jsonl")
    alignments = {
        row["benchmark_id"]: row for row in read_jsonl(args.output_dir / "alignments.jsonl")
    }
    semantic_rows = {
        row["benchmark_id"]: row for row in read_jsonl(args.output_dir / "semantic.jsonl")
    }
    predictions: dict[str, dict[str, bool]] = {
        "raw_string_match": {row["benchmark_id"]: True for row in panel},
    }
    method_names = {"inter": "align_intersection", "itermax": "align_itermax", "mwmf": "align_mwmf"}
    for raw_name, label in method_names.items():
        predictions[label] = {
            row["benchmark_id"]: alignments[row["benchmark_id"]]["decision"]["methods"][raw_name]["accept"]
            for row in panel
        }
    predictions["semantic_same_leaf_medium_or_high"] = {
        row["benchmark_id"]: (
            semantic_rows[row["benchmark_id"]]["sense_id"] == row["candidate_sense_id"]
            and semantic_rows[row["benchmark_id"]]["confidence"] in {"high", "medium"}
        ) for row in panel
    }
    predictions["semantic_same_leaf_high"] = {
        row["benchmark_id"]: (
            semantic_rows[row["benchmark_id"]]["sense_id"] == row["candidate_sense_id"]
            and semantic_rows[row["benchmark_id"]]["confidence"] == "high"
        ) for row in panel
    }
    for alignment_label in ("align_intersection", "align_itermax"):
        for semantic_label in ("semantic_same_leaf_medium_or_high", "semantic_same_leaf_high"):
            predictions[f"{alignment_label}_plus_{semantic_label}"] = {
                row["benchmark_id"]: (
                    predictions[alignment_label][row["benchmark_id"]]
                    and predictions[semantic_label][row["benchmark_id"]]
                ) for row in panel
            }
    metrics = {
        label: classification_metrics(panel, accepts)
        for label, accepts in predictions.items()
    }
    best = sorted(
        metrics.items(),
        key=lambda item: (-item[1]["passes_95_percent_precision_gate"], -item[1]["precision"], -item[1]["accepted"]),
    )[0]
    payload = {
        "schema_version": 1,
        "panel_size": len(panel),
        "gold_valid": sum(row["gold_valid_exact_leaf"] for row in panel),
        "gold_invalid": sum(not row["gold_valid_exact_leaf"] for row in panel),
        "metrics": metrics,
        "best_method": best[0],
        "decision": "proceed_to_larger_benchmark" if best[1]["passes_95_percent_precision_gate"] else "reject_before_scaling",
    }
    write_json(args.output_dir / "metrics.json", payload)

    lines = [
        "# Speech alignment + semantic-gate benchmark",
        "",
        f"Fixed panel: {len(panel)} exact-leaf candidates; {payload['gold_valid']} valid and {payload['gold_invalid']} invalid.",
        "",
        "| Method | Accepted | Precision | Recall of valid | Panel coverage | 95% gate |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for label, row in metrics.items():
        lines.append(
            f"| {label} | {row['accepted']} | {row['precision']:.1%} | "
            f"{row['recall_of_valid_candidates']:.1%} | {row['coverage_of_panel']:.1%} | "
            f"{'PASS' if row['passes_95_percent_precision_gate'] else 'fail'} |"
        )
    lines.extend(["", f"Decision: **{payload['decision']}**.", ""])
    (args.output_dir / "headline.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "align", "semantic", "score"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT)
        sub.add_argument("--index", type=Path, default=DEFAULT_INDEX)
        sub.add_argument("--menu", type=Path, default=DEFAULT_MENU)
        sub.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
        if command == "align":
            sub.add_argument("--aligner-model", default="bert")
        if command == "semantic":
            sub.add_argument("--model", default=DEFAULT_MODEL)
            sub.add_argument("--batch-size", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    {"prepare": prepare, "align": align, "semantic": semantic, "score": score}[args.command](args)


if __name__ == "__main__":
    main()
