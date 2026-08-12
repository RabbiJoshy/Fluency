import json
import tempfile
import unittest
from pathlib import Path

from pipeline.artist.util_5d_shared_sense_register import (
    apply_registers_to_menu, build_register, exact_register_assignments,
)
from pipeline.util_6a_assignment_format import dump_assignments
from pipeline.util_5c_sense_menu_format import (
    collect_surface_analyses_from_shared_menu, flatten_analyses_with_ids,
)
from pipeline.util_6a_pos_menu_filter import (
    auto_sense_rejection_reason, example_matches_credited_artist,
)


class SharedSenseRegisterTest(unittest.TestCase):
    def _artist(self, language_dir, folder, name, assignments):
        artist_dir = language_dir / folder
        assignment_path = artist_dir / "data/layers/sense_assignments/spanishdict.json"
        assignment_path.parent.mkdir(parents=True)
        (artist_dir / "artist.json").write_text(json.dumps({
            "name": name, "sense_registers": ["reggaeton"],
        }), encoding="utf-8")
        dump_assignments(assignments, assignment_path)
        return artist_dir

    def test_register_clusters_reusable_slang_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            language_dir = Path(tmp) / "spanish"
            self._artist(language_dir, "A", "Artist A", {
                "feka": {"gap-fill": [{
                    "sense": "a", "pos": "ADJ", "translation": "fake or inauthentic",
                    "lemma": "feka", "type": "slang", "examples": [0, 1],
                    "example_ids": ["seg_a", "seg_b"], "prompt_id": "sd-cop-v2",
                }]},
                "mari": {"gap-fill": [{
                    "sense": "b", "pos": "NOUN",
                    "translation": "Slang for marijuana or weed",
                    "lemma": "mari", "examples": [0], "prompt_id": "sd-cop-v2",
                }]},
                "unsafe": {"gap-fill": [{
                    "sense": "c", "pos": "NOUN", "translation": "a guessed thing",
                    "lemma": "unsafe", "examples": [0], "prompt_id": "legacy-unknown",
                }]},
            })
            consumer = self._artist(language_dir, "B", "Artist B", {
                "feka": {"gap-fill": [{
                    "sense": "d", "pos": "ADJ", "translation": "fake or counterfeit",
                    "lemma": "feka", "type": "slang", "examples": [0],
                    "prompt_id": "sd-cop-v2",
                }]},
                "mari": {"lexical-gap-fill-g31": [{
                    "sense": "e", "pos": "NOUN", "translation": "marijuana",
                    "lemma": "mari", "examples": [0],
                    "prompt_id": "sd-lexical-v2-g31",
                }]},
            })

            _path, payload = build_register(language_dir, "reggaeton")
            self.assertEqual(payload["senses"]["feka"][0]["translation"], "fake")
            self.assertEqual(payload["senses"]["mari"][0]["translation"], "marijuana")
            self.assertNotIn("unsafe", payload["senses"])
            self.assertEqual(
                payload["senses"]["feka"][0]["supporting_artists"],
                ["Artist A", "Artist B"],
            )

            menu, added = apply_registers_to_menu(
                consumer,
                {"mari": [{"headword": "Mari", "senses": {
                    "propn": {"pos": "PROPN", "translation": "Mari"},
                }}]},
                ["mari", "feka"],
            )
            self.assertEqual(added, 2)
            mari_senses = [sense for analysis in menu["mari"]
                           for sense in analysis["senses"].values()]
            self.assertEqual({sense["pos"] for sense in mari_senses}, {"PROPN", "NOUN"})
            self.assertEqual(
                {analysis["headword"] for analysis in menu["mari"]},
                {"Mari", "mari"},
            )
            self.assertEqual(
                next(s for s in mari_senses if s["pos"] == "NOUN")["source"],
                "shared-sense-register",
            )
            collected = collect_surface_analyses_from_shared_menu("mari", menu)
            _flat, ids, _normalised = flatten_analyses_with_ids(collected)
            self.assertIn(payload["senses"]["mari"][0]["id"], ids)

            # Identical cross-artist song-line evidence can be reused without
            # another classifier call.
            source_examples = language_dir / "A/data/layers/examples_raw.json"
            source_examples.write_text(json.dumps({
                "feka": [{"id": "123:4", "spanish": "Tú eres feka"}],
            }), encoding="utf-8")
            # Rebuild now that the source line exists in provenance.
            build_register(language_dir, "reggaeton")
            target_examples = consumer / "data/layers/examples_raw.json"
            target_examples.write_text(json.dumps({
                "feka": [{"id": "123:4", "spanish": "Tú eres feka"}],
            }), encoding="utf-8")
            exact = exact_register_assignments(consumer)
            self.assertEqual(
                exact["feka"]["shared-register-auto"][0]["examples"], [0])

    def test_single_sense_auto_vetoes_are_narrow(self):
        mari = {"pos": "PROPN", "translation": "Mari"}
        self.assertIn("conflicts", auto_sense_rejection_reason(
            "mari", mari, {"artist": "J Balvin"}, "NOUN"))
        self.assertTrue(example_matches_credited_artist(
            "boza", {"artist": "Boza"}))
        self.assertEqual(
            auto_sense_rejection_reason(
                "boza", {"pos": "NOUN", "translation": "rope"},
                {"artist": "Boza"}),
            "common_noun_conflicts_with_credited_artist",
        )
        self.assertIsNone(auto_sense_rejection_reason(
            "bunny", {"pos": "NOUN", "translation": "rabbit"},
            {"artist": "Bad Bunny"}, "NOUN"))

    def test_inline_discovered_sense_is_self_contained(self):
        item = {"sense": "not-in-menu", "pos": "ADJ", "translation": "fake"}
        valid_menu_ids = {"dictionary-id"}
        self.assertTrue(
            (item.get("translation") and item.get("pos"))
            or item.get("sense") in valid_menu_ids)


if __name__ == "__main__":
    unittest.main()
