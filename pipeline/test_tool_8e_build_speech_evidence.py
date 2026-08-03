#!/usr/bin/env python3

import unittest

import tool_8e_build_speech_evidence as speech


class SpeechEvidenceV01Tests(unittest.TestCase):
    def test_config_builds_stable_target_identity(self):
        config = speech.validate_config({
            "schema_version": 1,
            "run_id": "test",
            "sample_size_per_target": 2,
            "targets": [{
                "surface": "banco",
                "headword": "banco",
                "pos": "noun",
                "forms": ["banco", "bancos", "banco"],
            }],
        })
        self.assertEqual(config["targets"][0]["target_id"], "banco|banco|NOUN")
        self.assertEqual(config["targets"][0]["forms"], ["banco", "bancos"])

    def test_inventory_uses_only_exact_headword_and_pos(self):
        config = speech.validate_config({
            "schema_version": 1,
            "run_id": "test",
            "sample_size_per_target": 2,
            "targets": [{
                "surface": "banco", "headword": "banco", "pos": "NOUN",
                "forms": ["banco"],
            }],
        })
        menu = {
            "banco": [
                {"headword": "banco", "senses": {
                    "money": {"pos": "NOUN", "translation": "bank", "examples": []},
                    "wrong_pos": {"pos": "VERB", "translation": "I support", "examples": []},
                }},
                {"headword": "bancar", "senses": {
                    "wrong_lemma": {"pos": "NOUN", "translation": "support", "examples": []},
                }},
            ]
        }
        inventory = speech.inventory_for(config, menu)
        self.assertEqual(
            [sense["sense_id"] for sense in inventory["targets"][0]["senses"]],
            ["money"],
        )

    def test_surface_matching_respects_word_boundaries(self):
        inventory = {
            "targets": [{"target_id": "banco|banco|NOUN", "forms": ["banco", "bancos"]}]
        }
        pattern = speech.compile_forms(inventory)["banco|banco|NOUN"]
        self.assertEqual(pattern.search("Fui al banco.").group(1), "banco")
        self.assertIsNone(pattern.search("El bancolombia no es esta palabra."))

    def test_summary_publishes_only_unique_high_assignments(self):
        inventory = {
            "targets": [{
                "target_id": "banco|banco|NOUN",
                "surface": "banco",
                "headword": "banco",
                "pos": "NOUN",
                "senses": [
                    {"sense_id": "finance", "translation": "bank"},
                    {"sense_id": "seat", "translation": "bench"},
                ],
            }]
        }
        occurrences = [
            {
                "occurrence_id": f"occ-{index}",
                "target_id": "banco|banco|NOUN",
                "spanish": f"Spanish {index}",
                "english": f"English {index}",
                "source": {"corpus_line": index},
            }
            for index in range(4)
        ]
        assignments = [
            {"occurrence_id": "occ-0", "decision": {
                "status": "assigned", "sense_ids": ["finance"], "confidence": "high",
            }},
            {"occurrence_id": "occ-1", "decision": {
                "status": "assigned", "sense_ids": ["finance"], "confidence": "medium",
            }},
            {"occurrence_id": "occ-2", "decision": {
                "status": "assigned", "sense_ids": ["finance", "seat"], "confidence": "high",
            }},
            {"occurrence_id": "occ-3", "decision": {
                "status": "abstain", "sense_ids": [], "confidence": "low",
            }},
        ]
        summary, examples, _ = speech.summarize_records(
            inventory, occurrences, assignments
        )
        target = summary["targets"][0]
        self.assertEqual(target["accepted_unique_high"], 1)
        self.assertEqual(target["ambiguous_or_below_gate"], 2)
        self.assertEqual(target["explicit_abstentions"], 1)
        self.assertEqual([row["example_id"] for row in examples], ["occ-0"])
        self.assertEqual(
            target["senses"][0]["share_of_all_sampled_occurrences"], 0.25
        )

    def test_source_ids_remain_decomposed_and_verbatim(self):
        raw = "en/doc.xml.gz\tes/doc.xml.gz\t12\t9"
        source = speech.source_record(raw)
        self.assertEqual(source["alignment_ids"], raw)
        self.assertEqual(source["spanish_document"], "es/doc.xml.gz")
        self.assertEqual(source["spanish_segment"], "9")


if __name__ == "__main__":
    unittest.main()
