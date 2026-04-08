---
title: Level estimation algorithm
status: implemented
created: 2026-02-01
updated: 2026-04-08
---

# Level Estimation Algorithm

## Decision

Adaptive staircase: one word at a time, step size halves on reversals.

## Parameters

- Converges when step < 50 AND 5 consecutive correct, or after 30 words max
- Uses Spanish frequency list for word selection
- Open question: use base Spanish frequency list even in artist mode (less genre bias). Tracked as [soon] in TODO.md.

## Key files

- `js/estimation.js` — algorithm implementation
