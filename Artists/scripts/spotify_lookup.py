#!/usr/bin/env python3
"""Look up Spotify track IDs for all songs in the vocabulary.

Reads each artist's examples JSON, queries the Spotify Search API,
and writes a mapping file per artist: data/spotify_tracks.json

Usage:
    python3 Artists/scripts/spotify_lookup.py

Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env
"""

import json
import os
import sys
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---------- auth ----------

def get_access_token():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        # Try .env file
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == "SPOTIFY_CLIENT_ID":
                        client_id = v.strip()
                    elif k.strip() == "SPOTIFY_CLIENT_SECRET":
                        client_secret = v.strip()
    if not client_id or not client_secret:
        sys.exit("Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET")

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


# ---------- search ----------

def search_track(token, song_name, artist_name):
    """Return (track_id, track_url) or (None, None)."""
    q = f"track:{song_name} artist:{artist_name}"
    params = urllib.parse.urlencode({"q": q, "type": "track", "limit": 1})
    url = f"https://api.spotify.com/v1/search?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        items = data.get("tracks", {}).get("items", [])
        if items:
            return items[0]["id"], items[0]["external_urls"]["spotify"]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = int(e.headers.get("Retry-After", 5))
            # Cap at 60s — Retry-After can be unreasonably large
            retry = min(retry, 60)
            print(f"  Rate limited, waiting {retry}s...")
            time.sleep(retry)
            return search_track(token, song_name, artist_name)
        print(f"  HTTP {e.code} for {artist_name} - {song_name}")
    return None, None


# ---------- collect songs ----------

def collect_songs(artist_dir, artist_name):
    """Return set of unique song names from examples file."""
    # Use artist.json to find the correct filename stem
    artist_json = artist_dir / "artist.json"
    if artist_json.exists():
        cfg = json.load(open(artist_json))
        vocab_file = cfg.get("vocabulary_file", "")
        stem = vocab_file.replace(".json", "") if vocab_file else artist_name.replace(" ", "") + "vocabulary"
    else:
        stem = artist_name.replace(" ", "") + "vocabulary"
    examples_path = artist_dir / f"{stem}.examples.json"
    if not examples_path.exists():
        print(f"  No examples file: {examples_path}")
        return set()
    data = json.load(open(examples_path))
    songs = set()
    for entry in data.values():
        for meaning_examples in entry.get("m", []):
            if isinstance(meaning_examples, list):
                for ex in meaning_examples:
                    sn = ex.get("song_name")
                    if sn:
                        songs.add(sn)
            elif isinstance(meaning_examples, dict):
                sn = meaning_examples.get("song_name")
                if sn:
                    songs.add(sn)
    return songs


# ---------- main ----------

def main():
    artists_dir = ROOT / "Artists"
    # Find artist folders (have a vocabulary.examples.json)
    artist_folders = []
    for d in sorted(artists_dir.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and d.name not in ("scripts", "shared", "tools", "__pycache__"):
            artist_folders.append(d)

    token = get_access_token()
    print("Authenticated with Spotify\n")

    # Also build a combined file for the front-end
    combined = {}

    for artist_dir in artist_folders:
        artist_name = artist_dir.name
        songs = collect_songs(artist_dir, artist_name)
        if not songs:
            continue

        print(f"{artist_name}: {len(songs)} songs")
        results = {}
        missed = []

        for i, song_name in enumerate(sorted(songs)):
            track_id, track_url = search_track(token, song_name, artist_name)
            if track_id:
                results[song_name] = track_id
                status = "OK"
            else:
                missed.append(song_name)
                status = "MISS"
            print(f"  [{i+1}/{len(songs)}] {status}: {song_name}")
            time.sleep(0.1)  # rate limiting

        # Write per-artist file
        out_path = artist_dir / "data" / "spotify_tracks.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(results, open(out_path, "w"), indent=2, ensure_ascii=False)

        combined[artist_name] = results

        hit_rate = len(results) / len(songs) * 100 if songs else 0
        print(f"  -> {len(results)}/{len(songs)} matched ({hit_rate:.0f}%)")
        if missed:
            print(f"  Missed: {missed}\n")
        else:
            print()

    # Write combined file for front-end
    combined_path = ROOT / "Data" / "spotify_tracks.json"
    json.dump(combined, open(combined_path, "w"), indent=2, ensure_ascii=False)
    print(f"\nCombined file: {combined_path}")
    total = sum(len(v) for v in combined.values())
    print(f"Total tracks matched: {total}")


if __name__ == "__main__":
    main()
