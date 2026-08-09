#!/usr/bin/env python3
"""Refresh offline-content sizes/hashes and optionally add an Artist source."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "config" / "offline-content-manifest.json"
ARTISTS_PATH = PROJECT_ROOT / "config" / "artists.json"


def file_record(relative_path):
    path = PROJECT_ROOT / relative_path
    body = path.read_bytes()
    return {
        "path": relative_path,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def artist_source(artist_id, config, content_version):
    required = ("masterPath", "indexPath", "examplesPath")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(
            "%s is not a split Artist deck; missing %s" %
            (artist_id, ", ".join(missing)))
    language = str(config.get("language") or "").lower()
    files = [file_record(config[key]) for key in required]
    storage_bytes = sum(row["bytes"] for row in files)
    return {
        "id": "artist-" + artist_id,
        "name": config.get("name") or artist_id,
        "scope": "artist",
        "scopeLabel": "Lyrics · shared %s meanings included" % language.title(),
        "language": language,
        "artist": artist_id,
        "contentVersion": content_version,
        "storageBytes": storage_bytes,
        # Conservative until a deployed compressed transfer is measured.
        "transferBytes": storage_bytes,
        "dependencies": ["shared-%s-artist" % language],
        "files": files,
    }


def refresh_manifest(add_artist=None, content_version=None, generated_at=None):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    artists = json.loads(ARTISTS_PATH.read_text(encoding="utf-8"))
    content_version = content_version or manifest.get("contentVersion")

    if add_artist:
        config = artists.get(add_artist)
        if not config:
            raise ValueError("Unknown artist id: %s" % add_artist)
        replacement = artist_source(add_artist, config, content_version)
        for index, source in enumerate(manifest.get("sources") or []):
            if source.get("id") == replacement["id"]:
                manifest["sources"][index] = replacement
                break
        else:
            manifest.setdefault("sources", []).append(replacement)

    for source in manifest.get("sources") or []:
        source["files"] = [file_record(row["path"])
                           for row in source.get("files") or []]
        source["storageBytes"] = sum(row["bytes"] for row in source["files"])
        source["transferBytes"] = min(
            int(source.get("transferBytes") or source["storageBytes"]),
            source["storageBytes"],
        )

    if content_version:
        manifest["contentVersion"] = content_version
    manifest["generatedAt"] = generated_at or datetime.now(
        timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--add-artist", help="Artist id from config/artists.json")
    parser.add_argument("--content-version")
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    refresh_manifest(
        add_artist=args.add_artist,
        content_version=args.content_version,
        generated_at=args.generated_at,
    )
    print("Updated %s" % MANIFEST_PATH)


if __name__ == "__main__":
    main()
