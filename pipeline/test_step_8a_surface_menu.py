"""The seam where a card key and a dictionary headword disagree.

SpanishDict files `dame` as its own PHRASE entry ("give me"), and step_7a routes
that form onto its verb lemma, so the card key is `dame|dar` while the only
analysis under the surface says `dame`. Reading the menu strictly by lemma finds
nothing and the card renders an empty meaning even though the classifier decided
against that very analysis. Reading it loosely re-introduces the `analyses[0]`
fallback removed in 2026-04, under which `a|a` inherited `avoir`'s senses.

Both halves are tested here because the fix is the narrow band between them.
"""

import unittest

from pipeline.step_8a_assemble_vocabulary import get_senses_for_lemma


def _analysis(headword, sense_id, translation, pos="PHRASE"):
    return {
        "headword": headword,
        "senses": {sense_id: {"pos": pos, "translation": translation,
                              "headword": headword}},
    }


# `dame` as the menu actually holds it: one analysis, headword == the surface.
DAME_MENU = {"dame": [_analysis("dame", "1fb", "give me")]}

# The regression the strict rule exists to prevent: the only analysis under
# surface `a` belongs to a different headword entirely.
AVOIR_MENU = {"a": [_analysis("avoir", "abc", "to have", pos="VERB")]}


class SurfaceHeadwordMenuTests(unittest.TestCase):
    def test_lemma_match_is_unaffected(self):
        menu = {"doy": [_analysis("dar", "662", "to give", pos="VERB")]}
        senses, sense_map = get_senses_for_lemma(menu, "doy", "dar", True)
        self.assertEqual([s["translation"] for s in senses], ["to give"])
        self.assertEqual(list(sense_map), ["662"])

    def test_surface_headword_is_ignored_by_default(self):
        senses, sense_map = get_senses_for_lemma(DAME_MENU, "dame", "dar", True)
        self.assertEqual(senses, [])
        self.assertEqual(sense_map, {})

    def test_surface_headword_is_read_when_allowed(self):
        senses, sense_map = get_senses_for_lemma(
            DAME_MENU, "dame", "dar", True, allow_surface_headword=True)
        self.assertEqual([s["translation"] for s in senses], ["give me"])
        self.assertEqual(list(sense_map), ["1fb"])

    def test_allowing_it_does_not_restore_the_analyses_zero_fallback(self):
        # `avoir` is not the surface, so no amount of permission reaches it.
        senses, sense_map = get_senses_for_lemma(
            AVOIR_MENU, "a", "a", True, allow_surface_headword=True)
        self.assertEqual(senses, [])
        self.assertEqual(sense_map, {})

    def test_lemma_match_wins_over_the_surface_analysis(self):
        # `dimos` has both: its own phrase entry and a `dar` analysis. The lemma
        # the card key names decides, and the surface entry is never consulted.
        menu = {"dimos": [_analysis("dimos", "aaa", "we gave"),
                          _analysis("dar", "662", "to give", pos="VERB")]}
        senses, _ = get_senses_for_lemma(
            menu, "dimos", "dar", True, allow_surface_headword=True)
        self.assertEqual([s["translation"] for s in senses], ["to give"])


if __name__ == "__main__":
    unittest.main()
