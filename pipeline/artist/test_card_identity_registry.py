import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline.artist.step_8b_assemble_artist_vocabulary import (
    _build_menu_free_groups,
    _stabilize_sense_identities,
    assign_ids_from_master,
)


class ArtistCardIdentityTests(unittest.TestCase):
    def test_menu_free_group_keeps_inline_lemma_and_sense(self):
        groups = _build_menu_free_groups(
            "suis",
            {"suis|être": {"my-local-wsd": [{
                "sense": "sense-1",
                "examples": [0],
                "example_ids": ["seg-1"],
                "lemma": "être",
                "pos": "VERB",
                "translation": "am",
            }]}},
            min_priority=0,
            method_priorities={"my-local-wsd": 100},
        )

        self.assertEqual(groups[0]["lemma"], "être")
        self.assertEqual(groups[0]["word_senses"][0]["translation"], "am")
        self.assertEqual(groups[0]["assignments"][0]["sense"], "sense-1")

    def test_changed_lemma_reuses_existing_card_id(self):
        master = {
            "a1b2c3": {"word": "suis", "lemma": "suivre"},
        }
        entries = [{
            "word": "suis",
            "lemma": "être",
            "_identity_evidence": ["occ-1"],
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "cards.json"
            assign_ids_from_master(
                entries, master, registry_path=registry_path, language="fr")

        self.assertEqual(entries[0]["id"], "a1b2c3")
        self.assertNotIn("_identity_evidence", entries[0])

    def test_ambiguous_lemma_split_does_not_guess_progress_owner(self):
        master = {
            "a1b2c3": {"word": "como", "lemma": "comer"},
        }
        entries = [
            {"word": "como", "lemma": "comparison", "_identity_evidence": ["occ-1"]},
            {"word": "como", "lemma": "manner", "_identity_evidence": ["occ-2"]},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "cards.json"
            assign_ids_from_master(
                entries, master, registry_path=registry_path, language="es")

        self.assertNotIn("a1b2c3", {entry["id"] for entry in entries})
        self.assertNotEqual(entries[0]["id"], entries[1]["id"])

    def test_legacy_duplicate_master_aliases_become_explicit_migration(self):
        master = {
            "111111": {"word": "voy", "lemma": "ir"},
            "222222": {"word": "voy", "lemma": "ir"},
        }
        entries = [{"word": "voy", "lemma": "ir"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "cards.json"
            assign_ids_from_master(
                entries, master, registry_path=registry_path, language="es")

            from pipeline.util_identity_registry import CardIdentityRegistry
            registry = CardIdentityRegistry.load(registry_path, "es")

        self.assertEqual(entries[0]["id"], "222222")
        self.assertEqual(registry.records["111111"]["superseded_by"], "222222")

    def test_changed_gloss_and_provider_keep_existing_sense_progress_id(self):
        master = {"card-1": {
            "word": "banco",
            "lemma": "banco",
            "senses": [{
                "sense_id": "old-sense",
                "pos": "NOUN",
                "translation": "bench",
            }],
        }}
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "senses.json"
            first = [{
                "id": "card-1",
                "meanings": [{
                    "sense_id": "old-sense",
                    "pos": "NOUN",
                    "translation": "bench",
                    "examples": [{"_identity_evidence": ["occ-1"]}],
                }],
            }]
            _stabilize_sense_identities(
                first, master, registry_path, "es")

            revised = [{
                "id": "card-1",
                "meanings": [{
                    "sense_id": "new-provider-id",
                    "pos": "NOUN",
                    "translation": "seat; bench",
                    "examples": [{"_identity_evidence": ["occ-1"]}],
                }],
            }]
            _stabilize_sense_identities(
                revised, master, registry_path, "es")

        meaning = revised[0]["meanings"][0]
        self.assertEqual(meaning["sense_id"], "old-sense")
        self.assertIn("new-provider-id", meaning["sense_id_aliases"])
        self.assertNotIn("_identity_evidence", meaning["examples"][0])


if __name__ == "__main__":
    unittest.main()
