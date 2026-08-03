#!/usr/bin/env python3
"""Run the full, zero-AI Spanish Speech string-matching audit.

The audit scans the aligned OpenSubtitles corpus once.  A subtitle occurrence is
assigned to a SpanishDict leaf only when the aligned English line contains a
lexical cue that belongs to exactly one leaf for that Spanish surface form.
Everything else abstains.  This deliberately trades recall for auditability.

No model, embedding service, API, or generated sentence is used.  The command
writes only to a new Intermediates run directory and can resume from checkpoints.
It does not modify the active deck or any immutable historical run.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_INDEX = SPANISH / "vocabulary.index.json"
DEFAULT_MENU = SPANISH / "layers" / "sense_menu" / "spanishdict.json"
DEFAULT_CORPUS = SPANISH / "corpora" / "opensubtitles"
DEFAULT_OUTPUT = (
    SPANISH / "Intermediates" / "speech_string_audit" / "2026-08-03_v1"
)
EXPECTED_LINES = 61_434_251
SCHEMA_VERSION = 1

SPANISH_TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
ENGLISH_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
PAREN_RE = re.compile(r"\([^)]*\)")

# Sentence-level matches on these words are too weak to identify which aligned
# Spanish token they translate.  Function-word senses therefore abstain unless
# SpanishDict supplies a longer, distinctive phrase.
WEAK_SINGLE_TOKENS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "he", "her", "him", "his", "i", "if", "in", "is", "it",
    "its", "may", "me", "might", "more", "my", "no", "not", "of",
    "on", "one", "or", "our", "out", "she", "should", "so", "some",
    "than", "that", "the", "their", "them", "there", "these", "they",
    "this", "those", "to", "up", "us", "very", "was", "we", "were",
    "what", "when", "where", "which", "who", "will", "with", "would",
    "you", "your",
})

LEADING_GLOSS_WORDS = frozenset({
    "a", "an", "the", "to", "someone", "somebody", "something", "one",
})

# Small, transparent lookup used only to create literal string variants.  It is
# not a statistical or learned model.
IRREGULAR_FORMS = {
    "be": ("am", "are", "is", "was", "were", "been", "being"),
    "begin": ("began", "begun", "beginning"),
    "break": ("broke", "broken", "breaking"),
    "bring": ("brought", "bringing"),
    "build": ("built", "building"),
    "buy": ("bought", "buying"),
    "catch": ("caught", "catching"),
    "choose": ("chose", "chosen", "choosing"),
    "come": ("came", "coming"),
    "cost": ("cost", "costing"),
    "cut": ("cut", "cutting"),
    "do": ("did", "done", "doing", "does"),
    "draw": ("drew", "drawn", "drawing"),
    "drink": ("drank", "drunk", "drinking"),
    "drive": ("drove", "driven", "driving"),
    "eat": ("ate", "eaten", "eating"),
    "fall": ("fell", "fallen", "falling"),
    "feel": ("felt", "feeling"),
    "find": ("found", "finding"),
    "fly": ("flew", "flown", "flying"),
    "forget": ("forgot", "forgotten", "forgetting"),
    "get": ("got", "gotten", "getting", "gets"),
    "give": ("gave", "given", "giving"),
    "go": ("went", "gone", "going", "goes"),
    "grow": ("grew", "grown", "growing"),
    "have": ("had", "has", "having"),
    "hear": ("heard", "hearing"),
    "hold": ("held", "holding"),
    "keep": ("kept", "keeping"),
    "know": ("knew", "known", "knowing"),
    "lead": ("led", "leading"),
    "leave": ("left", "leaving"),
    "lose": ("lost", "losing"),
    "make": ("made", "making"),
    "mean": ("meant", "meaning"),
    "meet": ("met", "meeting"),
    "pay": ("paid", "paying"),
    "put": ("put", "putting"),
    "read": ("read", "reading"),
    "ride": ("rode", "ridden", "riding"),
    "run": ("ran", "running"),
    "say": ("said", "saying", "says"),
    "see": ("saw", "seen", "seeing"),
    "sell": ("sold", "selling"),
    "send": ("sent", "sending"),
    "show": ("showed", "shown", "showing"),
    "sit": ("sat", "sitting"),
    "speak": ("spoke", "spoken", "speaking"),
    "stand": ("stood", "standing"),
    "take": ("took", "taken", "taking"),
    "teach": ("taught", "teaching"),
    "tell": ("told", "telling"),
    "think": ("thought", "thinking"),
    "throw": ("threw", "thrown", "throwing"),
    "understand": ("understood", "understanding"),
    "wear": ("wore", "worn", "wearing"),
    "win": ("won", "winning"),
    "write": ("wrote", "written", "writing"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temporary.replace(path)


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_tokens(text: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(match.group(0) for match in pattern.finditer(folded))


def split_glosses(translation: str) -> list[str]:
    text = PAREN_RE.sub(" ", translation or "")
    return [part.strip() for part in re.split(r"\s*(?:;|/|,(?=\s))\s*", text) if part.strip()]


def regular_variants(word: str) -> set[str]:
    variants = {word}
    if len(word) < 3:
        return variants | set(IRREGULAR_FORMS.get(word, ()))
    if word.endswith("y") and len(word) > 3 and word[-2] not in "aeiou":
        variants.update({word[:-1] + "ies", word[:-1] + "ied", word[:-1] + "ying"})
    elif word.endswith("e"):
        variants.update({word + "s", word + "d", word[:-1] + "ing"})
    else:
        variants.update({word + "s", word + "ed", word + "ing"})
        if word.endswith(("s", "sh", "ch", "x", "z", "o")):
            variants.add(word + "es")
    variants.update(IRREGULAR_FORMS.get(word, ()))
    return variants


def raw_cues(translation: str) -> set[tuple[str, ...]]:
    cues: set[tuple[str, ...]] = set()
    for gloss in split_glosses(translation):
        tokens = list(normalize_tokens(gloss, ENGLISH_TOKEN_RE))
        while len(tokens) > 1 and tokens[0] in LEADING_GLOSS_WORDS:
            tokens.pop(0)
        if not tokens:
            continue
        cue = tuple(tokens)
        if len(cue) == 1:
            token = cue[0]
            if token in WEAK_SINGLE_TOKENS or len(token) < 2:
                continue
            cues.update((variant,) for variant in regular_variants(token))
        else:
            cues.add(cue)
    return cues


def flatten_menu(menu: dict[str, Any], surfaces: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for surface in sorted(surfaces):
        senses: dict[str, Any] = {}
        for analysis in menu.get(surface) or []:
            headword = analysis.get("headword") or surface
            for sense_id, sense in (analysis.get("senses") or {}).items():
                senses.setdefault(sense_id, {
                    "sense_id": sense_id,
                    "headword": headword,
                    "pos": sense.get("pos"),
                    "translation": sense.get("translation") or "",
                    "context": sense.get("context"),
                    "regions": sense.get("regions") or [],
                })
        if senses:
            result[surface] = senses
    return result


def build_cue_inventory(
    senses_by_surface: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[tuple[str, ...], str]], dict[str, dict[str, list[str]]]]:
    usable: dict[str, dict[tuple[str, ...], str]] = {}
    audit: dict[str, dict[str, list[str]]] = {}
    for surface, senses in senses_by_surface.items():
        owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
        per_sense: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        for sense_id, sense in senses.items():
            for cue in raw_cues(sense["translation"]):
                owners[cue].add(sense_id)
                per_sense[sense_id].add(cue)
        unique = {
            cue: next(iter(sense_ids))
            for cue, sense_ids in owners.items() if len(sense_ids) == 1
        }
        usable[surface] = unique
        audit[surface] = {
            sense_id: [" ".join(cue) for cue in sorted(per_sense[sense_id]) if cue in unique]
            for sense_id in senses
        }
    return usable, audit


def build_surface_matcher(surfaces: set[str]) -> dict[str, list[tuple[tuple[str, ...], str]]]:
    by_first: dict[str, list[tuple[tuple[str, ...], str]]] = defaultdict(list)
    for surface in surfaces:
        tokens = normalize_tokens(surface, SPANISH_TOKEN_RE)
        if tokens:
            by_first[tokens[0]].append((tokens, surface))
    for rows in by_first.values():
        rows.sort(key=lambda row: (-len(row[0]), row[1]))
    return dict(by_first)


def matched_surfaces(
    spanish: str, matcher: dict[str, list[tuple[tuple[str, ...], str]]]
) -> set[str]:
    tokens = normalize_tokens(spanish, SPANISH_TOKEN_RE)
    found: set[str] = set()
    for index, token in enumerate(tokens):
        for form, surface in matcher.get(token, ()):
            if tokens[index:index + len(form)] == form:
                found.add(surface)
    return found


def classify_english(
    english: str,
    senses: dict[str, Any],
    cues: dict[tuple[str, ...], str],
) -> dict[str, Any]:
    tokens = normalize_tokens(english, ENGLISH_TOKEN_RE)
    return classify_english_tokens(tokens, senses, index_cues(cues))


def index_cues(
    cues: dict[tuple[str, ...], str]
) -> dict[str, list[tuple[tuple[str, ...], str]]]:
    by_first: dict[str, list[tuple[tuple[str, ...], str]]] = defaultdict(list)
    for cue, sense_id in cues.items():
        by_first[cue[0]].append((cue, sense_id))
    return dict(by_first)


def classify_english_tokens(
    english_tokens: tuple[str, ...],
    senses: dict[str, Any],
    cues_by_first: dict[str, list[tuple[tuple[str, ...], str]]],
) -> dict[str, Any]:
    if len(senses) == 1:
        return {
            "status": "assigned",
            "sense_id": next(iter(senses)),
            "reason": "only_spanishdict_leaf_for_surface",
            "matched_cues": [],
        }
    token_set = set(english_tokens)
    matches: dict[str, list[str]] = defaultdict(list)
    padded = " " + " ".join(english_tokens) + " "
    for first in token_set.intersection(cues_by_first):
        for cue, sense_id in cues_by_first[first]:
            phrase = " " + " ".join(cue) + " "
            if phrase in padded:
                matches[sense_id].append(" ".join(cue))
    if not matches:
        return {"status": "abstain", "reason": "no_unique_english_cue"}
    if len(matches) > 1:
        return {
            "status": "abstain",
            "reason": "conflicting_unique_english_cues",
            "candidate_sense_ids": sorted(matches),
            "matched_cues": dict(matches),
        }
    sense_id, matched = next(iter(matches.items()))
    return {
        "status": "assigned",
        "sense_id": sense_id,
        "reason": "unique_english_cue",
        "matched_cues": sorted(matched),
    }


def sample_priority(seed: int, key: str, line_number: int) -> int:
    material = f"{seed}|{key}|{line_number}".encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:16], 16)


def retain_sample(
    samples: dict[str, list[dict[str, Any]]],
    key: str,
    record: dict[str, Any],
    limit: int,
    seed: int,
) -> None:
    if limit <= 0:
        return
    candidate = {**record, "_priority": sample_priority(seed, key, record["corpus_line"])}
    rows = samples.setdefault(key, [])
    rows.append(candidate)
    rows.sort(key=lambda row: row["_priority"])
    del rows[limit:]


def source_record(raw: str) -> dict[str, Any]:
    fields = raw.split("\t")
    return {
        "alignment_ids": raw,
        "english_document": fields[0] if len(fields) > 0 else None,
        "spanish_document": fields[1] if len(fields) > 1 else None,
        "english_segment": fields[2] if len(fields) > 2 else None,
        "spanish_segment": fields[3] if len(fields) > 3 else None,
    }


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "line_number": 0,
        "offsets": {"spanish": 0, "english": 0, "ids": 0},
        "surface_total": {},
        "surface_assigned": {},
        "surface_abstentions": {},
        "sense_counts": {},
        "samples": {},
        "checkpointed_at": None,
    }


def progress_line(
    line_number: int, started: float, start_line: int, assigned: int, total: int
) -> str:
    fraction = min(1.0, line_number / EXPECTED_LINES)
    width = 28
    filled = int(width * fraction)
    bar = "=" * filled + (">" if filled < width else "") + "." * max(0, width - filled - 1)
    elapsed = max(time.monotonic() - started, 0.001)
    rate = max((line_number - start_line) / elapsed, 0.001)
    remaining = max(EXPECTED_LINES - line_number, 0) / rate
    eta = time.strftime("%H:%M:%S", time.gmtime(remaining))
    coverage = assigned / total if total else 0.0
    return (
        f"[{bar}] {fraction:6.2%}  {line_number:,}/{EXPECTED_LINES:,} lines  "
        f"{rate:,.0f} lines/s  ETA {eta}  assigned {coverage:.1%}"
    )


def checkpoint(path: Path, state: dict[str, Any]) -> None:
    state["checkpointed_at"] = utc_now()
    atomic_json(path, state)


def scan(args: argparse.Namespace) -> None:
    paths = {
        "spanish": args.corpus_dir / "OpenSubtitles.en-es.es",
        "english": args.corpus_dir / "OpenSubtitles.en-es.en",
        "ids": args.corpus_dir / "OpenSubtitles.en-es.ids",
    }
    for path in [args.index, args.menu, *paths.values()]:
        if not path.is_file():
            raise FileNotFoundError(path)

    if args.output_dir.exists() and not args.resume:
        raise FileExistsError(
            f"Output exists; use --resume or choose a new --output-dir: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.output_dir / "checkpoint.json"
    state = read_json(checkpoint_path) if args.resume and checkpoint_path.is_file() else empty_state()
    if state.get("completed_at"):
        print(f"Audit is already complete: {args.output_dir}")
        return

    index = read_json(args.index)
    menu = read_json(args.menu)
    app_surfaces = {str(row.get("word") or "").casefold() for row in index if row.get("word")}
    senses_by_surface = flatten_menu(menu, app_surfaces)
    cue_inventory, cue_audit = build_cue_inventory(senses_by_surface)
    cues_by_surface = {
        surface: index_cues(cues) for surface, cues in cue_inventory.items()
    }
    matcher = build_surface_matcher(set(senses_by_surface))

    surface_total = Counter(state["surface_total"])
    surface_assigned = Counter(state["surface_assigned"])
    abstentions = Counter(state["surface_abstentions"])
    sense_counts = Counter(state["sense_counts"])
    samples: dict[str, list[dict[str, Any]]] = state["samples"]
    start_line = int(state["line_number"])
    started = time.monotonic()

    print(
        f"Spanish Speech string audit: {len(app_surfaces):,} app surfaces; "
        f"{len(senses_by_surface):,} with SpanishDict; "
        f"{sum(len(v) for v in senses_by_surface.values()):,} stable leaves",
        flush=True,
    )
    print("No API or model will be called. Ctrl-C is safe; rerun with --resume.", flush=True)

    with (
        paths["spanish"].open(encoding="utf-8", errors="replace") as spanish_handle,
        paths["english"].open(encoding="utf-8", errors="replace") as english_handle,
        paths["ids"].open(encoding="utf-8", errors="replace") as ids_handle,
    ):
        if start_line:
            spanish_handle.seek(int(state["offsets"]["spanish"]))
            english_handle.seek(int(state["offsets"]["english"]))
            ids_handle.seek(int(state["offsets"]["ids"]))
        line_number = start_line
        try:
            while True:
                spanish = spanish_handle.readline()
                english = english_handle.readline()
                source_ids = ids_handle.readline()
                if not spanish or not english or not source_ids:
                    break
                line_number += 1
                spanish = spanish.rstrip("\r\n")
                english = english.rstrip("\r\n")
                source_ids = source_ids.rstrip("\r\n")
                surfaces = matched_surfaces(spanish, matcher)
                english_tokens = (
                    normalize_tokens(english, ENGLISH_TOKEN_RE) if surfaces else ()
                )
                for surface in surfaces:
                    surface_total[surface] += 1
                    decision = classify_english_tokens(
                        english_tokens, senses_by_surface[surface], cues_by_surface[surface]
                    )
                    record = {
                        "corpus_line": line_number,
                        "surface": surface,
                        "spanish": spanish,
                        "english": english,
                        "source": source_record(source_ids),
                        "decision": decision,
                    }
                    if decision["status"] == "assigned":
                        sense_id = decision["sense_id"]
                        surface_assigned[surface] += 1
                        sense_counts[f"{surface}\t{sense_id}"] += 1
                        retain_sample(
                            samples, f"assigned\t{surface}\t{sense_id}", record,
                            args.examples_per_sense, args.seed,
                        )
                    else:
                        reason = decision["reason"]
                        abstentions[f"{surface}\t{reason}"] += 1
                        retain_sample(
                            samples, f"abstain\t{surface}\t{reason}", record,
                            args.abstentions_per_surface, args.seed,
                        )

                if line_number % args.progress_every == 0:
                    print(
                        "\r" + progress_line(
                            line_number, started, start_line,
                            sum(surface_assigned.values()), sum(surface_total.values()),
                        ), end="", flush=True,
                    )
                if line_number % args.checkpoint_every == 0:
                    state.update({
                        "line_number": line_number,
                        "offsets": {
                            "spanish": spanish_handle.tell(),
                            "english": english_handle.tell(),
                            "ids": ids_handle.tell(),
                        },
                        "surface_total": dict(surface_total),
                        "surface_assigned": dict(surface_assigned),
                        "surface_abstentions": dict(abstentions),
                        "sense_counts": dict(sense_counts),
                        "samples": samples,
                    })
                    checkpoint(checkpoint_path, state)
                if args.max_lines and line_number - start_line >= args.max_lines:
                    state.update({
                        "line_number": line_number,
                        "offsets": {
                            "spanish": spanish_handle.tell(),
                            "english": english_handle.tell(),
                            "ids": ids_handle.tell(),
                        },
                        "surface_total": dict(surface_total),
                        "surface_assigned": dict(surface_assigned),
                        "surface_abstentions": dict(abstentions),
                        "sense_counts": dict(sense_counts),
                        "samples": samples,
                    })
                    checkpoint(checkpoint_path, state)
                    print(
                        f"\nPaused after {args.max_lines:,} lines for this invocation; "
                        "continue with --resume."
                    )
                    return
        except KeyboardInterrupt:
            state.update({
                "line_number": line_number,
                "offsets": {
                    "spanish": spanish_handle.tell(),
                    "english": english_handle.tell(),
                    "ids": ids_handle.tell(),
                },
                "surface_total": dict(surface_total),
                "surface_assigned": dict(surface_assigned),
                "surface_abstentions": dict(abstentions),
                "sense_counts": dict(sense_counts),
                "samples": samples,
            })
            checkpoint(checkpoint_path, state)
            print(f"\nCheckpoint saved at line {line_number:,}. Resume with --resume.")
            return

        final_offsets = {
            "spanish": spanish_handle.tell(),
            "english": english_handle.tell(),
            "ids": ids_handle.tell(),
        }

    print("\r" + progress_line(
        line_number, started, start_line,
        sum(surface_assigned.values()), sum(surface_total.values()),
    ))
    state.update({
        "line_number": line_number,
        "offsets": final_offsets,
        "surface_total": dict(surface_total),
        "surface_assigned": dict(surface_assigned),
        "surface_abstentions": dict(abstentions),
        "sense_counts": dict(sense_counts),
        "samples": samples,
        "completed_at": utc_now(),
    })
    checkpoint(checkpoint_path, state)
    finalize(
        args, index, senses_by_surface, cue_audit, state,
        missing_surfaces=sorted(app_surfaces - set(senses_by_surface)),
    )


def finalize(
    args: argparse.Namespace,
    index: list[dict[str, Any]],
    senses_by_surface: dict[str, dict[str, Any]],
    cue_audit: dict[str, dict[str, list[str]]],
    state: dict[str, Any],
    missing_surfaces: list[str],
) -> None:
    totals = Counter(state["surface_total"])
    assigned = Counter(state["surface_assigned"])
    abstentions = Counter(state["surface_abstentions"])
    counts = Counter(state["sense_counts"])
    samples = state["samples"]

    surface_rows = []
    sense_rows = []
    for surface, senses in sorted(senses_by_surface.items()):
        total = totals[surface]
        accepted = assigned[surface]
        no_cue = abstentions[f"{surface}\tno_unique_english_cue"]
        conflict = abstentions[f"{surface}\tconflicting_unique_english_cues"]
        surfaced = 0
        for sense_id, sense in senses.items():
            count = counts[f"{surface}\t{sense_id}"]
            if count:
                surfaced += 1
            sense_rows.append({
                "surface": surface,
                **sense,
                "usable_cues": cue_audit[surface].get(sense_id, []),
                "assigned_occurrences": count,
                "share_of_all_surface_occurrences": round(count / total, 8) if total else 0.0,
                "share_of_assigned_occurrences": round(count / accepted, 8) if accepted else 0.0,
            })
        surface_rows.append({
            "surface": surface,
            "spanishdict_senses": len(senses),
            "senses_with_unique_cues": sum(bool(cue_audit[surface].get(sid)) for sid in senses),
            "senses_observed": surfaced,
            "matching_corpus_lines": total,
            "assigned": accepted,
            "assignment_coverage": round(accepted / total, 8) if total else 0.0,
            "abstain_no_unique_cue": no_cue,
            "abstain_conflicting_cues": conflict,
        })

    sample_rows = []
    for key, rows in sorted(samples.items()):
        for row in rows:
            sample_rows.append({k: v for k, v in row.items() if k != "_priority"})
    write_jsonl(args.output_dir / "surface_summary.jsonl", surface_rows)
    write_jsonl(args.output_dir / "sense_summary.jsonl", sense_rows)
    write_jsonl(args.output_dir / "audit_samples.jsonl", sample_rows)

    total_matches = sum(totals.values())
    total_assigned = sum(assigned.values())
    cue_senses = sum(
        bool(cues) for surface in cue_audit.values() for cues in surface.values()
    )
    observed_senses = sum(row["assigned_occurrences"] > 0 for row in sense_rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.output_dir.name,
        "status": "complete_string_audit",
        "completed_at": utc_now(),
        "method": {
            "classifier": "deterministic unique English lexical cue",
            "ai_or_model_calls": 0,
            "denominator": "all aligned corpus lines containing the exact Spanish app surface",
            "abstention": "no unique cue or conflicting unique cues",
            "sampling": "none for counts; deterministic bounded samples retained only for audit",
        },
        "inputs": {
            "index": {"path": str(args.index.relative_to(ROOT)), "sha256": sha256(args.index)},
            "sense_menu": {"path": str(args.menu.relative_to(ROOT)), "sha256": sha256(args.menu)},
            "corpus": str(args.corpus_dir.relative_to(ROOT)),
        },
        "metrics": {
            "app_cards": len(index),
            "app_surfaces": len({row.get("word") for row in index}),
            "spanishdict_surfaces": len(senses_by_surface),
            "missing_spanishdict_surfaces": len(missing_surfaces),
            "spanishdict_senses": len(sense_rows),
            "senses_with_unique_cues": cue_senses,
            "senses_observed": observed_senses,
            "aligned_lines_scanned": state["line_number"],
            "matched_surface_lines": total_matches,
            "assigned_surface_lines": total_assigned,
            "assignment_coverage": round(total_assigned / total_matches, 8) if total_matches else 0.0,
            "audit_samples": len(sample_rows),
        },
        "missing_spanishdict_surfaces": missing_surfaces,
        "limitations": [
            "Sentence-level bilingual alignment is not word alignment.",
            "Exact lexical cues favour senses whose English gloss appears literally.",
            "Translation-equivalent SpanishDict leaves intentionally receive no shared cue.",
            "Counts are raw lexical-cue matches, not validated lower bounds or prominence percentages.",
            "The completed audit does not modify or activate an app deck.",
        ],
    }
    write_json(args.output_dir / "manifest.json", manifest)

    strongest = sorted(
        (row for row in surface_rows if row["matching_corpus_lines"] >= 20),
        key=lambda row: (-row["assignment_coverage"], -row["matching_corpus_lines"]),
    )[:20]
    weakest = sorted(
        (row for row in surface_rows if row["matching_corpus_lines"] >= 20),
        key=lambda row: (row["assignment_coverage"], -row["matching_corpus_lines"]),
    )[:20]
    lines = [
        "# Spanish Speech string-matching audit",
        "",
        f"Scanned **{state['line_number']:,}** aligned subtitle lines with **zero AI/model calls**.",
        f"Assigned **{total_assigned:,} / {total_matches:,}** matched surface lines "
        f"(**{(total_assigned / total_matches if total_matches else 0):.1%}** coverage).",
        f"Observed **{observed_senses:,}** SpanishDict leaves through unique English cues.",
        "",
        "These are auditable lexical-cue matches, not validated sense counts. Sentence alignment is not word alignment, so precision must be established before any prominence use.",
        "",
        "## Highest-coverage surfaces (minimum 20 matches)",
        "",
        "| Surface | Lines | Assigned | Coverage | Senses observed/menu |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in strongest:
        lines.append(
            f"| {row['surface']} | {row['matching_corpus_lines']:,} | {row['assigned']:,} | "
            f"{row['assignment_coverage']:.1%} | {row['senses_observed']}/{row['spanishdict_senses']} |"
        )
    lines.extend([
        "",
        "## Lowest-coverage surfaces (minimum 20 matches)",
        "",
        "| Surface | Lines | Assigned | Coverage | Senses observed/menu |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in weakest:
        lines.append(
            f"| {row['surface']} | {row['matching_corpus_lines']:,} | {row['assigned']:,} | "
            f"{row['assignment_coverage']:.1%} | {row['senses_observed']}/{row['spanishdict_senses']} |"
        )
    (args.output_dir / "headline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Audit complete: {args.output_dir}")
    print(f"Headline: {args.output_dir / 'headline.md'}")


def plan(args: argparse.Namespace) -> None:
    index = read_json(args.index)
    menu = read_json(args.menu)
    surfaces = {str(row.get("word") or "").casefold() for row in index if row.get("word")}
    senses = flatten_menu(menu, surfaces)
    _, cue_audit = build_cue_inventory(senses)
    print(f"App cards: {len(index):,}")
    print(f"App surfaces: {len(surfaces):,}")
    print(f"SpanishDict-covered surfaces: {len(senses):,}")
    print(f"SpanishDict stable leaves: {sum(len(rows) for rows in senses.values()):,}")
    print(f"Leaves with at least one unique literal cue: {sum(bool(c) for rows in cue_audit.values() for c in rows.values()):,}")
    print(f"Corpus lines to scan: {EXPECTED_LINES:,}")
    print("AI/model/API calls: 0")
    print(f"Output directory: {args.output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "run"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--index", type=Path, default=DEFAULT_INDEX)
        sub.add_argument("--menu", type=Path, default=DEFAULT_MENU)
        sub.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
        sub.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
        if command == "run":
            sub.add_argument("--resume", action="store_true")
            sub.add_argument("--seed", type=int, default=20260803)
            sub.add_argument("--examples-per-sense", type=int, default=3)
            sub.add_argument("--abstentions-per-surface", type=int, default=3)
            sub.add_argument("--progress-every", type=int, default=250_000)
            sub.add_argument("--checkpoint-every", type=int, default=2_000_000)
            sub.add_argument(
                "--max-lines", type=int, default=0,
                help="Pause after N additional lines (0 means scan to completion)",
            )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "plan":
        plan(args)
    else:
        scan(args)


if __name__ == "__main__":
    main()
