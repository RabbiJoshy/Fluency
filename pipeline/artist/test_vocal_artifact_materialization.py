import json
import tempfile
import unittest
from pathlib import Path

from pipeline.artist import step_2a_count_words as count_step
from pipeline.artist.step_2d_classify_vocal_artifacts import (
    classify_occurrences,
    write_classifier_run,
    untranslated_segment_ids,
)
from pipeline.artist.step_2e_materialize_corpus import materialize_artist
from pipeline.artist.util_2a_corpus_ledger import ArtistCorpusLedger
from pipeline.artist.util_2b_evidence_view import (
    load_active_evidence,
    materialize_vocabulary_evidence,
)
from pipeline.util_evidence_store import archive_json_artifact


class VocalArtifactMaterializationTests(unittest.TestCase):
    def _artist(self, root):
        artist_dir = Path(root) / "Artist"
        artist_dir.mkdir(parents=True)
        with open(artist_dir / "artist.json", "w", encoding="utf-8") as handle:
            json.dump({
                "name": "Fixture Artist",
                "language": "spanish",
                "vocabulary_file": "Fixturevocabulary.json",
            }, handle)
        return artist_dir

    def _scan(self, artist_dir, songs, mwe_map=None):
        ledger = ArtistCorpusLedger(
            artist_dir, "spanish", artist_name="Fixture Artist")
        counts, candidates, _stats, _ngrams, word_songs = (
            count_step.build_counts_and_candidates(
                songs,
                lid_detector=None,
                mwe_map=mwe_map or {},
                primary_artist="Fixture Artist",
                ledger=ledger,
            )
        )
        selected = count_step.select_examples(counts, candidates, 10)
        direct = count_step.to_evidence_json(counts, selected, word_songs)
        ledger.finalize(config={"max_examples": 10})
        return direct

    def test_behavior_neutral_materializer_matches_legacy_counting_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = self._artist(tmp)
            songs = [{
                "id": 1,
                "title": "Song",
                "__batch": 3,
                "__song_order": 7,
                "lyrics": (
                    "Lyrics\n"
                    "Yo quiero mover, -over ahora\n"
                    "Game over ahora\n"
                    "Voy pa'l centro\n"
                    "Voy pa'l centro\n"
                    "Respeto, to’s me tienen miedo\n"
                    "Yo te vo’a buscar cerca del lunar\n"
                    "Abre la Möet y no falle\n"
                    "Passe le mic', on verra bien c'que ça donne, my lady\n"
                    "Нa cвiтaнку de madrugá\n"
                    "Ya estoy proba’o y preparado\n"
                    "'Tamo' aquí desde ayer\n"
                    "(Yeah) ah-na-na"
                ),
            }]
            direct = self._scan(
                artist_dir, songs, mwe_map={"pa'l": ["para", "el"]})
            materialized, summary = materialize_vocabulary_evidence(
                artist_dir / "data" / "evidence",
                max_examples=10,
                excluded_labels=[],
            )

            self.assertEqual(materialized, direct)
            self.assertEqual(summary["excluded_occurrences"], 0)

    def test_neutral_materializer_preserves_source_song_order_for_ties(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = self._artist(tmp)
            songs = [
                {
                    "id": "later-sort-id",
                    "title": "First Source Song",
                    "__batch": 0,
                    "__song_order": 0,
                    "lyrics": "Lyrics\nEsto es una burla seria",
                },
                {
                    "id": "earlier-sort-id",
                    "title": "Second Source Song",
                    "__batch": 0,
                    "__song_order": 1,
                    "lyrics": "Lyrics\nEsto es otra burla clara",
                },
            ]
            direct = self._scan(artist_dir, songs)
            materialized, _summary = materialize_vocabulary_evidence(
                artist_dir / "data" / "evidence",
                max_examples=10,
                excluded_labels=[],
            )

            self.assertEqual(materialized, direct)

    def test_basic_classifier_drops_only_the_echo_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = self._artist(tmp)
            songs = [{
                "id": 1,
                "title": "Song",
                "__batch": 0,
                "lyrics": (
                    "Lyrics\n"
                    "Yo quiero mover, -over ahora\n"
                    "Game over ahora\n"
                    "(Yeah) ah-na-na"
                ),
            }]
            direct = self._scan(artist_dir, songs)
            direct_by_word = {row["word"]: row for row in direct}
            self.assertEqual(direct_by_word["over"]["corpus_count"], 2)

            known_path = Path(tmp) / "known.json"
            with open(known_path, "w", encoding="utf-8") as handle:
                json.dump(["mover", "yo", "quiero", "ahora"], handle)
            summary = write_classifier_run(
                artist_dir, policy="basic", known_forms_path=known_path)
            materialized, materialized_summary = materialize_vocabulary_evidence(
                artist_dir / "data" / "evidence", max_examples=10)
            by_word = {row["word"]: row for row in materialized}

            self.assertEqual(summary["labels"]["echo"], 1)
            self.assertGreaterEqual(summary["labels"]["adlib"], 1)
            self.assertGreaterEqual(summary["labels"]["stutter"], 2)
            self.assertEqual(by_word["over"]["corpus_count"], 1)
            self.assertEqual(by_word["mover"]["corpus_count"], 1)
            self.assertEqual(materialized_summary["excluded_labels"], [
                "adlib", "credit", "echo", "stutter",
            ])

    def test_untranslated_line_is_a_credit_but_translated_one_is_not(self):
        """A line the translator copied across is a name/tag, not language.

        This is what keeps the producer tag `Sky Rompiendo` out of the deck.
        Capitalisation and spaCy NER were both measured useless here — NER
        misses `rompiendo` and `orión` and calls `grr` a person — but a human
        translator reliably leaves a credit verbatim and renders real Spanish.
        The comparison is accent- and punctuation-insensitive so that
        `Ozuna (Baby)` still matches its copied English.
        """
        segments = [
            {"segment_id": "s1", "state": "present", "text": "Sky Rompiendo"},
            {"segment_id": "s2", "state": "present", "text": "Ozuna (Baby)"},
            {"segment_id": "s3", "state": "present", "text": "Tú lo ve'"},
            {"segment_id": "s4", "state": "present", "text": "Sin traducir"},
        ]
        translations = {
            "Sky Rompiendo": "Sky Rompiendo",
            "Ozuna (Baby)": "Ozuna, baby!",
            "Tú lo ve'": "You see it",
        }
        self.assertEqual(
            untranslated_segment_ids(segments, translations), {"s1", "s2"})
        # No translations at all must not label anything.
        self.assertEqual(untranslated_segment_ids(segments, {}), set())

    def test_legitimate_elsewhere_use_is_not_retargeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = self._artist(tmp)
            self._scan(artist_dir, [{
                "id": "song",
                "title": "Song",
                "lyrics": "Lyrics\nMover, -over\nLary Over\nNo-no",
            }])
            active = load_active_evidence(artist_dir / "data" / "evidence")
            classified = classify_occurrences(
                active["segments"], active["occurrences"],
                known_forms={"mover", "no"})
            echo_ids = [occurrence_id for occurrence_id, value in classified.items()
                        if "echo" in value["labels"]]

            self.assertEqual(len(echo_ids), 1)
            echo_occurrence = next(
                row for row in active["occurrences"]
                if row["occurrence_id"] == echo_ids[0])
            echo_segment = next(
                row for row in active["segments"]
                if row["segment_id"] == echo_occurrence["segment_id"])
            self.assertEqual(echo_segment["text"], "Mover, -over")
            no_segment = next(
                row for row in active["segments"] if row["text"] == "No-no")
            no_occurrences = {
                row["occurrence_id"] for row in active["occurrences"]
                if row["segment_id"] == no_segment["segment_id"]
            }
            self.assertFalse(no_occurrences & set(classified))

    def test_classifier_uses_restored_form_for_known_word_guard(self):
        segments = [{
            "segment_id": "seg-1",
            "state": "present",
            "text": "move', -ove",
        }]
        occurrences = [
            {"occurrence_id": "occ-source", "segment_id": "seg-1",
             "state": "present", "ordinal": 0, "span": [0, 5],
             "surface": "move'"},
            {"occurrence_id": "occ-echo", "segment_id": "seg-1",
             "state": "present", "ordinal": 1, "span": [8, 11],
             "surface": "ove"},
        ]

        classified = classify_occurrences(
            segments,
            occurrences,
            known_forms={"mover"},
            normalization_forms={"occ-source": ["mover"]},
        )

        self.assertEqual(classified["occ-echo"]["labels"], ["echo"])

    def test_strict_parity_uses_immutable_baseline_on_repeated_active_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = self._artist(tmp)
            direct = self._scan(artist_dir, [{
                "id": 1,
                "title": "Song",
                "lyrics": "Lyrics\nMover, -over\nLary Over",
            }])
            evidence_dir = artist_dir / "data" / "evidence"
            archive_json_artifact(
                evidence_dir, "vocab_evidence_baseline", direct, language="es")
            output = artist_dir / "data" / "word_counts" / "vocab_evidence.json"
            output.parent.mkdir(parents=True)
            with open(output, "w", encoding="utf-8") as handle:
                json.dump(direct, handle, ensure_ascii=False, indent=2)

            known_path = Path(tmp) / "known.json"
            with open(known_path, "w", encoding="utf-8") as handle:
                json.dump(["mover"], handle)
            write_classifier_run(
                artist_dir, policy="basic", known_forms_path=known_path)

            first = materialize_artist(artist_dir)
            second = materialize_artist(artist_dir)
            with open(output, encoding="utf-8") as handle:
                by_word = {row["word"]: row for row in json.load(handle)}

            self.assertTrue(first["neutral_parity"])
            self.assertTrue(second["neutral_parity"])
            self.assertEqual(by_word["over"]["corpus_count"], 1)


if __name__ == "__main__":
    unittest.main()
