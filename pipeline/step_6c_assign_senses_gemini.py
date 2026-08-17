#!/usr/bin/env python3
"""Generate Wiktionary-based sense layers for an artist.

Produces two layer files in Artists/{lang}/{Name}/data/layers/:
  - senses_wiktionary_gemini.json      (word|lemma -> [{pos, translation, source}])
  - sense_assignments_wiktionary_gemini.json  (word -> [{sense_idx, examples, method}])

For single-sense words: auto-assigns all examples (no API call).
For multi-sense words: Flash Lite classifies examples to senses.
For zero-sense words: Flash Lite gap-fill proposes new senses.

Run from project root:
    .venv/bin/python3 pipeline/step_6c_assign_senses_gemini.py                          # normal mode
    .venv/bin/python3 pipeline/step_6c_assign_senses_gemini.py --artist-dir "Artists/spanish/Bad Bunny"
"""
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")

import argparse, concurrent.futures, gzip, hashlib, json, os, re, sys, time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Make artist-only helpers importable when running in artist mode.
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))

from step_5c_build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses)
from util_1a_artist_config import (load_artist_config,
                           artist_sense_menu_path, artist_sense_assignments_path,
                           load_dotenv_from_project_root)
from util_6a_method_priority import (METHOD_PRIORITY, best_method_priority,
                                     assign_sense_ids)
from util_6a_assignment_format import (load_assignments, dump_assignments,
                                        example_identity, stamp_example_ids,
                                        stamp_provenance)
from util_6a_prompt_registry import (
    CURRENT_SD_POLICY_ID, CURRENT_SD_PROMPT_ID, load_prompt_policy,
    load_registry,
)
from util_7a_lemma_split import merge_method_maps
from util_5c_sense_paths import sense_menu_path, sense_assignments_path
from util_6a_pos_menu_filter import (
    filter_senses_by_pos, filter_senses_by_precomputed_pos,
    sense_compatible_with_example_pos,
    auto_sense_rejection_reason,
)
from util_4a_routing import resolve_derivation
from util_5c_sense_menu_format import (
    normalize_artist_sense_menu, merge_analysis, get_analyses,
    collect_surface_analyses_from_shared_menu, flatten_analyses_with_ids,
    assign_analysis_sense_ids, extract_form_of_targets, extend_ids_for_extra_senses,
)
load_dotenv_from_project_root()


def generation_config(gemini_model):
    """Return JSON-generation settings compatible with the selected model.

    Gemini 3.5+ deprecates sampling parameters such as ``temperature`` and may
    reject them in future API versions. Older models still benefit from the
    explicit deterministic setting used by the existing regression baseline.
    """
    config = {"response_mime_type": "application/json"}
    match = re.match(r"^gemini-(\d+)\.(\d+)", str(gemini_model or ""))
    if not match or (int(match.group(1)), int(match.group(2))) < (3, 5):
        config["temperature"] = 0.0
    return config


def covered_example_indices(items, current_examples, allow_legacy_indices=True):
    """Resolve assignment coverage against the current example list.

    Stable example/occurrence references are authoritative. Numeric indices are
    retained only as a compatibility fallback for assignment items that predate
    stable evidence. This prevents an example reorder from both re-queuing work
    already completed and, more importantly, treating a reused index as proof
    that a different lyric was classified.
    """
    identity_to_indices = defaultdict(set)
    occurrence_to_indices = defaultdict(set)
    for index, example in enumerate(current_examples or []):
        if not isinstance(example, dict):
            continue
        for identity in (example.get("segment_id"), example.get("id"),
                         example_identity(example)):
            if identity:
                identity_to_indices[identity].add(index)
        for occurrence_id in example.get("occurrence_ids") or []:
            if occurrence_id:
                occurrence_to_indices[occurrence_id].add(index)

    covered = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        stable_example_ids = {
            value for value in (item.get("example_ids") or []) if value
        }
        stable_occurrence_ids = {
            value for value in (item.get("occurrence_ids") or []) if value
        }
        for ref in item.get("occurrence_refs") or []:
            if not isinstance(ref, dict):
                continue
            if ref.get("example_id"):
                stable_example_ids.add(ref["example_id"])
            if ref.get("occurrence_id"):
                stable_occurrence_ids.add(ref["occurrence_id"])

        has_stable_evidence = bool(stable_example_ids or stable_occurrence_ids)
        for identity in stable_example_ids:
            covered.update(identity_to_indices.get(identity, ()))
        for occurrence_id in stable_occurrence_ids:
            covered.update(occurrence_to_indices.get(occurrence_id, ()))

        if not has_stable_evidence and allow_legacy_indices:
            for index in item.get("examples") or []:
                if isinstance(index, int) and 0 <= index < len(current_examples):
                    covered.add(index)
    return covered


def _format_sense_line(idx, label, sense):
    """Format one candidate sense for a Gemini prompt.

    Adds `context` inline (in parentheses after the translation), and tacks
    a Wiktionary example onto a follow-up line when one is present. Both
    fields are optional — the formatter degrades gracefully to the old
    `"  idx. [POS] translation"` shape when the sense only carries the
    required keys.
    """
    base = "  %d. %s[%s] %s" % (idx, label, sense["pos"], sense["translation"])
    ctx = sense.get("context")
    if ctx:
        # Short contexts inline; keep the line compact enough to batch.
        base += " (%s)" % ctx[:80]
    register = sense.get("register") or []
    if register:
        base += " [%s]" % ",".join(register[:3])
    ex = sense.get("example") or {}
    target = (ex.get("target") or "").strip()
    english = (ex.get("english") or "").strip()
    if target and english:
        base += "\n     e.g. %s → %s" % (target[:80], english[:80])
    return base


def _format_example_line(idx, ex, indent="  "):
    """Format one example line for a Gemini prompt.

    Shape: ``  1. [VERB] Mira dónde yo estoy  |  Look where I am``

    The ``[POS]`` tag comes from ``example_pos.json`` (per-example spaCy tag,
    stamped onto the example dict in ``main()``). It is deliberately a HINT,
    never a filter — the full menu is still shown so the model can override a
    wrong tag. Degrades to the old untagged shape when ``pos`` is absent.
    """
    spa = ex.get("spanish") or ex.get("target") or ""
    eng = ex.get("english") or ""
    pos = str(ex.get("pos") or "").strip().upper()
    tag = "[%s] " % pos if pos else ""
    line = "%s%d. %s%s" % (indent, idx, tag, spa)
    if eng:
        line += "  |  " + eng
    return line


# ---------------------------------------------------------------------------
# Shared prompt blocks
# ---------------------------------------------------------------------------
# These three blocks encode the anti-over-translation contract and are reused
# verbatim by every prompt in this file (classify-or-propose, single gap-fill,
# batch gap-fill) so the paths cannot drift apart.
#
# Background (2026-08-07 rewrite): Gemini was rendering the sense of the CLAUSE
# or what the phrase REFERS TO instead of translating the headword, and was
# inventing senses even when the SpanishDict menu already carried a correct one
# (culito "ass" → shipped "young women"; andar "to hang out with" → shipped
# "to be on the loose"; subir "to raise" → shipped "to become outdated"). The
# fix is ordering (menu first, free-form reading never), an explicit
# word-not-clause rule with worked negatives, and a justification requirement
# before any off-menu proposal.

GLOSS_RULE_BLOCK = (
    "TRANSLATE THE WORD, NOT THE LINE.\n"
    "A gloss is an English translation of the headword itself — what a"
    " bilingual dictionary prints next to it. It is NOT a description of what"
    " the line is about, who it refers to, or what it implies. The line can be"
    " about anything; the WORD still means what it means.\n"
    "  \"Los culito' y los culote'\"  ->  culito = \"ass\"."
    " NOT \"young women\" — the line refers to women, but that is the"
    " referent of the phrase, not a translation of culito.\n"
    "  \"Sube ese culo y to's comentan\"  ->  subir = \"to raise\" / \"to go"
    " up\". NOT \"to become outdated\".\n"
    "  \"el punto y los saco'\"  ->  sacar = \"to take out\". NOT \"to"
    " ejaculate\".\n"
    "  \"Anda con la amiga siempre arrebatá'\"  ->  andar (con) = \"to hang"
    " out with\". NOT \"to be on the loose\".\n"
    "A gloss is 1-4 words, lowercase, no trailing period, no explanation."
    " Never write a sentence. Never write \"used to ...\", \"refers to ...\","
    " \"a person who ...\", \"especially when ...\"."
)

MENU_FIRST_BLOCK = (
    "PREFER THE MENU — IT IS THE DEFAULT ANSWER.\n"
    "The menu is a real bilingual dictionary. Start from it: read the senses"
    " and ask \"does one of these translate this WORD as it is used here?\""
    " Do not first decide what the line means and then judge the menu against"
    " that reading — that is how correct senses get rejected.\n"
    "A BROADER menu sense that is CORRECT beats a NARROWER invented one that"
    " is punchier. Flashcard space is limited, and a slightly general true"
    " gloss teaches the learner more than a precise wrong one. Figurative,"
    " vulgar or intensified usage of an ordinary sense is still that sense.\n"
    "Going off-menu is the EXCEPTION, not a peer option. Before proposing"
    " anything you MUST name the closest menu sense and state in a few words"
    " why it fails. \"A more idiomatic wording exists\" and \"the translation"
    " used a different English word\" are NOT reasons. Only genuine regional"
    " slang or figurative usage the dictionary really lacks qualifies."
)

POS_HINT_BLOCK = (
    "PER-EXAMPLE [POS] TAGS ARE EVIDENCE, NOT A FILTER.\n"
    "Example lines may carry a [POS] tag from an automatic tagger describing"
    " how the word is used in THAT line. The FULL menu is shown on purpose —"
    " including senses of other parts of speech — because the tagger is"
    " sometimes wrong. Use the tag to break ties (\"mira\" tagged [VERB] is"
    " the verb mirar \"to look at\"; tagged [NOUN] it is the noun mira"
    " \"sight\"), and override it when the line clearly disagrees."
)


# The English on each line is a scraped LYRIC translation — idiomatic, sung,
# often a paraphrase. Treating it as ground truth is what produced
# `sube` -> "to shake" (the translator wrote "Shake that ass"; the word is
# still subir, "to raise"). It is evidence about the situation, not a gloss of
# the headword.
TRANSLATION_AID_BLOCK = (
    "THE ENGLISH LINE IS AN AID, NOT THE ANSWER.\n"
    "Those translations are idiomatic lyric translations. They paraphrase,"
    " they pick vivid wording, and they sometimes translate the whole phrase"
    " rather than the word. Use them to understand the situation, then"
    " translate the SPANISH word yourself. Do NOT back-form a gloss out of"
    " whichever English word happens to sit in that position.\n"
    "  \"Sube ese culo\" translated as \"Shake that ass\"  ->  subir is still"
    " \"to raise\" / \"to go up\". NOT \"to shake\" — the translator chose"
    " livelier wording; the verb did not change meaning.\n"
    "When the English and the Spanish disagree, trust the Spanish and the menu."
)


# ---------------------------------------------------------------------------
# Spanish Wiktionary dialect supplement (inlined from bench_gapfill)
# ---------------------------------------------------------------------------
ESWIKT_FILE = PROJECT_ROOT / "Data/Spanish/Senses/wiktionary/kaikki-eswiktionary-raw.jsonl.gz"
DEFAULT_DIALECT_TAGS = {"Puerto-Rico", "Caribbean", "Cuba"}
_ESWIKT_POS_MAP = {
    "noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV",
    "intj": "INTJ", "phrase": "PHRASE", "name": "PROPN",
}


def load_eswiktionary(path, dialect_tags):
    """Load Spanish Wiktionary, filtering to dialect-tagged senses. Pickle-cached."""
    import pickle
    cache_path = Path(str(path) + ".eswikt_dialect.cache.pkl")
    cache_key = tuple(sorted(dialect_tags))
    if cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
        with open(cache_path, "rb") as f:
            cached_key, index = pickle.load(f)
        if cached_key == cache_key:
            print("  %d words with dialect senses (cached)" % len(index))
            return index

    index = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("lang_code") != "es":
                continue
            word = obj.get("word", "")
            raw_pos = obj.get("pos", "")
            pos = _ESWIKT_POS_MAP.get(raw_pos)
            if not pos:
                continue
            for s in obj.get("senses", []):
                tags = set(s.get("tags", []))
                if not (tags & dialect_tags):
                    continue
                glosses = s.get("glosses", [])
                if not glosses:
                    continue
                if "form-of" in tags:
                    continue
                index.setdefault(word, []).append({
                    "pos": pos,
                    "gloss_es": glosses[0],
                    "tags": sorted(tags & dialect_tags),
                })
    with open(cache_path, "wb") as f:
        pickle.dump((cache_key, index), f)
    print("  %d words with dialect senses" % len(index))
    return index


def build_combined_senses(word, lemma, en_senses, eswikt_index, translation_cache):
    """Combine English + Spanish Wiktionary senses into one menu."""
    combined = []
    for s in en_senses:
        combined.append({
            "pos": s["pos"],
            "translation": s["translation"],
            "source": "en-wikt",
        })
    for lookup in sorted(set([word, lemma])):
        for s in eswikt_index.get(lookup, []):
            gloss_es = s["gloss_es"]
            cached = translation_cache.get(gloss_es)
            combined.append({
                "pos": s["pos"],
                "translation": cached if cached else gloss_es,
                "source": "es-wikt",
                "gloss_es": gloss_es,
                "is_spanish": cached is None,
            })
    return combined


# ---------------------------------------------------------------------------
# Flash Lite classification (batch)
# ---------------------------------------------------------------------------
BATCH_SIZE = 50
GAP_FILL_BATCH_SIZE = 10
# Default per-word example cap. Override with --max-examples. When re-running
# with a higher value, already-classified indices are preserved and only the
# new ones are sent to Gemini.
DEFAULT_MAX_EXAMPLES_PER_WORD = 10


def classify_batch_gemini(words_data, api_key, gemini_model):
    """Classify examples to senses for a batch of multi-sense words.

    Returns list of per-word assignment lists: [{sense_idx, examples, method}]
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = build_classify_prompt(words_data)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=generation_config(gemini_model),
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: batch parse error")
            print("    Raw: %s" % (response.text[:500] if response.text else "None"))
            return None
        except Exception as e:
            msg = str(e)
            if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                # Non-retryable — abort the whole run instead of burning
                # 5 exponential retries per batch on a bad key.
                sys.exit("FATAL: Gemini API key not valid. The key comes from "
                         "$GEMINI_API_KEY (an explicit env prefix on the command "
                         "overrides the project .env — drop the prefix to use .env).")
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (attempt + 1, msg[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


def build_classify_prompt(words_data):
    """Build the exact prompt string sent by ``classify_batch_gemini``."""
    prompt_parts = [
        "You are classifying Spanish vocabulary from song lyrics.",
        "For each word below, assign each numbered example to the best-matching"
        " sense (0-indexed). If both an English sense and a Spanish [ES] sense"
        " cover the same meaning, prefer the English one.",
        "",
        "Substitution test: for each example, mentally substitute the sense"
        " definition into the English translation. Does it still convey the"
        " right meaning? If not, try other senses. Pick the sense whose"
        " definition makes the substituted sentence make sense, even if the"
        " translator used a different English word.",
        "Example: 'I have the shaved bug' + sense 'penis' — substituting"
        " 'penis' makes more sense than 'bug' in this context → pick 'penis'.",
        "",
        # You are picking, never inventing, on this path — but the same
        # word-not-clause failure applies, and the per-example [POS] tag is the
        # cheapest tiebreak available.
        GLOSS_RULE_BLOCK,
        "",
        (POS_HINT_BLOCK + "\n\n" + TRANSLATION_AID_BLOCK),
        "",
    ]

    for wi, wd in enumerate(words_data):
        prompt_parts.append('--- Word %d: "%s" (lemma: %s) ---' % (
            wi + 1, wd["word"], wd["lemma"]))
        prompt_parts.append("Senses:")
        for si, s in enumerate(wd["senses"]):
            label = "[ES] " if s.get("is_spanish") else ""
            prompt_parts.append(_format_sense_line(si, label, s))
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"], start=1):
            prompt_parts.append(_format_example_line(ei, ex))
        prompt_parts.append("")

    prompt_parts.append("Return a JSON array with one object per word:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "assignments": {"1": 0, "2": 1},
    }], indent=2))

    return "\n".join(prompt_parts)


_DEFINITIONAL_MARKERS = (
    "often used", "often referring", "often refers", "typically refers",
    "used to express", "used to indicate", "used as a", "used in",
    "similar to", "such as", "for example", "for instance",
    "a person who", "someone who", "something that",
    "the act of", "the state of", "the practice of",
    "may refer to", "can mean", "refers to",
    # 2026-08-07: prose that slipped past the original set — the `rrear`
    # failure shipped "To dance, especially in a provocative way."
    "especially", "particularly", "in a way", "in the sense",
    "denoting", "characterized by", "relating to", "used for",
    "the quality of", "the fact of", "an expression",
)


def _is_definitional(text):
    """Heuristic: does a proposed_sense look like a dictionary definition
    rather than a flashcard gloss?

    Flashcard glosses are short (≤5 tokens), don't use explanatory phrasing,
    and don't bundle multiple alternatives with semicolons / em-dashes.
    Gemini Flash Lite ignores the "short flashcard-friendly" instruction in
    the prompt with depressing regularity, so we detect and re-prompt.
    """
    if not isinstance(text, str):
        return False
    s = text.strip()
    if not s:
        return False
    # Too many words — dictionary entries run long; glosses don't.
    # 5-word threshold catches "No longer available or in stock." while
    # preserving legitimate 4-5 word glosses like "to give back to".
    if len(s.split()) > 5:
        return True
    # Definitional connectives.
    s_lower = s.lower()
    if any(marker in s_lower for marker in _DEFINITIONAL_MARKERS):
        return True
    # Semicolon or em-dash → "definition; other definition" pattern.
    if ";" in s or "—" in s:
        return True
    # Ends with period and has multiple clauses (definition-style).
    if s.endswith(".") and ("," in s and len(s.split()) > 4):
        return True
    # Sentence-cased AND terminated — dictionary-entry punctuation. Glosses are
    # lowercase fragments; proper-noun descriptions ("Brazilian footballer")
    # are capitalised but unterminated, so this only catches real prose.
    if s.endswith(".") and s[0].isupper():
        return True
    return False


def _repair_proposed_sense(word, lemma, examples, bad_answer, api_key, gemini_model):
    """Re-prompt for a single word whose proposed_sense looks definitional.

    Returns a corrected short gloss, or None if the re-prompt also fails.
    Costs ~one extra API call per failure (rare in practice once warmed up).
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    lyric_lines = []
    for i, ex in enumerate(examples[:5], start=1):
        lyric_lines.append("  %d. %s" % (i, ex.get("spanish", "")))
    lyrics_str = "\n".join(lyric_lines)

    prompt = (
        'A flashcard for the Spanish word "%s" (lemma: %s) was generated '
        'with this translation:\n  "%s"\n\n'
        'That\'s a dictionary definition, not a flashcard gloss. '
        'Flashcards need a SHORT, 1-4 word English equivalent — the way a '
        'bilingual dictionary headword is glossed.\n\n'
        'Examples of good vs bad:\n'
        '  shot → "drink" ✓ (NOT "a small amount of liquor consumed in one gulp")\n'
        '  panty → "panties" ✓ (NOT "Underwear worn by women")\n'
        '  bi → "boo" or "BMW" or "girl" depending on context ✓ (NOT "Term of endearment for a romantic partner")\n'
        '  cherry → "cherry" ✓ (NOT "a sweet, red fruit; used metaphorically")\n\n'
        'Lyrics where the word appears:\n%s\n\n'
        'Return JSON: {"proposed_sense": "<1-4 word English gloss>", '
        '"proposed_pos": "<NOUN/VERB/ADJ/ADV/INTJ>"}'
    ) % (word, lemma, bad_answer, lyrics_str)

    try:
        response = client.models.generate_content(
            model=gemini_model,
            contents=prompt,
            config=generation_config(gemini_model),
        )
        data = json.loads(response.text)
        new_sense = data.get("proposed_sense")
        if new_sense and not _is_definitional(new_sense):
            return data
        return None
    except Exception as e:
        print("    repair-prompt error for %r: %s" % (word, str(e)[:80]))
        return None


def build_gap_fill_prompt(word, lemma, senses, examples):
    """Build the exact prompt string sent by ``gap_fill_gemini``.

    Menu-first ordering (2026-08-07). The old prompt opened with "determine
    what X actually means in this artist's usage" and returned
    ``actual_meaning`` as its first field, which anchored the model on a
    contextual interpretation BEFORE it read the menu; the substitution test
    then judged real dictionary senses against that over-fitted reading and
    they "failed". ``actual_meaning`` is gone. The model now reads the menu
    first, and must name the closest sense + why it fails before it is allowed
    to propose anything.
    """
    menu_lines = []
    for i, s in enumerate(senses):
        label = "[ES] " if s.get("is_spanish") else ""
        menu_lines.append("%d. %s[%s] %s" % (i + 1, label, s["pos"],
                                              s["translation"]))
    menu = "\n".join(menu_lines) if menu_lines else "  (none)"

    lines = [_format_example_line(i, ex, indent="")
             for i, ex in enumerate(examples, start=1)]

    return (
        'You are helping build a Spanish vocabulary flashcard app for learners.'
        ' The word is "%s" (lemma: %s).\n\n'
        '%s\n\n'
        '%s\n\n'
        '%s\n\n'
        'STEP 1 — READ THE MENU FIRST. These are the dictionary senses'
        ' available for this word:\n%s\n'
        'If both an English sense and a Spanish [ES] sense cover the same'
        ' meaning, prefer the English one.\n\n'
        'STEP 2 — Here are the lyric lines the word appears in, as'
        ' `[POS] spanish | english`:\n%s\n\n'
        'STEP 3 — For the best-fitting menu sense, run the substitution test:'
        ' take one English lyric line and substitute that sense for the word.'
        ' Write out the substituted sentence. Ask whether the sense TRANSLATES'
        ' THE WORD, not whether it restates the line. A sense passes even when'
        ' the usage is more figurative, vulgar or intense than the dictionary'
        ' wording, and even when the translator chose a different English word.\n\n'
        'STEP 4 — Only if NO menu sense translates the word do you propose one.'
        ' You must fill in "closest_menu_sense_index" and "why_menu_fails"'
        ' first. If the menu is empty, propose directly.\n\n'
        'Return JSON:\n'
        '{\n'
        '  "closest_menu_sense_index": <1-indexed number of the closest menu sense, or null if the menu is empty>,\n'
        '  "substitution_example": "<that English lyric with the closest menu sense substituted in>",\n'
        '  "substitution_works": <true if the substituted sentence still translates the word correctly>,\n'
        '  "covered_by_existing": <true if substitution works, false if not>,\n'
        '  "best_sense_index": <1-indexed number of the best matching sense if covered, else null>,\n'
        '  "english_translation": "<if best sense is Spanish [ES], provide 2-5 word English translation; else null>",\n'
        '  "pos_verdict": "<if you picked a menu sense whose POS is wrong for these lines, the POS you believe is correct; else null>",\n'
        '  "why_menu_fails": "<only if NOT covered: a few words on why the closest menu sense fails; else null>",\n'
        '  "proposed_sense": "<only if NOT covered: a 1-4 word English gloss of the WORD, lowercase, no period; else null>",\n'
        '  "proposed_pos": "<POS tag if proposing: NOUN/VERB/ADJ/ADV/INTJ, else null>",\n'
        '  "proposed_lemma": "<best-guess Spanish lemma/headword if proposing, else null>",\n'
        '  "examples_needing_new_sense": <count of examples that need the new sense, 0 if covered>\n'
        '}'
    ) % (word, lemma, GLOSS_RULE_BLOCK, MENU_FIRST_BLOCK, (POS_HINT_BLOCK + "\n\n" + TRANSLATION_AID_BLOCK),
         menu, "\n".join(lines))


def gap_fill_gemini(word, lemma, senses, examples, api_key, gemini_model):
    """Ask Gemini: pick a sense or propose a new one. Returns result dict.

    Response keys consumed downstream are unchanged: ``covered_by_existing``,
    ``best_sense_index``, ``english_translation``, ``proposed_sense``,
    ``proposed_pos``, ``proposed_lemma``, ``examples_needing_new_sense``.
    ``actual_meaning`` is deliberately gone (it anchored the menu check);
    ``closest_menu_sense_index``, ``why_menu_fails`` and ``pos_verdict`` are
    new audit-only additions.
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = build_gap_fill_prompt(word, lemma, senses, examples)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=generation_config(gemini_model),
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: gap-fill parse error")
            return None
        except Exception as e:
            msg = str(e)
            if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                # Non-retryable — abort the whole run instead of burning
                # 5 exponential retries per batch on a bad key.
                sys.exit("FATAL: Gemini API key not valid. The key comes from "
                         "$GEMINI_API_KEY (an explicit env prefix on the command "
                         "overrides the project .env — drop the prefix to use .env).")
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (attempt + 1, msg[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


def build_gap_fill_batch_prompt(words_data):
    """Build the exact prompt string sent by ``gap_fill_batch_gemini``.

    Kept in lockstep with ``build_gap_fill_prompt`` so the batch path cannot
    drift from the single path: menu first, translate the word not the line,
    justify before inventing, per-example [POS] as a hint.
    """
    prompt_parts = [
        "You are helping build a Spanish vocabulary flashcard app for learners.",
        "",
        GLOSS_RULE_BLOCK,
        "",
        MENU_FIRST_BLOCK,
        "",
        (POS_HINT_BLOCK + "\n\n" + TRANSLATION_AID_BLOCK),
        "",
        "For each word below, in this order:",
        "1. READ THE CANDIDATE SENSES FIRST. Ask whether one of them translates"
        " the WORD as it is used in the example lines. Do not first decide what"
        " the lines mean and then judge the menu against that reading.",
        "2. Record \"closest_menu_sense_index\" — the 1-indexed sense you"
        " compared against, whether you keep it or reject it (null if the menu"
        " is empty).",
        "3. If it translates the word, set \"covered_by_existing\": true and"
        " \"best_sense_index\" to it. Figurative, vulgar or intensified usage"
        " of an ordinary sense is still that sense.",
        "4. ONLY if no candidate sense translates the word, set"
        " \"covered_by_existing\": false, fill \"why_menu_fails\" with a few"
        " words on why the closest sense fails, and propose ONE gloss of 1-4"
        " words in \"proposed_sense\" (lowercase, no trailing period, no"
        " explanation) plus \"proposed_pos\" and \"proposed_lemma\".",
        "5. If you keep a menu sense but its POS is wrong for these lines, set"
        " \"pos_verdict\" to the POS you believe is correct (recorded for human"
        " audit only) — do NOT reject the menu and invent instead.",
        "Example lines are shown as `[POS] spanish | english`.",
        "Return a JSON array with one object per word.",
        "",
    ]

    for wi, wd in enumerate(words_data, start=1):
        prompt_parts.append('--- Word %d: "%s" (lemma: %s) ---' % (
            wi, wd["word"], wd["lemma"]))
        if wd.get("senses"):
            prompt_parts.append("Candidate senses:")
            for si, s in enumerate(wd["senses"], start=1):
                label = "[ES] " if s.get("is_spanish") else ""
                prompt_parts.append(_format_sense_line(si, label, s))
        else:
            prompt_parts.append("Candidate senses: (none)")
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"], start=1):
            prompt_parts.append(_format_example_line(ei, ex))
        prompt_parts.append("")

    prompt_parts.append("Return JSON like:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "closest_menu_sense_index": 2,
        "covered_by_existing": False,
        "best_sense_index": None,
        "english_translation": None,
        "pos_verdict": None,
        "why_menu_fails": "menu only has the literal sense",
        "proposed_sense": "short meaning",
        "proposed_pos": "NOUN",
        "proposed_lemma": "hablar"
    }], indent=2))

    return "\n".join(prompt_parts)


def gap_fill_batch_gemini(words_data, api_key, gemini_model):
    """Ask Gemini to propose or reuse one sense for a batch of gap-fill words.

    Response keys consumed downstream are unchanged (``word``,
    ``proposed_sense``, ``proposed_pos``, ``proposed_lemma``);
    ``closest_menu_sense_index``, ``why_menu_fails`` and ``pos_verdict`` are
    new audit-only additions that the caller ignores.
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = build_gap_fill_batch_prompt(words_data)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=generation_config(gemini_model),
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: gap-fill batch parse error")
            return None
        except Exception as e:
            msg = str(e)
            if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                # Non-retryable — abort the whole run instead of burning
                # 5 exponential retries per batch on a bad key.
                sys.exit("FATAL: Gemini API key not valid. The key comes from "
                         "$GEMINI_API_KEY (an explicit env prefix on the command "
                         "overrides the project .env — drop the prefix to use .env).")
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (attempt + 1, msg[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


# ---------------------------------------------------------------------------
# Classify-or-propose (SpanishDict path) — unifies classification + gap-fill
# ---------------------------------------------------------------------------
# Small batch: the classify-or-propose prompt is denser (per-example calls +
# proposal metadata) than the plain classifier, so we send fewer words per
# call than BATCH_SIZE=50. The validated eval (scratchpad/eval30.py) used 10.
SD_CLASSIFY_BATCH_SIZE = 10
# The validated 3.1 baseline scored 6/6
# detection + 4/4 clean controls at flash-lite speed/price (2026-07-22 redesign,
# docs/design/artist_pipeline_quality_audit.md). The lexical-only prompt moves
# tagging/entity/construction decisions into separate layers. The revised 3.1
# default keeps that validated model and adds exact output-completeness rules;
# it is versioned separately so it cannot relabel the original 3.1 evidence.
# Runs made under this default are stamped
# prompt_id CURRENT_SD_PROMPT_ID (see util_6a_prompt_registry). Override with
# --gemini-model (+ pass a matching --prompt-id so provenance stays accurate).
SD_DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_ARTIST_CONTEXT = "regional slang and figurative usage"


def resolve_custom_menu_analyses(word, menu, routing_data=None,
                                 conjugation_reverse=None):
    """Resolve a restored surface to an existing provider menu analysis.

    Elision restoration deliberately preserves inflection (``aprendi'o`` ->
    ``aprendido``); this bridge performs the separate morphology step before
    WSD. It never invents senses: every returned analysis already exists in
    the active menu under a surface or stable headword.
    """
    direct = get_analyses(menu, word)
    if direct:
        return word, deepcopy(direct), "surface"

    by_headword = defaultdict(list)
    known = set(menu)
    gender_alias = {}
    for analyses in menu.values():
        if not isinstance(analyses, list):
            continue
        for analysis in analyses:
            if not isinstance(analysis, dict):
                continue
            headword = analysis.get("headword") or analysis.get("lemma")
            if not headword:
                continue
            known.add(headword)
            by_headword[headword].append(analysis)
            poses = {str(s.get("pos") or "").upper()
                     for s in (analysis.get("senses") or {}).values()
                     if isinstance(s, dict)}
            if headword.endswith("o") and "ADJ" in poses:
                feminine = headword[:-1] + "a"
                known.add(feminine)
                gender_alias[feminine] = headword

    candidates = []
    derivation_map = (routing_data or {}).get("derivation_map") or {}
    if derivation_map.get(word):
        candidates.append((derivation_map[word], "routing_derivation"))
    derived = resolve_derivation(word, known)
    if derived:
        candidates.append((derived, "morphological_derivation"))
    for row in (conjugation_reverse or {}).get(word, []) or []:
        if isinstance(row, dict) and row.get("lemma"):
            candidates.append((row["lemma"], "conjugation"))
    if word.endswith("se") and len(word) > 4:
        candidates.append((word[:-2], "reflexive_infinitive"))

    seen = set()
    for candidate, reason in candidates:
        candidate = gender_alias.get(candidate, candidate)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        analyses = get_analyses(menu, candidate) or by_headword.get(candidate) or []
        if analyses:
            return candidate, deepcopy(analyses), reason
    return word, [], None


def _artist_context(config):
    """Genre/dialect descriptor injected into the classify-or-propose prompt."""
    ctx = (config or {}).get("artist_context")
    if isinstance(ctx, str) and ctx.strip():
        return ctx.strip()
    return DEFAULT_ARTIST_CONTEXT


def _dominant_pos(senses):
    """Most common POS across a word's menu senses, or None when empty.

    Used to stamp a POS on off-menu proposals (the classify-or-propose prompt
    doesn't return one) — regional/figurative slang for a word almost always
    shares that word's grammatical category.
    """
    from collections import Counter
    counts = Counter(s.get("pos") for s in (senses or []) if s.get("pos"))
    return counts.most_common(1)[0][0] if counts else None


def build_classify_or_propose_prompt(words_data, artist_context):
    """Build the exact prompt string sent by ``classify_or_propose_batch``.

    Split out so ``--dry-run-prompt`` can dump the real payload without an API
    call. Any change here changes what the model actually receives.
    """
    # Lexical WSD contract (2026-08-09). Entity detection, usage tags,
    # constructions and POS are independent upstream evidence layers. This
    # prompt may propose a missing lexical slang gloss, but it must not turn a
    # phrase meaning or proper-name description into a word sense.
    header = (
        "You are building a Spanish vocabulary flashcard app from song lyrics"
        " (%s). Expect regional slang and figurative usage.\n"
        "Each word comes with a dictionary sense menu and example lines shown"
        " as `[POS] spanish | english translation`.\n"
        "\n"
        "%s\n"
        "\n"
        "%s\n"
        "\n"
        "%s\n"
        "\n"
        "PROCEDURE, in this order, for EACH example:\n"
        "1. Read the menu. Pick the menu sense id that translates the WORD as"
        " used in that line. The English translation shows the real meaning"
        " (substitution test), but you are translating the headword, not"
        " restating the line.\n"
        "2. The requested answer must be a lexical meaning of the HEADWORD."
        " Context may disambiguate it, but never attach the meaning of a whole"
        " phrase to one component word. If only a multi-word construction has"
        " the requested meaning and no lexical menu sense is defensible,"
        " abstain with construction_only.\n"
        "3. Record the id you compared against in \"closest\" whenever a menu"
        " exists, whether"
        " you keep it or reject it.\n"
        "4. Only if NO menu sense fits the contextual meaning (usually"
        " regional slang/figurative the dictionary lacks) set \"sense\": null,"
        " \"proposed\": a 1-4 word lexical gloss, \"why_not_menu\": a few"
        " words on why the sense in \"closest\" fails, and \"proposed_pos\":"
        " NOUN|VERB|ADJ|ADV|INTJ. A genuine lexical slang meaning missing from"
        " the dictionary is valid here even though slang TAGGING belongs to a"
        " separate layer. Else proposed/why_not_menu/proposed_pos null.\n"
        "5. Proper names, noise/adlibs/echoes, foreign-language material, and"
        " construction-only meanings are not WSD decisions. Set sense and"
        " proposed null and set \"abstain_reason\" to proper_noun, noise,"
        " foreign, construction_only, or insufficient_context. Do not describe"
        " the entity and do not invent a phrase gloss. Otherwise"
        " abstain_reason is null.\n"
        "6. Return EXACTLY one call for every numbered example, in order and"
        " with no duplicates. A non-null sense MUST copy one shown menu id"
        " verbatim. If sense is null, supply either a valid proposed lexical"
        " gloss OR an abstain_reason; never leave sense, proposed, and"
        " abstain_reason all null.\n"
        "Return ONLY JSON: [{\"word\":\"x\",\"calls\":[{\"example\":1,"
        "\"sense\":\"<id|null>\",\"closest\":\"<id>\","
        "\"proposed\":\"<gloss|null>\",\"why_not_menu\":\"<reason|null>\","
        "\"proposed_pos\":\"<NOUN|VERB|ADJ|ADV|INTJ|null>\","
        "\"abstain_reason\":\"<proper_noun|noise|foreign|construction_only|"
        "insufficient_context|null>\"}]}]"
    ) % (artist_context, GLOSS_RULE_BLOCK, MENU_FIRST_BLOCK, (POS_HINT_BLOCK + "\n\n" + TRANSLATION_AID_BLOCK))

    prompt_parts = [header, "", "WORDS:"]
    for wd in words_data:
        prompt_parts.append('\n--- "%s" ---' % wd["word"])
        prompt_parts.append("Senses:")
        senses = wd.get("senses") or []
        ids = wd.get("ids") or []
        if senses:
            for sid, s in zip(ids, senses):
                line = "  %s: [%s] %s" % (sid, s.get("pos", ""),
                                          s.get("translation", ""))
                ctx = s.get("context")
                if ctx:
                    line += " (%s)" % ctx[:80]
                prompt_parts.append(line)
        else:
            prompt_parts.append("  (none)")
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd.get("examples") or [], start=1):
            prompt_parts.append(_format_example_line(ei, ex))

    return "\n".join(prompt_parts)


def classify_or_propose_batch(words_data, api_key, gemini_model, artist_context):
    """Unified classify-or-propose classifier for the SpanishDict path.

    Per word, per example: pick the menu sense id that fits IN CONTEXT, or —
    when NO menu sense matches the usage — set sense=null and propose a short
    lexical gloss. Tagging, entities and constructions are separate layers.

    words_data: [{word, lemma, senses, ids, examples}] where senses[i] is a
    sense dict and ids[i] is its menu sense id (parallel lists). examples is
    [{spanish, english, pos}, ...] — `pos` is the optional per-example spaCy
    tag, rendered as a hint. A word with an empty menu (zero-sense gap-fill
    candidate) is fully supported — every example resolves to a proposal.

    Returns a list of per-word dicts:
        [{"word": w,
          "calls": [{"example": 1, "sense": "<id|null>", "closest": "<id>",
                     "proposed": "<gloss|null>", "why_not_menu": "<reason|null>",
                     "proposed_pos": "<POS|null>",
                     "abstain_reason": "<reason|null>"}, ...]}, ...]
    or None on unrecoverable failure.
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = build_classify_or_propose_prompt(words_data, artist_context)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=generation_config(gemini_model),
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: classify-or-propose parse error")
            print("    Raw: %s" % (response.text[:500] if response.text else "None"))
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


# ---------------------------------------------------------------------------
# Keyword fallback classifier
# ---------------------------------------------------------------------------
def classify_keyword(examples, senses):
    """Keyword overlap classifier — instant, no API. Returns list of sense indices."""
    import re
    _WORD_RE = re.compile(r"[a-z]+")
    _STOP = {"a", "an", "the", "to", "of", "in", "on", "at", "for", "is",
             "it", "be", "as", "or", "by", "and", "not", "with", "from",
             "that", "this", "but", "are", "was", "were", "i", "me", "my",
             "you", "he", "she", "we", "they", "do", "does", "did", "has",
             "have", "had", "will", "would", "can", "could"}

    def tokenize(text):
        return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 1}

    assignments = []
    for ex in examples:
        eng = ex.get("english", "")
        ex_words = tokenize(eng)
        best_idx = 0
        best_score = 0
        for si, s in enumerate(senses):
            sense_words = tokenize(s["translation"])
            score = len(ex_words & sense_words) if sense_words else 0
            if score > best_score:
                best_score = score
                best_idx = si
        assignments.append(best_idx)
    return assignments


def _dump_prompts_and_exit(label, batch_size, records, build_prompt,
                           plan_path=None):
    """Print the exact prompt payload for each batch, then exit(0).

    Used by --dry-run-prompt. Nothing is sent to Gemini and no layer file is
    written — the process ends here so a dry run can never mutate state.
    """
    print("\n" + "=" * 72)
    print("DRY RUN — %s: %d record(s), batches of %d. NO API CALL." % (
        label, len(records), batch_size))
    print("=" * 72)
    if not records:
        print("(no records reached this path — check --word / routing filters)")
    if plan_path:
        batches = []
        for start in range(0, len(records), batch_size):
            batch = records[start:start + batch_size]
            prompt = build_prompt(batch)
            batches.append({
                "batch": start // batch_size + 1,
                "words": [record.get("word") for record in batch],
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("utf-8")).hexdigest(),
            })
        record_rows = []
        for record in records:
            prompt = build_prompt([record])
            record_rows.append({
                **record,
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("utf-8")).hexdigest(),
            })
        payload = {
            "schema": "fluency.gemini-prompt-plan/v1",
            "label": label,
            "batch_size": batch_size,
            "records": record_rows,
            "batches": batches,
        }
        output_path = Path(plan_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Prompt plan: %d records / %d batches -> %s" % (
            len(record_rows), len(batches), output_path))
        print("DRY RUN COMPLETE — exiting without writing assignment layers.")
        sys.exit(0)
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        print("\n" + "-" * 72)
        print("BATCH %d  words: %s" % (start // batch_size + 1,
                                       [r.get("word") for r in batch]))
        print("-" * 72)
        print(build_prompt(batch))
    print("\n" + "=" * 72)
    print("DRY RUN COMPLETE — exiting without writing anything.")
    sys.exit(0)


def normalize_assignment_methods(word_data, default_method):
    """Coerce legacy or malformed assignment payloads to {method: [items]}."""
    if isinstance(word_data, dict):
        return word_data
    if isinstance(word_data, list):
        return {default_method: word_data}
    return {}


def _checkpoint_path(layers_dir, assignments_file, prompt_id, gemini_model):
    """Return a run-scoped checkpoint path.

    A checkpoint made by another prompt/model must never mark words complete
    for this run. Keep the readable assignment stem and add a short digest of
    the semantic run identity.
    """
    identity = json.dumps({
        "assignments_file": assignments_file,
        "prompt_id": prompt_id,
        "gemini_model": gemini_model,
    }, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:12]
    return os.path.join(
        layers_dir,
        ".%s.%s.checkpoint.json" % (Path(assignments_file).stem, digest),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate Wiktionary sense layers via Gemini Flash Lite")
    parser.add_argument("--artist-dir", default=None,
                        help="Artist directory (e.g. Artists/spanish/Bad Bunny). "
                             "Omit for normal mode (Data/Spanish).")
    parser.add_argument("--no-gemini", action="store_true",
                        help="Skip Gemini, use keyword classifier (free, lower accuracy)")
    parser.add_argument("--all-gemini", action="store_true",
                        help="Treat biencoder-routed words as Gemini candidates for this run")
    parser.add_argument("--force", action="store_true",
                        help="Re-classify all eligible words (ignore existing assignments)")
    parser.add_argument("--gemini-model", default=None,
                        help="Gemini model to use when Gemini is enabled. "
                             "Defaults to %s for the SpanishDict classify-or-"
                             "propose path and gemini-2.5-flash-lite otherwise."
                             % SD_DEFAULT_MODEL)
    parser.add_argument("--prompt-id", default=CURRENT_SD_PROMPT_ID,
                        help="Provenance id stamped onto every assignment this "
                             "run writes (joins into config/prompt_registry.json). "
                             "Mint a new registry entry when the prompt or model "
                             "changes, then pass its id here. Default: %(default)s.")
    parser.add_argument("--prompt-policy", default=CURRENT_SD_POLICY_ID,
                        help="Named acceptance policy used to decide which "
                             "existing model claims count as completed. "
                             "Default: %(default)s.")
    parser.add_argument("--replace-prompt-id", action="append", default=[],
                        help="Process only current examples carrying this old "
                             "prompt id (repeatable). Stable example or "
                             "occurrence identity is required; numeric-only "
                             "legacy rows are never targeted.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--normal-slang-only", action="store_true",
                        help="Only process normal-mode words that have eswiktionary dialect senses")
    mode_group.add_argument("--new-only", action="store_true",
                        help="Only process non-normal-mode words with corpus_count > 1")
    parser.add_argument("--sense-menu-file", type=str, default=None,
                        help="Alternative artist-layer menu file to read instead of building from Wiktionary")
    parser.add_argument("--assignments-file", type=str, default="sense_assignments/wiktionary.json",
                        help="Artist-layer assignments file to write (default: sense_assignments/wiktionary.json)")
    parser.add_argument("--method-name", type=str, default=None,
                        help="Method key override for classified multi-sense words")
    parser.add_argument("--keyword-method-name", type=str, default=None,
                        help="Method key override when --no-gemini is used")
    parser.add_argument("--auto-method-name", type=str, default="wiktionary-auto",
                        help="Method key for auto-assigned single-sense words")
    parser.add_argument("--menu-source-label", type=str, default="wiktionary",
                        help="Source label for reporting with --sense-menu-file")
    parser.add_argument("--include-clitics", action="store_true",
                        help="Include clitic-merge words (skipped by default)")
    parser.add_argument("--use-loanword-skip", action="store_true",
                        help="Also skip classification for words in the "
                             "english_loanwords.json layer. OFF by default: the layer "
                             "is over-broad — it blocks 138 naturalized Spanish words "
                             "(gasolina/gol/ron/dembow/bichote) that have SD menus, and "
                             "only blocks classification without hiding anything, while "
                             "word_routing already handles real English. Enable only if "
                             "you specifically want the extra code-switch skip.")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process specific surface words (repeatable). "
                             "Useful with --force to re-classify a small set "
                             "without disturbing existing assignments for the "
                             "rest of the inventory.")
    parser.add_argument("--skip-classification", action="store_true",
                        help="Skip multi-sense classification; only run gap-fill.")
    parser.add_argument("--skip-gap-fill", action="store_true",
                        help="Skip gap-fill for zero-sense words; only run classification.")
    parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES_PER_WORD,
                        help="Max examples per word to classify (default %d). "
                             "Re-running with a larger value picks up where the "
                             "previous run left off — already-classified example "
                             "indices for the same method are skipped and only "
                             "the new ones are sent to Gemini." %
                             DEFAULT_MAX_EXAMPLES_PER_WORD)
    parser.add_argument("--dry-run-prompt", action="store_true",
                        help="Build the batches exactly as a real run would, "
                             "print the EXACT prompt payload Gemini would "
                             "receive, and exit without calling the API or "
                             "writing any layer file. Pair with --word/--force "
                             "to inspect specific words. No API key needed.")
    parser.add_argument("--prompt-plan-json", default=None,
                        help="With --dry-run-prompt, write a structured no-API "
                             "plan with per-record and per-batch prompt hashes "
                             "instead of printing the full prompts.")
    parser.add_argument("--gemini-workers", type=int, default=1,
                        help="Concurrent Gemini batches for the SpanishDict "
                             "classify-or-propose path (default 1). Checkpoints "
                             "are still written after each completed batch.")
    args = parser.parse_args()
    if args.max_examples < 1:
        print("ERROR: --max-examples must be >= 1")
        sys.exit(1)
    if args.gemini_workers < 1:
        print("ERROR: --gemini-workers must be >= 1")
        sys.exit(1)
    if args.prompt_plan_json and not args.dry_run_prompt:
        parser.error("--prompt-plan-json requires --dry-run-prompt")

    is_artist = args.artist_dir is not None
    if is_artist:
        artist_dir = os.path.abspath(args.artist_dir)
        config = load_artist_config(artist_dir)
        layers_dir = os.path.join(artist_dir, "data", "layers")
    else:
        artist_dir = None
        config = {}
        layers_dir = str(PROJECT_ROOT / "Data" / "Spanish" / "layers")

    use_gemini = not args.no_gemini
    custom_menu_mode = bool(args.sense_menu_file)
    # The SpanishDict classify-or-propose path: custom menu whose source label
    # is "spanishdict", with Gemini enabled. Gated tightly so the wiktionary /
    # normal-mode classify + separate gap-fill paths are untouched.
    sd_gemini_mode = (use_gemini and custom_menu_mode
                      and args.menu_source_label == "spanishdict")
    # Resolve the model. Explicit --gemini-model always wins; otherwise the
    # SpanishDict path defaults to the stronger flash-lite and everything else
    # keeps the historical gemini-2.5-flash-lite default.
    if args.gemini_model:
        gemini_model = args.gemini_model
    elif sd_gemini_mode:
        gemini_model = SD_DEFAULT_MODEL
    else:
        gemini_model = "gemini-3.5-flash-lite"
    prompt_registry = load_registry()
    prompt_policy = load_prompt_policy(args.prompt_policy)
    if not prompt_policy:
        parser.error("--prompt-policy %r is not registered" % args.prompt_policy)
    accepted_model_prompt_ids = frozenset(
        prompt_policy.get("accepted_prompt_ids") or [])
    if use_gemini:
        prompt_entry = prompt_registry.get(args.prompt_id)
        if not prompt_entry:
            parser.error("--prompt-id %r is not registered" % args.prompt_id)
        registered_model = prompt_entry.get("model")
        if registered_model and registered_model != "unknown" and registered_model != gemini_model:
            parser.error(
                "--prompt-id %s is registered for %s, not %s; mint a new "
                "prompt id instead of mislabelling the run" % (
                    args.prompt_id, registered_model, gemini_model))
    if use_gemini and not args.dry_run_prompt:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("ERROR: Set GEMINI_API_KEY env var (or use --no-gemini)")
            sys.exit(1)
    else:
        # --dry-run-prompt never reaches an API call, so no key is required.
        api_key = os.environ.get("GEMINI_API_KEY", "") or None

    # Load word inventory + examples + translations
    print("Loading layers...")
    with open(os.path.join(layers_dir, "word_inventory.json")) as f:
        inventory = json.load(f)
    print("  %d words in inventory" % len(inventory))

    with open(os.path.join(layers_dir, "examples_raw.json")) as f:
        examples_raw = json.load(f)

    # Normal-mode schema uses `target` (Spanish) + inline `english`. Downstream
    # code expects the artist schema (`spanish` + separate translations dict),
    # so shim the examples in place.
    if not is_artist:
        for _exs in examples_raw.values():
            for _ex in _exs:
                if "spanish" not in _ex and "target" in _ex:
                    _ex["spanish"] = _ex["target"]

    example_pos = {}
    example_pos_path = os.path.join(layers_dir, "example_pos.json")
    if os.path.isfile(example_pos_path):
        with open(example_pos_path) as f:
            example_pos = json.load(f)
        example_pos.pop("_example_ids", None)
        print("  example_pos: %d words" % len(example_pos))
    else:
        print("  example_pos: (not found, spaCy fallback)")

    translations_path = os.path.join(layers_dir, "example_translations.json")
    if os.path.isfile(translations_path):
        with open(translations_path) as f:
            translations = json.load(f)
    elif is_artist:
        raise SystemExit("example_translations.json not found: %s" % translations_path)
    else:
        # Normal mode: translations live inline on each example record.
        translations = {}
        for _exs in examples_raw.values():
            for _ex in _exs:
                _spa = _ex.get("target") or _ex.get("spanish")
                _eng = _ex.get("english")
                if _spa and _eng:
                    translations[_spa] = {"english": _eng}
        print("  translations (inline from examples_raw): %d entries" % len(translations))

    if custom_menu_mode:
        custom_menu_path = Path(layers_dir) / args.sense_menu_file
        if not custom_menu_path.exists():
            print("ERROR: Alternative sense menu not found: %s" % custom_menu_path)
            sys.exit(1)
        with open(custom_menu_path) as f:
            shared_wikt_menu = normalize_artist_sense_menu(json.load(f))
        wikt_index = {}
        redirects = {}
        eswikt_index = {}
        cache_path = None
        translation_cache = {}
        print("Loading alternative sense menu: %s (%d words)" % (
            custom_menu_path.name, len(shared_wikt_menu)))
    else:
        # Load Wiktionary
        print("Loading English Wiktionary...")
        wikt_path = PROJECT_ROOT / "Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz"
        wikt_index, redirects = load_wiktionary(wikt_path)

        # Shared Wiktionary menu. In artist mode this is the normal-mode menu
        # used as a fallback base; in normal mode it's our own output menu.
        if is_artist:
            shared_menu_candidates = [
                PROJECT_ROOT / "Data/Spanish/layers/sense_menu/wiktionary.json",
            ]
        else:
            shared_menu_candidates = [sense_menu_path(layers_dir, "wiktionary")]
        shared_wikt_menu = {}
        for cand in shared_menu_candidates:
            if Path(cand).exists():
                with open(cand) as f:
                    shared_wikt_menu = json.load(f)
                break

        # Dialect supplement (eswiktionary) is artist-specific: normal mode
        # already merges dialect senses into its menu at step 5c.
        if is_artist:
            dialect_tags = set(config.get("dialect_tags", DEFAULT_DIALECT_TAGS))
            print("Loading Spanish Wiktionary (dialect: %s)..." % ", ".join(sorted(dialect_tags)))
            eswikt_index = load_eswiktionary(ESWIKT_FILE, dialect_tags)

            # Translation cache for Spanish glosses
            cache_path = PROJECT_ROOT / "pipeline/artist/bench/.eswikt_translation_cache.json"
            translation_cache = {}
            if cache_path.exists():
                with open(cache_path) as f:
                    translation_cache = json.load(f)
            print("  %d cached Spanish→English translations" % len(translation_cache))
        else:
            eswikt_index = {}
            cache_path = None
            translation_cache = {}

    # ---------------------------------------------------------------------------
    # Process each word
    # ---------------------------------------------------------------------------
    senses_out = {}        # word -> [{lemma, senses}]
    assignments_out = {}   # word -> [{sense_idx, examples, method}]

    single_sense = 0
    multi_sense_queue = []  # (word, lemma, senses, examples_with_eng)
    no_senses_queue = []    # (word, lemma, examples_with_eng)
    no_examples = 0

    # Load word_routing.json for flag-based skipping (preferred, from step 4)
    if is_artist:
        routing_path = os.path.join(artist_dir, "data", "known_vocab", "word_routing.json")
    else:
        routing_path = os.path.join(layers_dir, "word_routing.json")
    skip_set = set()
    routing_data = {}
    discovery_words = set()
    if os.path.isfile(routing_path):
        with open(routing_path) as f:
            routing_data = json.load(f)
        exclude = routing_data.get("exclude", {}) or {}
        # Skip every exclude.* bucket — they all share the same semantic
        # ("step 4 already decided this word is not worth classifier work").
        # Previously we hardcoded a subset (english/proper_nouns/interjections)
        # and let cognate + low_frequency leak through into the gap-fill queue,
        # which spent Gemini calls inventing senses for ~900 words per BB run
        # whose cards step_8b/the front-end then filter out anyway. Iterating
        # all values matches what step_6b already does and keeps step_6c in
        # sync with step_4a's contract: exclude == do not process.
        # Schema_v1 wrapped exclude.cognate as {word: {voters:[...]}}; the
        # isinstance branches handle both shapes safely.
        for cat_value in exclude.values():
            if isinstance(cat_value, list):
                skip_set.update(cat_value)
            elif isinstance(cat_value, dict):
                skip_set.update(cat_value.keys())
        # Words step_4a positively routed to sense discovery: no dictionary has
        # them, and phases 1-4 already established they are not English, not a
        # known Spanish form, not a clitic or derivation, not noise and not a
        # proper noun. That is real evidence, and it is what the corpus_count
        # floor on the gap-fill queue below is a poor proxy for.
        # schema_v2 renamed gemini → sense_discovery; read both.
        discovery_words = set(
            routing_data.get("sense_discovery", routing_data.get("gemini", [])) or [])
        if not args.all_gemini:
            # schema_v2 renamed biencoder.* → classifier.* and dropped the
            # always-empty `shared` sub-bucket; the .get() chain returns []
            # in either schema, so this stays a no-op for new files and a
            # safe read for legacy files that still have shared entries.
            skip_set.update(
                routing_data.get("classifier", routing_data.get("biencoder", {})).get("shared", [])
            )
        # Skip merge-clitics (folded into base verb, don't need assignment)
        if not args.include_clitics:
            clitic_merge = routing_data.get("clitic_merge", {})
            if isinstance(clitic_merge, dict):
                skip_set.update(clitic_merge.keys())
        print("  Skip words (from step 4): %d" % len(skip_set))

    conjugation_reverse = {}
    if custom_menu_mode:
        conjugation_path = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugation_reverse.json"
        if conjugation_path.is_file():
            with open(conjugation_path, encoding="utf-8") as handle:
                conjugation_reverse = json.load(handle)

    # Layer-derived skip: English loanwords identified by Wiktionary
    # etymology (tool_4a_build_english_loanwords.py). These are surface
    # forms that Wiktionary explicitly marks as "borrowed from English"
    # across every entry — pure code-switches like hey/baby/shot/panty
    # /cherry/play/out/okay. Sending them to gap-fill produces verbose
    # dictionary definitions ("Underwear worn by women.") that aren't
    # useful as flashcard glosses. Skip them; downstream stamping +
    # front-end filter handle their card-level treatment.
    #
    # Layered on top of word_routing so we don't need to rebuild
    # routing files to benefit — the loanword file is a separate
    # data-derived layer.
    loanwords_path = str(PROJECT_ROOT / "Data" / "Spanish" / "layers" / "english_loanwords.json")
    is_spanish = 'Spanish' in (layers_dir or '') or 'spanish' in (artist_dir or '')
    if args.use_loanword_skip and is_spanish and os.path.isfile(loanwords_path):
        with open(loanwords_path) as f:
            loanwords = json.load(f)
        # Allow per-artist override via curated keep-list (future hook).
        # For now, the broad set goes straight into skip_set.
        added = 0
        for w in loanwords.keys():
            if w not in skip_set:
                skip_set.add(w)
                added += 1
        print("  Skip words (English loanword layer): +%d" % added)

    # Load master for flag lookups (fallback when skip_words.json absent).
    # Master vocabulary is artist-mode only.
    master_flags = {}
    if is_artist:
        artists_dir = os.path.dirname(artist_dir)
        master_path = os.path.join(artists_dir, "vocabulary_master.json")
        if os.path.isfile(master_path):
            with open(master_path) as f:
                for mid, mv in json.load(f).items():
                    wl = "%s|%s" % (mv["word"], mv.get("lemma", mv["word"]))
                    master_flags[wl] = mv

    skipped_flags = 0
    skipped_short = 0
    skipped_not_slang = 0
    skipped_priority = 0
    pos_filtered_count = 0
    pos_single_sense_count = 0
    auto_vetoed_examples = 0
    auto_vetoed_words = set()

    # Load existing assignments for priority checking + gap-fill reuse
    existing_assigns = {}
    if args.assignments_file == "sense_assignments/wiktionary.json":
        if is_artist:
            assignments_path = artist_sense_assignments_path(layers_dir, "wiktionary")
        else:
            assignments_path = str(sense_assignments_path(layers_dir, "wiktionary"))
    else:
        assignments_path = os.path.join(layers_dir, args.assignments_file)
    if os.path.isfile(assignments_path):
        existing_assigns = load_assignments(assignments_path)

    if args.method_name and use_gemini:
        my_method = args.method_name
    elif args.keyword_method_name and not use_gemini:
        my_method = args.keyword_method_name
    elif custom_menu_mode and not use_gemini:
        my_method = "spanishdict-keyword"
    elif custom_menu_mode and args.prompt_id == "sd-lexical-v1-g31":
        my_method = "spanishdict-lexical-g31"
    elif custom_menu_mode and args.prompt_id == "sd-lexical-v2-g35":
        my_method = "spanishdict-lexical-g35"
    elif custom_menu_mode and args.prompt_id == "sd-lexical-v2-g31":
        my_method = "spanishdict-lexical-g31-v2"
    elif custom_menu_mode and args.prompt_id == "sd-lexical-v2-g25":
        my_method = "spanishdict-lexical-g25-v2"
    elif custom_menu_mode and "flash-lite" in gemini_model:
        my_method = "spanishdict-flash-lite"
    elif custom_menu_mode:
        my_method = "spanishdict-flash"
    elif not use_gemini:
        my_method = "keyword-wiktionary"
    elif "flash-lite" in gemini_model:
        my_method = "flash-lite-wiktionary"
    else:
        my_method = "flash-wiktionary"
    my_priority = METHOD_PRIORITY.get(my_method, 0)
    proposal_method = (
        {"sd-lexical-v1-g31": "lexical-gap-fill-g31",
         "sd-lexical-v2-g35": "lexical-gap-fill-g35",
         "sd-lexical-v2-g31": "lexical-gap-fill-g31-v2",
         "sd-lexical-v2-g25": "lexical-gap-fill-g25-v2"}.get(
             args.prompt_id, "gap-fill")
    )

    # For --normal-slang-only: load normal-mode senses
    normal_wl = set()
    if args.normal_slang_only:
        normal_senses_path = PROJECT_ROOT / "Data/Spanish/layers/sense_menu/wiktionary.json"
        if normal_senses_path.exists():
            with open(normal_senses_path) as f:
                normal_wl = set(json.load(f).keys())
            print("  Normal-mode senses: %d entries" % len(normal_wl))

    # For --new-only: use step 4's remaining list as whitelist
    new_only_words = set()
    if args.new_only:
        if os.path.isfile(routing_path):
            # schema_v2 renamed gemini → sense_discovery; read both for
            # backward-compat.
            new_only_words = set(
                routing_data.get("sense_discovery", routing_data.get("gemini", []))
            )
            if args.all_gemini:
                # schema_v2 renamed biencoder → classifier and hoisted
                # derivation out to top-level derivation_map. Walk both
                # schema shapes so --all-gemini --new-only catches every
                # routed word.
                classifier_section = routing_data.get(
                    "classifier", routing_data.get("biencoder", {})
                )
                for value in classifier_section.values():
                    if isinstance(value, list):
                        new_only_words.update(value)
                    elif isinstance(value, dict):
                        # schema_v1 had derivation as a {form: base} dict
                        # nested under biencoder; schema_v2 hoists it to
                        # top-level derivation_map.
                        new_only_words.update(value.keys())
                derivation_map = routing_data.get("derivation_map", {})
                if isinstance(derivation_map, dict):
                    new_only_words.update(derivation_map.keys())
            print("  --new-only whitelist (from step 4): %d words" % len(new_only_words))
        else:
            print("  WARNING: word_routing.json not found — run step 4 first")
            sys.exit(1)

    target_words = set(args.word) if args.word else None
    if target_words is not None:
        print("\n--word mode: processing only %d targeted words: %s"
              % (len(target_words), sorted(target_words)))
    else:
        print("\nProcessing %d words..." % len(inventory))

    for entry in inventory:
        word = entry["word"]
        lemma = word
        corpus_count = entry.get("corpus_count", 1)

        # --word filter: process only the targeted set when set.
        if target_words is not None and word not in target_words:
            continue

        # Skip words flagged by step 4 (preferred) or master flags (fallback)
        if word in skip_set:
            skipped_flags += 1
            continue
        # Skip contractions (elision forms handled by step 3's merge).
        # We no longer blanket-skip len<=2 — that was a legacy cost-saver
        # that broke Gemini classification for core function words (de, no,
        # y, en, me, lo, el, se, te, mi, tu, un, a). word_routing.exclude
        # and the noise curation already handle genuine single-letter noise.
        if "'" in word:
            skipped_short += 1
            continue

        # --normal-slang-only: only process words in normal mode that have eswiktionary senses
        if args.normal_slang_only:
            if wl_key not in normal_wl:
                skipped_not_slang += 1
                continue
            has_eswikt = bool(eswikt_index.get(word) or eswikt_index.get(lemma))
            if not has_eswikt:
                skipped_not_slang += 1
                continue

        # --new-only: only process words in step 4's remaining list
        if args.new_only:
            if word not in new_only_words:
                skipped_not_slang += 1
                continue

        # Skip words claimed by a STRICTLY higher-priority method. For the same
        # method we used to also skip at word level; now that selection is
        # example-level, equal priority is handled by the covered-index filter
        # below instead.
        if (word in existing_assigns and not args.force
                and not args.replace_prompt_id):
            existing_priority = best_method_priority(existing_assigns[word])
            if existing_priority > my_priority:
                skipped_priority += 1
                continue

        # Target window into the current per-word examples list. Stable
        # segment/example/occurrence references are the authoritative join;
        # numeric indices remain a legacy fallback only.
        all_exs = examples_raw.get(word, [])
        target_end = min(len(all_exs), args.max_examples)
        if target_end == 0:
            no_examples += 1
            continue

        replacement_abs = None
        if args.replace_prompt_id:
            replacement_items = []
            for method_name, items in (existing_assigns.get(word) or {}).items():
                is_non_model = (method_name.endswith("-auto") or
                                (method_name.startswith("legacy-")
                                 and method_name.endswith("-v1")))
                if is_non_model:
                    continue
                replacement_items.extend(
                    item for item in (items or [])
                    if isinstance(item, dict)
                    and item.get("prompt_id") in args.replace_prompt_id)
            replacement_abs = covered_example_indices(
                replacement_items, all_exs, allow_legacy_indices=False)
            if not replacement_abs:
                continue

        # Which absolute indices is THIS method already responsible for?
        # Only same-method coverage counts — we want incrementality inside
        # gemini runs, but a prior biencoder assignment shouldn't block gemini
        # from doing its own pass.
        covered_abs = set()
        if not args.force and word in existing_assigns:
            covered_abs.update(covered_example_indices(
                existing_assigns[word].get(my_method, []), all_exs))
            # Single-sense auto-assignment uses auto_method_name, not my_method.
            # Treat those as covered too so re-runs don't re-auto-assign them.
            covered_abs.update(covered_example_indices(
                existing_assigns[word].get(args.auto_method_name, []), all_exs))
            # Same-priority methods from prior runs (gap-fill at 50, any
            # other future equal-tier method). Without this, a word with
            # an existing gap-fill claim on every example would still fall
            # through the word-level priority check (which uses strict `>`
            # so equal tiers don't block) and re-queue for a full
            # re-classification every run. Union their covered examples
            # into the skip set.
            for method_name, items in (existing_assigns[word] or {}).items():
                if method_name in (my_method, args.auto_method_name):
                    continue
                for item in items or []:
                    is_retained = (method_name.startswith("legacy-")
                                   and method_name.endswith("-v1"))
                    is_deterministic = method_name.endswith("-auto")
                    # Match the named active deck/inspector policy. The target
                    # prompt also covers its own prior partial results so a
                    # checkpointed/rerun candidate remains incremental without
                    # becoming accepted for shipping.
                    is_trusted_prompt = (
                        item.get("prompt_id") in accepted_model_prompt_ids
                        or item.get("prompt_id") == args.prompt_id)
                    prio = METHOD_PRIORITY.get(method_name, 0)
                    if (prio < my_priority and not is_retained
                            and not is_deterministic
                            and not is_trusted_prompt):
                        continue
                    covered_abs.update(covered_example_indices([item], all_exs))

        # Build the (abs_idx, ex) list of NEW examples in the target window.
        selected = [(abs_i, all_exs[abs_i]) for abs_i in range(target_end)
                    if abs_i not in covered_abs
                    and (replacement_abs is None or abs_i in replacement_abs)]
        if not selected:
            # Target window fully covered by prior same-method work — nothing
            # to do. Any existing assignment is preserved untouched.
            skipped_priority += 1
            continue

        # Per-example spaCy POS tags. Hoisted above the example-build loop so
        # each example dict can carry its own tag into the prompt (see
        # _format_example_line). Previously this was computed after the loop
        # and used only for menu filtering, so the per-example POS signal never
        # reached Gemini at all.
        precomputed = {int(k): v for k, v in example_pos.get(word, {}).items()}

        examples = []
        abs_indices = []
        for abs_i, ex in selected:
            # Support both lyric format (spanish/title) and corpus format
            # (target/english) so artist examples_raw.json can contain a mix
            # of lyric lines and OpenSubs examples added by tool_5a_extend_examples.
            spa = ex.get("spanish") or ex.get("target", "")
            # Normalize elided surface forms to canonical word for Gemini
            surface = ex.get("surface")
            if surface and surface.lower() != word.lower() and spa:
                spa = re.sub(re.escape(surface), word, spa, count=1, flags=re.IGNORECASE)
            # Corpus examples already carry an English translation; lyric
            # examples need a translation lookup from the sidecar cache.
            eng = ex.get("english", "")
            if not eng:
                original_spa = ex.get("spanish", "")
                eng_obj = translations.get(original_spa)
                eng = eng_obj.get("english", "") if isinstance(eng_obj, dict) else (eng_obj or "")
            song_label = ex.get("title") or ex.get("source", "")
            examples.append({"spanish": spa, "english": eng,
                             "song": song_label, "id": ex.get("id", ""),
                             "pos": precomputed.get(abs_i),
                             "artist": ex.get("artist", "")})
            abs_indices.append(abs_i)

        if not examples:
            no_examples += 1
            continue

        wl_key = "%s|%s" % (word, lemma)
        mf = master_flags.get(wl_key, {})
        # is_noise replaces is_interjection in schema_v2; read both for
        # compatibility with master entries built before the rename.
        if (mf.get("is_english") or mf.get("is_propernoun")
                or mf.get("is_noise") or mf.get("is_interjection")):
            skipped_flags += 1
            continue

        id_list = []
        # Build the candidate menu from all shared surface-form analyses first.
        if custom_menu_mode:
            resolved_lemma, resolved_analyses, _resolution_kind = (
                resolve_custom_menu_analyses(
                    word, shared_wikt_menu, routing_data=routing_data,
                    conjugation_reverse=conjugation_reverse))
            if resolved_analyses:
                lemma = resolved_lemma
            shared_analyses = []
            for analysis in resolved_analyses:
                sense_map = analysis.get("senses", {})
                shared_analyses.append({
                    "headword": analysis.get("headword", analysis.get("lemma", word)),
                    # Preserve explicit provider/registry IDs. Converting this
                    # dict to values made short hash IDs depend on source
                    # order and could silently swap old assignment meanings.
                    "senses": deepcopy(sense_map or {}),
                })
        else:
            shared_analyses = collect_surface_analyses_from_shared_menu(word, shared_wikt_menu)
        if shared_analyses and not custom_menu_mode:
            present_lemmas = {a.get("headword", a.get("lemma", word)) for a in shared_analyses}
            for target_lemma in extract_form_of_targets(shared_analyses):
                if target_lemma in present_lemmas:
                    continue
                target_senses = lookup_senses(word, target_lemma, wikt_index, redirects)
                if not target_senses:
                    continue
                for s in target_senses:
                    s["translation"] = clean_translation(s["translation"])
                target_senses = merge_similar_senses(target_senses)
                if target_senses:
                    shared_analyses.append({"headword": target_lemma, "senses": target_senses})
                    present_lemmas.add(target_lemma)
        if shared_analyses:
            en_senses, id_list, normalized_analyses = flatten_analyses_with_ids(shared_analyses)
            if not custom_menu_mode:
                for analysis in normalized_analyses:
                    merge_analysis(senses_out, word, analysis.get("headword", analysis.get("lemma")), analysis.get("senses", {}))
        else:
            en_senses = []
        if not en_senses and not custom_menu_mode:
            en_senses = lookup_senses(word, lemma, wikt_index, redirects)
            if en_senses:
                for s in en_senses:
                    s["translation"] = clean_translation(s["translation"])
                en_senses = merge_similar_senses(en_senses)
            else:
                en_senses = []

        if custom_menu_mode:
            combined = en_senses
        else:
            combined = build_combined_senses(word, lemma, en_senses, eswikt_index,
                                             translation_cache)
        if id_list and len(combined) > len(id_list):
            id_list.extend(
                extend_ids_for_extra_senses(id_list, lemma, combined[len(id_list):])
            )

        if not combined:
            # No entry — queue for gap-fill for either Wiktionary or custom menu sources.
            # `corpus_count > 1` was the only gate here, and on a fixed lyric
            # corpus it excludes almost all genre slang: `bellaqueos`, `feka`,
            # `switchear`, `tenqui` and `bichota` each appear exactly once in
            # the test playlist, so none of them could ever reach gap-fill. The
            # six words that did get through were the ad-libs frequent enough to
            # clear it (`brum`, `ratatá`, `guro`). This is the same floor
            # step_4a applies -- applying it twice does not make it better
            # evidence, and a hapax in a playlist is not a hapax in the language.
            # Routing to sense_discovery is the stronger signal, so it admits;
            # the count stays as the fallback where no routing data exists.
            if word in discovery_words or corpus_count > 1:
                no_senses_queue.append((word, lemma, examples, abs_indices))
            continue

        keep_indices = list(range(len(combined)))
        if precomputed:
            pos_keep_indices, pos_stats = filter_senses_by_precomputed_pos(combined, precomputed)
        else:
            pos_keep_indices, pos_stats = filter_senses_by_pos(word, lemma, combined, examples)
        if pos_stats.get("used") and pos_stats.get("reduced"):
            keep_indices = pos_keep_indices
            pos_filtered_count += 1

        if len(keep_indices) == 1:
            filtered_combined = [combined[keep_indices[0]]]
            if shared_analyses:
                sid = id_list[keep_indices[0]]
            else:
                id_map = assign_analysis_sense_ids(lemma, filtered_combined)
                if not custom_menu_mode:
                    merge_analysis(senses_out, word, None, id_map)
                sid = list(id_map.keys())[0]
            allowed_abs = []
            rejected_examples = []
            rejected_abs = []
            for example, abs_i in zip(examples, abs_indices):
                reason = auto_sense_rejection_reason(
                    word, filtered_combined[0], example, precomputed.get(abs_i))
                if reason:
                    auto_vetoed_examples += 1
                    auto_vetoed_words.add(word)
                    rejected_examples.append(example)
                    rejected_abs.append(abs_i)
                else:
                    allowed_abs.append(abs_i)
            if allowed_abs:
                # Single sense: auto-assign only compatible NEW examples.
                single_sense += 1
                selected_method = args.auto_method_name
                if len(combined) > 1:
                    pos_single_sense_count += 1
                    selected_method = "pos-auto"
                assignments_out[word] = {selected_method: [{
                    "sense": sid,
                    "examples": allowed_abs,
                }]}
            if rejected_abs:
                # The menu does not contain a compatible sense for these
                # occurrences. Route them through the normal proposal path;
                # --skip-gap-fill leaves them safely unassigned.
                no_senses_queue.append(
                    (word, lemma, rejected_examples, rejected_abs))
        else:
            # Multi-sense at the word level. Before batching to Gemini, run a
            # per-example pos-auto pre-filter: examples whose trusted POS tag
            # narrows candidates to exactly 1 sense get assigned inline and
            # never see the API. Only ambiguous-POS examples are sent.
            #
            # Cost saving: across every language with a POS tagger and
            # polysemous menus, a large fraction of examples resolve on POS
            # alone — those used to burn prompt tokens re-confirming a
            # single candidate.
            filtered_combined = [combined[i] for i in keep_indices]
            filtered_ids = [id_list[i] for i in keep_indices] if shared_analyses else None
            if not shared_analyses and not custom_menu_mode:
                id_map = assign_analysis_sense_ids(lemma, filtered_combined)
                merge_analysis(senses_out, word, lemma, id_map)
                local_id_list = list(id_map.keys())
            else:
                local_id_list = filtered_ids or [id_list[i] for i in keep_indices]

            pos_auto_by_sense = {}  # local keep-index -> [abs_ex_idx]
            classify_local_indices = []  # positions within examples/abs_indices
            for local_pos, ex in enumerate(examples):
                abs_ex_idx = abs_indices[local_pos]
                ex_pos = precomputed.get(abs_ex_idx)
                if ex_pos:
                    pos_candidates = [k for k in range(len(keep_indices))
                                      if sense_compatible_with_example_pos(
                                          filtered_combined[k].get("pos"), ex_pos)]
                    if not pos_candidates:
                        pos_candidates = list(range(len(keep_indices)))
                else:
                    pos_candidates = list(range(len(keep_indices)))

                if len(pos_candidates) == 1:
                    pos_auto_by_sense.setdefault(pos_candidates[0], []).append(abs_ex_idx)
                else:
                    classify_local_indices.append(local_pos)

            if pos_auto_by_sense:
                assignments_out.setdefault(word, {})["pos-auto"] = [
                    {"sense": local_id_list[k], "examples": eis}
                    for k, eis in pos_auto_by_sense.items()
                ]
                pos_single_sense_count += 1

            # If pos-auto handled every example, nothing left for Gemini.
            if classify_local_indices:
                classify_examples = [examples[i] for i in classify_local_indices]
                classify_abs = [abs_indices[i] for i in classify_local_indices]
                multi_sense_queue.append((word, lemma, filtered_combined,
                                          classify_examples, filtered_ids,
                                          classify_abs))

    print("  Skipped (english/propn/intj): %d" % skipped_flags)
    print("  Skipped (short/contraction): %d" % skipped_short)
    if skipped_priority:
        print("  Skipped (higher-priority method): %d" % skipped_priority)
    if args.normal_slang_only:
        print("  Skipped (no eswikt or not in normal): %d" % skipped_not_slang)
    if args.new_only:
        print("  Skipped (normal-mode or freq<=1): %d" % skipped_not_slang)
    if pos_filtered_count:
        print("  POS-filtered menus: %d" % pos_filtered_count)
    if pos_single_sense_count:
        print("  POS-resolved to single sense: %d" % pos_single_sense_count)
    if auto_vetoed_examples:
        print("  Single-sense auto vetoes: %d example(s)" % auto_vetoed_examples)
    print("  No examples (skipped): %d" % no_examples)
    print("  Single-sense (auto-assigned): %d" % single_sense)
    print("  Multi-sense (need classifier): %d" % len(multi_sense_queue))
    print("  No sense menu entry (need gap-fill): %d" % len(no_senses_queue))

    # ---------------------------------------------------------------------------
    # SpanishDict classify-or-propose (unified classification + gap-fill)
    # ---------------------------------------------------------------------------
    # One Gemini call per batch decides, for each example, whether a menu sense
    # fits (classification) or none does (proposes an off-menu gloss + register
    # tag). This replaces the separate classify + gap-fill passes for the
    # SpanishDict source only — wiktionary / normal mode keep the legacy paths
    # below untouched.
    if sd_gemini_mode:
        artist_context = _artist_context(config)
        corpus_counts = {e.get("word"): e.get("corpus_count", 1) for e in inventory}
        review_items = []  # off-menu proposals for the review queue

        # Unified record list from both queues. Multi-sense words carry a menu
        # (pick a sense or propose off-menu); zero-sense words carry an empty
        # menu (always proposes). --skip-classification / --skip-gap-fill let
        # the dispatcher run just one half.
        records = []
        if not args.skip_classification:
            for word, lemma, senses, examples, explicit_ids, abs_idx_list in multi_sense_queue:
                idl = list(explicit_ids) if explicit_ids else list(
                    assign_analysis_sense_ids(lemma, senses).keys())
                records.append({
                    "word": word, "lemma": lemma, "senses": senses, "ids": idl,
                    "examples": examples, "abs": abs_idx_list,
                    "allow_propose": not args.skip_gap_fill,
                })
        if not args.skip_gap_fill:
            for word, lemma, examples, abs_idx_list in no_senses_queue:
                records.append({
                    "word": word, "lemma": lemma, "senses": [], "ids": [],
                    "examples": examples, "abs": abs_idx_list,
                    "allow_propose": True,
                })
        # These queues are now owned by this block; blank them so the legacy
        # classify + gap-fill sections below become no-ops.
        multi_sense_queue = []
        no_senses_queue = []

        if args.dry_run_prompt:
            _dump_prompts_and_exit(
                "classify-or-propose", SD_CLASSIFY_BATCH_SIZE, records,
                lambda batch: build_classify_or_propose_prompt(
                    [{"word": r["word"], "lemma": r["lemma"],
                      "senses": r["senses"], "ids": r["ids"],
                      "examples": r["examples"]} for r in batch],
                    artist_context),
                plan_path=args.prompt_plan_json)

        if records:
            print("\n" + "=" * 60)
            print("CLASSIFY-OR-PROPOSE %d SpanishDict words (%s, batches of %d)" % (
                len(records), gemini_model, SD_CLASSIFY_BATCH_SIZE))
            print("=" * 60)

            checkpoint_path = _checkpoint_path(
                layers_dir, args.assignments_file, args.prompt_id, gemini_model)
            done_words = set()
            if os.path.isfile(checkpoint_path):
                with open(checkpoint_path) as f:
                    checkpoint = json.load(f)
                if (checkpoint.get("prompt_id") != args.prompt_id
                        or checkpoint.get("gemini_model") != gemini_model
                        or checkpoint.get("assignments_file") != args.assignments_file):
                    raise RuntimeError(
                        "Checkpoint provenance mismatch: %s" % checkpoint_path)
                for word, word_data in checkpoint.get("assignments", {}).items():
                    assignments_out[word] = normalize_assignment_methods(word_data, my_method)
                done_words = set(checkpoint.get("done_words", []))
                review_items = checkpoint.get("review_items", []) or []
                if done_words:
                    print("  Resuming from checkpoint: %d words done" % len(done_words))

            def process_sd_batch(batch_start, batch):
                batch_no = batch_start // SD_CLASSIFY_BATCH_SIZE + 1
                print("  Batch %d: %s" % (batch_no, [r["word"] for r in batch][:5]))
                batch_data = [{"word": r["word"], "lemma": r["lemma"],
                               "senses": r["senses"], "ids": r["ids"],
                               "examples": r["examples"]} for r in batch]
                results = classify_or_propose_batch(
                    batch_data, api_key, gemini_model, artist_context)
                result_map = {}
                if isinstance(results, list):
                    for o in results:
                        if isinstance(o, dict) and o.get("word") is not None:
                            result_map[o["word"]] = o.get("calls") or []

                batch_assignments = {}
                batch_review_items = []
                batch_proposed_total = 0
                batch_classified_total = 0
                batch_done_words = []
                for r in batch:
                    word = r["word"]
                    calls = result_map.get(word, [])
                    id_set = set(r["ids"])
                    menu_buckets = {}   # sid -> [abs_idx]
                    proposed_map = {}   # gloss -> {examples, pos, ex}
                    abstentions = []
                    _VALID_POS = {"NOUN", "VERB", "ADJ", "ADV", "INTJ"}
                    for call in calls:
                        if not isinstance(call, dict):
                            continue
                        try:
                            li = int(call.get("example")) - 1
                        except (TypeError, ValueError):
                            continue
                        if not (0 <= li < len(r["abs"])):
                            continue
                        abs_i = r["abs"][li]
                        sense = call.get("sense")
                        sid = None
                        if sense not in (None, "null", "", "None"):
                            s = str(sense)
                            if s in id_set:
                                sid = s
                            elif s.lstrip("-").isdigit() and 0 <= int(s) < len(r["ids"]):
                                sid = r["ids"][int(s)]
                        if sid is not None:
                            menu_buckets.setdefault(sid, []).append(abs_i)
                        elif r["allow_propose"] and call.get("proposed"):
                            gloss = str(call["proposed"]).strip()
                            if not gloss:
                                continue
                            pm = proposed_map.setdefault(gloss, {
                                "examples": [], "pos": call.get("proposed_pos"),
                                "ex": r["examples"][li] if li < len(r["examples"]) else {},
                            })
                            pm["examples"].append(abs_i)
                        elif call.get("abstain_reason"):
                            abstentions.append({
                                "example": abs_i,
                                "reason": str(call.get("abstain_reason")),
                            })
                        elif r["ids"]:
                            # Invalid output is not evidence. Leave it
                            # unassigned so it remains visible in the rerun
                            # backlog rather than silently choosing sense 0.
                            abstentions.append({"example": abs_i,
                                                "reason": "invalid_output"})
                        # else: no menu + no proposal -> leave example unassigned.

                    word_out = {}
                    if menu_buckets:
                        items = []
                        total = sum(len(v) for v in menu_buckets.values())
                        for sid in sorted(menu_buckets):
                            eis = sorted(set(menu_buckets[sid]))
                            freq = len(eis) / total if total else 0
                            if total >= 5 and freq < 0.05:
                                continue
                            item = {"sense": sid, "examples": eis}
                            items.append(item)
                        if items:
                            word_out[my_method] = items
                            batch_classified_total += 1
                    if proposed_map:
                        gf_items = []
                        # Prefer the POS the model returned for the proposed
                        # meaning ("attractive" -> ADJ); fall back to the word's
                        # dominant menu POS only when it's missing/invalid.
                        fallback_pos = _dominant_pos(r["senses"]) or "NOUN"
                        _valid_pos = _VALID_POS
                        for gloss, pm in proposed_map.items():
                            prop_pos = str(pm.get("pos") or "").strip().upper()
                            pos = prop_pos if prop_pos in _valid_pos else fallback_pos
                            # Prose guard: proposals must be short lexical
                            # glosses, never descriptions or phrase meanings.
                            if _is_definitional(gloss):
                                repaired = _repair_proposed_sense(
                                    word, r["lemma"], r["examples"], gloss,
                                    api_key, gemini_model)
                                if repaired and repaired.get("proposed_sense"):
                                    new_gloss = str(repaired["proposed_sense"]).strip()
                                    rp = str(repaired.get("proposed_pos") or "").strip().upper()
                                    print("    repaired %r: %r → %r" % (
                                        word, gloss[:50], new_gloss))
                                    gloss = new_gloss
                                    if rp in _valid_pos:
                                        pos = rp
                            sense_list = [{"pos": pos, "translation": gloss,
                                           "source": "gap-fill"}]
                            sid = list(assign_sense_ids(sense_list).keys())[0]
                            item = {"sense": sid, "pos": pos, "translation": gloss,
                                    "lemma": r["lemma"],
                                    "examples": sorted(set(pm["examples"]))}
                            gf_items.append(item)
                            batch_proposed_total += 1
                            ex = pm.get("ex") or {}
                            batch_review_items.append({
                                "word": word,
                                "lemma": r["lemma"],
                                "proposed": gloss,
                                "corpus_count": corpus_counts.get(word, 0),
                                "example": ex.get("spanish", ""),
                                "translation": ex.get("english", ""),
                            })
                        if gf_items:
                            word_out[proposal_method] = gf_items

                    for abstention in abstentions:
                        ex_i = abstention["example"]
                        ex = r["examples"][r["abs"].index(ex_i)] if ex_i in r["abs"] else {}
                        batch_review_items.append({
                            "word": word,
                            "lemma": r["lemma"],
                            "abstain_reason": abstention["reason"],
                            "corpus_count": corpus_counts.get(word, 0),
                            "example_index": ex_i,
                            "example": ex.get("spanish", ""),
                            "translation": ex.get("english", ""),
                        })

                    if word_out:
                        batch_assignments[word] = word_out
                    batch_done_words.append(word)

                return {
                    "batch_no": batch_no,
                    "assignments": batch_assignments,
                    "done_words": batch_done_words,
                    "review_items": batch_review_items,
                    "classified_total": batch_classified_total,
                    "proposed_total": batch_proposed_total,
                }

            def apply_sd_batch(result):
                for word, word_out in result["assignments"].items():
                    existing_wo = assignments_out.setdefault(word, {})
                    for k, v in word_out.items():
                        existing_wo[k] = v
                done_words.update(result["done_words"])
                review_items.extend(result["review_items"])
                with open(checkpoint_path, "w") as f:
                    json.dump({"prompt_id": args.prompt_id,
                               "gemini_model": gemini_model,
                               "assignments_file": args.assignments_file,
                               "assignments": assignments_out,
                               "done_words": sorted(done_words),
                               "review_items": review_items}, f)

            t_start = time.time()
            proposed_total = 0
            classified_total = 0
            pending_batches = []
            for batch_start in range(0, len(records), SD_CLASSIFY_BATCH_SIZE):
                batch = records[batch_start:batch_start + SD_CLASSIFY_BATCH_SIZE]
                batch = [r for r in batch if r["word"] not in done_words]
                if batch:
                    pending_batches.append((batch_start, batch))

            workers = min(args.gemini_workers, len(pending_batches) or 1)
            if workers > 1:
                print("  Running with %d concurrent Gemini batches" % workers)
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [
                        executor.submit(process_sd_batch, batch_start, batch)
                        for batch_start, batch in pending_batches
                    ]
                    for fut in concurrent.futures.as_completed(futures):
                        result = fut.result()
                        apply_sd_batch(result)
                        classified_total += result["classified_total"]
                        proposed_total += result["proposed_total"]
            else:
                for batch_start, batch in pending_batches:
                    result = process_sd_batch(batch_start, batch)
                    apply_sd_batch(result)
                    classified_total += result["classified_total"]
                    proposed_total += result["proposed_total"]

            elapsed = time.time() - t_start
            print("  Done (%.1fs): %d words with menu senses, %d proposals" % (
                elapsed, classified_total, proposed_total))

        # Review queue: off-menu proposals ranked by corpus_count (artist mode).
        if is_artist:
            reports_dir = os.path.join(artist_dir, "data", "reports")
            os.makedirs(reports_dir, exist_ok=True)
            review_path = os.path.join(reports_dir, "sd_insufficient_review.json")
            existing_review = []
            if os.path.isfile(review_path):
                try:
                    with open(review_path) as f:
                        loaded = json.load(f)
                    existing_review = loaded.get("items", []) if isinstance(loaded, dict) else loaded
                except (json.JSONDecodeError, ValueError):
                    existing_review = []
            # De-duplicate proposals and abstentions; newest entry wins.
            merged = {}
            for it in (existing_review or []) + review_items:
                if isinstance(it, dict):
                    merged[(it.get("word"), it.get("proposed"),
                            it.get("example_index"),
                            it.get("abstain_reason"))] = it
            ranked = sorted(merged.values(),
                            key=lambda it: (it.get("corpus_count") or 0),
                            reverse=True)
            with open(review_path, "w", encoding="utf-8") as f:
                json.dump({
                    "_meta": {"source": "spanishdict",
                              "classifier": "lexical-wsd-propose",
                              "prompt_id": args.prompt_id,
                              "model": gemini_model,
                              "count": len(ranked)},
                    "items": ranked,
                }, f, ensure_ascii=False, indent=2)
            print("  Review queue: %d off-menu items -> %s" % (len(ranked), review_path))

    # ---------------------------------------------------------------------------
    # Classify multi-sense words
    # ---------------------------------------------------------------------------
    if args.skip_classification:
        print("\n  Skipping multi-sense classification (--skip-classification)")
        multi_sense_queue = []
    if multi_sense_queue and args.dry_run_prompt and use_gemini:
        _dump_prompts_and_exit(
            "classify (wiktionary)", BATCH_SIZE,
            [{"word": w, "lemma": l, "senses": s, "examples": ex}
             for w, l, s, ex, ids, abs_idx in multi_sense_queue],
            lambda batch: build_classify_prompt(batch),
            plan_path=args.prompt_plan_json)
    if multi_sense_queue:
        print("\n" + "=" * 60)
        if use_gemini:
            print("CLASSIFYING %d multi-sense words (%s, batches of %d)" % (
                len(multi_sense_queue), gemini_model, BATCH_SIZE))
        else:
            print("CLASSIFYING %d multi-sense words (keyword fallback)" % len(multi_sense_queue))
        print("=" * 60)

        t_start = time.time()
        checkpoint_path = _checkpoint_path(
            layers_dir, args.assignments_file, args.prompt_id, gemini_model)

        # Load checkpoint if exists
        done_words = set()
        if os.path.isfile(checkpoint_path):
            with open(checkpoint_path) as f:
                checkpoint = json.load(f)
            for word, word_data in checkpoint.get("assignments", {}).items():
                assignments_out[word] = normalize_assignment_methods(
                    word_data,
                    my_method,
                )
            done_words = set(checkpoint.get("done_words", []))
            print("  Resuming from checkpoint: %d words done" % len(done_words))

        if use_gemini:
            for batch_start in range(0, len(multi_sense_queue), BATCH_SIZE):
                batch = multi_sense_queue[batch_start:batch_start + BATCH_SIZE]
                # Skip batches where all words are already done
                batch = [tup for tup in batch if tup[0] not in done_words]
                if not batch:
                    continue
                batch_data = [{"word": w, "lemma": l, "senses": s,
                               "examples": ex}
                              for w, l, s, ex, ids, abs_idx in batch]
                batch_words = [tup[0] for tup in batch]
                print("  Batch %d: %s" % (
                    batch_start // BATCH_SIZE + 1, batch_words[:5]))

                results = classify_batch_gemini(batch_data, api_key, gemini_model)

                for i, (word, lemma, senses, examples, explicit_ids, abs_idx_list) in enumerate(batch):
                    id_list = explicit_ids or list(assign_analysis_sense_ids(lemma, senses).keys())

                    if results and i < len(results):
                        r = results[i]
                        raw_assigns = r.get("assignments", {})
                        # Group examples by sense ID, translating Gemini's
                        # 1-indexed local position back to the absolute index
                        # in examples_raw[word].
                        sense_buckets = {}
                        for ex_key, sense_idx in raw_assigns.items():
                            idx = int(sense_idx) if str(sense_idx).lstrip("-").isdigit() else 0
                            if idx < 0 or idx >= len(id_list):
                                idx = 0
                            sid = id_list[idx]
                            local_ex_idx = int(ex_key) - 1  # 1-indexed → 0-indexed local
                            if not (0 <= local_ex_idx < len(abs_idx_list)):
                                continue
                            abs_ex_idx = abs_idx_list[local_ex_idx]
                            sense_buckets.setdefault(sid, []).append(abs_ex_idx)

                        assignments = []
                        total = sum(len(v) for v in sense_buckets.values())
                        for sid in sorted(sense_buckets):
                            ex_indices = sorted(sense_buckets[sid])
                            freq = len(ex_indices) / total if total else 0
                            if total >= 5 and freq < 0.05:
                                continue
                            assignments.append({
                                "sense": sid,
                                "examples": ex_indices,
                            })
                        if not assignments:
                            assignments = [{"sense": id_list[0],
                                            "examples": list(abs_idx_list)}]
                        assignments_out[word] = {my_method: assignments}
                    else:
                        # Fallback: assign all to first sense (absolute indices)
                        assignments_out[word] = {my_method: [{
                            "sense": id_list[0] if id_list else "000",
                            "examples": list(abs_idx_list),
                        }]}
                    done_words.add(word)

                # Checkpoint after each batch
                with open(checkpoint_path, "w") as f:
                    json.dump({"prompt_id": args.prompt_id,
                               "gemini_model": gemini_model,
                               "assignments_file": args.assignments_file,
                               "assignments": assignments_out,
                               "done_words": sorted(done_words)}, f)
        else:
            # Keyword fallback
            for word, lemma, senses, examples, explicit_ids, abs_idx_list in multi_sense_queue:
                id_list = explicit_ids or list(assign_analysis_sense_ids(lemma, senses).keys())
                assigns = classify_keyword(examples, senses)
                sense_buckets = {}
                for ei, si in enumerate(assigns):
                    sid = id_list[si] if si < len(id_list) else id_list[0]
                    if not (0 <= ei < len(abs_idx_list)):
                        continue
                    sense_buckets.setdefault(sid, []).append(abs_idx_list[ei])
                assignments = []
                total = len(assigns)
                for sid in sorted(sense_buckets):
                    ex_indices = sorted(sense_buckets[sid])
                    freq = len(ex_indices) / total if total else 0
                    if total >= 5 and freq < 0.05:
                        continue
                    assignments.append({
                        "sense": sid,
                        "examples": ex_indices,
                    })
                if not assignments:
                    assignments = [{"sense": id_list[0],
                                    "examples": list(abs_idx_list)}]
                assignments_out[word] = {my_method: assignments}

        elapsed = time.time() - t_start
        print("  Done (%.1fs)" % elapsed)

    # ---------------------------------------------------------------------------
    # Gap-fill for words without any usable sense menu
    # ---------------------------------------------------------------------------
    if args.skip_gap_fill:
        print("\n  Skipping gap-fill (--skip-gap-fill)")
        no_senses_queue = []
    if no_senses_queue and use_gemini and args.dry_run_prompt:
        _dump_prompts_and_exit(
            "gap-fill (wiktionary)", GAP_FILL_BATCH_SIZE,
            [{"word": w, "lemma": l, "senses": [], "examples": ex}
             for w, l, ex, abs_idx in no_senses_queue],
            build_gap_fill_batch_prompt,
            plan_path=args.prompt_plan_json)
    if no_senses_queue and use_gemini:
        print("\n" + "=" * 60)
        print("GAP-FILL %d words without sense-menu entry" % len(no_senses_queue))
        print("=" * 60)

        # Check existing assignments for reusable gap-fill senses
        reused = 0
        need_gemini = []
        for word, lemma, examples, abs_idx_list in no_senses_queue:
            existing = existing_assigns.get(word, {})
            gf = existing.get("gap-fill", [])
            # Reuse if the existing gap-fill has inline sense definitions
            if gf and isinstance(gf[0], dict) and "pos" in gf[0]:
                # Reuse existing inline senses and union NEW example indices
                # onto the first entry (classifier has no way to route them to
                # a specific sense without another API call — first entry is
                # the conservative default).
                existing_covered = set()
                for entry in gf:
                    existing_covered.update(
                        int(i) for i in (entry.get("examples") or [])
                        if isinstance(i, int)
                    )
                new_abs = [i for i in abs_idx_list if i not in existing_covered]
                if new_abs:
                    gf[0]["examples"] = sorted(
                        set(int(i) for i in (gf[0].get("examples") or []) if isinstance(i, int))
                        | set(new_abs)
                    )
                assignments_out[word] = {"gap-fill": gf}
                reused += 1
            else:
                need_gemini.append((word, lemma, examples, abs_idx_list))

        if reused:
            print("  Reused %d existing gap-fill senses" % reused)

        t_start = time.time()
        proposed = 0
        for batch_start in range(0, len(need_gemini), GAP_FILL_BATCH_SIZE):
            batch = need_gemini[batch_start:batch_start + GAP_FILL_BATCH_SIZE]
            batch_words = [tup[0] for tup in batch]
            print("  Gap-fill batch %d: %s" % (
                batch_start // GAP_FILL_BATCH_SIZE + 1, batch_words[:5]))
            batch_data = [{
                "word": word,
                "lemma": lemma,
                "senses": [],
                "examples": examples,
            } for word, lemma, examples, abs_idx_list in batch]
            results = gap_fill_batch_gemini(batch_data, api_key, gemini_model)
            result_map = {}
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and item.get("word"):
                        result_map[item["word"]] = item

            for word, lemma, examples, abs_idx_list in batch:
                result = result_map.get(word)
                if result and result.get("proposed_sense"):
                    pos = result.get("proposed_pos", "NOUN")
                    trans = result["proposed_sense"]
                    # Length / definitional sanity check. Flash Lite tends to
                    # write dictionary entries ("Term of endearment for a
                    # romantic partner, similar to 'boo' or 'baby'.") instead
                    # of flashcard glosses. Re-prompt with a tighter prompt
                    # showing concrete good vs bad examples.
                    if _is_definitional(trans):
                        repaired = _repair_proposed_sense(
                            word, lemma, examples, trans, api_key, gemini_model)
                        if repaired and repaired.get("proposed_sense"):
                            trans = repaired["proposed_sense"]
                            pos = repaired.get("proposed_pos", pos)
                            print("    repaired %r: %r → %r" % (
                                word, result["proposed_sense"][:40], trans))
                    sense_list = [{"pos": pos, "translation": trans,
                                   "source": "gap-fill"}]
                    id_map = assign_sense_ids(sense_list)
                    sid = list(id_map.keys())[0]
                    assignments_out[word] = {"gap-fill": [{
                        "sense": sid,
                        "pos": pos,
                        "translation": trans,
                        "lemma": result.get("proposed_lemma") or lemma,
                        "examples": list(abs_idx_list),
                    }]}
                    proposed += 1

        elapsed = time.time() - t_start
        print("  Proposed %d new senses (%.1fs)" % (proposed, elapsed))
    elif no_senses_queue:
        print("\nSkipping %d gap-fill words (--no-gemini)" % len(no_senses_queue))

    # ---------------------------------------------------------------------------
    # Write layer files (merge with existing)
    # ---------------------------------------------------------------------------
    if not custom_menu_mode:
        if is_artist:
            senses_path = artist_sense_menu_path(layers_dir, "wiktionary")
        else:
            senses_path = str(sense_menu_path(layers_dir, "wiktionary"))
        existing_senses = {}
        if os.path.isfile(senses_path):
            with open(senses_path, "r", encoding="utf-8") as f:
                existing_senses = normalize_artist_sense_menu(json.load(f))
        for word, analyses in senses_out.items():
            for analysis in analyses:
                merge_analysis(existing_senses, word, analysis.get("headword", analysis.get("lemma")), analysis.get("senses", {}))
        with open(senses_path, "w", encoding="utf-8") as f:
            json.dump(existing_senses, f, ensure_ascii=False, indent=2)
        print("\nWrote %s (%d entries, %d new)" % (senses_path, len(existing_senses), len(senses_out)))

    # Stamp example_ids onto every new assignment item before merging.
    # Idempotent — items already carrying example_ids are untouched.
    stamp_example_ids(assignments_out, examples_raw)

    # Stamp provenance (prompt_id + run timestamp) onto every item this run
    # produced, so the display resolver and card UI can trace which prompt/model
    # made each assignment. Idempotent — items already carrying prompt_id are
    # untouched. run_ts uses UTC ISO-8601 (sorts lexicographically for tie-breaks).
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    # Only API-authored claims carry a Gemini prompt id. Deterministic
    # spanishdict-auto/pos-auto decisions remain attributable to their method
    # and must not masquerade as model output.
    gemini_methods = {my_method, proposal_method} if use_gemini else set()
    if gemini_methods:
        stamp_provenance(assignments_out, args.prompt_id, run_ts,
                         methods=gemini_methods)

    # Merge assignments with existing file.
    #
    # Incremental mode (the default): new items for the SAME method are unioned
    # with existing items via merge_method_maps — same sense ID wins its old
    # example list merged with the new one; new sense IDs are appended. Other
    # methods on the same word are preserved untouched.
    #
    # --force replaces the current method's entries wholesale (and still leaves
    # other methods alone).
    existing_assigns = {}
    if os.path.isfile(assignments_path):
        existing_assigns = load_assignments(assignments_path)
    for word in auto_vetoed_words:
        word_data = existing_assigns.get(word)
        if isinstance(word_data, dict):
            word_data.pop(args.auto_method_name, None)
            if not word_data:
                existing_assigns.pop(word, None)
    stale_auto_wiped = 0
    for word, methods in assignments_out.items():
        if word not in existing_assigns or not isinstance(existing_assigns[word], dict):
            existing_assigns[word] = {}
        incoming = normalize_assignment_methods(methods, my_method)
        # Stale-auto cleanup: if the new write has any non-auto method
        # (priority > 0), drop any existing priority-0 auto entries. Those
        # blanket claims were valid only when the menu had a single sense;
        # a word now earning pos-auto / Gemini / gap-fill stamps is
        # multi-sense by construction and the old blanket would stealthily
        # outvote unassigned examples in the resolver.
        incoming_has_non_auto = any(
            METHOD_PRIORITY.get(m, 0) > 0 for m in incoming
        )
        if incoming_has_non_auto:
            for m in list(existing_assigns[word].keys()):
                if METHOD_PRIORITY.get(m, 0) == 0:
                    existing_assigns[word].pop(m, None)
                    stale_auto_wiped += 1
        if args.force:
            # Drop only the methods we're re-writing; keep others.
            for m in incoming.keys():
                existing_assigns[word].pop(m, None)
            existing_assigns[word].update(incoming)
        else:
            existing_assigns[word] = merge_method_maps(existing_assigns[word], incoming)
    if stale_auto_wiped:
        print("  Dropped %d stale priority-0 auto entries (menu now multi-sense)"
              % stale_auto_wiped)
    dump_assignments(existing_assigns, assignments_path)
    print("Wrote %s (%d entries, %d updated)" % (assignments_path, len(existing_assigns), len(assignments_out)))

    # Save translation cache updates
    if translation_cache and cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(translation_cache, f, ensure_ascii=False, indent=2)

    # Clean up checkpoint
    checkpoint_path = _checkpoint_path(
        layers_dir, args.assignments_file, args.prompt_id, gemini_model)
    if os.path.isfile(checkpoint_path):
        os.remove(checkpoint_path)

    if args.artist_dir:
        print("\nDone! Raw assignments are complete. Materialize them into "
              "card identities, then rebuild the live deck:")
        print('  .venv/bin/python3 pipeline/artist/step_7a_map_senses_to_lemmas.py '
              '--artist-dir "%s"' % args.artist_dir)
        print('  .venv/bin/python3 pipeline/artist/step_8b_assemble_artist_vocabulary.py '
              '--artist-dir "%s" --sense-source %s'
              % (args.artist_dir, args.menu_source_label))
    else:
        print("\nDone! Raw assignments are complete. Run "
              "step_7a_map_senses_to_lemmas.py before deck assembly.")


if __name__ == "__main__":
    main()
