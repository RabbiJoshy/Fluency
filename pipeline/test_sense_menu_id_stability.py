import unittest

from pipeline.util_5c_sense_menu_format import (
    carry_sense_ids_by_content,
    flatten_analyses_with_ids,
)


class SenseMenuIdStabilityTest(unittest.TestCase):
    def test_flatten_preserves_explicit_provider_ids(self):
        senses, ids, normalized = flatten_analyses_with_ids([{
            "headword": "abrir",
            "senses": {
                "provider-a": {"pos": "VERB", "translation": "to open", "context": "to access"},
                "provider-b": {"pos": "VERB", "translation": "to open", "context": "to allow access"},
            },
        }])

        self.assertEqual(ids, ["provider-a", "provider-b"])
        self.assertEqual(list(normalized[0]["senses"]), ids)
        self.assertEqual(senses[0]["context"], "to access")

    def test_provider_reorder_does_not_swap_existing_id_meanings(self):
        old = [{"headword": "abrir", "senses": {
            "bf0": {"pos": "VERB", "translation": "to open", "context": "to access"},
            "bf07": {"pos": "VERB", "translation": "to open", "context": "to allow access through"},
        }}]
        rebuilt = [{"headword": "abrir", "senses": {
            "bf0": {"pos": "VERB", "translation": "to open", "context": "to allow access through"},
            "bf07": {"pos": "VERB", "translation": "to open", "context": "to access"},
        }}]

        carried = carry_sense_ids_by_content(rebuilt, old)

        self.assertEqual(carried[0]["senses"]["bf0"]["context"], "to access")
        self.assertEqual(
            carried[0]["senses"]["bf07"]["context"], "to allow access through"
        )


if __name__ == "__main__":
    unittest.main()
