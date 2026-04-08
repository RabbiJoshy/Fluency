---
title: Layered pipeline architecture
status: implemented
created: 2026-03-01
updated: 2026-04-08
---

# Layered Pipeline Architecture

## Decision

Both pipelines (normal mode and artist mode) use a layered architecture where each step writes its own output file. No step mutates another step's output. A final builder step assembles all layers into front-end files.

## Design

Each step reads its inputs, produces a layer file, and is independently re-runnable. Re-run any step, then `--from-step build` to reassemble.

**Normal mode layers:** `Data/Spanish/layers/`
**Artist mode layers:** `Artists/{Name}/data/layers/`

Schemas parallel each other where applicable (e.g., both have `word_inventory.json`, `examples_raw.json`, `sense_assignments.json`).

See `Artists/CLAUDE.md` for the full layer file table.
