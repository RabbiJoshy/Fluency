#!/usr/bin/env python3
"""step_6f_align_english_leaf — correct the leaf using the aligned English word.

The one added signal that has ever beaten plain gloss-cosine on this problem.
Everything else measured (query windowing, target marking, leaf exemplars, MLM
substitution, sense enrichment in three forms, sense cue words -- see
`docs/reference/wsd_dead_ends.md`) matched on PRESENCE: this topic is nearby,
this cue is in the sentence. Word alignment matches on RELATION -- it says which
English word IS this Spanish token -- and that is the difference.

    mBERT SimAlign aligns the Spanish target to its English subtitle word;
    where a leaf's gloss head is that word, take that leaf.

Measured before it was built: 49 better / 12 worse on 100 fresh hand-graded
speech cards, firing on ~16%.

This is a CORRECTOR, not a classifier. It reads the claims step_6e already
wrote, emits a claim only on the occurrences it actually changes, and leaves
every other example to the run it came from. So a corrected card's provenance
reads `sd-beto-cal-align-v4` and an untouched card's still reads
`sd-beto-cal-v3`; the builder resolves per example, so both are true at once.

It needs parallel text, which is why it is structurally a speech-mode step:
artist mode has a translation for some songs and none for others, and
`--artist-dir` is accepted so that partial coverage can be used deliberately
rather than by accident.

Usage:
    python3 pipeline/step_6f_align_english_leaf.py --dry-run
    python3 pipeline/step_6f_align_english_leaf.py
    python3 pipeline/step_6f_align_english_leaf.py --report changes.tsv
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline"))

from util_6a_assignment_format import stamp_example_ids  # noqa: E402
from util_pipeline_meta import display_path  # noqa: E402
from util_6f_alignment import (  # noqa: E402
    DEFAULT_METHOD, STOPWORDS, WordAligner, english_stem, find_target_span,
    tokenize_target)

LAYERS_DIR = REPO / "Data/Spanish/layers"
METHOD = "spanishdict-beto-cal-align-v5"
PROMPT_ID = "sd-beto-cal-align-v5"
# The runs this corrector is allowed to read and overturn. An unlisted method is
# left alone rather than silently corrected: the measurement is against the v3
# local path, and nothing says it holds against a different classifier.
SOURCE_METHODS = ("spanishdict-beto-cal-v5",)
# Escalated picks graded ~88% against ~76% for locally-decided ones. The
# alignment measurement was against the local path, so it does not license
# overturning a Gemini second opinion.
ESCALATED_PROMPT_IDS = ("sd-beto-cal-esc-v5",)

_PREPOSITIONS = frozenset(
    "of in on for with from at by into onto about over under after before".split())


def ex_text(c):
    return c.get("target") or c.get("spanish") or ""


def ex_surface(c, word):
    return c.get("surface") or word


def gloss_heads(translation, pos):
    """Head word(s) of an English gloss, as stems.

    A one-word gloss is its own head, which is the majority of the menu. For a
    multi-word gloss English puts the head at opposite ends depending on what
    kind of phrase it is -- `to give` and `hurry up` are head-initial, `good
    night` and `bus stop` head-final -- and the menu does not say which, because
    POS is `PHRASE` for both. Rather than guess a parse, accept either end and
    let the alignment carry the burden of being about this token: `dame` aligned
    to "give" matches the head of *give me*, and nothing aligned to "me" is
    going to select a leaf the target is not.

    A trailing prepositional phrase is dropped first (`piece of cake` -> piece),
    since its object is a modifier under any reading.
    """
    tokens = [t for t in tokenize_target(translation)]
    for i, token in enumerate(tokens):
        if token in _PREPOSITIONS and i:
            tokens = tokens[:i]
            break
    content = [t for t in tokens if t not in STOPWORDS]
    if not content:
        # An all-stopword gloss ("to", "it") has no head worth matching.
        return frozenset()
    if len(content) == 1:
        return frozenset({english_stem(content[0])})
    return frozenset({english_stem(content[0]), english_stem(content[-1])})


def _tsv(text):
    """One TSV cell. Quotes are stripped as well as tabs so a reader using
    Python's default QUOTE_MINIMAL cannot swallow the next three rows."""
    return (text or "").replace("\t", " ").replace('"', "'").replace("\n", " ")


def tuple_of_leaf(sense):
    """The (headword, POS) a leaf belongs to -- what stage 3 settles."""
    return ((sense.get("headword") or "").lower(), (sense.get("pos") or "").upper())


def load_claims(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", default="",
                    help="run against an artist corpus. Coverage is partial by "
                         "construction -- a song with no scraped translation "
                         "has no parallel text and is skipped -- so this is "
                         "opt-in rather than the default.")
    ap.add_argument("--method", default=DEFAULT_METHOD,
                    choices=["itermax", "inter", "mwmf"],
                    help="SimAlign matching method. itermax (default) accepted "
                         "44 of 60 benchmark rows at 81.8%% precision / 90.0%% "
                         "recall; inter 40 rows at 82.5%%/82.5%%.")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--on-tie", default="abstain", choices=["abstain", "keep"],
                    help="what to do when several leaves share the aligned "
                         "word as a head and the current pick is not among "
                         "them. `abstain` (default) writes no claim; the "
                         "signal identified a gloss, not a leaf.")
    ap.add_argument("--stay-in-tuple", action="store_true",
                    help="only correct to a leaf inside the (headword, POS) the "
                         "v3 pick already won. Off by default because the 49/12 "
                         "measurement was made without it, but it is the same "
                         "invariant stage 4 leaf repair holds, and it is the "
                         "lever for the failure mode this signal has: a loose "
                         "subtitle rendering pulls a function word onto a "
                         "content gloss (`lo` -> *stuff* on \"I saw the baby "
                         "stuff\"). 9.6%% of corrections change the tuple.")
    ap.add_argument("--include-escalated", action="store_true",
                    help="also correct picks a Gemini escalation authored. Off "
                         "by default: escalated picks graded ~88%% and the "
                         "alignment result was measured against the local path.")
    ap.add_argument("--limit", type=int, default=0,
                    help="align at most N occurrences (for a smoke run)")
    ap.add_argument("--report", default="",
                    help="write every changed pick to this TSV: word, sentence, "
                         "aligned English, gloss before, gloss after")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="report coverage and fire rate; write nothing")
    a = ap.parse_args()

    base = (REPO / a.artist_dir / "data/layers") if a.artist_dir else LAYERS_DIR
    examples = json.loads((base / "examples_raw.json").read_text(encoding="utf-8"))
    raw = json.loads((base / "sense_menu/spanishdict.json").read_text(encoding="utf-8"))
    menus = {w: {sid: v for e in entries for sid, v in e.get("senses", {}).items()}
             for w, entries in raw.items()}
    claims_path = base / "sense_assignments/spanishdict.json"
    claims = load_claims(claims_path)
    out_path = Path(a.out) if a.out else claims_path

    # Which (word, example index) each source method claimed, and with what.
    # A word can carry several claims for one example only across methods; within
    # a method the layer is already one claim per example.
    targets = {}          # (word, ex_idx) -> (sense_id, prompt_id)
    for word, by_method in claims.items():
        if not isinstance(by_method, dict) or word not in menus:
            continue
        for method in SOURCE_METHODS:
            for item in by_method.get(method) or []:
                pid = item.get("prompt_id") or ""
                for j in item.get("examples") or []:
                    targets[(word, j)] = (item.get("sense"), pid)

    # Precompute the head set per leaf once. Words whose whole menu shares one
    # head cannot be discriminated by this signal at all, so they are skipped
    # before any alignment work.
    heads = {}
    discriminable = set()
    for word, menu in menus.items():
        per_leaf = {sid: gloss_heads(m.get("translation"), m.get("pos"))
                    for sid, m in menu.items()}
        heads[word] = per_leaf
        distinct = {h for hs in per_leaf.values() for h in hs}
        if len(menu) > 1 and len(distinct) > 1:
            discriminable.add(word)

    work = []
    skipped_escalated = 0
    for (word, j), (sid, pid) in sorted(targets.items()):
        if word not in discriminable:
            continue
        if pid in ESCALATED_PROMPT_IDS and not a.include_escalated:
            skipped_escalated += 1
            continue
        rows = examples.get(word) or []
        if j >= len(rows):
            continue
        c = rows[j]
        if not (ex_text(c).strip() and (c.get("english") or "").strip()):
            continue
        work.append((word, j, sid, c))

    print(f"{len(targets):,} claimed occurrences from {'/'.join(SOURCE_METHODS)}")
    print(f"  {len(work):,} are alignable and on a menu this signal can "
          f"discriminate ({skipped_escalated:,} skipped as escalated)")
    if a.limit:
        work = work[:a.limit]
        print(f"  --limit {a.limit}: aligning {len(work):,}")

    aligner = WordAligner(cache_dir=base / "alignment_cache",
                          method=a.method, device=a.device)
    if aligner.cached:
        need = sum(1 for _w, _j, _s, c in work
                   if not aligner.is_cached(ex_text(c), c["english"]))
        print(f"  alignment cache: {aligner.cached:,} pairs on disk, "
              f"{need:,} of {len(work):,} still to align")

    if a.dry_run:
        print(f"\n--dry-run: nothing written")
        return

    changed = []            # (word, j, old_sid, new_sid, aligned_words)
    fired = no_span = no_english_word = tie = agreed = tuple_changed = 0
    started = time.monotonic()
    for n, (word, j, sid, c) in enumerate(work, 1):
        alignment = aligner.align(ex_text(c), c["english"])
        if alignment is None:
            continue
        span = find_target_span(alignment.source_tokens, ex_surface(c, word), word)
        if not span:
            no_span += 1
            continue
        aligned = {english_stem(t) for t in alignment.target_words_for(span)
                   if t not in STOPWORDS}
        if not aligned:
            no_english_word += 1
            continue
        matches = [s for s, hs in heads[word].items() if hs & aligned]
        if a.stay_in_tuple and sid in menus[word]:
            won = tuple_of_leaf(menus[word][sid])
            matches = [s for s in matches
                       if tuple_of_leaf(menus[word][s]) == won]
        if not matches:
            continue
        fired += 1
        if sid in matches:
            agreed += 1
            continue
        if len(matches) > 1 and a.on_tie == "abstain":
            tie += 1
            continue
        if sid in menus[word] and (tuple_of_leaf(menus[word][sid])
                                   != tuple_of_leaf(menus[word][matches[0]])):
            tuple_changed += 1
        changed.append((word, j, sid, matches[0],
                        sorted(alignment.target_words_for(span))))
        if n % 2000 == 0:
            aligner.flush()
            rate = n / max(time.monotonic() - started, 1e-6)
            print(f"  aligned {n:,}/{len(work):,} ({rate:.0f}/s), "
                  f"{len(changed):,} corrections so far", flush=True)
    aligner.flush()

    total = len(work)
    print(f"\naligned {total:,} occurrences in {time.monotonic() - started:.0f}s")
    print(f"  matched a gloss head on {fired:,} ({fired / max(total, 1):.0%})")
    print(f"    already agreed with the v3 pick: {agreed:,}")
    print(f"    ambiguous (several leaves share the head), abstained: {tie:,}")
    print(f"    CORRECTED: {len(changed):,} ({len(changed) / max(total, 1):.1%} "
          f"of alignable occurrences)")
    print(f"      of which change the (headword, POS) tuple: {tuple_changed:,} "
          f"({tuple_changed / max(len(changed), 1):.1%}) "
          f"-- see --stay-in-tuple")
    print(f"  target word not locatable in the sentence: {no_span:,}")
    print(f"  target aligned to nothing contentful: {no_english_word:,}")

    if a.report and changed:
        lines = ["word\texample\taligned_english\tbefore\tafter\tsentence\tenglish"]
        for word, j, old, new, aligned in changed:
            c = examples[word][j]
            before = menus[word][old]
            after = menus[word][new]
            lines.append("\t".join([
                word, str(j), " ".join(aligned),
                f'{before.get("pos","")}: {before.get("translation","")}',
                f'{after.get("pos","")}: {after.get("translation","")}',
                _tsv(ex_text(c)), _tsv(c["english"])]))
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  wrote {len(changed):,} changes to {a.report}")

    if not changed:
        print("nothing to write")
        return

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    by_word = collections.defaultdict(dict)
    for word, j, _old, new, _aligned in changed:
        entry = by_word[word].setdefault(
            new, {"sense": new, "examples": [], "method": METHOD,
                  "prompt_id": PROMPT_ID, "run_ts": ts})
        entry["examples"].append(j)

    out = load_claims(out_path) if out_path != claims_path else claims
    for word, by_sense in by_word.items():
        for entry in by_sense.values():
            entry["examples"].sort()
        # MERGE, never replace: the layer is {word: {method: [...]}} and this
        # corrector deliberately coexists with the run it corrects.
        out.setdefault(word, {})[METHOD] = list(by_sense.values())
    stamp_example_ids(out, examples)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from util_evidence_store import archive_json_artifact
        archive_json_artifact(base.parent / "evidence", "sense_assignments/spanishdict",
                              out, language="spanish",
                              adapter={"name": METHOD, "prompt_id": PROMPT_ID})
    except Exception as exc:
        print(f"  (archive skipped: {exc})")
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(changed):,} corrections across {len(by_word):,} words "
          f"-> {display_path(out_path)}  [{METHOD}]")


if __name__ == "__main__":
    main()
