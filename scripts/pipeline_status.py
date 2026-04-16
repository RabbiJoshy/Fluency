#!/usr/bin/env python3
"""Pipeline status dashboard.

Writes a point-in-time snapshot of which pipeline outputs exist, when they
were last produced, and (for versioned steps) whether they match the current
step_version. Result is written to PIPELINE_STATUS.txt at project root.

Usage:
    .venv/bin/python3 scripts/pipeline_status.py

The grid covers every step listed in pipeline/CLAUDE.md, even ones that
aren't yet retrofitted with step_version. Unversioned steps show EXISTS /
MISSING + the file mtime.

Adding a versioned step:
    1. Make the step stamp `step_version` into its output (_meta block or
       per-entry field — see pipeline/util_pipeline_meta.py).
    2. Set `current_version=N` on the STEPS entry below and update the checker
       to read the stamped version.
"""

import datetime
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_pipeline_meta import read_step_version, read_generated_at  # noqa: E402

OUTPUT_FILE = PROJECT_ROOT / "PIPELINE_STATUS.txt"

# Sources we consider canonical for any per_source step. Rows for these always
# appear even if no file exists yet — making "I haven't built this anywhere"
# visible. Per-step override via per_source["expected"].
EXPECTED_SOURCES = ("spanishdict", "wiktionary")


# ---------------------------------------------------------------------------
# Column discovery
# ---------------------------------------------------------------------------

def discover_artists():
    out = []
    for sub in sorted((PROJECT_ROOT / "Artists").iterdir()):
        if sub.is_dir() and (sub / "data").is_dir():
            out.append((sub.name, sub))
    return out


def discover_normal_modes():
    out = []
    data_root = PROJECT_ROOT / "Data"
    if not data_root.is_dir():
        return out
    for sub in sorted(data_root.iterdir()):
        if sub.is_dir() and (sub / "layers").is_dir():
            out.append(("Normal/%s" % sub.name, sub))
    return out


# ---------------------------------------------------------------------------
# Generic checkers
# ---------------------------------------------------------------------------

def check_file_versioned(path):
    """Return (version, mtime) for a versioned output file."""
    if not path or not Path(path).is_file():
        return (None, None)
    return (read_step_version(path), read_generated_at(path))


def check_file_unversioned(path):
    """Return (None, mtime) for an unversioned output file/dir."""
    if not path:
        return (None, None)
    p = Path(path)
    if not p.exists():
        return (None, None)
    try:
        return (None, int(p.stat().st_mtime))
    except OSError:
        return (None, None)


def check_file_glob_unversioned(dir_path, pattern):
    """Return (None, most-recent-mtime) for the first glob match in dir."""
    if not dir_path or not Path(dir_path).is_dir():
        return (None, None)
    matches = sorted(Path(dir_path).glob(pattern))
    if not matches:
        return (None, None)
    newest = max(matches, key=lambda p: p.stat().st_mtime)
    return (None, int(newest.stat().st_mtime))


# ---------------------------------------------------------------------------
# Versioned-step custom checkers (read from status.json, etc.)
# ---------------------------------------------------------------------------

def _load_spanishdict_status():
    path = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "spanishdict" / "status.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def check_spanishdict_artist(artist_dir):
    status = _load_spanishdict_status()
    if not status:
        return (None, None)
    entry = (status.get("artists") or {}).get(str(artist_dir.resolve()))
    if not entry:
        return (None, None)
    return (int(entry.get("step_version", 0) or 0), int(entry.get("updated_at", 0) or 0))


def check_spanishdict_normal(data_dir):
    """Min step_version across surface_status entries matching inventory words."""
    status = _load_spanishdict_status()
    if not status:
        return (None, None)
    inv_path = data_dir / "layers" / "word_inventory.json"
    try:
        with open(inv_path, encoding="utf-8") as f:
            inv = json.load(f)
    except (OSError, ValueError):
        return (None, None)
    words = {e.get("word", "").strip() for e in inv if isinstance(e, dict)}
    words.discard("")
    if not words:
        return (None, None)
    surface = status.get("surface") or {}
    versions, latest = [], 0
    for w in words:
        entry = surface.get(w)
        if not entry:
            continue
        versions.append(int(entry.get("step_version", 0) or 0))
        latest = max(latest, int(entry.get("updated_at", 0) or 0))
    if not versions:
        return (None, None)
    return (min(versions), latest)


# ---------------------------------------------------------------------------
# Step registry — every phase, every step, regardless of versioning status
#
# artist_output / normal_output: relative path checked for existence + mtime
#                                ("*" -> glob pattern from dir root)
# current_version: set to integer when step is retrofitted with step_version
# ---------------------------------------------------------------------------

STEPS = [
    # Each entry has a stable `id` that depends_on references. The `label` is
    # for display only and can be renamed without breaking dep edges.

    # Phase 1 — Acquire (artist only)
    {
        "id": "1a_lyrics",
        "label": "1a download_lyrics",
        "current_version": None,
        "artist_output": "data/input/batches",
        "normal_output": None,
    },
    {
        "id": "1b_translations",
        "label": "1b scrape_translations",
        "current_version": 1,
        "notes": {1: "geniURL + lyricsgenius community translations"},
        "artist_output": "data/input/translations/translations.json",
        "normal_output": None,
    },

    # Phase 2 — Extract / Count
    {
        "id": "2a_inventory",
        "label": "2a build_inventory / count_words",
        "current_version": 1,
        "notes": {1: "initial versioned schema"},
        "depends_on": ["1a_lyrics"],  # artist-only; resolves no-op for normal mode
        "artist_output": "data/word_counts/vocab_evidence.json",
        "normal_output": "layers/word_inventory.json",
        "extra_outputs": [
            {"label_suffix": "mwe_detected", "artist": "data/word_counts/mwe_detected.json"},
        ],
    },

    # Phase 3 — Normalize (artist only)
    {
        "id": "3a_elisions",
        "label": "3a merge_elisions",
        "current_version": 1,
        "notes": {1: "s/d-elision merge with corpus_count summing"},
        "depends_on": ["2a_inventory"],
        "artist_output": "data/elision_merge/vocab_evidence_merged.json",
        "normal_output": None,
    },

    # Phase 4 — Route
    {
        "id": "4a_routing",
        "label": "4a filter_known_vocab / route_clitics",
        "current_version": 1,
        "notes": {1: "initial versioned schema"},
        "depends_on": ["2a_inventory", "3a_elisions"],
        "artist_output": "data/known_vocab/word_routing.json",
        "normal_output": "layers/word_routing.json",
        "extra_outputs": [
            {"label_suffix": "detected_proper_nouns", "artist": "data/layers/detected_proper_nouns.json"},
        ],
    },

    # NOTE: steps with per_source expand into one row per source-file discovered
    # under the given dir. Dependencies declared on a per_source step that
    # reference another per_source step match the SAME source.

    # Phase 5 — Build Menus
    {
        "id": "5a_examples",
        "label": "5a build_examples / split_evidence",
        "current_version": 1,
        "notes": {1: "initial versioned schema"},
        "depends_on": ["2a_inventory", "3a_elisions", "4a_routing"],
        "artist_output": "data/layers/examples_raw.json",
        "normal_output": "layers/examples_raw.json",
        "extra_outputs": [
            # Artist 5a also produces word_inventory (split out of merged evidence).
            {"label_suffix": "word_inventory", "artist": "data/layers/word_inventory.json"},
        ],
    },
    {
        "id": "5b_conjugations",
        "label": "5b build_conjugations",
        "current_version": 1,
        "notes": {1: "verbecc + jehle + reverse lookup"},
        "depends_on": ["2a_inventory"],
        "artist_output": None,
        "normal_output": "layers/conjugations.json",
        "extra_outputs": [
            {"label_suffix": "reverse", "normal": "layers/conjugation_reverse.json"},
        ],
    },
    {
        "id": "5c_sense_menu",
        "label": "5c sense_menu",
        "current_version": 1,
        "notes": {1: "build_senses (normal) + build_spanishdict_menu (artist)"},
        "depends_on": ["2a_inventory", "5c_spanishdict_cache"],
        "per_source": {"artist_dir": "data/layers/sense_menu",
                       "normal_dir": "layers/sense_menu"},
    },
    {
        "id": "5c_spanishdict_cache",
        "label": "5c spanishdict_cache",
        "current_version": 2,
        "breaking_versions": {2},  # v2 added phrases extraction — content actually changed
        "notes": {1: "surface+headword", 2: "adds phrases_cache"},
        "depends_on": ["2a_inventory"],
        "artist_check": check_spanishdict_artist,
        "normal_check": check_spanishdict_normal,
    },
    {
        "id": "5d_mwes",
        "label": "5d build_mwes (wiktionary)",
        "current_version": 1,
        "notes": {1: "wiktionary MWE extraction, aho-corasick counting"},
        "depends_on": ["2a_inventory"],
        "artist_output": None,
        "normal_output": "layers/mwe_phrases.json",
    },

    # Phase 6 — Build Assignments
    {
        "id": "6a_assignments",
        "label": "6a sense_assignments",
        "current_version": 1,
        "notes": {1: "gemini/biencoder/keyword classifiers, method-priority merge"},
        "depends_on": ["5a_examples", "5c_sense_menu", "6a_pos"],
        "per_source": {"artist_dir": "data/layers/sense_assignments",
                       "normal_dir": "layers/sense_assignments"},
    },
    {
        "id": "6a_pos",
        "label": "6a tag_example_pos",
        "current_version": 2,
        "breaking_versions": {2},  # v2 swapped to transformer model — POS tags actually change
        "notes": {1: "legacy es_core_news_* models", 2: "es_dep_news_trf transformer default"},
        "depends_on": ["5a_examples"],
        "artist_output": "data/layers/example_pos.json",
        "normal_output": "layers/example_pos.json",
    },

    # Phase 7 — Consolidate
    {
        "id": "7a_lemma_assignments",
        "label": "7a sense_assignments_lemma",
        "current_version": 1,
        "notes": {1: "split assignments onto word|lemma keys"},
        "depends_on": ["6a_assignments", "5c_sense_menu"],
        "per_source": {"artist_dir": "data/layers/sense_assignments_lemma",
                       "normal_dir": "layers/sense_assignments_lemma"},
        "extra_outputs": [
            {"label_suffix": "unassigned_routing",
             "artist": "data/layers/unassigned_routing/{source}.json"},
        ],
    },
    {
        "id": "7b_cognates",
        "label": "7b flag_cognates",
        "current_version": 1,
        "notes": {1: "suffix score + CogNet voters"},
        "depends_on": ["5c_sense_menu"],
        "artist_output": None,
        "normal_output": "layers/cognates.json",
    },
    {
        "id": "7b_rerank",
        "label": "7b rerank",
        "current_version": 1,
        "notes": {1: "corpus_count + freq tiebreakers + cognate penalty"},
        "depends_on": ["7a_lemma_assignments", "7b_cognates"],
        "artist_output": "data/layers/ranking.json",
        "normal_output": None,
    },

    # Phase 8 — Assemble
    {
        "id": "8a_lrc",
        "label": "8a fetch_lrc_timestamps",
        "current_version": 1,
        "notes": {1: "LRCLIB synced lyrics + line matching"},
        "depends_on": ["5a_examples"],
        "artist_output": "data/layers/lyrics_timestamps.json",
        "normal_output": None,
    },
    {
        "id": "8a_assemble",
        "label": "8a assemble_vocabulary",
        "current_version": 1,
        "notes": {1: "monolith + index + examples split, hex IDs"},
        "depends_on": ["7a_lemma_assignments", "5a_examples",
                       "5b_conjugations", "5d_mwes", "7b_cognates"],
        "artist_output": None,
        "normal_output": "vocabulary.json",
        "extra_outputs": [
            {"label_suffix": "index", "normal": "vocabulary.index.json"},
            {"label_suffix": "examples", "normal": "vocabulary.examples.json"},
        ],
    },
    {
        "id": "8b_artist_assemble",
        "label": "8b assemble_artist_vocabulary",
        "current_version": 1,
        "notes": {1: "artist monolith + index + examples + master update"},
        "depends_on": ["7a_lemma_assignments", "7b_rerank", "8a_lrc"],
        "artist_glob": ("*vocabulary.json",),
        "normal_output": None,
        "extra_outputs": [
            {"label_suffix": "index", "artist_glob": ("*vocabulary.index.json",)},
            {"label_suffix": "examples", "artist_glob": ("*vocabulary.examples.json",)},
            {"label_suffix": "clitic_forms", "artist": "data/layers/clitic_forms.json"},
        ],
    },
    {
        "id": "8c_master",
        "label": "8c merge_to_master",
        "current_version": 1,
        "notes": {1: "merge artist monoliths into shared master"},
        "depends_on": ["8b_artist_assemble"],
        "shared_output": "Artists/vocabulary_master.json",
        "normal_output": None,
    },
]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def discover_per_source_names(step, columns):
    """Return sorted set of source names for this per_source step.

    Union of:
      - sources actually present on disk in any column
      - declared expected sources (so absent-everywhere sources still get a row)
    """
    cfg = step.get("per_source") or {}
    sources = set(cfg.get("expected", EXPECTED_SOURCES))
    for col_name, kind, dir_path in columns:
        sub = cfg.get("artist_dir" if kind == "artist" else "normal_dir")
        if not sub:
            continue
        scan = dir_path / sub
        if not scan.is_dir():
            continue
        for f in scan.glob("*.json"):
            if f.name.endswith(".meta.json"):
                continue
            sources.add(f.stem)
    return sorted(sources)


def expand_step(step, columns):
    """Yield one derived step per (per_source × extra_output) combination.

    A step can declare:
      - per_source: expand into one row per source (spanishdict, wiktionary, ...)
      - extra_outputs: list of {label_suffix, artist?, normal?, shared?, artist_glob?}
        emitting one extra row per file beyond the canonical output

    Both can combine — per_source × extra_outputs gives a full grid.
    """
    cfg = step.get("per_source")
    extras = step.get("extra_outputs") or []

    # First decide the source axis
    if cfg:
        sources = discover_per_source_names(step, columns)
        if not sources:
            sources = [None]  # one row, no source bracket
    else:
        sources = [None]

    # Then decide the output axis: canonical row + each extra
    output_specs = [None]  # canonical (use step's own artist_output/normal_output/etc.)
    output_specs.extend(extras)

    for source in sources:
        for spec in output_specs:
            derived = dict(step)
            label = step["label"]
            if source is not None:
                label += " [%s]" % source
            if spec is not None and spec.get("label_suffix"):
                label += " / %s" % spec["label_suffix"]
            derived["label"] = label
            # Apply per_source paths to canonical output (when canonical row, not extra)
            if cfg and source is not None and spec is None:
                if cfg.get("artist_dir"):
                    derived["artist_output"] = "%s/%s.json" % (cfg["artist_dir"], source)
                if cfg.get("normal_dir"):
                    derived["normal_output"] = "%s/%s.json" % (cfg["normal_dir"], source)
            # Apply extra-spec overrides
            if spec is not None:
                # Wipe inherited canonical paths so extra spec is the only source
                for k in ("artist_output", "normal_output", "artist_check",
                         "normal_check", "shared_output", "artist_glob"):
                    derived.pop(k, None)
                if "artist" in spec:
                    derived["artist_output"] = spec["artist"].format(source=source) if source and "{source}" in spec["artist"] else spec["artist"]
                if "normal" in spec:
                    derived["normal_output"] = spec["normal"].format(source=source) if source and "{source}" in spec["normal"] else spec["normal"]
                if "shared" in spec:
                    derived["shared_output"] = spec["shared"]
                if "artist_glob" in spec:
                    derived["artist_glob"] = spec["artist_glob"]
            derived.pop("per_source", None)
            derived.pop("extra_outputs", None)
            yield derived


def resolve_cell(step, kind, dir_path):
    """Return (current_version, observed_version_or_None, timestamp_or_None)."""
    current = step.get("current_version")
    # Custom checker path (versioned steps with non-file-based storage)
    if kind == "artist" and "artist_check" in step:
        v, ts = step["artist_check"](dir_path)
        return (current, v, ts)
    if kind == "normal" and "normal_check" in step:
        v, ts = step["normal_check"](dir_path)
        return (current, v, ts)
    # Shared output (same file checked for every artist column)
    if kind == "artist" and step.get("shared_output"):
        p = PROJECT_ROOT / step["shared_output"]
        if current:
            v, ts = check_file_versioned(p)
        else:
            v, ts = check_file_unversioned(p)
        return (current, v, ts)
    # Glob-based artist check
    if kind == "artist" and step.get("artist_glob"):
        patterns = step["artist_glob"]
        for pat in patterns:
            _, ts = check_file_glob_unversioned(dir_path, pat)
            if ts:
                return (current, None, ts)
        return (current, None, None)
    # Relative path check
    rel = step.get("artist_output" if kind == "artist" else "normal_output")
    if not rel:
        return (current, None, None)
    path = dir_path / rel
    if current:
        v, ts = check_file_versioned(path)
    else:
        v, ts = check_file_unversioned(path)
    return (current, v, ts)


def fmt_cell(current, breaking_versions, observed, ts, newer_dep_ts=None):
    """Render one grid cell.

    Precedence (highest first):
      STALE  — observed predates a breaking version bump (re-run to fix content)
      older  — version is current, but a dependency was regenerated since
               (re-run to pick up upstream changes)
      stamp  — version predates only cosmetic bumps (output content is fine)
      OK     — version matches and inputs are not newer
    """
    if ts is None and observed is None:
        return "—"
    date = datetime.datetime.fromtimestamp(ts).strftime("%m-%d") if ts else "??-??"
    if current is None:
        return "exists %s" % date
    v = observed if observed is not None else 0
    has_newer_dep = bool(newer_dep_ts and ts and newer_dep_ts > ts)
    if v < current:
        breaking_in_gap = any(bv > v and bv <= current for bv in (breaking_versions or set()))
        if breaking_in_gap:
            return "STALE v%d %s" % (v, date)
        # Cosmetic-only version gap. If an input is newer, the content IS stale
        # by cascade — escalate to "older". Otherwise it's just stamp-pending.
        if has_newer_dep:
            return "older v%d %s" % (v, date)
        return "stamp v%d %s" % (v, date)
    # Version matches — check input freshness
    if has_newer_dep:
        return "older v%d %s" % (v, date)
    return "OK    v%d %s" % (v, date)


def build_report():
    artists = discover_artists()
    normals = discover_normal_modes()
    columns = [(name, "artist", d) for name, d in artists] + \
              [(name, "normal", d) for name, d in normals]

    expanded = [s for step in STEPS for s in expand_step(step, columns)]

    # Pass 1: compute (current, observed, ts, applies) for every (step, column).
    # Stored in a dict keyed by (label, col_name) for dependency lookup.
    raw = {}
    for step in expanded:
        for col_name, kind, dir_path in columns:
            current, observed, ts = resolve_cell(step, kind, dir_path)
            applies = (
                ("artist_check" in step and kind == "artist") or
                ("normal_check" in step and kind == "normal") or
                step.get("shared_output") and kind == "artist" or
                step.get("artist_glob") and kind == "artist" or
                step.get("artist_output" if kind == "artist" else "normal_output")
            )
            raw[(step["label"], col_name)] = (current, observed, ts, applies)

    # Build a lookup of expanded rows by their stable id.
    # A dep declared as id="5c_sense_menu" matches every expansion of that step.
    expanded_by_id = {}
    for step in expanded:
        expanded_by_id.setdefault(step["id"], []).append(step["label"])

    # Validate dep references early so typos fail loudly instead of silently.
    known_ids = set(expanded_by_id.keys())
    for step in expanded:
        for dep_id in step.get("depends_on", []):
            if dep_id not in known_ids:
                raise SystemExit(
                    "Unknown dep id %r referenced by step id %r (label %r). "
                    "Available ids: %s"
                    % (dep_id, step["id"], step["label"], sorted(known_ids))
                )

    def resolve_dep_labels(step, dep_id):
        """Return list of expanded labels matching this dep id.

        If both step and dep are per_source-derived, match same source.
        Otherwise match all expansions of the dep id.
        """
        candidates = expanded_by_id.get(dep_id, [])
        if " [" in step["label"]:  # step is per_source-expanded
            source = step["label"].split(" [", 1)[1].split("]")[0]
            same_source = [c for c in candidates if "[" + source + "]" in c]
            if same_source:
                return same_source
        return candidates

    # Pass 2: render cells, applying dependency cascade.
    rows = []
    for step in expanded:
        label = step["label"]
        if step.get("current_version") is not None:
            label = "%s (v%d)" % (label, step["current_version"])
        breaking = step.get("breaking_versions", set())
        cells = []
        for col_name, kind, dir_path in columns:
            current, observed, ts, applies = raw[(step["label"], col_name)]
            if not applies:
                cells.append("n/a")
                continue
            # Find newest dep ts in this column
            newer_dep_ts = None
            for dep_root in step.get("depends_on", []):
                for dep_label in resolve_dep_labels(step, dep_root):
                    dep = raw.get((dep_label, col_name))
                    if not dep:
                        continue
                    _, _, dep_ts, dep_applies = dep
                    if dep_applies and dep_ts:
                        if newer_dep_ts is None or dep_ts > newer_dep_ts:
                            newer_dep_ts = dep_ts
            cells.append(fmt_cell(current, breaking, observed, ts, newer_dep_ts))
        rows.append((label, cells))

    col_widths = [max(len(col[0]), max(len(r[1][i]) for r in rows))
                  for i, col in enumerate(columns)]
    label_width = max(len(r[0]) for r in rows)

    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("Pipeline Status")
    lines.append("Generated: %s (local)" % now)
    lines.append("")
    lines.append("Legend:")
    lines.append("  OK    v<N> — output matches current step_version, inputs not newer")
    lines.append("  STALE v<N> — output predates a BREAKING bump — re-run to fix content")
    lines.append("  older v<N> — version is current, but a DEPENDENCY was regenerated since")
    lines.append("               this output. Re-run to pick up the upstream changes.")
    lines.append("  stamp v<N> — output predates only COSMETIC bumps — content is probably")
    lines.append("               fine, just hasn't been re-stamped. Don't re-run unless")
    lines.append("               you specifically want the stamp updated.")
    lines.append("  exists     — output exists, step not yet retrofitted with step_version")
    lines.append("  —          — output missing")
    lines.append("  n/a        — step does not apply to this mode/artist")
    lines.append("")
    lines.append("Note for LLMs: \"stamp\" entries do NOT need re-running. \"older\" entries")
    lines.append("DO need re-running because an upstream input has changed.")
    lines.append("")

    header = "%s | %s" % (
        "Step".ljust(label_width),
        " | ".join(col[0].ljust(w) for col, w in zip(columns, col_widths)),
    )
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)
    for label, cells in rows:
        lines.append("%s | %s" % (
            label.ljust(label_width),
            " | ".join(c.ljust(w) for c, w in zip(cells, col_widths)),
        ))

    # Version notes footer for retrofitted steps
    lines.append("")
    lines.append("Version notes:")
    any_notes = False
    for step in STEPS:
        notes = step.get("notes")
        if not notes:
            continue
        any_notes = True
        for v, note in sorted(notes.items()):
            lines.append("  %s v%d: %s" % (step["label"], v, note))
    if not any_notes:
        lines.append("  (no versioned steps yet)")

    return "\n".join(lines) + "\n"


def main():
    report = build_report()
    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print("Wrote %s" % OUTPUT_FILE)


if __name__ == "__main__":
    main()
