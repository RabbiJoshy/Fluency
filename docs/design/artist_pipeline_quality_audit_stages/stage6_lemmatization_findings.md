# Stage 6 — Lemmatization (step 7a + lemma origin) — Bad Bunny live SD deck

Audit date 2026-07-16 (written after session reset). All paths absolute; probes in
`probe_lemma_census.py` (same scratchpad). Live deck = `BadBunnyvocabulary.index.json`
(11,198 rows) joined to `Artists/spanish/vocabulary_master.json` (13,700 entries).
Join yields 9,972 live cards; ~8,004 after flag filters (is_english/noise/propernoun/
cognate/interjection) — the app's visible set is a further-filtered subset of that.

---

## F0. Where lemmas actually come from (the map)

**WHAT:** Step 7a does NOT lemmatize. The lemma is the SpanishDict *headword* string
captured at scrape time; 7a only splits a surface word's sense assignments onto
`word|headword` keys by sense-ID ownership. No spaCy, no spanish_forms.json, no
Gemini involvement in choosing the lemma.

Flow for a live card (precedence order):

1. **Scrape** — `pipeline/util_5c_spanishdict.py`:
   - `fetch_spanishdict_component()` (line 296) fetches `/translate/<word>?langFrom=es`.
     The `?langFrom=es` guard is RECENT; legacy cache entries have `entry_lang: None`
     (pre-fix scrapes) and can be backwards/fuzzy-resolved.
   - `build_surface_entry()` (line 555) stores `dictionary_analyses` (each with a
     `headword`) + `possible_results` (conjugation/inflection/dictionary pointers).
   - SD itself fuzzy-resolves unknown slang: the *surface page* for `perse` returns the
     English entry **purse**; `pasándola` returns **parar/pararse**; `toítas` returns
     **torta**. Verified in `Data/Spanish/Senses/spanishdict/surface_cache.json`
     (all three have `entry_lang: None`, i.e. legacy scrape).
2. **Menu build** — `build_menu_analyses()` (`util_5c_spanishdict.py:191`): surface's own
   `dictionary_analyses` + `possible_results` redirect headwords. Only guard is
   `_is_abbreviation_mismatch` (line 142: dot-in-headword). There is NO relatedness check
   (edit distance, shared prefix, "is surface a plausible inflection of headword",
   language check). Menu = `sense_menu/spanishdict.json` (7,054 words for BB).
3. **Classification** — step 6a (Gemini flash-lite) picks sense IDs from that menu.
   Garbage menu in → garbage assignment out (`perse|purse` was assigned by
   `spanishdict-flash-lite`, i.e. Gemini dutifully classified "perse" against purse senses).
4. **Split** — `pipeline/step_7a_map_senses_to_lemmas.py:193` calls
   `split_word_assignments()` (`pipeline/util_7a_lemma_split.py:92`):
   - key = `analysis_key()` = `word|analysis.headword` (util:67–89);
   - phrasebook self-analysis folded into `known_lemmas[0]` from `word_inventory.json`
     (step_7a:60–79 + util:79–87);
   - reflexive collapse `X|Xse → X|X` (util:137–144);
   - PHRASE-only self-analysis folded into first other lemma (util:146–157);
   - **fallback when no menu**: `word|inline_lemma` (a `lemma` field stamped on the
     assignment item, e.g. by gap-fill) else `word|word` (util:125–127, 185–187);
   - unassigned examples routed per spaCy POS to an analysis (step_7a:82–163) →
     `unassigned_routing/{source}.json`.
5. **Assembly** — artist step_8b groups per menu analysis again, mints master key
   `md5(word|lemma)[:6]`, splits surface `corpus_count` across analyses proportional to
   assigned examples (`step_8b_assemble_artist_vocabulary.py:802–809` — CURRENT code;
   the live index predates this, see F2).
6. **Post-hoc curation** — `pipeline/tool_8c_patch_master_curated.py` edits the master
   `lemma` FIELD in place; the md5 key keeps hashing the OLD wrong lemma (intentional —
   preserves Josh's progress IDs). So "fixed" cards have key≠md5(word|lemma) forever.

**Artist mode never consults**: `Data/Spanish/layers/homograph_overrides.json`, the
`derivation_map` in `data/known_vocab/word_routing.json` (built by step_4a but ignored
downstream at 7a/8b — see totito in F3), or spanish_forms.json. Also note
`pipeline/build_inventory.py` referenced in CLAUDE.md doesn't exist anymore
(homograph logic now lives in `step_2a_build_inventory.py`, normal mode only).

---

## F1. Verified bug trio — all three FIXED on the live master (patched, not rebuilt)

**WHAT:** perse→purse, pasándola→parar, toítas→torta are no longer visible as wrong
glosses; the 2026-07-14 sweep (commit a0fd811, tool_8c) patched lemma+senses in place.

**EVIDENCE (live master + examples):**
- `46520f` (= md5("perse|purse")): now `{word: perse, lemma: persecución}`, gloss
  "chase, heat, trouble (police)"; example "No hay perse" / "There's no escape". Live, n=3.
- `bf72ba` (= md5("pasándola|parar")): now lemma `pasar`, gloss "to have a great time
  (pasarla cabrón/bien)"; example "To' el mundo pasándola cabrón". Live, n=2.
- `e258b6` (= md5("toítas|torta")): now lemma `todo`, gloss "all (toíta' = todita)". Live, n=2.
- Also patched: `e07d71` (= md5("mía|miar")) → lemma `mío`, gloss "mine". Live, n=142.
- Orphan cousins still in master with junk: `cdb47c` `perse|perse` has 1 sense `('X','')`
  (blank X-sense entry; not in live index, harmless but dead weight).

**ROOT CAUSE (mechanism per word):** SD's surface page fuzzy-resolved the unknown form to
the nearest dictionary entry and the scraper accepted it verbatim
(`util_5c_spanishdict.py:211–215` — surface `dictionary_analyses` are trusted as-is):
- `perse` (PR slang "police/heat", from *persecución*) → SD served the ENGLISH entry
  **purse** (legacy scrape, `entry_lang: None`, predates `?langFrom=es` at line 296–303).
  This is also brief bug #6: the menu glosses were Spanish words (cartera/bolso) —
  reverse direction.
- `pasándola` (= pasando+la clitic; step_4a routed it `classifier.conjugation`, clitic
  handling didn't peel it) → SD fuzzy → **parar/pararse**. Assigned via
  biencoder + flash-lite against the parar menu.
- `toítas` (= toditas slang) → SD fuzzy → **torta** ("cake"). Routed
  `classifier.normal_vocab`, then flash-lite classified against torta senses.

**PROPOSED FIX:** none needed for these three (patched); the CLASS fix is F3's scrape
guard. **IMPACT:** 0 remaining of the trio. **EFFORT:** done.

---

## F2. Biggest live problem: homograph "survivor" cards with full surface counts

**WHAT:** For very common ambiguous words, the live index carries ONLY the minor-verb
analysis card, stamped with the FULL surface corpus_count — so Josh's highest-frequency
cards teach the wrong meaning of the word, illustrated with example lines where the word
means something else.

**EVIDENCE (live index + master + examples, all confirmed):**

| card | live gloss | count | reality in lyrics |
|---|---|---|---|
| `96be55` para\|parar | "to stop" | **1505** | para = preposition "for" in ~all lines; card example: "Nací pa' ser millo" ("born TO be rich") shown under "to stop" |
| `74eb50` como\|comer | "to eat/have for lunch" | **754** | como = "like/as"; card example: "Como Romeo…" ("LIKE Romeo") |
| `12d87b` todo\|todos | "everyone" (lemma `todos`) | **613** | todo = "all/everything"; example "eran to' maleantes" |
| `49fed5` fue\|ser + `0a7e88` fuiste\|ser + `b342df` fui\|ser | "to be" | 149/33/62 | wikt deck lemmatizes fue/fuiste → **ir**; BB lines are mostly "went/left" |
| `67140e` puta\|puto | ADJ "fucking" | 63 | noun puta sense missing (puta\|puta in master, not in index) |
| `8e3e09` cara\|caro | "expensive" | 59 | cara = "face"; card example: "Tu cara ya nadie va a reconocerla" |
| `3feace` baja\|bajar | "to lower" | 39 | noun/adj uses exist |
| `db9ba7` camino\|caminar | "to walk" | 36 | camino = "path/way" as noun |
| `329439` cuenta\|contar | "to tell/count" | 27 | "darse cuenta" noun uses |

In every case the CORRECT card exists in the master (`d5e934` para|para, `227610`
como|como, `98f9a6` cara|cara, `eab8e8` todo|todo, `18fc11` camino|camino, `cd0368`
fue|ir…) but is **absent from the live index**. The correct-lemma assignments also exist
in `sense_assignments_lemma/spanishdict.json` (para|para: 10 flash-lite examples;
como|como: 19; cara|cara: 19; todo|todo: 19) — the data is there, the live index just
predates the code that uses it.

**Proof it's a stale-build issue, already fixed in code:** the untracked monolith
`BadBunnyvocabulary.json` (a newer local step_8b run; its meta timestamp matches the
index meta but the index content was evidently restored from git — monolith isn't
tracked, git log shows no commits for it) contains the CORRECT cards: para|para
count=1505 mfli=True, como|como, cara|cara — and NO para|parar card. Current step_8b
also splits corpus_count proportionally (`step_8b…py:802–809`), so a rebuild fixes both
the wrong card and the count inflation. But rebuild is NO-GO-gated (memory: 3 blockers),
so the live deck keeps showing these.

**ROOT CAUSE:** old build of step_8b emitted only the analysis group that had keyword
assignments and handed it the whole surface count; the known/common analysis (para=for)
produced no card. (Exact old code no longer present — current `active_groups` +
`split_count_proportionally` logic replaced it.)

**PROPOSED FIX:** (a) short-term, tool_8c-style index patch is NOT possible (index has no
gloss fields; the wrong thing is which ID is present) — the honest short-term fix is a
targeted index edit swapping the survivor ID for the correct-master-ID with a
proportional count, or patching the survivor's master senses to the dominant meaning;
(b) real fix is the gated rebuild. **IMPACT:** at least the 9 words above =
~3,200 corpus occurrences incl. 2 of the deck's top ~40 cards by count — the single most
visible lemma problem in the live deck. Cross-check: 95 words in the live deck have
SD-deck lemma sets fully disjoint from the wikt deck's (probe output), most of this class.
**EFFORT:** M (rebuild path already exists; go/no-go blockers are elsewhere).

---

## F3. SD fuzzy-match fuzz still live (the perse class, unpatched members)

**WHAT:** Beyond the patched trio, live cards still carry lemmas/glosses from SD
fuzzy-resolving slang the dictionary doesn't know.

**EVIDENCE (live cards, ranked worst-first):**
- `479370` **totito|torito** n=24, gloss "NOUN little bull". Lyrics: "Con tu totito me
  comprometí" (vulgar PR slang, diminutive of *toto*). step_4a even routed it
  `derivation_map→toto` in `data/known_vocab/word_routing.json` — but neither 7a nor 8b
  reads derivation_map; the SD menu headword `torito` won. Exact toítas→torta class,
  still live.
- `9c46d2` **cel|cal** n=17, single sense "NOUN cal" (also a reverse gloss — Spanish word
  as translation). Lyrics: "Están tirando al cel" = cell phone (celular). Method
  `spanishdict-auto`. Both wrong lemma and useless gloss, live.
- `7574ab` **rolié|reliar** n=17, "to roll up" — slang *rolear/roliar*; SD fuzzed to the
  rare verb *reliar*. Gloss semi-usable, lemma wrong (paradigm links point to reliar).
- `b0e824` **dembow|dembo** n=12, gloss "NOUN dembo" — genre name fuzzed to *dembo*;
  gloss is a non-translation.
- `cc9b09` **revol|revolt** n=10 — ENGLISH lemma "revolt" with Spanish gloss "revuelta"
  (double reverse). Slang *revol* = revolver/commotion.
- Cosmetic subclass — punctuated interjection headwords as lemmas: `1d8657` dale|**¡Dale!**
  n=122, `ed36b9` diablo|**¡Diablos!** n=58, `4c7062` uy|**¡Uy!** n=10, `cbd5eb`
  jajaja|**¡Jajaja!** (noise-flagged). Lemma strings with `¡…!` leak into lemma-mode
  grouping keys and reference links (`js/vocab.js:1266` URL-encodes the lemma).
- Defensible-but-odd: `7c8586` jeva|jevo n=20 ("girlfriend" under masculine lemma),
  `6726db` mojaítas|mojaíta n=27 (non-canonical slang lemma, harmless).

**Census numbers:** detectors over the 9,972 live cards flagged 248 word|lemma pairs
(D1 lemma-not-a-Spanish-form: 58; D2 first-two-letters differ: 128; D3 slang/diminutive
ending with different stem: 107; D4 lemma is an English dictionary word: 16 — overlapping).
Most D2/D3 hits are legitimate stem-changing conjugations (vuelvo→volver, suena→sonar) —
after removing wikt-agreeing pairs, the confirmed-wrong live set is the ~12 cards listed
here plus F2's homographs. So this class is real but bounded: ~15–25 live cards.

**ROOT CAUSE:** `util_5c_spanishdict.py` trusts SD's fuzzy-resolved surface
`dictionary_analyses` with no plausibility guard (only `_is_abbreviation_mismatch`,
line 142); legacy cache entries additionally predate the `?langFrom=es` direction fix
(line 296–303). `build_menu_analyses` (line 191) then propagates the bogus headword, and
7a/8b key everything off it. derivation_map from step_4a is computed but never consulted
at 7a/8b.

**PROPOSED FIX:** (a) scrape/menu guard: reject a surface's dictionary_analyses when the
headword shares no prefix with the surface AND the surface isn't in the headword's
inflection set (spanish_forms.json lookup is one dict access) — quarantine those into
sense_discovery instead; (b) honor `derivation_map` at menu-build/7a time; (c) one-off
tool_8c batch for the ~12 live cards above. **IMPACT:** ~15–25 live cards, several with
vulgar/slang words Josh actually encounters (totito n=24, cel n=17). **EFFORT:** S for
(c), M for (a)+(b).

---

## F4. Homograph handling in artist mode: Gemini-over-merged-menu, no override layer

**WHAT:** Artist mode resolves form→multiple-lemma ambiguity implicitly: the menu holds
ALL SD analyses (como: como/comer/comerse; mía: mía/miar/mío/míos), Gemini picks a sense
per example, and 7a routes by sense ownership. There is no ratio prior or override —
`homograph_overrides.json` and `compute_homograph_ratios()` are normal-mode only
(no artist script references them; `pipeline/build_inventory.py` in CLAUDE.md is stale).

**EVIDENCE (current assignments, 10 sampled forms):** works well where the menu is sane —
mía: 19 ex → mía|mía vs 1 → mía|mío, 0 → miar (the mía|miar LIVE card is old-build
residue, since patched); como: 19 → como|como, 1 → como|comer; para: 10 → para|para,
2 → para|parar, 3 → **para|parir** (para is not a form of parir — SD possible_results
noise absorbed 3 real examples). Weak spots: singleton misassignments (como|comer's 1
example) still mint full cards at assembly; and suppletive fue/fui/fuiste land on `ser`
via SD's tie-break (`conjugation_lemma_from_possible_results`, `util_5c_spanishdict.py:574`
prefers the dictionary-headword pointer) while the wikt deck says `ir` — the live glosses
("to be") don't match most BB usages ("se fue").

**PROPOSED FIX:** minimum-example threshold (≥2 or ≥5% of surface examples) before an
analysis mints a card; ser/ir disambiguation belongs to the classifier stage, but a
cheap prior (both-analyses-in-menu for fue/fui/fuiste) would let Gemini choose per line.
**IMPACT:** singleton-analysis cards number ~dozens; fue/fui/fuiste = 244 corpus
occurrences glossed "to be". **EFFORT:** S–M.

---

## F5. Lemma collapse in the app amplifies wrong lemmas (be97b15)

**WHAT:** In lemma mode the app keeps only `most_frequent_lemma_instance === true` cards
(`js/vocab.js:375`) and, since commit be97b15, pools example sentences from all dropped
sibling cards with the same `lemma` string (`js/vocab.js:198–204, 543–544`). A wrong
lemma therefore does double damage: the wrong card becomes the lemma's REPRESENTATIVE,
and correct forms' examples get pooled under it.

**CONCRETE LIVE EXAMPLE:** lemma `parar`. `96be55` para|parar is mfli=True (n=1505 beats
every real parar form), so in lemma mode "para — to stop" is the ONE card for parar, and
genuine parar-form cards (paró, parado…) are dropped with their lyric lines pooled onto
it — Josh sees "para / to stop" fronting a mixed pile of "for" lines and parar lines.
Inverse case: `49fed5` fue|ser (mfli=False) collapses under the ser host card, so "se
fue" ("left/went") lines are pooled as examples of *ser* "to be". Also note the patch
interaction: tool_8c edits make `lemma` strings diverge from key hashes, and pooling
groups purely on the string — patched cards (mía|mío) now correctly pool under `mío`,
which is the one place the patch mechanism works in the app's favor.

**ROOT CAUSE:** pooling keys on the master `lemma` string (js/vocab.js:198) with no
sanity link between the collapsed card's meaning and the pooled examples' usage.
**IMPACT:** every F2/F3 card that is mfli=True (para, como, todo, cara, camino, totito,
cel… — the census shows most are) is a lemma-mode representative. **EFFORT:** fixed
automatically by F2's rebuild; no separate app fix warranted.

---

## F6. unassigned_routing is near-empty — but only covers already-assigned words

**WHAT:** `unassigned_routing/spanishdict.json` holds just 4 lemma keys / 15 example
indices: ya|ya (5), lambo|lamber (7), alex|Alex (1), royce|roce (2). Note two of the four
are themselves fuzz (Lambo→*lamber* "to lick", Royce→*roce* "friction").

**What happens to them in the deck:** step_8b attaches routed indices as a SENSE_CYCLE
row only when `--remainders` is on; default is off — "cleaner cards, but unassigned
examples are dropped" (`step_8b_assemble_artist_vocabulary.py:1800`). So these 15
examples are invisible today.

**The bigger hole:** step_7a builds routing only inside
`for word in assignments.items()` (`step_7a_map_senses_to_lemmas.py:191`) — a word with
raw examples but NO assignment entry at all gets no routing key and silently vanishes
(no card, no remainder, no trace). The unassigned file being this small is not evidence
of coverage; it's evidence the loop never looks at unassigned WORDS. Quantifying the
never-assigned-word set = brief bug #2's territory (known-vocab-filtered words), flagged
here as cross-stage.

**PROPOSED FIX:** iterate `examples_raw` ∪ `assignments` in 7a so every word leaves a
trace (matches Josh's "every word needs assignment or traceable skip reason" principle).
**IMPACT:** unknown count, structural. **EFFORT:** S.

---

## Ranked worst live wrong-lemma cards (deduped, with deck glosses)

1. para|parar n=1505 — "to stop" (preposition lines) [F2]
2. como|comer n=754 — "to eat" ("Como Romeo") [F2]
3. todo|todos n=613 — "everyone" [F2]
4. fue|ser n=149 + fui|ser n=62 + fuiste|ser n=33 — "to be" (mostly "went") [F2/F4]
5. dale|¡Dale! n=122 — punctuated lemma [F3]
6. puta|puto n=63 — ADJ-only "fucking" [F2]
7. cara|caro n=59 — "expensive" ("Tu cara…reconocerla") [F2]
8. diablo|¡Diablos! n=58 — punctuated lemma [F3]
9. baja|bajar n=39 — "to lower" [F2]
10. camino|caminar n=36 — "to walk" [F2]
11. cuenta|contar n=27 — "to tell/count" [F2]
12. mojaítas|mojaíta n=27 — non-canonical slang lemma (benign) [F3]
13. totito|torito n=24 — "little bull" (vulgar slang) [F3]
14. jeva|jevo n=20 — fem. slang under masc. lemma (benign) [F3]
15. cel|cal n=17 — gloss "cal" (reverse + wrong) [F3]
16. rolié|reliar n=17 — "to roll up" wrong paradigm [F3]
17. dembow|dembo n=12 — gloss "dembo" [F3]
18. uy|¡Uy! n=10 — punctuated lemma [F3]
19. revol|revolt n=10 — English lemma, Spanish gloss [F3]
(Detector totals: 248 flagged pairs / 9,972 live cards; after removing wikt-agreeing
regular conjugations, confirmed-wrong ≈ the list above + long tail of ~10 sub-n=10 cards.)

## Cross-stage notes for the orchestrator
- F2's mechanism confirms brief bug #2's visible face on the SD deck (survivor cards),
  and the fix-in-code-but-not-in-live-index situation is a strong argument for the gated
  rebuild being the highest-leverage single action.
- 1,226 of 11,198 live index rows have NO master entry (app join drops them silently) —
  worth a stage-8/assembly check on whether that's expected post-patch attrition.
- CLAUDE.md stale ref: `pipeline/build_inventory.py` → now `step_2a_build_inventory.py`.
