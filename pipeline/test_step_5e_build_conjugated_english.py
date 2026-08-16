import sys
import types
import unittest
from unittest import mock

from pipeline.step_5e_build_conjugated_english import (
    build_analysis_forms,
    conjugate_translation,
    nonfinite_translation,
)


class EnglishProductionFormsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake = types.ModuleType("lemminflect")
        known = {
            ("go", "VBD"): ("went",),
            ("give", "VBZ"): ("gives",),
            ("give", "VBD"): ("gave",),
            ("give", "VBG"): ("giving",),
            ("give", "VBN"): ("given",),
            ("speak", "VBG"): ("speaking",),
            ("speak", "VBN"): ("spoken",),
        }
        fake.getInflection = lambda head, tag: known.get((head, tag), ())
        cls._module_patch = mock.patch.dict(sys.modules, {"lemminflect": fake})
        cls._module_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._module_patch.stop()

    def test_keeps_person_matched_indicative_forms(self):
        self.assertEqual(
            conjugate_translation("to go", "pretérito-perfecto-simple", 2),
            "he went",
        )
        self.assertEqual(
            conjugate_translation("to be ready", "presente", 0),
            "I am ready",
        )

    def test_builds_conditional_and_command_rows(self):
        self.assertEqual(
            conjugate_translation("to give up", "presente", 0, mood="condicional"),
            "I would give up",
        )
        self.assertEqual(
            conjugate_translation("to give up", "afirmativo", 1, mood="imperativo"),
            "give up!",
        )
        self.assertEqual(
            conjugate_translation("to give up", "afirmativo", 3, mood="imperativo"),
            "let's give up!",
        )
        self.assertEqual(
            conjugate_translation("to give up", "negativo", 1, mood="imperativo"),
            "don't give up!",
        )
        self.assertEqual(
            conjugate_translation("to give up", "negativo", 3, mood="imperativo"),
            "let's not give up!",
        )
        self.assertIsNone(
            conjugate_translation("to give up", "afirmativo", 0, mood="imperativo")
        )

    def test_builds_irregular_nonfinite_forms(self):
        self.assertEqual(nonfinite_translation("to speak", "gerundio", "gerundio"), "speaking")
        self.assertEqual(nonfinite_translation("to speak", "participo", "participo"), "spoken")
        self.assertEqual(nonfinite_translation("to be on", "gerundio", "gerundio"), "being on")
        self.assertEqual(nonfinite_translation("to be on", "participo", "participo"), "been on")

    def test_abstains_from_modal_forms_that_english_cannot_inflect(self):
        rows = build_analysis_forms("can")

        self.assertIn("indicativo/presente", rows)
        self.assertIn("indicativo/pretérito-perfecto-simple", rows)
        self.assertNotIn("indicativo/futuro", rows)
        self.assertNotIn("condicional/presente", rows)
        self.assertNotIn("imperativo/afirmativo", rows)
        self.assertNotIn("gerundio/gerundio", rows)
        self.assertNotIn("participo/participo", rows)


if __name__ == "__main__":
    unittest.main()
