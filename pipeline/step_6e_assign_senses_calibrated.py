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
from pipeline.util_6d_wsd_features import (  # noqa: E402
    FEATURE_VERSION, build as build_features, companion_features)

LAYERS_DIR = REPO / "Data/Spanish/layers"
METHOD = "spanishdict-beto-cal-v1"
PROMPT_ID = "sd-beto-cal-v1"
# Escalated picks carry their own id: a Gemini-authored claim is different
# evidence from a locally-scored one and must stay separable in provenance.
PROMPT_ID_ESC = "sd-beto-cal-esc-v1"
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


def escalate(items, menus, model=ESC_MODEL, workers=8):
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
        prompt = f"""You are disambiguating one Spanish word in one line of song lyrics.

Line: {sent}
Target word as it appears: "{w}"

Candidate senses (id, headword and part of speech, English gloss):
{chr(10).join(lines)}

Pick the single sense id that this occurrence of "{w}" has in this line.
The headword matters: a reflexive lemma (ending -se) is correct only if this
occurrence is genuinely reflexive or pronominal. Lyrics are informal — prefer the
everyday reading over a rare or literary one.

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
                return ((w, sent), sid if sid in menus[w] else None)
            except Exception:
                if attempt == 3:
                    return ((w, sent), None)
                threading.Event().wait(3 * (attempt + 1))

    with ThreadPoolExecutor(workers) as exr:
        res = list(exr.map(ask, items))
    return {k: v for k, v in res if v}


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
    ap.add_argument("--escalate", default="", choices=["", "low", "low+medium"],
                    help="send these bands to Gemini flash-lite for a second opinion")
    ap.add_argument("--gate", default="se-only",
                    choices=["off", "se-only", "permissive"])
    ap.add_argument("--device", default="mps")
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
        print(f"encoding {len(sl):,} sentences with "
              f"{pman.get('model', DEFAULT_MODEL)}", flush=True)
        tk, mdl = load_encoder(pman.get("model", DEFAULT_MODEL), a.device)
        tokvec = encode_spans(sl, spans, tk, mdl, a.device,
                              pman.get("layers", DEFAULT_LAYERS))
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
    bands, gated, tok_used = collections.Counter(), 0, 0
    per_word = {}

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

        picks = []
        for j, c in enumerate(examples[w]):
            row = C[j]
            grow = row
            if a.gate != "off" and refl_amb:
                ev = reflexive_evidence(ex_surface(c, w), ex_text(c), a.gate)
                if ev is not None and (is_se == ev).any():
                    grow = np.where(is_se == ev, row, row.min() - 1.0)
                    gated += 1

            k = int(np.argmax(grow))
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
            feats = build_features(
                tuple_gap=tgap, class_gap=cgap, n_tup=n_tup, n_leaf=len(sids),
                sent_len=len(ex_text(c).split()), pred_tuple=pt,
                pred_empty=not (m.get("translation") or "").strip(),
                token=(tok_avail, tok_gap, tok_agree),
                companion=companion_features(w, ex_text(c), menus[w], sids[k], tuple_of),
                menu_pos=list(menus[w]).index(sids[k]))
            conf = (float(cal.predict_proba(np.array([feats]))[0, 1]) if cal
                    else min(max(tgap, 0.0), 1.0))
            band = "high" if conf >= cuts[0] else "medium" if conf >= cuts[1] else "low"
            bands[band] += 1
            picks.append((sids[k], conf, tgap, band, j))
        per_word[w] = picks

    # ---- escalate the weak band to Gemini
    esc_of = {}
    if a.escalate:
        want = {"low"} if a.escalate == "low" else {"low", "medium"}
        jobs = [(w, ex_text(examples[w][ji]), list(menus[w]))
                for w, picks in per_word.items()
                for (_sid, _cf, _tg, band, ji) in picks if band in want]
        print(f"\nescalating {len(jobs):,} {a.escalate}-band assignments to {ESC_MODEL} "
              f"(~${len(jobs)*347/1e6*0.10 + len(jobs)*30/1e6*0.40:.3f})", flush=True)
        esc_of = escalate(jobs, menus)
        print(f"  {len(esc_of):,} returned a valid sense")
        changed = 0
        for w, picks in per_word.items():
            for i, (sid, cf, tg, band, ji) in enumerate(picks):
                if band not in want:
                    continue
                new = esc_of.get((w, ex_text(examples[w][ji])))
                if new and new != sid:
                    changed += 1
                # take Gemini on disagreement: measured right 4.5x as often
                if new:
                    picks[i] = (new, cf, tg, band, ji, True)
                else:
                    picks[i] = (sid, cf, tg, band, ji, False)
        print(f"  changed the pick on {changed:,}")
    for w, picks in per_word.items():
        per_word[w] = [(p + (False,))[:6] if len(p) == 5 else p for p in picks]

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
    print(f"  token prototypes used on {tok_used:,} ({tok_used/max(n,1):.0%})")
    for b in ("high", "medium", "low"):
        print(f"  {b:<7} {bands[b]:>6,} ({bands[b]/max(n,1):.0%})")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Archive an immutable run before replacing the mutable layer -- the
    # canonical evidence contract. Without this a re-run destroys its own prior
    # output, which is exactly how the first run of this step wiped the
    # playlist's flash-lite claims.
    try:
        from util_evidence_store import archive_json_artifact
        archive_json_artifact(base.parent / "evidence", "sense_assignments/spanishdict",
                              out, language="spanish", adapter=METHOD)
    except Exception as exc:
        print(f"  (archive skipped: {exc})")
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
