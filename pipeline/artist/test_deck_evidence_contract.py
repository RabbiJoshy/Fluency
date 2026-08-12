import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.artist.step_8b_assemble_artist_vocabulary import (
    active_evidence_build_contract,
)
from pipeline.artist.util_2b_evidence_view import corpus_profile_fingerprint
from pipeline.util_pipeline_meta import (
    dependency_metadata,
    make_meta,
    write_sidecar,
)


class DeckEvidenceContractTests(unittest.TestCase):
    def _artist(self, root, profile=None):
        artist_dir = Path(root) / "Artist"
        artist_dir.mkdir(parents=True)
        if profile is not None:
            profile_path = artist_dir / "data" / "evidence" / "profiles" / "current.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
        return artist_dir

    @staticmethod
    def _profile():
        return {
            "language": "es",
            "runs": {
                "ledger": "run_ledger",
                "normalization": "run_norm",
                "corpus_membership": "run_member",
                "vocal_artifact": "run_noise",
            },
            "claim_runs": {"normalization": ["run_norm"]},
            "policies": {
                "vocal_artifact": {"excluded_labels": ["echo", "adlib"]},
            },
            "materialized_runs": {"word_inventory": "run_old"},
        }

    def _write_compatibility_inputs(self, artist_dir, profile, ledger_run=None):
        layers = artist_dir / "data" / "layers"
        layers.mkdir(parents=True)
        for filename, payload in (
                ("word_inventory.json", [{"word": "voy"}]),
                ("examples_raw.json", {"voy": [{"text": "Voy a casa"}]})):
            path = layers / filename
            path.write_text(json.dumps(payload), encoding="utf-8")
            write_sidecar(path, make_meta(
                "fixture", 1,
                extra={
                    "ledger_run": ledger_run or profile["runs"]["ledger"],
                    "corpus_profile_hash": corpus_profile_fingerprint(profile),
                },
            ))

    def test_legacy_artist_without_profile_remains_buildable(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = self._artist(tmp)
            self.assertEqual(active_evidence_build_contract(artist_dir), {})

    def test_matching_compatibility_inputs_return_reproducible_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile()
            artist_dir = self._artist(tmp, profile)
            self._write_compatibility_inputs(artist_dir, profile)

            contract = active_evidence_build_contract(artist_dir)

            self.assertEqual(contract["ledger_run"], "run_ledger")
            self.assertEqual(contract["excluded_labels"], ["adlib", "echo"])
            self.assertEqual(
                set(contract["layer_sha256"]), {"word_inventory", "examples_raw"})

    def test_stale_ledger_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile()
            artist_dir = self._artist(tmp, profile)
            self._write_compatibility_inputs(
                artist_dir, profile, ledger_run="run_previous")

            with self.assertRaisesRegex(ValueError, "not materialized from active ledger"):
                active_evidence_build_contract(artist_dir)

    def test_materialized_snapshot_pointers_do_not_stale_corpus(self):
        first = self._profile()
        second = copy.deepcopy(first)
        second["materialized_runs"] = {
            "word_inventory": "run_new",
            "final_deck__index": "run_deck",
        }
        self.assertEqual(
            corpus_profile_fingerprint(first),
            corpus_profile_fingerprint(second),
        )

    def test_dependency_metadata_hashes_content_and_propagates_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text('[{"word":"voy"}]', encoding="utf-8")
            write_sidecar(path, {
                "ledger_run": "run_ledger",
                "corpus_profile_hash": "profile_hash",
                "excluded_labels": ["echo"],
            })

            metadata = dependency_metadata(path)

            self.assertEqual(metadata["ledger_run"], "run_ledger")
            self.assertEqual(metadata["corpus_profile_hash"], "profile_hash")
            self.assertEqual(metadata["excluded_labels"], ["echo"])
            self.assertEqual(len(metadata["input_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
