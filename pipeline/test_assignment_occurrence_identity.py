import unittest

from pipeline.util_6a_assignment_format import (
    index_examples_by_identity,
    resolve_best_per_example,
    resolve_example_reference,
    resolve_routing_references,
    stamp_example_ids,
)
from pipeline.util_7a_lemma_split import merge_items


class AssignmentOccurrenceIdentityTests(unittest.TestCase):
    def test_stamp_adds_aligned_example_and_occurrence_references(self):
        assignments = {
            "no": {
                "local": [{"sense": "negation", "examples": [0, 1]}],
            },
        }
        examples = {
            "no": [
                {"id": "line-a", "occurrence_ids": ["occ-a", "occ-b"]},
                {"id": "line-b", "occurrence_ids": ["occ-c"]},
            ],
        }

        stamp_example_ids(assignments, examples)
        item = assignments["no"]["local"][0]

        self.assertEqual(item["example_ids"], ["line-a", "line-b"])
        self.assertEqual(item["occurrence_ids"], ["occ-a", "occ-b", "occ-c"])
        self.assertEqual(
            item["occurrence_refs"][1],
            {"occurrence_id": "occ-b", "example_id": "line-a", "example_index": 0},
        )

    def test_stamp_prefers_persisted_segment_identity(self):
        assignments = {"no": {"gemini": [{"sense": "n", "examples": [0]}]}}
        examples = {"no": [{
            "id": "song:12",
            "segment_id": "seg-persisted",
            "occurrence_ids": ["occ-a"],
        }]}

        stamp_example_ids(assignments, examples)

        self.assertEqual(
            assignments["no"]["gemini"][0]["example_ids"],
            ["seg-persisted"],
        )

    def test_builder_join_prefers_stable_id_over_stale_index(self):
        examples = [
            {"id": "legacy-b", "segment_id": "seg-b"},
            {"id": "legacy-a", "segment_id": "seg-a"},
        ]
        identity_index = index_examples_by_identity(examples)

        resolved = resolve_example_reference(
            {"ex_idx": 0, "ex_id": "seg-a"},
            examples,
            identity_index,
        )

        self.assertIs(resolved, examples[1])

    def test_missing_stable_id_never_retargets_to_numeric_index(self):
        examples = [{"id": "new-line", "segment_id": "seg-new"}]

        self.assertIsNone(resolve_example_reference(
            {"ex_idx": 0, "ex_id": "seg-deleted"},
            examples,
        ))

    def test_stable_routing_reference_survives_reorder(self):
        examples = [
            {"segment_id": "seg-b"},
            {"segment_id": "seg-a"},
        ]

        self.assertEqual(resolve_routing_references(
            [{"example_index": 0, "example_id": "seg-a"}],
            examples,
        ), [1])

    def test_stable_example_id_prevents_reorder_retargeting(self):
        word_data = {
            "local": [{
                "sense": "seat",
                "examples": [0],
                "example_ids": ["line-b"],
            }],
            "gemini": [{
                "sense": "finance",
                "examples": [1],
                "example_ids": ["line-b"],
            }],
        }

        resolved = resolve_best_per_example(word_data)
        claims = [entry for entries in resolved.values() for entry in entries]

        # Both stale numeric indices name the same stable line. Only the
        # higher-priority method may win; the line cannot be claimed twice.
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["ex_id"], "line-b")
        self.assertEqual(claims[0]["method"], "gemini")

    def test_profile_can_prioritize_a_custom_non_gemini_adapter(self):
        resolved = resolve_best_per_example({
            "gemini": [{
                "sense": "old", "examples": [0], "example_ids": ["seg-1"],
            }],
            "my-local-wsd": [{
                "sense": "new", "examples": [0], "example_ids": ["seg-1"],
            }],
        }, method_priority={"my-local-wsd": 100})

        self.assertEqual(resolved["new"][0]["method"], "my-local-wsd")

    def test_occurrences_in_one_teaching_line_can_resolve_independently(self):
        word_data = {
            "gemini": [
                {
                    "sense": "command",
                    "examples": [0],
                    "example_ids": ["line-a"],
                    "occurrence_refs": [{
                        "occurrence_id": "occ-a",
                        "example_id": "line-a",
                        "example_index": 0,
                    }],
                },
                {
                    "sense": "vision",
                    "examples": [0],
                    "example_ids": ["line-a"],
                    "occurrence_refs": [{
                        "occurrence_id": "occ-b",
                        "example_id": "line-a",
                        "example_index": 0,
                    }],
                },
            ],
        }

        resolved = resolve_best_per_example(word_data)

        self.assertEqual(resolved["command"][0]["occurrence_ids"], ["occ-a"])
        self.assertEqual(resolved["vision"][0]["occurrence_ids"], ["occ-b"])
        self.assertEqual(resolved["command"][0]["ex_id"], "line-a")

    def test_same_sense_occurrences_share_one_teaching_example(self):
        word_data = {
            "gemini": [{
                "sense": "negation",
                "examples": [0],
                "example_ids": ["line-a"],
                "occurrence_refs": [
                    {"occurrence_id": "occ-a", "example_id": "line-a", "example_index": 0},
                    {"occurrence_id": "occ-b", "example_id": "line-a", "example_index": 0},
                ],
            }],
        }

        resolved = resolve_best_per_example(word_data)

        self.assertEqual(len(resolved["negation"]), 1)
        self.assertEqual(
            resolved["negation"][0]["occurrence_ids"], ["occ-a", "occ-b"])

    def test_lemma_merge_keeps_example_ids_aligned(self):
        existing = [{
            "sense": "negation",
            "examples": [0],
            "example_ids": ["line-a"],
            "occurrence_refs": [{
                "occurrence_id": "occ-a",
                "example_id": "line-a",
                "example_index": 0,
            }],
        }]
        incoming = [{
            "sense": "negation",
            "examples": [1],
            "example_ids": ["line-b"],
            "occurrence_refs": [{
                "occurrence_id": "occ-b",
                "example_id": "line-b",
                "example_index": 1,
            }],
        }]

        merged = merge_items(existing, incoming)[0]

        self.assertEqual(merged["examples"], [0, 1])
        self.assertEqual(merged["example_ids"], ["line-a", "line-b"])
        self.assertEqual(merged["occurrence_ids"], ["occ-a", "occ-b"])

    def test_lemma_merge_uses_stable_id_not_reordered_index(self):
        existing = [{
            "sense": "seat",
            "examples": [0],
            "example_ids": ["line-b"],
        }]
        incoming = [{
            "sense": "seat",
            "examples": [1],
            "example_ids": ["line-b"],
        }]

        merged = merge_items(existing, incoming)[0]

        self.assertEqual(merged["examples"], [0])
        self.assertEqual(merged["example_ids"], ["line-b"])


if __name__ == "__main__":
    unittest.main()
