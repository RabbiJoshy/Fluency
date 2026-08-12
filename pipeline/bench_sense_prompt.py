#!/usr/bin/env python3
"""Regression harness for the SpanishDict classify-or-propose prompt.

Replaces the throwaway `scratchpad/eval30.py` / `suff_eval*.py` scripts the old
prompt comment referred to (they no longer exist). This one lives in the repo so
the prompt in `step_6c_assign_senses_gemini.build_classify_or_propose_prompt`
has a committed, re-runnable check.

What it measures — the two failure modes the owner flagged:
  1. OVER-TRANSLATION: Gemini translated the clause / the referent instead of
     the headword, and invented an off-menu gloss even though the SpanishDict
     menu already carried a correct sense (mira -> "sight", anda -> "to be on
     the loose", sube -> "to become outdated", saco -> "to ejaculate",
     culitos -> "young women").
  2. PROSE: proposals shipped as dictionary definitions rather than flashcard
     glosses (rrear -> "To dance, especially in a provocative way.").
Plus the cases where proposing is CORRECT (genuine menu gaps: cuantos, manín,
fulete, tequi, hermas) and proper nouns (quiles, beatles), so a prompt that
simply stops proposing is not scored as a win.

How it exercises the real payload: it does NOT reimplement layer loading or
words_data assembly. It calls `step_6c_assign_senses_gemini.main()` in-process
with exactly the argv the SpanishDict Gemini path uses (see
`pipeline/artist/step_6a_assign_senses._spanishdict_args_gemini`), restricted to
the gold words, and monkeypatches `classify_or_propose_batch` to capture the
batch payload + the model's raw answer. The capture then aborts the run before
any layer file, checkpoint or report is written, so the harness is read-only.

Run from project root:
    .venv/bin/python3 pipeline/bench_sense_prompt.py
    .venv/bin/python3 pipeline/bench_sense_prompt.py --dry-run
    .venv/bin/python3 pipeline/bench_sense_prompt.py --words mira,anda
"""
import argparse
import json
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))

import step_6c_assign_senses_gemini as s6c  # noqa: E402

DEFAULT_ARTIST_DIR = str(PROJECT_ROOT / "Artists" / "spanish" / "Bad Bunny")

# ---------------------------------------------------------------------------
# Gold set — real cards the owner flagged. Edit / extend as more audits arrive.
# ---------------------------------------------------------------------------
# mode:      "menu"    -> the menu already had a correct sense; picking it is the
#                         only pass. Proposing here is the over-translation bug.
#            "propose" -> genuine lexical menu gap; proposing is correct.
#            "abstain" -> non-lexical material; a named abstention is correct.
# context:   distinctive substring of the flagged lyric line, used to find the
#            example this expectation is about (accent/apostrophe-insensitive).
# want_any:  pass needs one of these substrings in the chosen/proposed gloss.
# forbid_any: the wrong answer that actually shipped.
# want_type: required `type` tag on a proposal (proper_noun cases).
GOLD_SET = [
    {"word": "mira", "mode": "menu", "context": "mira donde yo estoy",
     "want_any": ["look", "watch", "see"], "forbid_any": ["sight"],
     "want_pos": "VERB",
     "note": "menu has mirar->'to look at' (VERB) and mira->'sight' (NOUN); shipped 'sight'"},
    {"word": "anda", "mode": "menu", "context": "anda con la amiga",
     "want_any": ["hang out", "go", "walk", "be"],
     "forbid_any": ["on the loose"],
     "note": "menu's FIRST sense is andar->'to hang out with [used with con]'; shipped 'to be on the loose'"},
    {"word": "sube", "mode": "menu", "context": "sube ese culo",
     "want_any": ["raise", "go up", "lift", "come up", "put up", "turn up",
                  "climb", "get on", "rise"],
     "forbid_any": ["outdated"],
     "note": "menu has subir->'to raise'/'to go up'; shipped 'to become outdated'"},
    # `want_any` covers every sacar sense the menu offers, not just the ones
    # right for the flagged lyric: the harness falls back to the first example
    # when it cannot match `context`, and "saco un disco" legitimately means
    # "to release". The real failure being guarded against is the off-menu
    # invention, so `forbid_any` is what carries this case.
    {"word": "saco", "mode": "menu", "context": "el punto y los saco",
     "want_any": ["take out", "get out", "pull out", "take", "remove",
                  "release", "make", "extract"],
     "forbid_any": ["ejaculate"],
     "note": "menu has sacar->'to take out'/'to get out'; shipped 'to ejaculate'"},
    {"word": "culitos", "mode": "menu", "context": "los culito",
     "want_any": ["ass", "butt", "booty", "bottom"],
     "forbid_any": ["young women"],
     "note": "menu has culito->'ass'; shipped 'young women'"},
    {"word": "rrear", "mode": "any", "context": "rrear",
     "forbid_any": ["especially"],
     "note": "fragment of perrear; shipped the PROSE definition "
             "'To dance, especially in a provocative way.' — want a short gloss "
             "or a rejection, never prose"},
    {"word": "quiles", "mode": "abstain", "context": "justin quiles",
     "want_reason": "proper_noun", "forbid_any": ["screw"],
     "note": "a surname; lexical WSD must abstain as proper_noun"},
    {"word": "beatles", "mode": "abstain", "context": "los beatle",
     "want_reason": "proper_noun", "forbid_any": [" or "],
     "note": "a band; lexical WSD must abstain as proper_noun"},
    {"word": "cuantos", "mode": "propose", "context": "unos cuantos",
     "forbid_any": ["quantum"],
     "note": "menu ONLY has cuanto->'quantum (physics)' — a GENUINE gap, "
             "proposing is CORRECT"},
    # mode=menu, not propose: the menu DOES carry `bro, buddy (slang)` beside
    # `peanut`, so picking it is the right answer and proposing would be the
    # regression. The original gloss "peanut" was a wrong pick, not a menu gap.
    {"word": "manín", "mode": "menu", "context": "dime, manin",
     "want_any": ["bro", "buddy", "dude", "mate", "man", "pal", "friend"],
     "forbid_any": ["peanut"],
     "note": "menu has manín->'bro, buddy (slang)' beside 'peanut'; "
             "shipped 'peanut' — a wrong pick, not a gap"},
    {"word": "fulete", "mode": "propose", "context": "tranca el fulete",
     "want_any": ["gun", "pistol", "piece", "firearm", "strap"],
     "forbid_any": ["fillet"],
     "note": "PR slang, a gun; shipped 'fillet'"},
    {"word": "tequi", "mode": "propose", "context": "tequi y limon",
     "want_any": ["tequila"], "forbid_any": ["kid"],
     "note": "tequila; shipped 'kid'"},
    {"word": "hermas", "mode": "propose", "context": "mi herma",
     "want_any": ["bro", "brother", "sis", "sister", "sibling", "buddy"],
     "forbid_any": ["mold"],
     "note": "elided hermano; shipped 'mold'"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm(text):
    """Lowercase, strip accents and apostrophes — lyric elisions vary."""
    s = unicodedata.normalize("NFD", str(text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in "'’´`,.!?¿¡\"":
        s = s.replace(ch, "")
    return " ".join(s.split())


class _BenchDone(Exception):
    """Raised after the batch is captured, to abort main() before it writes."""


def _sense_label(record, sid):
    ids = record.get("ids") or []
    senses = record.get("senses") or []
    if sid in ids:
        s = senses[ids.index(sid)] or {}
        ctx = s.get("context")
        return "[%s] %s%s" % (s.get("pos", ""), s.get("translation", ""),
                             " (%s)" % ctx if ctx else "")
    return "<not in menu>"


def _sense_pos(record, sid):
    ids = record.get("ids") or []
    senses = record.get("senses") or []
    if sid in ids:
        return str((senses[ids.index(sid)] or {}).get("pos") or "").upper()
    return ""


def _pick_call(record, calls, context):
    """Find the call for the flagged lyric line; fall back to the first call."""
    examples = record.get("examples") or []
    want = _norm(context)
    target_li = None
    for i, ex in enumerate(examples):
        if want and want in _norm(ex.get("spanish", "")):
            target_li = i
            break
    for call in calls:
        try:
            li = int(call.get("example")) - 1
        except (TypeError, ValueError):
            continue
        if target_li is not None and li == target_li:
            return call, li, False
    if calls:
        try:
            li = int(calls[0].get("example")) - 1
        except (TypeError, ValueError):
            li = 0
        return calls[0], li, True
    return None, None, True


def _judge(gold, record, call):
    """Return (passed, reason, gloss, chose_menu, proposed_gloss)."""
    if call is None:
        return False, "no call returned for this word", "", False, ""
    sense = call.get("sense")
    sid = sense if sense not in (None, "null", "", "None") else None
    proposed = str(call.get("proposed") or "").strip()
    ctype = str(call.get("type") or "")
    chose_menu = sid is not None and sid in (record.get("ids") or [])

    if gold["mode"] == "abstain":
        reason = str(call.get("abstain_reason") or "")
        wanted = gold.get("want_reason")
        if sid is None and not proposed and reason == wanted:
            return True, "", "[%s]" % reason, False, ""
        return (False, "abstain_reason=%r, wanted %r" % (reason or None, wanted),
                proposed, chose_menu, proposed)

    gloss = ""
    if chose_menu:
        ids, senses = record["ids"], record["senses"]
        gloss = str((senses[ids.index(sid)] or {}).get("translation") or "")
    elif proposed:
        gloss = proposed

    if not gloss:
        return False, "no sense chosen and no gloss proposed", "", chose_menu, proposed

    n = _norm(gloss)
    for bad in gold.get("forbid_any", []):
        if _norm(bad) and _norm(bad) in n:
            return (False, "returned the known-bad answer %r" % gloss, gloss,
                    chose_menu, proposed)

    if gold["mode"] == "menu":
        if not chose_menu:
            return (False, "invented %r instead of picking a menu sense" % gloss,
                    gloss, chose_menu, proposed)
        want_pos = gold.get("want_pos")
        if want_pos and _sense_pos(record, sid) != want_pos:
            return (False, "picked a %s sense, wanted %s"
                    % (_sense_pos(record, sid) or "?", want_pos),
                    gloss, chose_menu, proposed)
    elif gold["mode"] == "propose":
        if chose_menu:
            return (False, "picked menu sense %r; this is a genuine gap and "
                    "should have been proposed" % gloss, gloss, chose_menu, proposed)
        want_type = gold.get("want_type")
        if want_type and ctype != want_type:
            return (False, "type=%r, wanted %r" % (ctype or None, want_type),
                    gloss, chose_menu, proposed)

    if proposed and ctype != "proper_noun" and s6c._is_definitional(proposed):
        return (False, "proposal is prose (_is_definitional): %r" % proposed,
                gloss, chose_menu, proposed)

    want = gold.get("want_any")
    if want and not any(_norm(w) in n for w in want):
        return (False, "%r matches none of %s" % (gloss, want), gloss,
                chose_menu, proposed)
    return True, "", gloss, chose_menu, proposed


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run(words, gold_by_word, artist_dir, dry_run, gemini_model=None,
        prompt_id=None):
    captured = {"records": None, "results": None}
    real_call = s6c.classify_or_propose_batch

    def capturing_call(words_data, api_key, gemini_model, artist_context):
        captured["records"] = words_data
        captured["model"] = gemini_model
        captured["artist_context"] = artist_context
        results = real_call(words_data, api_key, gemini_model, artist_context)
        captured["results"] = results
        # Abort before the caller writes assignments / checkpoint / report.
        raise _BenchDone()

    # One batch so a single capture covers the whole gold set.
    s6c.SD_CLASSIFY_BATCH_SIZE = max(len(words), 1)
    s6c.classify_or_propose_batch = capturing_call

    argv = [
        "step_6c_assign_senses_gemini.py",
        "--artist-dir", artist_dir,
        "--sense-menu-file", "sense_menu/spanishdict.json",
        # Scratch name only: the run is aborted before anything is written.
        "--assignments-file", "sense_assignments/_bench_sense_prompt.json",
        "--method-name", "spanishdict-flash-lite",
        "--keyword-method-name", "spanishdict-keyword",
        "--auto-method-name", "spanishdict-auto",
        "--menu-source-label", "spanishdict",
        "--force",
        "--include-clitics",
    ]
    for w in words:
        argv += ["--word", w]
    if gemini_model:
        argv += ["--gemini-model", gemini_model]
    if prompt_id:
        argv += ["--prompt-id", prompt_id]
    if dry_run:
        argv.append("--dry-run-prompt")

    old_argv = sys.argv
    sys.argv = argv
    try:
        s6c.main()
    except _BenchDone:
        pass
    except SystemExit as e:
        if not dry_run and e.code not in (0, None):
            raise
    finally:
        sys.argv = old_argv
        s6c.classify_or_propose_batch = real_call

    if dry_run:
        return 0

    records = captured["records"]
    results = captured["results"]
    if records is None:
        print("\nERROR: no batch reached the classifier — every gold word was "
              "filtered out upstream (routing / flags / no examples).")
        return 1
    reached = {r["word"] for r in records}
    missing = [w for w in words if w not in reached]

    result_map = {}
    if isinstance(results, list):
        for o in results:
            if isinstance(o, dict) and o.get("word") is not None:
                result_map[o["word"]] = o.get("calls") or []
    elif results is None:
        print("\nERROR: classify_or_propose_batch returned None (API/parse failure).")
        return 1

    print("\n" + "=" * 72)
    print("BENCH: classify-or-propose prompt vs gold set  (model=%s)"
          % captured.get("model"))
    print("=" * 72)

    passes, fails = [], []
    invented_on_menu_case = []
    prose_cases = []
    for record in records:
        word = record["word"]
        gold = gold_by_word.get(word)
        calls = result_map.get(word, [])
        call, li, fellback = _pick_call(record, calls, gold.get("context", ""))
        examples = record.get("examples") or []

        print("\n--- %s  (lemma=%s, mode=%s) ---" % (word, record.get("lemma"),
                                                     gold["mode"]))
        print("  expectation: %s" % gold.get("note", ""))
        print("  menu (%d senses):" % len(record.get("senses") or []))
        for sid, s in zip(record.get("ids") or [], record.get("senses") or []):
            ctx = s.get("context")
            print("    %s: [%s] %s%s" % (sid, s.get("pos", ""),
                                         s.get("translation", ""),
                                         " (%s)" % ctx if ctx else ""))
        if not record.get("senses"):
            print("    (none — zero-sense gap-fill candidate)")
        if li is not None and 0 <= li < len(examples):
            ex = examples[li]
            print("  example %d%s: %s | %s [POS=%s]"
                  % (li + 1, "  (NO context match — first call used)" if fellback else "",
                     ex.get("spanish", ""), ex.get("english", ""), ex.get("pos")))
        if call is None:
            print("  ANSWER: <none>")
        else:
            sid = call.get("sense")
            print("  sense:       %s   %s" % (
                sid, _sense_label(record, sid) if sid not in (None, "null") else ""))
            print("  proposed:    %r" % (call.get("proposed") or None))
            print("  closest:     %s   %s" % (
                call.get("closest"), _sense_label(record, call.get("closest"))))
            print("  why_not_menu:%r" % (call.get("why_not_menu") or None))
            print("  type:        %r   pos: %r   pos_verdict: %r   construction: %r"
                  % (call.get("type") or None, call.get("pos") or None,
                     call.get("pos_verdict") or None,
                     call.get("construction") or None))

        ok, reason, gloss, chose_menu, proposed = _judge(gold, record, call)
        if ok:
            passes.append(word)
            print("  RESULT: PASS  -> %r" % gloss)
        else:
            fails.append((word, reason))
            print("  RESULT: FAIL  -> %s" % reason)
        if gold["mode"] == "menu" and not chose_menu:
            invented_on_menu_case.append(word)
        if proposed and str(call.get("type") or "") != "proper_noun" \
                and s6c._is_definitional(proposed):
            prose_cases.append((word, proposed))

    menu_cases = [r["word"] for r in records
                  if gold_by_word[r["word"]]["mode"] == "menu"]
    menu_hits = [w for w in menu_cases if w in passes]

    print("\n" + "=" * 72)
    print("SCORE")
    print("=" * 72)
    print("  overall:            %d/%d pass" % (len(passes), len(records)))
    print("  menu-recovery:      %d/%d  (cases where the menu already had a "
          "correct sense)" % (len(menu_hits), len(menu_cases)))
    print("  still inventing:    %d  %s"
          % (len(invented_on_menu_case), invented_on_menu_case or ""))
    print("  prose proposals:    %d  %s" % (len(prose_cases), prose_cases or ""))
    if fails:
        print("  FAILURES:")
        for w, why in fails:
            print("    %-9s %s" % (w, why))
    if missing:
        print("  NOT REACHED (filtered upstream): %s" % missing)
    return 0 if not fails else 2


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--words", default=None,
                    help="Comma-separated subset/override of the gold words.")
    ap.add_argument("--artist-dir", default=DEFAULT_ARTIST_DIR)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the exact prompt payload and exit without "
                         "calling the API (no key needed).")
    ap.add_argument("--gemini-model", default=None,
                    help="Registered Gemini model to benchmark.")
    ap.add_argument("--prompt-id", default=None,
                    help="Prompt/model provenance id. Use the matching revised "
                         "v2 id for a same-prompt comparison.")
    args = ap.parse_args()

    gold_by_word = {g["word"]: g for g in GOLD_SET}
    if args.words:
        words = [w.strip() for w in args.words.split(",") if w.strip()]
        for w in words:
            gold_by_word.setdefault(w, {"word": w, "mode": "any", "context": "",
                                        "note": "(ad-hoc word, no expectation)"})
    else:
        words = [g["word"] for g in GOLD_SET]
    sys.exit(run(words, gold_by_word, args.artist_dir, args.dry_run,
                 gemini_model=args.gemini_model, prompt_id=args.prompt_id))


if __name__ == "__main__":
    main()
