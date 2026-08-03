#!/usr/bin/env python3

import unittest

import tool_8g_benchmark_speech_alignment as benchmark


class SpeechAlignmentBenchmarkTests(unittest.TestCase):
    def test_span_indices_support_multiword_phrases(self):
        tokens = ("i", "will", "get", "ready", "now")
        self.assertEqual(benchmark.span_indices(tokens, ("get", "ready")), {2, 3})

    def test_alignment_requires_target_to_cue_pair(self):
        row = {
            "surface": "hacer",
            "spanish": "Creo que debo hacer algo",
            "english": "I think I should do something",
            "matched_cues": ["think"],
        }
        wrong_token = benchmark.alignment_decision(row, {"inter": [(0, 1), (3, 4)]})
        self.assertFalse(wrong_token["methods"]["inter"]["accept"])
        forced_wrong = benchmark.alignment_decision(row, {"inter": [(3, 1)]})
        self.assertTrue(forced_wrong["methods"]["inter"]["accept"])

    def test_metrics_measure_precision_of_retained_examples(self):
        panel = [
            {"benchmark_id": "a", "gold_valid_exact_leaf": True},
            {"benchmark_id": "b", "gold_valid_exact_leaf": False},
            {"benchmark_id": "c", "gold_valid_exact_leaf": True},
        ]
        metrics = benchmark.classification_metrics(panel, {"a": True, "b": False, "c": False})
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall_of_valid_candidates"], 0.5)
        self.assertTrue(metrics["passes_95_percent_precision_gate"])


if __name__ == "__main__":
    unittest.main()
