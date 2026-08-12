import json
import tempfile
import unittest
from pathlib import Path

from pipeline.artist.step_2a_count_words import normalize_analysis_tokens
from pipeline.artist.util_2a_corpus_ledger import ArtistCorpusLedger
from pipeline.util_evidence_store import make_occurrence_id, read_jsonl


class ArtistCorpusLedgerTests(unittest.TestCase):
    def test_ingestion_completes_chained_elision_restoration(self):
        mapping = {"metío'": "metíos", "pegaíto'": "pegaítos"}
        self.assertEqual(
            normalize_analysis_tokens(
                ["metío'", "pegaíto'", "mojaítas"], mapping),
            ["metidos", "pegaditos", "mojaditas"],
        )

    def test_ingestion_restores_high_confidence_internal_elisions(self):
        self.assertEqual(
            normalize_analysis_tokens(
                ["nunca", "como", "e'to", "y", "moja'íta", "discoteka'"],
                {},
                known_forms={"esto", "mojado", "discotecas"},
            ),
            ["nunca", "como", "esto", "y", "mojadita", "discotecas"],
        )

    def test_ingestion_uses_context_only_for_ambiguous_candidates(self):
        known = {
            "menos", "emperado", "esperado", "llegarte", "llegaste",
            "pasante", "pasarte", "pasaste", "tiguere",
        }
        self.assertEqual(
            normalize_analysis_tokens(
                ["menos", "e'perado", "que", "llega'te", "te", "pasa'te",
                 "los", "tíguere'"],
                {}, known_forms=known,
            ),
            ["menos", "esperado", "que", "llegaste", "te", "pasaste",
             "los", "tigueres"],
        )

    def test_ingestion_abstains_when_internal_elision_is_ambiguous(self):
        self.assertEqual(
            normalize_analysis_tokens(
                ["algo", "e'perado", "y", "llega'te"], {},
                known_forms={"emperado", "esperado", "llegarte", "llegaste"},
            ),
            ["algo", "e'perado", "y", "llega'te"],
        )

    def _collector(self, root, language="spanish"):
        artist_dir = Path(root) / "Artist"
        artist_dir.mkdir(parents=True, exist_ok=True)
        return ArtistCorpusLedger(artist_dir, language, artist_name="Fixture Artist")

    @staticmethod
    def _observe(collector, song_id, line_no, text, tokens=None):
        tokens = tokens or [
            {"surface": token, "forms": [token.lower()]}
            for token in text.split()
        ]
        return collector.observe_line(
            song_id, "Song", line_no, text, tokens,
            included=True,
        )

    @staticmethod
    def _current_segments(root):
        evidence = Path(root) / "Artist" / "data" / "evidence"
        with open(evidence / "profiles" / "current.json", encoding="utf-8") as handle:
            profile = json.load(handle)
        path = evidence / "ledger" / "runs" / profile["runs"]["ledger"] / "segments.jsonl"
        return read_jsonl(path)

    def test_reorder_keeps_ids_and_removal_is_a_reversible_tombstone(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self._collector(tmp)
            line_a = self._observe(first, "song", 1, "Hola mundo")
            line_b = self._observe(first, "song", 2, "Adiós mundo")
            first_run = first.finalize()

            second = self._collector(tmp)
            moved_a = self._observe(second, "song", 20, "Hola mundo")
            second_run = second.finalize()

            self.assertEqual(line_a, moved_a)
            self.assertNotEqual(first_run["run_id"], second_run["run_id"])
            by_id = {row["segment_id"]: row for row in self._current_segments(tmp)}
            self.assertEqual(by_id[line_a]["state"], "present")
            self.assertEqual(by_id[line_b]["state"], "tombstone")

            third = self._collector(tmp)
            self._observe(third, "song", 20, "Hola mundo")
            restored_b = self._observe(third, "song", 30, "Adiós mundo")
            third.finalize()
            by_id = {row["segment_id"]: row for row in self._current_segments(tmp)}
            self.assertEqual(restored_b, line_b)
            self.assertEqual(by_id[line_b]["state"], "present")

    def test_repeated_target_tokens_have_distinct_occurrence_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = self._collector(tmp)
            segment_id = self._observe(
                collector,
                "song",
                1,
                "No no me digas no",
                [
                    {"surface": "No", "forms": ["no"]},
                    {"surface": "no", "forms": ["no"]},
                    {"surface": "me", "forms": ["me"]},
                    {"surface": "digas", "forms": ["digas"]},
                    {"surface": "no", "forms": ["no"]},
                ],
            )
            refs = collector.example_refs(
                "song", "Song", 1, "No no me digas no", "no")
            summary = collector.finalize()

            self.assertEqual(refs["segment_id"], segment_id)
            self.assertEqual(len(refs["occurrence_ids"]), 3)
            self.assertEqual(len(set(refs["occurrence_ids"])), 3)
            self.assertEqual(summary["occurrences"], 5)

    def test_repeated_identical_lines_are_distinct_source_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = self._collector(tmp)
            first = self._observe(
                collector, "song", 4, "No no",
                [{"surface": "No", "forms": ["no"]}],
            )
            second = self._observe(
                collector, "song", 8, "No no",
                [{"surface": "No", "forms": ["no"]}],
            )

            first_refs = collector.example_refs(
                "song", "Song", 4, "No no", "no")
            second_refs = collector.example_refs(
                "song", "Song", 8, "No no", "no")

            self.assertNotEqual(first, second)
            self.assertNotEqual(
                first_refs["occurrence_ids"], second_refs["occurrence_ids"])

    def test_one_raw_elision_can_emit_multiple_analysis_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = self._collector(tmp)
            self._observe(
                collector,
                "song",
                1,
                "Yo me vo'a quedar",
                [
                    {"surface": "Yo", "forms": ["yo"]},
                    {"surface": "me", "forms": ["me"]},
                    {"surface": "vo'a", "forms": ["voy", "a"]},
                    {"surface": "quedar", "forms": ["quedar"]},
                ],
            )
            voy = collector.example_refs(
                "song", "Song", 1, "Yo me vo'a quedar", "voy")
            article = collector.example_refs(
                "song", "Song", 1, "Yo me vo'a quedar", "a")
            summary = collector.finalize()

            self.assertEqual(voy["occurrence_ids"], article["occurrence_ids"])
            self.assertEqual(summary["occurrences"], 4)
            self.assertEqual(summary["normalization_claims"], 4)

    def test_trailing_elision_marker_attaches_to_raw_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = self._collector(tmp)
            self._observe(
                collector,
                "song",
                1,
                "Y vamo' a bailar",
                [
                    {"surface": "Y", "forms": ["y"]},
                    {"surface": "vamo'", "forms": ["vamo'"]},
                    {"surface": "a", "forms": ["a"]},
                    {"surface": "bailar", "forms": ["bailar"]},
                ],
            )
            refs = collector.example_refs(
                "song", "Song", 1, "Y vamo' a bailar", "vamo'")

            self.assertEqual(len(refs.get("occurrence_ids") or []), 1)

    def test_bracketed_repeat_does_not_steal_line_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = self._collector(tmp)
            segment_id = self._observe(
                collector,
                "song",
                1,
                "Mar (mar), frente al mar",
                [
                    {"surface": "Mar", "forms": ["mar"]},
                    {"surface": "frente", "forms": ["frente"]},
                    {"surface": "al", "forms": ["al"]},
                    {"surface": "mar", "forms": ["mar"]},
                ],
            )
            refs = collector.example_refs(
                "song", "Song", 1, "Mar (mar), frente al mar", "mar")

            self.assertEqual(refs["occurrence_ids"], [
                make_occurrence_id(segment_id, 0),
                make_occurrence_id(segment_id, 4),
            ])

    def test_language_namespaces_identical_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            spanish = self._collector(Path(tmp) / "es", "spanish")
            french = self._collector(Path(tmp) / "fr", "french")
            es_id = self._observe(spanish, "song", 1, "No")
            fr_id = self._observe(french, "song", 1, "No")
            self.assertNotEqual(es_id, fr_id)

    def test_ledger_advance_preserves_custom_method_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = self._collector(tmp)
            profile_path = (
                Path(tmp) / "Artist" / "data" / "evidence" /
                "profiles" / "current.json"
            )
            profile_path.parent.mkdir(parents=True)
            with open(profile_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "schema": "fluency.evidence-profile/v1",
                    "profile_id": "experiment",
                    "method_priorities": {"my-local-wsd": 100},
                    "runs": {},
                }, handle)

            self._observe(collector, "song", 1, "Bonjour monde")
            collector.finalize()

            with open(profile_path, encoding="utf-8") as handle:
                profile = json.load(handle)
            self.assertEqual(profile["profile_id"], "experiment")
            self.assertEqual(profile["method_priorities"]["my-local-wsd"], 100)
            self.assertIn("ledger", profile["runs"])


if __name__ == "__main__":
    unittest.main()
