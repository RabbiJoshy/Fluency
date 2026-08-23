#!/usr/bin/env python3
"""tool_5d_build_merged_mwes — one MWE inventory, ranked by what actually occurs.

Multiword expressions are not primarily a disambiguation aid. `así que` = "so",
`tal vez` = "maybe", `de vez en cuando` = "once in a while" are vocabulary a
learner needs in their own right; helping the classifier is a side effect. This
tool builds the inventory as CONTENT, and whatever the classifier gets from it
is a bonus.

## Why both sources, and why SpanishDict leads

SpanishDict's phrase list is curated for learners and is roughly ten times
richer per word than Wiktionary's:

    nuevo    SD 18 (de nuevo, año nuevo, algo nuevo)      WK 1
    importa  SD 15 (no me importa = I don't care)         WK 1
    así      SD 18 (así que = so, aun así = even so)      WK 5

3,528 expressions are SpanishDict-only against 399 Wiktionary-only -- but those
399 are real gaps (`pronto` has none in SD and three in WK, including
`de pronto`), so this unions rather than replaces.

## Why the corpus pass is the whole point

SpanishDict's `phrases` component also carries translation-drill fragments that
are worthless as cards: `yo nací ayer`, `nací el`, `en qué año naciste`. They
cannot be filtered by shape -- they look like phrases. But they do not occur:

    2298  lo que      = what               7  nací en
     491  así que     = so                 4  yo nací
     453  tal vez     = maybe              0  yo no nací ayer
     365  para que    = so that            0  en qué año naciste

Measured on 84k sentences, **69% of shape-passing SpanishDict phrases occur zero
times**. That is the junk, and it identifies itself. This tool counts against
the full 61M-line OpenSubtitles dump instead of a sample.

## The two tiers, which the schema exists to distinguish

A card shows EXAMPLES, and examples are sampled from a corpus. So an MWE meaning
can only be shown *with evidence* if a sentence containing it was harvested:

  - `corpus_freq > 0` with examples  -> can carry an example, can be sense-assigned
  - `corpus_freq == 0`               -> still teachable content, but no sentence
                                        to attach; belongs on a reference card,
                                        never in an example slot

Do not collapse these. The second tier is real learner value and it is exactly
the tier that cannot be validated against a sentence.

## Output

`Data/Spanish/layers/mwe_merged.json`:

    {"meta": {...},
     "mwes": {"de nuevo": {"translations": [...], "sources": [...],
                           "attach_words": [...], "corpus_freq": 1234,
                           "examples": [{"es": ..., "en": ..., "line": N}]}}}

Resumable: checkpoints every `--checkpoint-lines`. Re-running continues from the
last checkpoint unless `--restart`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = ROOT / "Data" / "Spanish" / "layers"
SENSES = ROOT / "Data" / "Spanish" / "Senses" / "spanishdict"
CORPUS = ROOT / "Data" / "Spanish" / "corpora" / "opensubtitles"

DEFAULT_OUT = LAYERS / "mwe_merged.json"
DEFAULT_CKPT = LAYERS / ".mwe_merged.checkpoint.json"

PUNCT = re.compile(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]+")
SENTENCE_PUNCT = re.compile(r"[¿?¡!.]")
MIN_WORDS, MAX_WORDS = 2, 5

# Spanish normally drops the subject pronoun, so an explicit one at the front
# marks a SpanishDict search suggestion rather than an idiom: `yo nací`,
# `él come`, `yo nací en`. Neither the shape gate nor the corpus pass catches
# these -- they look like phrases AND they occur -- so this is the one quality
# rule that has to be lexical.
#
# The exception is a pronoun followed by a subordinator, which is how the real
# ones are built: `yo que tú` (if I were you), `yo qué sé` (how should I know).
SUBJECT_PRONOUNS = {"yo", "tú", "tu", "él", "el", "ella", "usted", "ustedes",
                    "nosotros", "nosotras", "vosotros", "ellos", "ellas"}
SUBORDINATORS = {"que", "qué", "quien", "quién", "como", "cómo", "mismo",
                 "misma", "mismos", "mismas"}

# Wiktionary translations are sometimes prose rather than a gloss, and
# sometimes an English-borrowing note: `a la` -> "a la; in the style or manner
# of". SpanishDict does not do this, which is one more reason it leads.
PROSE = re.compile(r"alternative form|inflection of|plural of|see also"
                   r"|^used to (indicate|express|show|refer)", re.I)


def norm(text) -> str:
    return (text or "").strip().lower()


def flatten(text: str) -> str:
    return PUNCT.sub(" ", (text or "").lower())


def clean_translation(value, expression=None):
    """A usable English gloss, or None.

    Drops segments that merely restate the Spanish -- Wiktionary glosses the
    borrowing `a la` as "a la; in the style or manner of", whose first segment
    teaches nothing.
    """
    value = re.sub(r"\(.*?\)", "", value or "").strip()
    if not value or PROSE.search(value):
        return None
    if expression:
        parts = [p.strip() for p in re.split(r"[;]", value)
                 if p.strip() and norm(p) != norm(expression)]
        value = "; ".join(parts)
    return value or None


def teachable(expression: str) -> bool:
    """Shape gate. Rejects sentences and single words; keeps 2-5 word phrases.

    Deliberately NOT a quality gate -- `yo nací ayer` passes this and is junk.
    Quality is decided by the corpus pass, which is the only thing that can tell
    a phrase from a drill fragment.
    """
    expression = expression.strip()
    if SENTENCE_PUNCT.search(expression):
        return False
    tokens = expression.split()
    if not (MIN_WORDS <= len(tokens) <= MAX_WORDS):
        return False
    if (tokens[0].lower() in SUBJECT_PRONOUNS
            and tokens[1].lower() not in SUBORDINATORS):
        return False
    return True


# --------------------------------------------------------------------------
# candidates
# --------------------------------------------------------------------------

def load_candidates(verbose=True):
    """Union of both sources, keyed by normalised expression."""
    out = defaultdict(lambda: {"translations": [], "sources": set(),
                               "attach_words": set()})

    # `phrases_cache.json` holds BOTH directions -- it is keyed by headword in
    # either language, so `play` -> "tocar un instrumento" sits beside
    # `nuevo` -> "de nuevo". Ingesting the English half puts English strings in
    # a Spanish inventory: `a la` entered as "in the style or manner of" and
    # then matched 5,235 Spanish lines. Keying against the Spanish sense menu is
    # the direction test.
    spanish_keys = set()
    menu_path = LAYERS / "sense_menu" / "spanishdict.json"
    if menu_path.exists():
        spanish_keys = {norm(k) for k in
                        json.loads(menu_path.read_text(encoding="utf-8"))}

    sd_path = SENSES / "phrases_cache.json"
    if sd_path.exists():
        sd = json.loads(sd_path.read_text(encoding="utf-8"))
        skipped = 0
        for word, entries in sd.items():
            if spanish_keys and norm(word) not in spanish_keys:
                skipped += 1
                continue
            for entry in entries:
                expression = norm(entry.get("expression"))
                if not expression or not teachable(expression):
                    continue
                translation = clean_translation(entry.get("translation"), expression)
                if not translation:
                    continue
                row = out[expression]
                if translation not in row["translations"]:
                    row["translations"].insert(0, translation)   # SD gloss leads
                row["sources"].add("spanishdict")
                row["attach_words"].add(norm(word))
        if verbose:
            print(f"  spanishdict: {len(out):,} expressions "
                  f"({skipped:,} non-Spanish keys skipped)")

    before = len(out)
    wk_path = LAYERS / "mwe_phrases.json"
    if wk_path.exists():
        wk = json.loads(wk_path.read_text(encoding="utf-8"))
        for word, entries in wk.items():
            for entry in entries:
                expression = norm(entry.get("expression"))
                if not expression or not teachable(expression):
                    continue
                translation = clean_translation(entry.get("translation"), expression)
                if not translation:
                    continue
                row = out[expression]
                if translation not in row["translations"]:
                    row["translations"].append(translation)
                row["sources"].add("wiktionary")
                row["attach_words"].add(norm(word))
        if verbose:
            print(f"  + wiktionary: {len(out) - before:,} new, {len(out):,} total")
    return dict(out)


# --------------------------------------------------------------------------
# corpus pass
# --------------------------------------------------------------------------

def ngrams(tokens, lo=MIN_WORDS, hi=MAX_WORDS):
    for size in range(lo, hi + 1):
        for i in range(len(tokens) - size + 1):
            yield " ".join(tokens[i:i + size])


def scan(candidates, *, max_lines, examples_per_mwe, checkpoint_lines,
         checkpoint_path, restart):
    """One pass over the aligned dump. Counts hits and harvests examples.

    n-gram lookup rather than substring search: 10k phrases x 61M lines of
    `in` tests is not finishable, but hashing each line's 2-5 word n-grams is
    linear in the line.
    """
    es_path = CORPUS / "OpenSubtitles.en-es.es"
    en_path = CORPUS / "OpenSubtitles.en-es.en"
    if not es_path.exists():
        sys.exit(f"corpus not found: {es_path}")

    keys = set(candidates)
    counts = defaultdict(int)
    examples = defaultdict(list)
    start_line = 0

    if checkpoint_path.exists() and not restart:
        state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        counts.update(state["counts"])
        for k, v in state["examples"].items():
            examples[k] = v
        start_line = state["line"]
        print(f"  resuming from line {start_line:,}")

    have_en = en_path.exists()
    t0 = time.time()
    with es_path.open(encoding="utf-8", errors="replace") as es_f:
        en_f = en_path.open(encoding="utf-8", errors="replace") if have_en else None
        try:
            for line_no, es_line in enumerate(es_f):
                en_line = en_f.readline() if en_f else ""
                if line_no < start_line:
                    continue
                if max_lines and line_no >= max_lines:
                    break
                tokens = flatten(es_line).split()
                if len(tokens) < MIN_WORDS:
                    continue
                seen = set()
                for gram in ngrams(tokens):
                    if gram in keys and gram not in seen:
                        seen.add(gram)
                        counts[gram] += 1
                        if len(examples[gram]) < examples_per_mwe:
                            examples[gram].append({
                                "es": es_line.strip(),
                                "en": en_line.strip(),
                                "line": line_no,
                            })
                if checkpoint_lines and line_no and line_no % checkpoint_lines == 0:
                    _write_checkpoint(checkpoint_path, counts, examples, line_no)
                    rate = (line_no - start_line) / max(time.time() - t0, 1e-9)
                    print(f"    {line_no:,} lines  {rate:,.0f}/s  "
                          f"{len(counts):,} expressions seen", flush=True)
        finally:
            if en_f:
                en_f.close()
    return counts, examples


def _write_checkpoint(path, counts, examples, line):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"counts": dict(counts),
                                "examples": {k: v for k, v in examples.items()},
                                "line": line}), encoding="utf-8")


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--checkpoint", type=Path, default=DEFAULT_CKPT)
    ap.add_argument("--max-lines", type=int, default=0,
                    help="stop after N corpus lines (0 = whole dump). Use a few "
                         "hundred thousand for a smoke test.")
    ap.add_argument("--examples-per-mwe", type=int, default=6)
    ap.add_argument("--checkpoint-lines", type=int, default=2_000_000)
    ap.add_argument("--restart", action="store_true",
                    help="ignore an existing checkpoint")
    ap.add_argument("--min-freq", type=int, default=1,
                    help="corpus occurrences required to be kept in tier 1")
    args = ap.parse_args()

    print("loading candidates")
    candidates = load_candidates()
    print(f"\nscanning corpus ({'all' if not args.max_lines else f'{args.max_lines:,}'} lines)")
    counts, examples = scan(candidates,
                            max_lines=args.max_lines,
                            examples_per_mwe=args.examples_per_mwe,
                            checkpoint_lines=args.checkpoint_lines,
                            checkpoint_path=args.checkpoint,
                            restart=args.restart)

    mwes = {}
    for expression, row in candidates.items():
        freq = counts.get(expression, 0)
        mwes[expression] = {
            "translations": row["translations"],
            "sources": sorted(row["sources"]),
            "attach_words": sorted(row["attach_words"]),
            "corpus_freq": freq,
            "examples": examples.get(expression, []),
        }

    attested = sum(1 for v in mwes.values() if v["corpus_freq"] >= args.min_freq)
    payload = {
        "meta": {
            "generated": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
            "corpus_lines_scanned": args.max_lines or 61_434_251,
            "candidates": len(mwes),
            "attested": attested,
            "unattested": len(mwes) - attested,
            "examples_per_mwe": args.examples_per_mwe,
            "note": "tier 1 = corpus_freq > 0, can carry an example and be "
                    "sense-assigned. tier 2 = corpus_freq 0, teachable content "
                    "with no sentence to attach. Do not collapse them.",
        },
        "mwes": mwes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    print(f"\nwrote {args.out}")
    print(f"  candidates {len(mwes):,}   attested {attested:,}   "
          f"unattested {len(mwes) - attested:,}")
    top = sorted(mwes.items(), key=lambda kv: -kv[1]["corpus_freq"])[:12]
    print("\n  most frequent:")
    for expression, row in top:
        print(f"    {row['corpus_freq']:>7,}  {expression:<24} = "
              f"{row['translations'][0][:38] if row['translations'] else ''}")


if __name__ == "__main__":
    main()
