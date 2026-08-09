import json
import tempfile
import unittest
from pathlib import Path

from pipeline.step_7a_map_senses_to_lemmas import process_source


class MenuFreeLemmaMappingTests(unittest.TestCase):
    def test_inline_sense_is_mapped_without_menu(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            layers = Path(temp_dir)
            assignments_dir = layers / "sense_assignments"
            assignments_dir.mkdir(parents=True)
            with open(assignments_dir / "custom.json", "w", encoding="utf-8") as f:
                json.dump({
                    "suis": {
                        "custom-model": [{
                            "sense": "sense-opaque",
                            "examples": [0],
                            "example_ids": ["seg-1"],
                            "lemma": "être",
                            "pos": "VERB",
                            "translation": "am",
                        }],
                    },
                }, f)

            process_source(
                "custom",
                layers,
                known_lemmas_by_word={},
                examples_raw={"suis": [{"segment_id": "seg-1"}]},
                example_pos={},
            )

            with open(
                layers / "sense_assignments_lemma" / "custom.json",
                encoding="utf-8",
            ) as f:
                remapped = json.load(f)

            self.assertIn("suis|être", remapped)
            item = remapped["suis|être"]["custom-model"][0]
            self.assertEqual(item["sense"], "sense-opaque")
            self.assertEqual(item["translation"], "am")


if __name__ == "__main__":
    unittest.main()
