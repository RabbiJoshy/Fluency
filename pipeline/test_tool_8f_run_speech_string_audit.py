#!/usr/bin/env python3

import unittest

import tool_8f_run_speech_string_audit as audit


class SpeechStringAuditTests(unittest.TestCase):
    def test_translation_equivalent_leaves_do_not_get_a_unique_cue(self):
        senses = {
            "banco": {
                "finance": {"translation": "bank"},
                "blood": {"translation": "bank"},
                "seat": {"translation": "bench"},
            }
        }
        usable, report = audit.build_cue_inventory(senses)
        self.assertNotIn(("bank",), usable["banco"])
        self.assertEqual(usable["banco"][("bench",)], "seat")
        self.assertEqual(report["banco"]["finance"], [])

    def test_unique_literal_cue_assigns_without_a_model(self):
        senses = {
            "finance": {"translation": "bank"},
            "seat": {"translation": "bench"},
        }
        cues, _ = audit.build_cue_inventory({"banco": senses})
        decision = audit.classify_english(
            "I sat down on the benches.", senses, cues["banco"]
        )
        self.assertEqual(decision["status"], "assigned")
        self.assertEqual(decision["sense_id"], "seat")
        self.assertIn("benches", decision["matched_cues"])

    def test_conflicting_cues_abstain(self):
        senses = {
            "finance": {"translation": "bank"},
            "seat": {"translation": "bench"},
        }
        cues, _ = audit.build_cue_inventory({"banco": senses})
        decision = audit.classify_english(
            "The bank donated a bench.", senses, cues["banco"]
        )
        self.assertEqual(decision["status"], "abstain")
        self.assertEqual(decision["reason"], "conflicting_unique_english_cues")

    def test_sentence_matcher_handles_single_and_multiword_surfaces(self):
        matcher = audit.build_surface_matcher({"banco", "a lo mejor"})
        self.assertEqual(
            audit.matched_surfaces("A lo mejor voy al banco.", matcher),
            {"a lo mejor", "banco"},
        )

    def test_weak_single_function_word_is_not_a_cue(self):
        self.assertEqual(audit.raw_cues("that"), set())
        self.assertIn(("used", "to"), audit.raw_cues("used to"))


if __name__ == "__main__":
    unittest.main()
