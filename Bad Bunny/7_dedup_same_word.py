#!/usr/bin/env python3
"""
Deduplicates BadBunnyvocabulary.json by merging entries that share
the same word but have different (often hallucinated) lemmas.

For each group of entries with the same word, picks the best lemma
using a scoring heuristic, merges all meanings/examples into a single
entry, and drops the duplicates.

Run AFTER 6_fill_translation_gaps.py and BEFORE 8_flag_cognates.py.

Usage:
    python3 "Bad Bunny/7_dedup_same_word.py"
"""

import json
import re
from collections import defaultdict
from pathlib import Path

VOCAB_PATH = Path("Bad Bunny/BadBunnyvocabulary.json")

# ── Hallucination detection ──────────────────────────────────────

# Patterns that indicate a hallucinated lemma:
# spaCy invents verb infinitives by slapping -ir/-ar/-er onto stems
BOGUS_VERB_RE = re.compile(
    r"^.{2,}(ir|ar|er|ír|ér)$"
)

# Known real Spanish infinitives that we should NOT flag as bogus.
# Add to this set as needed.
KNOWN_REAL_VERBS = {
    "ir", "ser", "ver", "dar", "estar", "haber", "hacer", "poder",
    "tener", "decir", "querer", "saber", "poner", "venir", "salir",
    "pasar", "llamar", "llegar", "llevar", "dejar", "seguir", "creer",
    "hablar", "pensar", "quedar", "vivir", "sentir", "mirar", "caer",
    "dormir", "morir", "escribir", "abrir", "andar", "durar", "cantar",
    "bailar", "tirar", "tocar", "meter", "comer", "beber", "correr",
    "perder", "romper", "mover", "coger", "subir", "partir", "pedir",
    "servir", "repetir", "vestir", "medir", "reír", "oír", "huir",
    "jugar", "soñar", "volar", "llorar", "gritar", "rezar", "amar",
    "odiar", "matar", "robar", "fumar", "gastar", "ganar", "perdonar",
    "olvidar", "recordar", "buscar", "encontrar", "esperar", "cambiar",
    "usar", "parar", "acabar", "empezar", "comenzar", "terminar",
    "necesitar", "gustar", "faltar", "importar", "parecer", "conocer",
    "nacer", "crecer", "existir", "sufrir", "compartir", "permitir",
    "recibir", "producir", "traducir", "conducir", "reducir",
    "brillar", "perrear", "bellaquear", "janguear", "gozar", "disfrutar",
    "disparar", "tumbar", "trepar", "prendar", "prender", "encender",
    "apagar", "cerrar", "curar", "rezar", "soltar", "juntar",
}


def is_likely_hallucinated(lemma: str, word: str) -> bool:
    """
    Return True if the lemma looks like a spaCy hallucination.
    """
    if not lemma:
        return True

    # Identity lemma is always real
    if lemma == word:
        return False

    # Known real verb → not hallucinated
    if lemma in KNOWN_REAL_VERBS:
        return False

    # If it looks like a verb infinitive but isn't in our known list,
    # AND the word itself doesn't end the same way (i.e., it's not
    # actually a verb form), flag it as suspicious
    if BOGUS_VERB_RE.match(lemma):
        # Check if the lemma is just the word + random verb ending
        # e.g., "bella" → "bellar", "dímelo" → "dímelir"
        stem = lemma
        for suffix in ("ir", "ar", "er", "ír", "ér"):
            if lemma.endswith(suffix):
                stem = lemma[:-len(suffix)]
                break
        # If the stem IS the word (or very close), it's hallucinated
        if word.startswith(stem) and len(stem) >= len(word) - 2:
            return True

    return False


def score_entry(entry: dict, word: str) -> tuple:
    """
    Score an entry for "best lemma" selection.
    Higher = better. Returns a tuple for comparison.

    Priority:
    1. Non-hallucinated lemma (huge bonus)
    2. Lemma in KNOWN_REAL_VERBS (bonus for real verbs)
    3. Higher match count (from most_frequent_lemma_instance logic)
    4. More meanings
    5. Earlier rank (tiebreaker)
    """
    lemma = entry.get("lemma", "")
    hallucinated = is_likely_hallucinated(lemma, word)
    is_known_verb = lemma in KNOWN_REAL_VERBS
    match_count = sum(
        len(m.get("examples", []))
        for m in entry.get("meanings", [])
    )
    # Use the original match count from pos_summary if available
    # (stored transiently in step 4 but removed; fall back to example count)
    n_meanings = len(entry.get("meanings", []))
    rank = entry.get("rank", 99999)

    return (
        0 if hallucinated else 1,       # non-hallucinated wins
        1 if is_known_verb else 0,       # known real verb wins
        match_count,                     # more matches wins
        n_meanings,                      # more meanings wins
        -rank,                           # earlier rank wins (tiebreaker)
    )


def merge_entries(entries: list[dict], word: str) -> dict:
    """
    Merge a group of entries for the same word into a single entry.
    Picks the best entry as the base, then pools meanings from all entries.
    """
    # Score and sort
    scored = sorted(
        enumerate(entries),
        key=lambda x: score_entry(x[1], word),
        reverse=True,
    )

    best_idx, best = scored[0]

    # Start with a copy of the best entry
    merged = json.loads(json.dumps(best))

    # Collect all meanings, dedup by POS
    seen_pos = {m["pos"] for m in merged.get("meanings", [])}
    for idx, entry in scored[1:]:
        for m in entry.get("meanings", []):
            if m["pos"] not in seen_pos:
                seen_pos.add(m["pos"])
                merged["meanings"].append(json.loads(json.dumps(m)))

    # Carry forward any flags that are True in ANY entry
    for flag in ("is_english", "is_interjection", "is_propernoun", "is_transparent_cognate"):
        if any(e.get(flag, False) for e in entries):
            merged[flag] = True

    # Carry forward display_form if any entry has it
    for e in entries:
        if e.get("display_form") and not merged.get("display_form"):
            merged["display_form"] = e["display_form"]

    merged["most_frequent_lemma_instance"] = True

    return merged


def main():
    if not VOCAB_PATH.exists():
        raise FileNotFoundError(f"Input not found: {VOCAB_PATH}")

    data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    print(f"📥 Loaded {len(data)} entries")

    # Group by word
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in data:
        groups[entry["word"]].append(entry)

    dup_count = sum(1 for entries in groups.values() if len(entries) > 1)
    extra_count = sum(len(entries) - 1 for entries in groups.values() if len(entries) > 1)
    print(f"🔍 Found {dup_count} words with duplicates ({extra_count} extra entries)")

    # Merge
    out = []
    merges_done = 0
    for word in groups:
        entries = groups[word]
        if len(entries) == 1:
            out.append(entries[0])
        else:
            merged = merge_entries(entries, word)
            out.append(merged)
            merges_done += 1

            # Log interesting merges
            lemmas = [e["lemma"] for e in entries]
            winner = merged["lemma"]
            losers = [l for l in lemmas if l != winner]
            if losers:
                print(f"  ✂ {word}: kept «{winner}», dropped {losers}")

    # Re-rank
    out.sort(key=lambda e: e.get("rank", 99999))
    for i, entry in enumerate(out, start=1):
        entry["rank"] = i

    # Write
    VOCAB_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n✅ Wrote {len(out)} entries → {VOCAB_PATH}")
    print(f"   Merged {merges_done} duplicate groups")
    print(f"   Removed {len(data) - len(out)} extra entries")


if __name__ == "__main__":
    main()
