#!/usr/bin/env python3
"""step_6e_assign_senses_calibrated — the calibrated WSD stack.

Three independent signals, combined by a learned ranker:

  1. GLOSS  — Gemini sense vectors from the English gloss, hubness-offset,
              scored as the gap between the top two (headword, POS) TUPLES.
  2. TOKEN  — BETO contextual vector of the target token, scored against the
              offline tuple prototypes built by tool_5c_build_token_prototypes.
  3. CLITIC — a `se`-only proclitic gate that prunes the wrong half of an
              X / Xse pair before the argmax.

Why a ranker rather than a better classifier: every method measured on this
problem is accurate in a different place and none of them can rank its own
output. Gemini flash-lite scores 92% and its self-reported certainty is flat.
Token prototypes beat gloss embeddings on accuracy and rank far worse. Only the
combination ranks. Held-out yield at 99% lemma+POS:

    class gap (what step_6d shipped before 2026-08-16)   0.0%
    tuple gap                                           22.9%
    calibrated, gloss signals only                      24.2%
    calibrated + BETO token features                    43.7%

v3 (2026-08-19): BETO decides the tuple wherever its own top-two prototype gap
is >= 0.02, and the gloss embedding then picks the leaf inside it. Hand-graded
on every one of the 88 picks this changes: 60 better, 13 worse, 15 neutral
(+47 net on 1,776 = +2.6pp). Ungated the same override is a wash (20/13/7 on 40
graded) -- the gate is the whole finding: BETO's noun bias on noun/verb
homographs (`robo`, `secuestro`, `falta`) lives exactly where its prototypes are
near-tied, and it was announcing that and nobody was listening. Query-locality
was tested in the same pass and REJECTED: on 24,675 gold rows, windowing the
query to the target +/-3 tokens costs 5.8pp of leaf accuracy (53.09%->47.31%)
and marking the target is noise (52.42%).

v2 (2026-08-19): the calibrator is retrained on `ok_leaf`, not `ok_tup`. The
tuple target was 88.7% accurate on gold and had almost nothing left to rank; the
exact leaf -- what the card actually prints, context note included -- is 53.1% on
the same rows. Held-out precision of the top decile went 82.5%->99.7% under the
old target and 49.4%->89.1% under the new one, i.e. the score now separates the
thing the learner reads. Band cuts are therefore precision targets on LEAF
correctness (90% high, 70% medium) and are not comparable to v1's.

`confidence` here is therefore P(correct) from the calibrator, NOT a cosine
margin — a different quantity from step_6d's output, which is why this writes a
distinct method id and prompt_id. step_6d is left untouched and still works.

Isolation: claims are stamped `sd-beto-cal-v1`, so a deck built with
`--prompt-policy testplaylist-beto-cal-pinned` contains this run and nothing
else. Best-evidence selection stays the default everywhere else.

Usage:
    python3 pipeline/step_6e_assign_senses_calibrated.py --dry-run
    python3 pipeline/step_6e_assign_senses_calibrated.py \
        --artist-dir "Artists/spanish/SpanishTestPlaylist"
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline"))

from pipeline.util_5c_token_prototypes import (  # noqa: E402
    DEFAULT_LAYERS, DEFAULT_MODEL, encode_spans, find_span, load_encoder,
    proto_key, reflexive_evidence, tuple_of)
from step_6d_assign_senses_embeddings import embed, gloss, norm_tr  # noqa: E402
from util_6a_assignment_format import stamp_example_ids  # noqa: E402
from util_pipeline_meta import display_path  # noqa: E402
from pipeline.util_6d_wsd_features import (  # noqa: E402
    FEATURE_VERSION, build as build_features, companion_features,
    structural_features)
from pipeline.util_6e_leaf_selection import (  # noqa: E402
    companion_of, companion_satisfied, renderable, select_display_leaf)
from pipeline.util_6a_pos_menu_filter import (  # noqa: E402
    sense_compatible_bridged)

LAYERS_DIR = REPO / "Data/Spanish/layers"
METHOD = "spanishdict-beto-cal-v5"
PROMPT_ID = "sd-beto-cal-v5"
# Escalated picks carry their own id: a Gemini-authored claim is different
# evidence from a locally-scored one and must stay separable in provenance.
PROMPT_ID_ESC = "sd-beto-cal-esc-v5"
ESC_MODEL = "gemini-3.5-flash-lite"
BG_N, BG_K = 1200, 40
# P(correct) cuts, derived from the calibrator's own held-out curve at train time
# and overridden by its manifest when present.
HIGH_CUT, MEDIUM_CUT = 0.90, 0.70


def ex_text(c):
    """Normal mode stores the sentence under `target`, artist mode under
    `spanish`. Both shapes are live, so accept either."""
    return c.get("target") or c.get("spanish") or ""


def ex_surface(c, word):
    """Artist rows carry the realised `surface`, which can differ from the
    lookup key. Aligning on the realised form is what the token path needs."""
    return c.get("surface") or word


def escalate(items, menus, model=ESC_MODEL, workers=8, allow_abstain=False):
    """Second opinion from Gemini on the low-confidence band.

    Measured on 300 stratified items: rescues 81.3% of what the embedding path
    gets wrong while damaging 5% of what it gets right, and its accuracy is FLAT
    (83-100%) across confidence deciles where the embedding path collapses
    100%->53%. They fail on different things, which is what makes escalation
    worth the call rather than just a pricier classifier.

    On disagreement the caller should take Gemini: measured right 80.3% against
    18.0% when the two differ. Gemini's own certainty is NOT usable as a ranking
    signal (flat ~92% at every self-reported level), so this only improves the
    pick -- never the confidence.

    items: [(word, sentence, [sense_id, ...])] -> {(word, sentence): sense_id}
    """
    import re as _re, threading
    from concurrent.futures import ThreadPoolExecutor
    from google import genai
    from google.genai import types

    key = None
    for line in (REPO / ".env").open(encoding="utf-8"):
        k, _, v = line.partition("=")
        if k.strip() == "GEMINI_API_KEY":
            key = v.strip().strip('"').strip("'")
    if not key:
        print("  no GEMINI_API_KEY — escalation skipped")
        return {}
    client = genai.Client(api_key=key)
    lock, done = threading.Lock(), [0]

    def ask(job):
        w, sent, sids = job
        lines = []
        for sid in sids:
            m = menus[w][sid]
            tr = (m.get("translation") or "").strip() or "(no gloss)"
            cx = (m.get("context") or "").strip()
            lines.append(f'{sid}\t{m.get("headword","")} ({m.get("pos","")})\t{tr}'
                         + (f"  [{cx}]" if cx else ""))
        abstain_clause = ("""If NONE of the listed senses fits this occurrence -- common in lyrics, where
regional slang is often missing from the dictionary entirely -- reply
{"id": null} rather than forcing the nearest one.
""" if allow_abstain else "")
        prompt = f"""You are disambiguating one Spanish word in one line of song lyrics.

Line: {sent}
Target word as it appears: "{w}"

Candidate senses (id, headword and part of speech, English gloss):
{chr(10).join(lines)}

Pick the single sense id that this occurrence of "{w}" has in this line.
The headword matters: a reflexive lemma (ending -se) is correct only if this
occurrence is genuinely reflexive or pronominal. Lyrics are informal — prefer the
everyday reading over a rare or literary one.

{abstain_clause}
Reply with ONLY compact JSON: {{"id": "<sense id>"}}"""
        for attempt in range(4):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0, max_output_tokens=2000))
                mm = _re.search(r"\{.*\}", (r.text or ""), _re.S)
                out = json.loads(mm.group(0)) if mm else {}
                with lock:
                    done[0] += 1
                    if done[0] % 100 == 0:
                        print(f"    escalated {done[0]:,}/{len(items):,}", flush=True)
                sid = out.get("id")
                if sid is None or (isinstance(sid, str) and sid.lower() == "null"):
                    return ((w, sent), "__ABSTAIN__")
                return ((w, sent), sid if sid in menus[w] else None)
            except Exception:
                if attempt == 3:
                    return ((w, sent), None)
                threading.Event().wait(3 * (attempt + 1))

    with ThreadPoolExecutor(workers) as exr:
        res = list(exr.map(ask, items))
    return {k: v for k, v in res if v}


ABSTAIN = "__ABSTAIN__"


def load_prototypes(base):
    d = base / "token_prototypes"
    if not (d / "proto.npy").exists():
        d = LAYERS_DIR / "token_prototypes"          # fall back to the shared asset
    if not (d / "proto.npy").exists():
        return None, {}, {}
    idx = json.loads((d / "proto_index.json").read_text(encoding="utf-8"))
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return np.load(d / "proto.npy"), idx, man


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", default="")
    ap.add_argument("--hub", default="off", choices=["off", "on"],
                    help="hubness offset. OFF by default: measured net negative "
                         "(80.06%%->80.34%%) and it systematically demotes function "
                         "words, flipping the winner on 13.3%% of assignments")
    ap.add_argument("--escalate", default="", choices=["", "low", "low+medium", "all"],
                    help="send these bands to Gemini flash-lite for a second opinion. "
                         "`all` is the measured best: judged on 600 rendered lyric "
                         "cards, escalated picks score 82.5%% against 67.1%% for the "
                         "local path, and the whole deck costs ~$0.08 to escalate")
    ap.add_argument("--escalate-budget", type=float, default=0.0,
                    help="escalate the worst N%% of picks by confidence instead of "
                         "whole bands. The band cuts are PRECISION targets read off "
                         "the calibrator's held-out curve (90%%/70%% leaf), so on a "
                         "hard corpus the low band is most of the deck -- 68%% of the "
                         "31-song playlist -- which makes the escalator the main path "
                         "rather than the fallback. A budget fixes the share instead: "
                         "0.20 sends the least confident fifth and nothing else.")
    ap.add_argument("--allow-abstain", action="store_true",
                    help="let escalation reply 'none of these fit' and DROP the "
                         "claim. Off by default: it trades a wrong card for a "
                         "hole, and inventing the missing sense (step_6c gap-fill) "
                         "is the better answer for slang SpanishDict lacks.")
    ap.add_argument("--tuple-vote", default="beto", choices=["off", "beto"],
                    help="who decides the (headword, POS) tuple. `off` ships: the "
                         "gloss-embedding argmax decides and BETO only contributes "
                         "an advisory `token_agrees` feature to the calibrator. "
                         "`beto` lets the token prototypes DECIDE the tuple wherever "
                         "the whole menu is scoreable, and the gloss embedding then "
                         "picks the best leaf inside it. Measured on dictionary gold "
                         "the token path is the better tuple picker (87.75%% vs "
                         "83.08%% on identical items); this is the plumbing that "
                         "lets that difference reach the card.")
    ap.add_argument("--tuple-vote-min-gap", type=float, default=0.02,
                    help="only let --tuple-vote beto override when BETO's own "
                         "top-two tuple prototype similarity gap is >= this. "
                         "0.0 (default) means override unconditionally, including "
                         "where the token path is visibly guessing.")
    ap.add_argument("--min-confidence", type=float, default=0.0,
                    help="DROP any pick whose calibrated P(leaf correct) is below "
                         "this. Speech mode selects its sentences from a corpus, so "
                         "an unconfident occurrence should be discarded and another "
                         "harvested -- not escalated. Measured on gold: rejecting "
                         "50%% takes tuple accuracy 82.4%%->98.5%%, though leaf "
                         "accuracy stays flat (leaf errors are near-synonym "
                         "shuffles that occur everywhere, not hard sentences).")
    ap.add_argument("--keep-best", type=int, default=0,
                    help="per word, keep at most N picks, highest confidence first "
                         "(0 = keep all that clear --min-confidence). Cards show a "
                         "couple of examples, so N=1 or 2 buys precision for free.")
    ap.add_argument("--gate", default="se-only",
                    choices=["off", "se-only", "permissive", "dative-aware"],
                    help="clitic gate. `se-only` (default, 96.8%% correct where it "
                         "fires) has NO opinion on a me/te cluster, so a dative "
                         "construction can win a reflexive leaf -- `me agradan los "
                         "humanos` carded as agradarse `to like each other`. "
                         "`dative-aware` decides that case on agreement: le/les are "
                         "never reflexive, a 3rd-person accusative clitic marks the "
                         "object, and a reflexive clitic must match the verb's person. "
                         "NOT SHIPPABLE as measured: 22 changed picks hand-graded 9 "
                         "better / 6 worse / 7 lateral. Three real bugs were found and "
                         "fixed while measuring it (dropped empty-cluster rule, "
                         "imperative syncretism inverting the agreement test, "
                         "de-accented lookup against an accented conjugation index), so "
                         "the ratio above is AFTER those fixes -- it is the flag's "
                         "honest score, not a broken one. Needs a graded sample where "
                         "fixes clearly exceed breaks, or removal.")
    ap.add_argument("--menu-prior", type=float, default=0.02,
                    help="head start for senses earlier in the SpanishDict menu, "
                         "which is ordered commonest-first. Added to the cosine as "
                         "PRIOR*DECAY^rank. Measured on 144 hand-labelled "
                         "OpenSubtitles sentences: 0 -> 65.3%%, 0.02 -> 84.7%%. Do "
                         "NOT raise it much: the score is a dial between the "
                         "sentence and the dictionary's ordering, and by 0.05 rare "
                         "senses (the true sense is not the top entry) collapse "
                         "from 54%% to 19%% while overall barely moves. 0.02 holds "
                         "them at 58%% WITH --pos-filter on. 0 restores v3.")
    ap.add_argument("--menu-prior-decay", type=float, default=0.5,
                    help="geometric decay of the menu prior down the list")
    ap.add_argument("--pos-filter", default="on", choices=["off", "on"],
                    help="prune leaves whose part of speech contradicts the tag "
                         "spaCy gave THIS occurrence (Data/.../example_pos.json, "
                         "written by tool_6a_tag_example_pos). step_6b and step_6c "
                         "have always done this; the v3 stack silently did not. "
                         "It is the only signal here that raises rare-sense "
                         "accuracy on its own (54%%->62%%), because it judges the "
                         "token's category and has no view on sense frequency.")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--max-encode", type=int, default=0,
                    help="encode at most N new sentences this run, save, and stop. "
                         "Lets a 25k-sentence BETO pass be done in sittings without "
                         "cooking the laptop; every chunk is written to the token "
                         "vector cache, so re-running continues where it left off.")
    ap.add_argument("--no-token", action="store_true", help="gloss signals only")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    base = (REPO / a.artist_dir / "data/layers") if a.artist_dir else LAYERS_DIR
    examples = json.loads((base / "examples_raw.json").read_text(encoding="utf-8"))
    raw = json.loads((base / "sense_menu/spanishdict.json").read_text(encoding="utf-8"))
    menus = {w: {sid: v for e in entries for sid, v in e.get("senses", {}).items()}
             for w, entries in raw.items()}
    out_path = Path(a.out) if a.out else base / "sense_assignments/spanishdict.json"

    words = [w for w in examples if examples[w] and menus.get(w)]
    n_ex = sum(len(examples[w]) for w in words)
    print(f"{len(words):,} words with a menu and at least one example; {n_ex:,} examples")

    P, pidx, pman = (None, {}, {}) if a.no_token else load_prototypes(base)
    if P is not None:
        print(f"prototypes: {len(pidx):,} from {pman.get('model')} "
              f"({len(pman.get('scoreable_words') or []):,} fully scoreable menus)")

    cal, cuts = None, (HIGH_CUT, MEDIUM_CUT)
    cal_dir = LAYERS_DIR / "wsd_calibrator"
    if (cal_dir / "calibrator.joblib").exists():
        import joblib
        cal = joblib.load(cal_dir / "calibrator.joblib")
        cman = json.loads((cal_dir / "manifest.json").read_text(encoding="utf-8"))
        fv = cman.get("feature_version")
        if fv != FEATURE_VERSION:
            raise SystemExit(
                f"calibrator was trained on feature_version {fv}, this build emits "
                f"{FEATURE_VERSION}. Retrain with tool_6d_train_calibrator.py — "
                f"silently scoring a mismatched vector is worse than stopping.")
        bc = cman.get("band_cuts") or {}
        cuts = (bc.get("high", HIGH_CUT), bc.get("medium", MEDIUM_CUT))
        print(f"calibrator loaded; band cuts high>={cuts[0]:.2f} medium>={cuts[1]:.2f}")
    else:
        print("NO CALIBRATOR — falling back to the raw tuple gap as confidence")

    # ---- gloss vectors
    sent_texts, sense_texts = [], []
    for w in words:
        sent_texts += [ex_text(c) for c in examples[w]]
        sense_texts += [gloss(w, m) for m in menus[w].values()]
    if a.dry_run:
        missing = 0
        try:
            cached = set(json.loads(
                (LAYERS_DIR / "sense_vectors/vec_index.json").read_text()))
            missing = len({t for t in sent_texts + sense_texts} - cached)
        except Exception:
            pass
        print(f"\n--dry-run: {len(set(sent_texts)):,} distinct sentences, "
              f"{len(set(sense_texts)):,} glosses; {missing:,} need embedding")
        return
    V = embed(sent_texts + sense_texts)

    rng = np.random.default_rng(0)
    uniq = list(dict.fromkeys(sent_texts))
    BG = np.stack([V[t] for t in (uniq if len(uniq) <= BG_N
                                  else [uniq[i] for i in rng.choice(len(uniq), BG_N, False)])])

    # ---- token vectors for this run's sentences (target is always present here)
    tokvec = {}
    if P is not None:
        spans = collections.defaultdict(dict)
        for w in words:
            for c in examples[w]:
                t = ex_text(c)
                sp = find_span(t, ex_surface(c, w), w, None)
                if sp:
                    spans[t][w] = sp
        sl = sorted(spans)
        # Token vectors are CACHED on disk and the encode is resumable. Encoding
        # 25k sentences is ~15 minutes of sustained GPU; without a cache that
        # cost is paid again on every re-run, including a re-run that only
        # changes a rejection threshold. Chunked with a save after each chunk so
        # an interrupted run keeps its progress.
        cdir = base / "token_vec_cache"
        cidx_p, cvec_p = cdir / "index.json", cdir / "vecs.npy"
        cidx = json.loads(cidx_p.read_text()) if cidx_p.exists() else {}
        cvec = np.load(cvec_p) if cvec_p.exists() else np.zeros((0, 768), np.float16)
        want = {f"{t}\t{w}" for t in sl for w in spans[t]}
        todo = sorted({t for t in sl
                       if any(f"{t}\t{w}" not in cidx for w in spans[t])})
        if cidx:
            print(f"token vector cache: {len(cidx):,} on disk, "
                  f"{len(want - set(cidx)):,} of {len(want):,} still needed")
        if todo:
            if a.max_encode > 0:
                todo = todo[:a.max_encode]
            print(f"encoding {len(todo):,} sentences with "
                  f"{pman.get('model', DEFAULT_MODEL)}", flush=True)
            tk, mdl = load_encoder(pman.get("model", DEFAULT_MODEL), a.device)
            CH = 2000
            for i in range(0, len(todo), CH):
                chunk = todo[i:i + CH]
                got = encode_spans(chunk, spans, tk, mdl, a.device,
                                   pman.get("layers", DEFAULT_LAYERS))
                rows, keys = [], []
                for (sent, w), v in got.items():
                    k = f"{sent}\t{w}"
                    if k in cidx:
                        continue
                    keys.append(k); rows.append(v.astype(np.float16))
                if rows:
                    start = cvec.shape[0]
                    cvec = np.concatenate([cvec, np.stack(rows)]) if start else np.stack(rows)
                    for n, k in enumerate(keys):
                        cidx[k] = start + n
                cdir.mkdir(parents=True, exist_ok=True)
                np.save(cvec_p, cvec)
                cidx_p.write_text(json.dumps(cidx), encoding="utf-8")
                print(f"  cached {min(i + CH, len(todo)):,}/{len(todo):,} "
                      f"({cvec.shape[0]:,} vectors on disk)", flush=True)
        still = len(want - set(cidx))
        if still and a.max_encode > 0:
            print(f"\n--max-encode reached: {still:,} sentences still uncached. "
                  f"Re-run the same command to continue; nothing else has been "
                  f"written, so this is safe to repeat.")
            return
        tokvec = {}
        for t in sl:
            for w in spans[t]:
                r = cidx.get(f"{t}\t{w}")
                if r is not None:
                    tokvec[(t, w)] = cvec[r].astype(np.float32)
        print(f"  {len(tokvec):,} token vectors")

    scoreable = set(pman.get("scoreable_words") or [])
    # start from what is already on disk so other methods survive
    out = {}
    if out_path.exists():
        try:
            out = json.loads(out_path.read_text(encoding="utf-8"))
            prior = {m for v in out.values() if isinstance(v, dict) for m in v}
            print(f"merging into {len(out):,} existing words "
                  f"({len(prior)} other method(s) preserved)")
        except Exception:
            out = {}
    # POS tags for THIS layer's examples, keyed word -> example index -> POS.
    # Absent word or absent index means "no reliable tag": the menu is left
    # whole, which is the same conservative rule filter_menu_by_pos uses.
    expos = {}
    if a.pos_filter != "off":
        ep_path = base / "example_pos.json"
        if ep_path.exists():
            expos = json.loads(ep_path.read_text(encoding="utf-8"))
            cov = sum(1 for w in words for i in range(len(examples[w]))
                      if str(i) in (expos.get(w) or {}))
            print(f"POS filter ON: {cov:,} of {n_ex:,} examples carry a tag "
                  f"({cov/max(n_ex,1):.0%})")
        else:
            print(f"POS filter requested but {display_path(ep_path)} is missing — "
                  f"run tool_6a_tag_example_pos.py. Continuing without it.")
    if a.menu_prior:
        print(f"menu prior ON: +{a.menu_prior:g} * {a.menu_prior_decay:g}^rank "
              f"on the SpanishDict menu order")

    bands, gated, tok_used, releaf = collections.Counter(), 0, 0, 0
    pos_filtered = 0
    voted = 0
    vote_suppressed = 0
    per_word, leaf_ctx = {}, {}

    for w in words:
        sids = list(menus[w])
        S = np.stack([V[gloss(w, menus[w][s])] for s in sids])
        Q = np.stack([V[ex_text(c)] for c in examples[w]])
        # The offset penalises senses that sit near everything. For a generic
        # high-frequency gloss ("una" (DET): a - singular) that centrality is
        # TRUE, not spurious, so it punishes the correct answer hardest. Measured
        # net negative on 16,016 gold items and it inverted `una` to a verb on
        # every occurrence in the first playlist run.
        hub = (np.zeros(S.shape[0], np.float32) if a.hub == "off"
               else np.sort(BG @ S.T, axis=0)[-min(BG_K, BG.shape[0]):].mean(0))
        C = Q @ S.T - hub[None, :]

        cid, cls, tid, tls = [], {}, [], {}
        for s in sids:
            m = menus[w][s]
            cid.append(cls.setdefault((m.get("pos", ""), norm_tr(m.get("translation"))), len(cls)))
            tid.append(tls.setdefault(tuple_of(w, m), len(tls)))
        cid, tid = np.array(cid), np.array(tid)
        n_cls, n_tup = len(cls), len(tls)
        tup_list = list(tls)
        is_se = np.array([tup_list[t][0].endswith("se") for t in tid])
        lems = {t[0] for t in tup_list}
        refl_amb = any(l + "se" in lems for l in lems)

        # per-tuple prototypes for this word, if the whole menu has them
        TP = None
        if P is not None and w in scoreable:
            try:
                TP = np.stack([P[pidx[proto_key(w, t)]] for t in tup_list])
            except KeyError:
                TP = None

        # SpanishDict lists a word's senses commonest-first, and that ordering is
        # the strongest single signal on real speech: on the 144-item labelled
        # OpenSubtitles panel the true sense is the FIRST menu entry 82% of the
        # time, against a mean menu of 8.3. The gloss argmax alone scores 65%
        # there because every sense starts equal, so `esta` in "¿Qué haremos esta
        # noche?" reached leaf 13, `este` (INTJ) "um".
        #
        # This was measured as useless in 2026-08 and the measurement was run on
        # the one corpus where it cannot help: the 24,675-item dictionary gold is
        # every sense's own example sentence, 1.02 examples per sense, so the
        # gold is UNIFORM over senses by construction and a frequency prior has
        # nothing to predict. See util_6d_wsd_features.build's `menu_pos` note,
        # which rejects it as a calibrator feature -- that rejection still holds,
        # and is a different claim from this one. A prior belongs in the SCORE,
        # not in the confidence.
        prior = a.menu_prior * (a.menu_prior_decay ** np.arange(len(sids),
                                                                dtype=np.float32))
        picks = []
        for j, c in enumerate(examples[w]):
            row = C[j]
            grow = row + prior if a.menu_prior else row
            if a.gate != "off" and refl_amb:
                ev = reflexive_evidence(ex_surface(c, w), ex_text(c), a.gate)
                if ev is not None and (is_se == ev).any():
                    grow = np.where(is_se == ev, grow, grow.min() - 1.0)
                    gated += 1
            # ---- POS filter: the tagger already knows this token's part of
            # speech, and step_6b/step_6c have always used it. The v3 stack
            # dropped it. It is the only signal measured here that raises
            # RARE-sense accuracy (54%->62% alone on the panel), because it rules
            # out wrong-category leaves without any view on how common they are
            # -- which is exactly what the prior needs beside it: with the prior
            # alone rare senses fall to 46%, with both they hold at 58%.
            if a.pos_filter != "off":
                ep = expos.get(w, {}).get(str(j)) or expos.get(w, {}).get(j)
                if ep:
                    keep = np.array([bool(sense_compatible_bridged(
                        menus[w][s].get("pos"), ep)) for s in sids])
                    if keep.any() and not keep.all():
                        grow = np.where(keep, grow, grow.min() - 1.0)
                        pos_filtered += 1

            k = int(np.argmax(grow))
            # ---- BETO decides the tuple, the gloss embedding decides the leaf
            # Restricting the argmax (rather than replacing it) keeps every leaf
            # comparison inside one score family: the token path has no view on
            # leaves at all -- 95.6% of leaves ship a single example, so
            # prototypes exist only per tuple -- and mixing a token score with a
            # gloss score in one argmax is the exact failure the prototype bench
            # documents.
            if a.tuple_vote == "beto" and TP is not None and n_tup > 1:
                qv = tokvec.get((ex_text(c), w))
                if qv is not None:
                    qsims = TP @ qv
                    qo = np.argsort(-qsims)
                    bt = int(qo[0])
                    # a tiny top-two gap means the token path is guessing; below
                    # the threshold we leave the embedding's argmax alone
                    qgap = float(qsims[qo[0]] - qsims[qo[1]])
                    same = np.flatnonzero(tid == bt)
                    if same.size:
                        if qgap >= a.tuple_vote_min_gap:
                            k = int(same[np.argmax(grow[same])])
                            voted += 1
                        else:
                            vote_suppressed += 1
            # gaps on UNGATED scores, signed against the pick: a gate must not be
            # able to manufacture confidence by deleting the runner-up
            tb = np.full(n_tup, -np.inf); np.maximum.at(tb, tid, row)
            tgap = (float(tb[tid[k]] - np.delete(tb, tid[k]).max()) if n_tup > 1 else 1.0)
            cb = np.full(n_cls, -np.inf); np.maximum.at(cb, cid, row)
            cgap = (float(cb[cid[k]] - np.delete(cb, cid[k]).max()) if n_cls > 1 else 1.0)

            tok_avail, tok_gap, tok_agree = 0.0, 0.0, 0.0
            q = tokvec.get((ex_text(c), w))
            if TP is not None and q is not None and n_tup > 1:
                sims = TP @ q
                o = np.argsort(-sims)
                tok_avail, tok_used = 1.0, tok_used + 1
                tok_gap = float(sims[o[0]] - sims[o[1]])
                tok_agree = float(int(o[0]) == tid[k])

            m = menus[w][sids[k]]
            pt = tuple_of(w, m)
            # Features describe the ARGMAX pick, always -- the calibrator was
            # trained on that distribution, and re-scoring it against a leaf the
            # trainer never saw would silently shift its input. Leaf selection
            # below changes what is displayed, never what is scored.
            feats = build_features(
                tuple_gap=tgap, class_gap=cgap, n_tup=n_tup, n_leaf=len(sids),
                sent_len=len(ex_text(c).split()), pred_tuple=pt,
                pred_empty=not (m.get("translation") or "").strip(),
                token=(tok_avail, tok_gap, tok_agree),
                companion=companion_features(w, ex_text(c), menus[w], sids[k], tuple_of),
                structural=structural_features(w, ex_text(c), menus[w], sids[k], tuple_of),
                menu_pos=list(menus[w]).index(sids[k]))
            conf = (float(cal.predict_proba(np.array([feats]))[0, 1]) if cal
                    else min(max(tgap, 0.0), 1.0))
            band = "high" if conf >= cuts[0] else "medium" if conf >= cuts[1] else "low"
            bands[band] += 1
            picks.append((sids[k], conf, tgap, band, j))
        per_word[w] = picks
        # Kept so leaf selection can run once, AFTER escalation has had its say:
        # Gemini picks a raw leaf off the same menu and lands on empty glosses
        # too, so gating only the embedding pick would leave half the defect.
        # Leaf repair scores with the SAME matrix the pick used, prior included.
        # Otherwise a repair inside the won tuple silently reverts to raw cosine
        # and can undo the prior on the one leaf it touches.
        leaf_ctx[w] = (sids, tid, (C + prior[None, :]) if a.menu_prior else C)

    # ---- escalate the weak band to Gemini
    esc_of = {}
    if a.escalate:
        want = ({"low"} if a.escalate == "low"
                else {"low", "medium"} if a.escalate == "low+medium"
                else {"low", "medium", "high"})
        if a.escalate_budget > 0:
            # Rank by confidence and take the worst N%. `want` is recomputed as
            # a membership test on the pick itself so the code below, which is
            # written against bands, keeps working unchanged.
            allc = sorted(cf for picks in per_word.values() for (_s, cf, *_r) in picks)
            cut = allc[min(int(len(allc) * a.escalate_budget), len(allc) - 1)]
            want = None
            in_scope = lambda cf, band: cf <= cut
            print(f"  budget {a.escalate_budget:.0%}: escalating picks with "
                  f"confidence <= {cut:.4f}")
        else:
            in_scope = lambda cf, band: band in want
        jobs = [(w, ex_text(examples[w][ji]), list(menus[w]))
                for w, picks in per_word.items()
                for (_sid, cf, _tg, band, ji) in picks if in_scope(cf, band)]
        print(f"\nescalating {len(jobs):,} {a.escalate}-band assignments to {ESC_MODEL} "
              f"(~${len(jobs)*347/1e6*0.10 + len(jobs)*30/1e6*0.40:.3f})", flush=True)
        esc_of = escalate(jobs, menus, allow_abstain=a.allow_abstain)
        print(f"  {len(esc_of):,} returned a valid sense")
        changed = abstained = 0
        for w, picks in per_word.items():
            for i, (sid, cf, tg, band, ji) in enumerate(picks):
                if not in_scope(cf, band):
                    continue
                new = esc_of.get((w, ex_text(examples[w][ji])))
                if new == ABSTAIN:
                    # No menu sense fits. Forcing the nearest one is how a
                    # missing slang sense becomes a confidently wrong card, so
                    # the claim is dropped instead. ~4% of real speech has no
                    # correct answer in the menu; lyrics will be worse.
                    picks[i] = None
                    abstained += 1
                    continue
                if new and new != sid:
                    changed += 1
                # take Gemini on disagreement: measured right 4.5x as often
                picks[i] = (new, cf, tg, band, ji, True) if new else (sid, cf, tg, band, ji, False)
        for w in per_word:
            per_word[w] = [p for p in per_word[w] if p is not None]
        print(f"  changed the pick on {changed:,}; abstained on {abstained:,} "
              f"(no menu sense fits -- likely missing slang)")
    for w, picks in per_word.items():
        per_word[w] = [(p + (False,))[:6] if len(p) == 5 else p for p in picks]

    # ---- leaf selection: which gloss the card actually shows
    # The tuple is settled above and is NOT touched here, so lemma+POS accuracy
    # and the calibrator's P(ok_tup) both stay exactly as measured. This only
    # stops a card rendering an empty English gloss, or a gloss whose
    # "used with X" note the line does not satisfy.
    releaf_empty = releaf_comp = 0
    for w, picks in per_word.items():
        sids, tid, C = leaf_ctx[w]
        pos = {s: i for i, s in enumerate(sids)}
        for i, (sid, conf, tgap, band, ji, was_esc) in enumerate(picks):
            k = pos.get(sid)
            if k is None:                       # escalation returned an unknown id
                continue
            old = menus[w][sid]
            kd = select_display_leaf(ex_text(examples[w][ji]), menus[w],
                                     sids, C[ji], k, tid)
            if kd == k:
                continue
            if not renderable(old):
                releaf_empty += 1
            elif not companion_satisfied(companion_of(old), ex_text(examples[w][ji])):
                releaf_comp += 1
            releaf += 1
            picks[i] = (sids[kd], conf, tgap, band, ji, was_esc)

    # ---- rejection: drop what is not confident enough, rather than escalating it
    if a.min_confidence > 0 or a.keep_best > 0:
        before = sum(len(v) for v in per_word.values())
        lost_words = 0
        for w, picks in per_word.items():
            keep = [p for p in picks if p[1] >= a.min_confidence]
            if a.keep_best > 0:
                keep = sorted(keep, key=lambda p: -p[1])[:a.keep_best]
                keep = sorted(keep, key=lambda p: p[4])       # restore example order
            if picks and not keep:
                lost_words += 1
            per_word[w] = keep
        after = sum(len(v) for v in per_word.values())
        print(f"\nrejection: kept {after:,} of {before:,} picks "
              f"({after/max(before,1):.0%}); {lost_words:,} words lost every example "
              f"(min-confidence {a.min_confidence}, keep-best {a.keep_best or 'all'})")

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    for w, picks in per_word.items():
        by_sense = {}
        for j, (sid, conf, tgap, band, _ji, was_esc) in enumerate(picks):
            pid = PROMPT_ID_ESC if was_esc else PROMPT_ID
            e = by_sense.setdefault((sid, pid),
                                    {"sense": sid, "examples": [], "confidence": [],
                                     "band": [], "tuple_gap": [], "method": METHOD,
                                     "prompt_id": pid, "run_ts": ts})
            e["examples"].append(j)
            e["confidence"].append(round(conf, 4))
            e["tuple_gap"].append(round(tgap, 4))
            e["band"].append(band)
        # MERGE, never replace. The layer is {word: {method: [...]}} and several
        # methods coexist per word -- overwriting the word entry destroys every
        # other classifier's claims and silently removes the deck's ability to
        # pick best evidence. Only this method's key is touched.
        out.setdefault(w, {})[METHOD] = list(by_sense.values())

    stamp_example_ids(out, examples)
    n = sum(len(v) for v in per_word.values())
    print(f"\nassigned {n:,} examples across {len(out):,} words  [{METHOD}]")
    print(f"  clitic gate fired on {gated:,}")
    print(f"  POS filter pruned the menu on {pos_filtered:,} "
          f"({pos_filtered/max(n,1):.0%})")
    print(f"  BETO decided the tuple on {voted:,} ({voted/max(n,1):.0%})")
    if a.tuple_vote == "beto":
        print(f"  BETO overrides suppressed by --tuple-vote-min-gap "
              f"{a.tuple_vote_min_gap:g}: {vote_suppressed:,}")
    print(f"  token prototypes used on {tok_used:,} ({tok_used/max(n,1):.0%})")
    print(f"  leaf reselected within the tuple on {releaf:,} "
          f"({releaf_empty:,} had no English gloss, {releaf_comp:,} broke a "
          f"'used with' note); tuple unchanged on all of them")
    # Count the bands of what was actually WRITTEN. `bands` is filled during
    # scoring, before rejection removes picks, so dividing it by the final count
    # printed "low 2,057 (126%)" on any run that rejected anything.
    written = collections.Counter(p[3] for picks in per_word.values() for p in picks)
    for b in ("high", "medium", "low"):
        print(f"  {b:<7} {written[b]:>6,} ({written[b]/max(n,1):.0%})")
    if sum(written.values()) != sum(bands.values()):
        dropped = sum(bands.values()) - sum(written.values())
        print(f"  ({dropped:,} scored picks were rejected or abstained before "
              f"this count; bands as scored were "
              + ", ".join(f"{b} {bands[b]:,}" for b in ("high", "medium", "low"))
              + ")")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Archive an immutable run before replacing the mutable layer -- the
    # canonical evidence contract. Without this a re-run destroys its own prior
    # output, which is exactly how the first run of this step wiped the
    # playlist's flash-lite claims.
    try:
        from util_evidence_store import archive_json_artifact
        # adapter must be a MAPPING -- build_run_manifest does dict(adapter).
        # Passing the bare method string raised ValueError on every run since
        # this step was written, so the artifact was archived but the manifest
        # and the profile pointer never were: exactly the re-run protection this
        # call exists to provide was silently absent.
        archive_json_artifact(base.parent / "evidence", "sense_assignments/spanishdict",
                              out, language="spanish",
                              adapter={"name": METHOD, "prompt_id": PROMPT_ID})
    except Exception as exc:
        print(f"  (archive skipped: {exc})")
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {display_path(out_path)}")


if __name__ == "__main__":
    main()
