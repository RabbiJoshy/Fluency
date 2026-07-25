import unittest

from pipeline.artist.step_3a_merge_elisions import merge_evidence
from pipeline.artist.step_7b_rerank import sort_key


class SongCountPipelineTests(unittest.TestCase):
    def test_elision_merge_unions_full_corpus_song_ids(self):
        data = [
            {
                "word": "cansao",
                "corpus_count": 3,
                "song_ids": ["song-a", "song-b"],
                "examples": [{"id": "song-a:1", "line": "Estoy cansao"}],
            },
            {
                "word": "cansado",
                "corpus_count": 2,
                "song_ids": ["song-b", "song-c"],
                "examples": [{"id": "song-c:1", "line": "Estoy cansado"}],
            },
        ]
        targets = {
            "cansao": {"target_word": "cansado", "display_form": "cansao"},
            "cansado": {"target_word": "cansado", "display_form": "cansado"},
        }

        merged, _stats = merge_evidence(data, targets, known_vocab=set())

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["song_count"], 3)
        self.assertEqual(merged[0]["song_ids"], ["song-a", "song-b", "song-c"])

    def test_rerank_prefers_full_corpus_song_count_after_other_ties(self):
        word_to_rank = {"alpha": 100, "bravo": 100}
        entries = [
            {"word": "alpha", "lemma": "alpha", "corpus_count": 5, "_song_count": 2},
            {"word": "bravo", "lemma": "bravo", "corpus_count": 5, "_song_count": 4},
        ]

        entries.sort(key=lambda entry: sort_key(entry, word_to_rank, {}))

        self.assertEqual([entry["word"] for entry in entries], ["bravo", "alpha"])


if __name__ == "__main__":
    unittest.main()
