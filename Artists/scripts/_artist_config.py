"""Shared helper for artist pipeline scripts. Every script imports this."""

import json
import os
import time

# Artists/scripts/_artist_config.py -> Artists/
ARTISTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_DIR = os.path.join(ARTISTS_DIR, "shared")


def add_artist_arg(parser):
    """Add the --artist-dir argument to any argparse parser."""
    parser.add_argument(
        "--artist-dir", required=True,
        help="Path to artist data directory (e.g. Artists/Bad Bunny)",
    )


def load_artist_config(artist_dir):
    """Load artist.json from the artist directory."""
    path = os.path.join(artist_dir, "artist.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dotenv_from_project_root():
    """Load .env from the project root (Fluency/).

    Works regardless of where the script lives — derives project root
    from this file's location: Artists/scripts/_artist_config.py -> Artists/ -> Fluency/
    """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(this_dir))
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


def load_shared_list(filename):
    """Load a shared curated list from Artists/shared/.

    Handles both old format (plain list) and new format (dict with 'entries' key).
    Returns a plain list of strings.
    """
    path = os.path.join(SHARED_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("entries", [])


def scrape_lyrics_by_id(genius_client, song_id, max_tries=5):
    """Scrape lyrics from Genius by song ID with exponential backoff."""
    from requests.exceptions import Timeout, HTTPError
    delay = 2
    for attempt in range(1, max_tries + 1):
        try:
            lyrics = genius_client.lyrics(song_id=song_id)
            return lyrics
        except (Timeout, HTTPError) as e:
            if attempt == max_tries:
                print("    Failed after %d attempts: %s" % (max_tries, e))
                return None
            time.sleep(delay)
            delay *= 2
        except Exception as e:
            print("    Unexpected error scraping %d: %s" % (song_id, e))
            return None


def load_done_ids(progress_path):
    """Load a set of completed IDs from a JSON progress file."""
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_done_ids(progress_path, done_ids):
    """Save a set of completed IDs to a JSON progress file."""
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(sorted(done_ids), f, indent=2)


def load_shared_dict(filename):
    """Load a shared curated dict from Artists/shared/.

    Strips metadata keys (_format, _sources) and returns the plain dict.
    """
    path = os.path.join(SHARED_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}
