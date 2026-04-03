#!/usr/bin/env python3
"""
Step 6: LLM-based vocabulary analysis using Gemini API.

Two-pass architecture:
  Pass A — Translate unique example sentences (batched, deduplicated)
  Pass B — Word analysis: lemma, POS, sense disambiguation, flags (no sentence translation)

Reads data/elision_merge/vocab_evidence_merged.json
Outputs BadBunnyvocabulary.json in the schema consumed by steps 8, 9, and the app.

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/scripts/6_llm_analyze.py" [--limit N] [--batch-size N]

API key is read from .env (GEMINI_API_KEY=...) or --api-key flag.

Saves progress after every batch so it can be interrupted and resumed.
"""

import json
import os
import sys
import time
import argparse
import re
import hashlib
from typing import Optional, Dict, List, Any, Tuple


def _load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.dirname(SCRIPT_DIR)  # scripts/ -> Bad Bunny/
PROJECT_ROOT = os.path.dirname(PIPELINE_DIR)
INPUT_PATH = os.path.join(PIPELINE_DIR, "data", "elision_merge", "vocab_evidence_merged.json")
OUTPUT_PATH = os.path.join(PIPELINE_DIR, "BadBunnyvocabulary.json")
WORD_PROGRESS_PATH = os.path.join(PIPELINE_DIR, "data", "llm_analysis", "llm_progress.json")
SENTENCE_PROGRESS_PATH = os.path.join(PIPELINE_DIR, "data", "llm_analysis", "sentence_translations.json")
DETECTED_PROPN_PATH = os.path.join(PIPELINE_DIR, "data", "proper_nouns", "detected_proper_nouns.json")
MWE_PATH = os.path.join(PIPELINE_DIR, "data", "word_counts", "mwe_detected.json")

# ---------------------------------------------------------------------------
# Curated overrides — loaded from JSON. Never delete entries.
# ---------------------------------------------------------------------------
def _load_pipeline_json(step, filename):
    path = os.path.join(PIPELINE_DIR, "data", step, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

CURATED_TRANSLATIONS = _load_pipeline_json("llm_analysis", "curated_translations.json")

PROPER_NOUNS = frozenset(_load_pipeline_json("llm_analysis", "proper_nouns.json"))
INTERJECTIONS = frozenset(_load_pipeline_json("llm_analysis", "interjections.json"))
EXTRA_ENGLISH = frozenset(_load_pipeline_json("llm_analysis", "extra_english.json"))

# ---------------------------------------------------------------------------
# Auto-detect interjection-like words from vocabulary
# ---------------------------------------------------------------------------
_INTERJECTION_PATTERNS = [
    re.compile(r'^[wb]r+[aeiou]*$'),     # brr, brra, wrrr
    re.compile(r'^pr+[aeiou]*$'),         # prr, prra, prru
    re.compile(r'^sk[r]*t+$'),            # skrt, skrrt
    re.compile(r'^[jh]a+[jh]?a*$'),      # ja, jaja, jajaja, ha, haha
    re.compile(r'^[jh]e+[jh]?e*$'),      # je, jeje, he, hehe
    re.compile(r'^[uoa]h+$'),            # uh, uhh, oh, ohh, ah, ahh
    re.compile(r'^[eaio]h[aeiou]?h?$'),  # eh, eha, ah
    re.compile(r'^sh+$'),                 # shh, shhh
    re.compile(r'^[mh]m+$'),             # mm, mmm, hm, hmm
    re.compile(r'^ya+h*$'),              # ya, yah, yaah
    re.compile(r'^ye+[ah]*$'),           # yeh, yeah, yeaah
    re.compile(r'^na+h*$'),              # na, nah, naah
    re.compile(r'^w[oua]+h*$'),          # woo, wooh, wuh, wuuh, wouh
    re.compile(r'^[dt]u+h+$'),           # duh, tuh
    re.compile(r'^bo+$'),                # boo, booo
    re.compile(r'^a+y+$'),              # ay, ayy, ayyy
    re.compile(r'^r+a+h?$'),            # rra, rrra, rah
]

# Words that match interjection patterns but are real Spanish vocabulary
_INTERJECTION_EXCEPTIONS = frozenset({
    "ya", "na", "je", "he", "oh", "ah", "ay", "eh",  # kept in _SHORT_WORD_WHITELIST
    "bora", "monta",  # real words
    "bro", "pre", "pri", "pro", "prue",  # English slang / Spanish prefixes
    "bo", "ye",  # short but potentially real
})


def detect_interjections(vocab_words):
    # type: (list) -> frozenset
    """Auto-detect interjection-like words from vocabulary list using regex patterns."""
    detected = set()
    for entry in vocab_words:
        w = entry["word"].lower().replace("'", "")
        if len(w) < 2 or len(w) > 15:
            continue
        if w in _INTERJECTION_EXCEPTIONS:
            continue
        # Single repeated character (aaa, eee, sss)
        if len(w) >= 3 and len(set(w)) == 1:
            detected.add(entry["word"].lower())
            continue
        # Triple+ repeated letter anywhere (jajajaja, lalalalala, rrrah)
        if re.search(r'(.)\1\1', w):
            detected.add(entry["word"].lower())
            continue
        # Pattern matching
        for pat in _INTERJECTION_PATTERNS:
            if pat.match(w):
                detected.add(entry["word"].lower())
                break
    return frozenset(detected)


# Short Spanish words that are real vocabulary (don't filter these)
_SHORT_WORD_WHITELIST = frozenset({
    "a", "al", "be", "da", "de", "di", "el", "en", "es", "fe",
    "ha", "he", "ir", "la", "le", "lo", "me", "mi", "ni", "no",
    "oh", "os", "re", "se", "si", "so", "su", "te", "ti", "tu",
    "un", "va", "ve", "vi", "ya", "yo",
    # Common Caribbean/slang 2-letter
    "ay", "eh", "ey", "pa", "na", "ta",
})

# ---------------------------------------------------------------------------
# POS sets for curated function words
# ---------------------------------------------------------------------------
_CURATED_DET = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "mi", "tu", "su", "mis", "tus", "sus",
    "nuestro", "nuestra", "nuestros", "nuestras",
    "este", "esta", "ese", "esa",
})
_CURATED_PRON = frozenset({
    "yo", "tú", "él", "ella", "nosotros", "nosotras", "ellos", "ellas",
    "usted", "ustedes", "me", "te", "se", "lo", "le", "nos", "les",
    "mí", "ti", "sí", "conmigo", "contigo", "esto", "eso",
    "qué", "quién", "cómo", "dónde", "cuándo", "vos",
})
_CURATED_ADP = frozenset({
    "a", "de", "en", "con", "por", "para", "sin", "sobre", "entre",
    "desde", "hasta", "hacia", "contra", "del", "al",
    "pa'", "pa", "pa'l",
})
_CURATED_CCONJ = frozenset({
    "y", "o", "pero", "ni", "que", "porque", "aunque", "como",
    "si", "cuando", "donde", "mientras",
})
_CURATED_ADV = frozenset({
    "no", "ya", "más", "muy", "bien", "mal", "hoy", "aquí", "ahora",
    "siempre", "nunca", "también", "después", "antes", "así",
    "tan", "tanto", "sí", "ahí", "arriba", "claro",
})


def _guess_pos_from_curated(word, translation):
    # type: (str, str) -> str
    if word in _CURATED_DET:
        return "DET"
    if word in _CURATED_PRON:
        return "PRON"
    if word in _CURATED_ADP:
        return "ADP"
    if word in _CURATED_CCONJ:
        return "CCONJ"
    if word in _CURATED_ADV:
        return "ADV"
    if translation.startswith("to "):
        return "VERB"
    return "X"


# ---------------------------------------------------------------------------
# Stable hex ID generation
# ---------------------------------------------------------------------------

def make_stable_id(word, lemma):
    # type: (str, str) -> str
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    return h[:4]


def assign_unique_ids(entries):
    # type: (List[Dict]) -> None
    used = set()  # type: set
    for entry in entries:
        base_id = make_stable_id(entry["word"], entry["lemma"])
        final_id = base_id
        suffix = 0
        while final_id in used:
            suffix += 1
            h = hashlib.md5(
                (entry["word"] + "|" + entry["lemma"] + "|" + str(suffix)).encode("utf-8")
            ).hexdigest()
            final_id = h[:4]
        used.add(final_id)
        entry["id"] = final_id


# ---------------------------------------------------------------------------
# Prompt hashing (cache invalidation on prompt changes)
# ---------------------------------------------------------------------------

def compute_prompt_hash(prompt_text):
    # type: (str) -> str
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Gemini API interaction
# ---------------------------------------------------------------------------

def call_gemini(prompt, api_key, model="gemini-2.5-flash", json_mode=True):
    # type: (str, str, str, bool) -> Optional[str]
    """Call Gemini API and return the response text."""
    from google import genai

    client = genai.Client(api_key=api_key)
    config = {
        "temperature": 0.1,
        "max_output_tokens": 8192,
    }
    if json_mode:
        config["response_mime_type"] = "application/json"

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return response.text
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            print("  [RATE LIMITED] Waiting 15s...", file=sys.stderr)
            time.sleep(15)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e2:
                print("  [ERROR] Gemini retry failed: %s" % e2, file=sys.stderr)
                return None
        print("  [ERROR] Gemini call failed: %s" % e, file=sys.stderr)
        return None


def strip_markdown_fences(text):
    # type: (str) -> str
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl >= 0:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


# ---------------------------------------------------------------------------
# Pass A: Sentence Translation
# ---------------------------------------------------------------------------

SENTENCE_PROMPT = (
    "Translate each numbered Caribbean Spanish lyric line to natural English.\n"
    "Caribbean dialect: ere'=eres, to'=todo, pa'=para, na'=nada, -a'o/-í'o = -ado/-ido.\n"
    "Return a JSON object mapping line numbers to translations: {\"1\":\"...\",\"2\":\"...\"}\n"
    "Keep translations natural and colloquial. Preserve the tone (street, romantic, etc.).\n\n"
)


def collect_unique_lines(all_words):
    # type: (List[Dict]) -> List[str]
    """Return deduplicated list of all example line texts."""
    seen = set()  # type: set
    lines = []
    for entry in all_words:
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return lines


def build_sentence_prompt(lines_batch):
    # type: (List[str]) -> str
    parts = [SENTENCE_PROMPT]
    for i, line in enumerate(lines_batch, 1):
        parts.append("%d.%s" % (i, line))
    return "\n".join(parts)


def parse_sentence_response(text, lines_batch):
    # type: (Optional[str], List[str]) -> Dict[str, str]
    """Parse {number: translation} JSON, return {line_text: english_translation}."""
    if not text:
        return {}

    text = strip_markdown_fences(text)

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {}

    json_str = text[start:end + 1]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        print("  [WARN] Sentence JSON parse failed: %s" % e, file=sys.stderr)
        return {}

    result = {}  # type: Dict[str, str]
    for k, v in raw.items():
        try:
            idx = int(k) - 1
            if 0 <= idx < len(lines_batch):
                result[lines_batch[idx]] = str(v)
        except (ValueError, TypeError):
            pass
    return result


# ---------------------------------------------------------------------------
# Pass B: Word Analysis
# ---------------------------------------------------------------------------

WORD_PROMPT = (
    'Spanish lyrics word analysis. Return compact JSON array.\n'
    'Per word: {"w":"word","e":false,"p":false,"i":false,"c":false,'
    '"s":[{"l":"lemma","t":"POS","tr":"english","n":[line#s]}]}\n'
    'w=lowercase. l=dictionary lemma (infinitive for verbs, masculine singular for adj/nouns).\n'
    'POS: NOUN VERB ADJ ADV PRON ADP CCONJ DET INTJ PROPN X\n'
    'e=English loanword (baby,shit,flow NOT Spanish words like no,me,solo). '
    'p=proper noun. i=interjection/sound. '
    'c=transparent cognate ONLY if Spanish word looks almost identical to the English word '
    '(e.g. música=music, hotel=hotel, animal=animal, profesión=profession). '
    'NOT cognate if spelling differs significantly, even if meanings are related '
    '(abrazo≠hug, amiga≠friend, dinero≠money are NOT cognates).\n'
    'Only split senses when the English translation genuinely differs (e.g. rico=rich vs rico=delicious). '
    'Do NOT split if same translation, even if POS differs.\n'
    'IMPORTANT: Assign ALL line numbers to a sense in n. Keep output compact.\n\n'
)


def build_word_prompt(words_batch):
    # type: (List[Dict]) -> str
    parts = [WORD_PROMPT]
    for entry in words_batch:
        word = entry["word"]
        examples = entry["examples"]
        lines = " | ".join(
            "%d.%s" % (i + 1, ex["line"])
            for i, ex in enumerate(examples[:6])
        )
        parts.append("%s: %s" % (word, lines))
    return "\n".join(parts)


def parse_word_response(text):
    # type: (Optional[str]) -> Optional[List[Dict]]
    """Parse compact JSON array from word analysis response."""
    if not text:
        return None

    text = strip_markdown_fences(text)

    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        return None

    json_str = text[start:end + 1]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        print("  [WARN] Word JSON parse failed: %s" % e, file=sys.stderr)
        print("  [WARN] Raw text: %s..." % json_str[:200], file=sys.stderr)
        return None

    results = []
    for item in raw:
        entry = {
            "word": item.get("w") or item.get("word", ""),
            "is_english": item.get("e") if "e" in item else item.get("is_english", False),
            "is_propernoun": item.get("p") if "p" in item else item.get("is_propernoun", False),
            "is_interjection": item.get("i") if "i" in item else item.get("is_interjection", False),
            "is_transparent_cognate": item.get("c") if "c" in item else item.get("is_transparent_cognate", False),
            "senses": [],
        }
        raw_senses = item.get("s") or item.get("senses", [])
        for s in raw_senses:
            entry["senses"].append({
                "lemma": s.get("l") or s.get("lemma", ""),
                "pos": s.get("t") or s.get("pos", "X"),
                "translation": s.get("tr") or s.get("translation", ""),
                "lines": s.get("n") or s.get("lines", []),
            })
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Build vocabulary entries
# ---------------------------------------------------------------------------

def build_entry_from_llm(word_input, llm_result, sentence_translations):
    # type: (Dict, Dict, Dict[str, str]) -> Dict
    word = word_input["word"]
    display_form = word_input.get("display_form")
    corpus_count = word_input.get("corpus_count", 0)
    examples = word_input.get("examples", [])

    senses = llm_result.get("senses", [])
    is_english = llm_result.get("is_english", False)
    is_propernoun = llm_result.get("is_propernoun", False)
    is_interjection = llm_result.get("is_interjection", False)
    is_transparent_cognate = llm_result.get("is_transparent_cognate", False)

    w_lower = word.lower()
    if w_lower in PROPER_NOUNS:
        is_propernoun = True
    if w_lower in INTERJECTIONS:
        is_interjection = True
    if w_lower in EXTRA_ENGLISH:
        is_english = True

    lemma = word
    if senses:
        lemma = senses[0].get("lemma", word)

    total_lines = sum(len(s.get("lines", [])) for s in senses)
    meanings = []

    assigned_indices = set()  # type: set
    for sense in senses:
        for line_num in sense.get("lines", []):
            try:
                assigned_indices.add(int(line_num) - 1)
            except (ValueError, TypeError):
                pass

    for sense_idx, sense in enumerate(senses):
        s_pos = sense.get("pos", "X")
        s_translation = sense.get("translation", "")
        s_lines = sense.get("lines", [])

        if w_lower in CURATED_TRANSLATIONS:
            s_translation = CURATED_TRANSLATIONS[w_lower]

        freq = "%.2f" % (len(s_lines) / total_lines) if total_lines > 0 else "1.00"

        meaning_examples = []
        for line_num in s_lines:
            try:
                idx = int(line_num) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(examples):
                ex = examples[idx]
                line_text = ex.get("line", "")
                meaning_examples.append({
                    "song": ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"],
                    "song_name": ex.get("title", ""),
                    "spanish": line_text,
                    "english": sentence_translations.get(line_text, ""),
                })

        if sense_idx == 0:
            seen_lines = set(me["spanish"] for me in meaning_examples)
            for ex_idx, ex in enumerate(examples):
                if ex_idx not in assigned_indices:
                    line_text = ex.get("line", "")
                    if line_text in seen_lines:
                        continue
                    seen_lines.add(line_text)
                    meaning_examples.append({
                        "song": ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"],
                        "song_name": ex.get("title", ""),
                        "spanish": line_text,
                        "english": sentence_translations.get(line_text, ""),
                    })

        if not meaning_examples and examples:
            ex = examples[0]
            line_text = ex.get("line", "")
            meaning_examples.append({
                "song": ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"],
                "song_name": ex.get("title", ""),
                "spanish": line_text,
                "english": sentence_translations.get(line_text, ""),
            })

        meanings.append({
            "pos": s_pos,
            "translation": s_translation,
            "frequency": freq,
            "examples": meaning_examples,
        })

    if not meanings:
        translation = CURATED_TRANSLATIONS.get(w_lower, "")
        fallback_examples = []
        if examples:
            ex = examples[0]
            line_text = ex.get("line", "")
            fallback_examples.append({
                "song": ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"],
                "song_name": ex.get("title", ""),
                "spanish": line_text,
                "english": sentence_translations.get(line_text, ""),
            })
        meanings.append({
            "pos": "X",
            "translation": translation,
            "frequency": "1.00",
            "examples": fallback_examples,
        })

    entry = {
        "id": "",
        "word": word,
        "lemma": lemma,
        "meanings": meanings,
        "most_frequent_lemma_instance": True,
        "is_english": is_english,
        "is_interjection": is_interjection,
        "is_propernoun": is_propernoun,
        "is_transparent_cognate": is_transparent_cognate,
        "corpus_count": corpus_count,
        "display_form": display_form,
    }
    return entry


def build_entry_from_overrides_only(word_input, sentence_translations):
    # type: (Dict, Dict[str, str]) -> Dict
    word = word_input["word"]
    w_lower = word.lower()
    display_form = word_input.get("display_form")
    corpus_count = word_input.get("corpus_count", 0)
    examples = word_input.get("examples", [])

    is_english = w_lower in EXTRA_ENGLISH
    is_propernoun = w_lower in PROPER_NOUNS
    is_interjection = w_lower in INTERJECTIONS

    translation = CURATED_TRANSLATIONS.get(w_lower, word if is_english else "")

    if is_propernoun:
        pos = "PROPN"
    elif is_interjection:
        pos = "INTJ"
    elif is_english:
        pos = "X"
    else:
        pos = _guess_pos_from_curated(w_lower, translation)

    meaning_examples = []
    for ex in examples:
        line_text = ex.get("line", "")
        meaning_examples.append({
            "song": ex["id"].split(":")[0] if ":" in ex["id"] else ex["id"],
            "song_name": ex.get("title", ""),
            "spanish": line_text,
            "english": sentence_translations.get(line_text, ""),
        })

    return {
        "id": "",
        "word": word,
        "lemma": word,
        "meanings": [{"pos": pos, "translation": translation, "frequency": "1.00",
                       "examples": meaning_examples}],
        "most_frequent_lemma_instance": True,
        "is_english": is_english,
        "is_interjection": is_interjection,
        "is_propernoun": is_propernoun,
        "is_transparent_cognate": False,
        "corpus_count": corpus_count,
        "display_form": display_form,
    }


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def mark_most_frequent_lemma(entries):
    # type: (List[Dict]) -> None
    lemma_groups = {}  # type: Dict[str, List[Dict]]
    for entry in entries:
        lemma = entry.get("lemma", entry["word"])
        if lemma not in lemma_groups:
            lemma_groups[lemma] = []
        lemma_groups[lemma].append(entry)

    for lemma, group in lemma_groups.items():
        for e in group:
            e["most_frequent_lemma_instance"] = False
        best = max(group, key=lambda e: e.get("corpus_count", 0))
        best["most_frequent_lemma_instance"] = True


# ---------------------------------------------------------------------------
# Progress (with prompt-hash cache invalidation)
# ---------------------------------------------------------------------------

def load_progress(path, expected_hash):
    # type: (str, str) -> Dict
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        stored_hash = data.pop("_prompt_hash", None)
        if stored_hash and stored_hash != expected_hash:
            print("  [WARN] Prompt changed since last run (stored=%s, current=%s)." %
                  (stored_hash, expected_hash))
            print("         Use --reset to reprocess, or cached results will be reused as-is.")
        return data
    return {}


def save_progress(path, data, phash):
    # type: (str, Dict, str) -> None
    out = {"_prompt_hash": phash}
    out.update(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# Batch processing helpers
# ---------------------------------------------------------------------------

def process_word_batch(batch, api_key, model, last_request_time, min_interval):
    # type: (List[Dict], str, str, float, float) -> Tuple[Optional[List[Dict]], float]
    """Send a word batch to Gemini. Returns (parsed_results, last_request_time)."""
    now = time.time()
    wait = min_interval - (now - last_request_time)
    if wait > 0:
        time.sleep(wait)

    prompt = build_word_prompt(batch)
    last_request_time = time.time()
    response_text = call_gemini(prompt, api_key, model=model)
    parsed = parse_word_response(response_text)
    return parsed, last_request_time


def process_sentence_batch(batch, api_key, model, last_request_time, min_interval):
    # type: (List[str], str, str, float, float) -> Tuple[Dict[str, str], float]
    """Send a sentence batch to Gemini. Returns (translations_dict, last_request_time)."""
    now = time.time()
    wait = min_interval - (now - last_request_time)
    if wait > 0:
        time.sleep(wait)

    prompt = build_sentence_prompt(batch)
    last_request_time = time.time()
    response_text = call_gemini(prompt, api_key, model=model)
    translations = parse_sentence_response(response_text, batch)
    return translations, last_request_time


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Step 4: Two-pass Gemini vocabulary analysis")
    parser.add_argument("--api-key", type=str, default=os.environ.get("GEMINI_API_KEY", ""),
                        help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only first N words (0 = all)")
    parser.add_argument("--batch-size", type=int, default=15,
                        help="Words per API request for word analysis (default: 15)")
    parser.add_argument("--sentence-batch-size", type=int, default=40,
                        help="Lines per API request for sentence translation (default: 40)")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash-lite",
                        help="Gemini model (default: gemini-2.5-flash-lite)")
    parser.add_argument("--reset", action="store_true",
                        help="Ignore all saved progress and start fresh")
    parser.add_argument("--reset-sentences", action="store_true",
                        help="Reset only sentence translation progress")
    parser.add_argument("--reset-words", action="store_true",
                        help="Reset only word analysis progress")
    parser.add_argument("--fill-gaps", action="store_true",
                        help="Re-query only words with empty senses in the cache")
    parser.add_argument("--rpm", type=int, default=200,
                        help="Max requests per minute (default: 200, paid tier allows 1000)")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: Provide --api-key or set GEMINI_API_KEY environment variable")
        sys.exit(1)

    # Load input
    print("Loading %s..." % INPUT_PATH)
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        all_words = json.load(f)
    print("  %d words loaded" % len(all_words))

    # Load auto-detected proper nouns from step 4 (if available)
    global PROPER_NOUNS
    if os.path.exists(DETECTED_PROPN_PATH):
        with open(DETECTED_PROPN_PATH, "r", encoding="utf-8") as f:
            detected = json.load(f)
        auto_propn = set(detected.get("proper_nouns", []))
        added = auto_propn - PROPER_NOUNS
        if added:
            PROPER_NOUNS = PROPER_NOUNS | frozenset(added)
            print("  Loaded %d auto-detected proper nouns from step 4" % len(added))

    # Auto-detect interjection-like words from vocabulary
    global INTERJECTIONS
    auto_intj = detect_interjections(all_words)
    new_intj = auto_intj - INTERJECTIONS
    if new_intj:
        INTERJECTIONS = INTERJECTIONS | new_intj
        print("  Auto-detected %d additional interjections (total: %d)" %
              (len(new_intj), len(INTERJECTIONS)))

    # Load MWE data (if available)
    mwe_index = {}  # type: Dict[str, List[Dict]]
    if os.path.exists(MWE_PATH):
        with open(MWE_PATH, "r", encoding="utf-8") as f:
            mwe_data = json.load(f)
        for mwe in mwe_data.get("mwes", []):
            expr = mwe["expression"]
            translation = mwe["translation"] or ""
            for token in expr.split():
                token_lower = token.lower()
                if token_lower not in mwe_index:
                    mwe_index[token_lower] = []
                # Avoid duplicate entries for the same expression
                if not any(m["expression"] == expr for m in mwe_index[token_lower]):
                    mwe_index[token_lower].append({
                        "expression": expr,
                        "translation": translation,
                    })
        print("  Loaded %d MWEs, indexing %d words" %
              (len(mwe_data.get("mwes", [])), len(mwe_index)))

    if args.limit > 0:
        all_words = all_words[:args.limit]
        print("  Limited to first %d words" % args.limit)

    min_interval = 60.0 / args.rpm
    last_request_time = 0.0

    # ===================================================================
    # Pass A: Sentence Translation
    # ===================================================================
    print("\n=== Pass A: Sentence Translation ===")

    all_lines = collect_unique_lines(all_words)
    print("  %d unique lines across %d words" % (len(all_lines), len(all_words)))

    sentence_hash = compute_prompt_hash(SENTENCE_PROMPT)
    if args.reset or args.reset_sentences:
        sentence_progress = {}  # type: Dict[str, str]
        print("  Starting fresh (--reset)")
    else:
        raw_sp = load_progress(SENTENCE_PROGRESS_PATH, sentence_hash)
        sentence_progress = {}
        for k, v in raw_sp.items():
            if isinstance(v, str):
                sentence_progress[k] = v
        print("  Loaded sentence cache: %d translations" % len(sentence_progress))

    untranslated = [l for l in all_lines if l not in sentence_progress]
    print("  %d lines need translation" % len(untranslated))

    if untranslated:
        s_batch_size = args.sentence_batch_size
        total_s_batches = (len(untranslated) + s_batch_size - 1) // s_batch_size
        est_minutes = total_s_batches / args.rpm
        print("  Estimated: %d requests, ~%.0f minutes at %d RPM" %
              (total_s_batches, est_minutes, args.rpm))

        start_time = time.time()
        for batch_idx in range(0, len(untranslated), s_batch_size):
            batch = untranslated[batch_idx:batch_idx + s_batch_size]
            batch_num = batch_idx // s_batch_size + 1

            preview = batch[0][:50]
            print("[S %d/%d] %d lines (%s...)" % (batch_num, total_s_batches, len(batch), preview))

            translations, last_request_time = process_sentence_batch(
                batch, args.api_key, args.model, last_request_time, min_interval
            )

            if translations:
                sentence_progress.update(translations)
                translated_count = len(translations)
            else:
                translated_count = 0
                mid = len(batch) // 2
                halves = [batch[:mid], batch[mid:]] if mid > 0 else [batch]
                for half_idx, half in enumerate(halves):
                    if not half:
                        continue
                    print("  [RETRY half %d] %d lines" % (half_idx + 1, len(half)))
                    retry_trans, last_request_time = process_sentence_batch(
                        half, args.api_key, args.model, last_request_time, min_interval
                    )
                    if retry_trans:
                        sentence_progress.update(retry_trans)
                        translated_count += len(retry_trans)
                    else:
                        print("  [FAIL] Half %d failed, marking as empty" % (half_idx + 1))

            for line in batch:
                if line not in sentence_progress:
                    sentence_progress[line] = ""

            save_progress(SENTENCE_PROGRESS_PATH, sentence_progress, sentence_hash)

            if translated_count < len(batch):
                print("  [WARN] %d/%d lines translated" % (translated_count, len(batch)))

        elapsed = time.time() - start_time
        print("  Sentence pass done: %.1f minutes" % (elapsed / 60))

    filled = sum(1 for v in sentence_progress.values() if v)
    print("  Sentence cache: %d filled, %d empty" % (filled, len(sentence_progress) - filled))

    # ===================================================================
    # Pass B: Word Analysis
    # ===================================================================
    print("\n=== Pass B: Word Analysis ===")

    word_hash = compute_prompt_hash(WORD_PROMPT)
    if args.reset or args.reset_words:
        word_progress = {}  # type: Dict[str, Dict]
        print("  Starting fresh (--reset)")
    else:
        word_progress = load_progress(WORD_PROGRESS_PATH, word_hash)
        print("  Loaded word cache: %d words" % len(word_progress))

    words_for_llm = []
    override_count = 0
    zero_example_count = 0
    short_junk_count = 0
    gap_count = 0

    for entry in all_words:
        w = entry["word"]
        w_lower = w.lower()
        if (w_lower in PROPER_NOUNS or w_lower in INTERJECTIONS
                or w_lower in EXTRA_ENGLISH or w_lower in CURATED_TRANSLATIONS):
            override_count += 1
        elif not entry.get("examples"):
            zero_example_count += 1
        elif len(w_lower) <= 2 and w_lower not in _SHORT_WORD_WHITELIST:
            short_junk_count += 1
        elif w not in word_progress:
            words_for_llm.append(entry)
        elif args.fill_gaps and not word_progress[w].get("senses"):
            # Re-query words that previously got empty senses
            gap_count += 1
            del word_progress[w]
            words_for_llm.append(entry)

    print("  %d words handled by overrides" % override_count)
    print("  %d words skipped (zero examples)" % zero_example_count)
    print("  %d words skipped (short junk)" % short_junk_count)
    print("  %d words already in word cache" % len(word_progress))
    if args.fill_gaps:
        print("  %d words re-queued (empty senses)" % gap_count)
    print("  %d words need Gemini analysis" % len(words_for_llm))

    if words_for_llm:
        w_batch_size = args.batch_size
        total_w_batches = (len(words_for_llm) + w_batch_size - 1) // w_batch_size
        est_minutes = total_w_batches / args.rpm
        print("  Estimated: %d requests, ~%.0f minutes at %d RPM" %
              (total_w_batches, est_minutes, args.rpm))

        start_time = time.time()
        processed_this_run = 0
        failed_words = []

        for batch_idx in range(0, len(words_for_llm), w_batch_size):
            batch = words_for_llm[batch_idx:batch_idx + w_batch_size]
            batch_num = batch_idx // w_batch_size + 1

            elapsed = time.time() - start_time
            rate = processed_this_run / elapsed if elapsed > 0 and processed_this_run > 0 else 0
            remaining = len(words_for_llm) - batch_idx - len(batch)
            eta_min = remaining / (rate * 60) if rate > 0 else 0

            words_str = ", ".join(e["word"] for e in batch[:5])
            if len(batch) > 5:
                words_str += ", ... (+%d)" % (len(batch) - 5)
            print("[W %d/%d] %s  (%.1f w/s, ETA: %.0f min)" %
                  (batch_num, total_w_batches, words_str, rate, eta_min))

            parsed, last_request_time = process_word_batch(
                batch, args.api_key, args.model, last_request_time, min_interval
            )

            if parsed is None:
                mid = len(batch) // 2
                halves = [batch[:mid], batch[mid:]] if mid > 0 else [batch]
                for half_idx, half in enumerate(halves):
                    if not half:
                        continue
                    half_words = ", ".join(e["word"] for e in half[:4])
                    print("  [RETRY half %d] %s" % (half_idx + 1, half_words))

                    retry_parsed, last_request_time = process_word_batch(
                        half, args.api_key, args.model, last_request_time, min_interval
                    )

                    if retry_parsed:
                        retry_by_word = {}  # type: Dict[str, Dict]
                        for r in retry_parsed:
                            rw = r.get("word", "")
                            retry_by_word[rw] = r
                            retry_by_word[rw.lower()] = r
                        for entry in half:
                            w = entry["word"]
                            result = retry_by_word.get(w) or retry_by_word.get(w.lower())
                            if result:
                                word_progress[w] = result
                            else:
                                print("  [MISS] %s" % w)
                                failed_words.append(w)
                                word_progress[w] = {
                                    "word": w, "is_english": False, "is_propernoun": False,
                                    "is_interjection": False, "senses": [],
                                }
                            processed_this_run += 1
                    else:
                        print("  [FAIL] Half %d failed, skipping" % (half_idx + 1))
                        for entry in half:
                            failed_words.append(entry["word"])
                            word_progress[entry["word"]] = {
                                "word": entry["word"], "is_english": False,
                                "is_propernoun": False, "is_interjection": False,
                                "senses": [],
                            }
                            processed_this_run += 1
            else:
                result_by_word = {}  # type: Dict[str, Dict]
                for r in parsed:
                    rw = r.get("word", "")
                    result_by_word[rw] = r
                    result_by_word[rw.lower()] = r

                for entry in batch:
                    w = entry["word"]
                    result = result_by_word.get(w) or result_by_word.get(w.lower())
                    if result:
                        word_progress[w] = result
                    else:
                        print("  [MISS] %s — not in batch response" % w)
                        failed_words.append(w)
                        word_progress[w] = {
                            "word": w, "is_english": False, "is_propernoun": False,
                            "is_interjection": False, "senses": [],
                        }
                    processed_this_run += 1

            save_progress(WORD_PROGRESS_PATH, word_progress, word_hash)

        elapsed = time.time() - start_time
        print("  Word pass done: %.1f minutes, %d processed, %d failed" %
              (elapsed / 60, processed_this_run, len(failed_words)))
        if failed_words:
            print("  Failed: %s" % ", ".join(failed_words[:20]))

    # ===================================================================
    # Assemble final output
    # ===================================================================
    print("\n=== Assembling final vocabulary ===")
    final_entries = []

    for entry in all_words:
        w = entry["word"]
        w_lower = w.lower()

        is_short_junk = len(w_lower) <= 2 and w_lower not in _SHORT_WORD_WHITELIST
        if (w_lower in PROPER_NOUNS or w_lower in INTERJECTIONS
                or w_lower in EXTRA_ENGLISH or w_lower in CURATED_TRANSLATIONS
                or is_short_junk):
            final_entries.append(build_entry_from_overrides_only(entry, sentence_progress))
        elif w in word_progress:
            final_entries.append(build_entry_from_llm(entry, word_progress[w], sentence_progress))
        else:
            final_entries.append(build_entry_from_overrides_only(entry, sentence_progress))

    # Annotate MWE memberships
    if mwe_index:
        mwe_count = 0
        for fe in final_entries:
            w_lower = fe["word"].lower()
            if w_lower in mwe_index:
                fe["mwe_memberships"] = mwe_index[w_lower]
                mwe_count += 1
        print("  %d entries annotated with MWE memberships" % mwe_count)

    mark_most_frequent_lemma(final_entries)
    assign_unique_ids(final_entries)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_entries, f, ensure_ascii=False, indent=2)

    print("\nDone! Wrote %d entries to %s" % (len(final_entries), OUTPUT_PATH))


if __name__ == "__main__":
    main()
