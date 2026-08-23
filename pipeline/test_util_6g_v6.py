"""v6 must not change any pick until someone deliberately turns something on.

The whole point of shipping v6 as a reorganisation rather than a new algorithm
is that the defaults reproduce v5 exactly. Two of the three roles are new code
paths over the same numbers, and the third (`commit`) is a genuinely new idea
whose thresholds are unmeasured -- so the tests pin that OFF is really off.

The AUX bug is the reason `apply_vetoes` reports a reason for every drop: that
filter rejected every leaf of an auxiliary, the empty-set fallback fired, and
the stage silently became a no-op with no symptom. A veto that can erase a menu
must say so out loud.
"""

import unittest

from util_6g_v6 import (apply_vetoes, commit, companion_of, glosskey_of,
                        index_mwes, marginals, mwe_candidates, rank, render_at,
                        render_key, tuple_of)


def leaf(sid, pos, gloss, headword, context=""):
    return (sid, {"pos": pos, "translation": gloss,
                  "headword": headword, "context": context})


QUEDAR = [
    leaf("a79", "VERB", "to be left", "quedar", "to be available"),
    leaf("c63", "VERB", "to remain", "quedar", "to be available"),
    leaf("m01", "VERB", "to meet", "quedar", "to arrange to see"),
    leaf("s15", "VERB", "to stay", "quedarse", "to remain in a place"),
]


class Keys(unittest.TestCase):
    def test_glosskey_drops_context_but_keeps_headword(self):
        _, s = QUEDAR[0]
        self.assertEqual(glosskey_of(s), ("VERB", "to be left", "quedar"))
        self.assertEqual(tuple_of(s), ("VERB", "quedar"))

    def test_reflexive_is_a_different_tuple(self):
        # ir/irse and quedar/quedarse are different cards, not near-synonyms.
        self.assertNotEqual(tuple_of(QUEDAR[0][1]), tuple_of(QUEDAR[3][1]))


class Vetoes(unittest.TestCase):
    def test_pos_filter_that_kills_everything_is_ignored_and_reported(self):
        # Exactly the AUX failure: nothing survives, so the menu must stand.
        kept, reasons = apply_vetoes(
            "queda", "Esto se queda conmigo.", QUEDAR,
            example_pos="AUX", pos_compatible=lambda sense_pos, ex: False)
        self.assertEqual(len(kept), len(QUEDAR), "menu was erased")
        self.assertIn("_pos_filter", reasons)

    def test_every_drop_records_a_reason(self):
        kept, reasons = apply_vetoes(
            "queda", "Esto se queda conmigo.", QUEDAR,
            example_pos="VERB",
            pos_compatible=lambda sense_pos, ex: sense_pos == "VERB")
        self.assertEqual(len(kept), len(QUEDAR))       # all are VERB here
        self.assertNotIn("_pos_filter", reasons)

    def test_companion_note_vetoes_when_the_word_is_absent(self):
        cands = [leaf("x1", "VERB", "to support", "ir", 'to back; used with "por"'),
                 leaf("x2", "VERB", "to go", "ir", "to move")]
        self.assertEqual(companion_of(cands[0][1]), "por")
        kept, reasons = apply_vetoes("va", "Ella no va a recordarlo.", cands)
        self.assertEqual([i for i, _ in kept], ["x2"])
        self.assertIn("x1", reasons)

    def test_companion_note_survives_when_the_word_is_present(self):
        cands = [leaf("x1", "VERB", "to support", "ir", 'to back; used with "por"'),
                 leaf("x2", "VERB", "to go", "ir", "to move")]
        kept, _ = apply_vetoes("va", "Va por su equipo.", cands)
        self.assertEqual(len(kept), 2)

    def test_vetoes_do_not_know_about_mwes_at_all(self):
        # MWEs compete as candidates; a veto would delete correct answers on
        # compositional strings like `no tiene`.
        kept, reasons = apply_vetoes(
            "junto", "Lo encontré junto a la galería.", QUEDAR)
        self.assertEqual(len(kept), len(QUEDAR))
        self.assertNotIn("_mwe", reasons)


class Commit(unittest.TestCase):
    def _scores(self):
        return {"a79": 0.80, "c63": 0.79, "m01": 0.60, "s15": 0.55}

    def test_max_marginals_do_not_move_the_pick(self):
        scores = self._scores()
        out = commit(scores, QUEDAR)
        self.assertEqual(out["sense_id"], max(scores, key=scores.get))

    def test_defaults_always_emit_a_leaf(self):
        # Thresholds are unmeasured, so OFF must mean v5 behaviour.
        self.assertEqual(commit(self._scores(), QUEDAR)["level"], "leaf")

    def test_a_tuple_threshold_escalates_rather_than_guessing(self):
        out = commit(self._scores(), QUEDAR, tuple_min=1.0)
        self.assertEqual(out["level"], "escalate")

    def test_backing_off_drops_context_before_it_drops_the_gloss(self):
        out = commit(self._scores(), QUEDAR, leaf_min=1.0)
        self.assertEqual(out["level"], "glosskey")
        payload = render_at("glosskey", QUEDAR[0][1])
        self.assertNotIn("context", payload)
        self.assertEqual(payload["translation"], "to be left")

    def test_sum_pools_mass_and_max_does_not(self):
        # 'to be available' owns two leaves; only sum should notice.
        scores = self._scores()
        mx = marginals(scores, QUEDAR, aggregate="max")
        sm = marginals(scores, QUEDAR, aggregate="sum")
        self.assertLessEqual(max(mx["tuple"].values()), max(sm["tuple"].values()))


class Rank(unittest.TestCase):
    def test_prior_decays_over_the_surviving_order(self):
        flat = rank(QUEDAR, gloss_score=lambda s: 0.5)
        vals = [flat[i] for i, _ in QUEDAR]
        self.assertEqual(vals, sorted(vals, reverse=True))
        self.assertAlmostEqual(vals[0] - vals[1], 0.01, places=6)

    def test_domain_contributes_nothing_by_default(self):
        with_domain = rank(QUEDAR, gloss_score=lambda s: 0.5,
                           domain_score=lambda s: 1.0)
        without = rank(QUEDAR, gloss_score=lambda s: 0.5)
        self.assertEqual(with_domain, without)


MWE_PAYLOAD = {"mwes": {
    "junto a":  {"translations": ["next to", "alongside"], "attach_words": ["junto", "a"],
                 "corpus_freq": 4120, "id": "mwe_aaa", "examples": [{}]},
    "de nuevo": {"translations": ["again"], "attach_words": ["nuevo"],
                 "corpus_freq": 9900, "id": "mwe_bbb", "examples": [{}]},
    "sin par":  {"translations": ["unequalled"], "attach_words": ["par"],
                 "corpus_freq": 0, "id": "mwe_ccc", "examples": []},
}}


class Mwe(unittest.TestCase):
    def setUp(self):
        self.index = index_mwes(MWE_PAYLOAD)

    def test_tier_two_is_never_offered_as_a_candidate(self):
        # corpus_freq 0 means no sentence exists behind it, so it cannot be the
        # answer for an occurrence -- only reference content.
        self.assertNotIn("par", self.index)

    def test_candidate_only_when_the_string_is_present(self):
        got = mwe_candidates("junto", "Lo encontré junto a la galería.", self.index)
        self.assertEqual([s["mwe_expression"] for _, s in got], ["junto a"])
        self.assertEqual(mwe_candidates("junto", "Estaban muy junto.", self.index), [])

    def test_it_carries_the_stable_mwe_id(self):
        (sense_id, _), = mwe_candidates("nuevo", "Perdí el control de nuevo.", self.index)
        self.assertEqual(sense_id, "mwe_bbb")

    def test_it_gets_its_own_tuple_not_the_component_word_s(self):
        (_, sense), = mwe_candidates("nuevo", "Perdí el control de nuevo.", self.index)
        self.assertEqual(tuple_of(sense), ("PHRASE", "de nuevo"))
        self.assertNotEqual(tuple_of(sense), ("ADJ", "nuevo"))

    def test_phrase_pos_survives_the_pos_filter_without_a_special_case(self):
        cands = mwe_candidates("nuevo", "Perdí el control de nuevo.", self.index)
        kept, _ = apply_vetoes("nuevo", "Perdí el control de nuevo.", cands,
                               example_pos="ADJ",
                               pos_compatible=lambda sp, ex: sp == ex)
        self.assertEqual(len(kept), 1, "PHRASE must be orthogonal to the filter")

    def test_leaf_and_mwe_render_symmetrically(self):
        (_, mwe), = mwe_candidates("nuevo", "Perdí el control de nuevo.", self.index)
        leaf_key = render_key(QUEDAR[0][1], "quedar")
        mwe_key = render_key(mwe)
        for key in (leaf_key, mwe_key):
            self.assertTrue(key.startswith('"'))
            self.assertIn("): ", key)
            self.assertIn(" — ", key)
        self.assertTrue(mwe_key.startswith('"de nuevo" (PHRASE): again'))

    def test_it_competes_in_rank_like_any_other_candidate(self):
        cands = list(QUEDAR) + mwe_candidates(
            "nuevo", "Perdí el control de nuevo.", self.index)
        scores = rank(cands, gloss_score=lambda s: 0.9 if s.get("mwe_expression") else 0.5)
        self.assertEqual(max(scores, key=scores.get), "mwe_bbb")


if __name__ == "__main__":
    unittest.main()