"""Word alignment between a sentence and its translation.

One aligner, shared. Two things want it — the leaf corrector in
`step_6f_align_english_leaf` and the English-morphology work that will attach
inflected English to senses — and they must not drift into two tokenizations
that disagree about what "the aligned word" is.

The model is mBERT (`bert-base-multilingual-cased`, layer 8) driven by SimAlign,
which is what `tool_8g_benchmark_speech_alignment` measured on a frozen 60-row
panel: IterMax accepted 44 rows at 81.8% precision and 90.0% recall, strict
intersection 40 rows at 82.5%/82.5%. IterMax is the default here because the
extra recall is worth more than 0.7pp of precision to a corrector that only
fires where it finds a match at all.

Alignments are cached on disk by (model, layer, method, source, target), because
a single pass over the speech corpus is ~28k sentence pairs and the whole point
of caching the BETO encode was that a re-run should be cheap enough to sweep.
The cache is append-only and safe to interrupt.

Nothing here is Spanish-specific beyond the token regex, which admits the
accented Latin-1 range.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DEFAULT_MODEL = "bert-base-multilingual-cased"
DEFAULT_LAYER = 8
DEFAULT_METHOD = "itermax"

# SimAlign's own names for the three matching methods it returns.
_METHOD_KEYS = {"inter": "inter", "itermax": "itermax", "mwmf": "mwmf"}

SOURCE_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÿ]+(?:'[0-9A-Za-zÀ-ÿ]+)*")
TARGET_TOKEN_RE = re.compile(r"[0-9A-Za-z]+(?:'[0-9A-Za-z]+)*")

# Function words are never the head of a gloss and are never worth matching on.
# Kept deliberately short: this is a stoplist for HEAD selection, not a semantic
# filter, and every word removed here is a word the corrector can no longer fire
# on.
STOPWORDS = frozenset("""
a an the to of in on at by for with from as is are was were be been being
and or not no it its his her their your my our that this these those
""".split())

# Irregular English verb forms the suffix rules below cannot reach. Only the
# forms that actually appear as subtitle realisations of common gloss heads.
_IRREGULAR = {
    "gave": "give", "given": "give", "gives": "give", "giving": "give",
    "went": "go", "gone": "go", "goes": "go", "going": "go",
    "took": "take", "taken": "take", "takes": "take", "taking": "take",
    "made": "make", "makes": "make", "making": "make",
    "came": "come", "comes": "come", "coming": "come",
    "saw": "see", "seen": "see", "sees": "see", "seeing": "see",
    "said": "say", "says": "say", "saying": "say",
    "got": "get", "gotten": "get", "gets": "get", "getting": "get",
    "knew": "know", "known": "know", "knows": "know", "knowing": "know",
    "left": "leave", "leaves": "leave", "leaving": "leave",
    "told": "tell", "tells": "tell", "telling": "tell",
    "put": "put", "puts": "put", "putting": "put",
    "kept": "keep", "keeps": "keep", "keeping": "keep",
    "held": "hold", "holds": "hold", "holding": "hold",
    "found": "find", "finds": "find", "finding": "find",
    "thought": "think", "thinks": "think", "thinking": "think",
    "brought": "bring", "brings": "bring", "bringing": "bring",
    "ran": "run", "runs": "run", "running": "run",
    "began": "begin", "begun": "begin", "begins": "begin",
    "spoke": "speak", "spoken": "speak", "speaks": "speak",
    "heard": "hear", "hears": "hear", "hearing": "hear",
    "felt": "feel", "feels": "feel", "feeling": "feel",
    "lost": "lose", "loses": "lose", "losing": "lose",
    "paid": "pay", "pays": "pay", "paying": "pay",
    "sat": "sit", "sits": "sit", "sitting": "sit",
    "stood": "stand", "stands": "stand", "standing": "stand",
    "men": "man", "women": "woman", "children": "child", "people": "person",
    "feet": "foot", "teeth": "tooth", "lives": "life",
}


def tokenize_source(text):
    """Tokens of the source-language sentence, lowercased."""
    return tuple(m.group(0).lower() for m in SOURCE_TOKEN_RE.finditer(text or ""))


def tokenize_target(text):
    """Tokens of the translation, lowercased."""
    return tuple(m.group(0).lower() for m in TARGET_TOKEN_RE.finditer(text or ""))


def english_stem(token):
    """A crude English lemma, enough to match a subtitle word to a gloss head.

    Subtitles say "gave" where the gloss says "give". This is not a lemmatiser
    and does not try to be one: it handles the irregulars that actually occur
    plus the regular suffixes, and returns the token unchanged when it has no
    opinion. A wrong stem costs a missed match, never a wrong one, because the
    corrector requires an exact match on the stemmed form.
    """
    t = (token or "").lower()
    if t in _IRREGULAR:
        return _IRREGULAR[t]
    for suffix, replacement, min_stem in (
            ("ies", "y", 2), ("ied", "y", 2), ("ying", "ie", 2),
            ("ing", "", 4), ("ing", "e", 4),
            ("ed", "", 4), ("ed", "e", 4),
            ("es", "", 3), ("s", "", 3)):
        if t.endswith(suffix) and len(t) - len(suffix) >= min_stem:
            candidate = t[:-len(suffix)] + replacement
            if candidate:
                return candidate
    return t


def span_of(tokens, phrase_tokens):
    """Indices covered by every occurrence of `phrase_tokens` inside `tokens`."""
    if not phrase_tokens:
        return set()
    span = set()
    width = len(phrase_tokens)
    for start in range(len(tokens) - width + 1):
        if tokens[start:start + width] == tuple(phrase_tokens):
            span.update(range(start, start + width))
    return span


def find_target_span(tokens, *surfaces):
    """Indices of the target word, trying each candidate surface in turn.

    Artist rows carry a realised `surface` that can differ from the lookup key,
    and the key is the fallback. Returns an empty set when neither appears —
    the caller must treat that as "no opinion", not as "no alignment".
    """
    for surface in surfaces:
        if not surface:
            continue
        span = span_of(tokens, tokenize_source(surface))
        if span:
            return span
    return set()


class Alignment:
    """One aligned sentence pair."""

    __slots__ = ("source_tokens", "target_tokens", "pairs")

    def __init__(self, source_tokens, target_tokens, pairs):
        self.source_tokens = tuple(source_tokens)
        self.target_tokens = tuple(target_tokens)
        self.pairs = tuple(tuple(p) for p in pairs)

    def target_indices_for(self, source_indices):
        wanted = set(source_indices)
        return sorted({j for i, j in self.pairs if i in wanted})

    def target_words_for(self, source_indices):
        return [self.target_tokens[j] for j in self.target_indices_for(source_indices)
                if 0 <= j < len(self.target_tokens)]


class WordAligner:
    """SimAlign, loaded once, with an append-only disk cache.

    `cache_dir` is optional; without it the aligner still works and simply
    re-aligns every pair. With it, a re-run of a corpus-wide pass is I/O.
    """

    def __init__(self, cache_dir=None, model=DEFAULT_MODEL, layer=DEFAULT_LAYER,
                 method=DEFAULT_METHOD, device="cpu"):
        if method not in _METHOD_KEYS:
            raise ValueError(f"unknown matching method {method!r}; "
                             f"expected one of {sorted(_METHOD_KEYS)}")
        self.model = model
        self.layer = layer
        self.method = method
        self.device = device
        self._aligner = None
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._cache = {}
        self._dirty = 0
        if self.cache_dir and self._cache_path().exists():
            self._cache = json.loads(self._cache_path().read_text(encoding="utf-8"))

    # -- cache -------------------------------------------------------------
    def _cache_path(self):
        stem = f"{self.model.replace('/', '_')}.L{self.layer}.{self.method}"
        return self.cache_dir / f"align.{stem}.json"

    def _key(self, source_text, target_text):
        raw = f"{source_text}\x00{target_text}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:20]

    def flush(self):
        if not (self.cache_dir and self._dirty):
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path().write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        self._dirty = 0

    @property
    def cached(self):
        return len(self._cache)

    # -- alignment ---------------------------------------------------------
    def _load(self):
        if self._aligner is None:
            from simalign import SentenceAligner
            self._aligner = SentenceAligner(
                model=self.model, token_type="bpe",
                matching_methods="mai", device=self.device)
        return self._aligner

    def is_cached(self, source_text, target_text):
        return self._key(source_text, target_text) in self._cache

    def align(self, source_text, target_text):
        """Align one pair. Returns None when either side tokenizes to nothing."""
        source_tokens = tokenize_source(source_text)
        target_tokens = tokenize_target(target_text)
        if not source_tokens or not target_tokens:
            return None
        key = self._key(source_text, target_text)
        pairs = self._cache.get(key)
        if pairs is None:
            raw = self._load().get_word_aligns(
                list(source_tokens), list(target_tokens))
            pairs = raw[_METHOD_KEYS[self.method]]
            self._cache[key] = [list(p) for p in pairs]
            self._dirty += 1
        return Alignment(source_tokens, target_tokens, pairs)
