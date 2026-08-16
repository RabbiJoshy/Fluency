import unittest
import json

from pipeline.step_5b_build_conjugations import (
    STANDARD_PRONOUNS,
    build_conjugation_entry,
    build_morphology_fallbacks,
)


class _FakeConjugationResult:
    def __init__(self, payload):
        self.payload = payload

    def to_json(self):
        return json.dumps(self.payload)


class _FakeConjugator:
    def conjugate(self, _verb):
        forms = ["hubiera", "hubieras", "hubiera", "hubiéramos", "hubierais", "hubieran"]
        persons = [
            {"pr": pronoun, "c": [f"{pronoun} {form}"]}
            for pronoun, form in zip(STANDARD_PRONOUNS, forms)
        ]
        return _FakeConjugationResult({
            "moods": {"subjuntivo": {"pretérito-imperfecto-1": persons}},
        })


class MorphologyFallbackTests(unittest.TestCase):
    def test_builds_haber_imperfect_subjunctive_ra_paradigm(self):
        entry = build_conjugation_entry("haber", _FakeConjugator(), {})

        self.assertEqual(entry["tenses"]["Subj. Imperfecto"], [
            "hubiera", "hubieras", "hubiera",
            "hubiéramos", "hubierais", "hubieran",
        ])

    def test_reconstructs_core_table_and_nonfinite_forms(self):
        morphology = {
            "paso": [{"lemma": "pasar", "mood": "indicativo", "tense": "presente", "person": "1s"}],
            "pasa": [{"lemma": "pasar", "mood": "indicativo", "tense": "presente", "person": "3s"}],
            "pasando": [{"lemma": "pasar", "mood": "gerundio", "tense": "gerundio", "person": ""}],
            "pasado": [{"lemma": "pasar", "mood": "participo", "tense": "participo", "person": ""}],
            "pasara": [{"lemma": "pasar", "mood": "subjuntivo", "tense": "pretérito-imperfecto", "person": "1s"}],
            "pasaras": [{"lemma": "pasar", "mood": "subjuntivo", "tense": "pretérito-imperfecto", "person": "2s"}],
            "pasáramos": [{"lemma": "pasar", "mood": "subjuntivo", "tense": "pretérito-imperfecto", "person": "1p"}],
            "como": [{"lemma": "comer", "mood": "indicativo", "tense": "presente", "person": "1s"}],
        }

        tables, reverse = build_morphology_fallbacks(
            morphology, {"pasar"}, {"pasar": "to pass"})

        self.assertEqual(tables["pasar"]["tenses"]["Presente"],
                         ["paso", "—", "pasa", "—", "—", "—"])
        self.assertEqual(tables["pasar"]["tenses"]["Subj. Imperfecto"],
                         ["pasara", "pasaras", "—", "pasáramos", "—", "—"])
        self.assertEqual(tables["pasar"]["gerund"], "pasando")
        self.assertEqual(tables["pasar"]["past_participle"], "pasado")
        self.assertEqual(tables["pasar"]["translation"], "to pass")
        self.assertNotIn("comer", tables)
        self.assertTrue(any(form == "paso" and info["lemma"] == "pasar"
                            for form, info in reverse))


if __name__ == "__main__":
    unittest.main()
