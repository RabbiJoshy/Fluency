#!/usr/bin/env bash
#
# run_spanish_rerun.sh — one command to roll out every DEFERRED Spanish deck fix.
#
# The no-rerun fixes (front-end empty-meaning guard + the 6 in-place master
# patches) are already live. THIS script is for the deck-quality work that
# genuinely needs the pipeline: re-running Gemini sense assignment so verbose
# definitions get repaired, then rebuilding + re-stamping the master. Run it
# when the machine + Gemini budget are free.
#
# What it does, in order:
#   1. Re-run steps 6 -> build for each Spanish artist (Gemini reclassify +
#      gap-fill, --force so existing verbose defs get repaired; --skip 8 skips
#      the slow LRC-timestamp network fetch — timestamps don't change unless
#      lyrics do).
#   2. Rebuild the shared master from the per-artist monoliths.
#   3. Re-stamp the flags the rebuild drops (loanword, proper-noun-by-corpus).
#   4. Re-apply the 6 curated in-place patches (millo, niveles, diablo, ...).
#   5. Verify with the read-only bench.
#   6. Print the cache-bump checklist (data changed -> users need fresh fetch).
#
# !!! PIJP / DUTCH CONFLICT !!!
#   Phase 2 (tool_8c_merge_to_master) rebuilds the master for EVERY language,
#   Dutch included — it has no --language flag. Do NOT run this while the Dutch
#   "Pijp" pipeline is active or you will corrupt that job's inputs/outputs.
#   The script asks for confirmation before doing anything; pass --yes to skip
#   the prompt once you're certain Pijp is done.
#
# COST: phase 1 uses --force, so Gemini re-classifies every word for all three
#   artists. That is a real (paid) Gemini Flash-Lite run and takes a while.
#
# Usage (from the project root, in your own terminal — not inline):
#   ./run_spanish_rerun.sh
#   ./run_spanish_rerun.sh --yes      # skip the Pijp confirmation prompt

set -euo pipefail

# Always operate from the repo root (where this script lives), so the relative
# .venv / pipeline / Artists paths resolve no matter where it's invoked from.
cd "$(dirname "$0")"

PY=".venv/bin/python3"
ARTISTS=("Bad Bunny" "Young Miko" "Rosalía")

AUTO_YES=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) AUTO_YES=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found. Run from the project root with the venv present." >&2
  exit 1
fi

bar() { printf '\n=== %s ===\n' "$1"; }

# ---------------------------------------------------------------------------
# Safety gate: this rebuilds ALL languages. Make sure Pijp/Dutch is not running.
# ---------------------------------------------------------------------------
bar "PRE-FLIGHT"
echo "This rebuilds the master for ALL languages (Dutch included) and will run"
echo "a full --force Gemini reclassify for: ${ARTISTS[*]}."
echo

# Advisory heuristic — warns, does not auto-abort (avoids false positives).
if pgrep -fil 'pijp|opensubtitles|dutch' 2>/dev/null | grep -vi 'run_spanish_rerun' >/dev/null 2>&1; then
  echo "WARNING: a process matching pijp/opensubtitles/dutch appears to be running:"
  pgrep -fil 'pijp|opensubtitles|dutch' 2>/dev/null | grep -vi 'run_spanish_rerun' || true
  echo
fi

if [ "$AUTO_YES" -ne 1 ]; then
  read -r -p "Is the Dutch/Pijp pipeline finished and is it safe to proceed? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "Aborted. Re-run with --yes once Pijp is done."; exit 0 ;;
  esac
fi

START_TS=$(date +%s)

# ---------------------------------------------------------------------------
# Phase 1 — per-artist Gemini reclassify + reassemble (steps 6 -> build).
#   6   assign senses (Gemini + gap-fill)   <- repairs verbose definitions
#   7a  map senses to lemmas
#   7b  rerank
#   8   fetch LRC timestamps                 <- SKIPPED (slow, unchanged)
#   build  assemble artist vocabulary        <- re-reads cognates layer etc.
# set -e aborts the whole script if any artist fails, so the merge never runs
# against a half-rebuilt artist.
# ---------------------------------------------------------------------------
for ARTIST in "${ARTISTS[@]}"; do
  bar "PHASE 1: reclassify + assemble — $ARTIST"
  "$PY" pipeline/artist/run_artist_pipeline.py \
    --artist "$ARTIST" \
    --from-step 6 \
    --classifier gemini \
    --gap-fill \
    --force \
    --skip 8
done

# ---------------------------------------------------------------------------
# Phase 2 — rebuild the shared master from the per-artist monoliths.
#   (No --language flag: rebuilds every language. See the Pijp warning above.)
# ---------------------------------------------------------------------------
bar "PHASE 2: rebuild master (ALL languages)"
"$PY" pipeline/artist/tool_8c_merge_to_master.py

# ---------------------------------------------------------------------------
# Phase 3 — re-stamp the flags the rebuild drops (unknown fields are not kept).
#   These write to the master in place; the front-end reads them at runtime.
# ---------------------------------------------------------------------------
bar "PHASE 3: re-stamp loanword flag"
"$PY" pipeline/tool_8a_stamp_loanword_flag.py --language Spanish --master

bar "PHASE 3: re-stamp proper-noun-by-corpus flag"
"$PY" pipeline/tool_8a_stamp_propernoun_corpus.py --language Spanish

# ---------------------------------------------------------------------------
# Phase 4 — re-apply the curated in-place patches (idempotent).
# ---------------------------------------------------------------------------
bar "PHASE 4: re-apply curated master patches"
"$PY" pipeline/tool_8c_patch_master_curated.py

# ---------------------------------------------------------------------------
# Phase 5 — verify (read-only; replicates the front-end default filters).
# ---------------------------------------------------------------------------
bar "PHASE 5: deck-quality bench (read-only)"
"$PY" pipeline/bench_deck_quality.py

# ---------------------------------------------------------------------------
# Phase 6 — cache-bump checklist (the master + index changed, and the master
# has no ?v= tag, so users only get fresh data after a service-worker cache
# bump). Bump ALL of these in lockstep to today's date + a letter, e.g.
# 20260613a -> 20260614a and flashcards-v36 -> flashcards-v37:
#   - service-worker.js : CACHE_NAME  and  ASSET_VERSION
#   - js/main.js        : every ?v= import tag
#   - index.html        : every ?v= modulepreload + the main.js script tag
# ---------------------------------------------------------------------------
ELAPSED=$(( $(date +%s) - START_TS ))
bar "DONE in ${ELAPSED}s"
echo "Data rebuilt. To ship it to users, bump the cache version in lockstep:"
echo "  service-worker.js : CACHE_NAME (e.g. flashcards-v36 -> v37)"
echo "                      ASSET_VERSION (e.g. 20260613a -> 20260614a)"
echo "  js/main.js        : every ?v= import tag  -> same ASSET_VERSION"
echo "  index.html        : every ?v= tag         -> same ASSET_VERSION"
echo
echo "Then: git pull --rebase, commit, push."
