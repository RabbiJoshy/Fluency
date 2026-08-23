"""Two bugs found while building the merged MWE inventory, pinned.

Both were invisible in the output until the corpus pass ranked expressions by
frequency and put the bad ones at the top -- which is the argument for the
corpus pass existing at all.

1. `phrases_cache.json` is keyed by headword in BOTH languages, so `play` ->
   "tocar un instrumento" sits beside `nuevo` -> "de nuevo". Ingesting the
   English half put English strings into a Spanish inventory, and `a la` entered
   glossed as "in the style or manner of" and then matched 5,235 Spanish lines.

2. Wiktionary glosses a borrowing by restating it -- `a la` -> "a la; in the
   style or manner of" -- and writes usage prose where SpanishDict writes a
   gloss: `un momento` -> "Used to indicate disagreement or doubt". Neither
   teaches anything on a card.
"""

import unittest

from tool_5d_build_merged_mwes import clean_translation, teachable


class Shape(unittest.TestCase):
    def test_keeps_two_to_five_word_phrases(self):
        for good in ("de nuevo", "de vez en cuando", "no me importa"):
            self.assertTrue(teachable(good), good)

    def test_rejects_single_words_and_sentences(self):
        for bad in ("nuevo", "¿Usted come manzanas?", "él come",
                    "no te des por vencido y mira"):
            self.assertFalse(teachable(bad), bad)

    def test_explicit_subject_pronoun_marks_a_drill_fragment(self):
        # Spanish drops the subject pronoun, so an explicit one is a tell.
        for junk in ("yo nací", "él come", "yo nací en", "yo nací ayer"):
            self.assertFalse(teachable(junk), junk)

    def test_but_not_when_a_subordinator_follows(self):
        # The real pronoun-initial idioms are built this way.
        for good in ("yo que tú", "yo qué sé", "tú mismo"):
            self.assertTrue(teachable(good), good)

    def test_the_residual_gap_is_real_and_left_to_frequency(self):
        # `nací en` has no pronoun to catch it and does occur, so neither the
        # shape gate nor the corpus pass removes it. Recorded, not fixed --
        # the next rule for this class should be measured before it is added.
        self.assertTrue(teachable("nací en"))


class Translation(unittest.TestCase):
    def test_drops_a_segment_that_merely_restates_the_spanish(self):
        self.assertEqual(
            clean_translation("a la; in the style or manner of", "a la"),
            "in the style or manner of")

    def test_drops_wiktionary_usage_prose_entirely(self):
        self.assertIsNone(clean_translation(
            "Used to indicate disagreement or doubt: wait a minute",
            "un momento"))

    def test_drops_structural_wiktionary_notes(self):
        for prose in ("alternative form of en pie", "inflection of dar",
                      "plural of casa"):
            self.assertIsNone(clean_translation(prose, "x y"))

    def test_keeps_an_ordinary_gloss_untouched(self):
        self.assertEqual(clean_translation("again", "de nuevo"), "again")
        self.assertEqual(clean_translation("so that", "para que"), "so that")

    def test_strips_parentheticals_but_keeps_the_gloss(self):
        self.assertEqual(
            clean_translation("ever (at any time)", "alguna vez"), "ever")

    def test_a_gloss_that_is_only_a_restatement_is_dropped(self):
        self.assertIsNone(clean_translation("de nuevo", "de nuevo"))


if __name__ == "__main__":
    unittest.main()
