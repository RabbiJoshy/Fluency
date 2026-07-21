# Stage 4 — SpanishDict sense-menu quality (5a/5c) + example selection, BB live deck

Probes: `probe_a_menu.py`, `probe_a2_fuzzy_wikt.py`, `probe_b_examples.py` (this scratchpad dir).
Baseline: menu = 7,054 words / 73,576 senses (`Artists/spanish/Bad Bunny/data/layers/sense_menu/spanishdict.json`);
live deck = 11,198 index rows, 9,972 join master ("live"); 12,297 live meanings with examples / 23,193 example instances.
SD scrape cache: `Data/Spanish/Senses/spanishdict/surface_cache.json` (56 MB) + `headword_cache.json` (14 MB).

---

## PART A — SD menu quality

### F1. 26 menus fuzzy-resolved to ENGLISH headwords (the perse→purse class), 23 of them live

**WHAT:** SpanishDict's fuzzy matcher resolved 26 corpus words to English dictionary headwords; 23 have live cards.

**EVIDENCE (systematic scan: headword in /usr/share/dict/words AND not in spanish_forms.json):**
`revol→revolt` (n=10, live), `lambos→lamb` (5), `frabian→Fabian` (4), `lary→lazy` (4), `biles→bile` (3),
`cavaliers→cavalier` (3), `ebay→embay` (3), `perse→purse` (3, Josh flag es146520f), `yales→Yale` (3 — PR slang
"girls" resolved to the university), `alexio→alexia`, `anthon→Anthony`, `connes→Conn`, `illuminatis→illuminati`,
`jhay→jay` (Jhay Cortez), `nkan→nan`, `tranquilita/tranquilito→tranquility` (common diminutives of tranquila/o!),
`trili→trill`, `clarito→clarity`, `moral→morals`, `revelo→reveler`, `bakin'→baking`, `to'→to`, `lu'→Lu`, `to'l→tol`.

**ROOT CAUSE:** two layers. (a) SD fuzzy match itself returns EN headwords for unknown slang. (b) The scraper now
forces `?langFrom=es` (`pipeline/util_5c_spanishdict.py:296-307`) and stamps `entry_lang`
(util_5c_spanishdict.py:555-571), but `step_5c_build_senses.py:1044-1056` deliberately KEEPS legacy cache entries
with missing `entry_lang` ("we keep them — bumping the scraper STEP_VERSION will refetch"). Verified in cache:
`poses`, `perse`, `tranquilita`, `lary`, `revol`, `totito` all have `entry_lang=None` (pre-fix scrapes); `es` has
`entry_lang='es'` (post-fix). The refetch never happened for BB.

**PROPOSED FIX:** (1) Targeted re-scrape of all `entry_lang`-missing surface-cache entries used by BB
(command for Josh: `.venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py --artist-dir "Artists/spanish/Bad Bunny" --force`
— slow, network). (2) Even post-rescrape, add a builder guard in `build_menu_analyses`
(util_5c_spanishdict.py:191): drop analyses whose headword is in an EN wordlist and not in `spanish_forms.json`
(same test as the probe; catches EN headword_cache pages reached via `possible_results` redirects, which
`langFrom=es` does not fix). **IMPACT:** 23 live cards with nonsense identity (lemma column shows the EN word —
master has `lary|lazy`, `frabian|Fabian`, `connes|Conn`). × **EFFORT S** (guard) + M (re-scrape).

### F2. Reverse-direction (Spanish) glosses on live cards — 58 live master senses, ~40 genuinely backwards

**WHAT:** Sense glosses that are Spanish, not English, shipped to live cards (brief bug #6 quantified).

**EVIDENCE (probe: gloss tokens in spanish_forms.json AND absent from EN dict; live master join):** 58 live senses
are majority-Spanish; after removing loanword false positives (reggaetón, mafia, sushi…), the real backwards class:
- `poses` (id bb6bc5): SD resolved to the ENGLISH entry "pose" → 9 live senses glossed *posar, plantear,
  representar, hacer posar, hacerse pasar, postura, afectación* — an entire backwards card.
- `hey` (id 3f3f55): glosses *hola, momentito* — **Josh flagged this card (es03f3f55)**.
- `to` (via to'): *hacia, menos*. `revol`: *revuelta*. `lary`: *perezoso*. `fans`: *aficionado*.
  `bluntes`: *porro*. `cavaliers`: *caballero*. `frabian`: *Fabián*. `connes`: *Connecticut*.
  `bleacher`: *grada descubierta*. `mojo`: *chispa*. `base`: *fundamento*. `illuminatis`: *Iluminados/iluminados*.
  `perico`: *cortado* (Spain coffee sense; BB context is cocaine). `taba`: *jacks* (wave-1's beheaded 'taba).
- Menu-wide: 584 sense rows flagged (includes FPs like "twerking"/"nightclub" absent from /usr/share/dict/words).

**ROOT CAUSE:** same as F1 — backwards entries: when SD resolves an es query to an EN headword, translations come
out Spanish. The `entry_lang` guard (step_5c:1054) only skips entries *explicitly* marked non-es; legacy blanks and
EN headword-cache pages pass through. **PROPOSED FIX:** F1's guard kills most; additionally a cheap gloss-language
lint at menu build (flag senses whose gloss tokens are majority Spanish-only) feeding a review file.
**IMPACT:** ~40 live senses across ~25 cards showing Spanish "translations". × **EFFORT S**.

### F3. Wrong-SPANISH-headword fuzz on slang (totito→torito class) + junk sibling analyses

**WHAT:** Slang/diminutive queries fuzzy-resolve to the wrong Spanish lemma; and rare-verb analyses are ordered
before the common word.

**EVIDENCE:**
- `totito→torito` "little bull" (n=24; PR slang for vagina), `nacíos→nacho` — live sense gloss "nacho" (id 661626;
  nacíos = nacidos), `metíos→metro` — live gloss "metro" (id 1f5d87; metíos = metidos), `jeva→jevo` "boyfriend"
  (wrong gender; wikt has jeva "very attractive woman"), `eres→erar,r` (junk analyses "erar" and single-letter "r"
  alongside ser), `dile→di`, `dale→¡Dale!`, `jajaja→¡Jajaja!` (exclamation headwords become lemmas).
- Josh's flags in the same class: `toítas→torta` (es1e258b6), `así→asir` (es1f26a35), `denle→dense` (es1f868b4),
  `pasándola→parar` (brief #7).
- Ordering: `veces` menu lists `vezar` ("to accustom", 4 senses) BEFORE `vez` — probe's first-gloss for veces =
  "to accustom". `gata` menu's first sense is "jack" (car jack) before "cat". Order comes from
  `infer_analysis_order` (util_5c_spanishdict.py:496-516) which trusts SD's `possible_results` order. This is
  exactly what never-classified / gap-fill-fallback cards display (stage3's 326 first-menu-sense cards).

**ROOT CAUSE:** SD fuzzy match has no plausibility guard downstream — `build_menu_analyses` accepts any returned
headword (only abbreviation-with-dots filtered, util_5c_spanishdict.py:142-157); wave-1 F0 (lemma = SD headword at
scrape time, never lemmatized) makes the bad headword the card's lemma. **PROPOSED FIX:** plausibility gate on
surface→headword pairs (edit-distance/prefix on deaccented forms, allowing known suppletive conj via SD's own
`heuristic: conjugation` rows, which ARE trustworthy); order analyses by corpus/frequency evidence instead of raw SD
order for the first-sense fallback. **IMPACT:** dozens of tail cards with wrong identity; every future artist.
× **EFFORT M**.

### F4. Menu coverage by band: head 92% / mid 82% / slang-tail 62%

**EVIDENCE (bands: head = top-300 corpus; mid = rank 1000-3000; tail = corpus n>=3, absent from general Spanish
rank list, alpha, len>3 — 1,189 words):**

| band | SD menu present | avg senses/word | missing |
|---|---|---|---|
| head 300 | 276 (92%) | 14.1 | 24 — all loanwords/interjections: ey(844), baby(613), yeh(465), eh, yeah, bad, bunny, dos*, flow(121), oh… |
| mid 2000 | 1,639 (82%) | 11.0 | 361 — lamborghini, okey, fake, panty, gang… |
| tail 1189 | 737 (62%) | 8.9 | 452 — baby, flow, krippy(81), mambo, trap, blunt, bichote(29), toto(18)… |

(*dos IS missing from the menu despite being core Spanish — SD cache miss worth a look; it's also stage3's
n=133 never-classified card.) Empty-senses menus: 0 in all bands — when a menu exists it has senses.
**IMPACT:** missing-menu words can never be classified → they are the feedstock of stage3's blank X-cards.

### F5. SD context labels survive to cards; REGIONAL labels are captured then thrown away

**WHAT:** Every SD sense has a curated context label and it propagates; the `regions` field (10% of senses) never
leaves the menu layer.

**EVIDENCE:** menu senses with `context`: 73,576/73,576 (100%); live master senses with `context`: 8,819/13,313
(66%) — propagated via step_8b:896-898 and rendered by flashcards.js:1646-1658/2008. Menu senses with `regions`:
7,216 (10%) — top: United Kingdom 1441, Latin America 1440, Mexico 1322, US 1081, Spain 911, Caribbean 258. Live
master senses with a `regions` field: **0**. `grep -n regions pipeline/artist/step_8b_assemble_artist_vocabulary.py`
→ no hits; captured at scrape (util_5c_spanishdict.py:441-447, stored on sense at :536), then dropped at assembly.
Cases where it matters: `chingar` senses split by Mexico-region labels; `perico` "cortado" is a Spain-region sense
sitting on a PR deck; UK-region glosses ("centre" for corazón, "grada descubierta"-adjacent BrE items) would be
down-rankable if regions were visible to the builder/UI.

**PROPOSED FIX:** copy `regions` onto the meaning in step_8b (next to `context`), render as a small tag like
context; optionally use it to down-rank Spain/UK-region senses for a PR artist (ties into the eswiktionary dialect
plan in Josh's memory). **IMPACT:** disambiguation metadata for ~10% of senses currently invisible. × **EFFORT S**.

### F6. Head-vs-tail verdict: SD wins presence + learner glosses; WIKT is the rescue source for loanwords and PR slang

**EVIDENCE (same bands, SD vs `sense_menu/wiktionary.json`):**

| band | SD | WIKT | both | SD-only | WIKT-only | neither |
|---|---|---|---|---|---|---|
| head 300 | 276 | 281 | 269 | 7 | **12** | 12 |
| mid 2000 | 1,639 | 1,424 | 1,303 | 336 | 121 | 240 |
| tail 1189 | 737 | 347 | 214 | **523** | 133 | 319 |

- SD's tail presence is actually 2× WIKT's (523 SD-only) — but salted with F1/F3 damage.
- **134 tail words where SD is missing-or-wrong and WIKT has a menu**, incl. baby(613!), flow(121), mambo(48),
  trap(42), bichote(29 — "big shot"), blunt(26), toto(18 — the sense SD fuzzed to torito), party, sorry, shot.
  The two biggest never-classified head cards (baby, flow) are WIKT-only.
- Spot-compare quality: SD learner-grade at head (`lo`: 8 senses w/ direct-object contexts + SD example pairs;
  `hace→hacer` 30 senses vs WIKT hace="ago" only; `siento`: SD sentir-first vs WIKT sentar-first). Slang tail:
  WIKT more precise where present (`jeva` "very attractive woman" vs SD jevo "boyfriend"; `bellaco` WIKT
  "scoundrel" vs SD "wicked"; `bellaquear` es-wikt "Tener relaciones sexuales" — correct PR sense but
  Spanish-language gloss). NEITHER source has PR "bellaco = horny" in English — the eswiktionary dialect
  supplement remains necessary.

**PROPOSED (hybrid sketch):** keep SD primary; fall back to WIKT per-word when SD menu is missing OR fails the
F1/F3 plausibility gates (≈134 tail words + head loanwords); keep both analyses when they disagree (provenance
rule: additive, never overwrite). × **EFFORT M**.

---

## PART B — example selection

### F7. The actual chain that decides which lyric line Josh sees first (documented, with the twist that the last link overrides the rest)

1. **Base order** — `pipeline/artist/step_5a_split_evidence.py:57-63, 89-114`: `examples_raw.json` preserves
   prior order, appends new; original order = corpus/song scan order. No quality logic.
2. **Assignment order** — step_6 stores example indices per sense; step_8b builds `meaning_examples` in stored
   order (`step_8b_assemble_artist_vocabulary.py:842-877`).
3. **translation_quality sort** — step_8b:879-880 sorts desc by `translation_quality`; `translation_scores.json`
   **does not exist for BB** (verified; written only by `pipeline/artist/tool_1b_judge_translations.py:266`, never
   run) → every example defaults to 3 → stable no-op (brief bug #8 confirmed: the hook exists, the layer doesn't).
4. **Easiness sort** — step_8b:1601-1617 stamps `ex["easiness"]` positionally from ranking.json and sorts → broken
   no-op (F8).
5. **Front-end (decides)** — `js/vocab.js:1278-1294` takes `examples[0]` as `targetSentence`, but
   `js/flashcards.js:2072-2078` re-sorts every render via `sortExamplesByRelevance` (flashcards.js:363-388):
   recent-wrong-word hits desc → **deck-word hits desc** → personal easiness asc
   (computePersonalEasiness flashcards.js:268-292; static `ex.easiness` only if
   `Data/Spanish/spanish_ranks.json` failed to load, flashcards.js:126-136). Exact-string dedupe only
   (flashcards.js:390-398).

So pipeline steps 3-4 are inert; the first line Josh sees is decided almost entirely by deck-word hits (F9).

### F8. step_7b easiness scores are sorted away from their examples — 100% of shipped per-example easiness is fabricated, and the step_8b "sort by easiness" is a mathematical no-op

**WHAT:** step_7b computes per-example easiness then **sorts the score list detached from example indices**;
step_8b re-attaches positionally.

**ROOT CAUSE:** `pipeline/artist/step_7b_rerank.py:358-359` — `# Sort scores ascending (easiest first) to match
example sort order` + `scores.sort()` — but nothing has sorted the examples; `step_8b:1611-1612` then assigns
`ex["easiness"] = scores[i]` positionally and sorts an already-ascending list.

**EVIDENCE:** 12,297/12,297 live meanings (100.0%) have monotonic non-decreasing shipped easiness; 4,148/4,148
ranking.json score lists are pre-sorted. Misattribution demo (shipped vs recomputed with the same algorithm):
`que` (ed688d): "Que si te lo meto e' pa' recordar un T.B.T." shipped 199, actual ≈6588; `yo` (01d789): first
line shipped 24, actual ≈442, while the genuinely easiest line ("No sé si es casualidad…", ≈18) sits third.
Additionally **3,949/12,297 meanings (32%) are all-SENTINEL (999999)** — ranking.json's per-meaning lists are
built from `flatten_best_assignments` of the word-level file (step_7b:184-192, 344) while step_8b's meanings come
from lemma-grouped multi-method resolution, so lists misalign (e.g. every example of `fui|ser` b342df is
SENTINEL). 25.8% of all example instances carry SENTINEL.

**PROPOSED FIX:** delete the detached sort; key easiness by raw-example index (`{ex_idx: score}`) instead of
positional per-meaning lists — immune to meaning-alignment drift. **IMPACT:** currently only the
ranks-fetch-failure fallback path, but it poisons any future use of `ex.easiness`; fix is prerequisite for F9's
selector. × **EFFORT S**.

### F9. Front-end "relevance" sort is a longest-line contest: 80% of multi-example meanings lead with the longest lyric line

**WHAT:** `deckHits` counts, per token occurrence, tokens that are ANY deck word; with ~3.5k visible cards nearly
every Spanish token is a deck word, so deckHits ≈ sentence length, and it outranks easiness.

**ROOT CAUSE:** flashcards.js:343-350 (`getDeckWords` = every card's targetWord), :368-386 (per-token `deckHits++`,
sort `deckHits desc` before easiness).

**EVIDENCE (simulation of the exact sort, fresh-user state, over all live meanings with >=3 examples):** of 2,026
meanings, the pick is the single LONGEST line in **1,621 (80%)**; >= median length in 2,000 (99%); picked avg 12.3
tokens vs 9.1 median-candidate. Flagship cases from the 30-card sample:
- `nunca` (708823): first line = the 71-token spoken monologue from "Perdonen" ("Nunca esperen por artistas, ni
  por héroes ficticios. Ustedes son quienes tienen el poder. Enséñale a tu hijo…") — dh=60 crushes every actual
  lyric; interacts with stage1-F5 editorial/speech leakage.
- `sol` (64b1ab): "Leyenda como el Sol, sí, como el Sol de México (¡Ey, ey, ey, ey, ey…)" beats the short clean
  "Pero el sol de PR calienta má' que el de Phoenix".
This directly contradicts the repo's own design doc (`docs/design/example_selection_design.md:27` — "Longer
sentences … accumulate higher proximity scores regardless of quality" — the same failure mode, reinvented in JS;
the doc's fix (cap overlap benefit at 2-3, length penalty >12 words) was implemented only for normal-mode
build_examples, never for the artist deck path). **IMPACT:** first line on ~1,600 of ~2,000 multi-example live
meanings. × **EFFORT S** (JS-only: cap deckHits at 2-3, add length penalty).

### F10. Sort is blind to translation availability: 81 live meanings lead with a blank-English line while a translated line exists

**EVIDENCE:** simulation: 81 meanings (e.g. `bendición` 83ca4f — first line "Ma, échame la bendición (Yeah), que
yo me voy de misión (Wuh)" has NO English while both alternatives are translated; also hay, dímelo, ve, todos,
atrás…). Wave-1 counted 348 blank-EN instances; this isolates the ones the sort actively puts FIRST.
**ROOT CAUSE:** `sortExamplesByRelevance` never inspects `ex.english`; pipeline-side, the step_8b:879 hook is
inert because `tool_1b_judge_translations.py` was never run for BB (translation_scores.json absent — bug #8).
**PROPOSED FIX:** JS one-liner (blank-EN → sort last); separately, command for Josh (slow, Gemini):
`.venv/bin/python3 pipeline/artist/tool_1b_judge_translations.py --artist-dir "Artists/spanish/Bad Bunny"` to
finally materialize translation_scores.json for the step_8b hook. **IMPACT:** 81 first-lines. × **EFFORT S**.

### F11. Sample-of-30 card audit: 9/30 first examples are not the best available line

Band-stratified sample (10 head / 10 mid / 10 tail, seed 7, front-end-sim first line):
- **Selector-caused (5):** nunca (monologue first), sol (ad-lib-laden longest first), ahora (long explicit line
  over clean alternatives), bendición (blank-EN first), fui|ser (order arbitrary — all-SENTINEL).
- **Sense-fit failures (4, classification upstream but visible as "example doesn't match gloss"):**
  `di|decir` "say" — all 3 lines are dar-"gave" usages ("lo duro que yo te di") — matches Josh flag es11d6a05
  ("say#sense:0"); `como|comer` "to have for lunch" — all lines are "like" (stage6 homograph survivor);
  `negrito` "black coffee" — lines are about a person; `metido|meter` "to score" — lines are sexual/parked-at-mall.
- **Junk single-example cards (6, out of scope here — stage2/3 territory):** bé, fiber, carbone, mariana, madonna,
  gone (blank-gloss X-cards).
- Fragment-first: 0/30. Near-dup in top-3: 0/30 — and globally only 30/3,536 meanings (0.8%) still contain
  near-identical lines after the front-end's exact-string dedupe. **Chorus-dup is NOT a real problem — don't spend
  effort there.**
- Non-BB-voice first lines: not re-derived (wave-1: 32.7% of instances are non-BB voices; attribution exists in
  Gemini batch data, unused).

### F12. What a better selector should score (sketch) + estimated impact

Score per example, pick max (all data already on hand or one S-fix away):
1. **Length window** — target 6-14 tokens after ad-lib strip (kills F9; the design doc's own recipe).
2. **Translation present, quality-weighted** — blank EN = hard demote; `translation_quality` once tool_1b runs (F10).
3. **Deck-overlap capped at 2** — keep the pedagogic intent of deckHits without the length proxy.
4. **Real easiness** — personal easiness (already in JS) or fixed per-index easiness (F8).
5. **BB-voice preference** — needs the batch attribution layer surfaced (wave-1).
6. **Target-word salience** — target appears outside an ad-lib parenthetical, in the first ~10 tokens.
(No dedup work needed — 0.8%.) Semantic-fit guard (does the line embed near the sense gloss?) is the only L-effort
item and mainly papers over classification errors — lower priority than fixing those upstream.

**Estimated impact on the 30-card sample: 5/30 first-lines fixed outright (selector-caused class), plus the 81
blank-EN firsts and ~1,600 longest-line firsts deck-wide re-picked; 4/30 need stage-6 classification fixes, 6/30
need card-existence fixes (stage 2/3).** Items 1-3 are pure `js/flashcards.js` changes testable without a rebuild.

---

## Cross-stage notes
- F1/F2/F3 are the menu-side ancestors of Josh's lemma flags (perse, toítas, así→asir, denle→dense, hey) — flag
  attribution: FlaggedWords rows es146520f, es1e258b6, es1f26a35, es1f868b4, es03f3f55, es11d6a05 trace to this stage.
- F3's analysis-ordering (vezar-before-vez, "jack"-before-"cat") only bites through stage3's never-classified /
  first-menu-sense fallback — fixing stage3's gate shrinks F3's blast radius.
- The `_wikt` deck is NOT poisoned by F1/F2 (different source) but loses SD's context labels (100% → wikt has none
  comparable) — relevant to the hybrid decision (F6).
