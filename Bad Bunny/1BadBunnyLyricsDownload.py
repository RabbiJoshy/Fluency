TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from requests.exceptions import Timeout, HTTPError
from lyricsgenius import Genius

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

ARTIST_QUERY = "Bad Bunny"
BATCH_SIZE = 25
START_PAGE = 1

# # Prefer env var; DO NOT hardcode tokens in code.
# TOKEN = os.getenv("GENIUS_ACCESS_TOKEN", "").strip()
# if not TOKEN:
#     raise RuntimeError(
#         "Missing GENIUS_ACCESS_TOKEN env var. "
#         "Set it like: export GENIUS_ACCESS_TOKEN='...'"
#     )

genius = Genius(
    TOKEN,
    timeout=30,
    retries=3,
    sleep_time=1.0,
)

# Reduce junk upstream
genius.verbose = True
genius.remove_section_headers = True        # strips [Chorus], etc. :contentReference[oaicite:1]{index=1}
genius.skip_non_songs = True                # avoids tracklists / non-songs :contentReference[oaicite:2]{index=2}
genius.excluded_terms = [
    "(Remix)", "(Live)", "(Concert)", "(Version)", "(Acoustic)",
    "Tracklist", "Credits", "Romanized", "Translation"
]

# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def load_done_ids(progress_path: Path) -> set[int]:
    if progress_path.exists():
        return set(json.loads(progress_path.read_text()))
    return set()

def save_done_ids(progress_path: Path, done_ids: set[int]) -> None:
    progress_path.write_text(json.dumps(sorted(done_ids), indent=2))

def fetch_batch_song_metas(artist_id: int, page: int, per_page: int = 25):
    """
    Returns (songs, next_page) using Genius API's artist_songs endpoint.
    """
    res = genius.artist_songs(artist_id, per_page=per_page, page=page, sort="popularity")
    return res.get("songs", []), res.get("next_page")

def safe_search_song(title: str, artist_name: str, max_tries: int = 5):
    """
    Returns a lyricsgenius.types.Song (includes .lyrics, .album, .album_url, .year, .url). :contentReference[oaicite:3]{index=3}
    """
    delay = 2
    for attempt in range(1, max_tries + 1):
        try:
            song = genius.search_song(title, artist_name)
            return song
        except (Timeout, HTTPError):
            if attempt == max_tries:
                return None
            time.sleep(delay)
            delay *= 2

def song_to_record(song_id: int, title: str, artist_name: str, url_fallback: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch song via search_song (scrapes lyrics) and return a JSON-serializable record
    including album info.
    """
    s = safe_search_song(title, artist_name)
    if not s:
        return {
            "id": song_id,
            "title": title,
            "artist": artist_name,
            "url": url_fallback,
            "album": None,
            "album_url": None,
            "year": None,
            "lyrics": None,
        }

    # Song fields per docs: album, album_url, year, url, lyrics :contentReference[oaicite:4]{index=4}
    return {
        "id": song_id,
        "title": getattr(s, "title", title),
        "artist": getattr(getattr(s, "artist", None), "name", artist_name) if getattr(s, "artist", None) else artist_name,
        "url": getattr(s, "url", None) or url_fallback,
        "album": getattr(s, "album", None),
        "album_url": getattr(s, "album_url", None),
        "year": getattr(s, "year", None),
        "lyrics": getattr(s, "lyrics", None),
    }

# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def download_artist_lyrics_in_batches(artist_query: str, batch_size: int = 25, start_page: int = 1):
    # Resolve canonical artist + id (only 1 song needed just to get id/name)
    artist_stub = genius.search_artist(artist_query, max_songs=1)  # :contentReference[oaicite:5]{index=5}
    if not artist_stub:
        raise RuntimeError(f"Could not resolve artist: {artist_query}")

    artist_id = artist_stub.id
    artist_name = artist_stub.name

    out_dir = Path(f"genius_{artist_name.replace(' ', '_')}")
    out_dir.mkdir(exist_ok=True)

    progress_path = out_dir / "done_song_ids.json"
    done_ids = load_done_ids(progress_path)

    page = start_page
    batch_num = 1

    while page:
        metas, next_page = fetch_batch_song_metas(artist_id, page=page, per_page=batch_size)

        # Filter out already-done songs
        metas = [m for m in metas if m.get("id") not in done_ids]

        if not metas:
            page = next_page
            continue

        batch = []
        for m in metas:
            song_id = m["id"]
            title = m["title"]
            url_fallback = m.get("url")

            rec = song_to_record(song_id, title, artist_name, url_fallback=url_fallback)
            batch.append(rec)

            done_ids.add(song_id)
            save_done_ids(progress_path, done_ids)

        batch_file = out_dir / f"batch_{batch_num:03d}_page_{page}.json"
        batch_file.write_text(json.dumps(batch, ensure_ascii=False, indent=2))
        print(f"Saved {len(batch)} songs → {batch_file}")

        batch_num += 1
        page = next_page

if __name__ == "__main__":
    download_artist_lyrics_in_batches(ARTIST_QUERY, batch_size=BATCH_SIZE, start_page=START_PAGE)
