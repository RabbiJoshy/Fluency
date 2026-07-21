# Stage 3 — Step 4a word routing (Bad Bunny) — findings

Audited: `Artists/spanish/Bad Bunny/data/known_vocab/word_routing.json` (schema_v2,
step_version 4, generated 2026-04-26) against the LIVE deck
(`BadBunnyvocabulary.index.json`, built 2026-05-02) + `vocabulary_master.json` +
`sense_assignments/spanishdict.json`. Probes in this scratchpad:
`probe_s3_buckets.py`, `probe_s3_coverage.py`, `probe_s3_index.py`.

Routing stats: 11,217 input words → exclude 2,313 (english 935, cognate 79,
proper_nouns 353, noise 104, low_frequency 842), classifier 8,571
(normal_vocab 3,275, conjugation 5,293, elision 3), sense_discovery 206,
clitic_merge 91, derivation_map 36.

Key architectural fact established by code trace: **routing exclusions do not
remove words from the deck.** step_8b builds a card for every inventory word and
only converts THREE of the five exclude buckets into hide-flags
(`step_8b_assemble_artist_vocabulary.py:520-537` — english→is_english,
proper_nouns→is_propernoun, noise→is_noise). `exclude.cognate` and
`exclude.low_frequency` produce **no flag at all**. Meanwhile step_6c skips ALL
exclude.* buckets from classification (`step_6c_assign_senses_gemini.py:712-725`).
Net contract violation of the filter-design principle ("filters determine
METHOD, not deck inclusion"): two buckets get *no method AND no exclusion*.

---

## F1 — exclude.cognate is a ghost bucket: 71 of 79 curated cognates are fully visible cards with Gemini-invented (gap-fill) glosses  [CONFIRMED]

**WHAT:** Words Josh curates into `Artists/curations/cognates.json` drop get
excluded from classification but NOT from the deck — they surface as normal
cards whose senses were invented by gap-fill.

**EVIDENCE:** 71/79 exclude.cognate words are visible (unflagged, in index +
master): baby(cc=613 — the highest-frequency junk card in the deck), flow(121),
mambo(48), trap(42), chalet(41), polaroid(32), blunt(26), party(26), haters(25),
combo(22), sorry(16), ticket(16), okay(13), shot(13), light(11)… All carry only
`gap-fill` in `sense_assignments/spanishdict.json`; e.g. shot → NOUN "a small
drink of liquor", light → PROPER_NOUN "A brand name or nickname…". Master
flags for all of them: `{}` (no is_english/is_transparent_cognate). Josh flagged
five of exactly these cards in FlaggedWords (whatsapp es1efef8b, haters
es11eac4f, light es16a3dc0, okay es1b4f819, shot es10f1ec2) — i.e. the curation
he'd expect to fix them has zero live effect.

**ROOT CAUSE:** (a) `step_8b_assemble_artist_vocabulary.py:528-537` builds flag
sets only for english/proper_nouns/noise — cognate bucket ignored; the only
cognate path is the *shared score layer* at lines 1240-1251, which most of these
loanwords aren't in. (b) Assignments are incremental and never cleaned: the
gap-fill senses predate the curation (step_6c would skip these words now, but
their old assignments persist and the builder happily uses them).

**PROPOSED FIX:** In step_8b, stamp exclude.cognate words (e.g.
`is_transparent_cognate: true` or `cognate_score: 1.0`) the same way english/
noise/propn are stamped; add an assemble-time (or tool) sweep that drops stale
assignments for words currently in exclude.* buckets.

**IMPACT:** 71 visible junk cards incl. the deck's #1-frequency non-word (baby,
cc 613); explains ≥5 of Josh's flags. **EFFORT: S**

---

## F2 — cognate_score dormant-junk bug quantified: a rebuild would newly hide 695 currently-visible cards, including every form of estar  [CONFIRMED, quantifies known bug #1]

**WHAT:** Zero live index entries carry `cognate_score` today (probed: 0 of
11,198), so the front-end cognate filter is inert for BB. On any fresh step_8b
run, the shared layer stamps scores and — with the default
`excludeCognates: true` + threshold 0.85 (`js/state.js:50,52`) — 695 cards that
are visible today silently disappear.

**EVIDENCE:** `Data/Spanish/layers/cognates.json` (10,247 entries):
`estar|estar → {"score": 1.0, "cognet": true}` (junk — estar≠star), and the
would-hide top by corpus count is dominated by estar's paradigm: está(373),
estoy(352), estás(191), estamos(115), están(88), estar(59), estaba(38); plus
mucho(67, 0.89), pasa(53, 0.86), importa(45, 0.92), tranquilo(43)/tranquila(42)
(0.94), primero(40, 1.0), encanta(37), hombre(22, 0.91), grande(27, 0.92),
mueve/mover/mueves (0.89), besos(32, 1.0), oro(23, 1.0)… Total: 695 visible
cards with score ≥ 0.85.

**ROOT CAUSE:** Junk scores originate in `pipeline/step_7c_flag_cognates.py`
(suffix/similarity scorer + CogNet voter — CogNet links estar via "star"-family
noise). Stamping site: `step_8b_assemble_artist_vocabulary.py:1240-1251`. The
live index predates the layer, so the bug is dormant until rebuild.

**PROPOSED FIX:** Before the next rebuild: audit the layer for function
words/copulas/high-frequency verbs (blocklist or cap scores for the top-N
frequency band); add a build-time "would-hide diff" report so a rebuild prints
which previously-visible cards a stamped score now hides.

**IMPACT:** 695 of 3,951 default-view cards (~18%) would vanish on rebuild —
deck-breaking, and invisible until Josh notices estar is gone. **EFFORT: M**

---

## F3 — Known bug #2 quantified on the LIVE SD deck: 326 default-view cards (8.3%) have no classifier assignment; the a→"bishop" equivalents are the gap-fill cards  [CONFIRMED]

**WHAT:** Cards reach the deck without any real WSD pass; their gloss is either
a Gemini gap-fill invention or blank.

**EVIDENCE (default view = corpus_count>1, unflagged; hideSingleOccurrence
defaults true in `js/state.js:54`):** 3,951 cards total → 3,415 classified
(spanishdict-flash-lite/biencoder), 210 auto/keyword (benign-ish:
`spanishdict-auto` = single-sense menus), **297 gap-fill-only**, **29 blank
X-cards** (master senses = `[{"pos":"X","translation":""}]` — card with an empty
translation). Worst 25 unclassified by corpus count: baby(613), dos(133!),
flow(121), mambo(48), lean(45), trap(42), chalet(41), polaroid(32), bichote(29
— PR slang, real vocab), blunt(26), party(26), haters(25), combo(22), toto(18),
champaña(16), sorry(16), ticket(16), condones(16!), break(15), reggaetón(15),
oasis(15), atreves(14!), okay(13), shot(13), cherry(13). Note dos, condones,
champaña, atreves, bichote are REAL Spanish that ended up gap-fill-only
(SD menu gap, not routing error — but same user-visible symptom).
Full-deck numbers (incl. cc=1): 8,467 unflagged join-able cards, 3,195 without a
classifier method, of which 2,461 are blank X-cards (2,509 of the X-cards sit at
cc=1 and are hidden ONLY by the display toggle — see F4).

**MECHANISM (precise code path):** step_4a excludes or step_6c skips → word has
no assignments → step_8b else-branch
`step_8b_assemble_artist_vocabulary.py:1137-1161` fabricates ONE meaning
`{pos:"X", translation:"" (or curated), frequency:"1.00"}` with only the first
raw example; if gap-fill ran, invented senses become the card
(`sense_frequencies=[1.0]` piles everything on the invented first sense).
Front-end `joinWithMaster` (`js/vocab.js:91-115`) keeps any sense with freq>0 —
there is no "unclassified" gate. Live index carries no `sense_methods` /
`unassigned` keys at all (probed: 0 of 11,198), so the app cannot even style
these differently.

**PROPOSED FIX:** (a) builder: don't emit blank X-meanings for visible words —
either flag the entry (`unassigned:true` already exists in newer builder code
but the live index predates it) or suppress; (b) periodic "unclassified visible
cards" report ranked by cc as a release gate.

**IMPACT:** 326 default-visible cards; the top of the deck (baby at cc 613, dos
at 133) is in this class. **EFFORT: M** (mostly rebuild + report)

---

## F4 — exclude.low_frequency is also a ghost bucket: 839 excluded words became (blank) cards guarded only by a UI toggle  [CONFIRMED]

**WHAT:** The freq<2 floor (step_4a Phase 5, `--min-freq` default 2) routes 842
words to exclude.low_frequency; 839 of them are in the live index as unflagged
X-blank cards. Nothing in the data excludes them — only the front-end
`hideSingleOccurrence: true` default keeps them out of view; toggling it OFF
(a visible settings switch, `js/ui.js:1345-1349`) surfaces hundreds of blank
cards (a'lante, abandone', acostumbra'u, alqaedas, sayayines, …).

**ROOT CAUSE:** step_8b builds flag sets only for 3 of 5 exclude buckets
(`:528-537`); low_frequency words still flow through inventory → card, and the
freq floor coincidentally aligns with the cc>1 UI filter.

**PROPOSED FIX:** Treat low_frequency like noise in step_8b (flag), or drop from
inventory at step_5a.

**IMPACT:** Latent 839 blank cards one toggle away; sample counts in every
"deck size" stat. Bucket content itself sampled clean (0 of 842 in
spanish_forms — real Spanish freq-1 words correctly survive via Phase 2).
**EFFORT: S**

---

## F5 — step_6c's english_loanwords.json skip blocks classification of 138 classifier-routed BB words, including real Spanish  [CONFIRMED]

**WHAT:** On top of routing, step_6c adds the 1,606-entry
`Data/Spanish/layers/english_loanwords.json` to its skip set
(`step_6c_assign_senses_gemini.py:743-765`), overriding step_4a's routing
decision for words the routing had sent TO the classifier.

**EVIDENCE:** 138 classifier-bucket BB words are in the loanword layer; 67 never
got any assignment, 47 got only gap-fill/other. Top by freq: bichote(29 — PR
slang "drug kingpin", not an English loanword; got a gap-fill card), vip(24),
dj(20), jet(15), dembow(12 — reggaetón genre word!), panty(11), man(10),
like(10), motel(10), tenis(9), gol(9), estrés(8), video(8), club(7), gasolina(6),
yate(6), ron(4), líder(3), internet(4), josear(4), surfear(5) — most of these
are fully naturalized Spanish (gol, gasolina, ron, líder, estrés, tenis, video
are in any Spanish dictionary). The layer itself contains outright errors
("aberración" is listed). This contradicts both the "one source of truth"
principle in step_4a's header and the filter-design rule (method, not
inclusion) — and the corresponding front-end flag `is_english_loanword` is never
stamped by step_8b (grep: no hits), so the layer only *blocks classification*
without ever *hiding* anything.

**PROPOSED FIX:** Remove the layer from step_6c's skip set (routing already
handles English via spanish_forms + en_50k), or intersect it with
`not in spanish_forms` before skipping.

**IMPACT:** 138 words, several Josh-relevant slang/naturalized terms stuck with
gap-fill or nothing (bichote, dembow, gasolina). **EFFORT: S**

---

## F6 — Noise curation kills real high-frequency Spanish: ya(722), he(90), ha(72), tá(56), ma(30), to(29)  [CONFIRMED]

**WHAT:** `Artists/curations/noise.json` drop contains real words; the keep
section only protects {a, o, y, e, u}.

**EVIDENCE:** noise bucket top-freq: ey(844), **ya(722)**, yeh(465), eh(349),
yeah(251), oh(140), **he(90)**, ah(81), je(79), **ha(72)**, **tá(56)**…
- **ya** — core adverb ("already/now"), corpus_count 722; it has NO master entry
  at all (`ya|ya` id b2e6a5 absent from index and master) — the word is simply
  missing from the deck.
- **he / ha** — auxiliary haber (yo he / él ha), spanish_forms tags both as
  verb; both exist in master as blank X-cards with `is_noise: true` (senses
  `['X:']`). Josh flagged "ha" (es0f71c2a, complaint about its haber senses on
  an earlier build — the "fix" appears to have been noise-curating it away).
- **tá(56) / ma(30) / to(29)** — elision surfaces of está/mamá/todo dumped as
  noise instead of being elision-merged.

**ROOT CAUSE:** Phase 1a (curated noise) runs before the Phase 2 Spanish check
(`step_4a_filter_known_vocab.py:323-329`), so curation always wins; drop list
was populated over-broadly; keep list too narrow.

**PROPOSED FIX:** Move ya/he/ha (and arguably ay) to noise.json keep; route
tá/ma/to through the elision pipeline instead of noise.

**IMPACT:** A top-30-frequency word (ya) absent from the deck; 2 haber
auxiliaries blanked. Small count, high visibility. **EFFORT: S**

---

## F7 — clitic_merge: wrong and inconsistent bases (91 entries, ~15 problematic)  [CONFIRMED in live routing; code partially fixed since]

**WHAT:** The live routing's clitic merges point at a mix of infinitives,
bare imperatives, gerunds, subjunctives, infinitive+clitic forms, and one
English word.

**EVIDENCE (live word_routing.json clitic_merge):**
- **delete → dele** (freq 1): English "delete" in a lyric, split as
  d(é)+le+te; "dele" isn't even in today's conjugation_reverse.json, and has no
  master/inventory entry, so step_8b's guard (`:557 if not base_entry:
  continue`) silently no-ops the merge.
- **siénteme → sentar** (freq 3): BB context is sentir ("feel me"), but
  `conj_reverse["siente"][0].lemma == "sentar"` and strip_clitic takes
  `entries[0]` (`pipeline/artist/step_4a_filter_known_vocab.py:207`) — the
  first-entry lemma pick is arbitrary for sentar/sentir-type collisions. Same
  error class as Josh's flags sentirse#lemma (es143fa51), dejarse#lemma
  (es1531b73).
- **Inconsistent target types:** trépate→trepa, chequéate→chequea,
  arrópame→arropa, vírate→vira, dévorame→devora, sóbate→soba, lámelo→lame
  (surface imperatives); fumárselo→fumarse, rompértelo/rompértela→romperte,
  mamártela→mamarte, bájatelo→bájate, tumbármelo→tumbarme (bases that are
  themselves clitic forms — Josh flagged fumarse#lemma es199b369);
  stalkeándote→stalkeando, roncándome→roncando, pichándole→pichando (gerunds);
  actualícense→actualicen, adáptense→adapten (3pl forms); dimelo→dime (base is
  itself an unmerged clitic form); papele→papar, copiete→copiar, peguete→pegar
  (dubious slang splits). Today's strip_clitic returns `entries[0].lemma`, which
  cannot produce surface bases like "trepa" — so the live file predates the
  current code, and **a rebuild will silently re-target ~30 merges**
  (provenance concern per Josh's rules).

**MISSES:** dime (freq 297) is verb-only in spanish_forms and lives in the
conjugation bucket un-merged (and currently has NO master entry at all — see
F11); vámonos(30) unclassified. Artist mode writes clitic_keep/orphans as empty
by design, so there's no tier-3 for these.

**PROPOSED FIX:** In strip_clitic, when the base has multiple lemma analyses,
pick by inventory presence / corpus count rather than `entries[0]`; normalize
all targets to infinitive; assert every merge target exists in the inventory at
routing time (fail loudly instead of step_8b's silent `continue`).

**IMPACT:** 91 words; ~15 wrong or unstable, mostly low-freq but includes
user-flagged lemma errors. **EFFORT: M**

---

## F8 — derivation_map: wrong bases, name leakage, and missed Caribbean diminutives  [CONFIRMED]

**WHAT:** 36 mappings; ~6 wrong, plus systematic misses.

**EVIDENCE:**
- **perfumito → perfumo** (should be perfume): rule `("ito", 3, ("o","e",""))`
  tries ending "o" first (`pipeline/util_4a_routing.py:229`) and "perfumo"
  (verb, 1sg of perfumar) is in spanish_forms, shadowing "perfume" (noun).
- **callaito → callao**: callaíto="quiet(ly)" (callado); spanish_forms tags
  callao as adj,name,noun (El Callao / stone) — wrong headword for the lyric.
- **Name diminutives become cards:** jaimito→jaime, nandito→nando,
  rolandito→rolando, julito→jul — bases are `name` (or noun "jul") in
  spanish_forms; these should land in proper_nouns, not derivation.
- **Misses:** vowel-elided diminutives mojaítas(27), callaítas(7) have no
  matching rule (-aíta/-aíto family) and fell to sense_discovery, where invented
  senses/lemmas produced the toítas→torta-class garbage Josh flagged
  (es1e258b6).

**PROPOSED FIX:** Prefer non-verb bases when multiple candidates exist; skip
derivation when the base is name-only; add -aíto/-aíta (and -ío/-ía participle
elision) rules.

**IMPACT:** Small counts but includes one flagged card class. **EFFORT: S**

---

## F9 — is_propernoun_corpus hides 50 real Spanish words on the LIVE deck and bypasses the proper_nouns.json keep list  [CONFIRMED data; tool internals need 1 check]

**WHAT:** Beyond step_4a's 353 propn exclusions, master entries carry a
`is_propernoun_corpus` flag (stamped by `pipeline/tool_8a_stamp_propernoun_corpus.py`)
and the front-end hides on EITHER flag (`js/vocab.js:361`). The curation keep
list protects words from step_4a only — not from this flag.

**EVIDENCE:** 61 live cards hidden via is_propernoun_corpus; 50 have non-name
POS in spanish_forms: **dios(140), puerto(53), conejo(40)** (rabbit — obviously
capitalized as "Conejo Malo" in lyrics), **paciencia(16)**, don(20), pin(12),
light(11), retro(10), condado(7), cristo(5), chile(5), maría(5), curry(6),
mercedes(30), victoria(9)… — dios, don, condado, cristo, santa are explicitly in
`Artists/curations/proper_nouns.json` **keep**, yet hidden anyway. (The legacy
`data/layers/detected_proper_nouns.json` from the old cap-ratio detector is
garbage-quality — lists borracho, paciencia, navidad, gasolina as propn and
chambea/chulo/cuchara as "english" — worth deleting or archiving so nothing ever
re-consumes it.)

**PROPOSED FIX:** Make tool_8a respect proper_nouns.json keep (and probably a
frequency guard: never corpus-flag a word with a non-name Wiktionary POS and
cc≥20).

**IMPACT:** 50 real-word cards invisible today (dios at cc 140 is the worst).
**EFFORT: S**

---

## F10 — exclude.english bucket itself is healthy; the leak is the reverse direction via spanish_forms loanword headwords  [CONFIRMED]

**WHAT:** Sampled 30 random + top-30: the 935-word english bucket contains no
real Spanish victims — only 1 word overlaps spanish_forms ("bang", curated), and
the son/dime/ten/mama/primo class is safely in classifier buckets (Phase 4
requires `not in spanish_forms`, step_4a:489). The actual quality hole is
English junk that *enters the deck* because es-Wiktionary has loanword
headwords: hey(7), down(6), out(7), play(7), cherry(13), panty(11), millo(13),
pos(7) all routed to classifier.normal_vocab (`source=spanish_forms`) and became
cards — Josh flagged every one of these (es03f3f55, es19cb252, es17eb594,
es1f38ee0, es11a7731, es11a51e9, es1c7a231, es1fb6b49). Where no SD menu
existed, gap-fill invented glosses (down → "Feeling sad, depressed…").

**ROOT CAUSE:** Phase 2 treats spanish_forms membership as sufficient
Spanish-ness; no review path for words in BOTH spanish_forms and en_50k.

**PROPOSED FIX:** Emit a small review report (spanish_forms ∩ en_50k ∩ corpus,
ranked by cc) per artist run; resolution stays curation (cognates.json /
extra_english) — but note curation only works once F1 is fixed.

**IMPACT:** ~8 flagged cards of this class on the live deck; recurring per
artist. **EFFORT: S**

---

## F11 — Cross-stage observation for the orchestrator: 1,226 of 11,198 live index ids (11%) dangle — no master entry — so those cards silently vanish at join time  [CONFIRMED data; ownership belongs to master-patch/builder stage]

**EVIDENCE:** joinWithMaster drops ids missing from master (`js/vocab.js:88
if (!m) continue`). 1,226 index ids have no master key, including cc=862,
dime|dime (a49c83, cc=300), and ids matching Josh's flag list: f26a35 (así),
0eb26f (bebé), 03d6c1 (nadar), 1d6a05 ("say"). Master mtime 2026-07-14
(a0fd811 tool_8c sweep) vs index 2026-05-02: patching master re-keys/deletes
`md5(word|lemma)` entries without rebuilding the artist index, so every
lemma-fix orphans the corresponding live card. Some of that is intended
(deleting junk), but dime/bebé/así are real words that now show NO card.
Recommend the tool_8c/builder stage verify which of the 1,226 were deliberate.

---

## Notes / minor

- **sense_discovery (206)** is dominated by elision leftovers step_3 missed:
  to'as(47), to's(35), vamo(13), tán(11), ójala(12), metíos(10), exagerao(8),
  jodíos(6), bendecíos(3) — these are where the Gemini-invent + lemmatizer-fuzz
  garbage (to's→tos, ójala→ojalar, perse→purse; Josh flags es1a47070, es17d43b4,
  es146520f, es13526ec) is manufactured. Fix belongs to step_3/elision coverage
  (add -ao/-ío participle and to'+clitic patterns), not step_4a proper.
- **exclude.proper_nouns (353)** sampled clean in both halves (curated 170,
  wikt_all_propn 183): real names/brands; worst nits are junk-but-harmless
  entries (at, bm, ap). The capitalized-at-line-start victim class is gone from
  step_4a itself (no cap heuristics anymore) — it survives only via the legacy
  corpus flag (F9).
- **word_routing_debug.json** trail (bucket/source/freq per word) made this
  audit cheap — worth keeping.
- Timestamp sanity: routing meta 2026-04-26, index meta 2026-05-02 → the live
  deck WAS built from the current routing file; code has drifted since (F7
  provenance risk on rebuild).
