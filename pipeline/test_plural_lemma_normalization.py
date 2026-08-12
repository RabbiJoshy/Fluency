import unittest

from pipeline.util_7a_lemma_split import (
    is_regular_plural_form,
    plural_lemma_redirects,
    split_word_assignments,
)
from pipeline.tool_7d_build_derivational_relations import build_relations


class PluralLemmaNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.analyses = [
            {
                "headword": "besitos",
                "senses": {
                    "274": {"pos": "NOUN", "translation": "kisses"},
                },
            },
            {
                "headword": "besito",
                "senses": {
                    "b8c": {"pos": "NOUN", "translation": "kiss"},
                },
            },
        ]

    def test_regular_plural_rules_cover_accents_and_z_to_ces(self):
        self.assertTrue(is_regular_plural_form("besitos", "besito"))
        self.assertTrue(is_regular_plural_form("canciones", "canción"))
        self.assertTrue(is_regular_plural_form("luces", "luz"))
        self.assertFalse(is_regular_plural_form("bonito", "bono"))

    def test_plural_redirect_requires_both_nominal_analyses(self):
        self.assertEqual(
            plural_lemma_redirects(self.analyses),
            {"besitos": "besito"},
        )
        verb_twin = [
            {"headword": "comes", "senses": {"a": {"pos": "VERB"}}},
            {"headword": "come", "senses": {"b": {"pos": "VERB"}}},
        ]
        self.assertEqual(plural_lemma_redirects(verb_twin), {})

    def test_split_preserves_sense_ids_under_one_singular_key(self):
        assignments = {
            "spanishdict-flash-lite": [
                {"sense": "274", "examples": [0]},
                {"sense": "b8c", "examples": [1]},
            ]
        }
        split = split_word_assignments("besitos", self.analyses, assignments)

        self.assertEqual(list(split), ["besitos|besito"])
        items = split["besitos|besito"]["spanishdict-flash-lite"]
        self.assertEqual([item["sense"] for item in items], ["274", "b8c"])

    def test_generated_collision_suffix_resolves_to_current_menu_id(self):
        sense_id = "generated:artist-master:3968ed3bbfcb"
        analyses = [{
            "headword": "poner",
            "senses": {sense_id: {"pos": "VERB", "translation": "to move"}},
        }]
        alias = sense_id + ":5798"
        assignments = {"spanishdict-lexical-g31": [{
            "sense": alias,
            "examples": [1],
            "example_ids": ["seg_example"],
        }]}

        split = split_word_assignments("ponerse", analyses, assignments)

        item = split["ponerse|poner"]["spanishdict-lexical-g31"][0]
        self.assertEqual(item["sense"], sense_id)
        self.assertEqual(item["sense_id_aliases"], [alias])
        self.assertEqual(item["example_ids"], ["seg_example"])

    def test_non_generated_suffix_is_not_folded(self):
        analyses = [{
            "headword": "poner",
            "senses": {"dictionary:abc": {"pos": "VERB"}},
        }]
        assignments = {"model": [{
            "sense": "dictionary:abc:1234",
            "examples": [0],
        }]}

        split = split_word_assignments("x", analyses, assignments)
        self.assertEqual(
            split["x|x"]["model"][0]["sense"],
            "dictionary:abc:1234")


class DerivationalRelationTests(unittest.TestCase):
    def test_semantic_guard_links_besito_but_not_bonito(self):
        master = {
            "1": {"word": "besito", "lemma": "besito", "senses": [
                {"pos": "NOUN", "translation": "kiss"},
            ]},
            "2": {"word": "beso", "lemma": "beso", "senses": [
                {"pos": "NOUN", "translation": "kiss"},
            ]},
            "3": {"word": "bonito", "lemma": "bonito", "senses": [
                {"pos": "ADJ", "translation": "beautiful"},
            ]},
            "4": {"word": "bono", "lemma": "bono", "senses": [
                {"pos": "NOUN", "translation": "bond"},
            ]},
        }

        relations = build_relations(master, [], {"include": {}, "exclude": []})

        self.assertEqual(relations["besito"]["base_lemma"], "beso")
        self.assertNotIn("bonito", relations)

    def test_curated_override_can_correct_an_orthographic_base(self):
        master = {
            "1": {"word": "placita", "lemma": "placita", "senses": []},
            "2": {"word": "plaza", "lemma": "plaza", "senses": []},
        }
        curation = {"include": {
            "placita": {"base_lemma": "plaza", "relation": "diminutive"},
        }, "exclude": []}

        relations = build_relations(master, [], curation)

        self.assertEqual(relations["placita"], {
            "base_lemma": "plaza",
            "relation": "diminutive",
            "source": "curated",
        })


if __name__ == "__main__":
    unittest.main()
