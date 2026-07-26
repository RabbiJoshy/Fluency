import unittest

from pipeline.artist.step_2a_count_words import (
    _pool_construction_families,
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


if __name__ == "__main__":
    unittest.main()
