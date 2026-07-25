import unittest

from pipeline.artist.step_2a_count_words import build_counts_and_candidates


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


if __name__ == "__main__":
    unittest.main()
