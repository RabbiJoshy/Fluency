# Sense Assignment Internals — Reference

Deep details of step 6 (sense assignment) and step 7a (lemma split + unassigned routing). Read on demand when working in this area.

For the high-level dispatcher model, see `pipeline/CLAUDE.md` "Sense Assignment Model". For method priority numbers see `docs/reference/method_priority.md`.

---

## Surface form normalization

Step 3 stamps a `surface` field on each example recording the original word form found in the lyrics (e.g. `"vece'"` for inventory key `"veces"`). Step 5 carries this through to `examples_raw.json`. Downstream consumers use it to:

- **POS tagger** (`tool_6a_tag_example_pos.py`): substitutes the canonical word into the sentence before spaCy tagging, so spaCy sees proper Spanish.
- **Sense assignment** (`step_6b`, `step_6c`): same substitution for bi-encoder embedding and Gemini prompts. Translation lookup uses the original (pre-substitution) Spanish as the key.

Re-running step 3 backfills `surface` on all examples, then step 5's backfill (`if not prev_ex.get("surface") and new_by_id[eid].get("surface")`) propagates it to `examples_raw.json`. If the surface field is ever missing on tagged examples, re-run 3 + 5 together — do not patch per-word.

## Orthogonal POS labels

`pipeline/util_6a_pos_menu_filter.py` defines `_ORTHOGONAL_POS = {"PHRASE", "CONTRACTION"}`. These sense POS types are **never filtered out** by observed-POS narrowing — they apply regardless of the surface word's grammatical POS (an idiom or contraction can surface as any POS in context). Both filter paths (`filter_senses_by_pos` live tagging, `filter_senses_by_precomputed_pos`) keep orthogonal senses in the candidate pool.

When adding new SpanishDict POS labels to `_POS_MAP` in `pipeline/util_5c_spanishdict.py`, decide per-label whether it represents a grammatical category (filterable) or an orthogonal category (survives filtering) and update `_ORTHOGONAL_POS` accordingly.

## Keyword classifier (`step_6b`)

- **Dynamic stop-word exemption**: `classify_example_keyword` collects every token present in any candidate sense translation and exempts those tokens from `_STOP_WORDS` for that word's classification. This lets function-word translations like `"that"` (que), `"but"` (pero), `"than"` (que) survive filtering and actually match against example English. For unrelated words, `"that"` stays as a stop word to avoid spurious matches.
- **No fallback dump**: when no example matches any keyword, the word gets **no assignment at all**. Previously the classifier would dump all examples into sense 0 as a last resort; that made every SpanishDict entry look keyword-assigned even when it wasn't. Now the word falls through to the builder's remainder bucketing.

## SpanishDict cache coverage

The SpanishDict **phrases cache** (`Data/Spanish/senses/spanishdict/phrases_cache.json`) was introduced after the initial scrape of Bad Bunny, Young Miko, and normal mode. Only Rosalía has full phrases coverage. Re-run `tool_5c_build_spanishdict_cache.py --force` for each to populate MWE phrases:

```bash
.venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py --artist-dir "Artists/spanish/Bad Bunny" --force
.venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py --artist-dir "Artists/spanish/Young Miko" --force
.venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py --inventory-file Data/Spanish/layers/word_inventory.json --force
```

After re-scraping, rebuild the SpanishDict sense menu with `step_5c_build_senses.py --sense-source spanishdict --artist-dir "Artists/{lang}/{Name}" --force` (or omit `--artist-dir` for normal mode) to pick up newly cached headword redirects and phrases.

---

## Step_7a — lemma split + unassigned routing

Step 7a does two things:

1. **Splits word-level sense assignments** onto `word|lemma` keys using the sense IDs of each analysis. Writes to `sense_assignments_lemma/{source}.json`.
2. **Routes every unassigned raw example to one `word|lemma` key** based on its spaCy POS tag. Writes to `unassigned_routing/{source}.json` as `{lemma_key: [raw_example_idx, ...]}`.

### Routing rules

In `_route_unassigned_for_word` in `pipeline/step_7a_map_senses_to_lemmas.py`:

- If the example's POS is in `_TRUSTED_ROUTING_POS` (`{VERB, NOUN, ADJ, ADV, INTJ}`) and at least one analysis has senses of that POS, route to the analysis with the most senses of that POS (tiebreak: most existing assignments).
- If the POS is untrusted (`PRON`, `CCONJ`, `DET`, `PHRASE`, `CONTRACTION`, …) or missing, or no analysis has a matching POS, route to the **primary analysis** — the one with the most keyword assignments (tiebreak: first analysis).

This means `gana` (with 4 analyses: gana, ganas, ganar, ganarse) produces distinct cards per lemma. NOUN-tagged unassigned examples land on `gana|ganas` (most NOUN senses) instead of piling onto the ganar card.

`example_pos.json` and `examples_raw.json` are optional inputs — if either is missing, step 7a skips routing or routes everything to the primary analysis.

---

## SENSE_CYCLE remainder behavior (`step_8b`)

Step 8b reads `unassigned_routing/<source>.json` and attaches each group's routed indices as `group["unassigned_ex_indices"]`. A group becomes a card if it has **either** keyword assignments **or** routed unassigned examples — a group with only routed examples produces a SENSE_CYCLE-only card. No build-time POS routing happens here; 8b is pure assembly.

When `best_method` is keyword-level, the builder turns routed unassigned examples into SENSE_CYCLE remainder rows, grouped by the example's spaCy POS tag:

- Trusted POS (`{VERB, NOUN, ADJ, ADV, INTJ}`) → POS-specific bucket; `allSenses` lists every sense of that POS in the current group.
- Untrusted or missing POS → universal `ANY` bucket; `allSenses` lists every sense in the group across all POS.
- Keyword-assigned examples are never duplicated into remainder rows.
- Gemini/bi-encoder assignments do not generate remainder rows.
- Remainders with zero examples are never emitted.

SENSE_CYCLE entries always use `pos: "SENSE_CYCLE"` (with `cycle_pos` carrying the actual POS or `"ANY"`) — this keeps them out of the master vocabulary. The builder filters SENSE_CYCLE/X senses when writing to master, which prevents single-sense remainders from colliding with assigned senses of the same translation.

---

## `assignment_method` propagation

Keyword-level assignments (priority ≤ 15: `spanishdict-keyword`, `keyword-wiktionary`, etc.) propagate in two places:

- **Per-example**: Each example dict in `*.examples.json` carries its own `assignment_method`. The builder stamps the method from `assignment.get("method")` on every example in an assignment. This is the authoritative signal for per-example UI decisions (border, English keyword highlight).
- **Per-meaning**: Informational `assignment_method` field on the assembled meaning (only for keyword-level best methods, for UI fallback when examples lack the stamp).
- **Per-sense in index**: `sense_methods[i]` on the index entry, used by front-end `joinWithMaster()` to reconstruct the per-sense flag. `null` entries in `sense_methods` plus `idx.unassigned = true` signal a random/remainder bucket.
