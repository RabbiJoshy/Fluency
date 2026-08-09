import json
import tempfile
import unittest
from pathlib import Path

from pipeline.artist.tool_migrate_evidence_store import discover_layers


class EvidenceBaselineMigrationTests(unittest.TestCase):
    def test_discovers_static_and_arbitrary_sense_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artist = Path(temp_dir)
            routing = artist / "data" / "known_vocab" / "word_routing.json"
            custom = artist / "data" / "layers" / "sense_assignments" / "local.json"
            sidecar = custom.with_name("local.meta.json")
            for path in (routing, custom, sidecar):
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as file:
                    json.dump({}, file)

            discovered = {layer for _path, layer in discover_layers(artist)}

            self.assertIn("word_routing", discovered)
            self.assertIn("sense_assignments/local", discovered)
            self.assertNotIn("sense_assignments/local.meta", discovered)


if __name__ == "__main__":
    unittest.main()
