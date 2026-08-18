# Fluency — Artist-mode WSD

## What this is

Word sense disambiguation for a Spanish vocabulary app. A card is a surface form; each sense carries a `headword` and `pos` from SpanishDict. The job is assigning corpus lines to senses.

**The only fixed constraint is cost and speed at scale** — many languages, a deck built in a minute. Everything else is negotiable including the current stack (gloss embeddings + BETO + `gemini-3.5-flash-lite`). Treat it as the thing to beat, not defend. New tools and libraries are welcome.

Artist mode is the surface because it's the harder case: fixed corpus, hard register (slang, elision, fragments), thin evidence — usually one occurrence per word, so one bad call is the whole card. **Per-sentence accuracy is the metric, not yield.**

## The working loop — non-negotiable

Change **one** thing → rebuild the test playlist → **render the cards and grade them yourself** → sort errors into *classes* → propose options → Josh chooses.

```bash
.venv/bin/python3 pipeline/step_6e_assign_senses_calibrated.py --artist-dir "Artists/spanish/SpanishTestPlaylist" --escalate all
```
```bash
.venv/bin/python3 pipeline/artist/step_7a_map_senses_to_lemmas.py --artist-dir "Artists/spanish/SpanishTestPlaylist"
```
```bash
.venv/bin/python3 pipeline/artist/step_8b_assemble_artist_vocabulary.py --artist-dir "Artists/spanish/SpanishTestPlaylist" --prompt-policy testplaylist-beto-cal-pinned
```

Then `scripts/update_offline_content_manifest.py`, bump `CACHE_NAME`, verify with `tools/check_asset_versions.py`. Deck appears as "Joshua's Test Playlist". A few cents, a few minutes.

Three rules, each learned expensively last session:

- **The rendered card is the only truth.** Not the deck JSON — `js/` repairs a lot at render time, and three "findings" were phantoms from reading JSON (93 blank cards were 47; 152 junk cards were 45; 78 duplicate rows were 0). Use `pipeline/tool_8j_render_cards.py`. `test_tool_8j_render_parity.py` fails if `js/` drifts from it.
- **You are the judge.** Outsourcing grading to a cheaper model cost £10 and produced a 4.7pp regression that didn't exist. Grading 190 cards by hand took two tool calls and found the same rate plus the actual error classes. Do not build an automated grader.
- **One variable per pass.** Moving the prompt and the judge together made the result unattributable.

Weight Josh's card-level observations above any number. When he says something looks wrong, believe the symptom and find it.

## Shipped last session

- **Leaf selection** (`pipeline/util_6e_leaf_selection.py` → `step_6e`): the `used with` leaf gate, measured 9:1 and previously unbuilt. 216 repairs; tuple never moves, so no calibration is invalidated.
- **Routing floor removed** (`step_4a --floor-drops`, `step_6c discovery_words`): a corpus-frequency floor was applied twice and ate exactly the genre slang the deck exists to teach. `bellaqueos`, `switchear`, `glopeta`, `locotrón`, `rulay` and others now reach discovery and land in Main; brands abstain into Extra.
- **`--escalate all`**: local path 67.1% vs escalated 82.5%, and escalation was running on 28% of the deck. **71.3% → 84.8%** on graded rendered cards.
- **Lemma corruption fixed**: `sense_id` is unique *within a word*, not globally (96,279 senses share 8,416 ids). A global map was showing `cama` → *haberes*, `pero` → *loco*.
- Commits `88b0f717`, `fc7e7e41`, `4ddf8189`; cache v261.

## First: make the architecture whole

Josh's direction — get the whole thing running end to end in the best predicted way *before* iterating. Each of these is a piece that exists, works, and isn't connected. The recurring shape in this codebase is **the right answer computed upstream and discarded downstream** — check upstream before writing new detection.

1. **Proper-noun stamping is orphaned.** `caps_stats.json` is built (`rompiendo` sits at `cap_rate 1.0`), `js/vocab.js` honours `is_propernoun_corpus` by default — and `tool_8a_stamp_propernoun_corpus.py` is a `tool_`, absent from `run_artist_pipeline.py`. **0 cards** in the playlist carry the flag. This is why "Sky Rompiendo" (a producer tag) is a vocabulary card. Check whether `--min-obs` admits 2-observation words before assuming it fixes that case.
2. **The elision backstop is starved.** `step_2c_resolve_elisions_gemini.py` is in the orchestrator and does the right thing — Gemini on unconfident cases only — but saw **6 words**. `step_3a_merge_elisions` resolved `ma'` → `mas` (literary "but") *confidently*, so the vocative never reached it. Architecture right, confidence threshold wrong. Improve the deterministic half first; Gemini goes over the top.
3. **Verify `step_4a` kept all three signals** from `legacy_detect_proper_nouns.py` (capitalisation ratio + spaCy NER + curated list), which claims to have superseded it.
4. **`test_song_count_pipeline.py::test_trailing_apostrophe_restores_z_only_when_unambiguous` fails** and has for a while — same area, `trailing_apos_restore` in `step_3a`.
5. **MWE components render standalone** though the expression is detected: `por más que` is in the layer with `count: 2`, and `más` and `por` still show their own glosses.

## MWE — options open, no decision made

Excluding words that are members of a **known** MWE removes that error class cleanly, because membership is already computed — nothing needs detecting. That's the floor.

The interesting direction, Josh's: **a surface-form card carries a sense that *is* the MWE**, alongside the separate MWE page. `más` stays teachable; `por más que` owns the meaning it actually carries.

Live options — rank them with evidence, don't assume:
- exclude MWE-member occurrences from word cards entirely
- reroute the occurrence to the expression
- keep both, mark the word
- later-pass idea: during invention, let the prompt propose a **multi-word** gloss when no single word translates the line well

This touches sense identity, which is load-bearing — sense IDs carry per-sense learner progress (`COLLABORATION.md` rule 4). Agree the contract before changing it.

## The crux: predicting when to escalate

Not "which words lack a menu" — that's routing, solved. The question is **per-occurrence: does anything in this menu fit this line?** Stage-one confidence exists to make that call, and every signal tried fails there. Self-reported model certainty is worthless (flat across all levels; failed three times now, including on a local 8B).

Sharpened by last session: **the bigger half is words that *have* a menu but lack the slang sense** — `mal` 'ill' for *me tiene' mal*, `varear` 'horseback riding', `nota` 'note' where the line means *high*, `cabrón` as an adverbial intensifier. These are structurally unreachable: `step_6e`'s escalation is a closed-set `{"id": ...}` pick, and only menu-less words reach a proposer. Roughly 4% of ordinary speech has no correct answer in the menu; lyrics are worse.

Candidate signals: disagreement between the two independent methods; the shape of the whole score distribution rather than a top-two gap; a forced-choice probe; something new.

## Also open

- **Register reuse** — unwired. `apply_registers_to_menu` admits only `established` senses, so 81 playlist words with *provisional* register candidates are invisible to the inventor. That's how `rulay` got a fourth gloss minted next to three existing ones. Machinery all exists: `Artists/spanish/sense_registers/reggaeton.json`, `policy.json`, `tool_5d_build_shared_sense_registers.py`.
- **Duplicate senses** — 5,159 mergeable pairs at cosine ≥0.93; proposal at `Data/Spanish/layers/sense_merge_proposal.json`, deliberately unapplied. Deferred; register reuse reduces new ones at source.
- **High polysemy** (`dar` with 40+ leaves) — in scope, bad performance accepted, it's the destination not the first pass.
- **Confidence semantics** — bands are calibrated on `ok_tup` (lemma+POS), not on the gloss, and were measured near-meaningless on lyrics. A card saying "high · P(correct) 98.6%" claims less than it appears to.

## Dead ends — don't redo

Trained clitic classifier (a `se`-only regex captures 100% of the headroom). `used with` as a ranking feature or soft prior. Menu position. Deleting empty-translation leaves. Tuple-sum aggregation. Hubness offset (inverted function words). 8B generative WSD, Jina/Cohere rerankers, Spanish examples as sense vectors, pairwise yes/no prompting, WordNet as inventory.

Added last session: **English line in the escalation prompt** (+1.6pp on the 10% it touched — noise). **spaCy DET gate** (breaks proclitic pronouns `la ve`, `los miro`). **"Prefer the bare form" elision rule** (would break 24 correct plurals to fix 1). **Coarsening the inventory** (only 19% of errors are granularity; ceiling +3pp). **Automated LLM grading** (11.7% verdict flips, biased harsh).

## Known-wrong, low priority

`una`/`unos` — SpanishDict's `uno`/ADJ "one" carries context *"numeral or indefinite"*, claiming the article reading that belongs to `un`/DET "a". Two words, an inventory defect, no classifier fixes it. Same pile as `ma'`.

## Decisions come back to Josh

All of the work is yours — elision restoration, proper-noun mapping, curation, pipeline mechanisms, the escalation signal, error taxonomy. Josh is not a queue you hand tasks to.

What comes back to him is **decisions**: anything that changes a contract (sense identity, card identity, progress keys), anything that costs money, anything where two options have different failure modes and the evidence doesn't rank them, and anything you're about to assume rather than measure. Bring options with evidence and let him pick — don't dress a single recommendation as a conclusion. He corrected the course four times last session on card evidence alone and was right every time.

## Working with Josh

Long runs go in his terminal — print the command. Price model spend before spending it, and check `max_output_tokens` and thinking budget: a 40-token JSON reply left at 2000 with thinking on billed ~190 invisible tokens per call. Name pipeline steps canonically (`step_4a_filter_known_vocab` (word routing), not "step 4a"). `git pull --rebase` before pushing; never force-push.
