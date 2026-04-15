"""Path helpers for per-source sense files.

Mirrors the artist pipeline's directory-based layout:
    layers/sense_menu/{source}.json
    layers/sense_assignments/{source}.json
    layers/sense_assignments_lemma/{source}.json
"""

from pathlib import Path


def sense_menu_path(layers_dir, source="wiktionary"):
    return Path(layers_dir) / "sense_menu" / f"{source}.json"


def sense_assignments_path(layers_dir, source="wiktionary"):
    return Path(layers_dir) / "sense_assignments" / f"{source}.json"


def sense_assignments_lemma_path(layers_dir, source="wiktionary"):
    return Path(layers_dir) / "sense_assignments_lemma" / f"{source}.json"


def discover_sources(layers_dir, subdir="sense_assignments"):
    """Return list of available source names by scanning a subdirectory."""
    d = Path(layers_dir) / subdir
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
