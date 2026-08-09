import tempfile
import unittest
from pathlib import Path

from pipeline.util_identity_registry import CardIdentityRegistry, SenseIdentityRegistry


class CardIdentityRegistryTests(unittest.TestCase):
    def test_lemma_change_reuses_unique_surface_identity(self):
        registry = CardIdentityRegistry("french")
        registry.seed("a1b2c3", "suis", "suivre", ["occ-1"])

        card_id = registry.assign(
            "suis", "être", ["occ-1"], preferred_id="ffffff")

        self.assertEqual(card_id, "a1b2c3")
        self.assertEqual(len(registry.records[card_id]["aliases"]), 2)

    def test_ambiguous_homograph_does_not_guess(self):
        registry = CardIdentityRegistry("spanish")
        registry.seed("111111", "banco", "banco", ["occ-seat"])
        registry.seed("222222", "banco", "bancar", ["occ-bank"])

        self.assertIsNone(registry.resolve("banco", "new-analysis"))

    def test_occurrence_overlap_survives_surface_and_lemma_change(self):
        registry = CardIdentityRegistry("spanish")
        registry.seed("111111", "pa'", "para", ["occ-1"])

        self.assertEqual(
            registry.resolve("para", "parar", ["occ-1"]),
            "111111",
        )

    def test_claimed_identity_cannot_be_reused_for_automatic_split(self):
        registry = CardIdentityRegistry("spanish")
        registry.seed("111111", "como", "comer", ["occ-1", "occ-2"])

        self.assertIsNone(registry.resolve(
            "como", "new-lemma", ["occ-2"], claimed_ids={"111111"}))

    def test_batch_can_disable_inference_for_ambiguous_split(self):
        registry = CardIdentityRegistry("spanish")
        registry.seed("111111", "como", "comer", ["occ-1", "occ-2"])

        assigned = registry.assign(
            "como", "new-lemma", ["occ-1"], preferred_id="222222",
            allow_inference=False,
        )

        self.assertEqual(assigned, "222222")

    def test_registry_round_trip_and_explicit_merge(self):
        registry = CardIdentityRegistry("spanish")
        registry.seed("111111", "voy", "ir")
        registry.seed("222222", "voy", "voy")
        registry.merge("222222", "111111", "manual reconciliation")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cards.json"
            registry.save(path)
            loaded = CardIdentityRegistry.load(path, "spanish")

        self.assertEqual(loaded.records["222222"]["superseded_by"], "111111")
        self.assertEqual(loaded.resolve("voy", "voy"), "111111")


class SenseIdentityRegistryTests(unittest.TestCase):
    def test_gloss_change_with_same_occurrence_preserves_sense_id(self):
        registry = SenseIdentityRegistry("es")
        registry.seed(
            "old-sense", "card-1", "NOUN", "bench", evidence_ids=["occ-1"])

        result = registry.reconcile("card-1", [{
            "preferred_id": "new-provider-id",
            "pos": "NOUN",
            "translation": "seat; bench",
            "evidence_ids": ["occ-1"],
        }])

        self.assertEqual(result, ["old-sense"])
        record = registry.records["card-1::old-sense"]
        self.assertIn("new-provider-id", record["external_ids"])

    def test_ambiguous_sense_split_does_not_guess_progress_owner(self):
        registry = SenseIdentityRegistry("es")
        registry.seed(
            "old-sense", "card-1", "NOUN", "bank",
            evidence_ids=["occ-1", "occ-2"])

        result = registry.reconcile("card-1", [
            {"preferred_id": "new-a", "pos": "NOUN", "translation": "bank A",
             "evidence_ids": ["occ-1"]},
            {"preferred_id": "new-b", "pos": "NOUN", "translation": "bank B",
             "evidence_ids": ["occ-2"]},
        ])

        self.assertEqual(result, ["new-a", "new-b"])


if __name__ == "__main__":
    unittest.main()
