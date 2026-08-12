#!/usr/bin/env python3
"""Focused regression tests for structured curation proposal operations."""

import unittest

from pipeline.artist.tool_4a_apply_proposals import (
    apply_proposal,
    blocked_reason,
    operation_target,
    proposal_operation,
)


class StructuredProposalTests(unittest.TestCase):
    def test_prose_is_never_parsed_as_keep(self):
        proposal = {
            "kind": "noise",
            "word": "bo",
            "proposed": "keep (real word)",
        }
        self.assertIsNone(proposal_operation(proposal))
        self.assertIn("structured operation", blocked_reason(proposal, None, {}))

    def test_add_keep_targets_keep_section(self):
        proposal = {"kind": "noise", "word": "bo", "operation": "add_keep"}
        operation = proposal_operation(proposal)
        self.assertEqual(("noise.json", "keep", False),
                         operation_target(proposal, operation))
        doc = {"drop": ["bo"], "keep": []}
        self.assertTrue(apply_proposal(proposal, doc, operation, "keep"))
        self.assertEqual(["bo"], doc["keep"])
        self.assertEqual(["bo"], doc["drop"])

    def test_remove_drop_is_explicit(self):
        proposal = {"kind": "cognate", "word": "combo",
                    "operation": "remove_drop"}
        operation = proposal_operation(proposal)
        filename, section, remove = operation_target(proposal, operation)
        self.assertEqual(("cognates.json", "drop", True),
                         (filename, section, remove))
        doc = {"drop": ["combo", "hotel"], "keep": []}
        self.assertTrue(apply_proposal(
            proposal, doc, operation, section, remove=remove))
        self.assertEqual(["hotel"], doc["drop"])

    def test_replace_elision_updates_generated_target(self):
        proposal = {
            "kind": "elision", "word": "ta'", "proposed": "está",
            "target_lemma": "estar", "operation": "replace_elision",
            "source": "review",
        }
        operation = proposal_operation(proposal)
        self.assertEqual(
            ("elision_mapping.json", None, False),
            operation_target(proposal, operation))
        doc = [{
            "action": "merge", "merge_type": "elision_pair",
            "elided_word": "ta'", "full_word": "tas",
            "target_word": "tas", "display_form": "ta'",
        }]
        self.assertTrue(apply_proposal(proposal, doc, operation, None))
        self.assertEqual("está", doc[0]["target_word"])
        self.assertEqual("estar", doc[0]["target_lemma"])
        self.assertNotIn("full_word", doc[0])

    def test_occurrence_override_requires_stable_ids(self):
        proposal = {"kind": "noise", "word": "ta",
                    "operation": "add_occurrence_override",
                    "occurrence_action": "normalize",
                    "normalization_target": "está"}
        self.assertIn("stable occurrence/example IDs",
                      blocked_reason(proposal, proposal_operation(proposal), {}))
        proposal["occurrence_ids"] = ["occ_123"]
        self.assertIn("no safe pre-routing materializer",
                      blocked_reason(
                          proposal, proposal_operation(proposal), {}))

    def test_legacy_echo_operations_are_narrowly_supported(self):
        self.assertEqual("add_drop", proposal_operation({
            "kind": "echo_reduplication", "proposed": "noise"}))
        self.assertEqual("add_occurrence_override", proposal_operation({
            "kind": "echo_reduplication", "proposed": "drop_occurrences"}))


if __name__ == "__main__":
    unittest.main()
