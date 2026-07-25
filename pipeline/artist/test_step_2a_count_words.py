import unittest

from pipeline.artist.step_2a_count_words import (
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


if __name__ == "__main__":
    unittest.main()
