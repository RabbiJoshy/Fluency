# WSD changes made AFTER the Fluency-Next migration snapshot

**Read this if you are porting, mirroring or reconciling the WSD stack into
`~/PycharmProjects/Fluency-Next`.**

A parallel effort is migrating this repo to a new format in `Fluency-Next`. The
WSD algorithm changed in `Fluency` on 2026-08-22, possibly after that migration
took its snapshot. Anything listed here is a POST-SNAPSHOT change and will not
be present in a copy taken before it. Nothing here is a refactor — every item
changes what meaning a card prints.

Whether these landed before or after any given migration snapshot is decided by
one thing only: whether the six commits below are in that repo's history. Check,
do not assume.

## The exact boundary

    78506bf6  WSD v5: the dictionary orders senses by frequency, and nothing was listening
    22a5531b  docs/handover: the brief for the next WSD pass
    745fc3c9  speech deck: rebuild with the aligner genuinely excluded
    3023029f  docs/handover: the two operational traps that cost time today
    ac72dfe9  docs/handover: correct the parsimony framing, and state the cost model
    a445213c  speech deck: publish v5 to the app, and record it in the dev changelog

Everything before `9303ce72` is pre-change. Commits `23f1ad43`, `38cdb3e6`,
`b3578d2d`, `6f85b7a4` are concurrent Codex work on a different subject (audit
events / provenance) and are NOT part of this.

## What actually changed, and what a port must carry

Behavioural, must be ported for the deck to reproduce:

| file | change |
|---|---|
| `pipeline/step_6e_assign_senses_calibrated.py` | v3 -> v5. Adds `--menu-prior` (default 0.02) and `--menu-prior-decay` (0.5), and `--pos-filter` (default on). METHOD/PROMPT_ID now `spanishdict-beto-cal-v5` / `sd-beto-cal-v5` / `sd-beto-cal-esc-v5`. Leaf repair now scores with the priored matrix. |
| `pipeline/util_6a_pos_menu_filter.py` | NEW `sense_compatible_bridged()`. `sense_compatible_with_example_pos()` is unchanged, and step_6b/6c/8b still call it — do not "unify" them without re-measuring. |
| `pipeline/util_6a_method_priority.py` | registers `spanishdict-beto-cal-v5` (89) and `spanishdict-beto-cal-align-v5` (90). REQUIRED — an unregistered method scores 0 against Spanish's minPriority 50 and the builder writes a deck with no examples, exit code 0, no error. |
| `pipeline/step_6f_align_english_leaf.py` | rebased onto v5 ids. Built but NOT in the shipped policy. |
| `config/prompt_registry.json` | new prompts `sd-beto-cal-v5`, `sd-beto-cal-esc-v5`, `sd-beto-cal-align-v5`; new policies `speech-beto-cal-v5-pinned` and `speech-beto-cal-v5-noalign`. The shipped speech deck uses **noalign**. |

Non-behavioural: `docs/reference/wsd_algorithm.md` and `wsd_dead_ends.md` were
CORRECTED — two entries previously recorded as dead ends are wrong, and the
files carry a warning at the top explaining why. A migration that ports the old
docs will re-import the wrong conclusions.

Regenerable, do not hand-port: everything under `Data/Spanish/layers/` and the
`vocabulary.*` outputs. Re-run the pipeline instead.

App-side, migration-irrelevant: `config/offline-content-manifest.json`
(`language-spanish` contentVersion -> `2026-08-22-beto-cal-v5`) and
`config/dev_changelog.json`.

## How to reproduce the deck from a clean port

    tool_6a_tag_example_pos.py                      # needs es_dep_news_trf
    step_6e_assign_senses_calibrated.py             # defaults are the measured config
    step_7a_map_senses_to_lemmas.py --language spanish
    step_8a_assemble_vocabulary.py --prompt-policy speech-beto-cal-v5-noalign --drop-unrenderable

## Keep this file current

Any later WSD change must be added here with its commit hash and whether it is
behavioural, or the migration cannot tell what it is missing. If a change is
made in `Fluency-Next` instead of here, say so explicitly — the two repos will
otherwise silently diverge on the one thing that decides what every card says.
