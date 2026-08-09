import tempfile
import unittest
from pathlib import Path

from pipeline.artist.util_1a_artist_config import (
    artist_sense_assignments_path,
    artist_sense_menu_path,
)


class CustomSensePathTests(unittest.TestCase):
    def test_unknown_menu_free_adapter_uses_new_style_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            layers = Path(temp_dir)

            self.assertEqual(
                Path(artist_sense_menu_path(layers, "local-transformer", prefer_new=False)),
                layers / "sense_menu" / "local-transformer.json",
            )
            self.assertEqual(
                Path(artist_sense_assignments_path(
                    layers, "local-transformer", prefer_new=False)),
                layers / "sense_assignments" / "local-transformer.json",
            )


if __name__ == "__main__":
    unittest.main()
