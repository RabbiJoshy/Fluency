#!/usr/bin/env python3
"""
Phase 3: Dictionary-based translations using Wiktionary glosses.

Replaces steps 5 + 6 (cache-based translation + Google Translate gap-filling).
Uses Wiktionary sense glosses matched on (lemma, POS) for context-aware
translations that don't suffer from bare-word ambiguity.

Input : Bad Bunny/intermediates/4_wiktionary_output.json
Output: Bad Bunny/intermediates/phase3_vocabulary.json
Also:   Bad Bunny/intermediates/phase3_diff_report.json

Requires:
  Wiktionary dump at /tmp/kaikki_spanish.jsonl.gz
"""

import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
IN_PATH = SCRIPT_DIR / "intermediates" / "4_wiktionary_output.json"
OUT_PATH = SCRIPT_DIR / "intermediates" / "phase3_vocabulary.json"
DIFF_PATH = SCRIPT_DIR / "intermediates" / "phase3_diff_report.json"
OLD_VOCAB_PATH = SCRIPT_DIR / "BadBunnyvocabulary.json"
WIKT_DUMP = Path("/tmp/kaikki_spanish.jsonl.gz")

# ── Curated translations for high-frequency function words ───────────────────
# These are words where Wiktionary glosses are too verbose, wrong POS-matched,
# or missing. Flashcard translations should be short and practical.
CURATED_TRANSLATIONS = {
    # Articles / determiners
    "el": "the", "la": "the", "los": "the", "las": "the",
    "un": "a, an", "una": "a, an", "unos": "some", "unas": "some",
    # Possessives
    "mi": "my", "tu": "your", "su": "his/her/their",
    "mis": "my", "tus": "your", "sus": "his/her/their",
    "nuestro": "our", "nuestra": "our", "nuestros": "our", "nuestras": "our",
    # Personal pronouns
    "yo": "I", "tú": "you", "él": "he", "ella": "she",
    "nosotros": "we", "nosotras": "we", "ellos": "they", "ellas": "they",
    "usted": "you (formal)", "ustedes": "you all",
    # Object / reflexive pronouns
    "me": "me", "te": "you", "se": "oneself/himself/herself",
    "lo": "it/him", "la": "her/it", "le": "him/her (indirect)",
    "nos": "us", "les": "them (indirect)", "los": "them",
    # Prepositional pronouns
    "mí": "me", "ti": "you", "sí": "oneself/himself",
    "conmigo": "with me", "contigo": "with you",
    # Prepositions
    "a": "to, at", "de": "of, from", "en": "in, at, on",
    "con": "with", "por": "for, by", "para": "for, to",
    "sin": "without", "sobre": "on, about", "entre": "between",
    "desde": "from, since", "hasta": "until, up to",
    "hacia": "toward", "contra": "against",
    # Contractions
    "del": "of the", "al": "to the",
    # Conjunctions
    "y": "and", "o": "or", "pero": "but", "ni": "nor, not even",
    "que": "that, which", "porque": "because",
    "aunque": "although", "como": "as, like",
    "si": "if", "cuando": "when", "donde": "where",
    "mientras": "while",
    # Adverbs
    "no": "no, not", "ya": "already, now", "más": "more",
    "muy": "very", "bien": "well", "mal": "badly",
    "hoy": "today", "aquí": "here", "ahora": "now",
    "siempre": "always", "nunca": "never",
    "también": "also", "después": "after, later",
    "antes": "before", "así": "like this, so",
    "tan": "so, such", "tanto": "so much",
    # Demonstratives
    "este": "this", "esta": "this", "ese": "that", "esa": "that",
    "esto": "this", "eso": "that",
    # Interrogatives
    "qué": "what", "quién": "who", "cómo": "how",
    "dónde": "where", "cuándo": "when",
    # Caribbean elisions
    "pa'": "for, to", "na'": "nothing", "to'": "all, every",
    "pa": "for, to", "na": "nothing",
    "toy": "I am", "tá": "is",
    "vo'a": "I'm going to", "pa'l": "to the",
    # Other high-frequency
    "hay": "there is/are", "sé": "I know",
    "mucho": "a lot, much", "poco": "little, few",
    "sí": "yes",
    # Common words where Wiktionary's first sense is misleading
    "hacer": "to do, to make",
    "querer": "to want, to love",
    "gustar": "to like, to please",
    "gusta": "to like, to please",
    "cabrón": "bastard, badass",
    "cabrones": "bastards, badasses",
    "arriba": "up, above",
    "panas": "friends, buddies",
    "claro": "of course, clear",
    "dale": "go ahead, do it",
    "duro": "hard, tough",
    "mami": "baby, babe",
    "papi": "daddy, babe",
    "loco": "crazy",
    "loca": "crazy",
    "bellaco": "horny, turned on",
    "bellaca": "horny, turned on",
    "perreo": "reggaeton dancing",
    "perrear": "to dance reggaeton",
    "janguear": "to hang out",
    "jangueo": "hanging out, partying",
    "bicho": "thing, dude",
    "bichote": "big shot, boss",
    "gata": "girl, babe",
    "gato": "cat, dude",
    "pana": "friend, buddy",
    # Caribbean elisions not in step 3 mapping
    "cuida'o": "careful, taken care of", "olvida'o": "forgotten",
    "burla'o": "mocked", "pasa'o": "past, happened",
    "arrebata'o": "hyped up, wild", "llega'o": "arrived",
    "calla'o": "quiet", "enamora'o": "in love",
    "exagera'o": "exaggerated", "pela'o": "broke, bald",
    "demasia'o": "too much", "esta'o": "state, been",
    "jodí'o": "screwed", "para'o": "standing, stopped",
    "la'o": "side", "verda'": "truth", "verdá'": "truth",
    "de'o": "finger", "lu'": "light", "to'l": "all the",
    "usté'": "you (formal)", "pa'cá": "over here",
    "pa'llá": "over there", "pa'rriba": "upward",
    "pa'trás": "backwards",
    # More reggaeton slang
    "bellaqueo": "reggaeton grinding", "bellacoso": "lustful, horny",
    "demonia": "she-devil", "jevo": "boyfriend, partner",
    "frontear": "to show off, to flex", "caile": "come hang out",
    "feka": "fake", "chamaquita": "young girl",
    "bellaquita": "flirty girl", "manín": "buddy, pal",
    "totito": "completely, totally",
    "neverita": "cooler, ice chest",
    # More Caribbean elisions and slang
    "tamos": "we are", "vamo": "let's go",
    "ójala": "hopefully, God willing", "ojalá": "hopefully, God willing",
    "acho": "wow, damn (PR exclamation)",
    "rolié": "Rolex (slang)", "tera": "tons of, a lot",
    "demaga": "too much (PR slang)", "tán": "they are",
    "juquear": "to hook up", "juquea'o": "hooked up",
    "callaíta": "quiet (feminine, PR)", "callaítas": "quiet (fem. pl., PR)",
    "mojaítas": "wet (fem. pl., PR)", "mojaíto": "wet (PR)",
    "solita": "alone (diminutive)", "solito": "alone (diminutive)",
    "solitos": "alone (dim. plural)", "loquita": "a little crazy",
    "ojitos": "little eyes", "ojito": "little eye",
    "mamita": "baby, babe",
    "saramambiche": "damn (PR expletive)",
    "cuida'o": "careful, taken care of",
    "verda'": "truth", "verdá'": "truth",
    "la'o": "side", "lao'": "side",
    "ma'i": "mommy (PR)",
    "yao'": "ready, let's go (PR)",
    "rd": "Dominican Republic",
    # Words where Wiktionary has wrong/obscure sense
    "oye": "hey!, listen!",
    "combo": "crew, group",
    "combos": "crews, groups",
    "nada": "nothing",
    "ahí": "there",
    "prende": "lights up, turns on",
    "prender": "to light up, to turn on",
    "haber": "to have (auxiliary)",
    "había": "there was/were",
    "santa": "saint, holy",
    "vos": "you (informal)",
    "pr": "Puerto Rico",
    "conocer": "to know, to meet",
    "cambiar": "to change",
    "nacer": "to be born",
    "repetir": "to repeat",
    "dembow": "dembow (music genre)",
    "quedarme": "to stay, to remain",
    "cerquita": "real close, nearby",
    "paso": "step",
    "pasar": "to pass, to happen",
    "llamar": "to call",
    "puesta": "set, ready",
    "puesto": "set, ready; position",
    "poner": "to put, to place",
}

# ── Proper nouns (should be filtered from the learning deck) ─────────────────
PROPER_NOUNS = frozenset({
    # Artists / producers
    "luian", "balvin", "tainy", "anuel", "romeo", "becky", "nicky", "tego",
    "shakira", "yandel", "ozuna", "farru", "farruko", "drake", "diddy",
    "maluma", "rauw", "cardi", "karol", "myke", "rihanna", "natti", "noriel",
    "rvssian", "lavoe", "eladio", "ricky", "miko", "miky", "benny", "ñejo",
    "ñengo", "brytiago", "yovngchimi", "amenazzy", "pusho", "jeday", "juhn",
    "tokischa", "diplo", "alofoke",
    # People
    "benito", "bryant", "myers", "rocky", "kobe", "messi", "verstappen",
    "alex", "booker", "chris", "eddie", "donald", "trump", "matt", "royce",
    "mayweather", "ray", "dicaprio", "lennon", "luka", "barea", "jimmy",
    "mark", "mike", "tom", "brad", "pitt", "bernie", "biles", "goldberg",
    "hector", "james", "john", "justin", "lopez", "marc", "martin", "michael",
    "jay",
    # Brands
    "gucci", "louis", "vuitton", "jordan", "bugatti", "lamborghini", "ferrari",
    "chanel", "nike", "versace", "prada", "iphone", "rolex", "balenciaga",
    "dolce", "adidas", "porsche", "maserati", "bulgari", "bentley", "benz",
    "fendi", "cartier", "dior", "durex", "bottega", "lambo", "lambos",
    # Places
    "miami", "york", "santurce", "colombia", "bronx", "coachella", "tokyo",
    "neverland", "legoland",
    # Platforms / media
    "instagram", "netflix", "soundcloud", "snapchat", "tiktok", "twitter",
    "spotify", "youtube", "billboard", "ebay",
    # Album references
    "yhlqmdlg",
    # Additional names found in remaining gaps
    "gaby", "andy", "bobby", "edgar", "jeter", "woodz", "vinci", "amber",
    "geezy", "maelo", "cotto", "bori", "claus", "wiz",
})

# ── Interjections / onomatopoeia (should be filtered) ────────────────────────
INTERJECTIONS = frozenset({
    "prr", "mmm", "wouh", "tra", "plo", "rrr", "rra", "shh", "wua", "hmm",
    "ku", "uah", "woo", "jajajaja", "rrra", "prra", "ouh", "uoh", "ieh",
    "yih", "ra", "wu", "jajajajaja", "jum", "jejeje", "prru", "rrrah",
    "yap", "muah", "lelolai", "aah", "prrr", "brrum", "buh", "fiu", "juh",
    "wah", "skrrs", "rrear", "ayy", "rah", "mua", "lalalalalalala", "oo",
    "brru", "roro", "wao'",
    # Syllable fragments from rhythmic repetition
    "tó", "bé", "gi", "gu", "pu", "mo", "ar", "ju", "ts", "flo", "wo",
    # Additional sound effects and fragments
    "mm", "trr", "tss", "uff", "eah", "hehe", "waka", "kr", "ki",
    "ching",
    # Single letters (not useful vocabulary)
    "b", "c", "d", "f", "g", "j", "k", "p", "q", "r", "s", "t", "v", "w", "x", "z",
    # Misc fragments
    "auh",
})

# ── Additional English words that slipped through ────────────────────────────
EXTRA_ENGLISH = frozenset({
    "bunny", "kush", "phillie", "bang", "glock", "og", "molly", "outro",
    "babydoll", "twerk", "perco", "percos", "krippy", "lil", "sung", "sup",
    "vogue",
})

# POS mapping: Wiktionary → Universal Dependencies
WIKT_TO_UD = {
    "verb": "VERB", "noun": "NOUN", "adj": "ADJ", "adv": "ADV",
    "pron": "PRON", "prep": "ADP", "conj": "CCONJ", "det": "DET",
    "article": "DET", "num": "NUM", "intj": "INTJ", "particle": "PART",
    "contraction": "ADP", "name": "PROPN", "prefix": "X", "suffix": "X",
    "phrase": "X", "abbrev": "X",
}

UD_TO_WIKT = defaultdict(list)
for wikt, ud in WIKT_TO_UD.items():
    UD_TO_WIKT[ud].append(wikt)
# Add extra mappings for common UD tags
UD_TO_WIKT["SCONJ"].extend(["conj"])
UD_TO_WIKT["CCONJ"].extend(["conj"])
UD_TO_WIKT["ADP"].extend(["prep"])

# ── English verb conjugation for flashcard-friendly translations ───────────────
# Maps Spanish infinitive translation → conjugated English forms.
# Only irregular English verbs need entries here; regular verbs are handled
# mechanically by _conjugate_regular().

IRREGULAR_ENGLISH = {
    # infinitive: (1sg, 2sg, 3sg, 1pl, 3pl, gerund, past, past_part, imperative)
    "be":    ("am", "are", "is", "are", "are", "being", "was", "been", "be"),
    "go":    ("go", "go", "goes", "go", "go", "going", "went", "gone", "go"),
    "have":  ("have", "have", "has", "have", "have", "having", "had", "had", "have"),
    "do":    ("do", "do", "does", "do", "do", "doing", "did", "done", "do"),
    "say":   ("say", "say", "says", "say", "say", "saying", "said", "said", "say"),
    "see":   ("see", "see", "sees", "see", "see", "seeing", "saw", "seen", "see"),
    "give":  ("give", "give", "gives", "give", "give", "giving", "gave", "given", "give"),
    "know":  ("know", "know", "knows", "know", "know", "knowing", "knew", "known", "know"),
    "come":  ("come", "come", "comes", "come", "come", "coming", "came", "come", "come"),
    "put":   ("put", "put", "puts", "put", "put", "putting", "put", "put", "put"),
    "leave": ("leave", "leave", "leaves", "leave", "leave", "leaving", "left", "left", "leave"),
    "want":  ("want", "want", "wants", "want", "want", "wanting", "wanted", "wanted", "want"),
    "feel":  ("feel", "feel", "feels", "feel", "feel", "feeling", "felt", "felt", "feel"),
    "think": ("think", "think", "thinks", "think", "think", "thinking", "thought", "thought", "think"),
    "take":  ("take", "take", "takes", "take", "take", "taking", "took", "taken", "take"),
    "tell":  ("tell", "tell", "tells", "tell", "tell", "telling", "told", "told", "tell"),
    "get":   ("get", "get", "gets", "get", "get", "getting", "got", "gotten", "get"),
    "can":   ("can", "can", "can", "can", "can", "—", "could", "—", "—"),
    "let":   ("let", "let", "lets", "let", "let", "letting", "let", "let", "let"),
    "drink": ("drink", "drink", "drinks", "drink", "drink", "drinking", "drank", "drunk", "drink"),
    "eat":   ("eat", "eat", "eats", "eat", "eat", "eating", "ate", "eaten", "eat"),
    "sleep": ("sleep", "sleep", "sleeps", "sleep", "sleep", "sleeping", "slept", "slept", "sleep"),
    "run":   ("run", "run", "runs", "run", "run", "running", "ran", "run", "run"),
    "write": ("write", "write", "writes", "write", "write", "writing", "wrote", "written", "write"),
    "sing":  ("sing", "sing", "sings", "sing", "sing", "singing", "sang", "sung", "sing"),
    "fall":  ("fall", "fall", "falls", "fall", "fall", "falling", "fell", "fallen", "fall"),
    "lose":  ("lose", "lose", "loses", "lose", "lose", "losing", "lost", "lost", "lose"),
    "win":   ("win", "win", "wins", "win", "win", "winning", "won", "won", "win"),
    "keep":  ("keep", "keep", "keeps", "keep", "keep", "keeping", "kept", "kept", "keep"),
    "spend": ("spend", "spend", "spends", "spend", "spend", "spending", "spent", "spent", "spend"),
    "understand": ("understand", "understand", "understands", "understand", "understand", "understanding", "understood", "understood", "understand"),
    "begin": ("begin", "begin", "begins", "begin", "begin", "beginning", "began", "begun", "begin"),
    "light": ("light", "light", "lights", "light", "light", "lighting", "lit", "lit", "light"),
    "shine": ("shine", "shine", "shines", "shine", "shine", "shining", "shone", "shone", "shine"),
    "ride":  ("ride", "ride", "rides", "ride", "ride", "riding", "rode", "ridden", "ride"),
    "rise":  ("rise", "rise", "rises", "rise", "rise", "rising", "rose", "risen", "rise"),
    "sit":   ("sit", "sit", "sits", "sit", "sit", "sitting", "sat", "sat", "sit"),
    "stand": ("stand", "stand", "stands", "stand", "stand", "standing", "stood", "stood", "stand"),
    "break": ("break", "break", "breaks", "break", "break", "breaking", "broke", "broken", "break"),
    "catch": ("catch", "catch", "catches", "catch", "catch", "catching", "caught", "caught", "catch"),
    "grow":  ("grow", "grow", "grows", "grow", "grow", "growing", "grew", "grown", "grow"),
    "lead":  ("lead", "lead", "leads", "lead", "lead", "leading", "led", "led", "lead"),
    "meet":  ("meet", "meet", "meets", "meet", "meet", "meeting", "met", "met", "meet"),
    "hear":  ("hear", "hear", "hears", "hear", "hear", "hearing", "heard", "heard", "hear"),
    "find":  ("find", "find", "finds", "find", "find", "finding", "found", "found", "find"),
    "bring": ("bring", "bring", "brings", "bring", "bring", "bringing", "brought", "brought", "bring"),
    "sell":  ("sell", "sell", "sells", "sell", "sell", "selling", "sold", "sold", "sell"),
    "send":  ("send", "send", "sends", "send", "send", "sending", "sent", "sent", "send"),
    "build": ("build", "build", "builds", "build", "build", "building", "built", "built", "build"),
    "hold":  ("hold", "hold", "holds", "hold", "hold", "holding", "held", "held", "hold"),
    "pay":   ("pay", "pay", "pays", "pay", "pay", "paying", "paid", "paid", "pay"),
    "hit":   ("hit", "hit", "hits", "hit", "hit", "hitting", "hit", "hit", "hit"),
    "shoot": ("shoot", "shoot", "shoots", "shoot", "shoot", "shooting", "shot", "shot", "shoot"),
    "hurt":  ("hurt", "hurt", "hurts", "hurt", "hurt", "hurting", "hurt", "hurt", "hurt"),
    "set":   ("set", "set", "sets", "set", "set", "setting", "set", "set", "set"),
    "bite":  ("bite", "bite", "bites", "bite", "bite", "biting", "bit", "bitten", "bite"),
    "choose":("choose", "choose", "chooses", "choose", "choose", "choosing", "chose", "chosen", "choose"),
    "drive": ("drive", "drive", "drives", "drive", "drive", "driving", "drove", "driven", "drive"),
    "fly":   ("fly", "fly", "flies", "fly", "fly", "flying", "flew", "flown", "fly"),
    "forget":("forget", "forget", "forgets", "forget", "forget", "forgetting", "forgot", "forgotten", "forget"),
    "hide":  ("hide", "hide", "hides", "hide", "hide", "hiding", "hid", "hidden", "hide"),
    "wake":  ("wake", "wake", "wakes", "wake", "wake", "waking", "woke", "woken", "wake"),
    "wear":  ("wear", "wear", "wears", "wear", "wear", "wearing", "wore", "worn", "wear"),
    "lend":  ("lend", "lend", "lends", "lend", "lend", "lending", "lent", "lent", "lend"),
    "fight": ("fight", "fight", "fights", "fight", "fight", "fighting", "fought", "fought", "fight"),
    "seek":  ("seek", "seek", "seeks", "seek", "seek", "seeking", "sought", "sought", "seek"),
    "teach": ("teach", "teach", "teaches", "teach", "teach", "teaching", "taught", "taught", "teach"),
    "dream": ("dream", "dream", "dreams", "dream", "dream", "dreaming", "dreamed", "dreamed", "dream"),
    "burn":  ("burn", "burn", "burns", "burn", "burn", "burning", "burned", "burned", "burn"),
    "prove": ("prove", "prove", "proves", "prove", "prove", "proving", "proved", "proven", "prove"),
    "swear": ("swear", "swear", "swears", "swear", "swear", "swearing", "swore", "sworn", "swear"),
}
# Index: 0=1sg, 1=2sg, 2=3sg, 3=1pl, 4=3pl, 5=gerund, 6=past, 7=past_part, 8=imperative
_CONJ_1SG, _CONJ_2SG, _CONJ_3SG, _CONJ_1PL, _CONJ_3PL = 0, 1, 2, 3, 4
_CONJ_GER, _CONJ_PAST, _CONJ_PP, _CONJ_IMP = 5, 6, 7, 8


def _conjugate_regular(infinitive: str) -> tuple:
    """Mechanically conjugate a regular English verb."""
    v = infinitive
    # 3rd person singular
    if v.endswith(("s", "sh", "ch", "x", "z", "o")):
        s3 = v + "es"
    elif v.endswith("y") and len(v) > 1 and v[-2] not in "aeiou":
        s3 = v[:-1] + "ies"
    else:
        s3 = v + "s"
    # gerund
    if v.endswith("e") and not v.endswith("ee"):
        ger = v[:-1] + "ing"
    elif v.endswith("ie"):
        ger = v[:-2] + "ying"
    else:
        ger = v + "ing"
    # past / past participle
    if v.endswith("e"):
        past = v + "d"
    elif v.endswith("y") and len(v) > 1 and v[-2] not in "aeiou":
        past = v[:-1] + "ied"
    else:
        past = v + "ed"
    return (v, v, s3, v, v, ger, past, past, v)


def _extract_infinitive(translation: str):
    """Extract the bare English infinitive from a translation like 'to walk' or 'to be able to'."""
    if not translation.startswith("to "):
        return None
    rest = translation[3:].strip()
    # Handle multi-meaning translations: take first verb phrase before comma or semicolon
    # "to have; to possess" → "have"
    # "to be able to, can" → "be able to"
    for sep in (";", ","):
        rest = rest.split(sep)[0].strip()
    # Remove trailing "to" artifacts: "to have; to possess" → after split → "have" (correct)
    return rest if rest else None


def conjugate_english(translation: str, tags: set):
    """
    Given a Spanish-to-English infinitive translation and Wiktionary inflection tags,
    return the conjugated English form, or None if we can't determine it.

    Examples:
      ("to be", {present, indicative, first-person, singular}) → "I am"
      ("to go", {present, indicative, third-person, singular}) → "he/she goes"
      ("to walk", {gerund}) → "walking"
      ("to say, to tell", {imperative, second-person, singular}) → "say!"
    """
    inf = _extract_infinitive(translation)
    if not inf:
        return None

    # For multi-word infinitives like "be able to", just use the first word for conjugation
    # but append the rest
    parts = inf.split()
    main_verb = parts[0]
    suffix = " " + " ".join(parts[1:]) if len(parts) > 1 else ""

    # Look up conjugation table
    if main_verb in IRREGULAR_ENGLISH:
        forms = IRREGULAR_ENGLISH[main_verb]
    else:
        forms = _conjugate_regular(main_verb)

    # Determine which form to use based on tags
    is_present = "present" in tags
    is_past = "past" in tags or "preterite" in tags
    is_imperfect = "imperfect" in tags
    is_future = "future" in tags
    is_conditional = "conditional" in tags
    is_subjunctive = "subjunctive" in tags
    is_imperative = "imperative" in tags
    is_gerund = "gerund" in tags or "progressive" in tags
    is_participle = "participle" in tags and "past" in tags

    is_1p = "first-person" in tags
    is_2p = "second-person" in tags
    is_3p = "third-person" in tags
    is_sing = "singular" in tags
    is_plur = "plural" in tags

    # Gerund: walking, going, being
    if is_gerund:
        return forms[_CONJ_GER] + suffix

    # Past participle: walked, gone, been
    if is_participle:
        return forms[_CONJ_PP] + suffix

    # Imperative: walk!, go!, be!
    if is_imperative:
        return forms[_CONJ_IMP] + suffix + "!"

    # Future: will walk, will go
    if is_future:
        person = "I" if is_1p and is_sing else "you" if is_2p else "he/she" if is_3p and is_sing else "we" if is_1p and is_plur else "they"
        return f"{person} will {main_verb}{suffix}"

    # Conditional: would walk, would go
    if is_conditional:
        person = "I" if is_1p and is_sing else "you" if is_2p else "he/she" if is_3p and is_sing else "we" if is_1p and is_plur else "they"
        return f"{person} would {main_verb}{suffix}"

    # Imperfect: was walking, used to walk
    if is_imperfect:
        person = "I" if is_1p and is_sing else "you" if is_2p else "he/she" if is_3p and is_sing else "we" if is_1p and is_plur else "they"
        return f"{person} used to {main_verb}{suffix}"

    # Past (preterite): I walked, he went
    if is_past:
        person = "I" if is_1p and is_sing else "you" if is_2p else "he/she" if is_3p and is_sing else "we" if is_1p and is_plur else "they"
        return f"{person} {forms[_CONJ_PAST]}{suffix}"

    # Present subjunctive: use bare infinitive
    if is_subjunctive and is_present:
        return main_verb + suffix

    # Present indicative
    if is_present:
        if is_1p and is_sing:
            return f"I {forms[_CONJ_1SG]}{suffix}"
        elif is_2p and is_sing:
            return f"you {forms[_CONJ_2SG]}{suffix}"
        elif is_3p and is_sing:
            return f"he/she {forms[_CONJ_3SG]}{suffix}"
        elif is_1p and is_plur:
            return f"we {forms[_CONJ_1PL]}{suffix}"
        elif is_3p and is_plur or is_plur:
            return f"they {forms[_CONJ_3PL]}{suffix}"

    return None


def clean_gloss(gloss: str) -> str:
    """
    Clean a Wiktionary gloss for use as a flashcard translation.
    Remove parenthetical notes, clean up formatting.
    """
    if not gloss:
        return ""

    # Skip glosses that are just form-of references
    if any(gloss.startswith(p) for p in (
        "inflection of", "plural of", "feminine of", "masculine of",
        "Alternative spelling", "Alternative form", "Obsolete",
        "Misspelling", "Dated form", "abbreviation of",
        "alternative letter-case form",
    )):
        return ""

    # Skip alphabet letter definitions
    if re.match(r"^The \w+ letter of the Spanish alphabet", gloss):
        return ""

    # Skip "initialism of" glosses that are too verbose
    if gloss.startswith("initialism of") and len(gloss) > 40:
        return ""

    # Remove parenthetical qualifiers but keep the main meaning
    result = gloss

    # Remove leading context labels in parentheses: "(colloquial) to eat" → "to eat"
    result = re.sub(r"^\([^)]{0,30}\)\s*", "", result)

    # Remove inline parenthetical notes: "to know (a person or a place)" → "to know"
    result = re.sub(r"\s*\([^)]*\)", "", result)

    # Remove trailing colon-separated elaboration: "there: used to designate..." → "there"
    result = re.sub(r":\s+.+$", "", result)

    # Clean up "used with..." and similar trailing notes
    result = re.sub(r"\s*[;,]\s*used (?:with|to|in|as).*$", "", result, flags=re.IGNORECASE)

    # Remove "female equivalent of X" patterns → just keep the translation
    result = re.sub(r";\s*female equivalent of\s+\w+", "", result)

    # Strip wiki formatting artifacts
    result = result.strip(" ,;.")

    # Truncate very long glosses (keep first clause)
    if len(result) > 40:
        # Try splitting on semicolons first
        parts = result.split(";")
        result = parts[0].strip()
    if len(result) > 40:
        # Try splitting on commas
        parts = result.split(",")
        result = ", ".join(parts[:2]).strip()
    if len(result) > 40:
        # Last resort: hard truncate at word boundary
        result = result[:37].rsplit(" ", 1)[0] + "..."

    return result


def load_wiktionary_glosses(dump_path: Path):
    """
    Parse Wiktionary dump into:
      glosses:   word → {wikt_pos: [cleaned glosses]}  (true lemma entries only)
      inflections: word → [(lemma, wikt_pos, tags_set), ...]  (form-of entries)
    """
    print("Loading Wiktionary glosses + inflections...")
    glosses = defaultdict(lambda: defaultdict(list))
    inflections = defaultdict(list)

    with gzip.open(dump_path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            word = entry.get("word", "").lower().strip()
            wikt_pos = entry.get("pos", "")
            if not word:
                continue

            for sense in entry.get("senses", []):
                if "form_of" in sense:
                    # Store inflection info: which lemma this is a form of + tags
                    form_of_list = sense.get("form_of", [])
                    tags = set(sense.get("tags", []))
                    for fo in form_of_list:
                        lemma_word = fo.get("word", "").lower().strip()
                        if lemma_word:
                            inflections[word].append((lemma_word, wikt_pos, tags))
                else:
                    raw_glosses = sense.get("glosses", [])
                    for g in raw_glosses:
                        cleaned = clean_gloss(g)
                        if cleaned and cleaned not in glosses[word][wikt_pos]:
                            glosses[word][wikt_pos].append(cleaned)

    print(f"  {len(glosses):,} words with glosses, {len(inflections):,} inflected forms")
    return dict(glosses), dict(inflections)


def get_translation(word: str, lemma: str, ud_pos: str,
                    glosses: dict, inflections: dict = None) -> str:
    """
    Get the best translation for a word given its lemma and POS.

    Strategy:
      0. Check curated translations table (highest priority)
      1. Surface form has its own standalone sense (e.g., oye as INTJ)
      2. Conjugation-aware: get lemma translation, then conjugate for this form
      3. Fall back to lemma + matching POS (infinitive form)
      4. Fall back to lemma + any POS
      5. Fall back to word + any POS
      6. Pattern-based fallbacks (elisions, diminutives)
    """
    w = word.lower()

    # 0. Curated translations (short, flashcard-ready)
    #    If the word itself has a curated entry, use it directly
    if w in CURATED_TRANSLATIONS:
        return CURATED_TRANSLATIONS[w]

    # Map UD POS to possible Wiktionary POS values
    wikt_pos_options = UD_TO_WIKT.get(ud_pos, [])

    # 1. Surface form has a standalone sense matching our POS
    #    e.g., "oye" has intj="hey! listen!" and we want that if POS is INTJ
    if w in glosses and w != lemma:
        for wp in wikt_pos_options:
            if wp in glosses[w]:
                gs = glosses[w][wp]
                if gs:
                    return gs[0]

    # 2. Conjugation-aware translation for verbs
    #    Use curated or Wiktionary lemma translation, then conjugate for this form
    if inflections and ud_pos == "VERB" and w != lemma and w in inflections:
        # Try curated lemma translation first, then Wiktionary
        lemma_trans = CURATED_TRANSLATIONS.get(lemma) or _get_lemma_translation(lemma, wikt_pos_options, glosses)
        if lemma_trans and lemma_trans.startswith("to "):
            for infl_lemma, infl_pos, tags in inflections[w]:
                if infl_lemma == lemma and infl_pos == "verb":
                    conjugated = conjugate_english(lemma_trans, tags)
                    if conjugated:
                        return conjugated
                    break

    # 2b. If lemma has curated entry but we couldn't conjugate, return it as-is
    if lemma in CURATED_TRANSLATIONS:
        return CURATED_TRANSLATIONS[lemma]

    # 3. Lemma + matching POS (returns infinitive for verbs)
    lemma_trans = _get_lemma_translation(lemma, wikt_pos_options, glosses)
    if lemma_trans:
        return lemma_trans

    # 4. Lemma + any POS
    if lemma in glosses:
        for wp in glosses[lemma]:
            gs = glosses[lemma][wp]
            if gs:
                return gs[0]

    # 5. Word + any POS (surface form, any sense)
    if w != lemma and w in glosses:
        for wp in glosses[w]:
            gs = glosses[w][wp]
            if gs:
                return gs[0]

    # 6. Pattern-based fallbacks for Caribbean elisions and diminutives

    # Elided participles: cambia'o → cambiado, prendí'o → prendido
    if re.match(r"(.+?)'[oa]s?$", w):
        m = re.match(r"(.+?)'([oa]s?)$", w)
        if m:
            stem, suffix = m.group(1), m.group(2)
            for recon in [stem + "d" + suffix, stem + "ad" + suffix]:
                trans = get_translation(recon, recon, "VERB", glosses, inflections)
                if trans:
                    return trans
                if recon.endswith("ado"):
                    verb = recon[:-3] + "ar"
                    trans = get_translation(verb, verb, "VERB", glosses, inflections)
                    if trans:
                        return trans
                elif recon.endswith("ido"):
                    for ending in ("er", "ir"):
                        verb = recon[:-3] + ending
                        trans = get_translation(verb, verb, "VERB", glosses, inflections)
                        if trans:
                            return trans

    # Diminutives: solita → sola/solo, loquita → loca/loco, ojitos → ojos
    if re.match(r"(.+?)(it[oa]s?)$", w):
        m = re.match(r"(.+?)(it[oa]s?)$", w)
        if m:
            stem = m.group(1)
            suffix = m.group(2)
            gender_suffix = suffix.replace("it", "")
            for base in [stem + gender_suffix, stem + "o", stem + "a", stem]:
                trans = get_translation(base, base, "X", glosses, inflections)
                if trans:
                    return f"little {trans}" if not trans.startswith("little") else trans

    return ""


def _get_lemma_translation(lemma: str, wikt_pos_options: list, glosses: dict) -> str:
    """Get translation for a lemma with POS matching, then any POS."""
    if lemma in glosses:
        for wp in wikt_pos_options:
            if wp in glosses[lemma]:
                gs = glosses[lemma][wp]
                if gs:
                    return gs[0]
    return ""


def get_all_pos_translations(word: str, lemma: str, pos_counts: dict,
                             glosses: dict, inflections: dict = None,
                             pos_lemma_map: dict = None) -> list[dict]:
    """
    Build a meanings list: one entry per POS with the best translation.
    Uses pos_lemma_map (POS → lemma) to look up POS-specific lemmas
    when a word has different lemmas per POS (e.g., llamas: NOUN→llama, VERB→llamar).
    """
    meanings = []
    total_count = sum(pos_counts.values())

    for ud_pos, count in sorted(pos_counts.items(), key=lambda x: -x[1]):
        # Use POS-specific lemma if available
        pos_lemma = pos_lemma_map.get(ud_pos, lemma) if pos_lemma_map else lemma

        trans = get_translation(word, pos_lemma, ud_pos, glosses, inflections)
        if not trans:
            # Try with the overall lemma
            trans = get_translation(word, lemma, ud_pos, glosses, inflections)
        if not trans:
            # Try without POS constraint
            trans = get_translation(word, lemma, "X", glosses, inflections)

        freq = f"{count / total_count:.2f}" if total_count > 0 else "1.00"

        meanings.append({
            "pos": ud_pos,
            "translation": trans,
            "frequency": freq,
        })

    return meanings


def main():
    # Load inputs
    with open(IN_PATH) as f:
        wikt_output = json.load(f)
    print(f"Loaded {len(wikt_output)} entries from Phase 1 output")

    glosses, inflections = load_wiktionary_glosses(WIKT_DUMP)

    # Load old vocabulary for comparison and stable IDs
    old_vocab = {}
    old_ids = {}
    if OLD_VOCAB_PATH.exists():
        with open(OLD_VOCAB_PATH) as f:
            for entry in json.load(f):
                key = (entry.get("word", ""), entry.get("lemma", ""))
                old_vocab[entry.get("word", "")] = entry
                if "id" in entry:
                    old_ids[key] = entry["id"]

    # Build output
    output = []
    next_id = max((int(v, 16) for v in old_ids.values()), default=0) + 1

    stats = {
        "total": 0, "translated": 0, "empty_translation": 0,
        "from_wiktionary": 0, "from_old_cache": 0,
    }
    diff_report = {"translation_changes": [], "new_translations": [],
                   "still_empty": [], "stats": {}}

    for idx, entry in enumerate(wikt_output):
        word = entry["word"]
        lemma = entry["lemma"]
        corpus_count = entry.get("corpus_count", 0)
        pos_counts = entry.get("pos_summary", {}).get("pos_counts", {})
        lang_flags = entry.get("language_flags", {})
        display_form = entry.get("display_form")
        examples = entry.get("evidence", {}).get("examples", [])

        # Stable ID assignment
        key = (word, lemma)
        if key in old_ids:
            hex_id = old_ids[key]
        else:
            # Try word-only match from old vocab
            old_entry = old_vocab.get(word)
            if old_entry and "id" in old_entry:
                hex_id = old_entry["id"]
            else:
                hex_id = format(next_id, "04x")
                next_id += 1

        # Determine flags — use curated wordlists + NLP signals
        w_lower = word.lower()
        is_english = (lang_flags.get("is_english", False) or
                      w_lower in EXTRA_ENGLISH)
        is_interjection = (w_lower in INTERJECTIONS or
                          ("INTJ" in pos_counts and
                           pos_counts.get("INTJ", 0) / max(sum(pos_counts.values()), 1) > 0.5))
        is_propernoun = (w_lower in PROPER_NOUNS or
                        ("PROPN" in pos_counts and
                         pos_counts.get("PROPN", 0) / max(sum(pos_counts.values()), 1) > 0.5))

        # Build POS → lemma map from contextual matches
        # e.g., llamas: NOUN→llama, VERB→llamar
        matches = entry.get("matches", [])
        pos_lemma_map = {}
        for m in matches:
            m_pos = m.get("pos", "")
            m_lemma = m.get("lemma", "")
            if m_pos and m_lemma and m_pos not in pos_lemma_map:
                pos_lemma_map[m_pos] = m_lemma

        # Get translations
        if is_english:
            # English words get themselves as translation
            meanings = [{"pos": "X", "translation": word, "frequency": "1.00"}]
        elif is_interjection or is_propernoun:
            meanings = [{"pos": list(pos_counts.keys())[0] if pos_counts else "X",
                         "translation": "", "frequency": "1.00"}]
        else:
            meanings = get_all_pos_translations(word, lemma, pos_counts, glosses,
                                                inflections, pos_lemma_map)

        # Add examples to meanings, matched by POS
        # Build example_id → POS mapping from matches
        matches = entry.get("matches", [])
        example_pos_map = {}  # example_id → POS
        for m in matches:
            eid = m.get("example_id", "")
            if eid and eid not in example_pos_map:
                example_pos_map[eid] = m.get("pos", "X")

        # Build example_id → example data mapping
        example_data = {}
        for ex in examples[:20]:
            eid = ex.get("id", "")
            if eid:
                example_data[eid] = {
                    "song": eid.split(":")[0] if ":" in eid else "",
                    "song_name": ex.get("title", ""),
                    "spanish": ex.get("line", ""),
                    "english": "",
                }

        for meaning in meanings:
            meaning_pos = meaning["pos"]
            meaning_examples = []

            # First: examples whose POS matches this meaning
            for eid, pos in example_pos_map.items():
                if pos == meaning_pos and eid in example_data:
                    meaning_examples.append(example_data[eid])
                    if len(meaning_examples) >= 10:
                        break

            # If no POS-matched examples, fall back to any available examples
            if not meaning_examples:
                for ex in examples[:10]:
                    eid = ex.get("id", "")
                    if eid in example_data:
                        meaning_examples.append(example_data[eid])
                        if len(meaning_examples) >= 10:
                            break

            meaning["examples"] = meaning_examples

        # Track stats
        stats["total"] += 1
        word_trans = meanings[0]["translation"] if meanings else ""
        if word_trans:
            stats["translated"] += 1
            stats["from_wiktionary"] += 1
        else:
            stats["empty_translation"] += 1
            if not is_english and not is_interjection and not is_propernoun:
                diff_report["still_empty"].append({
                    "word": word, "lemma": lemma, "corpus_count": corpus_count,
                })

        # Compare with old vocabulary
        old = old_vocab.get(word)
        if old:
            old_trans = old.get("meanings", [{}])[0].get("translation", "") if old.get("meanings") else ""
            if word_trans and old_trans and word_trans != old_trans:
                diff_report["translation_changes"].append({
                    "word": word, "old": old_trans, "new": word_trans,
                    "corpus_count": corpus_count,
                })
            elif word_trans and not old_trans:
                diff_report["new_translations"].append({
                    "word": word, "translation": word_trans,
                    "corpus_count": corpus_count,
                })

        # Build output entry
        out_entry = {
            "id": hex_id,
            "word": word,
            "lemma": lemma,
            "meanings": meanings,
            "most_frequent_lemma_instance": True,  # Will be recomputed in Phase 4
            "is_english": is_english,
            "is_interjection": is_interjection,
            "is_propernoun": is_propernoun,
            "is_transparent_cognate": False,  # Step 8 is authoritative
            "corpus_count": corpus_count,
        }
        if display_form:
            out_entry["display_form"] = display_form

        output.append(out_entry)

    # ── Compute most_frequent_lemma_instance ────────────────────────────────
    # Group by lemma, mark only the highest-corpus-count form as True
    lemma_groups = defaultdict(list)
    for i, entry in enumerate(output):
        lemma_groups[entry["lemma"]].append((i, entry.get("corpus_count", 0)))

    changed_count = 0
    for lemma, entries in lemma_groups.items():
        if len(entries) <= 1:
            continue
        # Find the entry with the highest corpus count
        best_idx = max(entries, key=lambda x: x[1])[0]
        for idx, _ in entries:
            should_be = (idx == best_idx)
            if output[idx]["most_frequent_lemma_instance"] != should_be:
                output[idx]["most_frequent_lemma_instance"] = should_be
                changed_count += 1

    print(f"\nmost_frequent_lemma_instance: {changed_count} entries updated")
    print(f"  Lemmas with multiple forms: {sum(1 for v in lemma_groups.values() if len(v) > 1)}")

    # Stats
    diff_report["stats"] = stats
    diff_report["stats"]["translation_changes"] = len(diff_report["translation_changes"])
    diff_report["stats"]["new_translations"] = len(diff_report["new_translations"])
    diff_report["stats"]["still_empty"] = len(diff_report["still_empty"])

    # Write output
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(output)} entries to {OUT_PATH}")

    with open(DIFF_PATH, "w", encoding="utf-8") as f:
        json.dump(diff_report, f, ensure_ascii=False, indent=2)
    print(f"Wrote diff report to {DIFF_PATH}")

    # Summary
    print(f"\n{'='*60}")
    print(f"TRANSLATION STATS:")
    print(f"  Total entries:        {stats['total']}")
    print(f"  With translation:     {stats['translated']} ({stats['translated']/stats['total']*100:.1f}%)")
    print(f"  Empty translation:    {stats['empty_translation']} ({stats['empty_translation']/stats['total']*100:.1f}%)")
    print(f"  Still empty (non-junk): {len(diff_report['still_empty'])}")

    print(f"\nTRANSLATION CHANGES vs old vocab (top 20 by count):")
    changes = sorted(diff_report["translation_changes"], key=lambda x: -x["corpus_count"])
    for c in changes[:20]:
        print(f"  {c['word']:15s}  \"{c['old']:20s}\" → \"{c['new'][:30]}\"  (count={c['corpus_count']})")

    print(f"\nNEW TRANSLATIONS (top 20 — previously empty):")
    new = sorted(diff_report["new_translations"], key=lambda x: -x["corpus_count"])
    for n in new[:20]:
        print(f"  {n['word']:15s}  \"{n['translation'][:30]}\"  (count={n['corpus_count']})")

    print(f"\nSTILL EMPTY (top 20 — need claude -p):")
    empty = sorted(diff_report["still_empty"], key=lambda x: -x["corpus_count"])
    for e in empty[:20]:
        print(f"  {e['word']:15s}  (lemma={e['lemma']}, count={e['corpus_count']})")


if __name__ == "__main__":
    main()
