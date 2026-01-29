import json
import time
from pathlib import Path
from requests.exceptions import Timeout, HTTPError
from lyricsgenius import Genius

TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

genius = Genius(
    TOKEN,
    timeout=30,     # give requests more time
    retries=3,      # retry on timeouts / 5xx
    sleep_time=1.0  # be nice to Genius + reduce rate issues
)
genius.verbose = True
genius.remove_section_headers = True
genius.skip_non_songs = True
genius.excluded_terms = ["(Remix)", "(Live)"]

def load_done_ids(progress_path: Path) -> set[int]:
    if progress_path.exists():
        return set(json.loads(progress_path.read_text()))
    return set()

def save_done_ids(progress_path: Path, done_ids: set[int]) -> None:
    progress_path.write_text(json.dumps(sorted(done_ids), indent=2))

def fetch_batch_song_metas(artist_id: int, page: int, per_page: int = 25):
    # Returns (songs, next_page)
    res = genius.artist_songs(artist_id, per_page=per_page, page=page, sort="popularity")
    return res.get("songs", []), res.get("next_page")

def safe_get_lyrics(song_id: int, title: str, artist_name: str, max_tries: int = 5):
    # genius.song(song_id) may or may not include scraped lyrics depending on versions/settings,
    # so we use search_song(title, artist_name) to reliably get .lyrics (scraped).
    delay = 2
    for attempt in range(1, max_tries + 1):
        try:
            s = genius.search_song(title, artist_name)
            if s and getattr(s, "lyrics", None):
                return s.lyrics
            return None
        except (Timeout, HTTPError):
            if attempt == max_tries:
                return None
            time.sleep(delay)
            delay *= 2  # simple exponential backoff

def download_artist_lyrics_in_batches(artist_query: str, batch_size: int = 25, start_page: int = 1):
    # Get canonical artist + id
    artist_stub = genius.search_artist(artist_query, max_songs=1)  # just to resolve name + _id
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
            lyrics = safe_get_lyrics(song_id, title, artist_name)
            batch.append({
                "id": song_id,
                "title": title,
                "artist": artist_name,
                "url": m.get("url"),
                "lyrics": lyrics
            })
            done_ids.add(song_id)
            save_done_ids(progress_path, done_ids)

        batch_file = out_dir / f"batch_{batch_num:03d}_page_{page}.json"
        batch_file.write_text(json.dumps(batch, ensure_ascii=False, indent=2))
        print(f"Saved {len(batch)} songs → {batch_file}")

        batch_num += 1
        page = next_page

download_artist_lyrics_in_batches("Bad Bunny", batch_size=25, start_page=1)
