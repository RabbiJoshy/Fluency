import unittest

from pipeline.tool_6a_tag_example_pos import example_id_signature


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


if __name__ == "__main__":
    unittest.main()
