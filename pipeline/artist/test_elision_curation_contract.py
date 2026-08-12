import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURATIONS = PROJECT_ROOT / "Artists" / "curations"


class ElisionCurationContractTests(unittest.TestCase):
    def test_reviewed_restorations_do_not_regress_to_suffix_guesses(self):
        expected = {
            "actitu'": "actitud",
            "ajedre'": "ajedrez",
            "azúca'": "azúcar",
            "confia'": "confiar",
            "cru'": "cruz",
            "feli'": "feliz",
            "felicida'": "felicidad",
            "gonzále'": "gonzález",
            "mai'": "mai",
            "mayagüe'": "mayagüez",
            "oportunida'": "oportunidad",
            "patá'": "patada",
            "rodrígue'": "rodríguez",
            "segui'": "seguir",
            "ta'": "está",
            "uste'": "usted",
        }
        with open(CURATIONS / "elision_mapping.json", encoding="utf-8") as handle:
            mappings = json.load(handle)
        active = {
            row.get("elided_word"): row.get("target_word")
            for row in mappings
            if row.get("action") == "merge"
            and row.get("merge_type") in ("elision_pair", "elided_only")
        }
        self.assertEqual(
            {word: active.get(word) for word in expected}, expected)

    def test_apostrophized_ta_is_restored_without_whitelisting_bare_ta(self):
        with open(CURATIONS / "noise.json", encoding="utf-8") as handle:
            noise = json.load(handle)
        self.assertIn("ta", noise["drop"])
        self.assertNotIn("ta", noise["keep"])

    def test_routing_bucket_corrections_are_explicit(self):
        with open(CURATIONS / "proper_nouns.json", encoding="utf-8") as handle:
            proper = json.load(handle)
        with open(CURATIONS / "noise.json", encoding="utf-8") as handle:
            noise = json.load(handle)
        with open(CURATIONS / "extra_english.json", encoding="utf-8") as handle:
            english = json.load(handle)
        self.assertNotIn("bori", proper["drop"])
        self.assertNotIn("leggo", proper["drop"])
        self.assertIn("leggo", noise["drop"])
        self.assertIn("ay", noise["keep"])
        self.assertNotIn("pal'", english["entries"])
        self.assertNotIn("move'", english["entries"])


if __name__ == "__main__":
    unittest.main()
