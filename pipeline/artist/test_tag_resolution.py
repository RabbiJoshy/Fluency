import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.artist import tool_4a_tag_dashboard
from pipeline.artist.tool_4b_resolve_tags import _source_from_dashboard_row


class TagResolutionTests(unittest.TestCase):
    def test_compact_artist_index_carries_local_category(self):
        builder = Path(__file__).with_name("step_8b_assemble_artist_vocabulary.py")
        source = builder.read_text(encoding="utf-8")
        self.assertIn('idx_entry["extra_category"] = entry["extra_category"]', source)

    def test_low_frequency_is_an_explicit_abstention_not_core(self):
        tags, category = _source_from_dashboard_row({
            "bucket": "exclude.low_frequency",
            "loanword": False,
            "en50k": False,
            "spanish_form": False,
            "word_eq_trans": False,
        })
        self.assertEqual(category, "unresolved")
        self.assertIn(
            {"tag": "unresolved", "source": "routing_low_frequency"}, tags)

    def test_sense_discovery_is_an_abstention_not_core(self):
        # A sense_discovery word is one we are asking a model about, not one we
        # have evidence for. Since the frequency floor stopped diverting these
        # to exclude.low_frequency, falling through to `core` would ship a word
        # the model declines to gloss (a brand, a name) as a blank Main card.
        tags, category = _source_from_dashboard_row({
            "bucket": "sense_discovery",
            "loanword": False,
            "en50k": False,
            "spanish_form": False,
            "word_eq_trans": False,
        })
        self.assertEqual(category, "unresolved")
        self.assertIn(
            {"tag": "unresolved", "source": "routing_sense_discovery"}, tags)

    def test_positive_classifier_evidence_remains_core(self):
        tags, category = _source_from_dashboard_row({
            "bucket": "classifier.conjugation",
            "loanword": False,
            "en50k": False,
            "spanish_form": True,
            "word_eq_trans": False,
        })
        self.assertEqual(category, "core")
        self.assertEqual(tags, [])

    def test_source_discovery_uses_configured_path_not_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artist = root / "Artists" / "spanish" / "NoSpaces"
            (artist / "data" / "known_vocab").mkdir(parents=True)
            (artist / "data" / "known_vocab" / "word_routing.json").write_text(
                "{}", encoding="utf-8")
            (artist / "artist.json").write_text(
                json.dumps({"vocabulary_file": "deck.json"}), encoding="utf-8")
            (root / "config").mkdir()
            (root / "config" / "artists.json").write_text(json.dumps({
                "test": {
                    "name": "Display Name With Spaces",
                    "language": "spanish",
                    "indexPath": "Artists/spanish/NoSpaces/deck.index.json",
                }
            }), encoding="utf-8")
            with patch.object(tool_4a_tag_dashboard, "ROOT", str(root)):
                sources = tool_4a_tag_dashboard.discover_sources()
            self.assertEqual(len(sources), 1)
            self.assertTrue(sources[0]["routing"].startswith(str(artist)))


if __name__ == "__main__":
    unittest.main()
