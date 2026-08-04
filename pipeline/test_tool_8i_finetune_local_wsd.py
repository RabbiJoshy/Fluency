#!/usr/bin/env python3

import unittest

import tool_8i_finetune_local_wsd as finetune


class LocalWsdFinetuneTests(unittest.TestCase):
    def test_query_can_include_bilingual_support(self):
        spanish_only = finetune.query_text("banco", "Me senté en un banco.")
        bilingual = finetune.query_text(
            "banco", "Me senté en un banco.", "I sat on a bench.", True
        )
        self.assertNotIn("bench", spanish_only)
        self.assertIn("bench", bilingual)

    def test_training_pairs_use_sibling_negatives(self):
        menu = {
            "banco": [
                {
                    "headword": "banco",
                    "senses": {
                        "seat": {
                            "pos": "NOUN",
                            "translation": "bench",
                            "context": "seat",
                            "examples": [
                                {
                                    "original": "Me senté en un banco.",
                                    "translated": "I sat on a bench.",
                                }
                            ],
                        },
                        "money": {
                            "pos": "NOUN",
                            "translation": "bank",
                            "context": "finance",
                            "examples": [
                                {
                                    "original": "Fui al banco.",
                                    "translated": "I went to the bank.",
                                }
                            ],
                        },
                    },
                }
            ]
        }
        pairs, stats = finetune.build_training_pairs(menu, {"banco"}, 10, 1)
        self.assertEqual(stats["selected_positives"], 2)
        self.assertEqual(len(pairs), 4)
        self.assertEqual(sorted(label for _, _, label in pairs), [0, 0, 1, 1])


if __name__ == "__main__":
    unittest.main()
