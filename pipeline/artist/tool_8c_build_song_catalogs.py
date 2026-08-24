#!/usr/bin/env python3
"""Build compact per-song card membership for shipped Lyrics decks.

The learner-facing index is surface-keyed, while the pipeline's merged
evidence retains the complete set of song IDs for each surface.  This tool
joins those two authoritative outputs and emits a small catalog that the app
can use to select songs without loading ledger or intermediate files.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPANISH_MASTER = ROOT / "Artists" / "spanish" / "vocabulary_master.json"
SPOTIFY_TRACKS = ROOT / "Artists" / "spotify_tracks.json"

DECKS = (
    {
        "slug": "bad-bunny",
        "name": "Bad Bunny",
        "directory": ROOT / "Artists" / "spanish" / "Bad Bunny",
        "index": "BadBunnyvocabulary.index.json",
        "examples": "BadBunnyvocabulary.examples.json",
        "output": "BadBunnysongs.json",
    },
    {
        "slug": "rosalia",
        "name": "Rosalía",
        "directory": ROOT / "Artists" / "spanish" / "Rosalía",
        "master": ROOT / "Artists" / "spanish" / "Rosalía" / "Rosaliavocabulary.master.json",
        "index": "Rosaliavocabulary.index.json",
        "examples": "Rosaliavocabulary.examples.json",
        "output": "Rosaliasongs.json",
    },
    {
        "slug": "young-miko",
        "name": "Young Miko",
        "directory": ROOT / "Artists" / "spanish" / "Young Miko",
        "index": "YoungMikovocabulary.index.json",
        "examples": "YoungMikovocabulary.examples.json",
        "output": "YoungMikosongs.json",
    },
    {
        "slug": "spanish-test-playlist",
        "name": "Spanish Test Playlist",
        "directory": ROOT / "Artists" / "spanish" / "SpanishTestPlaylist",
        "index": "SpanishTestPlaylistvocabulary.index.json",
        "examples": "SpanishTestPlaylistvocabulary.examples.json",
        "output": "SpanishTestPlaylistsongs.json",
    },
)


def load_json(path: Path, fallback=None):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def iter_example_objects(value):
    if isinstance(value, dict):
        if value.get("song") not in (None, "") or value.get("song_name") or value.get("title"):
            yield value
        for child in value.values():
            yield from iter_example_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_example_objects(child)


def song_id_from_example(example):
    if example.get("song") not in (None, ""):
        return str(example["song"])
    raw = str(example.get("id") or "")
    return raw.split(":", 1)[0] if ":" in raw else ""


def build_catalog(deck, master, spotify_by_artist):
    directory = deck["directory"]
    index = load_json(directory / deck["index"], [])
    evidence = load_json(directory / "data" / "elision_merge" / "vocab_evidence_merged.json", [])
    raw_examples = load_json(directory / "data" / "layers" / "examples_raw.json", {})
    compact_examples = load_json(directory / deck["examples"], {})
    playlist = load_json(directory / "tracks.json", {}) or {}

    rank_by_id = {str(row["id"]): position for position, row in enumerate(index)}
    id_by_word = {}
    for card_id in rank_by_id:
        word = (master.get(card_id) or {}).get("word")
        if word and word not in id_by_word:
            id_by_word[word] = card_id

    metadata = {}
    membership = defaultdict(set)

    def note_example(example, card_id=None):
        song_id = song_id_from_example(example)
        if not song_id:
            return
        title = str(example.get("song_name") or example.get("title") or "").strip()
        row = metadata.setdefault(song_id, {"id": song_id, "title": title})
        if title and not row.get("title"):
            row["title"] = title
        artist = str(example.get("artist") or "").strip()
        track = str(example.get("spotify_track_id") or example.get("track_id") or "").strip()
        if artist:
            row["artist"] = artist
        if track:
            row["spotifyTrackId"] = track
        if card_id in rank_by_id:
            membership[song_id].add(card_id)

    for word, examples in (raw_examples or {}).items():
        card_id = id_by_word.get(word)
        for example in iter_example_objects(examples):
            note_example(example, card_id)

    for card_id, examples in (compact_examples or {}).items():
        for example in iter_example_objects(examples):
            note_example(example, str(card_id))

    # Full membership comes from merged evidence's song_ids, not from the
    # bounded example sample.  Example scanning above supplies song metadata
    # and also covers synthesized cards that have no direct evidence row.
    for row in evidence:
        card_id = id_by_word.get(row.get("word"))
        if card_id not in rank_by_id:
            continue
        for song_id in row.get("song_ids") or []:
            membership[str(song_id)].add(card_id)
        for example in iter_example_objects(row.get("examples") or []):
            note_example(example, card_id)

    track_rows = playlist.get("tracks") if isinstance(playlist, dict) else []
    playlist_by_title = defaultdict(list)
    for track in track_rows or []:
        playlist_by_title[normalized_title(track.get("title"))].append(track)

    spotify_titles = spotify_by_artist.get(deck["name"], {})
    songs = []
    for song_id, card_ids in membership.items():
        row = metadata.setdefault(song_id, {"id": song_id, "title": ""})
        title = row.get("title") or f"Song {song_id}"
        matches = playlist_by_title.get(normalized_title(title), [])
        if len(matches) == 1:
            track = matches[0]
            row.setdefault("artist", track.get("artist") or "")
            row.setdefault("spotifyTrackId", track.get("spotify_id") or "")
        row.setdefault("artist", deck["name"] if deck["slug"] != "spanish-test-playlist" else "")
        if not row.get("spotifyTrackId"):
            row["spotifyTrackId"] = spotify_titles.get(title, "")
        songs.append({
            "id": song_id,
            "title": title,
            "artist": row.get("artist") or "",
            "spotifyTrackId": row.get("spotifyTrackId") or "",
            "cardIds": sorted(card_ids, key=lambda card_id: rank_by_id[card_id]),
        })

    songs.sort(key=lambda row: (normalized_title(row["title"]), row["id"]))
    covered = set().union(*(set(song["cardIds"]) for song in songs)) if songs else set()
    return {
        "schemaVersion": 1,
        "source": deck["slug"],
        "name": deck["name"],
        "songCount": len(songs),
        "cardCount": len(rank_by_id),
        "songLinkedCardCount": len(covered),
        "songs": songs,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify outputs without writing")
    args = parser.parse_args()
    spotify = load_json(SPOTIFY_TRACKS, {})
    failed = False
    for deck in DECKS:
        master = load_json(deck.get("master", SPANISH_MASTER), {})
        catalog = build_catalog(deck, master, spotify)
        output = deck["directory"] / deck["output"]
        serialized = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
        if args.check:
            current = output.read_text(encoding="utf-8") if output.exists() else ""
            if current != serialized:
                print(f"STALE {output.relative_to(ROOT)}")
                failed = True
            else:
                print(f"OK {deck['slug']}: {catalog['songCount']} songs, "
                      f"{catalog['songLinkedCardCount']} linked cards")
        else:
            output.write_text(serialized, encoding="utf-8")
            print(f"WROTE {output.relative_to(ROOT)}: {catalog['songCount']} songs, "
                  f"{catalog['songLinkedCardCount']} linked cards")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
