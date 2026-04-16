#!/usr/bin/env python3
"""Shared helpers for pipeline step versioning.

Each pipeline step declares a STEP_VERSION constant. Every output it produces
embeds that version (either as a top-level `_meta` block for dict-keyed JSON
files, or per-entry `step_version` fields for status-style JSON files).

The dashboard script (`scripts/pipeline_status.py`) reads those stamps to tell
which outputs are current vs. stale.

Convention:
- Dict-keyed output files (example_pos.json, etc.): reserve top-level `_meta`
  key holding {step_name, step_version, generated_at, tool_versions, ...}.
- Per-entry status files (spanishdict/status.json): add `step_version` alongside
  the existing `updated_at` / `status` fields on each entry.
"""

import json
import time
from pathlib import Path


META_KEY = "_meta"


def make_meta(step_name, step_version, tool_versions=None, extra=None):
    """Build a `_meta` dict for stamping into a dict-keyed output file or sidecar."""
    meta = {
        "step_name": step_name,
        "step_version": step_version,
        "generated_at": int(time.time()),
    }
    if tool_versions:
        meta["tool_versions"] = dict(tool_versions)
    if extra:
        meta.update(extra)
    return meta


def sidecar_path(output_path):
    """Return sidecar path for a given output file.

    Convention: `foo.json` → `foo.meta.json`, `foo` → `foo.meta.json`.
    Use this for list-typed outputs that can't host an embedded `_meta` key.
    """
    p = Path(output_path)
    return p.with_suffix(p.suffix + ".meta.json") if p.suffix else p.with_name(p.name + ".meta.json")


def write_sidecar(output_path, meta):
    """Write the given meta dict to `<output_path>.meta.json`."""
    path = sidecar_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def read_meta(output_path):
    """Return the `_meta` block for an output, or None if absent.

    Checks sidecar `<path>.meta.json` first, falls back to embedded `_meta`
    key inside dict-typed output files.
    """
    sidecar = sidecar_path(output_path)
    if sidecar.is_file():
        try:
            with open(sidecar, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        meta = data.get(META_KEY)
        if isinstance(meta, dict):
            return meta
    return None


def read_step_version(output_path):
    """Convenience: return just the step_version from a file's _meta, or 0."""
    meta = read_meta(output_path)
    if not meta:
        return 0
    return int(meta.get("step_version", 0) or 0)


def read_generated_at(output_path):
    """Convenience: return generated_at (unix seconds) or file mtime as fallback."""
    meta = read_meta(output_path)
    if meta and meta.get("generated_at"):
        return int(meta["generated_at"])
    try:
        return int(Path(output_path).stat().st_mtime)
    except OSError:
        return 0
