import tempfile
import unittest
from pathlib import Path

from pipeline.artist.tool_8c_build_song_catalogs import build_catalog


class SongCatalogTests(unittest.TestCase):
    def test_full_membership_does_not_depend_on_bounded_examples(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "data/elision_merge").mkdir(parents=True)
            (directory / "data/layers").mkdir(parents=True)
            (directory / "index.json").write_text('[{"id":"aaaaaaaa"}]')
            (directory / "examples.json").write_text('{}')
            (directory / "data/layers/examples_raw.json").write_text(
                '{"hola":[{"id":"song-1:1","title":"First"}]}'
            )
            (directory / "data/elision_merge/vocab_evidence_merged.json").write_text(
                '[{"word":"hola","song_ids":["song-1","song-2"]}]'
            )
            (directory / "tracks.json").write_text(
                '{"tracks":[{"title":"First","artist":"A","spotify_id":"track-1"}]}'
            )
            catalog = build_catalog({
                "slug": "fixture", "name": "A", "directory": directory,
                "index": "index.json", "examples": "examples.json", "output": "songs.json",
            }, {"aaaaaaaa": {"word": "hola"}}, {"A": {}})
            songs = {song["id"]: song for song in catalog["songs"]}
            self.assertEqual(songs["song-1"]["cardIds"], ["aaaaaaaa"])
            self.assertEqual(songs["song-2"]["cardIds"], ["aaaaaaaa"])
            self.assertEqual(songs["song-1"]["spotifyTrackId"], "track-1")


if __name__ == "__main__":
    unittest.main()
