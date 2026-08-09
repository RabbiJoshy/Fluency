import unittest

from pipeline.tool_6a_migrate_example_ids import _build_id_lookup, _migrate_items


class AssignmentMigrationTests(unittest.TestCase):
    def _stats(self):
        return {
            "total": 0,
            "already_had": 0,
            "migrated": 0,
            "occurrence_migrated": 0,
            "missing": 0,
        }

    def test_legacy_line_id_upgrades_without_trusting_reordered_index(self):
        examples = {
            "banco": [
                {"id": "song:2", "segment_id": "seg-b", "occurrence_ids": ["occ-b"]},
                {"id": "song:1", "segment_id": "seg-a", "occurrence_ids": ["occ-a"]},
            ],
        }
        items = [{
            "sense": "seat",
            "examples": [0],
            "example_ids": ["song:1"],
        }]

        _migrate_items(items, _build_id_lookup(examples)["banco"], self._stats())

        self.assertEqual(items[0]["example_ids"], ["seg-a"])
        self.assertEqual(items[0]["occurrence_ids"], ["occ-a"])
        self.assertEqual(items[0]["occurrence_refs"][0]["example_index"], 1)

    def test_missing_reference_keeps_alignment_and_does_not_retarget(self):
        examples = {"banco": [{"segment_id": "seg-new"}]}
        items = [{
            "sense": "seat",
            "examples": [0],
            "example_ids": ["seg-deleted"],
        }]
        stats = self._stats()

        _migrate_items(items, _build_id_lookup(examples)["banco"], stats)

        self.assertEqual(items[0]["example_ids"], ["seg-deleted"])
        self.assertNotIn("occurrence_refs", items[0])
        self.assertEqual(stats["missing"], 1)


if __name__ == "__main__":
    unittest.main()
