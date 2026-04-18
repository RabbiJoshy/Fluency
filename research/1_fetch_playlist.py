#!/usr/bin/env python3
"""
Step 1a: Fetch track list from a Spotify playlist.

Outputs a tracks.json file that can be inspected/edited before downloading lyrics.

Usage:
    .venv/bin/python3 research/1_fetch_playlist.py \
        --playlist "https://open.spotify.com/playlist/0ubVKl2OeeqSa5C0I3zbq7" \
        --out Artists/french/TestPlaylist/tracks.json
"""

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REDIRECT_PORT = 8766
REDIRECT_URI = "http://127.0.0.1:%d/callback" % REDIRECT_PORT


# ---------- Spotify user OAuth (PKCE) ----------

def _read_client_id():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    if not client_id:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == "SPOTIFY_CLIENT_ID":
                        client_id = v.strip()
    if not client_id:
        sys.exit("Missing SPOTIFY_CLIENT_ID in .env")
    return client_id


def get_user_token():
    client_id = _read_client_id()

    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "playlist-read-private playlist-read-collaborative",
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    })

    auth_code = [None]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("state", [None])[0] == state and "code" in qs:
                auth_code[0] = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Authenticated! You can close this tab.</h2></body></html>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Auth failed")

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    print("Opening browser for Spotify login...")
    webbrowser.open(auth_url)
    server.handle_request()
    server.server_close()

    if not auth_code[0]:
        sys.exit("OAuth failed — no auth code received")

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": auth_code[0],
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read())
    return token_data["access_token"]


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser(description="Fetch Spotify playlist track list")
    parser.add_argument("--playlist", required=True, help="Spotify playlist URL")
    parser.add_argument("--out", required=True, help="Output JSON path (e.g. Artists/french/TestPlaylist/tracks.json)")
    args = parser.parse_args()

    playlist_id = args.playlist.split("/playlist/")[1].split("?")[0]
    token = get_user_token()

    # Get playlist name
    meta_url = "https://api.spotify.com/v1/playlists/%s?fields=name" % playlist_id
    req = urllib.request.Request(meta_url, headers={"Authorization": "Bearer %s" % token})
    with urllib.request.urlopen(req) as resp:
        meta = json.loads(resp.read())
    playlist_name = meta.get("name", playlist_id)
    print("Playlist: %s" % playlist_name)

    # Fetch all items (paginated, Feb 2026 API: /items not /tracks)
    tracks = []
    url = "https://api.spotify.com/v1/playlists/%s/items" % playlist_id
    while url:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer %s" % token})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        for entry in data.get("items", []):
            # Feb 2026 API: nested field is "item", not "track"
            t = entry.get("track") or entry.get("item")
            if t and t.get("name") and t.get("artists"):
                tracks.append({
                    "title": t["name"],
                    "artist": t["artists"][0]["name"],
                    "spotify_id": t.get("id", ""),
                })
        url = data.get("next")

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "playlist_name": playlist_name,
        "playlist_id": playlist_id,
        "track_count": len(tracks),
        "tracks": tracks,
    }
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print("Wrote %d tracks -> %s" % (len(tracks), out_path))


if __name__ == "__main__":
    main()
