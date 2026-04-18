#!/usr/bin/env python3
"""
Step 3: Normalize elision variants in vocab_evidence.json before sense assignment.

Language-aware (`--language {spanish,french}`, default `spanish`).

### Spanish (`--language spanish`, default)

Three merge families handled here (all preserve `surface` on each example so
the front-end can render the original lyric form):

1. Explicit mapping (`elision_mapping.json`): manual and auto-generated
   `elided_only` / `elision_pair` / `same_word_dup` entries.
2. D-elision regex family: Caribbean dropped-d past participles and
   derivatives in masculine/feminine × singular/plural:
       -a'o  -> -ado   (burla'o -> burlado)
       -a'a  -> -ada   (pega'a  -> pegada)
       -a'os -> -ados  (pega'os -> pegados)
       -a'as -> -adas  (moja'as -> mojadas)
       -í'o  -> -ido   (jodí'o  -> jodido)
       -í'a  -> -ida   (prendí'a-> prendida)
       -í'os -> -idos  (escondí'os-> escondidos)
       -í'as -> -idas  (mordí'as-> mordidas)
3. Trailing-apostrophe tiebreaker: for `word'` not covered above, try
   restoring a dropped final consonant (`s`, `d`, `z`, `r`, `l`, `n`) and
   merge if exactly one candidate exists in normal_vocab.

Also ambiguous: `ve'` splits per-example into `vez` (noun) vs `ves` (verb)
using the preceding-word disambiguator.

### French (`--language french`)

Splits leading apostrophe clitics that the step-2 tokenizer keeps glued to
the next word (French writes `l'amour` as one orthographic token). The
clitic is dropped; its counts and examples merge into the bare base word.
The original surface form is preserved on each example.

Handled proclitics: `l' j' d' qu' n' m' s' t' c' jusqu' puisqu' lorsqu'`
(plus their capitalized and curly-apostrophe variants).

Input:  data/word_counts/vocab_evidence.json
Output: data/elision_merge/vocab_evidence_merged.json

Usage:
  .venv/bin/python3 pipeline/artist/step_3a_merge_elisions.py --artist-dir "Artists/spanish/Bad Bunny"
  .venv/bin/python3 pipeline/artist/step_3a_merge_elisions.py --artist-dir "Artists/french/TestPlaylist" --language french
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

import argparse
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_1a_artist_config import SHARED_DIR

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 4
STEP_VERSION_NOTES = {
    1: "s-elision + d-elision merge with corpus_count summing",
    2: "+ plural/feminine d-elision, double-elision chain (-ao' → -ao → -ado), trailing-apos tiebreaker",
    3: "+ --language flag, French proclitic splitter (l'/j'/d'/qu' etc.)",
    4: "french: consult Wiktionary phrase/contraction index; promote known apos "
       "forms (c'est, j'ai, qu'il, n'est, s'il, …) to own entries instead of "
       "stripping them into a verb form",
}

# ---------------------------------------------------------------------------
# French proclitics the step-2 tokenizer glues onto the following word.
# Listed longest-first so `jusqu'` is matched before `qu'`.
# ---------------------------------------------------------------------------
FRENCH_PROCLITICS = (
    "puisqu", "lorsqu", "jusqu",
    "qu", "l", "d", "j", "n", "m", "s", "t", "c",
)
_FRENCH_APOS = "'\u2019"  # straight + curly
_FRENCH_PROCLITIC_RE = re.compile(
    r"^(" + "|".join(FRENCH_PROCLITICS) + r")[" + _FRENCH_APOS + r"](.+)$",
    re.IGNORECASE,
)


def french_strip_proclitic(word):
    """If `word` starts with a French proclitic + apostrophe, return the
    stripped tail; else None.

    Examples:
      l'amour      -> amour
      j'aime       -> aime
      qu'il        -> il
      jusqu'à      -> à
      L'Amour      -> amour (lowercased)
    """
    m = _FRENCH_PROCLITIC_RE.match(word)
    if not m:
        return None
    tail = m.group(2).lower().strip()
    # Guard: don't split if tail is empty or just an apostrophe (malformed).
    if not tail or all(ch in _FRENCH_APOS for ch in tail):
        return None
    return tail


# ---------------------------------------------------------------------------
# French apostrophized phrase/contraction index (Wiktionary-driven tiering).
#
# Wiktionary gives dedicated entries to stable apostrophized chunks like
# `c'est` (it is), `j'ai` (I have), `qu'il`, `s'il`, `n'est`, `m'a`, …. Those
# deserve their own cards — the old "strip everything" rule was merging
# `c'est` into `est`, which is why the sense menu for a 293-count verb form
# was showing "[ADJ] east". We consult this index before stripping: if a form
# is here, it survives as its own entry; otherwise we fall through to the
# original proclitic splitter (the right call for `l'amour`, `j'aime`, …).
# ---------------------------------------------------------------------------

# POS tags we accept as "this apostrophized form is a real lexical unit".
# `contraction` covers c'est/n'est/m'a/qu'il/s'il/…; `phrase` covers j'ai,
# s'il vous plaît, je m'appelle, etc.; the function-word POS tags catch
# `d'`/`qu'` apocopic forms that Wiktionary classifies as adverb/preposition.
_FRENCH_APOS_PHRASE_POS = frozenset((
    "phrase", "contraction", "proverb",
    "adv", "prep", "intj", "conj", "pron",
))

# Cache pickle schema version for the French apos-phrase index.
_APOS_CACHE_VERSION = 1
_FRENCH_APOS_NORM_RE = re.compile(r"\u2019")


def _normalize_apos(word):
    """Normalize curly apostrophes to straight so the index keys join cleanly."""
    return _FRENCH_APOS_NORM_RE.sub("'", word.lower())


def load_french_apos_phrases(kaikki_path):
    """Scan the French kaikki dump for apostrophized phrase/contraction entries.

    Returns ``{normalized_word: (pos, cleaned_gloss_line)}``. The gloss is
    the first sense's gloss verbatim (for diagnostic printing); step_5c
    does its own proper cleaning when it builds the sense menu, so this is
    not the learner-facing text.

    Pickle-cached alongside the kaikki file so subsequent runs are instant.
    """
    import gzip
    import pickle
    cache_path = Path(str(kaikki_path) + ".apos_phrases.cache.pkl")
    if cache_path.exists() and cache_path.stat().st_mtime >= Path(kaikki_path).stat().st_mtime:
        try:
            with open(cache_path, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, tuple) and len(data) == 2 and data[0] == _APOS_CACHE_VERSION:
                return data[1]
        except (EOFError, pickle.UnpicklingError, ValueError):
            pass  # Rebuild below.

    if not os.path.exists(kaikki_path):
        print(f"  (no French kaikki file at {kaikki_path}; skipping phrase tier)")
        return {}

    print(f"  Scanning French kaikki for apostrophized phrase entries ({kaikki_path.name})...")
    index = {}
    with gzip.open(kaikki_path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            word = (item.get("word") or "").lower()
            pos = item.get("pos") or ""
            if not word or pos not in _FRENCH_APOS_PHRASE_POS:
                continue
            if "'" not in word and "\u2019" not in word:
                continue
            senses = item.get("senses") or []
            gloss = ""
            for s in senses:
                glosses = s.get("glosses") or []
                if glosses:
                    gloss = glosses[0][:120]
                    break
            key = _normalize_apos(word)
            # First-seen wins. Multiple POS entries for the same apostrophized
            # word (e.g. `il y a` as prep and as verb) all resolve to the same
            # cue for step_3a; the richer sense menu lookup happens in step_5c.
            index.setdefault(key, (pos, gloss))

    with open(cache_path, "wb") as f:
        pickle.dump((_APOS_CACHE_VERSION, index), f)
    print(f"    {len(index)} apostrophized phrase/contraction entries indexed")
    return index

PIPELINE_DIR = None
IN_PATH = None
OUT_PATH = None
MAPPING_PATH = None
MAX_EXAMPLES = 10

# ---------------------------------------------------------------------------
# D-elision patterns: masc/fem × sing/pl. Ordered longest-suffix-first so
# '-a'os'/'-í'as' are matched before '-a'o'/'-í'a'.
# ---------------------------------------------------------------------------
D_ELISION_RULES = [
    (re.compile(r"^(.+)a'os$"), "ados"),
    (re.compile(r"^(.+)a'as$"), "adas"),
    (re.compile(r"^(.+)í'os$"), "idos"),
    (re.compile(r"^(.+)í'as$"), "idas"),
    (re.compile(r"^(.+)a'o$"), "ado"),
    (re.compile(r"^(.+)a'a$"), "ada"),
    (re.compile(r"^(.+)í'o$"), "ido"),
    (re.compile(r"^(.+)í'a$"), "ida"),
]

D_ELISION_EXCEPTIONS = frozenset()

# Trailing-apostrophe consonant candidates (s-elision is most common; others
# cover verda' → verdad, die' → diez, comé' → comer).
_TRAILING_APOS_RESTORES = ("s", "d", "z", "r", "l", "n")

# ---------------------------------------------------------------------------
# Ambiguous elisions — split per-example using the preceding word
# ---------------------------------------------------------------------------
DISAMBIG_METHOD = "preceding_word"

AMBIGUOUS_ELISIONS = {
    "ve'": {
        "noun_target": "vez",
        "verb_target": "ves",
        "noun_preceding": frozenset({
            "una", "otra", "cada", "tal", "última", "primera",
            "esta", "esa", "la", "qué", "alguna", "cualquier",
        }),
        "noun_pos": frozenset({"NOUN"}),
    },
}

_TOKENIZE_RE = re.compile(r"[\w''\u2019]+", re.UNICODE)
_spacy_nlp = None


def _get_spacy_trf():
    global _spacy_nlp
    if _spacy_nlp is None:
        import spacy
        _spacy_nlp = spacy.load("es_dep_news_trf")
    return _spacy_nlp


def _preceding_word(line, target_form):
    tokens = _TOKENIZE_RE.findall(line.lower())
    for i, tok in enumerate(tokens):
        if tok == target_form and i > 0:
            return tokens[i - 1]
    return None


def _disambiguate_example(amb, word, line):
    if DISAMBIG_METHOD == "spacy_trf":
        nlp = _get_spacy_trf()
        doc = nlp(line)
        for tok in doc:
            if tok.text.lower().rstrip("'\u2019") == word.rstrip("'\u2019"):
                if tok.pos_ in amb["noun_pos"]:
                    return amb["noun_target"]
                return amb["verb_target"]
        return amb["verb_target"]

    prev = _preceding_word(line, word)
    if prev in amb["noun_preceding"]:
        return amb["noun_target"]
    return amb["verb_target"]


def d_elision_canonical(word):
    """If word is a d-elision (any masc/fem × sing/pl form), return
    (canonical, display) else None.
    """
    if word in D_ELISION_EXCEPTIONS:
        return None
    for pattern, suffix in D_ELISION_RULES:
        m = pattern.match(word)
        if m:
            return (m.group(1) + suffix, word)
    return None


def double_elision_canonical(word):
    """Chain: `parao'` → `parao` → `parado`.

    A word ending in `'` where the stripped stem is itself a d-elision target.
    Returns (canonical, display) or None. Display is the original double-elided
    form.
    """
    if not word.endswith("'"):
        return None
    stripped = word[:-1]
    d = d_elision_canonical(stripped)
    if d:
        return (d[0], word)
    return None


def trailing_apos_restore(word, known_set):
    """For a `word'` form not covered by other rules, try restoring a dropped
    final consonant (s/d/z/r/l/n). Returns (canonical, display) if exactly
    one restoration hits the known-word set; None otherwise.

    The "exactly one" rule guards against ambiguity (e.g. pue' → pues vs pued
    vs puer). If two restorations both hit, we give up and leave the word
    alone for step 4 to handle.
    """
    if not word.endswith("'") or len(word) < 3:
        return None
    stem = word[:-1]
    hits = [stem + c for c in _TRAILING_APOS_RESTORES if (stem + c) in known_set]
    if len(hits) == 1:
        return (hits[0], word)
    return None


def load_merge_targets(mapping_path):
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    targets = {}
    for r in mapping:
        if r["action"] != "merge":
            continue
        if r["merge_type"] == "elision_pair":
            targets[r["elided_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
            targets[r["full_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
        elif r["merge_type"] == "elided_only":
            targets[r["elided_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
    return targets


def load_known_vocab():
    """Load the normal-mode Spanish vocabulary for trailing-apos tiebreaker."""
    vocab_path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "vocabulary.json")
    if not os.path.isfile(vocab_path):
        return set()
    with open(vocab_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(entry["word"].lower() for entry in data)


def merge_evidence(data, targets, known_vocab):
    """Merge entries. Returns a new list. Each example carries `surface`."""
    groups = defaultdict(lambda: {"count": 0, "examples": [], "display_form": None,
                                  "variants": {}})

    stats = {"mapping": 0, "d_elision": 0, "double_elision": 0, "trailing_apos": 0, "unmerged": 0}

    for entry in data:
        word = entry["word"]
        count = entry.get("corpus_count", 0)
        examples = entry.get("examples", [])

        # Ambiguous elisions: split per example
        if word in AMBIGUOUS_ELISIONS and word in targets:
            amb = AMBIGUOUS_ELISIONS[word]
            display = targets[word]["display_form"]
            target_example_counts = defaultdict(int)
            for ex in examples:
                key = _disambiguate_example(amb, word, ex.get("line", ""))
                groups[key]["display_form"] = display
                ex["surface"] = word
                groups[key]["examples"].append(ex)
                target_example_counts[key] += 1
            n_examples = len(examples)
            if n_examples > 0:
                for tgt, ex_count in target_example_counts.items():
                    proportional = round(count * ex_count / n_examples)
                    groups[tgt]["count"] += proportional
                    groups[tgt]["variants"][word] = (
                        groups[tgt]["variants"].get(word, 0) + proportional
                    )
            else:
                fallback = amb["verb_target"]
                groups[fallback]["count"] += count
                groups[fallback]["variants"][word] = (
                    groups[fallback]["variants"].get(word, 0) + count
                )
            stats["mapping"] += 1
            continue

        key = None
        display = None
        source = "unmerged"

        if word in targets:
            t = targets[word]
            key = t["target_word"]
            display = t["display_form"]
            source = "mapping"
        else:
            # Try d-elision (plural/feminine/masculine)
            d = d_elision_canonical(word)
            if d:
                key, display = d[0], d[1]
                source = "d_elision"
            else:
                # Try double-elision: parao' → parado
                dd = double_elision_canonical(word)
                if dd:
                    key, display = dd[0], dd[1]
                    source = "double_elision"
                else:
                    # Try trailing-apos tiebreaker
                    tap = trailing_apos_restore(word, known_vocab)
                    if tap:
                        key, display = tap[0], tap[1]
                        source = "trailing_apos"

        if key is None:
            key = word
            display = word
            source = "unmerged"

        stats[source] = stats.get(source, 0) + 1

        if groups[key]["display_form"] is None:
            groups[key]["display_form"] = display

        for ex in examples:
            ex["surface"] = ex.get("surface", word)  # preserve pre-existing surface from step 2a

        groups[key]["count"] += count
        groups[key]["examples"].extend(examples)
        groups[key]["variants"][word] = groups[key]["variants"].get(word, 0) + count

    # Build output, deduplicating examples by song
    out = []
    for word, g in groups.items():
        seen_songs = set()
        deduped = []
        for ex in g["examples"]:
            song_id = ex["id"].split(":")[0] if "id" in ex else None
            if song_id and song_id in seen_songs:
                continue
            if song_id:
                seen_songs.add(song_id)
            deduped.append(ex)

        entry = {
            "word": word,
            "corpus_count": g["count"],
            "examples": deduped[:MAX_EXAMPLES],
        }
        if g["display_form"] and g["display_form"] != word:
            entry["display_form"] = g["display_form"]
        if len(g["variants"]) >= 2:
            entry["variants"] = g["variants"]

        out.append(entry)

    out.sort(key=lambda e: -e["corpus_count"])
    return out, stats


def merge_evidence_french(data, apos_phrase_index=None):
    """French elision handling.

    Tiering:
      Tier A — `apos_phrase_index` says this apostrophized form has a
               dedicated Wiktionary entry (c'est, j'ai, qu'il, n'est, s'il,
               m'a, t'as, jusqu'au, …). Keep as its own entry; the sense
               menu built in step_5c will use the phrase/contraction gloss.
      Tier B — `french_strip_proclitic` recognises a proclitic + tail
               (l'amour, j'aime, l'autre, d'un). Strip the proclitic, merge
               counts/examples into the bare tail (original Tier B behaviour).
      Tier C — unchanged: non-apostrophe tokens fall through as-is.

    ``apos_phrase_index`` is the dict returned by ``load_french_apos_phrases``.
    Passing ``None`` disables Tier A and falls back to the pre-tier-4 strip-
    everything behaviour (useful for tests).
    """
    groups = defaultdict(lambda: {"count": 0, "examples": [], "display_form": None,
                                  "variants": {}})
    stats = {"apos_phrase_kept": 0, "proclitic_split": 0, "unmerged": 0}
    apos_phrase_index = apos_phrase_index or {}
    phrase_hits = []  # (word, pos, gloss, count) for reporting

    for entry in data:
        word = entry["word"]
        count = entry.get("corpus_count", 0)
        examples = entry.get("examples", [])

        # Tier A: Wiktionary knows this apostrophized form as a lexical unit.
        # Preserve it as its own entry — the sense menu step will pull the
        # `contraction`/`phrase` gloss, and the learner gets "it is" on the
        # card for c'est instead of "east" (est|adj) via the old merge.
        apos_hit = None
        if ("'" in word) or ("\u2019" in word):
            apos_hit = apos_phrase_index.get(_normalize_apos(word))

        if apos_hit is not None:
            key = word
            display = word
            source = "apos_phrase_kept"
            phrase_hits.append((word, apos_hit[0], apos_hit[1], count))
        else:
            tail = french_strip_proclitic(word)
            if tail is not None:
                key = tail
                display = word  # keep the original l'amour as display
                source = "proclitic_split"
            else:
                key = word
                display = word
                source = "unmerged"
        stats[source] = stats.get(source, 0) + 1

        if groups[key]["display_form"] is None:
            groups[key]["display_form"] = display

        for ex in examples:
            ex["surface"] = ex.get("surface", word)

        groups[key]["count"] += count
        groups[key]["examples"].extend(examples)
        groups[key]["variants"][word] = groups[key]["variants"].get(word, 0) + count

    # Build output (dedup by song — matches Spanish behaviour)
    out = []
    for word, g in groups.items():
        seen_songs = set()
        deduped = []
        for ex in g["examples"]:
            song_id = ex["id"].split(":")[0] if "id" in ex else None
            if song_id and song_id in seen_songs:
                continue
            if song_id:
                seen_songs.add(song_id)
            deduped.append(ex)

        entry = {
            "word": word,
            "corpus_count": g["count"],
            "examples": deduped[:MAX_EXAMPLES],
        }
        if g["display_form"] and g["display_form"] != word:
            entry["display_form"] = g["display_form"]
        if len(g["variants"]) >= 2:
            entry["variants"] = g["variants"]
        out.append(entry)

    out.sort(key=lambda e: -e["corpus_count"])
    return out, stats


def main():
    global PIPELINE_DIR, IN_PATH, OUT_PATH, MAPPING_PATH

    parser = argparse.ArgumentParser(description="Step 3: Merge elisions and normalize variants")
    parser.add_argument("--artist-dir", required=True, help="Path to artist data directory")
    parser.add_argument("--language", choices=("spanish", "french"), default="spanish",
                        help="Language-specific normalization (default: spanish)")
    args = parser.parse_args()

    PIPELINE_DIR = os.path.abspath(args.artist_dir)
    IN_PATH = Path(os.path.join(PIPELINE_DIR, "data", "word_counts", "vocab_evidence.json"))
    OUT_PATH = Path(os.path.join(PIPELINE_DIR, "data", "elision_merge", "vocab_evidence_merged.json"))
    MAPPING_PATH = Path(os.path.join(SHARED_DIR, "elision_mapping.json"))

    print(f"Loading {IN_PATH} ...")
    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {len(data)} entries")

    # French: simpler flow, no Spanish-specific loading.
    if args.language == "french":
        print(f"Language: french (apos-phrase tier + proclitic splitter)")
        french_kaikki_path = Path(
            os.path.join(_PROJECT_ROOT, "Data", "French", "Senses",
                         "wiktionary", "kaikki-french.jsonl.gz")
        )
        apos_index = load_french_apos_phrases(french_kaikki_path)
        merged, stats = merge_evidence_french(data, apos_phrase_index=apos_index)

        os.makedirs(os.path.dirname(str(OUT_PATH)), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        write_sidecar(OUT_PATH, make_meta("merge_elisions", STEP_VERSION,
                                          extra={"language": "french",
                                                 "apos_phrase_index_size": len(apos_index)}))

        print(f"\nWrote {len(merged)} entries -> {OUT_PATH}")
        print(f"  Reduced by {len(data) - len(merged)} entries")
        print(f"  Merge sources:")
        for k in ("apos_phrase_kept", "proclitic_split", "unmerged"):
            print(f"    {k}: {stats.get(k, 0)}")
        print("\n=== Top 20 merged entries ===")
        for e in merged[:20]:
            df = e.get("display_form", "")
            display = f" (display: {df})" if df else ""
            print(f"  {e['word']}{display} — {e['corpus_count']} occurrences, {len(e['examples'])} examples")
        return

    # Spanish (default)
    print(f"Loading merge mapping from {MAPPING_PATH} ...")
    targets = load_merge_targets(MAPPING_PATH)
    print(f"  {len(targets)} words have merge targets")

    print("Loading normal-mode vocabulary for trailing-apos tiebreaker ...")
    known_vocab = load_known_vocab()
    print(f"  {len(known_vocab)} canonical forms")

    merged, stats = merge_evidence(data, targets, known_vocab)

    os.makedirs(os.path.dirname(str(OUT_PATH)), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    write_sidecar(OUT_PATH, make_meta("merge_elisions", STEP_VERSION))

    print(f"\nWrote {len(merged)} entries -> {OUT_PATH}")
    print(f"  Reduced by {len(data) - len(merged)} entries")
    print(f"  Merge sources:")
    for k in ("mapping", "d_elision", "double_elision", "trailing_apos", "unmerged"):
        print(f"    {k}: {stats.get(k, 0)}")
    if AMBIGUOUS_ELISIONS:
        print(f"  Ambiguous elision method: {DISAMBIG_METHOD}")

    # Report ambiguous elision splits
    for amb_word, amb in AMBIGUOUS_ELISIONS.items():
        noun_t = amb["noun_target"]
        verb_t = amb["verb_target"]
        noun_entry = next((e for e in merged if e["word"] == noun_t), None)
        verb_entry = next((e for e in merged if e["word"] == verb_t), None)
        noun_from_amb = 0
        verb_from_amb = 0
        if noun_entry and noun_entry.get("variants"):
            noun_from_amb = noun_entry["variants"].get(amb_word, 0)
        if verb_entry and verb_entry.get("variants"):
            verb_from_amb = verb_entry["variants"].get(amb_word, 0)
        if noun_from_amb or verb_from_amb:
            print(f"  Ambiguous '{amb_word}' split: "
                  f"{noun_from_amb} → {noun_t}, {verb_from_amb} → {verb_t}")

    print("\n=== Top 20 merged entries ===")
    for e in merged[:20]:
        df = e.get("display_form", "")
        display = f" (display: {df})" if df else ""
        print(f"  {e['word']}{display} — {e['corpus_count']} occurrences, {len(e['examples'])} examples")


if __name__ == "__main__":
    main()
