"""Shared helper for artist pipeline scripts. Every script imports this."""

import json
import os

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


def load_shared_dict(filename):
    """Load a shared curated dict from Artists/shared/.

    Strips metadata keys (_format, _sources) and returns the plain dict.
    """
    path = os.path.join(SHARED_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}
