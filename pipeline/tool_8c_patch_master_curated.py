#!/usr/bin/env python3
"""No-rerun curated patches to vocabulary_master.json (in place).

Applies a small set of hand-verified corrections directly to the assembled
master, WITHOUT re-running the pipeline. Each edit is in-place (no change to
any card's sense COUNT) so the per-artist index files — which reference senses
positionally — stay in sync. See docs/deck_quality_audit.md.

Two kinds of edit:
  - OVERRIDES      : per-card field corrections (lemma / flag / sense fields).
  - COGNATE_STAMPS : flag single-sense transparent cognates (gloss == the
                     Spanish word, e.g. radio->"radio") with
                     is_transparent_cognate so the front-end hides them by
                     default. Single-sense only — hiding the card loses no
                     other meaning. False friends (cognates.json `keep`) and
                     multi-sense leaks are deliberately excluded.

Idempotent and safe to re-run: it verifies each entry's surface word before
touching it and only reports a change when a value actually differs.

IMPORTANT: `tool_8c_merge_to_master` rebuilds master from layers and drops
these edits. Re-run this script after any master rebuild, until the fixes are
folded into the pipeline proper. Run from project root:

    .venv/bin/python3 pipeline/tool_8c_patch_master_curated.py
"""
import json
import os
import sys

MASTER = "Artists/spanish/vocabulary_master.json"

# key (master hex) -> expected surface word + the in-place mutations.
#   lemma   : new lemma string (or None to leave)
#   flags   : top-level flag overrides
#   senses  : {sense_index: {field: value, ...}}
OVERRIDES = [
    {
        "key": "c7a231", "word": "millo", "lemma": None, "flags": {},
        # "Nací pa' ser millo" — PR slang clip of millón = rich, not "corn".
        "senses": {0: {"translation": "millionaire", "context": "slang"}},
    },
    {
        "key": "7917b4", "word": "niveles", "lemma": "nivel", "flags": {},
        # "es cuestión de niveles" — plural of NOUN nivel, not the verb nivelar.
        "senses": {0: {"pos": "NOUN", "translation": "level", "context": ""}},
    },
    {
        "key": "b7f4e2", "word": "diablo", "lemma": None, "flags": {},
        # Fill the blank interjection sense (the flagged "damn!" usage).
        "senses": {1: {"translation": "damn!, the hell", "context": "exclamation"}},
    },
    {
        "key": "8b83ae", "word": "diablos", "lemma": None, "flags": {},
        # "¿Cómo diablos...?" = how the hell.
        "senses": {0: {"translation": "the hell, devils", "context": "exclamation"}},
    },
    {
        "key": "d15eaf", "word": "bi", "lemma": None, "flags": {},
        # Shorten the verbose gap-fill gloss in place (single real sense).
        "senses": {0: {"translation": "boo; baby (term of endearment)"}},
    },
    {
        "key": "0f1ec2", "word": "shot", "lemma": None,
        # English code-switch — hide via the default-on loanword filter.
        "flags": {"is_english_loanword": True},
        "senses": {},
    },
    {
        "key": "0aa057", "word": "compositor", "lemma": None, "flags": {},
        # Leaked as itself; English "compositor" is an archaic printing term.
        # The music sense (the one in the corpus) is "composer". Fix the gloss
        # rather than hide the card.
        "senses": {0: {"translation": "composer"}},
    },
    {
        "key": "6be7cb", "word": "tití", "lemma": None, "flags": {},
        # PR usage ("Tití me preguntó") = auntie, not the monkey "titi".
        # Fix the gloss rather than hide the card.
        "senses": {0: {"translation": "auntie"}},
    },
    {
        "key": "eeeb94", "word": "eo", "lemma": None,
        # Bad Bunny ad-lib filler ("eo eo eo"), not the rare noun eo=hiatus.
        # Hide as noise (default-on noise filter) rather than teach it.
        "flags": {"is_noise": True},
        "senses": {},
    },
    # --- 2026-07-05 audit: verbatim-EN + mid-line-caps detector triage ---
    {
        "key": "3f1a0e", "word": "tán", "lemma": "estar", "flags": {},
        # "'tán" = apheresis of "están" (all 9 corpus lines), but SpanishDict
        # resolved the ENGLISH headword "tan" -> 9 Spanish-gloss senses.
        # Rewrite sense 0 to the real meaning and blank the other 8; the
        # front-end drops empty-translation meanings AFTER the positional
        # join (js/vocab.js empty-meaning guard), so blanking is index-safe.
        # Blanked senses also get pos=X so they read as placeholders (the
        # bench's blank_rows check ignores X; the front-end drops them on
        # translation alone either way).
        "senses": dict(
            [(0, {"pos": "VERB", "translation": "are (short for ‘están’)",
                  "context": "colloquial contraction"})] +
            [(i, {"pos": "X", "translation": "", "context": ""})
             for i in range(1, 9)]
        ),
    },
    {
        "key": "4c4d59", "word": "media", "lemma": "medio", "flags": {},
        # "media virá', media asfixiá'" = half/kinda, not "communication outlets".
        "senses": {0: {"pos": "ADJ", "translation": "half",
                       "context": "before adjectives: media loca = half crazy"}},
    },
    {
        "key": "95c738", "word": "manín", "lemma": "manín", "flags": {},
        # PR slang vocative (Dominican origin), not the peanut (maní).
        "senses": {0: {"translation": "bro, buddy (slang)", "context": ""}},
    },
    {
        "key": "a6fac9", "word": "mera", "lemma": None, "flags": {},
        # "¡Mera, Miko!" — PR attention-getter, not "boss".
        "senses": {0: {"translation": "hey!, look! (attention-getter)", "context": ""}},
    },
    {
        "key": "8c937e", "word": "capos", "lemma": None, "flags": {},
        # "Conozco los capo'" = drug bosses; "ceja" is the guitar-capo sense
        # from the reverse-direction (EN headword) SpanishDict lookup.
        "senses": {0: {"translation": "kingpin, boss", "context": "drug capo"}},
    },
    {
        "key": "359d36", "word": "complot", "lemma": None, "flags": {},
        # Reverse-direction glosses (complot/conspiración are Spanish).
        "senses": {0: {"translation": "plot, conspiracy"},
                   1: {"translation": "conspiracy"}},
    },
    {
        "key": "d53676", "word": "squirteé", "lemma": None, "flags": {},
        # Spanish-language gap-fill gloss.
        "senses": {0: {"translation": "to squirt", "context": ""}},
    },
    {
        "key": "3c1255", "word": "jeepeta", "lemma": None, "flags": {},
        "senses": {0: {"translation": "SUV, jeep", "context": "Caribbean slang"}},
    },
    {
        "key": "383046", "word": "hippies", "lemma": "hippie", "flags": {},
        "senses": {0: {"translation": "hippie", "context": ""}},
    },
    {
        "key": "49fcf4", "word": "hijeputada", "lemma": None, "flags": {},
        "senses": {0: {"translation": "dirty move, low blow", "context": ""}},
    },
    {
        "key": "844643", "word": "toa", "lemma": None, "flags": {},
        # "Toa' solteras" = todas.
        "senses": {0: {"translation": "all (short for ‘toda’)",
                       "context": "colloquial"}},
    },
    {
        "key": "548cb0", "word": "zeta", "lemma": None, "flags": {},
        "senses": {0: {"translation": "Z (slang for a car)", "context": ""}},
    },
    # Verbose gap-fill glosses shortened in place (single real sense each).
    {
        "key": "7dc675", "word": "dos", "lemma": None, "flags": {},
        "senses": {0: {"translation": "two"}},
    },
    {
        "key": "feeeb2", "word": "champaña", "lemma": None, "flags": {},
        "senses": {0: {"translation": "champagne"}},
    },
    {
        "key": "55303f", "word": "condones", "lemma": "condón", "flags": {},
        "senses": {0: {"translation": "condom"}},
    },
    {
        "key": "4881ae", "word": "mai", "lemma": None, "flags": {},
        "senses": {0: {"translation": "mom (slang)"}},
    },
    {
        "key": "19132e", "word": "bb", "lemma": None, "flags": {},
        "senses": {0: {"translation": "baby (texting shorthand)"}},
    },
    {
        "key": "492bf1", "word": "mambo", "lemma": None, "flags": {},
        "senses": {0: {"translation": "party, ruckus (slang)"}},
    },
    {
        "key": "c5f16d", "word": "reggaetón", "lemma": None, "flags": {},
        "senses": {0: {"translation": "reggaeton"}},
    },
    {
        "key": "c5b6fa", "word": "chalet", "lemma": None, "flags": {},
        "senses": {0: {"translation": "chalet, villa"}},
    },
    {
        "key": "c1ae53", "word": "puertorro", "lemma": None, "flags": {},
        "senses": {0: {"translation": "Puerto Rico / Puerto Rican (slang)"}},
    },
    # --- 2026-07-05 blank-rows fill: SpanishDict captured the usage label
    # (context) but not the gloss. Fill translation in place; the sense
    # becomes visible for lyrics that were assigned to it. ---
    {"key": "364d4a", "word": "da", "lemma": None, "flags": {},
     "senses": {10: {"translation": "to apply, to put on"}}},
    {"key": "c74f26", "word": "damos", "lemma": None, "flags": {},
     "senses": {8: {"translation": "to apply, to put on"}}},
    {"key": "aa8aaa", "word": "dado", "lemma": None, "flags": {},
     "senses": {1: {"translation": "to hand over"}}},
    {"key": "b186ac", "word": "dé", "lemma": None, "flags": {},
     "senses": {3: {"translation": "to hand over"}}},
    {"key": "6fa2b2", "word": "dimos", "lemma": None, "flags": {},
     "senses": {2: {"translation": "to hand over"}}},
    {"key": "695915", "word": "dar", "lemma": None, "flags": {},
     "senses": {4: {"translation": "to hand over"}}},
    {"key": "3a794e", "word": "muere", "lemma": None, "flags": {},
     "senses": {2: {"translation": "to be dying of",
                    "context": "morirse de amor/hambre"}}},
    {"key": "607394", "word": "pocos", "lemma": None, "flags": {},
     "senses": {1: {"translation": "few, not many"}}},
    {"key": "7c7faf", "word": "pusimos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to become", "context": "ponerse + adjective"}}},
    {"key": "cd31b3", "word": "pusiera", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to become", "context": "ponerse + adjective"}}},
    {"key": "b00c69", "word": "cada", "lemma": None, "flags": {},
     "senses": {2: {"translation": "each, every",
                    "context": "progression: cada vez más"}}},
    {"key": "70efad", "word": "fenomenal", "lemma": None, "flags": {},
     "senses": {0: {"translation": "amazingly, great"}}},
    {"key": "44d65c", "word": "se", "lemma": None, "flags": {},
     "senses": {5: {"translation": "one, people (impersonal)",
                    "context": "se dice = people say"}}},
    {"key": "ae4417", "word": "sendo", "lemma": None, "flags": {},
     "senses": {0: {"translation": "huge, mighty", "context": "colloquial"}}},
    {"key": "1a6760", "word": "eramos", "lemma": "ser", "flags": {},
     # éramos = "we were" (ser), not the farming verb erar.
     "senses": {0: {"translation": "were (éramos = we were)", "context": ""}}},
    {"key": "c6a0a0", "word": "amanezca", "lemma": None, "flags": {},
     "senses": {1: {"translation": "to dawn, to wake up"}}},
    {"key": "961948", "word": "amanezco", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to dawn, to wake up"}}},
    {"key": "1d2e8e", "word": "pendiente", "lemma": None, "flags": {},
     "senses": {1: {"translation": "pending, unresolved"}}},
    {"key": "1522d2", "word": "veces", "lemma": None, "flags": {},
     "senses": {2: {"translation": "turn, time"}}},
    {"key": "85813b", "word": "culona", "lemma": None, "flags": {},
     "senses": {0: {"translation": "big-bottomed woman", "context": "vulgar"}}},
    {"key": "5f5acd", "word": "huele", "lemma": None, "flags": {},
     "senses": {1: {"translation": "to seem, to smack of",
                    "context": "huele a = smells like"}}},
    {"key": "4821a1", "word": "vuelva", "lemma": None, "flags": {},
     "senses": {1: {"translation": "to do again", "context": "volver a + verb"}}},
    {"key": "3f2038", "word": "vuelves", "lemma": None, "flags": {},
     "senses": {2: {"translation": "to do again", "context": "volver a + verb"}}},
    {"key": "d988e1", "word": "caer", "lemma": None, "flags": {},
     "senses": {2: {"translation": "to fall (night, rain)", "context": "weather/time"}}},
    {"key": "2a9135", "word": "cae", "lemma": None, "flags": {},
     "senses": {1: {"translation": "to fall (night, rain)", "context": "weather/time"}}},
    {"key": "fb2520", "word": "acaso", "lemma": None, "flags": {},
     "senses": {1: {"translation": "perhaps, by any chance",
                    "context": "rhetorical questions"}}},
    {"key": "296e68", "word": "esperando", "lemma": None, "flags": {},
     "senses": {4: {"translation": "to hang on, to wait"}}},
    {"key": "b88fc0", "word": "saber", "lemma": None, "flags": {},
     "senses": {4: {"translation": "to taste of", "context": "saber a"}}},
    {"key": "85b01d", "word": "sabe", "lemma": None, "flags": {},
     "senses": {2: {"translation": "to taste of", "context": "saber a"}}},
    {"key": "61bd7d", "word": "a", "lemma": None, "flags": {},
     "senses": {1: {"translation": "at, per", "context": "with quantities"}}},
    {"key": "2fa825", "word": "poco", "lemma": None, "flags": {},
     "senses": {1: {"translation": "little, not much"}}},
    {"key": "996882", "word": "común", "lemma": None, "flags": {},
     "senses": {0: {"translation": "the majority, common people"}}},
    {"key": "cb971a", "word": "de", "lemma": None, "flags": {},
     "senses": {1: {"translation": "of, belonging to", "context": "possession"}}},
    {"key": "b31775", "word": "bate", "lemma": None, "flags": {},
     # "to' los récords bate" = batir; (the blunt NOUN sense is separate).
     "senses": {0: {"translation": "to break (a record), to beat",
                    "context": "batir"}}},
    # Round 2 (found by the new code_switch_verbatim bench detector).
    {
        "key": "53c40c", "word": "cuki", "lemma": "cuki", "flags": {},
        # "esa es mi cuki" = cutie/cookie, not the guinea pig (cuy).
        "senses": {0: {"translation": "cutie, sweetie", "context": ""}},
    },
    {
        "key": "bb0e1c", "word": "trili", "lemma": "trili", "flags": {},
        # PR slang ("un charro, un trili" = a scrub, a nobody); "trino" was a
        # reverse-direction lookup of English "trill".
        "senses": {0: {"translation": "nobody, wack person (slang)", "context": ""}},
    },
]

# Single-sense transparent cognates: only sense glosses to the Spanish word
# itself, so the card teaches nothing. Stamp is_transparent_cognate -> the
# front-end hides them under the default-on cognate filter. (key, word) pairs;
# word is verified against the master before stamping. Generated from the
# bench cognate-leak scan, hand-reviewed: false friends and multi-sense leaks
# (china, super, union, general, ...) are excluded. See docs/deck_quality_audit.md.
COGNATE_STAMPS = [
    ("19f1f6", "alcohol"),
    ("f4245c", "area"),
    ("a2dcd6", "bachata"),
    ("822807", "bases"),
    ("dc0219", "chicha"),
    ("7cef6e", "control"),
    ("57765a", "crack"),
    ("22f1f4", "dimensión"),
    ("b40305", "formal"),
    ("acd437", "gala"),
    ("78b399", "idea"),
    ("391fac", "iris"),
    ("503471", "legal"),
    ("0e5c84", "local"),
    ("cf0920", "manual"),
    ("9e03b3", "marihuana"),
    ("deeb66", "melón"),
    ("2d00c2", "normal"),
    ("0557d6", "novena"),
    ("835779", "perfume"),
    ("5f478c", "personal"),
    ("71816b", "popular"),
    ("91c4e7", "radio"),
    ("dc47ea", "samurai"),
    ("701880", "sangría"),
    ("6e83d0", "santería"),
    ("353258", "sativa"),
    ("2c66cd", "sensual"),
    ("75b019", "sushi"),
    ("a93b2f", "súper"),
    ("7c2d28", "unión"),
    ("a34e06", "vodka"),
    ("cc4896", "élite"),
    # Short (<4 char) transparent cognates the generator's len>=4 guard skips;
    # hand-verified single-sense gloss==word leaks (see the 6-short-word audit).
    ("0cfe85", "dúo"),
    ("bad194", "era"),    # NOUN era|era only; VERB era|ser ("to be") untouched
    ("b936fa", "ex"),
    ("4c30db", "gas"),
    # 2026-07-05 audit: single-real-sense transparent cognates (any extra
    # sense is a blank POS=X placeholder the front-end already drops).
    ("29631d", "puma"),
    ("7e6a8a", "panda"),
    ("4fcc7c", "viral"),
    ("3eb0c6", "saga"),
    ("4e013c", "oasis"),
    ("f51897", "ángel"),
    ("591399", "chef"),
    ("bd6fcd", "record"),
    ("f5f42a", "rifles"),
    ("5cd309", "pelvis"),
    ("8b6095", "boutique"),
    ("38dc7a", "mariachi"),
    ("24f4f8", "parental"),   # "Parental Advisory"
    ("c5f16d", "reggaetón"),  # gloss shortened to "reggaeton" above -> transparent
]

# English code-switches the Wiktionary-derived english_loanwords.json layer
# misses (they aren't in es.wiktionary as all-English-borrowing entries, so
# tool_4a/tool_8a never flag them). Same effect as the layer stamp:
# is_english_loanword -> the default-on loanword filter hides them. Surface
# word verified before stamping. The systematic fix is a manual loanword
# supplement folded into tool_8a; until then these live here. (key, word).
LOANWORD_STAMPS = [
    ("8e40c1", "boy"),
    ("6e23bc", "combo"),
    ("1eac4f", "haters"),
    ("f0ae8d", "lean"),
    ("d34a61", "lit"),
    ("9648af", "polaroid"),
    ("ab4169", "sexy"),
    ("39f5f1", "squad"),
    # 2026-07-05 audit: found by the verbatim-in-EN detector (word appears
    # unchanged in the Genius English translation of ALL its lyric lines).
    ("51da55", "so"),        # "so no me frontee'" — English conjunction
    ("99931a", "go"),
    ("6b4e32", "too"),       # "it's too late"
    ("64488e", "yes"),
    ("173660", "game"),      # Game Boy / game over
    ("c25d9b", "time"),      # one time / all time
    ("c9867f", "body"),
    ("c699f3", "tune"),      # Auto-Tune
    ("c0280c", "royal"),     # royal rumble / royal blue
    ("76034e", "cash"),
    ("2f1f33", "tag"),       # tag team
    ("5c1136", "ski"),       # jet ski / ski mask
    ("b6f2c9", "blackjack"),
    ("2b486d", "planking"),
    ("fc7e57", "speaker"),
    ("44b09d", "stripper"),
    ("3f5623", "closet"),
    ("1a7731", "cherry"),
    ("f50c67", "selfie"),
    ("a9d184", "gangsters"),
    ("272fb5", "boys"),      # Pep Boys / Carbon Fiber Boys
    ("5f0ca8", "shots"),
    ("5554cc", "viking"),
    ("1e4c81", "parking"),
    ("796c0e", "buffet"),
    ("9a0d59", "bumper"),
    ("cf5f27", "full"),      # PR "estar full" — still the English word
    ("958218", "retros"),    # retro Jordans
    ("372a99", "rap"),
    ("b9fc38", "hot"),       # hot pants / Hot Topic
    ("00deb3", "gangalee"),  # dancehall borrowing
    ("8668fa", "fan"),       # Young Miko
    ("a81a50", "fans"),
    ("5c3139", "lowkey"),
    ("810d8a", "strikes"),   # baseball
    ("4fdfde", "gangster"),
    ("ad642f", "boujee"),    # Young Miko; gloss was reverse-direction "fresa"
    ("4a18df", "let's"),     # "let's go" — pure English contraction
]

# Proper nouns the corpus detector missed — found by the mid-line-caps
# detector (word is ALWAYS capitalized mid-sentence in its lyric lines) and
# hand-verified against the examples. Most got dictionary-artifact glosses
# (rob="syrup" for Rob Van Dam, vegas="meadow" for Las Vegas). Stamp
# is_propernoun -> hidden by the default-on proper-noun filter. (key, word).
PROPERNOUN_STAMPS = [
    ("9d2e27", "rob"),        # Rob Van Dam ("syrup")
    ("579bff", "lee"),        # Bruce Lee ("read")
    ("7453f7", "carmen"),     # Virgen del Carmen ("poem")
    ("e82db5", "montana"),    # Tony Montana / Montana The Producer ("mountain")
    ("aae07e", "vegas"),      # Las Vegas ("meadow")
    ("8e6bf9", "coronas"),    # Corona beer
    ("57efd1", "aires"),      # Buenos Aires ("air")
    ("d49313", "central"),    # Central Park ("main")
    ("26cf81", "triple"),     # Triple H
    ("d34750", "union"),      # The Union
    ("4e023e", "formula"),    # Formula 1
    ("91cbe0", "urus"),       # Lamborghini Urus
    ("d1bcdc", "mini"),       # Mini Cooper
    ("81144f", "usa"),        # USA (glossed "EE. UU."; usar has 10 own cards)
    ("b33915", "sprinter"),   # Mercedes Sprinter
    ("2100f3", "choliseo"),   # El Choliseo (PR venue)
    ("6f77b0", "gta"),        # Grand Theft Auto
    ("205b77", "ferro"),      # "el Ferro" = Ferrari ("anchor")
    ("203998", "tic"),        # Tic Tacs / "Tic Toc" (brand refs)
    ("d7a473", "caicos"),     # Turks and Caicos ("guys", lemma=chicos!)
    ("5d9dad", "ganda"),      # name in ad-lib ("to eat")
    ("cd6ba1", "luían"),      # DJ Luian ("to polish")
    ("d48473", "lary"),       # Lary Over (lemma=lazy, gloss="perezoso")
    ("b40a91", "glizzy"),     # Glizzy = Glock nickname ("esplendoroso")
    ("f33f9a", "murdaz"),     # Trap Murdaz ("scathing")
    ("29eebb", "wayy"),       # Money Wayy
    ("7f434c", "sinfo"),      # nickname Sinfo (lemma=sino, gloss="but")
    ("593f69", "chapo"),      # El Chapo
    ("828399", "jhay"),       # Jhay Cortez ("chick")
    ("7727f3", "chacón"),     # surname ("Philippine lizard")
    ("cae1e5", "cavaliers"),  # Cleveland Cavaliers ("caballero")
    ("2e8786", "beatles"),    # The Beatles
    ("e4b532", "snuka"),      # Jimmy Snuka
    ("04964d", "guiru"),      # nickname
    ("76fd28", "wasón"),      # proper name per its own gloss
    ("a5e41d", "jota"),       # Jota Rosa (producer tag), Young Miko
    ("2f1cc0", "barea"),      # José Juan Barea (PR NBA player)
]

# Junk tokens: ad-libs, stutters, bare prefixes and single letters that teach
# nothing. Stamp is_noise -> hidden by the default-on noise filter. (key, word).
NOISE_STAMPS = [
    ("724438", "kariri"),  # ad-lib; Gemini gloss was a Spanish sentence
    ("8d67ac", "nio"),     # "¡Nio!" ad-lib (glossed "nor")
    ("e19087", "cheki"),   # "Cheki" = check-it ad-lib (lemma=cheli!)
    ("e58aef", "l"),       # single letter
    ("b551c9", "des"),     # bare prefix card ("de-", "un-", ...)
    ("ef69e1", "dí"),      # stutter "Dí-Díselo" captured as prefix "di-"
    ("7d6209", "neo"),     # bare prefix card ("neo-")
    ("d900bb", "ao'"),     # line-echo ad-lib ("tirao'-ao'-ao'"), Young Miko
]


def main():
    if not os.path.isfile(MASTER):
        sys.exit("master not found: %s (run from project root)" % MASTER)
    with open(MASTER, "r", encoding="utf-8") as f:
        m = json.load(f)

    changes = 0
    for ov in OVERRIDES:
        entry = m.get(ov["key"])
        if entry is None:
            print("SKIP %s (%s): key not in master" % (ov["key"], ov["word"]))
            continue
        if entry.get("word") != ov["word"]:
            print("SKIP %s: expected word %r, found %r — not patching"
                  % (ov["key"], ov["word"], entry.get("word")))
            continue

        if ov.get("lemma") and entry.get("lemma") != ov["lemma"]:
            print("  %-10s lemma %r -> %r" % (ov["word"], entry.get("lemma"), ov["lemma"]))
            entry["lemma"] = ov["lemma"]
            changes += 1

        for flag, val in ov.get("flags", {}).items():
            if entry.get(flag) != val:
                print("  %-10s flag %s -> %r" % (ov["word"], flag, val))
                entry[flag] = val
                changes += 1

        senses = entry.get("senses", [])
        for idx, fields in ov.get("senses", {}).items():
            if idx >= len(senses):
                print("  %-10s SKIP sense[%d]: out of range (have %d)"
                      % (ov["word"], idx, len(senses)))
                continue
            for field, val in fields.items():
                if senses[idx].get(field) != val:
                    print("  %-10s sense[%d].%s %r -> %r"
                          % (ov["word"], idx, field, senses[idx].get(field), val))
                    senses[idx][field] = val
                    changes += 1

    for key, word in COGNATE_STAMPS:
        entry = m.get(key)
        if entry is None:
            print("SKIP %s (%s): key not in master" % (key, word))
            continue
        if entry.get("word") != word:
            print("SKIP %s: expected word %r, found %r — not stamping"
                  % (key, word, entry.get("word")))
            continue
        if entry.get("is_transparent_cognate") is not True:
            print("  %-12s is_transparent_cognate -> True" % word)
            entry["is_transparent_cognate"] = True
            changes += 1

    flag_stamp_lists = [
        (LOANWORD_STAMPS, "is_english_loanword"),
        (PROPERNOUN_STAMPS, "is_propernoun"),
        (NOISE_STAMPS, "is_noise"),
    ]
    for stamps, flag in flag_stamp_lists:
        for key, word in stamps:
            entry = m.get(key)
            if entry is None:
                print("SKIP %s (%s): key not in master" % (key, word))
                continue
            if entry.get("word") != word:
                print("SKIP %s: expected word %r, found %r — not stamping"
                      % (key, word, entry.get("word")))
                continue
            if entry.get(flag) is not True:
                print("  %-12s %s -> True" % (word, flag))
                entry[flag] = True
                changes += 1

    if changes == 0:
        print("No changes (master already patched).")
        return

    # Atomic write, matching the builder's dump format (single line, raw UTF-8).
    tmp = MASTER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, MASTER)
    print("\nApplied %d field change(s) to %s" % (changes, MASTER))


if __name__ == "__main__":
    main()
