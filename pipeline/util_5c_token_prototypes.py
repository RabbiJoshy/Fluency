#!/usr/bin/env python3
"""util_5c_token_prototypes — token alignment and contextual encoding.

Shared by `tool_5c_build_token_prototypes` (builds the offline asset) and
`pipeline/wsd_harness/bench_token_prototypes.py` (measures it), so the two can
never drift apart on how a target token is located or encoded.

A tuple prototype is the mean contextual vector of the target token across the
example sentences of one `(headword, POS)` tuple. Measured 2026-08-17 on 9,731
held-out items — see Data/Spanish/Intermediates/wsd_sense_harness/README.md §7/§9:

    encoder      prototype acc   calibrated yield@99%
    mBERT            83.26%          44.4%
    BETO             87.75%          53.7%   <- shipped
    XLM-R base       82.68%          40.9%
    XLM-R large      78.06%          31.6%

Bigger is worse, and not a layer artifact. Monolingual Spanish pretraining beats
both scale and multilinguality here, so DEFAULT_MODEL is BETO and DEFAULT_LAYERS
is the mean of the last 4 hidden layers.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np

DEFAULT_MODEL = "dccuchile/bert-base-spanish-wwm-cased"
DEFAULT_LAYERS = 4
DEFAULT_MIN_EXAMPLES = 2
WORD_RE = re.compile(r"[a-záéíóúüñ0-9]+")


def deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def tuple_of(word: str, sense: dict) -> tuple[str, str]:
    """The (lemma, POS) pair learner knowledge is recorded at."""
    return ((sense.get("headword") or word).strip().lower(),
            (sense.get("pos") or "").strip())


def find_span(sentence: str, word: str, headword: str, revconj: dict | None):
    """Character span of the token realising `headword` in `sentence`.

    Order matters. The surface form wins when present, because that is the
    occurrence production actually disambiguates. Otherwise the conjugation
    layer resolves an inflected verb to its lemma (`Unió` -> `unir`), covering
    the 61k of 96k leaves that are verbs. A stem test mops up nouns and
    adjectives, where Spanish inflection is suffixing.

    Returns (start, end) or None.
    """
    low = sentence.lower()
    dl = deacc(sentence)
    spans = [(m.start(), m.end()) for m in WORD_RE.finditer(low)]

    w = deacc(word)
    for a, b in spans:                                    # 1. exact surface form
        if deacc(sentence[a:b]) == w:
            return a, b

    hw = headword[:-2] if headword.endswith("se") and len(headword) > 3 else headword
    if revconj:
        for a, b in spans:                                # 2. conjugation layer
            for entry in revconj.get(sentence[a:b].lower(), ()) or ():
                if (entry.get("lemma") or "").lower() in (hw, headword):
                    return a, b

    hwd = deacc(hw)                                       # 3. stem prefix
    stem = hwd[:-2] if len(hwd) > 4 else hwd
    best = None
    if len(stem) >= 4:
        for a, b in spans:
            t = dl[a:b]
            if t.startswith(stem) and (best is None or len(t) < best[2]):
                best = (a, b, len(t))
    return (best[0], best[1]) if best else None


def load_encoder(model_name: str = DEFAULT_MODEL, device: str = "mps"):
    from transformers import AutoTokenizer, AutoModel
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name, output_hidden_states=True)
    model.eval().to(device)
    return tok, model


def encode_spans(sentences, spans_by_sent, tok, model, device="mps",
                 layers=DEFAULT_LAYERS, batch=64, max_length=96, progress=None):
    """One forward pass per sentence; extract every requested span from it.

    `spans_by_sent` maps sentence -> {key: (start, end)}. Returns
    {(sentence, key): L2-normalised float32 vector}. Sub-word pieces overlapping
    the span are mean-pooled.
    """
    import torch

    out = {}
    with torch.no_grad():
        for i in range(0, len(sentences), batch):
            chunk = sentences[i:i + batch]
            enc = tok(chunk, return_tensors="pt", padding=True, truncation=True,
                      max_length=max_length, return_offsets_mapping=True)
            offsets = enc.pop("offset_mapping")
            enc = {k: v.to(device) for k, v in enc.items()}
            hs = model(**enc).hidden_states
            reps = torch.stack(hs[-layers:]).mean(0).cpu().numpy()
            for bi, sent in enumerate(chunk):
                om = offsets[bi].numpy()
                for key, (a, b) in spans_by_sent.get(sent, {}).items():
                    sel = [t for t in range(len(om))
                           if om[t][1] > om[t][0] and om[t][0] < b and om[t][1] > a]
                    if not sel:
                        continue
                    v = reps[bi][sel].mean(0)
                    n = float(np.linalg.norm(v))
                    if n > 0:
                        out[(sent, key)] = (v / n).astype(np.float32)
            if progress and (i // batch) % 25 == 0:
                progress(min(i + batch, len(sentences)), len(sentences))
    return out


def proto_key(word: str, t: tuple[str, str]) -> str:
    """Flat key for the persisted prototype index."""
    return f"{word}\t{t[0]}\t{t[1]}"


CLITICS = {"me", "te", "se", "nos", "os", "lo", "la", "le", "los", "las", "les"}
REFL = {"me", "te", "se", "nos", "os"}
# A genuine verb+enclitic must leave an INFINITIVE or GERUND when the pronoun is
# stripped. Testing the suffix alone over-fires badly: "parte" ends in `ar`+`te`,
# as do muerte / suerte / fuerte / arte. Imperative+clitic (levántate) is missed
# rather than guessed, which is the safe direction for a gate.
ENCLITIC_PRONOUNS = ("se", "me", "te", "nos", "os")
VERB_STEM = re.compile(r"(?:[aei]r|[aáeéií]ndo)$")


def _is_verb_enclitic(w: str) -> bool:
    for suf in ENCLITIC_PRONOUNS:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            if VERB_STEM.search(w[:-len(suf)]):
                return True
    return False


def reflexive_evidence(word: str, sentence: str, mode: str = "se-only"):
    """Is a reflexive clitic bound to THIS occurrence of the target form?

    Spanish proclitics form a tight cluster immediately before the verb
    (no + se + 2nd + 1st + 3rd), so scanning backwards over consecutive clitic
    pronouns is the whole parse. Enclitics ride on the form itself.

    Returns True (reflexive lemma), False (plain lemma) or None (no opinion).

    Measured on the production-shaped slice: 'se-only' fires on 64% of
    reflexive-ambiguous items and is 96.8% correct; 'permissive' fires on 68% at
    94.0%, because me/te/nos are usually INDIRECT OBJECTS (`me lo dio` is `dar`,
    not `darse`). se-only is the default for that reason.

    Worth knowing before reaching for a trained replacement: a perfect oracle is
    worth only +4.3pp accuracy on this slice, and this regex already captures
    100% of the YIELD headroom -- regex and oracle both land at 24.5%.
    """
    w = deacc(word)
    toks = WORD_RE.findall(deacc(sentence))
    if w not in toks:
        # production always classifies a sentence containing the form; guessing
        # when it is absent is worthless
        return None
    # No enclitic branch. Deciding "is this word a verb+clitic" from the string
    # alone over-fires on parte / muerte / suerte (all end in -Xr + te), and the
    # conjugation lexicon cannot adjudicate either -- verbecc generates a
    # paradigm for "par", so `par` is listed as an infinitive. The branch was
    # near-worthless anyway: when the lookup key really is `hacerse`, its menu
    # holds only -se tuples, so there is nothing for the gate to prune.
    i = toks.index(w)
    cluster = []
    j = i - 1
    while j >= 0 and toks[j] in CLITICS:
        cluster.append(toks[j])
        j -= 1
    if mode == "dative-aware":
        # the ORIGINAL form, not the de-accented one: conjugation_reverse is
        # keyed with accents, so passing `w` here silently no-ops the agreement
        # test on salvó / pensará / disculpó and every other accented form.
        return _dative_aware(word.lower(), cluster)
    want = REFL if mode == "permissive" else {"se"}
    if any(c in want for c in cluster):
        return True
    return False if not cluster or mode == "permissive" else None


# 3rd person reflexive is ALWAYS `se`, so le/les are dative by definition; and a
# reflexive clitic must agree in person with its verb, which the conjugation
# lexicon already knows. `se-only` returns None on a me/te cluster (no opinion)
# and `permissive` returns True (measured worse: 94.0% vs 96.8%, because me/te
# are usually indirect objects). This third mode decides the me/te case on
# agreement instead of guessing either way -- `me agradan los humanos` is 3rd
# person with a 1st person clitic, so it cannot be reflexive.
_ACC3 = {"lo", "la", "los", "las"}
_PERSON = {"me": "1", "nos": "1", "te": "2", "os": "2"}
_CONJ_REV = None


def _person_of(form):
    """Person(s) the surface form can be, from the conjugation lexicon."""
    global _CONJ_REV
    if _CONJ_REV is None:
        import json
        p = LAYERS_DIR / "conjugation_reverse.json" if "LAYERS_DIR" in globals() else None
        try:
            from pathlib import Path
            p = Path(__file__).resolve().parents[1] / "Data/Spanish/layers/conjugation_reverse.json"
            _CONJ_REV = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _CONJ_REV = {}
    ents = _CONJ_REV.get(form) or []
    # Imperative is excluded when any other reading exists. `agrada` is 3rd
    # person present AND 2nd person imperative (the usted form), so including it
    # makes the person set {2,3}, which overlaps a `te` clitic and defeats the
    # agreement test on exactly the gustar-type verbs this exists to catch. A
    # subordinate clause is not an imperative context.
    non_imp = [e for e in ents if "imperativo" not in (e.get("mood") or "")]
    use = non_imp or ents
    return {(e.get("person") or "")[:1] for e in use if e.get("person")}


def _dative_aware(form, cluster):
    if "se" in cluster:
        return True
    if any(c in {"le", "les"} for c in cluster):
        return False                      # 3rd person reflexive is `se`, never `le`
    if any(c in _ACC3 for c in cluster):
        return False                      # `me lo dio` -- the 3rd person clitic is the object
    if not cluster:
        # Same assertion se-only makes: no proclitic at all means no reflexive
        # reading. Returning None here instead silently stops the gate pruning
        # -se leaves on every clitic-free line, which is a regression, not a
        # refinement.
        return False
    persons = {_PERSON[c] for c in cluster if c in _PERSON}
    if not persons:
        return None
    verb = _person_of(form)
    if verb and not (persons & verb):
        return False                      # clitic and verb disagree -> dative, not reflexive
    return True if verb else None
