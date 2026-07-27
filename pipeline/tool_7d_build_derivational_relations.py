#!/usr/bin/env python3
"""Build a conservative, auditable derivational-lemma relation layer.

Diminutives and superlatives remain independent lexemes/cards. This tool only
links a derived lemma to a base when the suffix resolver and English sense
evidence agree, plus explicit reviewed inclusions. It never strips every
``-ito``/``-illo`` ending: that would corrupt lexical words such as ``bonito``,
``burrito``, ``gatillo`` and ``pastilla``.

Reads:
  Artists/spanish/vocabulary_master.json
  Data/Spanish/vocabulary.index.json
  Artists/curations/derivational_relations.json

Writes:
  Data/Spanish/layers/derivational_relations.json
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.util_4a_routing import resolve_derivation  # noqa: E402
from pipeline.util_7a_lemma_split import is_regular_plural_form  # noqa: E402
from pipeline.util_pipeline_meta import make_meta  # noqa: E402


DEFAULT_MASTER = PROJECT_ROOT / "Artists" / "spanish" / "vocabulary_master.json"
DEFAULT_NORMAL = PROJECT_ROOT / "Data" / "Spanish" / "vocabulary.index.json"
DEFAULT_CURATION = PROJECT_ROOT / "Artists" / "curations" / "derivational_relations.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "derivational_relations.json"

STEP_VERSION = 1
_MARKER_RE = re.compile(r"\b(?:diminutive|little|small|tiny)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOP = frozenset({
    "the", "a", "an", "to", "of", "in", "on", "for", "with", "and", "or",
    "little", "small", "tiny", "diminutive", "proper", "name", "person",
    "someone", "something", "one", "used", "term",
})


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _fold(value):
    text = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _tokens(gloss):
    return {
        token for token in _WORD_RE.findall(_fold(gloss))
        if len(token) >= 3 and token not in _STOP
    }


def _collect_glosses(master, normal_vocab):
    glosses = defaultdict(set)
    poses = defaultdict(set)
    for entry in list(master.values()) + list(normal_vocab):
        if not isinstance(entry, dict):
            continue
        lemma = (entry.get("lemma") or entry.get("word") or "").strip().lower()
        if not lemma:
            continue
        senses = entry.get("senses") or entry.get("meanings") or []
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            gloss = (sense.get("translation") or "").strip()
            if gloss:
                glosses[lemma].add(gloss)
            pos = (sense.get("pos") or "").strip().upper()
            if pos:
                poses[lemma].add(pos)
    return glosses, poses


def build_relations(master, normal_vocab, curation):
    glosses, poses = _collect_glosses(master, normal_vocab)
    known_lemmas = set(glosses) | {
        (entry.get("lemma") or entry.get("word") or "").strip().lower()
        for entry in master.values() if isinstance(entry, dict)
    }
    excluded = {
        str(value).strip().lower()
        for value in (curation.get("exclude") or []) if str(value).strip()
    }
    relations = {}

    for lemma in sorted(known_lemmas):
        if not lemma or lemma in excluded:
            continue
        base = resolve_derivation(lemma, known_lemmas)
        if not base or base == lemma or is_regular_plural_form(lemma, base):
            continue
        derived_glosses = glosses.get(lemma) or set()
        base_glosses = glosses.get(base) or set()
        marker_evidence = sorted(g for g in derived_glosses if _MARKER_RE.search(g))
        shared_tokens = sorted(set().union(*(_tokens(g) for g in derived_glosses))
                               & set().union(*(_tokens(g) for g in base_glosses))) \
            if derived_glosses and base_glosses else []
        if not marker_evidence and not shared_tokens:
            continue
        relation = "superlative" if "isim" in _fold(lemma) else "diminutive"
        record = {
            "base_lemma": base,
            "relation": relation,
            "source": "suffix+english-gloss",
        }
        if marker_evidence:
            record["evidence_glosses"] = marker_evidence[:3]
        if shared_tokens:
            record["shared_gloss_tokens"] = shared_tokens[:6]
        if poses.get(lemma):
            record["pos"] = sorted(poses[lemma])
        relations[lemma] = record

    for lemma, value in (curation.get("include") or {}).items():
        lemma = str(lemma).strip().lower()
        if not lemma or lemma in excluded or not isinstance(value, dict):
            continue
        base = str(value.get("base_lemma") or "").strip().lower()
        if not base:
            continue
        relations[lemma] = {
            "base_lemma": base,
            "relation": value.get("relation") or "derived",
            "source": "curated",
        }

    return relations


def main():
    parser = argparse.ArgumentParser(description="Build derivational lemma relations")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--normal-vocab", type=Path, default=DEFAULT_NORMAL)
    parser.add_argument("--curation", type=Path, default=DEFAULT_CURATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    master = _load(args.master, {})
    normal_vocab = _load(args.normal_vocab, [])
    curation = _load(args.curation, {})
    relations = build_relations(master, normal_vocab, curation)
    output = {
        "_meta": make_meta("build_derivational_relations", STEP_VERSION),
        "relations": relations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("Wrote %d relations -> %s" % (len(relations), args.output))


if __name__ == "__main__":
    main()
