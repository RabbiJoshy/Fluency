import unittest
import json
import tempfile
from pathlib import Path

from pipeline.artist.step_8a_fetch_lrc_timestamps import (
    load_song_artists,
    match_examples_to_lrc,
    parse_lrc,
)


class LyricTimestampTests(unittest.TestCase):
    def test_empty_lrc_row_is_a_real_end_boundary(self):
        lrc = (
            "[00:10.00]Primera línea\n"
            "[00:13.50]\n"
            "[00:18.00]Segunda línea\n"
        )

        lines = parse_lrc(lrc, duration_ms=24000)

        self.assertEqual(lines[0], (10000, 13500, "Primera línea", "primera línea"))
        self.assertEqual(lines[1], (18000, 24000, "Segunda línea", "segunda línea"))

    def test_matched_example_carries_start_and_end(self):
        lines = parse_lrc(
            "[00:01.00]Hola corazón\n[00:04.25]Siguiente línea\n",
            duration_ms=8000,
        )

        matched = match_examples_to_lrc(["¡Hola, corazón!"], lines)

        self.assertEqual(matched["¡Hola, corazón!"]["ms"], 1000)
        self.assertEqual(matched["¡Hola, corazón!"]["end_ms"], 4250)
        self.assertEqual(matched["¡Hola, corazón!"]["confidence"], "exact")

    def test_playlist_song_artists_come_from_lyric_metadata(self):
        """A playlist title must never be used in place of its track artist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            artist_dir = Path(temp_dir)
            lyrics_dir = artist_dir / "lyrics" / "spanish"
            lyrics_dir.mkdir(parents=True)
            (artist_dir / "artist.json").write_text(json.dumps({
                "name": "Spanish Test Playlist",
                "batch_glob_rel": "lyrics/spanish/*.json",
            }), encoding="utf-8")
            (lyrics_dir / "amarillo.json").write_text(json.dumps({
                "id": 5302840,
                "title": "Amarillo",
                "artist": "J Balvin",
            }), encoding="utf-8")

            self.assertEqual(load_song_artists(str(artist_dir)), {
                "Amarillo": "J Balvin",
            })


if __name__ == "__main__":
    unittest.main()
