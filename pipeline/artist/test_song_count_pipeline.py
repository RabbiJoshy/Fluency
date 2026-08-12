import unittest

from pipeline.artist.step_3a_merge_elisions import (
    d_elision_ext_canonical,
    internal_apos_restore,
    merge_evidence,
    trailing_apos_restore,
)
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

    def test_trailing_apostrophe_restores_z_only_when_unambiguous(self):
        self.assertEqual(trailing_apos_restore("lu'", {"luz"}), ("luz", "lu'"))
        self.assertIsNone(trailing_apos_restore("cru'", {"cruz", "crus"}))

    def test_internal_apostrophe_requires_one_known_candidate(self):
        self.assertEqual(
            internal_apos_restore("e'to", {"esto"}), ("esto", "e'to"))
        self.assertIsNone(
            internal_apos_restore("e'perado", {"emperado", "esperado"}))

    def test_k_spelling_variant_still_requires_a_known_target(self):
        self.assertEqual(
            internal_apos_restore("discoteka'", {"discotecas"}),
            ("discotecas", "discoteka'"),
        )
        self.assertIsNone(internal_apos_restore("bruka'", {"brucas", "brukas"}))

    def test_diminutive_d_elision_can_validate_through_base_adjective(self):
        self.assertEqual(
            d_elision_ext_canonical("moja'íta", {"mojado"}),
            ("mojadita", "moja'íta", "d_elision_diminutive"),
        )


if __name__ == "__main__":
    unittest.main()
