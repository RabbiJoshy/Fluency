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
