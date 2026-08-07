#!/usr/bin/env python3
"""
Step 2c: Gemini pass over the elisions `step_3a_merge_elisions` (elision
normalization) deliberately refuses to guess.

WHY THIS EXISTS
---------------
`step_3a_merge_elisions` resolves ~94% of elided surfaces deterministically.
Its trailing-apostrophe tiebreaker only fires when EXACTLY ONE restoration of
the dropped final consonant (s/d/z/r/l/n) lands in the canonical Spanish form
table — a deliberate refusal to guess. The residue is genuinely ambiguous:
Spanish drops final -s (2sg / plural) and final -r (infinitive) in the same
phonetic position, and both restorations are real words.

    caga'  ->  cagas | cagad | cagar | cagan
    move'  ->  moved | mover
    coma'  ->  comas | comal | coman

A dictionary cannot separate those. The lyric line can. So: compute the
candidate set with exactly the same machinery step_3a uses, then ask Gemini to
pick ONE member of that set — or abstain — given the actual lines the word
appears in.

WHAT IT WRITES
--------------
Verdicts go into the EXISTING `Artists/curations/elision_mapping.json`, which
is documented as accepting "manual and auto-generated" entries. Nothing else in
the pipeline changes: `step_3a_merge_elisions` reads the mapping first, before
any of its regex families, so a record here simply pre-empts the tiebreaker.

Because `target_word` drives the downstream sense-menu lookup, resolving
`caga' -> cagar` automatically gives the card cagar's real SpanishDict menu
instead of an invented gloss. `display_form` keeps the lyric spelling.

RECORD SHAPE
------------
Merge (consumed by `step_3a_merge_elisions.load_merge_targets` and by
`step_2a_count_words.load_elision_normalization`):

    {"action": "merge",
     "merge_type": "elided_only",          # <- see NOTE ON merge_type
     "provenance": "gemini_elision",
     "elided_word": "caga'", "target_word": "cagar",
     "display_form": "caga'", "target_lemma": "cagar",
     "gemini": {model, run_at, confidence, candidates, reason, evidence, ...}}

Abstain / low confidence (consumed by `step_4a_filter_known_vocab`, which
routes `action: skip` words to the `elision` bucket and leaves them unmerged):

    {"action": "skip", "merge_type": "gemini_elision",
     "provenance": "gemini_elision", "word": "coma'", "note": "...",
     "gemini": {...}}

NOTE ON merge_type
    The brief for this step asked for `merge_type: "gemini_elision"` on merges.
    That value would be INERT: both readers of the mapping whitelist
    `elision_pair` / `elided_only` (`step_3a_merge_elisions.load_merge_targets`,
    `step_2a_count_words.load_elision_normalization`), so a `gemini_elision`
    merge_type would be silently ignored and the whole pass would be a no-op —
    contradicting the stated goal that "the rest of the pipeline needs no
    changes". Merges therefore carry `merge_type: "elided_only"` plus a separate
    `provenance: "gemini_elision"` field. Provenance is still exact and these
    records are trivially auditable / revertible on their own:

        jq '[.[] | select(.provenance == "gemini_elision")]' \
            Artists/curations/elision_mapping.json

    Skip records are not read through any merge_type whitelist, so those do
    carry `merge_type: "gemini_elision"` literally.

    No ppm fields are written. Nothing reads them, the elided form is by
    definition absent from the frequency list, and mixing a corpus-derived ppm
    with the es_50k-derived ppm on the existing records would be misleading.
    The artist corpus count lives in the `gemini` provenance block instead.

SAFETY
------
- `--dry-run` is the DEFAULT. Writing requires an explicit `--apply`.
- Never free generation: Gemini may only return a string already in the
  candidate list, or null. Anything else is treated as an abstain.
- Abstain is cheap and required: a wrong merge silently folds counts into the
  wrong lemma, which is worse than leaving the word unmerged.
- Existing records are never clobbered. A word already present in the mapping
  is not re-asked. `--force` re-asks ONLY words whose existing record carries
  `provenance: "gemini_elision"` — the 2876 deterministic/curated entries are
  untouchable.

Usage:
  # dry run (default) — prints every proposal, writes nothing
  .venv/bin/python3 pipeline/artist/step_2c_resolve_elisions_gemini.py \
      --artist-dir "Artists/spanish/Bad Bunny"

  # plan only, no API calls at all (candidate sets + what would be asked)
  .venv/bin/python3 pipeline/artist/step_2c_resolve_elisions_gemini.py \
      --artist-dir "Artists/spanish/Bad Bunny" --no-gemini

  # write verdicts into Artists/curations/elision_mapping.json
  .venv/bin/python3 pipeline/artist/step_2c_resolve_elisions_gemini.py \
      --artist-dir "Artists/spanish/Bad Bunny" --apply
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from util_1a_artist_config import SHARED_DIR, load_dotenv_from_project_root  # noqa: E402
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

# step_3a is READ-ONLY here: we reuse its candidate machinery verbatim so the
# two steps can never disagree about what "already resolved" means.
import step_3a_merge_elisions as elision_rules  # noqa: E402


STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "constrained-choice Gemini resolution of trailing-apostrophe elisions "
       "step_3a's exactly-one-candidate tiebreaker declines; writes "
       "provenance-stamped merge/skip records into elision_mapping.json",
}

# Same default model family as step_6c_assign_senses_gemini (the SpanishDict
# classify-or-propose path). Cheap, deterministic at temperature 0.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# Denser prompt than the plain classifier (candidate list + lyric lines per
# word), so keep batches small like step_6c's SD_CLASSIFY_BATCH_SIZE.
DEFAULT_BATCH_SIZE = 10

# A wrong merge is worse than no merge, so the bar is high.
DEFAULT_MIN_CONFIDENCE = 0.75

DEFAULT_MAX_EXAMPLES = 5

SPANISH_FORMS_PATH = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers",
                                  "spanish_forms.json")
CONJ_REVERSE_PATH = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers",
                                 "conjugation_reverse.json")
MAPPING_PATH = os.path.join(SHARED_DIR, "elision_mapping.json")

_PERSON_GLOSS = {
    "1s": "I", "2s": "you (tú)", "3s": "he/she/it", "2s_f": "you (formal)",
    "1p": "we", "2p": "you all (vosotros)", "3p": "they",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_spanish_forms_with_pos(path=SPANISH_FORMS_PATH):
    """{word: "pos,pos"} — the canonical 'is this Spanish?' table.

    Same file step_3a's tiebreaker and step_4a's Phase 2 consult. step_3a wraps
    it in a frozenset (keys only); we keep the POS string because it is useful
    context for the classifier.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_conj_reverse(path=CONJ_REVERSE_PATH):
    """{form: [{lemma, mood, tense, person}, ...]} — verbecc reverse index.

    Used only to describe candidates to Gemini ("cagas = tú, present") and to
    fill `target_lemma`. Missing file degrades gracefully.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_translation_index(artist_dir):
    """{spanish_line: english_line} from the aligned Genius translations.

    Optional. When present the English gloss is the single strongest signal
    for -s (you/they) vs -r (infinitive), so we pass it through.
    """
    path = os.path.join(artist_dir, "data", "input", "translations",
                        "aligned_translations.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    idx = data.get("index")
    return idx if isinstance(idx, dict) else {}


def load_mapping(path=MAPPING_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def mapping_known_words(mapping):
    """Every surface the mapping already has an opinion about.

    Returns (all_known, gemini_owned): `gemini_owned` is the subset this step
    wrote, which is the only subset `--force` is allowed to re-ask.
    """
    all_known = set()
    gemini_owned = set()
    for r in mapping:
        for key in ("elided_word", "full_word", "word"):
            w = r.get(key)
            if w:
                all_known.add(w)
                if r.get("provenance") == "gemini_elision":
                    gemini_owned.add(w)
    return all_known, gemini_owned


# ---------------------------------------------------------------------------
# Candidate construction — the constrained choice set
# ---------------------------------------------------------------------------
def candidate_forms(word, spanish_forms):
    """Restorations of `word` that are real Spanish forms.

    Identical construction to `step_3a_merge_elisions.trailing_apos_restore`
    (same `_TRAILING_APOS_RESTORES` tuple, same membership test against the
    canonical form table) — this step differs only in what it does when the
    result is ambiguous. step_3a keeps len == 1 and drops everything else; we
    pick up len >= 2 and let the lyric decide.
    """
    if not word.endswith("'") or len(word) < 3:
        return []
    stem = word[:-1]
    return [stem + c for c in elision_rules._TRAILING_APOS_RESTORES
            if (stem + c) in spanish_forms]


def describe_candidate(form, spanish_forms, conj_reverse):
    """Compact morphological description shown to the classifier.

    e.g. "cagas — verb; cagar: indicativo presente, you (tú)"
    """
    pos = spanish_forms.get(form) or ""
    bits = []
    if pos:
        bits.append(pos)
    analyses = conj_reverse.get(form) or []
    seen = []
    for a in analyses[:3]:
        lemma = a.get("lemma", "")
        mood = a.get("mood", "")
        tense = a.get("tense", "")
        person = _PERSON_GLOSS.get(a.get("person", ""), a.get("person", ""))
        desc = "%s: %s %s%s" % (lemma, mood, tense,
                                (", " + person) if person else "")
        if desc not in seen:
            seen.append(desc)
    if seen:
        bits.append("; ".join(seen))
    return "%s — %s" % (form, " | ".join(bits)) if bits else form


def infer_target_lemma(form, spanish_forms, conj_reverse):
    """Best-effort lemma for the chosen restoration.

    Audit-only: no reader of elision_mapping.json consumes `target_lemma`
    (grep confirms only writers touch it), so a miss costs nothing. Verb forms
    come from the verbecc reverse index; a plural noun/adj falls back to the
    singular when that singular is itself a known form; otherwise the form is
    its own lemma.
    """
    analyses = conj_reverse.get(form) or []
    if analyses:
        counts = defaultdict(int)
        for a in analyses:
            if a.get("lemma"):
                counts[a["lemma"]] += 1
        if counts:
            return max(counts.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
    if form.endswith("es") and form[:-2] in spanish_forms:
        return form[:-2]
    if form.endswith("s") and form[:-1] in spanish_forms:
        return form[:-1]
    return form


def collect_targets(evidence, mapping, spanish_forms, known_vocab,
                    merge_targets, max_examples, translations,
                    already_known, force_words):
    """Partition trailing-apostrophe survivors into ask / no-candidate / cached.

    A survivor is a `word'` that every deterministic rule in
    `step_3a_merge_elisions` declines: explicit mapping, d-elision,
    double-elision and the exactly-one trailing-apos tiebreaker.
    """
    ask, no_candidates, cached = [], [], []

    for entry in evidence:
        word = entry.get("word", "")
        if not word.endswith("'"):
            continue
        if word in merge_targets:
            continue
        if elision_rules.d_elision_canonical(word):
            continue
        if elision_rules.double_elision_canonical(word):
            continue
        if elision_rules.trailing_apos_restore(word, known_vocab):
            continue

        cands = candidate_forms(word, spanish_forms)
        examples = []
        for ex in entry.get("examples", [])[:max_examples]:
            line = ex.get("line", "")
            if not line:
                continue
            examples.append({"line": line,
                             "english": translations.get(line, ""),
                             "title": ex.get("title", "")})

        rec = {"word": word,
               "corpus_count": entry.get("corpus_count", 0),
               "candidates": cands,
               "examples": examples}

        if len(cands) < 2:
            # len == 0: nothing in Spanish restores it (English filler like
            # `fuckin'`, proper nouns like `mykono'`). len == 1 can't happen —
            # step_3a's tiebreaker already claimed it above.
            no_candidates.append(rec)
            continue
        if word in already_known and word not in force_words:
            cached.append(rec)
            continue
        ask.append(rec)

    ask.sort(key=lambda r: (-r["corpus_count"], r["word"]))
    no_candidates.sort(key=lambda r: (-r["corpus_count"], r["word"]))
    return ask, no_candidates, cached


# ---------------------------------------------------------------------------
# Gemini — constrained choice, abstention always available
# ---------------------------------------------------------------------------
def resolve_batch_gemini(batch, api_key, model, spanish_forms, conj_reverse,
                         artist_context):
    """Ask Gemini to pick one candidate per word, or abstain.

    Client setup, temperature, JSON response mode, invalid-key fatal path and
    5-attempt exponential backoff all follow
    `pipeline/step_6c_assign_senses_gemini.classify_or_propose_batch`.

    Returns [{"word", "choice"|null, "confidence", "reason"}] or None on
    unrecoverable failure (caller treats that as "ask nobody, change nothing").
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    header = (
        "You are normalizing elided word forms in Spanish song lyrics (%s).\n"
        "Caribbean Spanish drops a final consonant and writes an apostrophe:"
        " `cantar` and `cantas` both become `canta'`.\n"
        "For EACH word below you are given the lyric lines it appears in and a"
        " CLOSED LIST of candidate restorations. Every candidate is a real"
        " Spanish form; only the context can tell them apart.\n"
        "Decide which candidate the singer actually used, reading the whole"
        " line: an infinitive (-r) follows a modal/preposition (quiero, va a,"
        " para, sin, puede); a 2nd-person -s follows tú/te or an imperative"
        " address; a 3rd-person plural -n has a plural subject; a plural noun"
        " -s follows a determiner/quantifier. The English translation, when"
        " shown after `|`, is the strongest signal.\n"
        "You MUST pick a string that appears VERBATIM in that word's candidate"
        " list, or abstain. NEVER invent a form outside the list.\n"
        "ABSTAIN whenever the line is too short, too garbled, the token is a"
        " fragment/English/a proper noun, or two candidates remain equally"
        " plausible: set \"choice\": null. Abstaining is the CORRECT answer in"
        " those cases and costs nothing — a wrong merge silently folds the"
        " word's counts into the wrong lemma.\n"
        "\"confidence\" is 0.0-1.0 for the choice. \"reason\" is at most 12"
        " words naming the cue you used.\n"
        "Return ONLY JSON: [{\"word\":\"x\",\"choice\":\"<candidate|null>\","
        "\"confidence\":0.0,\"reason\":\"...\"}]"
    ) % artist_context

    parts = [header, "", "WORDS:"]
    for rec in batch:
        parts.append('\n--- "%s" ---' % rec["word"])
        parts.append("Candidates (choose exactly one, or null):")
        for c in rec["candidates"]:
            parts.append("  %s" % describe_candidate(c, spanish_forms,
                                                     conj_reverse))
        parts.append("Lyric lines:")
        if rec["examples"]:
            for i, ex in enumerate(rec["examples"], start=1):
                eng = ("  |  " + ex["english"]) if ex.get("english") else ""
                parts.append("  %d. %s%s" % (i, ex["line"], eng))
        else:
            parts.append("  (none — abstain)")

    prompt = "\n".join(parts)

    response = None
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0.0,
                        "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: elision batch parse error")
            print("    Raw: %s" % (response.text[:500] if response is not None
                                   and response.text else "None"))
            return None
        except Exception as e:
            msg = str(e)
            if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                sys.exit("FATAL: Gemini API key not valid. The key comes from "
                         "$GEMINI_API_KEY (an explicit env prefix on the command "
                         "overrides the project .env — drop the prefix to use .env).")
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (attempt + 1, msg[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


def adjudicate(rec, verdict, min_confidence):
    """Turn a raw Gemini verdict into a decision dict.

    Enforces the constraint: an off-list `choice` is an abstain, not a merge.
    """
    if verdict is None:
        return {"decision": "abstain", "choice": None, "confidence": 0.0,
                "reason": "no response from classifier"}

    choice = verdict.get("choice")
    if isinstance(choice, str):
        choice = choice.strip()
    reason = (verdict.get("reason") or "")[:200]
    try:
        confidence = float(verdict.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    if not choice or choice in ("null", "None"):
        return {"decision": "abstain", "choice": None,
                "confidence": confidence, "reason": reason or "abstained"}
    if choice not in rec["candidates"]:
        return {"decision": "abstain", "choice": None, "confidence": 0.0,
                "reason": "off-list answer %r rejected" % choice}
    if confidence < min_confidence:
        return {"decision": "abstain", "choice": choice,
                "confidence": confidence,
                "reason": "below --min-confidence: %s" % (reason or "")}
    return {"decision": "merge", "choice": choice, "confidence": confidence,
            "reason": reason}


# ---------------------------------------------------------------------------
# Record building + write-back
# ---------------------------------------------------------------------------
def build_record(rec, decision, model, run_at, spanish_forms, conj_reverse):
    provenance = {
        "model": model,
        "run_at": run_at,
        "step_version": STEP_VERSION,
        "confidence": round(decision["confidence"], 3),
        "candidates": list(rec["candidates"]),
        "reason": decision["reason"],
        "corpus_count": rec["corpus_count"],
        "evidence": [ex["line"] for ex in rec["examples"]][:3],
    }

    if decision["decision"] == "merge":
        target = decision["choice"]
        return {
            "action": "merge",
            # elided_only (not "gemini_elision") so the mapping's readers
            # actually consume it — see NOTE ON merge_type in the module
            # docstring. `provenance` carries the audit trail.
            "merge_type": "elided_only",
            "provenance": "gemini_elision",
            "elided_word": rec["word"],
            "target_word": target,
            "display_form": rec["word"],
            "target_lemma": infer_target_lemma(target, spanish_forms,
                                               conj_reverse),
            "gemini": provenance,
        }

    return {
        "action": "skip",
        "merge_type": "gemini_elision",
        "provenance": "gemini_elision",
        "word": rec["word"],
        "note": "Gemini abstained: %s" % (decision["reason"] or "ambiguous"),
        "gemini": provenance,
    }


def apply_records(mapping, records):
    """Splice records into the mapping list.

    Replaces an existing record only when that record is itself
    `provenance: gemini_elision` — curated/deterministic entries are never
    overwritten, they simply cause the new record to be dropped.
    """
    by_word = {}
    for i, r in enumerate(mapping):
        for key in ("elided_word", "word"):
            w = r.get(key)
            if w and w not in by_word:
                by_word[w] = i

    replaced = added = refused = 0
    for new in records:
        word = new.get("elided_word") or new.get("word")
        idx = by_word.get(word)
        if idx is None:
            mapping.append(new)
            added += 1
        elif mapping[idx].get("provenance") == "gemini_elision":
            mapping[idx] = new
            replaced += 1
        else:
            refused += 1
    return added, replaced, refused


def write_mapping(mapping, path=MAPPING_PATH):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_proposal(rec, decision):
    tag = "MERGE " if decision["decision"] == "merge" else "SKIP  "
    arrow = decision["choice"] or "(abstain)"
    print("\n%s %-16s -> %-14s conf=%.2f  count=%d"
          % (tag, rec["word"], arrow, decision["confidence"],
             rec["corpus_count"]))
    print("       candidates: %s" % ", ".join(rec["candidates"]))
    if decision["reason"]:
        print("       reason:     %s" % decision["reason"])
    for ex in rec["examples"][:2]:
        eng = ("  |  " + ex["english"]) if ex.get("english") else ""
        print("       lyric:      %s%s" % (ex["line"], eng))


def main():
    parser = argparse.ArgumentParser(
        description="Resolve ambiguous trailing-apostrophe elisions with Gemini "
                    "and write verdicts into elision_mapping.json.")
    parser.add_argument("--artist-dir", required=True,
                        help="Path to artist data directory")
    parser.add_argument("--apply", action="store_true",
                        help="Write verdicts into Artists/curations/elision_mapping.json. "
                             "Without this the step is a dry run and writes nothing.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Explicit no-op form of the default behaviour.")
    parser.add_argument("--force", action="store_true",
                        help="Re-ask words this step already resolved. Never "
                             "re-asks curated / deterministic mapping entries.")
    parser.add_argument("--no-gemini", action="store_true",
                        help="Print the plan (candidate sets, lyric lines) "
                             "without making any API call.")
    parser.add_argument("--gemini-model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES,
                        help="Lyric lines per word sent to Gemini.")
    parser.add_argument("--min-confidence", type=float,
                        default=DEFAULT_MIN_CONFIDENCE,
                        help="Below this, a choice becomes an abstain (skip record).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the N highest-count words.")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    dry_run = not args.apply
    artist_dir = os.path.abspath(args.artist_dir)
    evidence_path = os.path.join(artist_dir, "data", "word_counts",
                                 "vocab_evidence.json")
    report_path = os.path.join(artist_dir, "data", "elision_merge",
                               "gemini_elision_report.json")

    print("Gemini elision resolution")
    print("=" * 60)
    print("Artist dir: %s" % artist_dir)
    print("Mode:       %s" % ("DRY RUN (no writes)" if dry_run else "APPLY"))

    if not os.path.isfile(evidence_path):
        sys.exit("ERROR: missing %s — run step_2a_count_words (tokenise/count) first."
                 % evidence_path)

    with open(evidence_path, "r", encoding="utf-8") as f:
        evidence = json.load(f)
    print("Evidence:   %d entries" % len(evidence))

    spanish_forms = load_spanish_forms_with_pos()
    if not spanish_forms:
        sys.exit("ERROR: %s is missing — the candidate set cannot be validated."
                 % SPANISH_FORMS_PATH)
    conj_reverse = load_conj_reverse()
    translations = load_translation_index(artist_dir)
    mapping = load_mapping()
    merge_targets = elision_rules.load_merge_targets(MAPPING_PATH)
    known_vocab = elision_rules.load_known_vocab()
    already_known, gemini_owned = mapping_known_words(mapping)
    force_words = gemini_owned if args.force else set()

    print("Forms:      %d canonical Spanish forms" % len(spanish_forms))
    print("Mapping:    %d records (%d written by this step)"
          % (len(mapping), len(gemini_owned)))
    print("Translations: %d aligned lines" % len(translations))

    ask, no_candidates, cached = collect_targets(
        evidence, mapping, spanish_forms, known_vocab, merge_targets,
        args.max_examples, translations, already_known, force_words)

    if args.limit is not None:
        ask = ask[:args.limit]

    print("\n--- Survivors of step_3a_merge_elisions (elision normalization) ---")
    print("  ambiguous, to ask:      %d" % len(ask))
    print("  already in mapping:     %d (use --force to re-ask this step's own)"
          % len(cached))
    print("  no Spanish candidate:   %d (left untouched; not English-filterable here)"
          % len(no_candidates))
    if no_candidates:
        print("    %s" % ", ".join(r["word"] for r in no_candidates))

    if not ask:
        print("\nNothing to resolve.")
        return

    if args.no_gemini:
        print("\n--- PLAN ONLY (--no-gemini): no API calls made ---")
        for rec in ask:
            print("\n  %-16s count=%d" % (rec["word"], rec["corpus_count"]))
            print("       candidates: %s" % ", ".join(rec["candidates"]))
            for ex in rec["examples"][:2]:
                eng = ("  |  " + ex["english"]) if ex.get("english") else ""
                print("       lyric:      %s%s" % (ex["line"], eng))
        print("\n%d words would be sent in %d batch(es) to %s."
              % (len(ask), (len(ask) + args.batch_size - 1) // args.batch_size,
                 args.gemini_model))
        return

    load_dotenv_from_project_root()
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit("ERROR: no Gemini API key. Set GEMINI_API_KEY in .env or pass "
                 "--api-key. Use --no-gemini to print the plan without calling out.")

    artist_context = "reggaeton / Caribbean Spanish"
    config_path = os.path.join(artist_dir, "artist.json")
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg.get("artist_context"), str) and cfg["artist_context"].strip():
            artist_context = cfg["artist_context"].strip()

    run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    records, proposals = [], []
    n_merge = n_abstain = 0

    print("\n--- Resolving %d words (%s, batches of %d) ---"
          % (len(ask), args.gemini_model, args.batch_size))
    for start in range(0, len(ask), args.batch_size):
        batch = ask[start:start + args.batch_size]
        print("\n  Batch %d: %s"
              % (start // args.batch_size + 1, [r["word"] for r in batch]))
        results = resolve_batch_gemini(batch, api_key, args.gemini_model,
                                       spanish_forms, conj_reverse,
                                       artist_context)
        by_word = {}
        for item in (results or []):
            if isinstance(item, dict) and item.get("word"):
                by_word[item["word"]] = item

        for rec in batch:
            decision = adjudicate(rec, by_word.get(rec["word"]),
                                  args.min_confidence)
            print_proposal(rec, decision)
            proposals.append({"word": rec["word"],
                              "candidates": rec["candidates"],
                              "decision": decision["decision"],
                              "choice": decision["choice"],
                              "confidence": decision["confidence"],
                              "reason": decision["reason"],
                              "corpus_count": rec["corpus_count"],
                              "evidence": [e["line"] for e in rec["examples"]]})
            records.append(build_record(rec, decision, args.gemini_model,
                                        run_at, spanish_forms, conj_reverse))
            if decision["decision"] == "merge":
                n_merge += 1
            else:
                n_abstain += 1

    print("\n" + "=" * 60)
    print("Proposed merges:  %d" % n_merge)
    print("Proposed skips:   %d" % n_abstain)

    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit these "
              "records to %s" % MAPPING_PATH)
        return

    added, replaced, refused = apply_records(mapping, records)
    write_mapping(mapping)
    print("\nWrote %s" % MAPPING_PATH)
    print("  added:    %d" % added)
    print("  replaced: %d (prior gemini_elision records)" % replaced)
    print("  refused:  %d (curated record already owns the word)" % refused)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"run_at": run_at, "model": args.gemini_model,
                   "min_confidence": args.min_confidence,
                   "merges": n_merge, "skips": n_abstain,
                   "no_candidate_words": [r["word"] for r in no_candidates],
                   "proposals": proposals},
                  f, ensure_ascii=False, indent=2)
    write_sidecar(report_path,
                  make_meta("resolve_elisions_gemini", STEP_VERSION,
                            extra={"model": args.gemini_model,
                                   "asked": len(ask),
                                   "merges": n_merge, "skips": n_abstain}))
    print("  report:   %s" % report_path)


if __name__ == "__main__":
    main()
