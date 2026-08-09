import json
import tempfile
import unittest
from pathlib import Path

from pipeline.artist.step_5a_split_evidence import load_playlist_track_metadata


class PlaylistSpotifyMetadataTests(unittest.TestCase):
    def test_tracks_json_keeps_artist_and_matches_normalized_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            track_path = Path(temp_dir) / "tracks.json"
            track_path.write_text(json.dumps({"tracks": [{
                "title": "Qué Más Pues?",
                "artist": "J Balvin",
                "spotify_id": "playlist-track-id",
            }]}), encoding="utf-8")

            metadata = load_playlist_track_metadata(temp_dir)

            self.assertEqual(metadata["que mas pues"], {
                "artist": "J Balvin",
                "spotify_track_id": "playlist-track-id",
            })

    def test_ambiguous_playlist_title_is_not_assigned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            track_path = Path(temp_dir) / "tracks.json"
            track_path.write_text(json.dumps({"tracks": [
                {"title": "Same Song", "artist": "Artist A", "spotify_id": "a"},
                {"title": "Same Song", "artist": "Artist B", "spotify_id": "b"},
            ]}), encoding="utf-8")

            self.assertNotIn("same song", load_playlist_track_metadata(temp_dir))


if __name__ == "__main__":
    unittest.main()
