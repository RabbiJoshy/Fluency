# Stage 5 — step_6c Gemini Flash Lite classification + gap-fill (LIVE SpanishDict deck)

Audit date 2026-07-20. All data: `Artists/spanish/Bad Bunny/data/layers/` (BB), code:
`pipeline/step_6c_assign_senses_gemini.py` (6c), `pipeline/artist/step_6a_assign_senses.py` (6a).
Gemini spend this audit: 5 calls, ~74K in / ~9.4K out tokens ≈ **$0.011** (budget $1).

Baseline (probe1): sense_assignments/spanishdict.json = 7,387 words. Method histogram
(words / items / example-claims):
`spanishdict-flash-lite` 6,372/9,124/20,172 · `spanishdict-keyword` 5,237/6,654/14,200 ·
`biencoder` 617/837/1,042 · `spanishdict-auto` 470/470/1,305 · `gap-fill` 358/358/1,108 ·
`pos-auto` 41/45/105. Menu = 7,054 words / 73,576 senses (median 8/word, p90 23, max 72;
930 words >20 senses, 82 words >40 — pico 71, ve 56, da 47, corta 47).

---

## The two prompts, verbatim (unchanged since April 2026)

**Classification prompt** — `classify_batch_gemini()`, step_6c:171-207. Batches of 50 words
(BATCH_SIZE=50), each word with its sense menu + up to 10 examples:

```
You are classifying Spanish vocabulary from song lyrics.
For each word below, assign each numbered example to the best-matching sense (0-indexed). If both an English sense and a Spanish [ES] sense cover the same meaning, prefer the English one.

Substitution test: for each example, mentally substitute the sense definition into the English translation. Does it still convey the right meaning? If not, try other senses. Pick the sense whose definition makes the substituted sentence make sense, even if the translator used a different English word.
Example: 'I have the shaved bug' + sense 'penis' — substituting 'penis' makes more sense than 'bug' in this context → pick 'penis'.

--- Word 1: "<word>" (lemma: <lemma>) ---
Senses:
  0. [POS] translation (context) [register]
     e.g. target → english          <- only if the sense carries an example
Examples:
  1. <spanish line> | <english translation>
  ...

Return a JSON array with one object per word:
[{"word": "example", "assignments": {"1": 0, "2": 1}}]
```

**Gap-fill prompt actually used by the live run** — `gap_fill_batch_gemini()`, step_6c:404-444,
called at step_6c:1339 with `"senses": []` hardcoded (step_6c:1333-1338), batches of 10:

```
You are helping build a Spanish vocabulary flashcard app for learners.
For each word below, decide whether the examples are covered by an existing
dictionary sense menu. If not, propose ONE short flashcard-friendly sense.
Return a JSON array with one object per word.

--- Word 1: "<word>" (lemma: <lemma>) ---
Candidate senses: (none)
Examples:
  1. <spanish> | <english>

Return JSON like:
[{"word": "example", "covered_by_existing": false, "best_sense_index": null,
  "english_translation": null, "proposed_sense": "short meaning",
  "proposed_pos": "NOUN", "proposed_lemma": "hablar"}]
```

Prompt-audit facts:
- **Bilingual context is already there** (spanish | english per example) — the proposed
  "add English translation" variant is moot.
- **No dialect/register hint** anywhere.
- **Sense lines carry no headword** — `_format_sense_line` (step_6c:50-72) prints only
  `[POS] translation (context)`; for 've' the model sees 56 bare glosses with no signal
  which belong to ir vs irse vs ver vs verse. The `label` slot is only used for `[ES]`.
- **lemma is always == word in artist mode** (step_6c:868-869: `lemma = word`), so the
  header "(lemma: ve)" adds nothing.
- **Silent first-sense fallbacks**: invalid/out-of-range sense idx → coerced to 0
  (step_6c:1216-1218); whole-batch parse failure → ALL examples assigned to sense 0
  (step_6c:1241-1246). First-menu-sense bias is built in as the error mode.
- The much better single-word gap-fill prompt with the written-out substitution test
  (`gap_fill_gemini`, step_6c:325-375) is **dead code** in 6c — main() never calls it.
- `_repair_proposed_sense` + `_is_definitional` (step_6c:237-322) exist NOW but post-date
  the live run (see F6: 67% of live gap-fill glosses fail the current detector).

---

## F1 — The live deck's wrong senses are mostly NOT reproducible today: same prompt, same
menus, today's flash-lite gets 16-17/20 of them right (live: 0/20). CONFIRMED, eval below.

WHAT: The dominant error source on the live deck is neither the prompt text nor (mostly)
the menu — it is the April-2026 classification RUN itself (older flash-lite endpoint
quality + batch scatter). The stored assignments are stale relative to what the identical
pipeline produces today.

EVIDENCE — gold-set eval (design + raw results at end): 30 items = 20 error-class
(live picked wrong, correct sense verifiably ON the menu) + 10 controls (live correct).
Live deck score on error-class: **0/20**. Current prompt V0 (single example/word):
**17/20**. Production-like V3 (all 10 examples/word): **16/20**. Production-size V4
(50-word batch): **16/20**. Examples: `media` "Como media virá'" live=sock →
today=medio:half (all variants); `suena` "suena la Glock" live=to blow (mucus) →
today=sonar:to go off; `da` "el sol te da" live=to teach → today=dar:to hit; `pico`
"un melón y pico" live=beak → today=pico:something(quantity); `botes` "pa' los bote'"
live=bottle → today=bote:boat; `tienen` "Tienen que espera'" live=to be(age) →
today=to have to.

ROOT CAUSE: step_6c incremental design (covered-index skip, step_6c:929-956) means the
deck permanently keeps the April run's picks; nothing ever re-audits them. Model endpoint
`gemini-2.5-flash-lite` improved silently since.

PROPOSED FIX: re-run `step_6a --classifier gemini --force` on BB (est. ~130 batches ×
~20K tokens ≈ $1-2 at flash-lite pricing) — command for Josh, not run here:
`.venv/bin/python3 pipeline/artist/step_6a_assign_senses.py --artist-dir "Artists/spanish/Bad Bunny" --classifier gemini --force --no-gap-fill`
(then step_7a + builder). Protect Josh's tool_8c curations first (curated overrides must
win over re-classified output — verify merge order before running).

IMPACT: largest single quality lever found. Proxy for affected cards: 565 of 6,372
flash-lite words (8.9%) have example claims scattered across ≥3 senses, 133 across ≥5
(a, su, rico, están:7, ve:6, ven:7, dejo:7, sale:6…); taxonomy sample says ~17% of
classified words carry ≥1 wrong-sense example → ~1,100 words. Josh-visible: the still-
unfixed flags ve/da/suena/vuelve/mueve/media are all this class (live master rows:
`ve|ir: to go×4 + to wear + to be`, `da|dar: … to teach …`, `suena|sonar: … to kick the
bucket`, `media|media: sock; average; half hour; half past; midfield; stocking`).
EFFORT: S (a re-run + rebuild), M if curation-protection needs work.

## F2 — Batch load measurably degrades accuracy; BATCH_SIZE=50 is too big. CONFIRMED.

WHAT: The same gold items pass at 10/10 (controls) with 1 example/word in a 30-word
batch, drop to 8/10 with 10 examples/word, and 7/10 at production 50-word size — new
errors are exactly the live-deck signature: easy words scattered to absurd senses
(`conejo`→"fanny", `mesa`→"board"/"committee", `borra`→"yearling ewe", `ve` "se ve la
luz"→"to go").
EVIDENCE: eval table below (V0 vs V3 vs V4 controls column); token counts 12.7K → 13.9K
→ 19.9K.
ROOT CAUSE: step_6c:155 `BATCH_SIZE = 50`; one JSON response must carry ~300+ index
assignments.
PROPOSED FIX: BATCH_SIZE 50→10 (5× more calls, still cheap); optionally single-word
calls for the top-500 frequency words. Also add a "0. NONE of these fits" escape option
so proper-noun/slang examples stop being force-binned (the coerce-to-0 fallback at
step_6c:1216-1218 makes bin-0 the dumping ground).
IMPACT: every future run, all artists. EFFORT: S.

## F3 — Prompt variants do NOT help; don't spend effort there. CONFIRMED (negative result).

WHAT: A PR/Caribbean-dialect + reggaeton-register hint made things WORSE (V1 14/20 vs
V0 17/20) — it pushed the model into slang over-reach (e.g. `vuelve` items flipped to the
blank-gloss `volver ''` sense). Adding headwords to sense lines (V2) was neutral-to-noise
(15/20). Controls stayed 10/10 in both.
IMPLICATION: with today's model the current prompt wording is adequate; the wins are in
run conditions (F2), menus (F4, F5), and re-running (F1). The one wording change still
worth making is the NONE-escape (F2), which no variant tested here provides.

## F4 — Menu faults are the second error source (~8% of words) and gap-fill can never
rescue them: it fires only on zero-sense words. CONFIRMED.

WHAT: When SpanishDict has an entry but the PR-slang sense is missing, the classifier
must pick something wrong, and the gap-fill safety net is structurally bypassed —
`no_senses_queue` is only fed when `combined` is empty (step_6c:1056-1059).
EVIDENCE (live cards, probe2): `palomo` n=3 → "male pigeon" (menu: 4 pigeon/dove senses;
real: PR "sucker/chump" — Josh curated it to exactly that); `millo` n=13 → "corn"
("Ya mismo soy millo" = millionaire; menu only millet/corn/maize); `corta` n=16 →
fag end/to slice/to amputate for gun lines ("aquí to's andan con corta"); `coro` n=13 →
"chorus" for "hacer coro" (crew/roll-with); `tabla` → "surfboard" for "darte tabla";
`polo` → only sport/clothing senses, so "polo positivo y negativo" → "polo (sport)";
`tratar` → menu lacks "tratar de = to try", both examples ("Tratar de olvidar") got
"to treat"; `bate` n=5 → menu is a single BLANK-gloss sense `[bate|VERB] '' (to
moderate)` auto-assigned to blunt/bat lines; `tírala` → menu only has `tira` NOUN
(strip/strap/cops) — clitic never merged, imperative of tirar absent; `glizzy` → matched
English headword "glitzy" with SPANISH glosses (esplendoroso/espectacular…) — the
reverse-direction-menu class (diagnosed bug #6) reaching the classifier.
ROOT CAUSE: menu scrape scope (stage upstream) + step_6c gap-fill gate at 1056-1059.
PROPOSED FIX: let classification emit NONE-fits (F2) and route NONE-majority words into
the gap-fill queue WITH their menu (the dead `gap_fill_gemini` prompt at step_6c:325-375
was designed for exactly this — senses + substitution test + propose-if-not-covered).
IMPACT: most of Josh's remaining un-fixed flags are this class; taxonomy says ~3/40
words (7.5%) ≈ ~480 words corpus-wide upper bound, concentrated in the slang vocabulary
that is the whole point of an artist deck. EFFORT: M.

## F5 — SD conjugated-form PHRASE analyses + blank-gloss senses pollute menus and win
classifications. CONFIRMED.

WHAT: Menus for conjugated surfaces carry SD's learner-page PHRASE entries ("move
(imperative)", "he moves", "she moves", "let's go") alongside the real verb analyses;
the classifier loves them, producing wrong-analysis cards.
EVIDENCE: `mueve` live = ALL 10 examples → `b62 move (imperative PHRASE)` including
"yo soy el que mueve los kilos" (declarative); today's model still falls for it (V3/V4
picked "she moves" PHRASE). `vamos` live = all 10 → "let's go (PHRASE)" including
"pa' mi cama nos vamo' los tre'" (= we're going, irse); still picked today. These two
gold items were 2 of the 4 persistent failures. Blank glosses: 1,958 menu senses across
1,182 words have `translation: ""`; 53 assignment items (48 words, 80 example-claims)
point at blank senses (a, de, sabe, diablo, poco, cae, muere, damos, vuelves…) →
glossless card rows (the `bate` card was one until Josh curated it).
ROOT CAUSE: menu build (step_5c/SD scrape) keeps zero-information senses; 6c renders
them as `  N. [VERB]  (to hand over)` — an attractive low-content bin.
PROPOSED FIX: drop blank-translation senses from the classifier menu (they can stay in
the layer file); demote/merge PHRASE duplicates of verb analyses when the same headword
family is present.
IMPACT: 1,182 words carry blank senses; PHRASE-trap affects high-frequency imperative-
looking forms (mueve, dale, vamos, ve…) — the exact words Josh sees most. EFFORT: S-M.

## F6 — Gap-fill on the live deck: 67% of its 358 glosses are definitional junk by
step_6c's own current standard. CONFIRMED.

WHAT: The live gap-fill ran before `_is_definitional` + `_repair_proposed_sense`
existed; its output is dictionary sentences, not flashcard glosses, plus invented
entries for words that should never have been cards.
EVIDENCE: 240/358 (67%) of live gap-fill translations fail the current detector.
Live samples: `haters` → "People who intensely dislike or resent someone, often
expressing their negativity online." (Josh-flagged card es11eac4f, still live);
`baby` → "Term of endearment, like 'darling'…"; `flow` → "A person's distinctive
style, manner…"; `game` n=6 → "A video game console, specifically the Nintendo Game
Boy."; `meme` → "something or someone that is the subject of ridicule…". 53 of 358
gap-fill words are English loanwords (baby, flow, like, down, light, man…) — the
exclude.cognate/loanword leak wave-1 flagged, grandfathered in before the skip layer.
Junk beyond definitional style: proper-noun inventions (`luis`, `wason`→"The Joker",
`lanalizer`, `guiru`, `yankee`), a French line leak (`caressais`→lemma "caresser"),
invented wrong lemmas (`compes`→"competición"; should be competencia), non-canonical
POS strings the prompt didn't ask for (`ADJECTIVE`, `INTERJECTION`, `PROPER_NOUN` —
prompt requests NOUN/VERB/ADJ/ADV/INTJ; downstream stores them verbatim). Sample of 20
judged: 8 good (atreves→"to dare…" though 6 words, ticket→"Money…" correct slang,
viral, okey, fantasías), 12 junk/dubious → ~40-60% junk rate consistent with the 67%
detector number.
ROOT CAUSE: live data predates step_6c:1352-1363 repair path; batch gap-fill prompt
(the weak one) was used; exclusion buckets leaked (fixed since at step_6c:719-727).
PROPOSED FIX: one-off re-gap-fill pass: `--skip-classification --force` limited to
gap-fill words (or a tool that re-prompts the 240 definitional ones through
`_repair_proposed_sense`); validate proposed_pos against the canonical set; drop PROPN
proposals outright (master already flags propernouns).
IMPACT: 358 words, 1,108 example-claims; 297 of the never-classified default-view cards
wave-1 counted are gap-fill-only. Highly visible (the flagged `bi`/`haters` cards).
EFFORT: S (re-prompt is ~36 batches ≈ cents).

## F7 — english_loanwords skip: layer applied AFTER routing, silently overriding
step_4a's classifier verdict for 138 words. CONFIRMED (mechanics + count).

WHAT: step_6c:755-767 loads `Data/Spanish/layers/english_loanwords.json` (1,606 surface
forms, built from Wiktionary "borrowed from English" etymologies by
tool_4a_build_english_loanwords.py) and adds every one to `skip_set` — after
word_routing's exclude buckets, with no per-artist keep-list (the comment at 760-761
admits the hook is "future").
EVIDENCE: word_routing classifier buckets ∩ loanwords = **138 words** (adrenalina,
after, bichote, brasier, cachar, chance, gasolina-class words…), matching wave-1's
stage3 #5. 93 loanwords still HAVE assignments from runs before the layer existed
(baby, bikini, blunt, brother, clan, club…) → inconsistent state: old loanwords keep
(often junk gap-fill) senses, new ones get nothing, and joinWithMaster renders
unclassified ones as first-menu-sense/X cards.
ROOT CAUSE: skip is keyed on Wiktionary etymology, not on whether the word is a live
Spanish borrowing with a real SD menu (bichote, brasier, gasolina are Spanish-integrated
words, not code-switches).
PROPOSED FIX: only skip loanwords that have NO SpanishDict menu entry (pure
code-switches); words with an SD menu should classify normally. Add the per-artist
keep-list the comment promises. Clean the 93 grandfathered ones one way or the other.
IMPACT: 138 routed words never classified + 93 inconsistent; includes Josh flags
(light, down, play, out, shot, panty, cherry). EFFORT: S.

## F8 — --max-examples 10 never bites: examples_raw.json is itself capped at 10.
The classifier sees ≤10 of up to ~1,500 corpus occurrences. CONFIRMED.

WHAT: 0 of 6,372 flash-lite words have >10 raw examples (probe1) — step_5a's example
selection already caps the layer at 10, so the 6c flag is a no-op on BB and "fraction
of high-count words classified on a subsample" = effectively all high-count words:
que/no/me/la/a… all have exactly 10 stored examples regardless of corpus_count (para
n=1505, cabrón n=308, vamos n=295).
IMPLICATION: (a) the per-word sense DISTRIBUTION on cards extrapolates from ≤10 lines —
minority senses of very frequent words are invisible; (b) the 5%-frequency prune at
step_6c:1230-1232 can never fire under 10 examples (1/10 = 10% ≥ 5%), so every stray
single-example misclassification becomes a visible sense row — this is why scatter
(F1/F2) converts directly into 5-6-row cards (`media` card shows 6 senses from 10
examples).
PROPOSED FIX: raise the prune threshold for ≤10-example words (e.g. drop 1-example
senses when the word has ≥8 examples and the sense is unique), or classify more
examples for the top-N words (step_5a change, not 6c). EFFORT: S (threshold) / M (more
examples).

## F9 — Orphan bug #3 status: live BB data currently CLEAN (0 orphans); .bak shows the
bug existed (202 items); the code path that caused it is still open for wiktionary-
source gemini runs. CONFIRMED with counts.

WHAT: Assignments whose sense id no longer exists in the menu.
EVIDENCE: current `sense_assignments/spanishdict.json` vs `sense_menu/spanishdict.json`:
**0/16,550 items orphaned** (probe1 — gap-fill excluded as it carries inline senses).
`spanishdict.json.bak` vs current menu: **202/16,550 items, 131 words** — an orphan
population existed and was repaired (meta file says `step_name: migrate_example_ids`,
2026-04-29 era). Young Miko current: 0/4,201 (spanishdict), 0/1,815 (wiktionary).
CODE: the dispatcher's gemini branch passes `--sense-menu-file` for spanishdict
(step_6a:56-65 `_spanishdict_args_gemini`, applied at 132-134) — the brief's literal
"gemini branch omits --sense-menu-file" is FIXED for spanishdict — but there is **no
wiktionary elif** in the gemini branch (contrast biencoder branch step_6a:112-124 which
points at the artist wikt menu when present). A `--sense-source wiktionary --classifier
gemini` run therefore rebuilds menus from raw kaikki inside 6c and re-keys content-hash
ids (util_6a_method_priority.py:85-109) whenever `clean_translation`/merge logic
changes → the Young-Miko-style 60% orphaning can recur on any wikt gemini rerun.
RELATED PITFALL (confirmed in code): with `--sense-menu-file` but no `--method-name`,
step_6c:806-809 silently stamps the method `spanishdict-flash-lite` even for a
non-SpanishDict menu; any custom method name not in METHOD_PRIORITY falls to priority 0
(util_6a_method_priority.py:71 `.get(m, 0)`) and loses every priority contest silently.
PROPOSED FIX: mirror the biencoder wikt-menu branch in the gemini branch; make 6c refuse
`--sense-menu-file` without `--method-name` (or derive the label from the menu filename);
add an assemble-time orphan assertion so orphans fail loudly instead of being cleaned
ad hoc. EFFORT: S.

## F10 — Failure taxonomy (stratified 40-word sample, seed 42: 14 high / 14 mid / 12 low
frequency flash-lite words, all examples inspected)

| Class | Words | % | Examples |
|---|---|---|---|
| Correct / defensible | 30 | 75% | quiero, conejo, dale, después, polvo ("screw" for sex lines — correct), fueran ("to be made of" for "lunas fueran de miel"), blanquita, costado, escondíos |
| ≥1 wrong-sense pick, right sense ON menu (classifier fault) | 7 | 17.5% | saber ("can" for "no quiero saber más de ti"), tienen ("to be (age)" for "tienen que"), quito ("except for" for "le quito sus panties"; "take off clothing" for the CITY Quito), pico ("beak" for "y pico"), botes ("bottle" for boats), nace ("to hatch" for "guerra que nace"), blanquita ex2 (coke line → "white girl") |
| Right sense MISSING from menu (menu fault; gap-fill structurally can't fire) | 3 | 7.5% | glizzy (reverse-direction "glitzy" menu), tírala (only `tira` NOUN senses), tratar (no "tratar de = to try") |
| Evidence too thin / chorus repetition | 0 | 0% | (repetition dedup upstream seems adequate in this sample) |

Classifier-fault : menu-fault ≈ 2.3 : 1 by word count — but F1 shows the classifier
faults are largely an artifact of the April run; on a re-run today the residual mix
shifts toward menu faults (F4/F5) as the dominant remaining source.

---

## VERDICT

1. **Dominant error source on the live deck: the stale April-2026 classification run**,
   not the prompt and not primarily the menu. Identical prompt + menus today: 16-17/20
   error-class items correct vs live 0/20, controls 10/10 (single-example).
2. **Prompt changes alone would NOT have fixed the observed error classes** — dialect
   hint hurts (14/20), headword labels neutral (15/20). The valuable changes are
   operational: re-run with --force, shrink BATCH_SIZE, add a NONE-escape, prune
   blank/PHRASE menu senses, and re-open gap-fill for menu-fault words.
3. Ranked recommendations: (1) F1 re-run (+F2 batch=10) — S effort, fixes ~1,100 words;
   (2) F6 gap-fill re-prompt — S, fixes 240 junk glosses incl. flagged cards; (3) F5
   blank/PHRASE menu pruning — S; (4) F4 NONE-escape + menu-carrying gap-fill — M,
   the only path for palomo/millo/corta-class slang; (5) F7 loanword-skip refinement — S;
   (6) F9 dispatcher/method-name hardening — S, prevents the next orphan incident.

---

## APPENDIX — Eval design + raw results

**Design.** 30 gold items = (word, one BB lyric example, accept-set of menu sense ids).
20 error-class items chosen from Josh's flags + probe2/probe3 findings where the correct
sense verifiably exists on the live SD menu (accept-sets defined by headword+gloss, then
resolved to ids from the live menu — see `eval_gemini.py` GOLD table); 10 controls where
the live deck is correct. One item (`blanquita` ex2) is marked debatable (coke vs girl).
Menu-fault words (palomo, millo…) were deliberately EXCLUDED — no classifier prompt can
fix an absent sense. Variants: **V0** = production prompt verbatim, 1 example/word;
**V1** = V0 + "Puerto Rican Spanish… reggaeton/trap… slang or figurative sense" hint;
**V2** = V0 with `[headword|POS]` sense lines; **V3** = V0 with ALL (≤10) examples/word
(grade gold indices only); **V4** = V3 padded with 20 random multi-sense words to
production BATCH_SIZE=50. Model gemini-2.5-flash-lite, temp 0, JSON mime. Scripts:
`eval_gemini.py`, `eval2_batchsize.py`; raw JSON: `eval_results.json`,
`eval2_results.json` (this scratchpad).

**Accuracy:**

| Variant | error-class (20) | controls (10) | all (30) | in-tokens |
|---|---|---|---|---|
| LIVE deck (April 2026 run) | **0** | 10 | 10 | — |
| V0 current prompt, 1 ex/word | **17** | 10 | 27 | 12,716 |
| V1 + dialect/register hint | 14 | 10 | 24 | 12,769 |
| V2 + headword labels | 15 | 10 | 25 | 14,461 |
| V3 all examples/word | 16 | 8 | 24 | 13,869 |
| V4 50-word production batch | 16 | 7 | 23 | 19,929 |

**Per-item (live pick → V0/V3/V4 picks; OK per accept-set):**

| word/ex | line (gist) | live pick | V0 | V3 | V4 |
|---|---|---|---|---|---|
| media/0 | "media virá'" half crazy | sock ✗ | half ✓ | half ✓ | half ✓ |
| media/6 | "Media libreta" | sock ✗ | half ✓ | half ✓ | half ✓ |
| media/9 | "Media libra" | stocking ✗ | half ✓ | half ✓ | half ✓ |
| suena/8 | "suena la Glock" | to blow(mucus) ✗ | to go off ✓ | to ring ✓ | to ring ✓ |
| suena/5 | "la que suena" (gun) | look familiar ✗ | to ring ✓ | to ring ✓ | to ring ✓ |
| ve/3 | "se ve rica" | go(imper.) ✗ | ir:to look ✓ | ir:to look ✓ | ir:to look ✓ |
| ve/7 | "se ve la luz" | to wear ✗ | ver:to see ✓ | to go ✗ | to go ✗ |
| ve/5 | "no se ve contenta" | watch ✗ | verse:to look ✓ | ir:to look ✓ | ir:to look ✓ |
| da/8 | "el sol te da" | to teach ✗ | dar:to hit ✓ | to hit ✓ | to hit ✓ |
| vuelve/9 | "me vuelve loco" | go back ✗ | to turn ✓ | to turn ✓ | to turn ✓ |
| vuelve/0 | "se vuelve loca" | to return ✗ | to become ✓ | to turn ✓ | to turn ✓ |
| pico/0 | "melón y pico" | beak ✗ | something ✓ | something ✓ | something ✓ |
| pico/2 | "melón y pico" | beak ✗ | something ✓ | something ✓ | something ✓ |
| botes/0 | "pa' los bote'" | bottle ✗ | boat ✓ | boat ✓ | boat ✓ |
| tienen/7 | "tienen que" | to be(age) ✗ | to have to ✓ | to have to ✓ | to have to ✓ |
| quito/8 | "le quito sus panties" | except for ✗ | take off ✓ | except for ✗ | except for ✗ |
| blanquita/2 | "blanquita, perico, kilo" | white girl ✗ | white girl ✗ | snow ✓ | snow ✓ |
| mueve/1 | "mueve los kilos" | move!(PHRASE) ✗ | (out-of-range) ✗ | she moves ✗ | she moves ✗ |
| saber/4 | "no quiero saber más" | can ✗ | to know ✓ | to know ✓ | to know ✓ |
| vamos/1 | "nos vamo' los tre'" | let's go ✗ | let's go ✗ | let's go ✗ | let's go ✗ |
| controls ×10 | — | 10/10 | 10/10 | 8/10 (conejo→fanny, mesa→board) | 7/10 (+borra→yearling ewe) |

Persistent failures across all variants: `vamos` + `mueve` (PHRASE-analysis traps, F5),
`quito` under load, `blanquita` (genuinely ambiguous). Everything else is recoverable by
a re-run.

**Probe scripts in this scratchpad:** `probe1_structure.py`, `probe2_errorwords.py`,
`probe3_taxonomy.py` (+ `probe3_out.txt`), `eval_gemini.py`, `eval2_batchsize.py`.
