import unittest
from collections import Counter

from pipeline.artist.step_2a_count_words import (
    _detect_construction_templates,
    _pool_construction_families,
    _remove_construction_shadowed_hits,
    build_counts_and_candidates,
    parse_section_vocalists,
)


class CountWordsDedupTests(unittest.TestCase):
    def test_repeated_line_counts_once_per_song(self):
        songs = [
            {
                "id": "song-a",
                "title": "A",
                "lyrics": (
                    "Lyrics\n"
                    "Hola mundo uno dos tres\n"
                    "HOLA, mundo uno dos tres\n"
                    "Adiós mundo uno dos tres\n"
                ),
            },
            {
                "id": "song-b",
                "title": "B",
                "lyrics": "Lyrics\nHola mundo uno dos tres\n",
            },
        ]

        counts, _candidates, stats, ngrams, word_songs = build_counts_and_candidates(songs)

        # The normalized "hola mundo..." line counts once in each song.
        self.assertEqual(counts["hola"], 2)
        # Song A's distinct "adiós..." line remains an additional count.
        self.assertEqual(counts["mundo"], 3)
        self.assertEqual(stats["duplicate_lines"], 1)
        self.assertEqual(ngrams["unigrams"]["hola"], 2)
        self.assertEqual(ngrams["counts"][2]["hola mundo"], 2)
        self.assertEqual(ngrams["songs"]["hola mundo"], {"song-a", "song-b"})
        self.assertEqual(len(ngrams["lines"]["hola mundo"]), 2)
        self.assertEqual(
            {example["id"] for example in ngrams["examples"]["hola mundo"]},
            {"song-a:1", "song-b:1"},
        )
        # Full-corpus song provenance is not limited by retained examples and
        # counts a repeated chorus only once within its song.
        self.assertEqual(word_songs["hola"], {"song-a", "song-b"})
        self.assertEqual(word_songs["adiós"], {"song-a"})

    def test_named_section_vocalists_are_attached_without_changing_line_ids(self):
        self.assertEqual(
            parse_section_vocalists("[Verso: Bad Bunny feat. Jhay Cortez]"),
            ["Bad Bunny", "Jhay Cortez"],
        )
        songs = [{
            "id": "duet",
            "title": "Duet",
            "lyrics": (
                "Lyrics\n"
                "[Verso 1: Bad Bunny & Rosalía]\n"
                "Hola mundo uno dos tres\n"
                "[Coro]\n"
                "Adiós mundo uno dos tres\n"
            ),
        }]

        _counts, candidates, _stats, _ngrams, _songs = build_counts_and_candidates(
            songs, primary_artist="Bad Bunny")

        named = next(candidate for candidate in candidates["hola"]
                     if candidate["line_text"].startswith("Hola"))
        self.assertEqual(named["line_no"], 1)
        self.assertEqual(named["vocalists"], ["Bad Bunny", "Rosalía"])
        self.assertTrue(named["sung_by_primary_artist"])
        generic = next(candidate for candidate in candidates["adiós"]
                       if candidate["line_text"].startswith("Adiós"))
        self.assertEqual(generic["line_no"], 2)
        self.assertNotIn("vocalists", generic)

    def test_mwe_evidence_retains_collapsed_elision_surface(self):
        songs = [{
            "id": "elided",
            "title": "Elided",
            "lyrics": "Lyrics\nYo me vo'a quedar aquí siempre\n",
        }]

        _counts, _candidates, _stats, ngrams, _songs = build_counts_and_candidates(
            songs, mwe_map={"vo'a": ["voy", "a"]})

        example = ngrams["examples"]["me voy a"][0]
        self.assertEqual(example["matched_variant"], "me voy a")
        self.assertEqual(example["matched_surface"], "me vo'a")

    def test_mwe_evidence_retains_leading_aphesis_surface(self):
        songs = [{
            "id": "aphesis",
            "title": "Aphesis",
            "lyrics": "Lyrics\n'Toy puesto para ti desde siempre\n",
        }]

        _counts, _candidates, _stats, ngrams, _songs = build_counts_and_candidates(songs)

        example = ngrams["examples"]["estoy puesto"][0]
        self.assertEqual(example["matched_variant"], "estoy puesto")
        self.assertEqual(example["matched_surface"].lower(), "'toy puesto")

    def test_morphological_expression_family_uses_unique_line_union(self):
        confirmed = [
            {
                "expression": "sé que",
                "translation": "I know that",
                "count": 2,
                "occurrence_count": 2,
                "examples": [{"id": "a:1", "line": "Yo sé que vienes"}],
            },
            {
                "expression": "yo sé que",
                "translation": "I know that",
                "count": 2,
                "occurrence_count": 2,
                "examples": [
                    {"id": "a:1", "line": "Yo sé que vienes"},
                    {"id": "b:1", "line": "Yo sé que no"},
                ],
            },
        ]
        evidence = {
            "lines": {
                "sé que": {("a", "yo sé que vienes"), ("c", "sé que sí")},
                "yo sé que": {("a", "yo sé que vienes"), ("b", "yo sé que no")},
            },
            "songs": {
                "sé que": {"a", "c"},
                "yo sé que": {"a", "b"},
            },
        }

        pooled = _pool_construction_families(
            confirmed,
            {"sé que": "saber que", "yo sé que": "saber que"},
            evidence,
        )

        self.assertEqual(len(pooled), 1)
        family = pooled[0]
        self.assertEqual(family["family"], "saber que")
        self.assertEqual(family["count"], 3)
        self.assertEqual(family["num_songs"], 3)
        self.assertEqual(family["occurrence_count"], 4)
        self.assertEqual(set(family["variants"]), {"sé que", "yo sé que"})
        self.assertEqual(len(family["examples"]), 2)

    def test_ir_a_template_requires_a_following_infinitive(self):
        ngram_data = {
            "counts": {
                3: Counter({
                    "voy a comer": 3,
                    "voy a casa": 9,
                    "vas a bailar": 2,
                    "voy a caga'": 1,
                }),
            },
            "lines": {
                "voy a comer": {("a", "voy a comer")},
                "voy a casa": {("x", "voy a casa")},
                "vas a bailar": {
                    ("b", "vas a bailar"),
                    ("c", "vas a bailar mañana"),
                },
                "voy a caga'": {("d", "voy a caga'")},
            },
            "songs": {
                "voy a comer": {"a"},
                "voy a casa": {"x"},
                "vas a bailar": {"b", "c"},
                "voy a caga'": {"d"},
            },
        }
        morphology = {
            "voy": [{"lemma": "ir", "mood": "indicativo"}],
            "vas": [{"lemma": "ir", "mood": "indicativo"}],
            "comer": [{"lemma": "comer", "mood": "infinitivo"}],
            "bailar": [{"lemma": "bailar", "mood": "infinitivo"}],
            "casa": [{"lemma": "casar", "mood": "indicativo"}],
            "cagar": [{"lemma": "cagar", "mood": "infinitivo"}],
        }
        templates = [{
            "family": "ir a + infinitive",
            "kind": "verb_link_nonfinite",
            "lemma": "ir",
            "link": "a",
            "nonfinite": "infinitivo",
            "translation": "go or be going to + verb",
        }]

        constructions, covered = _detect_construction_templates(
            ngram_data,
            templates,
            morphology,
            lambda expression: [{
                "id": expression,
                "line": expression,
                "matched_variant": expression,
                "matched_surface": expression,
            }],
        )

        self.assertEqual(len(constructions), 1)
        construction = constructions[0]
        self.assertEqual(construction["count"], 4)
        self.assertEqual(construction["num_songs"], 4)
        self.assertEqual(
            construction["variant_counts"], {"voy a": 2, "vas a": 2})
        self.assertNotIn("voy a casa", covered)
        self.assertIn("voy a comer", covered)

    def test_longer_construction_does_not_inflate_standalone_expression(self):
        future_key = ("a", "me voy a beber")
        leaving_key = ("b", "me voy mañana")
        items = [{
            "expression": "me voy",
            "translation": "I'm leaving",
            "count": 2,
            "occurrence_count": 2,
            "num_songs": 2,
            "examples": [
                {"id": "a:1", "line": "Me voy a beber"},
                {"id": "b:1", "line": "Me voy mañana"},
            ],
        }]
        constructions = [{
            "_verb_lemma": "ir",
            "_line_keys": {future_key},
            "_shadow_standalone": True,
        }]
        ngram_data = {"lines": {"me voy": {future_key, leaving_key}}}
        morphology = {
            "voy": [{"lemma": "ir", "mood": "indicativo"}],
        }

        filtered = _remove_construction_shadowed_hits(
            items, constructions, ngram_data, morphology, {})

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["count"], 1)
        self.assertEqual(filtered[0]["num_songs"], 1)
        self.assertEqual(filtered[0]["examples"][0]["id"], "b:1")


if __name__ == "__main__":
    unittest.main()
