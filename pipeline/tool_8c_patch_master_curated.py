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
        "senses": {0: {"translation": "boo, baby"}},
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
            [(0, {"pos": "VERB", "translation": "are (‘tán = están)",
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
        "key": "d53676", "word": "squirteé", "lemma": "squirtear", "flags": {},
        # Spanish-language gap-fill gloss; lemma was the English stem "squirt".
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
        "senses": {0: {"translation": "all (toa’ = todas)",
                       "context": "colloquial"}},
    },
    {
        "key": "548cb0", "word": "zeta", "lemma": None, "flags": {},
        "senses": {0: {"translation": "a \"Z\" (car)", "context": ""}},
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
     "senses": {0: {"translation": "to break (records)",
                    "context": "batir"}}},
    # --- 2026-07-05 verb-lemma repairs: surface forms (or English stems)
    # stored as the lemma, so conjugation/morphology lookups all missed.
    # Lemma-only edits (in place); glosses were already correct. ---
    {"key": "bfcaa5", "word": "tar", "lemma": "estar", "flags": {}, "senses": {}},
    {"key": "0d5c7c", "word": "tas", "lemma": "estar", "flags": {}, "senses": {}},
    {"key": "1c1083", "word": "vo", "lemma": "ir", "flags": {}, "senses": {}},
    {"key": "aaa994", "word": "perriabas", "lemma": "perrear", "flags": {}, "senses": {}},
    {"key": "cb8838", "word": "joseando", "lemma": "josear", "flags": {}, "senses": {}},
    {"key": "29be5b", "word": "enchuló", "lemma": "enchular", "flags": {}, "senses": {}},
    {"key": "4ba1f9", "word": "fronteando", "lemma": "frontear", "flags": {}, "senses": {}},
    {"key": "77a518", "word": "frontearme", "lemma": "frontear", "flags": {}, "senses": {}},
    {"key": "6f372f", "word": "fronteándome", "lemma": "frontear", "flags": {}, "senses": {}},
    {"key": "517c94", "word": "frontean", "lemma": "frontear", "flags": {}, "senses": {}},
    {"key": "59b9c0", "word": "frontee", "lemma": "frontear", "flags": {}, "senses": {}},
    {"key": "9691f9", "word": "frontearle", "lemma": "frontear", "flags": {}, "senses": {}},
    {"key": "3cf468", "word": "juqueó", "lemma": "juquear", "flags": {}, "senses": {}},
    {"key": "538cf5", "word": "cachamos", "lemma": "cachar", "flags": {}, "senses": {}},
    {"key": "8174f1", "word": "fantasmeas", "lemma": "fantasmear", "flags": {}, "senses": {}},
    {"key": "d4768a", "word": "descontrolo", "lemma": "descontrolar", "flags": {}, "senses": {}},
    {"key": "4ebcac", "word": "posteados", "lemma": "postear", "flags": {}, "senses": {}},
    {"key": "cc6c98", "word": "wheeliando", "lemma": "wheeliar", "flags": {}, "senses": {}},
    {"key": "ad1ff6", "word": "zumba", "lemma": "zumbar", "flags": {}, "senses": {}},
    {"key": "0f69d2", "word": "dárselo", "lemma": "dar", "flags": {}, "senses": {}},
    # Non-Spanish code-switch lines (French feature + Italian) — is_english
    # is the unconditional hide flag for foreign-language words.
    {"key": "ade610", "word": "jouais", "lemma": None,
     "flags": {"is_english": True}, "senses": {}},
    {"key": "b4a3fe", "word": "caressais", "lemma": None,
     "flags": {"is_english": True}, "senses": {}},
    {"key": "40242f", "word": "capisci", "lemma": None,
     "flags": {"is_english": True}, "senses": {}},
    # --- 2026-07-05 verbose_def sweep: Gemini sentence-definitions and
    # dictionary artifacts shortened to flashcard glosses, in place. ---
    {"key": "593c41", "word": "amén", "lemma": None, "flags": {},
     "senses": {0: {"translation": "amen"}}},
    {"key": "19de0f", "word": "atreve", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to dare"}}},
    {"key": "e027ed", "word": "atreves", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to dare"}}},
    {"key": "21a56e", "word": "beibe", "lemma": None, "flags": {},
     "senses": {0: {"translation": "baby (endearment)"}}},
    {"key": "584ab2", "word": "bellaquita", "lemma": None, "flags": {},
     "senses": {0: {"translation": "bad girl, naughty girl"}}},
    {"key": "2f9717", "word": "bendecida", "lemma": None, "flags": {},
     "senses": {0: {"translation": "blessed"}}},
    {"key": "474b61", "word": "bichotes", "lemma": None, "flags": {},
     "senses": {0: {"translation": "drug kingpin, big shot"}}},
    {"key": "841c24", "word": "blunes", "lemma": None, "flags": {},
     "senses": {0: {"translation": "blunts"}}},
    {"key": "538cf5", "word": "cachamos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to catch, to score"}}},
    {"key": "e31486", "word": "caigas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to fall", "context": ""}}},
    {"key": "50313c", "word": "callaítas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "quiet, low-key (calladitas)"}}},
    {"key": "f059b6", "word": "campeonatos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "championship"}}},
    {"key": "e18d4e", "word": "cana", "lemma": None, "flags": {},
     "senses": {0: {"translation": "gray hair"}}},
    {"key": "13bc19", "word": "capea", "lemma": None, "flags": {},
     # PR slang capear = pick up drugs, not the bullfighting cape pass.
     "senses": {0: {"translation": "to score, to pick up (slang)"}}},
    {"key": "69d206", "word": "caripelao", "lemma": None, "flags": {},
     "senses": {0: {"translation": "shameless person"}}},
    {"key": "c28212", "word": "chamaquita", "lemma": None, "flags": {},
     "senses": {0: {"translation": "young girl"}}},
    {"key": "dfb1ae", "word": "chamaquito", "lemma": None, "flags": {},
     "senses": {0: {"translation": "young boy, kid"}}},
    {"key": "9b8edb", "word": "colmadón", "lemma": None, "flags": {},
     "senses": {0: {"translation": "big corner store"}}},
    {"key": "4cad6d", "word": "curvas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "curves"}}},
    {"key": "ab1993", "word": "curé", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to heal"}}},
    {"key": "1092d9", "word": "doña", "lemma": None, "flags": {},
     "senses": {0: {"translation": "ma'am, lady"}}},
    {"key": "29be5b", "word": "enchuló", "lemma": "enchular", "flags": {},
     "senses": {0: {"translation": "to make fall in love (slang)"}}},
    {"key": "833c8b", "word": "ere", "lemma": None, "flags": {},
     "senses": {0: {"translation": "you are (ere' = eres)"}}},
    {"key": "66b2f6", "word": "esnúa", "lemma": None, "flags": {},
     "senses": {0: {"translation": "naked (desnuda)"}}},
    {"key": "bd4b60", "word": "espejos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "mirror"}}},
    {"key": "8174f1", "word": "fantasmeas", "lemma": "fantasmear", "flags": {},
     "senses": {0: {"translation": "to front, act fake"}}},
    {"key": "5f7140", "word": "fantasmeo", "lemma": None, "flags": {},
     "senses": {0: {"translation": "fronting, fakery"}}},
    {"key": "5cf199", "word": "fav", "lemma": None, "flags": {},
     "senses": {0: {"translation": "favor"}}},
    {"key": "517c94", "word": "frontean", "lemma": "frontear", "flags": {},
     "senses": {0: {"translation": "to front, show off"}}},
    {"key": "4ba1f9", "word": "fronteando", "lemma": "frontear", "flags": {},
     "senses": {0: {"translation": "to front, show off"}}},
    {"key": "6f372f", "word": "fronteándome", "lemma": "frontear", "flags": {},
     "senses": {0: {"translation": "to front, show off"}}},
    {"key": "cb8838", "word": "joseando", "lemma": "josear", "flags": {},
     "senses": {0: {"translation": "to hustle (josear)"}}},
    {"key": "1490a7", "word": "labia", "lemma": None, "flags": {},
     "senses": {0: {"translation": "smooth talk"}}},
    {"key": "fdaeb1", "word": "latina", "lemma": None, "flags": {},
     "senses": {0: {"translation": "Latina woman"}}},
    {"key": "23c797", "word": "latino", "lemma": None, "flags": {},
     "senses": {0: {"translation": "Latino, Latin American"}}},
    {"key": "5be41c", "word": "males", "lemma": None, "flags": {},
     "senses": {0: {"translation": "troubles, woes"}}},
    {"key": "7e3f3f", "word": "malianteos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "hustling, thug life"}}},
    {"key": "ee072f", "word": "mamas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to suck (vulgar)"}}},
    {"key": "dbbbea", "word": "mame", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to suck (vulgar)"}}},
    {"key": "3a9b6c", "word": "mara", "lemma": None, "flags": {},
     "senses": {0: {"translation": "gang"}}},
    {"key": "d65728", "word": "mari", "lemma": None, "flags": {},
     "senses": {0: {"translation": "weed (marijuana)"}}},
    {"key": "a63d28", "word": "mecha", "lemma": None, "flags": {},
     "senses": {0: {"translation": "fuse, wick",
                    "context": "corto de mecha = short-tempered"}}},
    {"key": "91f546", "word": "nano", "lemma": "nano", "flags": {},
     # Vocative "Nano, ya" — term of address, not a diminutive suffix.
     "senses": {0: {"pos": "NOUN", "translation": "bro, buddy (address)", "context": ""}}},
    {"key": "a482e0", "word": "noviecito", "lemma": None, "flags": {},
     "senses": {0: {"translation": "boyfriend (diminutive)"}}},
    {"key": "f4a825", "word": "pai", "lemma": None, "flags": {},
     "senses": {0: {"translation": "dad (slang)"}}},
    {"key": "a924e2", "word": "pal", "lemma": None, "flags": {},
     "senses": {0: {"translation": "for the (pa'l = para el)"}}},
    {"key": "7e2226", "word": "pali", "lemma": None, "flags": {},
     "senses": {0: {"translation": "pill (slang)"}}},
    {"key": "e0c614", "word": "perfumito", "lemma": None, "flags": {},
     "senses": {0: {"translation": "perfume (diminutive)"}}},
    {"key": "aaa994", "word": "perriabas", "lemma": "perrear", "flags": {},
     "senses": {0: {"translation": "to dance perreo"}}},
    {"key": "f5f1e6", "word": "pikete", "lemma": None, "flags": {},
     "senses": {0: {"translation": "swagger, style"}}},
    {"key": "1eab01", "word": "ponderosa", "lemma": None, "flags": {},
     "senses": {0: {"translation": "ponderosa pine (weed metaphor)"}}},
    {"key": "fb6b49", "word": "pos", "lemma": "por", "flags": {},
     # Corpus lines are all "po'" = por ("les pasé po' encima").
     "senses": {0: {"pos": "ADP", "translation": "por (clipped: po')", "context": ""}}},
    {"key": "ff88b7", "word": "posar", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to pose"}}},
    {"key": "b38355", "word": "pose", "lemma": None, "flags": {},
     "senses": {0: {"translation": "pose"}}},
    {"key": "4ebcac", "word": "posteados", "lemma": "postear", "flags": {},
     "senses": {0: {"translation": "posted up, hanging out"}}},
    {"key": "57aa81", "word": "pre", "lemma": "pre", "flags": {},
     # "desde el pre" = the pre-game, not a prefix.
     "senses": {0: {"pos": "NOUN", "translation": "pre-game (el pre)", "context": ""}}},
    {"key": "37d185", "word": "prendida", "lemma": None, "flags": {},
     "senses": {0: {"translation": "lit, fired up"}}},
    {"key": "37cbc3", "word": "probé", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to try, to taste"}}},
    {"key": "6a4343", "word": "puertorriqueños", "lemma": None, "flags": {},
     "senses": {0: {"translation": "Puerto Rican"}}},
    {"key": "32c8b8", "word": "quemados", "lemma": None, "flags": {},
     "senses": {0: {"translation": "burned, burnt out"}}},
    {"key": "7399fd", "word": "raja", "lemma": None, "flags": {},
     "senses": {0: {"translation": "slit, crack"}}},
    {"key": "eadfe0", "word": "revueltas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "mixed up, all together"}}},
    {"key": "de68e6", "word": "roles", "lemma": None, "flags": {},
     # "el Role'" = a Rolex.
     "senses": {0: {"translation": "Rolex (Role')"}}},
    {"key": "f4904b", "word": "rosario", "lemma": None, "flags": {},
     "senses": {0: {"translation": "rosary"}}},
    {"key": "e62ada", "word": "rulay", "lemma": None, "flags": {},
     "senses": {0: {"translation": "living it up, chilling"}}},
    {"key": "e66e3c", "word": "rumba", "lemma": None, "flags": {},
     "senses": {0: {"translation": "party"}}},
    {"key": "6a6470", "word": "serie", "lemma": None, "flags": {},
     "senses": {0: {"translation": "series, TV show"}}},
    {"key": "4a25b9", "word": "sudaítas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "sweaty (sudaditas)"}}},
    {"key": "0d5c7c", "word": "tas", "lemma": "estar", "flags": {},
     "senses": {0: {"translation": "you are ('tás = estás)"}}},
    {"key": "f99fa9", "word": "tetotas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "big boobs (vulgar)"}}},
    {"key": "fe7a73", "word": "tiguere", "lemma": None, "flags": {},
     "senses": {0: {"translation": "hustler, street-smart guy"}}},
    {"key": "e17ef3", "word": "toditas", "lemma": None, "flags": {},
     "senses": {0: {"translation": "all of them (fem.)"}}},
    {"key": "240c23", "word": "toto", "lemma": None, "flags": {},
     "senses": {0: {"translation": "pussy (vulgar)"}}},
    {"key": "5cf290", "word": "trajecito", "lemma": None, "flags": {},
     "senses": {0: {"translation": "little outfit"}}},
    {"key": "525323", "word": "trapxficante", "lemma": None, "flags": {},
     "senses": {0: {"translation": "trap-dealer (wordplay)"}}},
    {"key": "8c40b6", "word": "tumbamos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "to knock down"}}},
    {"key": "a32bbf", "word": "uni", "lemma": None, "flags": {},
     "senses": {0: {"translation": "uni, college"}}},
    {"key": "d439c9", "word": "vídeos", "lemma": None, "flags": {},
     "senses": {0: {"translation": "video"}}},
    {"key": "1c1083", "word": "vo", "lemma": "ir", "flags": {},
     "senses": {0: {"translation": "I'm gonna (vo'a = voy a)"}}},
    {"key": "cc6c98", "word": "wheeliando", "lemma": "wheeliar", "flags": {},
     "senses": {0: {"translation": "doing wheelies, cruising"}}},
    {"key": "ba6e23", "word": "zona", "lemma": None, "flags": {},
     "senses": {0: {"translation": "zone, area"}}},
    {"key": "91e258", "word": "brava", "lemma": None, "flags": {},
     "senses": {0: {"translation": "Brava (San Juan club)"}}},
    {"key": "1a8f51", "word": "película", "lemma": None, "flags": {},
     # YM slang: "la película" = the scene / what's going on.
     "senses": {0: {"translation": "the scene, the situation", "context": "slang"}}},
    # --- 2026-07-07 Phase-0 finds: reverse-direction SpanishDict lookups
    # surfaced by bench_wikt_sense_coverage (English headword collisions:
    # sea, vine, mire, tas; plus wrong-paradigm lemmas). Same in-place
    # pattern as 'tán': rewrite sense 0, blank extras with pos=X. ---
    {"key": "612672", "word": "sea", "lemma": "ser", "flags": {},
     # "sea lo que sea" = subjunctive of ser, not English "sea"->mar.
     "senses": {0: {"pos": "VERB", "translation": "be (subjunctive of ser)",
                    "context": ""},
                1: {"pos": "X", "translation": "", "context": ""}}},
    {"key": "6dc1f9", "word": "vine", "lemma": "venir", "flags": {},
     # "vine" = I came (venir), not English "vine"->vid/enredadera/parra.
     "senses": {0: {"pos": "VERB", "translation": "to come", "context": ""},
                1: {"pos": "X", "translation": "", "context": ""},
                2: {"pos": "X", "translation": "", "context": ""}}},
    {"key": "247799", "word": "mire", "lemma": "mirar", "flags": {},
     # mirar subjunctive, not English "mire"->envolver en.
     "senses": {0: {"pos": "VERB", "translation": "to look at", "context": ""}}},
    {"key": "427258", "word": "tás", "lemma": "estar", "flags": {},
     # "'tás" = estás, not the jeweler's anvil (English "tas").
     "senses": {0: {"pos": "VERB", "translation": "you are (’tás = estás)",
                    "context": "colloquial contraction"}}},
    {"key": "e07d71", "word": "mía", "lemma": "mío", "flags": {},
     # possessive "mine", not miar "to miaow".
     "senses": {0: {"pos": "PRON", "translation": "mine", "context": ""}}},
    {"key": "794249", "word": "mía", "lemma": "mío", "flags": {}, "senses": {}},
    {"key": "26e43b", "word": "besos", "lemma": None, "flags": {},
     # "collision" artifact; sense 1 is already "kiss" — keep one.
     "senses": {0: {"translation": "kiss", "context": ""},
                1: {"pos": "X", "translation": "", "context": ""}}},
    {"key": "890250", "word": "besos", "lemma": "beso", "flags": {}, "senses": {}},
    # Interjections/onomatopoeia from the verbose_def sweep — hidden by the
    # default-on noise filter (is_interjection).
    {"key": "95f6c2", "word": "auch", "lemma": None,
     "flags": {"is_interjection": True}, "senses": {}},
    {"key": "d9a262", "word": "ea", "lemma": None,
     "flags": {"is_interjection": True}, "senses": {}},
    {"key": "7889b3", "word": "wuff", "lemma": None,
     "flags": {"is_interjection": True}, "senses": {}},
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
    # --- 2026-07-12 wikt-deck audit: carried over from live-deck flags for
    # the _wikt parallel deck (deck_quality_candidates_wikt.json review, 194
    # candidates vs the fully-curated live deck). Keyed to the WIKT master
    # (Artists/spanish/vocabulary_master_wikt.json); most of these words share
    # the same hex key in the live master too (word|lemma hash is identity-based)
    # and are already True there via the live deck's own flag layer, so replaying
    # this block against the live master with the default --master is a harmless
    # no-op re-affirmation. "dj" is wikt-only (absent from live -> SKIP: key not
    # in master). See VERDICTS in the 2026-07-12 wikt curation session.
    {"key": "05365c", "word": "break", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "23dd80", "word": "bus", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "b51186", "word": "chat", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "fdc1a7", "word": "clóset", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "80a058", "word": "cool", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "013290", "word": "crush", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "f4f2f7", "word": "curry", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "22bb54", "word": "dealer", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "528537", "word": "dj", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "9cb252", "word": "down", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "0293af", "word": "feedback", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "ce5f5f", "word": "flow", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "e53f3d", "word": "gang", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "3f3f55", "word": "hey", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "1695eb", "word": "hobby", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "2d49a4", "word": "lady", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "15ddf0", "word": "like", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "903961", "word": "link", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "6ea00d", "word": "lobby", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "8d4797", "word": "mall", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "72463f", "word": "man", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "f3af27", "word": "meme", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "879ffa", "word": "navy", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "a8386a", "word": "okey", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "7eb594", "word": "out", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "36c983", "word": "pac", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "9ef989", "word": "paper", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "83fd2f", "word": "party", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "ee5697", "word": "piercing", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "0246f2", "word": "podcast", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "162de5", "word": "remix", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "68ba31", "word": "ring", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "f789bf", "word": "rookie", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "185503", "word": "sorry", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "fda931", "word": "stop", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "16c7bd", "word": "sunroof", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "691c05", "word": "superstar", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "8bf3a9", "word": "swing", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "396e29", "word": "top", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "ff924b", "word": "tory", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "aaeef8", "word": "trap", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "0e406f", "word": "trip", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "e3be50", "word": "vip", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    {"key": "068a6f", "word": "wiki", "lemma": None,
     "flags": {"is_english_loanword": True}, "senses": {}},
    # Both is_english_loanword AND is_transparent_cognate per verdict.
    {"key": "1a71de", "word": "gym", "lemma": None,
     "flags": {"is_english_loanword": True, "is_transparent_cognate": True},
     "senses": {}},
    {"key": "79d49a", "word": "jet", "lemma": None,
     "flags": {"is_english_loanword": True, "is_transparent_cognate": True},
     "senses": {}},
    # is_transparent_cognate. ("gas", key 4c30db, is already covered by the
    # existing COGNATE_STAMPS entry below -- not duplicated here.)
    {"key": "43246d", "word": "químico", "lemma": None,
     "flags": {"is_transparent_cognate": True}, "senses": {}},
    # is_propernoun. These three exist in the WIKT master with lemma==word;
    # the LIVE master keys the same surface words under different lemmas
    # (chicos/gandir/luir), so the live-master hex key would be wrong here --
    # these are wikt-specific keys and are absent from live (harmless SKIP).
    {"key": "82c04e", "word": "caicos", "lemma": None,  # live lemma=chicos, different key
     "flags": {"is_propernoun": True}, "senses": {}},
    {"key": "52292d", "word": "ganda", "lemma": None,  # live lemma=gandir, different key
     "flags": {"is_propernoun": True}, "senses": {}},
    {"key": "a7e29a", "word": "luían", "lemma": None,  # live lemma=luir, different key
     "flags": {"is_propernoun": True}, "senses": {}},
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
    ("8f6d3c", "diesel"),     # sour diesel / Vin Diesel
    ("76dd7f", "safari"),
    ("f5da8c", "portobello"),
    ("b38355", "pose"),       # gloss shortened to "pose" above -> transparent
    ("593c41", "amén"),       # amén/amen (accent-insensitive match)
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
    ("1aff73", "do"),        # "what you can do with my body"
    ("89ceb1", "switche"),   # "nos vamos al switche" — English switch
    ("1e1175", "rulin"),     # "nos fuimos rulin" — English rulin'/rolling
    ("a18e27", "strippers"), # plural of already-stamped stripper
    ("0a5e61", "men"),       # PR address term from English "man"
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
    ("18ef23", "tatís"),      # Fernando Tatís Jr. (glossed "to walk so many"!)
    ("f38ee0", "play"),       # "jugando Play" = PlayStation
    ("8a16b9", "laramercy"),  # gang/crew name
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
    ("03651b", "lego"),    # "Lego, lego, lego" ad-lib
    ("87a68a", "chi"),     # truncated fragment ("me la chi-")
    ("22fa75", "rrear"),   # stutter fragment of "(pe)rrear"
    ("4930fb", "opo"),     # truncated "oportunidad" ("Perdiste la opo-")
]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Apply curated no-rerun patches to a master")
    ap.add_argument("--master", default=MASTER,
                    help="Master file to patch (default: the live master). Point at "
                         "vocabulary_master_wikt.json for the parallel Wiktionary deck.")
    ap.add_argument("--flags-only", action="store_true",
                    help="Apply only flag stamps (loanword/propernoun/noise/cognate/"
                         "interjection) and lemma corrections — skip per-sense edits. "
                         "REQUIRED for a parallel master whose sense menus come from a "
                         "different source: sense indexes point at different senses "
                         "there, so positional sense edits would corrupt them.")
    args = ap.parse_args()
    master_path = args.master

    if not os.path.isfile(master_path):
        sys.exit("master not found: %s (run from project root)" % master_path)
    with open(master_path, "r", encoding="utf-8") as f:
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

        if args.flags_only:
            continue
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
    tmp = master_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, master_path)
    print("\nApplied %d field change(s) to %s" % (changes, master_path))


if __name__ == "__main__":
    main()
