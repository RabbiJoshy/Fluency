import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline.artist.step_8b_assemble_artist_vocabulary import _copy_example_surface


class SurfaceProvenanceTest(unittest.TestCase):
    def test_noncanonical_occurrence_surface_reaches_compact_example(self):
        output = {}
        _copy_example_surface(
            {"surface": "cometamo'", "spanish": "Que cometamo' el mismo error"},
            output,
            "cometamos",
        )
        self.assertEqual(output["surface"], "cometamo'")

    def test_canonical_surface_is_omitted_from_compact_example(self):
        output = {}
        _copy_example_surface({"surface": "cometamos"}, output, "cometamos")
        self.assertNotIn("surface", output)


if __name__ == "__main__":
    unittest.main()
