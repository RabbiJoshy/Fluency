import json
import tempfile
import unittest
from pathlib import Path

from pipeline.util_evidence_store import (
    WSD_INPUT_SCHEMA,
    WSD_OUTPUT_SCHEMA,
    archive_json_artifact,
    build_occurrence,
    build_run_manifest,
    build_segment,
    claim_is_current,
    make_analysis_unit_id,
    make_claim,
    read_jsonl,
    resolve_claims,
    scan_source_tokens,
    validate_wsd_input,
    validate_wsd_output,
    write_jsonl_atomic,
)


class EvidenceIdentityTests(unittest.TestCase):
    def _lyric_segment(self, text="Yo te vo'a esperar", positions=None):
        return build_segment(
            "es",
            text,
            {
                "kind": "lyrics",
                "corpus_id": "genius",
                "document_id": "genius:123",
                "text": text,
                "positions": positions or [4],
            },
            metadata={"title": "Song"},
        )

    def test_line_reordering_metadata_does_not_change_segment_identity(self):
        first = self._lyric_segment(positions=[4])
        moved = self._lyric_segment(positions=[19, 42])

        self.assertEqual(first["segment_id"], moved["segment_id"])
        # Source position is revision metadata, so a source refresh remains auditable.
        self.assertNotEqual(first["revision_id"], moved["revision_id"])

    def test_raw_occurrence_survives_revised_normalization(self):
        segment = self._lyric_segment()
        occurrence = build_occurrence(segment, 2, [6, 10], "vo'a", "unicode-token-v1")

        first = make_analysis_unit_id(
            occurrence["occurrence_id"], 0, "voy", "elision-v1")
        second = make_analysis_unit_id(
            occurrence["occurrence_id"], 0, "vos", "elision-v2")

        self.assertEqual(occurrence["surface"], "vo'a")
        self.assertNotEqual(first, second)
        self.assertEqual(
            occurrence["occurrence_id"],
            build_occurrence(segment, 2, [6, 10], "vo'a", "unicode-token-v1")["occurrence_id"],
        )

    def test_repeated_tokens_get_distinct_occurrence_ids(self):
        segment = self._lyric_segment("No no me digas no")
        ids = [
            build_occurrence(segment, i, [i, i + 1], "no", "test-scanner")["occurrence_id"]
            for i in (0, 1, 4)
        ]
        self.assertEqual(len(set(ids)), 3)

    def test_frozen_scanner_is_unicode_and_elision_agnostic(self):
        rows = scan_source_tokens("'Toy aquí, vo'a où Żółć")
        self.assertEqual(
            [row["surface"] for row in rows],
            ["'Toy", "aquí", "vo'a", "où", "Żółć"],
        )


class EvidenceClaimTests(unittest.TestCase):
    def _claim(self, method_id, run_id, value, confidence=1.0, projection=None):
        return make_claim(
            "sense_assignment",
            "analysis_unit",
            "unit_1",
            "assert",
            value,
            {"method_id": method_id, "run_id": run_id},
            projection or {"context": "bank line", "pos": "NOUN"},
            confidence=confidence,
        )

    def test_competing_classifier_runs_coexist_and_profile_switches_winner(self):
        gemini = self._claim("gemini-v3", "run-gemini", {"sense_id": "finance"})
        local = self._claim("local-wsd-v1", "run-local", {"sense_id": "seat"})

        first = resolve_claims(
            [gemini, local], {"gemini-v3": 100, "local-wsd-v1": 50})
        second = resolve_claims(
            [gemini, local], {"gemini-v3": 50, "local-wsd-v1": 100})

        key = ("sense_assignment", "analysis_unit", "unit_1")
        self.assertEqual(first[key]["value"]["sense_id"], "finance")
        self.assertEqual(second[key]["value"]["sense_id"], "seat")
        self.assertEqual({gemini["claim_id"], local["claim_id"]}, {
            first[key]["claim_id"], second[key]["claim_id"],
        })

    def test_semantic_dependency_fingerprint_localizes_staleness(self):
        projection = {"context": "bank line", "pos": "NOUN"}
        claim = self._claim("local", "run-1", {"sense_id": "seat"}, projection=projection)

        self.assertTrue(claim_is_current(claim, projection))
        self.assertFalse(claim_is_current(
            claim, {"context": "bank line", "pos": "VERB"}))

    def test_menu_free_wsd_input_is_valid(self):
        record = {
            "schema": WSD_INPUT_SCHEMA,
            "analysis_unit_id": "unit_1",
            "occurrence_id": "occ_1",
            "language": "fr",
            "surface": "banco",
            "normalized_form": "banco",
            "lexeme_id": "lex_fr_1",
            "context": {"target_text": "Un contexte sans dictionnaire."},
            "inventory": None,
        }
        self.assertTrue(validate_wsd_input(record))

    def test_menu_free_wsd_output_can_propose_inline_sense(self):
        record = {
            "schema": WSD_OUTPUT_SCHEMA,
            "analysis_unit_id": "unit_1",
            "occurrence_id": "occ_1",
            "method_id": "local-transformer-v2",
            "decision": "proposed",
            "proposed_sense": {
                "lemma": "être",
                "pos": "VERB",
                "translation": "to be",
            },
        }

        self.assertTrue(validate_wsd_output(record))

    def test_speech_shaped_parallel_segment_uses_shared_contract(self):
        segment = build_segment(
            "es",
            "Está sentado en el banco.",
            {
                "kind": "parallel_corpus",
                "corpus_id": "opensubtitles-en-es",
                "document_id": "subtitle-doc",
                "segment_key": "842",
            },
            aligned_texts=[{"language": "en", "text": "He is sitting on the bench."}],
        )
        occurrence = build_occurrence(
            segment, 4, [20, 25], "banco", "unicode-token-v1")

        self.assertEqual(segment["source"]["kind"], "parallel_corpus")
        self.assertEqual(segment["aligned_texts"][0]["language"], "en")
        self.assertEqual(occurrence["segment_id"], segment["segment_id"])


class EvidenceFileTests(unittest.TestCase):
    def test_compatibility_snapshot_preserves_distinct_runs_and_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = archive_json_artifact(
                Path(tmp), "routing", {"noise": ["eh"]}, language="fr")
            again = archive_json_artifact(
                Path(tmp), "routing", {"noise": ["eh"]}, language="fr")
            second = archive_json_artifact(
                Path(tmp), "routing", {"noise": ["euh"]}, language="fr")

            self.assertEqual(first["run_id"], again["run_id"])
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertTrue(Path(first["path"], "artifact.json").is_file())
            with open(Path(tmp) / "profiles" / "current.json", encoding="utf-8") as file:
                profile = json.load(file)
            self.assertEqual(profile["materialized_runs"]["routing"], second["run_id"])

    def test_snapshot_ignores_only_volatile_generated_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = archive_json_artifact(
                Path(tmp), "pos", {"word": {"0": "NOUN"}, "_meta": {
                    "step_version": 4, "generated_at": 1,
                }})
            second = archive_json_artifact(
                Path(tmp), "pos", {"word": {"0": "NOUN"}, "_meta": {
                    "step_version": 4, "generated_at": 999,
                }})

            self.assertEqual(first["run_id"], second["run_id"])

    def test_jsonl_round_trip_and_manifest_hashes_dependencies(self):
        segment = build_segment(
            "nl", "Een regel", {
                "kind": "fixture", "corpus_id": "test", "document_id": "doc",
                "segment_key": "1",
            })
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "segments.jsonl"
            artifact = write_jsonl_atomic(path, [segment])
            self.assertEqual(read_jsonl(path), [json.loads(json.dumps(segment))])
            manifest = build_run_manifest(
                "run-1", "corpus", "nl",
                {"name": "fixture", "version": "1"},
                {"source": "sha256:abc"}, {"dedupe": True},
                {"segments.jsonl": artifact},
                {segment["segment_id"]: "sha256:def"},
            )
            self.assertTrue(manifest["immutable"])
            self.assertEqual(manifest["artifacts"]["segments.jsonl"]["records"], 1)
            self.assertTrue(manifest["input_selection_hash"].startswith("sha256:"))

    def test_divergent_duplicate_id_is_rejected(self):
        segment = build_segment(
            "fr", "Même ligne", {
                "kind": "fixture", "corpus_id": "test", "document_id": "doc",
                "segment_key": "1",
            })
        changed = dict(segment)
        changed["text"] = "Different text under reused identity"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "segments.jsonl"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(segment, ensure_ascii=False) + "\n")
                handle.write(json.dumps(changed, ensure_ascii=False) + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate ID"):
                read_jsonl(path)

    def test_occurrence_reader_uses_occurrence_not_parent_segment_identity(self):
        segment = build_segment(
            "es", "No no", {
                "kind": "fixture", "corpus_id": "test", "document_id": "doc",
                "segment_key": "1",
            })
        occurrences = [
            build_occurrence(segment, 0, [0, 2], "No", "test-scanner"),
            build_occurrence(segment, 1, [3, 5], "no", "test-scanner"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "occurrences.jsonl"
            write_jsonl_atomic(path, occurrences)
            self.assertEqual(read_jsonl(path), occurrences)


if __name__ == "__main__":
    unittest.main()
