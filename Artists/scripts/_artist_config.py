"""Shared helper for artist pipeline scripts. Every script imports this."""

import json
import os
import time

# Artists/scripts/_artist_config.py -> Artists/
ARTISTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)
SHARED_DIR = os.path.join(ARTISTS_DIR, "shared")
PROJECT_SHARED_DIR = os.path.join(PROJECT_ROOT, "shared")


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


# ---------------------------------------------------------------------------
# geniURL: find English translations on Genius
# ---------------------------------------------------------------------------

GENIURL_BASE = "https://api.sv443.net/geniurl/translations"
GENIURL_MIN_INTERVAL = 1.2  # seconds between requests (rate limit: 25/30s)

import threading
_geniurl_lock = threading.Lock()
_geniurl_last_request = 0.0


def _geniurl_throttle():
    """Enforce minimum interval between geniURL requests across all threads."""
    global _geniurl_last_request
    with _geniurl_lock:
        now = time.time()
        wait = GENIURL_MIN_INTERVAL - (now - _geniurl_last_request)
        if wait > 0:
            time.sleep(wait)
        _geniurl_last_request = time.time()


def find_english_translation(song_id):
    """Query geniURL for an English translation of song_id.

    Returns (translation_genius_id, title, url) or None.
    Thread-safe: uses global rate limiter.
    """
    import requests

    _geniurl_throttle()
    url = "%s/%s" % (GENIURL_BASE, song_id)
    try:
        resp = requests.get(url, timeout=15)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            time.sleep(retry_after)
            resp = requests.get(url, timeout=15)

        if resp.status_code >= 400:
            return None

        data = resp.json()
        if data.get("error") or not data.get("translations"):
            return None

        for t in data["translations"]:
            if t.get("language") == "en":
                return (t["id"], t.get("title", ""), t.get("url", ""))
        return None

    except Exception as e:
        return None


def load_shared_dict(filename, modes=None):
    """Load a shared curated dict from shared/ (project root).

    Supports both the new tagged format (``{word: {translation, pos, mode}}``)
    and the legacy flat format (``{word: translation}``).

    Args:
        filename: JSON filename inside ``shared/``.
        modes: Optional set/tuple of mode strings to keep (e.g. ``("shared", "artist")``).
               If *None*, all entries are returned.

    Returns:
        Plain ``{word: translation}`` dict with metadata keys stripped.
    """
    path = os.path.join(PROJECT_SHARED_DIR, filename)
    if not os.path.isfile(path):
        # Fall back to Artists/shared/ location
        path = os.path.join(SHARED_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for k, v in data.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            # Tagged format — keys are word|lemma
            if modes and v.get("mode") not in modes:
                continue
            result[k] = v["translation"]
        else:
            # Legacy flat format
            result[k] = v
    return result
