import unittest

from pipeline.step_5b_build_conjugations import build_morphology_fallbacks


class MorphologyFallbackTests(unittest.TestCase):
    def test_reconstructs_core_table_and_nonfinite_forms(self):
        morphology = {
            "paso": [{"lemma": "pasar", "mood": "indicativo", "tense": "presente", "person": "1s"}],
            "pasa": [{"lemma": "pasar", "mood": "indicativo", "tense": "presente", "person": "3s"}],
            "pasando": [{"lemma": "pasar", "mood": "gerundio", "tense": "gerundio", "person": ""}],
            "pasado": [{"lemma": "pasar", "mood": "participo", "tense": "participo", "person": ""}],
            "como": [{"lemma": "comer", "mood": "indicativo", "tense": "presente", "person": "1s"}],
        }

        tables, reverse = build_morphology_fallbacks(
            morphology, {"pasar"}, {"pasar": "to pass"})

        self.assertEqual(tables["pasar"]["tenses"]["Presente"],
                         ["paso", "—", "pasa", "—", "—", "—"])
        self.assertEqual(tables["pasar"]["gerund"], "pasando")
        self.assertEqual(tables["pasar"]["past_participle"], "pasado")
        self.assertEqual(tables["pasar"]["translation"], "to pass")
        self.assertNotIn("comer", tables)
        self.assertTrue(any(form == "paso" and info["lemma"] == "pasar"
                            for form, info in reverse))


if __name__ == "__main__":
    unittest.main()
