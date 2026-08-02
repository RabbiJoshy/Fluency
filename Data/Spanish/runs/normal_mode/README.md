# Spanish Normal Mode run registry

This directory preserves immutable sense/example pipeline checkpoints. The
working files under `Data/Spanish/layers/` remain the inputs consumed by the
existing builders; they are not the historical record.

Each run contains its exact SpanishDict menu, surface assignments, lemma
assignments, derived distributions, and a manifest with hashes and provenance.
Never edit an archived run in place. Create a new run ID instead.

Archive the active layers with:

```bash
.venv/bin/python3 pipeline/tool_6d_archive_normal_run.py \
  --run-id YYYY-MM-DD_short_description \
  --purpose "Why this run exists"
```

`Data/Spanish/active_normal_run.json` identifies the checkpoint currently used
as the comparison or deployment baseline. Changing that pointer does not by
itself copy a run back into `layers/`; activation should remain an explicit,
reviewed operation so a mistaken pointer cannot overwrite working data.

Large downloadable corpora do not belong here. Compact, expensive-to-recreate
menus, assignments, distributions, curated examples, and their manifests do.
