#!/usr/bin/env python3
"""Tests for util_6e_leaf_selection.

The load-bearing property is the negative one: leaf selection must never move
the tuple. Everything measured on this pipeline -- lemma+POS accuracy, the
calibrator's P(ok_tup), the band cuts on the card -- is a claim about the tuple,
so a stage that could change it would silently invalidate all of them.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from util_6e_leaf_selection import (companion_of, companion_satisfied,
                                    renderable, select_display_leaf)


def leaf(translation, context="", headword="x", pos="VERB"):
    return {"translation": translation, "context": context,
            "headword": headword, "pos": pos}


class CompanionSatisfied(unittest.TestCase):
    def test_no_companion_is_always_satisfied(self):
        # The gate only removes; an unconstrained leaf must never be penalised
        # against a constrained one.
        self.assertTrue(companion_satisfied(None, "cualquier cosa"))

    def test_plain_presence_and_absence(self):
        self.assertTrue(companion_satisfied("de", "Se enamoró de ella"))
        self.assertFalse(companion_satisfied("de", "Es que en mi lista tu eres la favorita"))

    def test_fused_prepositions_count_as_present(self):
        # `contigo` IS con+ti. Without this the gate fires on a correct pick.
        self.assertTrue(companion_satisfied("con", "Yo me caso contigo"))
        self.assertTrue(companion_satisfied("a", "Al carajo las penas"))
        self.assertTrue(companion_satisfied("de", "Salimos del cine"))

    def test_reggaeton_elisions_count_as_present(self):
        # The register this deck is built from elides these constantly, so
        # treating them as absent would fire the gate hardest where it is least
        # entitled to.
        self.assertTrue(companion_satisfied("de", "Contigo me convierto en perro 'e raza"))
        self.assertTrue(companion_satisfied("para", "Vamo' pa' la disco"))

    def test_multiword_companion_needs_every_part(self):
        self.assertTrue(companion_satisfied("a por", "Vino a por el dinero"))
        self.assertFalse(companion_satisfied("a por", "Vino a la casa"))

    def test_companion_of_reads_both_quoting_styles(self):
        self.assertEqual(companion_of({"context": 'to support; used with "por"'}), "por")
        self.assertEqual(companion_of({"context": "used with que"}), "que")
        self.assertIsNone(companion_of({"context": "to smash"}))


class SelectDisplayLeaf(unittest.TestCase):
    def setUp(self):
        # leaves 0,1 are one tuple; leaf 2 is a different tuple entirely.
        self.sids = ["a", "b", "c"]
        self.menu = {"a": leaf("", "to result"),
                     "b": leaf("to fall", "to drop"),
                     "c": leaf("to hang", "", headword="y")}
        self.tid = [0, 0, 1]

    def test_empty_gloss_backs_off_to_a_renderable_sibling(self):
        got = select_display_leaf("Me caí", self.menu, self.sids,
                                  [9.0, 1.0, 8.0], 0, self.tid)
        self.assertEqual(self.sids[got], "b")

    def test_never_leaves_the_winning_tuple(self):
        # leaf "c" scores highest overall and is renderable, but it is a
        # different tuple, so it must not be reachable.
        got = select_display_leaf("Me caí", self.menu, self.sids,
                                  [9.0, 1.0, 99.0], 0, self.tid)
        self.assertNotEqual(self.sids[got], "c")

    def test_renderable_pick_is_left_alone(self):
        got = select_display_leaf("Me caí", self.menu, self.sids,
                                  [1.0, 9.0, 1.0], 1, self.tid)
        self.assertEqual(self.sids[got], "b")

    def test_companion_violation_moves_to_a_clean_sibling(self):
        menu = {"a": leaf("to root for", 'to be associated with; used with "de"'),
                "b": leaf("to be", "used to talk about characteristics")}
        got = select_display_leaf("Es que en mi lista tu eres la favorita",
                                  menu, ["a", "b"], [9.0, 1.0], 0, [0, 0])
        self.assertEqual(got, 1)

    def test_satisfied_companion_is_not_moved(self):
        menu = {"a": leaf("to root for", 'to be associated with; used with "de"'),
                "b": leaf("to be", "used to talk about characteristics")}
        got = select_display_leaf("Yo soy del Barcelona",
                                  menu, ["a", "b"], [9.0, 1.0], 0, [0, 0])
        self.assertEqual(got, 0)

    def test_falls_back_to_the_original_when_the_tuple_offers_nothing(self):
        # Every leaf unrenderable: keep the original rather than dropping a real
        # occurrence or reaching into another tuple.
        menu = {"a": leaf("", "to result"), "b": leaf("", "to matter")}
        got = select_display_leaf("Me caí", menu, ["a", "b"], [9.0, 1.0], 0, [0, 0])
        self.assertEqual(got, 0)

    def test_singleton_tuple_is_untouched(self):
        menu = {"a": leaf("", "to result")}
        self.assertEqual(select_display_leaf("x", menu, ["a"], [1.0], 0, [0]), 0)

    def test_renderable(self):
        self.assertFalse(renderable({"translation": "   "}))
        self.assertFalse(renderable({}))
        self.assertTrue(renderable({"translation": "to fall"}))


if __name__ == "__main__":
    unittest.main()
