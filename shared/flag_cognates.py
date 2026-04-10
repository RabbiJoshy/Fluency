"""
Shared cognate detection logic used by both artist and normal-mode pipelines.

Scores Spanish-English cognate similarity (0.0–1.0) via:
1. Suffix transformation rules → 1.0 (ción→tion, dad→ty, amente→ly, ar→ate, etc.)
2. String similarity via SequenceMatcher
3. Phonetic normalization — English digraphs (ph→f, th→t, qu→cu, y→i)
   and Spanish prosthetic-e stripping (especial→special) before comparison

Scores are stored in the cognates.json layer. The front-end filters at a
user-chosen threshold, so there is no hardcoded pass/fail cutoff here.

Two modes:
- Suffix-only: for normal mode (no LLM data available)
- Intersection: for artist mode (both LLM flag and suffix rules must agree)
"""

import difflib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

# Minimum score to store in the cognates layer.  Below this, words look too
# different to be useful cognates at any reasonable front-end threshold.
_MIN_SCORE_FLOOR = 0.5

# ---------------- helpers ----------------

def normalize(s):
    # type: (str) -> str
    """Lowercase + strip accents."""
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def strip_plural(w):
    # type: (str) -> str
    """Remove common plural suffixes (Spanish & English)."""
    # Spanish -ces → -z  (voces→voz, veces→vez)
    if len(w) >= 4 and w.endswith("ces"):
        return w[:-3] + "z"
    if len(w) >= 5 and w.endswith("es"):
        return w[:-2]
    if len(w) >= 4 and w.endswith("s"):
        return w[:-1]
    return w


_VOWELS = set("aeiou")


def _is_consonant(c):
    return c.isalpha() and c not in _VOWELS


def _phonetic_normalize_en(w):
    # type: (str) -> str
    """Normalize English digraphs to Spanish-like equivalents.

    ph→f, th→t, qu→cu, y→i (when y acts as a vowel between consonants).
    """
    w = w.replace("ph", "f")
    w = w.replace("th", "t")
    w = w.replace("qu", "cu")
    # y→i only between consonants (vowel-y, not consonant-y like "yes")
    out = list(w)
    for i, c in enumerate(out):
        if c != "y":
            continue
        before = _is_consonant(out[i - 1]) if i > 0 else True
        after = _is_consonant(out[i + 1]) if i + 1 < len(out) else True
        if before and after:
            out[i] = "i"
    return "".join(out)


def _strip_prosthetic_e(w):
    # type: (str) -> str
    """Strip Spanish prosthetic e- before s+consonant clusters.

    Spanish adds e- before s+consonant (especial→special, escuadrón→scuadrón,
    estructura→structura). Returns the stripped form if the pattern matches.
    """
    if len(w) >= 4 and w[0] == "e" and w[1] == "s" and _is_consonant(w[2]):
        return w[1:]
    return w


def apply_suffix(w, src, dst):
    # type: (str, str, str) -> Optional[str]
    if w.endswith(src) and len(w) > len(src):
        return w[:-len(src)] + dst
    return None


# Suffix mapping: (spanish_suffix, english_suffix)
# Order matters — more specific suffixes first to avoid partial matches
SUFFIX_RULES = [
    # -ción / -sión → -tion / -sion
    ("cion", "tion"),
    ("sion", "sion"),
    # -ancia / -encia → -ance / -ence
    ("ancia", "ance"),
    ("encia", "ence"),
    # -amente → -ly  (Spanish -mente attaches to feminine: honesta+mente → honestly)
    ("amente", "ly"),
    # -mente → -ly
    ("mente", "ly"),
    # -ismo → -ism
    ("ismo", "ism"),
    # -ista → -ist
    ("ista", "ist"),
    # -ivo / -iva → -ive
    ("ivo", "ive"),
    ("iva", "ive"),
    # -oso / -osa → -ous
    ("oso", "ous"),
    ("osa", "ous"),
    # -ico / -ica → -ic
    ("ico", "ic"),
    ("ica", "ic"),
    # -dad → -ty  (universidad→university, realidad→reality)
    ("idad", "ity"),
    ("dad", "ty"),
    # -ente / -ante → -ent / -ant
    ("ente", "ent"),
    ("ante", "ant"),
    # -ia / -ía → -y  (democracia→democracy, energía→energy)
    ("ia", "y"),
    # -ario / -aria → -ary
    ("ario", "ary"),
    ("aria", "ary"),
    # -izar → -ize  (organizar→organize, utilizar→utilize)
    ("izar", "ize"),
    # -ificar → -ify  (clarificar→clarify, modificar→modify)
    ("ificar", "ify"),
    # -ado / -ada → -ated  (activado→activated, complicada→complicated)
    ("ado", "ated"),
    ("ada", "ated"),
    # -ado / -ada → -ed  (preparado→prepared, armada→armed)
    ("ado", "ed"),
    ("ada", "ed"),
    # -ar → -ate  (celebrar→celebrate, separar→separate)
    ("ar", "ate"),
    # -mento → -ment  (argumento→argument, momento→moment)
    ("mento", "ment"),
    # -ura → -ure  (cultura→culture, estructura→structure)
    ("ura", "ure"),
    # -cto → -ct  (correcto→correct, distinto→distinct)
    ("cto", "ct"),
    # -ido → -id  (rápido→rapid, líquido→liquid)
    ("ido", "id"),
    # -il → -ile  (ágil→agile, frágil→fragile)
    ("il", "ile"),
    # -or → -or  (exact, but catches actor, color, etc.)
    ("or", "or"),
    # -al → -al  (usually exact after plural strip, but just in case)
    ("al", "al"),
    # -ble → -ble  (usually exact)
    ("ble", "ble"),
]


def split_english_glosses(translation):
    # type: (str) -> list
    """
    Extract candidate English words/phrases from a translation string.
    Returns both individual tokens AND multi-word phrases.
    e.g. "ice cream / gelato" → ["ice cream", "gelato", "ice", "cream"]
    """
    if not translation:
        return []

    t = translation.lower()
    # Strip parenthetical notes like "(informal)"
    t = re.sub(r"\([^)]*\)", "", t)
    # Split on / and , as gloss separators
    parts = [p.strip() for p in re.split(r"[/,]", t) if p.strip()]

    out = []
    for p in parts:
        # Add the full phrase first (for multi-word cognates)
        clean = " ".join(tok for tok in p.split() if tok.isalpha())
        if clean:
            out.append(clean)
        # Then add individual tokens
        for tok in p.split():
            if tok.isalpha() and tok not in out:
                out.append(tok)
    return out


def cognate_score(spanish, english):
    # type: (str, str) -> float
    """Return cognate similarity score (0.0–1.0) for a Spanish/English pair.

    1.0 = exact match or suffix rule match.
    <1.0 = best SequenceMatcher ratio (raw or phonetically normalized).
    0.0 = too short or no meaningful similarity.
    """
    s = normalize(spanish)
    e = normalize(english)

    if len(s) < 4 or len(e) < 4:
        return 0.0

    s0 = strip_plural(s)
    e0 = strip_plural(e)

    # exact / plural match
    if s0 == e0:
        return 1.0

    # Try all suffix rules (exact stem transform).
    # Check against both e (original) and e0 (de-pluraled) because strip_plural
    # can incorrectly strip a terminal 's' that's part of the word itself
    # (e.g. "famous" → "famou"), so we need to also compare against the
    # pre-strip form to catch cases like famoso → famous.
    for es_suffix, en_suffix in SUFFIX_RULES:
        result = apply_suffix(s0, es_suffix, en_suffix)
        if result is not None and (result == e0 or result == e):
            return 1.0

    # Also try with prosthetic-e stripped from Spanish (especial→special)
    s1 = _strip_prosthetic_e(s0)

    # Suffix rules again with prosthetic-e stripped form
    if s1 != s0:
        if s1 == e0:
            return 1.0
        for es_suffix, en_suffix in SUFFIX_RULES:
            result = apply_suffix(s1, es_suffix, en_suffix)
            if result is not None and (result == e0 or result == e):
                return 1.0

    # Similarity: best of raw and phonetically-normalized ratios.
    best = difflib.SequenceMatcher(None, s0, e0).ratio()

    # Phonetic normalization: English digraphs (ph, th, qu, y-as-vowel) break
    # SequenceMatcher alignment.  Length guard: only for 6+ char words to
    # avoid short-word false positives (e.g. meta/meth, pato/path).
    if len(s0) >= 6 and len(e0) >= 6:
        e_phon = _phonetic_normalize_en(e0)
        # Try all combos: raw-sp × phon-en, stripped-sp × raw-en, stripped-sp × phon-en
        if e_phon != e0:
            best = max(best, difflib.SequenceMatcher(None, s0, e_phon).ratio())
        if s1 != s0:
            best = max(best, difflib.SequenceMatcher(None, s1, e0).ratio())
            if e_phon != e0:
                best = max(best, difflib.SequenceMatcher(None, s1, e_phon).ratio())

    return round(best, 3)


def is_transparent_cognate(spanish, english):
    # type: (str, str) -> bool
    """Legacy bool wrapper — True when score >= 0.83."""
    return cognate_score(spanish, english) >= 0.83


# ---------------- entry-level detection ----------------

def best_cognate_score(entry):
    """Return the best cognate score across all word/lemma × translation pairs.

    Entry must have 'word', optionally 'lemma', and 'meanings' list
    where each meaning has a 'translation' field.
    """
    candidates = set()
    word = entry.get("word", "")
    lemma = entry.get("lemma", "")
    if word:
        candidates.add(word)
    if lemma and lemma != word:
        candidates.add(lemma)

    if not candidates:
        return 0.0

    best = 0.0
    for meaning in entry.get("meanings", []):
        translation = meaning.get("translation", "")
        for eng in split_english_glosses(translation):
            for sp in candidates:
                score = cognate_score(sp, eng)
                if score == 1.0:
                    return 1.0
                best = max(best, score)
    return best


def suffix_rule_says_cognate(entry):
    """Legacy bool wrapper — True when best score >= 0.83."""
    return best_cognate_score(entry) >= 0.83


# ---------------- CogNet loading ----------------

def _load_cognet():
    """Load CogNet Spanish→English lookup from shared/cognet_spa_eng.json.

    Returns a dict mapping normalized Spanish word → set of normalized English cognates.
    Returns empty dict if file not found.
    """
    cognet_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cognet_spa_eng.json")
    if not os.path.isfile(cognet_path):
        return {}
    with open(cognet_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # Values are lists; convert to sets for fast lookup
    return {k: set(v) for k, v in raw.items()}


def _cognet_match(word, lemma, translations, cognet):
    """Check if CogNet confirms a cognate relationship for this word.

    Returns True if the word or lemma appears in CogNet AND at least one
    CogNet English cognate matches one of the entry's translations.
    """
    if not cognet:
        return False
    w_norm = normalize(word)
    l_norm = normalize(lemma)
    for sp in (w_norm, l_norm):
        if sp not in cognet:
            continue
        cognet_engs = cognet[sp]
        for t in translations:
            if t in cognet_engs:
                return True
            for tok in t.split():
                if tok in cognet_engs:
                    return True
    return False


# ---------------- layer writer ----------------

def detect_cognates(senses_data, output_path, master_path=None):
    """Detect cognates and write cognates.json with per-voter signals.

    Each entry: {"score": float, "cognet"?: true, "gemini"?: true}.
    Included if any voter fires (score >= floor, CogNet match, or Gemini flag).

    Used by both normal and artist pipelines — one shared cognates.json.

    Args:
        senses_data: dict keyed by "word|lemma" with list of sense dicts
        output_path: where to write the cognates.json layer
        master_path: optional path to vocabulary_master.json for Gemini voter
    """
    cognet = _load_cognet()

    # Load master for Gemini LLM flags (if available)
    wl_to_master = {}
    if master_path is None:
        # Auto-detect: Artists/vocabulary_master.json relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate = os.path.join(project_root, "Artists", "vocabulary_master.json")
        if os.path.isfile(candidate):
            master_path = candidate
    if master_path and os.path.isfile(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            master = json.load(f)
        for mid, m in master.items():
            wl_to_master["%s|%s" % (m["word"], m["lemma"])] = m
        print("  Master loaded: %d entries (for Gemini voter)" % len(master))

    cognate_layer = {}

    for key, sense_list in senses_data.items():
        word, lemma = key.split("|", 1) if "|" in key else (key, key)
        entry = {
            "word": word,
            "lemma": lemma,
            "meanings": [{"translation": s.get("translation", "")} for s in sense_list],
        }
        score = best_cognate_score(entry)

        translations = set()
        for s in sense_list:
            for eng in split_english_glosses(s.get("translation", "")):
                translations.add(eng)
        has_cognet = _cognet_match(word, lemma, translations, cognet)

        # Gemini LLM flag from master
        m = wl_to_master.get(key)
        gemini_flag = m.get("is_transparent_cognate", False) if m else False

        if score >= _MIN_SCORE_FLOOR or has_cognet or gemini_flag:
            obj = {"score": score}
            if has_cognet:
                obj["cognet"] = True
            if gemini_flag:
                obj["gemini"] = True
            cognate_layer[key] = obj

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cognate_layer, f, ensure_ascii=False)

    scored = sum(1 for v in cognate_layer.values() if v["score"] >= _MIN_SCORE_FLOOR)
    with_cognet = sum(1 for v in cognate_layer.values() if v.get("cognet"))
    with_gemini = sum(1 for v in cognate_layer.values() if v.get("gemini"))
    print("  %d entries (%d scored >= %.2f, %d CogNet, %d Gemini)"
          % (len(cognate_layer), scored, _MIN_SCORE_FLOOR, with_cognet, with_gemini))
    print("  -> %s" % output_path)
    return cognate_layer
