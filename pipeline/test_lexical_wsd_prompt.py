import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from step_6c_assign_senses_gemini import (
    _checkpoint_path,
    build_classify_or_propose_prompt,
    covered_example_indices,
    generation_config,
    resolve_custom_menu_analyses,
)
from util_6a_assignment_format import stamp_provenance
from util_6a_method_priority import METHOD_PRIORITY
from util_6a_prompt_registry import (
    CURRENT_SD_POLICY_ID, accepted_prompt_ids, load_prompt_policy, load_registry,
)
from artist.step_8b_assemble_artist_vocabulary import resolve_sense_provenance


class LexicalWsdPromptTests(unittest.TestCase):
    def test_restored_inflections_resolve_to_existing_menu_before_wsd(self):
        menu = {
            "todo": [{"headword": "todo", "senses": {
                "t": {"pos": "ADJ", "translation": "all"}}}],
            "sentado": [{"headword": "sentado", "senses": {
                "s": {"pos": "ADJ", "translation": "seated"}}}],
            "dar": [{"headword": "dar", "senses": {
                "d": {"pos": "VERB", "translation": "to give"}}}],
            "morir": [{"headword": "morir", "senses": {
                "m": {"pos": "VERB", "translation": "to die"}}}],
        }
        conjugations = {"des": [{"lemma": "dar"}]}

        self.assertEqual(resolve_custom_menu_analyses(
            "todito", menu)[0], "todo")
        self.assertEqual(resolve_custom_menu_analyses(
            "sentadita", menu)[0], "sentado")
        self.assertEqual(resolve_custom_menu_analyses(
            "des", menu, conjugation_reverse=conjugations)[0], "dar")
        self.assertEqual(resolve_custom_menu_analyses(
            "morirse", menu)[0], "morir")

    def test_prompt_keeps_slang_proposals_but_removes_tagging_authority(self):
        prompt = build_classify_or_propose_prompt([{
            "word": "bicho",
            "lemma": "bicho",
            "senses": [{"pos": "NOUN", "translation": "bug"}],
            "ids": ["abc"],
            "examples": [{"spanish": "ese bicho", "english": "that guy",
                          "pos": "NOUN"}],
        }], "Puerto Rican Spanish")

        self.assertIn("genuine lexical slang meaning", prompt)
        self.assertIn('"abstain_reason"', prompt)
        self.assertIn("construction_only", prompt)
        self.assertIn("EXACTLY one call for every numbered example", prompt)
        self.assertIn("copy one shown menu id", prompt)
        self.assertIn("never leave sense, proposed, and", prompt)
        self.assertNotIn('"type":', prompt)
        self.assertNotIn('"construction":', prompt)
        self.assertNotIn('"pos_verdict":', prompt)

    def test_prompt_provenance_only_stamps_selected_model_methods(self):
        assignments = {
            "bicho": {
                "spanishdict-auto": [{"sense": "a", "examples": [0]}],
                "spanishdict-lexical-g31": [{"sense": "b", "examples": [1]}],
            },
        }
        stamp_provenance(assignments, "sd-lexical-v1-g31", "2026-08-09T00:00Z",
                         methods={"spanishdict-lexical-g31"})

        self.assertNotIn("prompt_id", assignments["bicho"]["spanishdict-auto"][0])
        self.assertEqual(
            assignments["bicho"]["spanishdict-lexical-g31"][0]["prompt_id"],
            "sd-lexical-v1-g31",
        )

    def test_checkpoint_identity_changes_with_prompt_or_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _checkpoint_path(tmp, "sense_assignments/spanishdict.json",
                                    "p1", "m1")
            self.assertNotEqual(base, _checkpoint_path(
                tmp, "sense_assignments/spanishdict.json", "p2", "m1"))
            self.assertNotEqual(base, _checkpoint_path(
                tmp, "sense_assignments/spanishdict.json", "p1", "m2"))

    def test_stable_example_identity_survives_reordering(self):
        examples = [{"segment_id": "seg_new"}, {"segment_id": "seg_done"}]
        items = [{"examples": [0], "example_ids": ["seg_done"]}]
        self.assertEqual(covered_example_indices(items, examples), {1})

    def test_stable_identity_prevents_reused_index_false_coverage(self):
        examples = [{"segment_id": "seg_different"}]
        items = [{"examples": [0], "example_ids": ["seg_old"]}]
        self.assertEqual(covered_example_indices(items, examples), set())

    def test_legacy_index_only_assignment_still_covers(self):
        examples = [{"segment_id": "seg_a"}, {"segment_id": "seg_b"}]
        items = [{"examples": [1]}]
        self.assertEqual(covered_example_indices(items, examples), {1})

    def test_replacement_target_never_trusts_numeric_only_legacy_index(self):
        examples = [{"segment_id": "seg-current"}]
        items = [{"examples": [0], "prompt_id": "legacy-unknown"}]
        self.assertEqual(covered_example_indices(
            items, examples, allow_legacy_indices=False), set())

    def test_occurrence_identity_covers_regrouped_example(self):
        examples = [{"segment_id": "seg_new", "occurrence_ids": ["occ_done"]}]
        items = [{"examples": [4], "occurrence_refs": [{
            "occurrence_id": "occ_done", "example_id": "seg_old",
            "example_index": 4,
        }]}]
        self.assertEqual(covered_example_indices(items, examples), {0})

    def test_generation_config_omits_deprecated_sampling_for_gemini_35(self):
        self.assertEqual(generation_config("gemini-3.5-flash-lite"), {
            "response_mime_type": "application/json",
        })
        self.assertEqual(generation_config("gemini-3.6-flash"), {
            "response_mime_type": "application/json",
        })
        self.assertEqual(generation_config("gemini-3.1-flash-lite"), {
            "response_mime_type": "application/json",
            "temperature": 0.0,
        })

    def test_active_model_policy_names_prompts_instead_of_ranking_tiers(self):
        policy = load_prompt_policy(CURRENT_SD_POLICY_ID)
        accepted = accepted_prompt_ids(CURRENT_SD_POLICY_ID)
        self.assertEqual(accepted, frozenset({
            "sd-lexical-v1-g31", "sd-lexical-v2-g31",
        }))
        self.assertEqual(policy.get("preference_order"), [
            "sd-lexical-v1-g31", "sd-lexical-v2-g31",
        ])
        self.assertNotIn("sd-lexical-v2-g31",
                         policy.get("evaluation_prompt_ids", []))
        self.assertIn("legacy-unknown",
                      policy.get("rejected_prompt_ids", {}))

    def test_rosalia_v7_current_claims_are_explicitly_admitted(self):
        self.assertGreaterEqual(
            METHOD_PRIORITY["spanishdict-embed-v7-provider"], 50)
        self.assertIn("speech-embed-wsd-v7", load_registry())
        self.assertEqual(
            accepted_prompt_ids("rosalia-v7-provider-current"),
            frozenset({"speech-embed-wsd-v7"}),
        )

    def test_provenance_distinguishes_off_menu_model_proposals(self):
        registry = {
            "sd-lexical-v2-g31": {"capability_tier": 40},
        }
        assignments = {
            "spanishdict-lexical-g31-v2": [{
                "sense": "menu-sense", "prompt_id": "sd-lexical-v2-g31",
            }],
            "lexical-gap-fill-g31-v2": [{
                "sense": "proposed-sense", "prompt_id": "sd-lexical-v2-g31",
            }],
        }

        provenance = resolve_sense_provenance(assignments, registry)

        self.assertFalse(provenance["menu-sense"]["model_proposed"])
        self.assertTrue(provenance["proposed-sense"]["model_proposed"])
        self.assertEqual(provenance["proposed-sense"]["method"],
                         "lexical-gap-fill-g31-v2")


if __name__ == "__main__":
    unittest.main()
