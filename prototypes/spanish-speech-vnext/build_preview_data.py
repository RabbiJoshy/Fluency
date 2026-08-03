#!/usr/bin/env python3
"""Export the v0.1 Speech evidence run into a small, static preview payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = (
    REPO_ROOT
    / "Data/Spanish/Intermediates/speech_mode_evidence/runs/2026-08-03_v0_1"
)
DEFAULT_OUTPUT = Path(__file__).with_name("preview-data.js")
SPEECH_VNEXT_RUN_ID = "2026-08-03_pilot_v0_1"
DEFAULT_DECK_OUTPUT = (
    REPO_ROOT / "Data/Spanish/runs/speech_vnext" / SPEECH_VNEXT_RUN_ID / "deck.json"
)
LEGACY_WORD_IDS = {
    "banco": "2232e7",
    "cola": "612fad",
    "cura": "d2a3bd",
    "sierra": "03102e",
}

# These are deliberately visible in Evidence view. They demonstrate why a high-confidence
# model response is still only a candidate until a person (or stronger review stage) accepts it.
MANUAL_REVIEW = {
    "Quizás prefieras que te patee la cola.": {
        "status": "known_mismatch",
        "note": "Figurative threat: this is not the animal-anatomy sense shown by SpanishDict.",
    },
    "-Concepción, ven y brilla mi cola.": {
        "status": "needs_review",
        "note": "Context is too thin to publish confidently.",
    },
    "¡Mi cola está ardiendo!": {
        "status": "needs_review",
        "note": "Likely slang/body usage rather than a literal animal tail.",
    },
}

WORD_NOTES = {
    "banco": {
        "verdict": "clean_signal",
        "headline": "A clean first-pass result",
        "detail": "All 25 sampled uses received a high-confidence unique sense, strongly favoring the financial sense.",
    },
    "cola": {
        "verdict": "known_risk",
        "headline": "Useful counts, unsafe examples",
        "detail": "The broad tail-versus-line split is plausible, but several figurative body uses were confidently attached to the literal tail sense.",
    },
    "cura": {
        "verdict": "clean_signal",
        "headline": "Two genuinely common senses",
        "detail": "The noun sample splits evenly between priest and cure; verb-shaped uses were allowed to abstain.",
    },
    "sierra": {
        "verdict": "insufficient",
        "headline": "Not enough usable evidence",
        "detail": "Only 14 of 25 random occurrences passed the gate, so the prominence labels should not be published yet.",
    },
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def relative_source(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def build_payload(run_dir: Path) -> dict:
    summary = json.loads((run_dir / "summary.json").read_text())
    candidates = read_jsonl(run_dir / "example_bank.jsonl")
    by_sense: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for row in candidates:
        review = MANUAL_REVIEW.get(row["spanish"], {"status": "unaudited"})
        by_sense[(row["target_id"], row["sense_id"])].append(
            {
                "id": row["example_id"],
                "spanish": row["spanish"],
                "english": row["english"],
                "modelConfidence": row["assignment"]["decision"]["confidence"],
                "modelReason": row["assignment"]["decision"]["reason"],
                "review": review,
                "source": {
                    "corpus": row["source"]["corpus"],
                    "corpusLine": row["source"]["corpus_line"],
                    "spanishDocument": row["source"]["spanish_document"],
                    "spanishSegment": row["source"]["spanish_segment"],
                },
            }
        )

    words = []
    for target in summary["targets"]:
        senses = []
        for sense in target["senses"]:
            examples = by_sense[(target["target_id"], sense["sense_id"])]
            # Keep the known failures visible, then use the earliest remaining sampled records.
            examples.sort(
                key=lambda example: (
                    0 if example["review"]["status"] != "unaudited" else 1,
                    example["source"]["corpusLine"],
                )
            )
            canonical = sense["spanishdict_examples"][0] if sense["spanishdict_examples"] else None
            senses.append(
                {
                    "id": sense["sense_id"],
                    "translation": sense["translation"],
                    "context": sense["context"],
                    "regions": sense["regions"],
                    "prominence": sense["provisional_prominence"],
                    "acceptedCount": sense["accepted_random_occurrences"],
                    "shareOfSample": sense["share_of_all_sampled_occurrences"],
                    "canonicalExample": canonical,
                    "corpusCandidates": examples[:4],
                }
            )

        important = [sense for sense in senses if sense["acceptedCount"] > 0]
        other = [sense for sense in senses if sense["acceptedCount"] == 0]
        words.append(
            {
                "id": target["target_id"],
                "surface": target["surface"],
                "headword": target["headword"],
                "pos": target["pos"],
                "spanishDictUrl": f"https://www.spanishdict.com/translate/{target['surface']}",
                "sampled": target["sampled_occurrences"],
                "accepted": target["accepted_unique_high"],
                "coverage": target["accepted_coverage"],
                "abstained": target["explicit_abstentions"],
                "belowGate": target["ambiguous_or_below_gate"],
                "prominenceStatus": target["prominence_status"],
                "note": WORD_NOTES[target["surface"]],
                "importantSenses": important,
                "otherSenses": other,
            }
        )

    return {
        "schemaVersion": 1,
        "prototype": True,
        "generatedAt": summary["generated_at"],
        "sourceRun": relative_source(run_dir),
        "method": {
            "senseAuthority": "SpanishDict stable leaf sense IDs",
            "prominence": "25 seeded random OpenSubtitles occurrences per word; high-confidence unique assignments only",
            "canonicalExamples": "SpanishDict examples already attached to each leaf sense",
            "corpusExamples": "Model-matched candidates requiring independent audit",
        },
        "words": words,
    }


def build_speech_vnext_deck(preview: dict) -> dict:
    words = []
    for word in preview["words"]:
        selected_ids = {sense["id"] for sense in word["importantSenses"]}
        dictionary_senses = []
        for sense in [*word["importantSenses"], *word["otherSenses"]]:
            dictionary_senses.append(
                {
                    "sense_id": sense["id"],
                    "pos": word["pos"],
                    "translation": sense["translation"],
                    "context": sense["context"],
                    "regions": sense["regions"],
                    "display": sense["id"] in selected_ids,
                    "prominence": sense["prominence"],
                    "observed_count": sense["acceptedCount"],
                    "share_of_sample": sense["shareOfSample"],
                    "canonical_examples": [sense["canonicalExample"]]
                    if sense["canonicalExample"]
                    else [],
                }
            )
        words.append(
            {
                "legacy_word_id": LEGACY_WORD_IDS[word["surface"]],
                "surface": word["surface"],
                "lemma": word["headword"],
                "pos": word["pos"],
                "sample": {
                    "total": word["sampled"],
                    "accepted": word["accepted"],
                    "coverage": word["coverage"],
                    "abstained": word["abstained"],
                    "below_gate": word["belowGate"],
                },
                "publication": {
                    "status": word["note"]["verdict"],
                    "headline": word["note"]["headline"],
                    "detail": word["note"]["detail"],
                },
                "dictionary_senses": dictionary_senses,
            }
        )

    return {
        "schema_version": 1,
        "architecture": "spanish_speech_vnext",
        "run_id": SPEECH_VNEXT_RUN_ID,
        "status": "candidate_default_four_word_pilot",
        "immutable_after_review": True,
        "generated_at": preview["generatedAt"],
        "product_contract": {
            "sense_authority": "SpanishDict stable leaf sense IDs",
            "sense_selection": "Display senses with accepted evidence; audit before publishing at scale",
            "prominence": "Broad labels derived from random-use evidence; numeric shares retained only for audit",
            "examples": "SpanishDict exact sense-tied examples only",
            "personalisation": "Out of scope; downstream export can use missed stable sense IDs later",
        },
        "legacy_compatibility": {
            "default_app_unchanged": True,
            "legacy_candidate_run": "Data/Spanish/runs/normal_mode/2026-08-03_spanishdict_examples_v2",
            "legacy_app_index": "Data/Spanish/vocabulary.index.json",
            "legacy_app_examples": "Data/Spanish/vocabulary.examples.json",
            "portable_fields": [
                "legacy_word_id",
                "SpanishDict sense_id",
                "translation",
                "context",
                "canonical SpanishDict example",
            ],
            "not_adopted_as_vnext_truth": [
                "legacy numeric sense distributions",
                "personalised generated frames",
                "unaudited corpus-to-sense attachments",
            ],
        },
        "evidence": {
            "source_run": preview["sourceRun"],
            "corpus_candidates_location": (
                f"{preview['sourceRun']}/example_bank.jsonl"
            ),
            "corpus_candidates_in_learner_deck": False,
        },
        "words": words,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--deck-output", type=Path, default=DEFAULT_DECK_OUTPUT)
    args = parser.parse_args()

    payload = build_payload(args.run_dir.resolve())
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    args.output.write_text(f"window.SPEECH_PREVIEW_DATA = {serialized};\n")
    args.deck_output.parent.mkdir(parents=True, exist_ok=True)
    deck = build_speech_vnext_deck(payload)
    deck_bytes = (json.dumps(deck, ensure_ascii=False, indent=2) + "\n").encode()
    args.deck_output.write_bytes(deck_bytes)
    manifest = {
        "schema_version": 1,
        "run_id": SPEECH_VNEXT_RUN_ID,
        "architecture": "spanish_speech_vnext",
        "immutable_after_review": True,
        "deck": {
            "path": args.deck_output.name,
            "bytes": len(deck_bytes),
            "sha256": hashlib.sha256(deck_bytes).hexdigest(),
        },
        "source_evidence_run": payload["sourceRun"],
        "legacy_fallback": "Data/Spanish/runs/normal_mode/2026-08-03_spanishdict_examples_v2",
    }
    manifest_path = args.deck_output.with_name("manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(
        f"Wrote {args.output}, {args.deck_output}, and {manifest_path} "
        f"({len(payload['words'])} words)"
    )


if __name__ == "__main__":
    main()
