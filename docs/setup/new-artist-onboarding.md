# Adding a New Artist

Procedural guide for onboarding a new artist into the artist-mode pipeline.

## Steps

1. **Create the artist config**: `Artists/{lang}/{Name}/artist.json` with fields:
   - `name`
   - `genius_query` (used by step 1 to scrape lyrics)
   - `vocabulary_file` (output filename)

2. **Download lyrics**: Run step 1.
   ```bash
   .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "{Name}" --from-step 1 --to-step 1
   ```

3. **Curate `duplicate_songs.json`**: See `Artists/DEDUP_INSTRUCTIONS.md`. Use `Artists/tools/scan_duplicates.py` for automated remix/live-version detection.

4. **Copy reusable curated data** from an existing artist if appropriate:
   - `conjugation_families.json`
   - `skip_mwes.json`
   - any artist-specific `curated_translations.json` entries that generalize

5. **Run the pipeline** (cheap-first workflow):
   ```bash
   # Free pass first
   .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "{Name}" --classifier keyword --no-gap-fill

   # Then add Gemini translations if quality warrants
   .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "{Name}" --words-only
   ```
   See `docs/setup/artist-pipeline-quick-start.md` for full mode reference.

6. **Builder auto-produces** `index.json` + `examples.json` from layers. No additional step needed.

7. **Register in front-end**: add the artist to `config/artists.json` (sets paths, color, masterPath, etc.).

8. **Shared vocab benefits**: words shared with existing artists get translations via client-side merge (`joinWithMaster()` in `js/vocab.js`) — no Gemini needed for overlapping vocab.

## Verification

- Open `index.html?artist={slug}` and spot-check the deck.
- Look for words with `pos=X` or empty translations — these indicate uncovered cases that may need curated overrides or short-word-whitelist additions.
- Check that lyrics-mode features work: example cycling, album art, Spotify links if applicable.
