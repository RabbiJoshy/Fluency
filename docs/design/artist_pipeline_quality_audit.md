---
title: Artist Pipeline — Full Quality Audit (SpanishDict / Bad Bunny live deck)
status: research
language: spanish
created: 2026-07-21
updated: 2026-07-21
---

# Artist Pipeline — Full Quality Audit (SpanishDict / Bad Bunny live deck)

- **Status:** research (investigation only — nothing implemented)
- **Date:** 2026-07-21
- **Scope:** the PRODUCTION Spanish artist pipeline end-to-end — raw lyrics (step 1) →
  rendered flashcard — for the live SpanishDict-based Bad Bunny deck.
- **Method:** 7 sub-agents, one per stage, sampling REAL BB data against the live
  `BadBunnyvocabulary.index.json` (built **2026-05-02**), `vocabulary_master.json`
  (patched through **Jul-14**), and the layer/menu/assignment files. Full per-stage
  evidence is archived alongside this doc in
  [`artist_pipeline_quality_audit_stages/`](artist_pipeline_quality_audit_stages)
  (`stage{1..7}_*_findings.md`, probe-script names cited inline); this doc is the
  synthesis + the single prioritized proposal list. A small Gemini eval (~$0.01) was run
  for stage 5.
- **Baseline:** 537 songs scraped → 302 kept → 11,198 index rows / 26,588 example
  instances → 9,972 join master → **3,442–3,491 visible cards** under default/Josh
  settings.

---

## 0. The meta-finding: the live deck is a frozen snapshot of a moving master

One fact frames ~60% of the worst user-visible defects. The pieces of the deck were
built at different times and never reconciled:

| artifact | built | |
|---|---|---|
| `ranking.json` (deck order + easiness) | **Apr-26** | |
| `sense_assignments/*` (Gemini classification) | **Apr** (never re-audited) | |
| `BadBunnyvocabulary.index.json` + `.examples.json` (the live deck) | **May-2** | |
| `sense_assignments_lemma/*` (7a re-map) | **Jul-12** | |
| `vocabulary_master.json` (tool_8c hand-patches) | **Jul-14** | |

`joinWithMaster` (`js/vocab.js:88-116`) zips the May-2 index against the Jul-14 master
**by array position**. Every in-place master edit since May-2 therefore either orphans a
card (id no longer in the index) or misaligns its senses against the index's frequency/
example arrays. The following top defects are all consequences — and all are **already
fixed in current code or data, just not in the live index**:

- Homograph "survivor" cards (`para|parar` n=1505, `como|comer` n=754, `todo|todos` n=613)
  — current `step_8b` splits corpus_count proportionally; the May-2 build predates it.
  (stage 6 F2)
- 765 cards with `len(senses) ≠ len(sense_frequencies)`; 153 show wrong-sense examples.
  (stage 7 F1)
- 1,226 index rows (11%) orphaned → **no card at all** for `las` (862), `dime` (300),
  `otra`, `calle`, `así`, `bebé`. (stage 2 F8 / stage 3 F11 / stage 7 F10)
- 20 of Josh's 72 flagged wordIds no longer produce any card (dead re-keyed ids). (stage 7 F2)
- The stale April Gemini run: today's identical prompt+menus score **16-17/20** on the
  error class the live deck gets **0/20**. (stage 5 F1)

**Therefore the single highest-leverage action is the gated rebuild** (`step_8b`, then
re-run `tool_8c` count-preserving edits). It is currently NO-GO not because it's wrong but
because it would *also introduce new damage* (the cognate timebomb + blank never-classified
cards below). The top of the proposal list is the set of fixes that convert the rebuild
from NO-GO to GO. Everything the rebuild can't fix (front-end example selection, menu
scrape quality, classifier run conditions) is ranked after.

---

## Stage 1 — Lyric + translation acquisition (steps 1a/1b)

Better shape than expected: the step-2a cleaner catches nearly all Genius boilerplate, and
**Genius community-translation alignment is trustworthy — 30/30 random pairs correct**
(stage 1 F7). Live example translation sources: gemini 61.6% / genius 37.1% / blank 1.3%.
The problems are specific leaks, not systemic:

- **F1 — Genius editorial descriptions leak as lyrics → 9 fake cards + ~31 polluted
  examples.** The "Read More" strip regex (`step_2a_count_words.py:173`) requires a newline
  that these pages don't have, so annotation prose becomes "lyrics." Fake cards: `rlndt`,
  `rolandito`, `rolando`, `jusino`, `salas` (lemma "sala"!), `metáfora`, `alude`,
  `rumoreó`. One live example sentence is literally a Genius footnote about a 1999 news
  story. **[S]**
- **F3 — 348 live examples (1.3%) have empty English** — lines absent from
  `example_translations.json`, concentrated in Prayer / La Parabi / Ahora Soy Peor. **[S]**
- **F4 — 32.7% of live example instances are not Bad Bunny's voice** (guest verses on
  remixes: Arcángel 460 lines, J Balvin 398, Cazzu/Khea rioplatense…). Section-tag
  attribution *exists in the batch data and is thrown away* (`step_2a:211-212`). Mostly
  invisible per-card but it dilutes the whole deck's claim to be "Bad Bunny's Spanish" and
  mixes dialect/register. **[M]**
- **F2 — one real song ("No Prometo Nada") dropped** by a whole-text "letra completa"
  placeholder substring test. **[S]**
- **F5 — 318 examples carry invisible Genius anti-scrape Unicode** (U+2005/205F/200A);
  cosmetic but a latent exact-match hazard. **[S]**
- Side note: the **Genius API token is hardcoded and committed** in `step_1a` / `step_1b`
  (a `.env` loader already exists). Hygiene.

---

## Stage 2 — Tokenization, elisions, ad-lib stripping (steps 2a/3a)

- **F1 — Leading-apostrophe beheading (the worst wrong-word class found).** `WORD_RE`
  (`step_2a:72`) allows internal/trailing but not *leading* apostrophes, so Caribbean
  aphesis loses its marker: `'tamos→tamos`, `'taba→taba`, `'e→e`. Live result: **`tamos`
  and `tamo` are taught as the noun "fluff/chaff", `taba` as "jacks/ankle bone", and the
  `e`="and" card (n=234, high rank) is ~92% actually `'e`=de.** None of these were in
  FlaggedWords — new finds. **[S–M, needs rebuild]**
- **F2 — Auto-generated `elision_mapping.json` has junk canonical targets** that hard-code
  wrong merges: `tamo'→"tamos"` lemma **"tir"**, `feli'→"felis"` (the cat genus), `na`
  lemma **"nir"**, `to's` kept as its own visible card. ~971 auto entries never audited. **[M]**
- **F5 — Ad-lib/fragment debris in visible first examples:** 37 visible cards lead with a
  ≥50%-ad-lib line (`bla` glossed NOUN "b" with example *"Bla, bla, bla…"*; `mamacita` →
  *"Mamacita (Rra, rra)"*); 66 lead with a ≤3-token line. **[S–M]**
- **F6 — MWE:** curated layer is sound; PMI layer is chorus-echo noise. One cheap win:
  curate `de una`, `a fuego`, `al garete`, `de cora` (all-function-word idioms the PMI path
  structurally can't find). Empty-string pattern chips (`que yo [PRON]: ""`) reach the
  index. **[S]**
- **F4 / F7 — smaller leaks:** bare `pa` taught as NOUN, `pal`; French `une`→"to unite"
  card (lingua is ES-vs-EN only). **[S]**
- **Doc correction:** `Artists/CLAUDE.md:154` says `multi_word_elisions.json` is "not yet
  wired into step 2a" — **stale; it IS wired and applied** (verified `pa'l → para + el`).

---

## Stage 3 — Word routing (step 4a)

Architectural fact established by code trace: **routing exclusions do not remove words from
the deck.** `step_8b` converts only 3 of 5 exclude buckets into hide-flags
(`:520-537`: english, proper_nouns, noise). `exclude.cognate` and `exclude.low_frequency`
get **no flag and no exclusion** — a direct violation of the filter-design principle
("filters determine METHOD, not deck inclusion").

- **F1 — `exclude.cognate` is a ghost bucket:** 71/79 curated cognates are fully visible
  cards with Gemini-invented gap-fill glosses — incl. `baby` (cc 613, the deck's #1
  non-word). Five of Josh's flags (whatsapp, haters, light, okay, shot) are exactly this —
  the curation he'd expect to fix them has **zero live effect**. **[S]**
- **F2 — cognate_score timebomb quantified (rebuild BLOCKER):** 0 live cards carry
  `cognate_score` today, but a fresh `step_8b` stamps the `cognates.json` layer and, with
  default `excludeCognates:true` @ 0.85, **695 currently-visible cards vanish** — led by
  `estar`'s entire paradigm (`estar|estar` is scored 1.0 — junk; estar≠star), plus mucho,
  hombre, grande, primero. **[M]**
- **F3 — never-classified cards quantified (known bug #2):** 326 of 3,951 default-view cards
  (8.3%) have no classifier assignment (297 gap-fill-only + 29 blank X-cards). Worst: baby
  (613), dos (133), flow (121). The `a`→"bishop" class. **[M]**
- **F4 — `exclude.low_frequency` is also a ghost bucket:** 839 freq-1 words became blank
  X-cards guarded only by the `hideSingleOccurrence` UI toggle. **[S]**
- **F5/F7/F6 — over-broad skips kill real Spanish:** `english_loanwords.json` (applied in
  6c *after* routing) blocks 138 classifier-routed words incl. naturalized `gasolina, gol,
  ron, líder, estrés, dembow, bichote`; `noise.json` drops `ya` (n=722 — **no master entry
  at all**), `he`, `ha`; `is_propernoun_corpus` hides `dios` (140), `conejo` (40),
  `paciencia` — even words on the proper_nouns keep-list. **[S each]**
- **F7/F8 — clitic_merge & derivation_map:** ~15 of 91 clitic bases wrong/unstable
  (`siénteme→sentar` should be sentir; `delete→dele`); derivation sends name diminutives
  (`rolandito→rolando`) into cards and misses `-aíta/-aíto` (→ the toítas class). **[S–M]**

---

## Stage 4 — SD menu quality + example selection (steps 5a/5c)

**Menu quality (Part A).** Coverage by band: **head 92% / mid 82% / slang-tail 62%**; when
a menu exists it has senses (0 empty). SD wins on presence + learner-grade glosses at the
head; **Wiktionary is the rescue source** for 134 tail words where SD is missing-or-wrong
(baby, flow, mambo, bichote…). But SD's tail presence is salted with fuzzy-match damage:

- **F1 — 26 menus fuzzy-resolved to ENGLISH headwords (perse→purse class), 23 live:**
  `revol→revolt`, `lary→lazy`, `yales→Yale`, `tranquilita→tranquility`, `clarito→clarity`.
  Root cause is two-layer: SD's fuzzy matcher returns EN headwords for unknown slang, AND
  legacy cache entries with `entry_lang:None` predate the `?langFrom=es` fix and were never
  re-scraped. **[S guard + M re-scrape]**
- **F2 — ~40 reverse-direction (Spanish) glosses** on live cards (`hey`→*hola*;
  `poses`→9 Spanish senses via EN "pose"). **[S]**
- **F3 — wrong-Spanish-headword fuzz** (`totito→torito` "little bull"; `veces` lists
  `vezar` "to accustom" before `vez`). **[M]**
- **F5 — SD `regions` labels are captured then dropped:** 7,216 menu senses (10%) carry a
  region (Caribbean, Mexico, Spain…); **0 reach the live master.** Directly relevant to the
  eswiktionary dialect plan — `perico`="cortado" is a Spain sense sitting on a PR deck. **[S]**

**Example selection (Part B).** The pipeline's example-ordering stages are almost entirely
inert; the first line Josh sees is decided by a front-end sort:

- **F7/F8 — pipeline sorts are no-ops:** `translation_scores.json` doesn't exist for BB, so
  the quality sort defaults to a stable no-op; the step_7b easiness sort is
  mathematically broken (see stage 7 F3).
- **F9 — the front-end selector is a longest-line contest.** `sortExamplesByRelevance`
  ranks by `deckHits` (count of tokens that are any deck word) before easiness; with ~3.5k
  visible cards nearly every token is a deck word, so **deckHits ≈ sentence length**.
  Simulation over 2,026 multi-example meanings: **the single LONGEST line is picked 80% of
  the time.** `nunca` leads with a 71-token spoken monologue. This exact failure mode is
  documented in the repo's own `example_selection_design.md` and was fixed for normal mode
  only. **[S — pure JS]**
- **F10 — 81 meanings lead with a blank-English line** while a translated alternative
  exists. **[S]**
- **F11 — 30-card audit:** 9/30 first examples are not the best available line (5
  selector-caused, 4 classification-caused). Chorus-duplication is **not** a real problem
  (0.8% after dedupe) — don't spend effort there.

---

## Stage 5 — Gemini classification + gap-fill (step 6c) + eval

Both prompts are unchanged since April. Key prompt facts: bilingual context is *already*
present (so the "add English" variant is moot); there is no dialect/register hint; sense
lines carry no headword; invalid/failed parses **silently coerce to sense 0** (first-menu-
sense bias is the built-in error mode). A 30-item gold eval (20 error-class + 10 controls)
was run against the current prompt and variants:

| Variant | error-class (20) | controls (10) |
|---|---|---|
| **LIVE deck (April run)** | **0** | 10 |
| V0 current prompt, 1 ex/word | **17** | 10 |
| V1 + PR-dialect/register hint | 14 | 10 |
| V2 + headword labels | 15 | 10 |
| V3 all examples/word | 16 | 8 |
| V4 50-word production batch | 16 | 7 |

- **F1 — The dominant error source is the stale April run itself, not the prompt.**
  Identical prompt+menus today get 16-17/20 right where the live deck gets 0/20.
  Re-running is the largest single lever (~1,100 words). **[S re-run + curation-protection]**
- **F3 — Prompt changes do NOT help (negative result): the dialect hint made it WORSE
  (14/20)** — it pushed the model into slang over-reach. Headword labels neutral. *Do not
  spend effort on prompt wording.* The gusta/palomo class is a menu problem, not a prompt
  problem.
- **F2 — Batch load degrades accuracy:** controls 10/10 → 8/10 → 7/10 as batch grows from
  30→50 words. `BATCH_SIZE=50` is too big; drop to 10, and add a "NONE of these fits"
  escape so slang stops being force-binned to sense 0. **[S]**
- **F4/F5 — Menu faults are the second source (~8%) and gap-fill can't rescue them**
  (it fires only on zero-sense words): `palomo`→"male pigeon" (real: PR "sucker"),
  `millo`→"corn" (real: "millionaire"), `corta`, `mueve`→"move! (PHRASE)" for a declarative
  line. Blank-gloss + PHRASE menu senses are attractive low-content bins. **[S–M]**
- **F6 — 240/358 (67%) of live gap-fill glosses are definitional junk** by step_6c's own
  current `_is_definitional` detector (the live run predates it): `haters` → "People who
  intensely dislike or resent someone…". A re-prompt is ~36 batches ≈ cents. **[S]**
- **F9 — orphan bug #3 status:** live BB data currently CLEAN (0 orphans; the `.bak` shows
  202 were once repaired). The brief's "gemini branch omits --sense-menu-file" is **FIXED
  for spanishdict** — but there is still no `wiktionary` elif in the gemini branch, so a
  `--sense-source wiktionary --classifier gemini` run can recur the Young-Miko 60% orphaning.
  Also: `--sense-menu-file` without `--method-name` silently stamps `spanishdict-flash-lite`
  and any unknown method name falls to priority 0. **[S — harden before any wikt gemini run]**

---

## Stage 6 — Lemmatization (step 7a)

- **F0 — Step 7a does not lemmatize.** The lemma is the SpanishDict *headword string
  captured at scrape time*, with **no plausibility guard** (only an abbreviation-dot check).
  `derivation_map` and `homograph_overrides.json` are computed but **never consulted in
  artist mode**. spaCy/spanish_forms play no role in choosing the lemma. This is the root of
  every wrong-lemma class below.
- **F2 — Homograph survivor cards = the single most visible lemma problem.** The live index
  carries ONLY the minor-verb analysis stamped with the full surface count: `para|parar`
  "to stop" n=1505, `como|comer` "to eat" n=754 (*"Como Romeo…"*), `todo|todos` "everyone"
  n=613, `cara|caro` "expensive" (*"Tu cara…"*), `fue/fui/fuiste|ser` (should be *ir*). The
  correct card exists in master and the correct assignments exist in
  `sense_assignments_lemma/` — **the live index just predates the code that uses them.**
  Fixed by the rebuild. **[M — rebuild]**
- **F1 — the flagged trio (perse/pasándola/toítas) is confirmed fixed** by the Jul-14 sweep
  (patched in place, not rebuilt).
- **F3 — perse-class fuzz still has live victims:** `totito→torito` "little bull" (n=24),
  `cel→cal` (n=17, cell phone), `revol→revolt`, `dembow→dembo`, plus punctuated lemmas
  `dale|¡Dale!` (n=122), `diablo|¡Diablos!` (n=58). Bounded: ~15-25 live cards. **[S for a
  tool_8c batch; M for the scrape guard + derivation_map wiring]**
- **F4 — fue/fui/fuiste → ser** via SD's tie-break where BB usage is mostly *ir* ("se fue"
  = went/left); 244 corpus occurrences glossed "to be". **[S–M]**
- **F5 — lemma-mode collapse amplifies wrong lemmas:** since be97b15 the app pools sibling
  examples under the `most_frequent_lemma_instance` card, so `para|parar` "to stop" becomes
  the sole `parar` card and absorbs all the preposition lines. Auto-fixed by F2's rebuild.

---

## Stage 7 — Assembly (7b/8b) + front-end join

- **F1 — the positional master↔index contract is broken on 765 cards** (see §0); 153 show
  wrong-sense examples/frequencies, 112 silently drop examples in truncated buckets.
  Structural fix: store a stable sense key `(pos, normalized translation, context)` in the
  index and match by key, not position. **[S validator / M keyed join + rebuild]**
- **F2 — 20 of 72 flagged wordIds produce no card** (9 orphaned, 10 gone from both, e.g.
  `ha` re-keyed to a blank-X sense → no "ha" card at all despite n=72). The top quality
  signal is going dark. Needs an id-migration map (old→new) applied to the FlaggedWords
  sheet after rebuild. **[S–M]**
- **F3 — the entire easiness system is a functional no-op.** step_7b sorts each meaning's
  score list ascending *detached from example identity* (`step_7b:359 scores.sort()`);
  step_8b re-attaches positionally. Result: 100% of shipped per-example easiness is
  fabricated (0/13,902 buckets non-ascending — the no-op signature), and 32% are all-
  sentinel from meaning-count misalignment. Deck ORDER is also stale (para at #14, como #25).
  The `_wikt` deck reuses this same Apr-26 ranking. **[M]**
- **F4 — method priority works as specified**, but flash-lite wins 98.8% of disputes and is
  wrong in ~⅓ of sampled ones (determiner PRON-vs-ADJ, aspectual verbs); the gap-fill /
  flash-lite 50/50 tie breaks on dict order. Stamp `disputed:true` + explicit tie-break. **[S]**
- **F4b — the per-sense trust UI is inert:** 0 live rows carry `sense_methods`, so every
  pill renders "trusted" — invented gap-fill glosses are visually indistinguishable from
  menu-classified ones. **[S]**
- **F5 — the --min-priority 50 cut blanks 360 lemma-keys on rebuild** (only sub-50 claims),
  incl. real words routed away from Gemini (`sé|saber`, `ya|ya`, `una|uno`, `mía|mío`). This
  is the SD-deck twin of the never-classified bug and a **rebuild BLOCKER**. **[S–M]**
- **F6 — curated overrides are whole-word-only** (brief bug #5 confirmed): multi-sense cards
  can't be fixed via curation, which is why ≥14 `#sense:N` flags migrated into hand-written
  `tool_8c` positional master patches. Needs sense-addressable curation keyed on
  `(pos, context)` not array index. **[M]**
- **F7 — translation judge never ran for BB** (0/26,588 scored); extrapolating Young Miko's
  distribution, ~1,200 instances show translations a judge would call bad. **[S + Gemini]**
- **F8 — silent drops in the join:** 3,927 joined cards (39%!) die at the blank-gloss strip
  with no counter; `stats.allWords` uses the *unsorted* primary gloss so 168 cards show a
  different word-list gloss than their card. **[S each]**
- **F9 — 217 duplicate-gloss pill pairs remain** (SD sub-sense granularity fragments
  frequencies — Josh's `vuelve` flag: to return / to come back / to go back all context
  "to be back"). The card UI groups them, but frequencies stay fragmented. **[M]**
- **F10 — end-to-end conservation table** (defaults): 11,198 index − 1,226 orphaned − 3,927
  blank-gloss − 6 english − 16 noise − 141 loanword − 145 propn − 504 cognate − 1,791
  single-occurrence = **3,442 visible cards**. All leaks accounted for.

---

## Prioritized proposals (impact × effort)

One list, ranked. Themes tagged: **[EX]** examples · **[SENSE]** sense assignment ·
**[LEM]** lemmatization · **[REBUILD]** rebuild-enablement · **[HYG]** hygiene/future-artist.
Nothing here is implemented — each needs Josh's explicit go, and pipeline steps >30s are
printed as commands, not run.

### Tier 0 — De-risk and execute the rebuild (unlocks the largest impact block)

The rebuild alone fixes: homograph survivors (para/como/todo/cara/fue), the 765 misaligned
cards, the 1,226 orphans, count inflation, the stale April classification, and frequency
fragmentation. It's NO-GO only because of P2+P3. Do those first, then rebuild.

| # | Proposal | Theme | Impact | Effort |
|---|---|---|---|---|
| **P1** | **Re-run Gemini classification** `step_6a --classifier gemini --force --no-gap-fill` on BB (protect tool_8c curations first; verify merge order). Fixes the stale-April error class. | SENSE | **Very high** (~1,100 words; live 0/20→~16/20) | S* |
| **P2** | **Fix the cognate_score timebomb before rebuild** (stage 3 F2): blocklist/cap `cognates.json` scores for the top-N frequency band + copulas (estar); add a build-time "would-hide diff" report. | REBUILD | **Very high** (prevents 695 cards incl. all of *estar* vanishing) | M |
| **P3** | **Prevent never-classified blanking** (stage 7 F5 / stage 3 F3): gap-fill classify the 360 sub-50-only keys (one Gemini batch) before the min-priority cut, OR exempt single-analysis words. | REBUILD/SENSE | **Very high** (saves sé/ya/una/mía + 326-card class) | S–M |
| **P4** | **Stamp all 5 exclude buckets in step_8b** (stage 3 F1/F4): flag `exclude.cognate` (`is_transparent_cognate`) and `exclude.low_frequency`; add an assemble-time sweep dropping stale assignments for words now in exclude.*. | REBUILD | High (kills the `baby` #1-junk-card class + 839 blank low-freq) | S |
| **P5** | **Rebuild** `step_8b`, then re-apply only count-preserving tool_8c edits; **emit an id-migration map** (old→new) and apply it to the FlaggedWords sheet (stage 7 F1/F2). | REBUILD | **Very high** (clears §0 entirely; revives 20 dark flags) | S–M |

\* P1 effort is S for the re-run itself; M if curation-protection needs work. Est. spend
~$1-2 flash-lite.

### Tier 1 — Front-end wins (no rebuild, testable immediately, high visibility)

| # | Proposal | Theme | Impact | Effort |
|---|---|---|---|---|
| **P6** | **Rewrite the example selector** (`sortExamplesByRelevance`, stage 4 F9/F10): cap `deckHits` at 2-3, add a 6-14-token length window, demote blank-English lines last. Pure JS. | EX | **High** (re-picks first line on ~1,600 longest-line + 81 blank-EN meanings) | S |
| **P7** | **Re-gap-fill the 240 definitional glosses** (stage 5 F6): re-prompt through `_repair_proposed_sense`, validate POS against the canonical set, drop PROPN proposals. ~cents. | SENSE | High (haters/baby/flow-class flagged cards) | S |
| **P8** | **Fix the detached easiness sort** (stage 7 F3 / stage 4 F8): key easiness by raw `ex_idx` instead of positional per-meaning lists; prerequisite for any real example ordering. | EX | Medium (unblocks P6's easiness signal; fixes _wikt reuse) | S |

### Tier 2 — Sense-assignment & menu quality (fold into the P1 re-run / next build)

| # | Proposal | Theme | Impact | Effort |
|---|---|---|---|---|
| **P9** | **Menu plausibility guard** (stage 4 F1/F3, stage 6 F3): in `build_menu_analyses`, reject a surface's headword when it's an EN-dict word not in `spanish_forms`, or shares no prefix/inflection with the surface; quarantine to sense_discovery. Kills perse/totito/revol class. | LEM/SENSE | High (dozens of tail cards; every future artist) | M |
| **P10** | **BATCH_SIZE 50→10 + a "NONE fits" escape** (stage 5 F2/F4); route NONE-majority words into gap-fill *with their menu* (the dead `gap_fill_gemini` prompt was built for this). The only path for palomo/millo/corta slang. | SENSE | High (~480 slang words — the point of an artist deck) | S + M |
| **P11** | **Prune blank-translation & PHRASE senses from the classifier menu** (stage 5 F5): mueve/vamos/dale PHRASE traps + 1,958 blank-gloss bins. | SENSE | Medium-high (high-freq imperative-looking forms) | S–M |
| **P12** | **Refine the loanword skip** (stage 5 F7 / stage 3 F5): only skip loanwords with NO SD menu; add the per-artist keep-list; clean the 93 grandfathered ones. Recovers gasolina/gol/ron/dembow/bichote. | SENSE | Medium (138 words incl. flags) | S |
| **P13** | **Re-scrape `entry_lang:None` surface-cache entries** used by BB (`tool_5c_build_spanishdict_cache --force`), then rebuild menus. Removes the legacy backwards/fuzzy scrapes P9 can only guard against. | LEM/SENSE | Medium | M (network) |
| **P14** | **Honor `derivation_map` + a fue/fui/fuiste→ir prior** at menu-build/7a (stage 6 F3/F4): 244 "to be" occurrences + name-diminutive routing. | LEM | Medium | S–M |

### Tier 3 — Corpus hygiene (mostly one-line, compounding for artist #4)

| # | Proposal | Theme | Impact | Effort |
|---|---|---|---|---|
| **P15** | **Fix the Genius editorial-leak regex** (stage 1 F1): drop the newline requirement, treat `[Letra…]`/first section tag as lyrics start; prune the 9 junk master entries. | HYG | Medium (9 fake cards, visible when hit) | S |
| **P16** | **Capture leading apostrophes in `WORD_RE`** + add elided mappings (stage 2 F1): fixes tamos/taba/e wrong-word cards. Needs the rebuild (coordinate with P2). | LEM/HYG | Medium (4 visible wrong cards, high-freq `e`) | S–M |
| **P17** | **Gap-fill the 348 blank-English examples** (stage 1 F3) + **run the translation judge** for BB (stage 7 F7) — one Gemini batch each; materializes `translation_scores.json` for the step_8b hook. | EX | Medium (~350 untranslated + ~1,200 low-quality) | S |
| **P18** | **Curate the missing MWEs** `de una`, `a fuego`, `al garete`, `de cora` (stage 2 F6); drop empty pattern chips. | EX | Low-medium (cheapest quality win) | S |
| **P19** | **Ad-lib/fragment first-example filter** at assemble time (stage 2 F5), per Josh's preserve-examples rule (filter, don't re-pick). | EX | Medium (~100 junk first examples) | S–M |
| **P20** | **Audit `elision_mapping.json` junk targets** vs `spanish_forms` (stage 2 F2): tir/nir/felis/to's. Sample layer, fix targets, never delete. | HYG | Low-medium | M |
| **P21** | **Hardening & honesty:** move the Genius token to `.env`; add the wiktionary elif to 6c's gemini branch + refuse `--sense-menu-file` without `--method-name` (stage 5 F9); stamp `sense_methods` for gap-fill/auto so the trust UI works (stage 7 F4b); surface region labels (stage 4 F5); count every join drop into the dev footer (stage 7 F8). | HYG | Low each, prevents next incident | S each |

### The open source-choice question (SD vs Wiktionary vs hybrid)

Evidence supports the **hybrid lean, not a cutover**: SD wins presence + learner glosses at
the head (head 92% vs wikt's tail 62%→SD's 2× tail presence), but SD's tail is salted with
the fuzzy-match damage P9/P13 address, and Wiktionary is the *only* source for 134 tail
words incl. the two biggest never-classified cards (baby, flow). Neither source has PR
"bellaco = horny" in English — the **eswiktionary dialect supplement remains necessary**
regardless. Recommended shape: **keep SD primary; fall back to WIKT per-word when SD's menu
is missing or fails the P9 plausibility gate; keep both analyses when they disagree**
(additive, per the provenance rule). This slots into the method-priority system rather than
replacing the source. Not a Tier-0/1 item — it depends on P9's gate existing first.

---

## What NOT to spend effort on (negative results)

- **Prompt wording** (stage 5 F3): the PR-dialect hint made accuracy *worse*; headword
  labels were neutral. The classifier's problems are run conditions + menus, not the prompt.
- **Chorus/near-duplicate example dedup** (stage 4 F11): only 0.8% of meanings after the
  front-end's exact-string dedupe. Not a real problem.
- **A separate lemma-mode app fix for wrong-lemma pooling** (stage 6 F5): auto-fixed by the
  P5 rebuild.
- **Genius translation *alignment*** (stage 1 F7): 30/30 correct; the lever is coverage
  (P17), not alignment.

---

## Implementation progress (2026-07-21)

Work started against this plan the same day it was written. Log:

- **P6 — example selector — DONE & SHIPPED** (commit `1e3c794`). Rewrote
  `sortExamplesByRelevance`: translated-first → 6–14 content-token length window → deck
  overlap capped at 3 / recent-wrong capped at 2 → easiness. Verified on live data: `nunca`
  71→10 tokens, `sol` drops the ad-lib line, `ahora`/`tú`/`bendición` all tighten. Cache
  bumped 20260721a / v44.
- **P2 — cognate timebomb — DONE & SHIPPED** (commit `b837b82`). Chose the *live-parity*
  route over blocklist-and-enable: `step_8b` now gates the auto `cognate_score` stamp behind
  `--stamp-cognate-scores` (default OFF), so a rebuild stamps none and hides nothing new; the
  curated `is_transparent_cognate` hides (~500 live cards) are untouched. New read-only
  `tool_8b_cognate_would_hide.py` reports the blast radius (BB artifact:
  `Artists/spanish/Bad Bunny/data/reports/cognate_would_hide.json`) so a cleaned filter can
  be enabled deliberately later. **Measured** would-hide at 0.85 = 444 cards: 28 copula/aux
  (estar paradigm, 1,306 occ — the deck-breaker) + 47 false-positives + 369 defensible real
  cognates.
- **P3 — never-classified blanking — INVESTIGATED, DOWNGRADED (no code change).** The
  "360 keys blanked / saves sé/ya/una/mía" framing was overstated. Sibling-analysis check:
  360 cut keys = 172 correct junk-cuts (surface word keeps another analysis, e.g.
  `para|parar` cut while `para|para` survives) + 188 at-risk, of which **only 11 have
  cc≥2** (visible past `hideSingleOccurrence`) and **exactly one is a real Spanish word:
  `y` (=and, cc 3501)**. The rest are English (`to`, `i'm`, `don't`) / proper nouns
  (`marc`, `justin`) that `is_english`/propn already hide. The audit's cited casualties are
  safe: `sé`/`una`/`mía` survive via a sibling analysis (`mía|mío` is junk but `mía|mía`
  lives); `ya` is already noise-excluded (cc 0). **Net: the min-priority cut works
  correctly; the rebuild's only P3 casualty is `y`.** Optional trivial keep for `y`;
  otherwise no action. This removes P3 as a rebuild blocker.

**Revised rebuild gate:** with P2 done (live parity) and P3 dissolved, the rebuild no longer
introduces new damage. Remaining Tier-0 items are correctness, not blockers: P4 (stamp the 2
ghost exclude buckets), then P1 (re-classify) + P5 (rebuild + id-migration map). P4 is the
next step.
