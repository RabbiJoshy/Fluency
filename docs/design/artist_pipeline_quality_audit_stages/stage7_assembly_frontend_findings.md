# Stage 7 — Assembly (7b/8b) + front-end join: findings
Audit of ranking, method priority, dedup, curated application, min-priority cut, and the
master→index→card join on the live SpanishDict Bad Bunny deck. Probes:
`probe_s7_main.py`, `probe_s7_flags.py` (this scratchpad). All counts from live files.

**Deck timeline that frames everything below:** live index/examples built **2026-05-02**
(`BadBunnyvocabulary.index.json.meta.json` generated_at=1777757873); master patched through
**Jul-14** (tool_8c sweeps); sense_assignments_lemma re-mapped **Jul-12**; ranking.json built
**Apr-26**. The live deck is a positional snapshot of a master that has since been edited in
place. Most findings below are consequences of that drift.

---

## F1. Master↔index positional contract broken on 765 live cards — 153 show WRONG-SENSE examples/frequencies  [CONFIRMED — top finding]

**WHAT:** `joinWithMaster` zips `master[id].senses[i]` with `index.sense_frequencies[i]` and
`examples[id].m[i]` purely by position (js/vocab.js:98-116, 516-521). In-place master edits
(tool_8c sense removals/additions) changed sense counts on 765 of 9,972 joined ids, so
frequencies and example buckets attach to the wrong senses.

**EVIDENCE (live cards):**
- `hay|haber` (cb0b96): master now has **1** sense ('to have to'), index has **3** freq slots
  [0.5, 0.3, 0.2]. The card shows **"hay → to have to"** with bucket-0 examples like
  *"ya hay vuelos disponibles" / "there are flights available"* — the there-is/are senses were
  removed from master; 5 examples in truncated buckets are lost.
- `como|comer` (74eb50, deck position 25): 4 senses vs 5 slots; card shows
  **"como → to have for lunch" f=1.0** with 10 examples that are all *"Como Romeo…"* = "like".
- `corta` (109eab, Josh-flagged): 4 senses vs 5 slots; truncated bucket 4 holds the one真
  ADJ example (*"mini falda corta"*); plus 3 near-identical 'gun, piece (PR slang)' senses.
- `todo|todos` (12d87b, position 28): 1 sense vs 3 slots — 'everyone' f=1.0 absorbs everything.
- Census: **765 joined ids** with `len(senses) != len(sense_frequencies)`; **153** have index
  LONGER than master (post-build sense removal ⇒ positional shift / example misattachment),
  **112** of those still carry freq>0 in truncated slots (examples silently dropped);
  **612** have master LONGER (senses appended post-build ⇒ unreachable: freq undefined →
  joinWithMaster drops them — this is also why tool_8c "fill blank sense" edits at positions
  ≥ len(freqs) can never surface, e.g. `da` 364d4a s10 'to apply, to put on').

**ROOT CAUSE:** tool_8c edits master in place assuming "no change to sense COUNT"
(pipeline/tool_8c_patch_master_curated.py:5-7 explicitly promises this), but some sweep
removed/blanked-and-dropped senses; nothing validates `len(master.senses) == len(index arrays)`
per id; js/vocab.js:98 `(m.senses || []).forEach((sense, i) => freqs[i]…` has no key-based
matching.

**PROPOSED FIX:** (a) immediate: a validation tool that diffs sense counts per live id and
lists misaligned cards (all 153 need an index rebuild or master restore); (b) structural:
store the master sense key `(pos, normalized translation, context)` — or a stable sense id —
in the index rows instead of relying on position, and match by key in joinWithMaster.
**IMPACT:** 765/9,972 joined cards, incl. deck positions 14/25/28 (para/como/todo) that Josh
sees in set 1. × **EFFORT:** S (validator) / M (keyed join + rebuild).

---

## F2. Flagged-card black hole: 20 of Josh's 72 flagged wordIds no longer produce any card

**WHAT:** The FlaggedWords workflow keys on wordId; master re-keys since May-2 orphaned or
deleted the ids, so the flagged cards vanished instead of being fixed — and Josh cannot
re-verify them in-app.

**EVIDENCE:** Fate census of all 72 flagged ids against live index+master:
- joins (card exists): 50 (31 unfixed + 19 sweep-fixed)
- **ORPHANED** (index row, no master → joinWithMaster drops): 9 — incl. `así` (f26a35 —
  master now has así|así under a8634e which is NOT in the index → **no card for "así" at
  all**), `bebé` (0eb26f), `señorita`, `sangre`, `nadar`-lemma, `papa`, `ojalá`.
- **gone from both**: 10 — `ha`, `vuelve`, `suena`, `mueve`, `da`, `sentirse`, `fumarse`…
  (pre-May-2 ids; deck rebuild re-keyed them).
- master only (no index row): 3 (`ve` f61755 — deck instead shows `ve|ir` 9d1497).
- Re-key trace: ha f71c2a→b08688, but b08688's ONLY sense is `pos=X, translation=''` →
  front-end blank-strip kills it → **the word "ha" (n=72) has no card at all**. vuelve
  c006bf→d83b44 (exists, see F9). da e708b→364d4a (exists, glosses now fine).

**ROOT CAUSE:** same in-place master churn as F1 + `assign_ids_from_master` re-keys on
word|lemma change (step_8b:93-119); no id-migration map is applied to the FlaggedWords sheet
or to the live index (index never rebuilt after tool_8c lemma edits — wave-1 stage2 F8's
1,226 orphans; 9 of Josh's flags sit inside that orphan set).
**PROPOSED FIX:** rebuild index+examples after master patching (one step_8b run), and emit an
id-migration map (old→new) that a small script applies to the FlaggedWords sheet.
**IMPACT:** 20/72 of the top quality signal is dark; several are top-frequency words
(así, bebé, ha). × **EFFORT:** S-M.

---

## F3. Ranking: stale, homograph-inflated order; the entire easiness system is a functional no-op

**WHAT:** Deck order Josh studies = `ranking.order` (step_7b, Apr-26) = raw
`word_inventory.corpus_count` desc with tiebreakers; homograph-survivor counts and chorus
inflation directly set positions. The per-example "easiness" scoring/sorting does nothing
to example order and stamps wrong per-example values.

**EVIDENCE:**
- Live index follows ranking.order (9,971/11,198 rows matched, 30 adjacent inversions).
  Positions: **para (n=1505, lemma parar) #14, como (n=754, comer) #25, todo (n=613, todos)
  #28, baby #29, fue|ir #101**. The current step_8b proportional split fixes corpus_count on
  a rebuild but NOT the order: step_7b reads raw inventory counts
  (step_7b_rerank.py:292 `inv.get("corpus_count")`) and step_8b applies ranking.order
  verbatim (step_8b:1568-1599) — so even a fresh rebuild keeps para at #14 unless 7b re-runs
  after (or is taught) the split.
- Easiness no-op chain: step_7b sorts each meaning's score list ascending **detached from
  example identity** (step_7b:359 `scores.sort()`); step_8b stamps them positionally onto
  examples then sorts by easiness (step_8b:1601-1616). Stamping ascending keys onto the
  current order and stable-sorting = order unchanged; the stamped value is NOT that
  sentence's score. Live proof: 26,588/26,588 examples carry `easiness` (6,373 = sentinel
  999999); **0 of 13,902 meaning buckets are non-ascending** — exactly the signature of the
  no-op. Displayed first-example = lowest ex_idx (raw corpus order), not "easiest".
- Misalignment on top: ranking.easiness arrays are per-WORD from `flatten_best_assignments`
  (single best method, word-level) while the builder builds meanings per lemma-group from
  per-example resolution — **332/6,143** words have meaning-count mismatch (e.g. hay 3 vs 1,
  ven 7 vs 5) so scores land on the wrong meanings even as a multiset.
- Cross-source reuse (design-doc concern) is real: the **_wikt deck (built Jul-12) reuses the
  Apr-26 spanishdict-derived ranking.json** — 18,983/18,983 wikt examples carry easiness
  stamped from spanishdict meaning arrays.
- Staleness: ranking Apr-26 predates the Jul-11/12 menu+assignment reruns AND the
  May-2 deck.

**ROOT CAUSE:** step_7b:337-365 computes easiness keyed by word/meaning-index with sorted
score lists; step_8b:1601-1616 pairs by position. **PROPOSED FIX:** kill the 7b easiness
layer; compute easiness at builder time per actual example (or key scores by ex_idx in the
layer); re-run 7b after homograph-split counts (or feed 7b split counts). **IMPACT:** every
card's example ORDER (the first lyric Josh sees) is unmanaged; deck order distorted at the
very top of set 1. × **EFFORT:** M.

---

## F4. Method priority resolution: works as specified, but flash-lite wins 98.8% of disputes and is wrong in ~⅓ of sampled ones; gap-fill/flash-lite ties break on dict order

**WHAT:** `resolve_best_per_example` (util_6a_assignment_format.py:165-226) correctly gives
each example to the highest-priority claim — no live case of a lower-priority method
beating a higher one, and no stale method labels exist (census: only 6 methods). The
quality risk is the table itself: keyword's disagreeing signal is discarded silently.

**EVIDENCE:** lemma file (Jul-12): flash-lite 6,540 words/20,172 examples; keyword 5,358 w;
biencoder 622 w; auto 470 w; gap-fill 358 w; pos-auto 41 w. 14,376 examples claimed by 2+
methods; **4,525 with disagreeing senses**; winner = spanishdict-flash-lite in 4,472
(98.8%), keyword 34 (beating only prio-0 auto), biencoder 16, pos-auto 3. In a 15-sample
audit, flash-lite's pick was wrong (keyword right) in ~5:
- `sigue|seguir` "el corazón **sigue** vacío" → FL "to follow" (keyword: "to still be" ✔)
- `probar` "no quieras **probar** de qué estamos hecho'" → FL "to try on [clothing]" ✖
- `otros` "**Otros** amores también hay" → FL PRON "another" (ADJ "other" ✔)
- `esa` "en **esa** misma pose" → FL PRON "that one" (ADJ ✔); `mucha` "**mucha** bellaca" same class
- `pongo` "**pongo** a perrear" → FL "to put" (keyword "to get [to become]" closer)
Pattern: determiner PRON-vs-ADJ and aspectual/copular verb senses.
Tie hazard: gap-fill and spanishdict-flash-lite are both prio 50; the winner is whichever
method key iterates first (`prio > existing[0]`, util_6a_assignment_format.py:217) — dict
insertion order, no explicit rule.

**ROOT CAUSE:** winner-take-all with no disagreement signal; METHOD_PRIORITY is global, not
POS-aware. **PROPOSED FIX (sketch):** stamp `disputed: true` on examples where a ≥10-prio
method disagreed (cheap; surfaces for review/eval), and break the 50/50 tie explicitly
(classifier > gap-fill). **IMPACT:** up to ~4.5k example placements (17% of instances) ride
on FL being right; sampled error rate suggests ~1.5k mis-bucketed examples. × **EFFORT:** S
(tie+flag) / L (arbitration).

## F4b. The `sense_methods` / `unassigned` trust channel is empty on the live deck

Live index: **zero** rows carry `sense_methods`, zero carry `unassigned` — because the deck
was built at min-priority 50 (per-example stamps in examples.json: flash-lite 20,143,
spanishdict-auto 1,262, gap-fill 1,108, pos-auto 99, none 3,976; no keyword/biencoder), and
step_8b only stamps meaning-level method when ALL contributors are keyword-tier
(step_8b:903-909). Consequence: every pill renders as "trusted" (solid border) —
js/CLAUDE.md's per-sense trust UI is inert; gap-fill glosses (invented senses) are visually
indistinguishable from menu-classified ones. Fix: stamp `sense_methods` for gap-fill/auto
too. Impact: UI honesty on ~2.5k examples' senses. Effort S.

---

## F5. --min-priority 50 cut: 360 lemma-keys lose ALL claims (684 examples); the *-auto exemption saves 471 words

**WHAT:** At the Spanish default (config/config.json:13 minPriority 50), any lemma-key whose
only claims are keyword/biencoder is emptied at build; its card degrades to the
X-fallback/blank path (step_8b:1137-1161) and usually vanishes client-side.

**EVIDENCE (current Jul-12 lemma file):** 6,898 keys have a ≥50 method; **471 keys survive
ONLY via the `*-auto` exemption** (util_6a_assignment_format.py:198-200 — without it, 470
spanishdict-auto single-sense words would go blank: the exemption is doing real work);
**360 keys have ONLY sub-50 claims** (354 keyword, 11 biencoder; 684 examples orphaned).
The list is mostly the junk the cut was designed for (`para|parar`, `para|parir`,
`como|comer`, `fue|ir`, `veces|vezar`, `to'|to`) **but includes real words that were
known-vocab-filtered away from Gemini** (`sé|saber`, `ya|ya`, `una|uno`, `mía|mío`) — on any
fresh rebuild these become blank X-cards (this is the SD-deck twin of brief bug #2 /
wave-1's 326 never-classified cards; the cut turns "classified by keyword only" into
"nothing at all"). Note the irony: the live deck's para|parar card exists only because the
LIVE build predates the current state; current assignments would blank it (fixing the
homograph card while blanking sé/ya/una).

**ROOT CAUSE:** cut is method-based, not confidence-based, and words routed away from Gemini
never got a ≥50 claim (step_4a routing + step_6c skips — stage-3's finding).
**PROPOSED FIX:** before cutting, gap-fill classify any word whose only claims are sub-50
(one Gemini batch over 360 words), or exempt single-analysis words like autos.
**IMPACT:** 360 words × their examples on the next rebuild. × **EFFORT:** S-M.

---

## F6. Curated overrides: whole-word-only gate confirmed (brief bug #5); tool_8c per-sense edits are the de-facto workaround; lemma re-keys break curated keys

**WHAT:** `curated_translations` can only replace the gloss of a card with exactly ONE
assignment; multi-sense cards cannot be corrected through curation, so sense-level fixes
migrated into tool_8c's hand-written positional master patches.

**EVIDENCE:**
- Gate: step_8b:835-837 and 1086-1088 `if curated_key in curated and len(word_assignments)
  == 1: translation = curated[…]`; unconditional only on single-sense-menu (1016-1017) and
  X-fallback (1138-1139) paths. Key is `word.lower()|word_lemma` — whole word, no sense
  addressing.
- Live examples of flags that curation could NOT express (all #sense:N flags):
  1. `ha` — "to have#sense:0; must#sense:1" (two senses of one card);
  2. `verdes` — "unripe#sense:2" (fix one of 3 senses, keep green/dollar);
  3. `dediqué` — "to dedicate#sense:0". None are addressable as `word|lemma → gloss`;
  all 60+ tool_8c OVERRIDES entries with `"senses": {N: {...}}` (millo s0, media s0, se s5,
  a s1, bate s0, tán s0-s8…) exist precisely because of this gap.
- Precedence (works as documented): artist file `data/llm_analysis/curated_translations.json`
  wins over `shared/curated_translations.json` filtered to modes ("shared","artist")
  (step_8b:501-514; load_shared_dict util_1a_artist_config.py:242-282).
- Rot: 22 curated keys match a live id but their gloss is absent from the card — both
  curated files are dated **Jul-12**, deck built **May-2** (18 are proper-noun labels hidden
  by the default propn filter anyway; real ones: `éramos|ser` "were (éramos = we were)" vs
  card 'to be'; `bicho` 'dick (vulgar, PR)' vs card 'dick'). 0 multi-sense-unapplied cases
  remain BECAUSE tool_8c already patched master directly.
- Curated keys are word|lemma → every tool_8c lemma re-key silently detaches the curated
  entry (same mechanism as F2).

**PROPOSED FIX (what sense-addressable curation needs):** curated schema v2 entries keyed
`word|lemma` + a sense selector that survives rebuilds — `(pos, context)` or the SD sense
id, NOT the array index — applied at master-update time in step_8b (formalizing tool_8c)
so both build and no-rebuild paths share one file; regression-check on rebuild per Josh's
curated-translations policy. **IMPACT:** unblocks the whole #sense:N flag class (≥14 of 72
flags). × **EFFORT:** M.

---

## F7. Translation judge (brief bug #8): wiring EXISTS in step_8b but BB never ran the judge — 0/26,588 live examples scored

**WHAT:** step_8b loads `layers/translation_scores.json` (step_8b:430-431), stamps
`translation_quality` per example (871-873) and sorts examples best-first (879-880) — but
the file exists only for Rosalía and Young Miko (`Artists/spanish/*/data/layers/`); Bad
Bunny has none, so the field appears on 0 of 26,588 live examples.

**EVIDENCE:** probe H: 0 live `translation_quality`; judge = `pipeline/artist/
tool_1b_judge_translations.py`. Young Miko distribution (3,055 lines): score 1:17, 2:121,
3:413, 4:649, 5:1855 → **4.5% ≤2, 18% ≤3**. Extrapolated to BB's 26,588 example instances:
~1,200 instances currently display translations a judge would call bad (≤2), with no
ordering or badge. Also: even with scores present, (a) they only REORDER, never hide/flag;
(b) the easiness stamp+sort (F3) runs after — today it happens to be order-preserving
(no-op), so the quality sort would survive by accident, a fragile invariant.
**PROPOSED FIX:** command for Josh (slow, Gemini):
`.venv/bin/python3 pipeline/artist/tool_1b_judge_translations.py --artist-dir
"Artists/spanish/Bad Bunny"` then rebuild; add a ≤2 gate or per-example badge in step_8b.
**IMPACT:** ~4-5% of every card's example translations. × **EFFORT:** S.

---

## F8. Front-end join final pass: silent drops, inert filters, and two primary-gloss quirks

**WHAT/EVIDENCE (mechanism map with live counts):**
- **Sense ordering / primary gloss:** joined meanings keep master order; card meanings are
  sorted by frequency desc (vocab.js:716-723) and `currentMeaningIndex=0` → the pill Josh
  sees first IS the highest-frequency sense. BUT `card.translation` and `stats.allWords`
  use the UNsorted `item.meanings[0]` (vocab.js:734, 779-784) — on **168 visible cards**
  the word-list/stats gloss differs from the card's primary pill (no→"no" vs "not",
  de→"from" vs "of", da→"to happen" vs "to give").
- **Zero-frequency sense filtering:** senses with `!freq` dropped at vocab.js:99 — that is
  the designed cross-artist filter, and (good news) **0 live senses** have freq==0 while
  holding examples (no rounding casualties). The 5% MIN_SENSE_FREQ filter (vocab.js:559)
  drops **0** pills; the 6-sense cap drops **65 pills on 30 cards** (function words: de, la,
  se…) — the cap keeps top-by-frequency, so it silently hides legitimate minor senses on
  exactly the words with the most senses.
- **Blank-gloss strip is uncounted:** vocab.js:327-328 filters blank-translation meanings
  and drops the card if none remain — **3,927 joined cards** (39%!) die here with no
  counter; the "✓ N cards (…excluded)" message never mentions them (counts only lemma dups
  + mastered).
- **hideSingleOccurrence** (default ON, artist mode): drops 1,791 cards (corpus_count ≤1).
- **excludeCognates** (default ON, threshold 0.85): ACTIVE on the live deck — despite no
  cognate_score in the index, joinWithMaster maps master `is_transparent_cognate` → score 1
  (vocab.js:166) and ui.js:1023-1025 sets cognateFieldAvailable from exactly that → **504
  cards hidden** (tool_8c COGNATE_STAMPS et al). Wave-1's rebuild timebomb (695 more via
  cognates.json scores) comes on top of this.
- **Lemma-mode collapsing** (default OFF): keeps only `most_frequent_lemma_instance`;
  `poolLemmaSiblingExamples` (vocab.js:194-234) pools sibling examples by translation-string
  match onto the host meaning **or falls back to host.meanings[0]** — with F1's misattached
  glosses, sibling examples of a different sense land on the host's first pill. Not
  quantified (lemma mode off by default).
- **mergeArtistVocabularies** (multi-artist): master-based merge concatenates examples
  positionally `i < existing.meanings.length` (vocab.js:1381-1387) — same positional
  assumption as F1, so cross-artist merges inherit the misalignment; frequency is
  recomputed from example counts (1451-1461), which REORDERS pills differently than
  single-artist mode.

**ROOT CAUSE:** join is positional + filters silent. **PROPOSED FIX:** count every drop
class into `counts` and show in the dev footer; align stats.allWords with the sorted
primary; make the 6-cap keep-all-with-examples. × **EFFORT:** S each.

---

## F9. Meaning dedup: 217 duplicate-gloss pill pairs remain; SD sub-sense granularity fragments frequencies (Josh's duplicate-sense flag class)

**WHAT:** Master unions senses on `(pos, normalize_translation, context)` (step_8b:1457-1481),
so same-gloss senses with different SD contexts, and near-identical glosses with any textual
difference, both survive as separate pills.

**EVIDENCE (visible cards, default settings):** **217** same-(pos, normalized-gloss)
pairs with differing context — a→"to"×3, qué→"what"×2, dice/están/puedo/tienen…; **2**
pairs identical even in context (corta 'gun, piece (PR slang)' ×3 — near-dupes that differ
only by a parenthetical never merge). Bad-split showcase = Josh's flagged `vuelve` (now
d83b44): senses to return / to come back / to go back, ALL context "to be back", frequency
fragmented 0.14/0.29/0.29. The vengan/recoge/compre/tabla flags were this class (sweep-fixed).
Mitigation already shipped: the card UI groups duplicates (GROUP_DUPLICATE_MEANINGS,
flashcards.js:1612-1935, translation-axis and context-axis group cards), so Josh sees ONE
group card — but frequencies stay fragmented (percentage per member), the 6-cap counts
members individually, and flags/curation must target individual members.
Bad MERGES (distinct senses collapsed by same gloss) — plausible, low-rate: requires two SD
senses sharing pos+gloss+context; the context key makes true collapses rare; none surfaced
in sampling. Not quantified further.

**ROOT CAUSE:** dedup is exact-key; no gloss-similarity merge at assemble time
(step_8a's parenthetical-context rendering handles display, not fragmentation).
**PROPOSED FIX:** at assemble, merge sense siblings whose normalized gloss OR (pos+context)
match with high token overlap, summing frequencies (keep first gloss); the UI grouping
already proves which axis to merge on. **IMPACT:** ~217 visible cards incl. top verbs.
× **EFFORT:** M.

---

## F10. End-to-end conservation table (default settings)

Card level (probe D, defaults: excludeNoise/Loanwords/ProperNouns/Cognates ON, threshold
0.85, hideSingleOccurrence ON, lemma mode OFF):

| stage | count | mechanism (file:line) |
|---|---|---|
| index rows | **11,198** | BadBunnyvocabulary.index.json |
| − orphaned (no master entry) | −1,226 | joinWithMaster `if (!m) continue` vocab.js:88 — silent |
| = joined entries | 9,972 | |
| − zero visible meanings (all senses freq0/blank gloss) | −3,927 | vocab.js:327-328 — silent, uncounted |
| − is_english | −6 | vocab.js:332 |
| − is_noise (excludeNoise) | −16 | vocab.js:338 |
| − is_english_loanword | −141 | vocab.js:345 |
| − proper noun (3 signals) | −145 | vocab.js:359-364 |
| − cognate ≥0.85 (via is_transparent_cognate→1) | −504 | vocab.js:166,367 |
| − single occurrence (count ≤1) | −1,791 | vocab.js:371 |
| = **visible cards** | **3,442** | (wave-1 "3,491 under Josh's settings" — Δ is toggle set) |

Sense level (on joined ids): 13,313 master senses → 12,130 freq>0 (1,183 are other-artist /
post-build appended senses, correctly hidden) → 3,947 blank-gloss (the 3,927 dead cards +
partials) → 5,455 pills on visible cards → −0 (<5% filter) −65 (6-cap, 30 cards) =
**5,390 pills shown**. No other leaks found: zero freq-0-with-examples senses, zero <5%
casualties; everything unaccounted in prior stages traces to the rows above.

---

## Flag walks (task 7 — five unfixed flags, master→index→card)

1. **ha (es0f71c2a)** → F2: id dead; word re-keyed to b08688 whose single sense is
   `X/""` → blank-strip kills card → **no "ha" card exists** (n=72). Flag unfixable in-app.
2. **así (es1f26a35, asir#lemma)** → F2/orphan: index row f26a35 has no master entry
   (dropped at vocab.js:88); re-keyed master a8634e not in index → **no "así" card**.
3. **conviene (es10f94a7)** → still wrong, live: card shows single pill VERB "to be
   advisable" f=1.0 (4 examples) but the lyric *"Tú sabes que te conviene"* = "it suits
   you / is in your interest" — sense s1 'to be in the interest of' has freq 0. Cause:
   flash-lite bucketed all 4 examples on one sub-sense (F4 class); whole-word curation
   can't fix the split (F6).
4. **des (es1b551c9)** → resolved-by-hiding: master des|des- (prefix junk from SD headword
   "des-") now `is_noise: true` → filtered (vocab.js:338). The underlying lemma fuzz (des =
   dar subjunctive in "cuando quiera' que me la des") remains untaught.
5. **verdes (es09f8490, unripe#sense:2)** → fixed by sense removal (now ADJ green 0.86 /
   NOUN dollar 0.14, card correct) — but it is one of F1's shrunken-master cards, i.e. the
   fix class that breaks positional alignment elsewhere.
   Bonus: **levanté** (es1c44ae6) still shows all 8 examples on "to get up [to awaken]"
   (s1 'to lift' freq0) — same F4 class as conviene; **pos** (es1fb6b49) now correct
   ("por (clipped: po')") via master patch; **pasándola** (es1bf72ba) fixed (pasar idiom).

Flag-class attribution across the 72: ≈20 dead ids (F2), ≈14 #sense:N sense-level fixes
(F6), ≈10 lemma fuzz (stage-6), ≈8 loanword/noise hides (routing), remainder gloss quality
(sweep-fixed).

---

## Command-for-Josh list (not run — >30s or writes)
- Rebuild live deck to clear F1/F2 orphans+misalignment (after deciding on F5's 360 words):
  `.venv/bin/python3 pipeline/artist/step_8b_assemble_artist_vocabulary.py --artist-dir "Artists/spanish/Bad Bunny"`
  (then re-run tool_8c per its header, and re-apply — noting F1 — only count-preserving edits).
- Judge BB translations (F7): `.venv/bin/python3 pipeline/artist/tool_1b_judge_translations.py --artist-dir "Artists/spanish/Bad Bunny"`
- Re-rank after split-aware counts (F3): re-run step_7b then 8b (7b before 8b).
