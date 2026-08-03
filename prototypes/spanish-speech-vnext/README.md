# Spanish Speech Mode vNext preview

This is an isolated, non-shipping prototype of the four-word Speech evidence experiment. It does
not alter the active deck, app entry point, or service worker.

The same exporter now also writes the first immutable app-facing Speech vNext deck to
`Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json`. The real app consumes that
versioned artifact at `index.html?speech=vnext`; it does not depend on prototype assets.

## Open it

From the repository root:

```bash
python3 prototypes/spanish-speech-vnext/build_preview_data.py
python3 -m http.server 8765 --directory prototypes/spanish-speech-vnext
```

Then open `http://127.0.0.1:8765/`.

Use **Learner** view to judge the proposed product surface: ordered senses, broad prominence labels,
and one SpanishDict example attached to every displayed sense. Use **Evidence** view to inspect the
small sample counts, stable SpanishDict IDs, and unaudited OpenSubtitles candidates—including known
failure cases for `cola`.

The generated `preview-data.js` is a compact derivative of:

`Data/Spanish/Intermediates/speech_mode_evidence/runs/2026-08-03_v0_1`
