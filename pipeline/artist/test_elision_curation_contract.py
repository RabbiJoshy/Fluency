import json
import unittest
from pathlib import Path

from pipeline.artist.step_3a_merge_elisions import (
    load_spanish_forms,
    trailing_apos_restore,
)
from pipeline.artist.tool_3b_compact_elision_curations import compact


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURATIONS = PROJECT_ROOT / "Artists" / "curations"


class ElisionCurationContractTests(unittest.TestCase):
    def test_reviewed_restorations_are_rule_derived_not_manual_guesses(self):
        expected = {
            "actitu'": "actitud",
            "ajedre'": "ajedrez",
            "azúca'": "azúcar",
            "confia'": "confiar",
            "cru'": "cruz",
            "feli'": "feliz",
            "felicida'": "felicidad",
            "gonzále'": "gonzález",
            "mayagüe'": "mayagüez",
            "oportunida'": "oportunidad",
            "rodrígue'": "rodríguez",
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
        self.assertTrue(set(expected).isdisjoint(active))
        known = load_spanish_forms()
        self.assertEqual({
            word: (trailing_apos_restore(word, known) or (None,))[0]
            for word in expected
        }, expected)
        self.assertIsNone(trailing_apos_restore("mai'", known))

    def test_elision_curation_has_no_inert_rows(self):
        with open(CURATIONS / "elision_mapping.json", encoding="utf-8") as handle:
            mappings = json.load(handle)
        compacted, removed = compact(mappings)
        self.assertEqual(compacted, mappings)
        self.assertEqual(sum(removed.values()), 0)

    def test_mixed_lexical_surfaces_are_not_globally_noise(self):
        with open(CURATIONS / "noise.json", encoding="utf-8") as handle:
            noise = json.load(handle)
        for word in ("bo", "lu", "ma", "mor", "na", "po", "ta", "to",
                     "tá", "tó", "wua"):
            self.assertNotIn(word, noise["drop"])

    def test_routing_bucket_corrections_are_explicit(self):
        with open(CURATIONS / "proper_nouns.json", encoding="utf-8") as handle:
            proper = json.load(handle)
        with open(CURATIONS / "noise.json", encoding="utf-8") as handle:
            noise = json.load(handle)
        with open(CURATIONS / "extra_english.json", encoding="utf-8") as handle:
            english = json.load(handle)
        self.assertNotIn("bori", proper["drop"])
        self.assertNotIn("arcángel", proper["drop"])
        self.assertNotIn("leggo", proper["drop"])
        self.assertEqual(proper["keep"], [])
        self.assertIn("leggo", noise["drop"])
        self.assertIn("ay", noise["keep"])
        self.assertNotIn("pal'", english["entries"])
        self.assertNotIn("move'", english["entries"])

    def test_curated_mwes_do_not_duplicate_constructions_or_skips(self):
        with open(CURATIONS / "curated_mwes.json", encoding="utf-8") as handle:
            curated = json.load(handle)
        with open(CURATIONS / "skip_mwes.json", encoding="utf-8") as handle:
            skipped = set(json.load(handle)["entries"])
        entries = {key for key in curated if not key.startswith("_")}
        construction_fragments = {
            "voy a", "va a", "vas a", "van a", "iba a", "vamo' a",
            "va' a", "vo' a", "te vo'a", "me voy a", "te voy a", "se va a",
            "hay que", "sé que", "creo que", "dice que", "dicen que",
            "dijo que", "quiero que", "quiere que", "tienen que",
        }
        self.assertFalse(entries & skipped)
        self.assertFalse(entries & construction_fragments)
        self.assertEqual(curated["hace tiempo"], "for some time; a while ago")


if __name__ == "__main__":
    unittest.main()
