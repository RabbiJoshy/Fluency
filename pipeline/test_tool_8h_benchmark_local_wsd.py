#!/usr/bin/env python3

import unittest

import tool_8h_benchmark_local_wsd as benchmark


class LocalWsdBenchmarkTests(unittest.TestCase):
    def test_bilingual_context_is_optional(self):
        row = {
            "surface": "banco",
            "spanish": "Me senté en un banco.",
            "english": "I sat on a bench.",
        }
        self.assertNotIn("bench", benchmark.context_text(row))
        self.assertIn(
            "bench", benchmark.context_text(row, include_english=True)
        )

    def test_sense_text_variants(self):
        sense = {
            "headword": "banco",
            "pos": "NOUN",
            "translation": "bench",
            "context": "seat",
            "canonical_examples": [{"spanish": "Nos sentamos en un banco."}],
        }
        self.assertIn("bench", benchmark.sense_text(sense, "definition"))
        self.assertEqual(
            benchmark.sense_text(sense, "example"),
            "Ejemplo de este significado: Nos sentamos en un banco.",
        )
        combined = benchmark.sense_text(sense, "definition_example")
        self.assertIn("bench", combined)
        self.assertIn("Nos sentamos", combined)

    def test_classification_metrics(self):
        panel = [
            {
                "benchmark_id": "valid",
                "candidate_sense_id": "a",
                "gold_valid_exact_leaf": True,
            },
            {
                "benchmark_id": "invalid",
                "candidate_sense_id": "b",
                "gold_valid_exact_leaf": False,
            },
        ]
        metrics = benchmark.classification_metrics(
            panel, {"valid": "a", "invalid": "different"}
        )
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall_of_valid_candidates"], 1.0)
        self.assertEqual(metrics["true_negative"], 1)


if __name__ == "__main__":
    unittest.main()
