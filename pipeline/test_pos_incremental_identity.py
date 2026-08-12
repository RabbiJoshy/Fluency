import unittest

from pipeline.tool_6a_tag_example_pos import (
    example_id_signature,
    legacy_example_id_signature,
    remap_pos_for_reordered_ids,
)


class PosIncrementalIdentityTests(unittest.TestCase):
    def test_reorder_changes_signature_for_numeric_pos_output(self):
        before = [{"id": "line-a"}, {"id": "line-b"}]
        after = [{"id": "line-b"}, {"id": "line-a"}]

        self.assertNotEqual(
            example_id_signature(before),
            example_id_signature(after),
        )

    def test_same_order_is_incrementally_stable(self):
        examples = [{"id": "line-a"}, {"id": "line-b"}]

        self.assertEqual(
            example_id_signature(examples),
            ["line-a", "line-b"],
        )

    def test_persisted_segment_id_precedes_shifting_legacy_line_id(self):
        before = [{"id": "song:4", "segment_id": "seg-a"}]
        after = [{"id": "song:9", "segment_id": "seg-a"}]

        self.assertEqual(
            example_id_signature(before),
            example_id_signature(after),
        )

    def test_legacy_signature_can_upgrade_without_retagging(self):
        examples = [{"id": "song:4", "segment_id": "seg-a"}]

        self.assertEqual(legacy_example_id_signature(examples), ["song:4"])
        self.assertEqual(example_id_signature(examples), ["seg-a"])

    def test_pos_tags_follow_stable_ids_through_reorder(self):
        remapped = remap_pos_for_reordered_ids(
            {"0": "VERB", "1": "NOUN"},
            ["line-a", "line-b"],
            ["line-b", "line-a"],
        )

        self.assertEqual(remapped, {"0": "NOUN", "1": "VERB"})

    def test_duplicate_ids_are_remapped_by_occurrence_order(self):
        remapped = remap_pos_for_reordered_ids(
            {"0": "VERB", "1": "NOUN", "2": "ADJ"},
            ["same", "other", "same"],
            ["same", "same", "other"],
        )

        self.assertEqual(remapped, {"0": "VERB", "1": "ADJ", "2": "NOUN"})

    def test_changed_identity_set_requires_retag(self):
        self.assertIsNone(remap_pos_for_reordered_ids(
            {"0": "VERB"}, ["line-a"], ["line-b"]))

    def test_actual_example_order_overrides_a_legacy_sorted_signature(self):
        actual_ids = legacy_example_id_signature([
            {"id": "line-z"}, {"id": "line-a"},
        ])

        self.assertEqual(actual_ids, ["line-z", "line-a"])
        self.assertNotEqual(actual_ids, sorted(actual_ids))


if __name__ == "__main__":
    unittest.main()
