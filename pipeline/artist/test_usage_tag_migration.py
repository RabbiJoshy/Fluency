import json
import tempfile
import unittest
from pathlib import Path

from pipeline.artist import step_2a_count_words as count_step
from pipeline.artist.tool_6d_migrate_legacy_usage_tags import (
    build_usage_tag_claims,
    canonical_tag,
    collect_occurrence_assertions,
    load_elision_aliases,
)
from pipeline.artist.tool_6e_apply_usage_tag_overrides import (
    collect_override_operations,
)
from pipeline.artist.util_2a_corpus_ledger import ArtistCorpusLedger
from pipeline.artist.util_2b_evidence_view import resolved_usage_tags


class UsageTagMigrationTests(unittest.TestCase):
    def _active(self, root, lyrics="Eso es calle"):
        artist_dir = Path(root) / "Artist"
        artist_dir.mkdir()
        (artist_dir / "artist.json").write_text(json.dumps({
            "name": "Fixture Artist",
            "language": "spanish",
            "vocabulary_file": "Fixture.json",
        }), encoding="utf-8")
        ledger = ArtistCorpusLedger(
            artist_dir, "spanish", artist_name="Fixture Artist")
        count_step.build_counts_and_candidates(
            [{"id": 7, "title": "Song", "lyrics": "Lyrics\n" + lyrics}],
            lid_detector=None,
            primary_artist="Fixture Artist",
            ledger=ledger,
        )
        ledger.finalize(config={"max_examples": 10})
        from pipeline.artist.util_2b_evidence_view import load_active_evidence
        return artist_dir, load_active_evidence(artist_dir / "data" / "evidence")

    def test_taxonomy_normalizes_aliases_but_rejects_other_bucket(self):
        self.assertEqual(canonical_tag("idiomatic"), "idiom")
        self.assertEqual(canonical_tag("INTJ"), "interjection")
        self.assertIsNone(canonical_tag("other"))

    def test_context_record_becomes_occurrence_claim_with_raw_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            _artist_dir, active = self._active(tmp)
            occurrence = next(row for row in active["occurrences"]
                              if row["surface"].lower() == "calle")
            segment_id = occurrence["segment_id"]
            assignments = {"calle": {"gap-fill": [{
                "sense": "abc",
                "type": "idiomatic",
                "construction": "estar en la calle",
                "pos": "NOUN",
                "example_ids": [segment_id],
                "occurrence_refs": [{
                    "occurrence_id": occurrence["occurrence_id"],
                    "example_id": segment_id,
                }],
                "prompt_id": "sd-cop-v3",
                "run_ts": "2026-08-07T14:40Z",
            }]}}

            assertions, report = collect_occurrence_assertions(
                assignments, active, {"examples": {}})
            claims = build_usage_tag_claims(
                assertions, active, "run_fixture", "assignment_hash")

            self.assertEqual(report["resolved_records"], 1)
            self.assertEqual(len(claims), 1)
            self.assertEqual(claims[0]["value"]["labels"], ["idiom"])
            self.assertEqual(
                claims[0]["value"]["source_assertions"][0]["prompt_id"],
                "sd-cop-v3")
            self.assertEqual(claims[0]["subject"]["id"], occurrence["occurrence_id"])

    def test_legacy_line_id_is_filtered_to_target_word_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            _artist_dir, active = self._active(tmp, "Calle con calle")
            segment = next(row for row in active["segments"]
                           if row["text"] == "Calle con calle")
            occurrence_ids = [
                row["occurrence_id"] for row in active["occurrences"]
                if row["segment_id"] == segment["segment_id"]
            ]
            assignments = {"calle": {"gap-fill": [{
                "type": "slang",
                "example_ids": ["7:1"],
                "prompt_id": "sd-cop-v2",
            }]}}
            assertions, report = collect_occurrence_assertions(assignments, active, {
                "examples": {"7:1": {
                    "segment_id": segment["segment_id"],
                    "occurrence_ids": occurrence_ids,
                }},
            })

            self.assertEqual(report["resolved_records"], 1)
            self.assertEqual(len(assertions), 2)
            self.assertEqual({row[0]["word"] for row in assertions.values()}, {"calle"})

    def test_historical_elision_alias_can_resolve_assignment_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _artist_dir, active = self._active(tmp, "Siempre metío' aquí")
            segment = next(row for row in active["segments"]
                           if row["text"] == "Siempre metío' aquí")
            occurrence_ids = [row["occurrence_id"] for row in active["occurrences"]
                              if row["segment_id"] == segment["segment_id"]]
            mapping_path = root / "elisions.json"
            mapping_path.write_text(json.dumps([{
                "elided_word": "metío'",
                "target_word": "metíos",
                "target_lemma": "metío",
            }]), encoding="utf-8")
            assignments = {"metíos": {"gap-fill": [{
                "type": "slang", "example_ids": ["7:1"]}]}}
            assertions, report = collect_occurrence_assertions(
                assignments, active,
                {"examples": {"7:1": {
                    "segment_id": segment["segment_id"],
                    "occurrence_ids": occurrence_ids,
                }}},
                elision_aliases=load_elision_aliases(mapping_path),
            )

            self.assertEqual(report["resolved_records"], 1)
            self.assertEqual(len(assertions), 1)

    def test_exact_line_can_restore_one_dropped_final_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            _artist_dir, active = self._active(tmp, "Estoy pesao' hoy")
            segment = next(row for row in active["segments"]
                           if row["text"] == "Estoy pesao' hoy")
            occurrence_ids = [row["occurrence_id"] for row in active["occurrences"]
                              if row["segment_id"] == segment["segment_id"]]
            assertions, report = collect_occurrence_assertions(
                {"pesaos": {"gap-fill": [{
                    "type": "slang", "example_ids": ["7:1"]}]}},
                active,
                {"examples": {"7:1": {
                    "segment_id": segment["segment_id"],
                    "occurrence_ids": occurrence_ids,
                }}},
            )

            self.assertEqual(report["resolved_records"], 1)
            self.assertEqual(len(assertions), 1)

    def test_occurrence_curation_takes_precedence_over_global_curation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _artist_dir, active = self._active(tmp)
            occurrence = next(row for row in active["occurrences"]
                              if row["surface"].lower() == "calle")
            curations = {
                "global": [{
                    "language": "es",
                    "surface": "calle",
                    "action": "add",
                    "tags": ["slang"],
                    "reason": "fixture global",
                    "reviewed_by": "test",
                }],
                "occurrences": [{
                    "artist": "Fixture Artist",
                    "occurrence_id": occurrence["occurrence_id"],
                    "action": "remove",
                    "tags": ["slang"],
                    "reason": "literal here",
                    "reviewed_by": "test",
                }],
            }
            operations, matched = collect_override_operations(
                curations, active, "Fixture Artist", "es")
            active["claims"][(
                "usage_tag", "occurrence", occurrence["occurrence_id"])] = {
                    "value": {"labels": ["figurative"]}}
            active["claims"][(
                "usage_tag_override", "occurrence", occurrence["occurrence_id"])] = {
                    "value": {"operations": operations[occurrence["occurrence_id"]]}}

            resolved = resolved_usage_tags(active, occurrence["occurrence_id"])
            self.assertEqual(len(matched), 2)
            self.assertEqual(resolved["labels"], ["figurative"])
            self.assertEqual(
                [row["scope"] for row in resolved["operations"]],
                ["global", "occurrence"])


if __name__ == "__main__":
    unittest.main()
