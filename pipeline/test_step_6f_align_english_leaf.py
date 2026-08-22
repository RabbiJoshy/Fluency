"""The pieces of the aligned-English corrector that are not the model.

The alignment itself is mBERT and is not tested here; what is tested is
everything around it, because that is where a silent change would move glosses
on 1,500 cards without anyone noticing.
"""

import unittest

from pipeline.step_6f_align_english_leaf import gloss_heads, tuple_of_leaf, _tsv
from pipeline.util_6f_alignment import (
    Alignment, english_stem, find_target_span, tokenize_source, tokenize_target)


class GlossHeadTests(unittest.TestCase):
    def test_single_word_gloss_is_its_own_head(self):
        self.assertEqual(gloss_heads("bank", "NOUN"), {"bank"})

    def test_infinitive_marker_is_not_a_head(self):
        self.assertEqual(gloss_heads("to give", "VERB"), {"give"})

    def test_both_ends_of_a_multiword_gloss_count(self):
        # English is head-initial for `hurry up` and head-final for `good
        # night`, and POS is PHRASE for both, so both ends are accepted.
        self.assertEqual(gloss_heads("give me", "PHRASE"), {"give", "me"})
        self.assertEqual(gloss_heads("good night", "PHRASE"), {"good", "night"})

    def test_trailing_prepositional_phrase_is_dropped(self):
        self.assertEqual(gloss_heads("piece of cake", "NOUN"), {"piece"})

    def test_all_stopword_gloss_has_no_head(self):
        self.assertEqual(gloss_heads("the", "DET"), frozenset())
        self.assertEqual(gloss_heads("", "NOUN"), frozenset())

    def test_heads_are_stemmed_so_a_subtitle_can_match(self):
        # The subtitle says "attorneys"; the gloss says "attorney".
        self.assertIn(english_stem("attorneys"), gloss_heads("attorney", "NOUN"))
        self.assertIn(english_stem("gave"), gloss_heads("to give", "VERB"))


class StemTests(unittest.TestCase):
    def test_irregulars(self):
        for form, lemma in (("gave", "give"), ("went", "go"), ("took", "take"),
                            ("children", "child"), ("men", "man")):
            self.assertEqual(english_stem(form), lemma)

    def test_regular_suffixes(self):
        self.assertEqual(english_stem("hurried"), "hurry")
        self.assertEqual(english_stem("leaving"), "leave")
        self.assertEqual(english_stem("attorneys"), "attorney")

    def test_short_words_are_left_alone(self):
        # Stripping `s` off `is`/`us`/`as` would invent matches.
        for token in ("is", "us", "as", "bus", "gas"):
            self.assertEqual(english_stem(token), token)


class TargetLocationTests(unittest.TestCase):
    def test_finds_the_surface_in_the_sentence(self):
        tokens = tokenize_source("Ahora abre la puerta y dame mis cosas.")
        self.assertEqual(find_target_span(tokens, "dame"), {5})

    def test_falls_back_from_realised_surface_to_lookup_key(self):
        tokens = tokenize_source("Dame el informe.")
        self.assertEqual(find_target_span(tokens, "no-such-surface", "dame"), {0})

    def test_absent_target_is_no_opinion_not_an_error(self):
        tokens = tokenize_source("Hola mundo.")
        self.assertEqual(find_target_span(tokens, "dame"), set())


class AlignmentTests(unittest.TestCase):
    def test_target_words_follow_the_pairs(self):
        al = Alignment(tokenize_source("y dame mis cosas"),
                       tokenize_target("and give me my stuff"),
                       [(0, 0), (1, 1), (1, 2), (3, 4)])
        self.assertEqual(al.target_words_for({1}), ["give", "me"])
        self.assertEqual(al.target_words_for({3}), ["stuff"])
        self.assertEqual(al.target_words_for({2}), [])


class TupleTests(unittest.TestCase):
    def test_tuple_is_headword_and_pos(self):
        self.assertEqual(tuple_of_leaf({"headword": "Dar", "pos": "verb"}),
                         ("dar", "VERB"))

    def test_missing_fields_do_not_raise(self):
        self.assertEqual(tuple_of_leaf({}), ("", ""))


class ReportTests(unittest.TestCase):
    def test_tsv_cell_cannot_break_the_row(self):
        cell = _tsv('he said\t"go"\nnow')
        self.assertNotIn("\t", cell)
        self.assertNotIn('"', cell)
        self.assertNotIn("\n", cell)


if __name__ == "__main__":
    unittest.main()
