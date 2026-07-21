# Stage 2/3 findings — tokenization, elision merging, ad-lib stripping (Bad Bunny live deck)

Audit date 2026-07-16/19. All counts from probes against the live data
(`BadBunnyvocabulary.index.json` 11,198 rows; simulated front-end default filter
reproduces **3,491 visible cards** — vocab.js:301-380 logic with default toggles).
Probe scripts in this scratchpad: `probe_tokenizer.py`, `probe_inventory.py`,
`probe_visible.py`, `probe_examples.py`, `probe_leading_apos_counts.py`.

Data freshness note: `vocab_evidence.json` is step-2a **v3** (2026-04-26);
`vocab_evidence_merged.json` (step 3a v5) is dated 2026-04-20 but was built from a
v3-count evidence file (fa12827 rebuild already ran v3; the 04-26 rerun 69942f2 only
changed n-gram canonicalization for MWE detection). So the live inventory reflects
current tokenizer logic — no staleness discount on the findings below.

---

## F1 — Leading-apostrophe elisions are beheaded at tokenize time; three live cards teach the wrong word, and the "e" card's evidence is ~90% wrong

**WHAT:** `WORD_RE` (step_2a_count_words.py:72: `[LETTERS]+(?:'[LETTERS]+)*'?`) allows
internal and trailing apostrophes but NOT leading ones, so Caribbean aphesis forms
lose their elision marker: `'tamos`→`tamos`, `'taba`→`taba`, `'tá`→`tá`, `'e`→`e`,
`'el`→`el`, `'onde`→`onde`. Downstream, the beheaded token collides with (or is
looked up as) an unrelated real word.

**EVIDENCE (real BB, live deck):**
- Card `4cecaf` word **tamos**, lemma **tamo**, sense `NOUN "fluff"` — VISIBLE, n=17.
  Its own examples: *"To' los mío' están bien, **'tamos** bien"* (Estamos Bien — the song
  title is literally the full form), *"**'Tamos** fumando como do' hippie'"*. The card
  teaches "fluff"; every example means "we are".
- Card `b83ec5` word **tamo**, lemma tamo, `NOUN "fluff"/"chaff"` — VISIBLE, n=11.
  Example: *"Tú y yo **'tamo** envuelto' en el bellaqueo"*.
- Card `68124b` word **taba**, lemma taba, `NOUN "jacks"/"ankle bone"` — VISIBLE, n=8.
  Example: *"Antes **'taba** preso dentro de la casa"* (= estaba).
- Card `0fbda0` word **e**, `CCONJ "and"` — VISIBLE, n=234, high rank. Corpus probe:
  of 244 matches, **224 are `'e` (= de)** and only ~20 are the real conjunction.
  9 of its 10 examples_raw lines are `'e`=de: *"los hijo' **'e** puta de Bayamón"*,
  *"las tazas **'e** café"*, *"fuera **'e** la cama"*. Card says "and"; evidence says "of".
- `'el` (= del): 36 occurrences silently absorbed into **el** (n=2,327) — e.g.
  *"Tengo al abogado **'el** diablo"*.
- Hidden-but-stranded: `tá` (56), `tán` (11, later gloss-patched to "are ('tán = están)"
  via curation), `ta` (4), `onde` (4) — ~107 estar-family occurrences never reach
  the está/están/estaba/estamos cards' counts or examples.
- Contrast: `'toy` (47) is fine ONLY because elision_mapping has a manual
  `toy → estoy` entry; the same fix was never added for tá/taba/tamo/tamos/tán/e/el.

**ROOT CAUSE:** pipeline/artist/step_2a_count_words.py:72 (`WORD_RE` regex) discards
the leading apostrophe, destroying the elision signal before step 3a can act;
Artists/curations/elision_mapping.json has no entries for the beheaded surfaces
(and cannot distinguish `'e`=de from `e`=and once the marker is gone).

**PROPOSED FIX (sketch):** capture the leading apostrophe in WORD_RE
(`'?[LETTERS]+…`), keep it on the token (`'tamos`), then: (a) add elided_only
mappings `'tamos/'tamo→estamos`, `'tá→está`, `'tán→están`, `'taba→estaba`,
`'toy→estoy`, `'onde→donde`, `'e→de`, `'el→del`; (b) bare `tamos/taba/tá` become
count-0 and drop out. `'e` vs `e` disambiguation becomes trivial once the marker
survives. Needs a step-2a→3a→…rebuild (the known cognate-stamping rebuild hazard
applies — coordinate with that fix).

**IMPACT:** 4 visible cards actively wrong (tamos, tamo, taba + the n=234 "e" card
whose gloss mismatches ~96% of its evidence); ~150 corpus occurrences of estar/de
misrouted; "e" is a high-frequency card Josh sees early. × **EFFORT: S-M**
(regex + ~8 mapping entries + rebuild).

---

## F2 — The auto-generated part of elision_mapping.json contains junk canonical targets that hard-code wrong merges

**WHAT:** Many `same_word_dup`/auto entries carry nonsense `target_word`/`target_lemma`
that lock elided forms onto fake words instead of their real full forms.

**EVIDENCE (Artists/curations/elision_mapping.json):**
- `{"elided_word": "tamo'", "full_word": "tamos", "target_word": "tamos", "target_lemma": "tir"}`
  — merges `tamo'` into the beheaded junk form "tamos" with fabricated lemma **"tir"**.
- `{"elided_word": "feli'", "target_word": "felis", "target_lemma": "feli"}` — feliz
  ("happy") elision canonicalized to **"felis"** (the cat genus; not a Spanish word).
  Live master has BOTH `cc8575 felis|feliz ADJ "happy"` (curation-patched) and
  `0770f9 felis|felis X ""` — the headword Josh sees is still the misspelling "felis".
  Example line: *"Y tú mereces ser feli'-i'-i'-i'"*.
- `{"elided_word": "ta'", "target_word": "tas", "target_lemma": "ta"}` (= está').
- `{"word": "na", "target_word": "na", "target_lemma": "nir"}` — bare `na` (= nada)
  kept separate with fabricated lemma "nir" instead of merging to nada.
- `{"word": "to's", "target_word": "to's", "target_lemma": "to"}` and
  `{"word": "to'as", "target_lemma": "to'ir"}` — to's survives as its own VISIBLE card
  (n=35) with a hand-curated gloss instead of merging into todos.
- File stats: 971 of 2,871 entries are `same_word_dup`; the junk lemmas above all come
  from that auto-generated batch.

**ROOT CAUSE:** the generator that produced elision_mapping.json inferred
target_lemma by naive suffix-stripping (tamos→"tir", na→"nir", feli'→"feli") and
nobody audited the tail; step 3a (`load_merge_targets`, step_3a_merge_elisions.py:394)
trusts the file verbatim.

**PROPOSED FIX:** one-shot audit script: flag every mapping entry whose
`target_word` or `target_lemma` is absent from `Data/Spanish/vocabulary.json` /
spanish_forms.json; hand-fix the ~dozens of hits (tamo'→estamos, feli'→feliz,
ta'→está, na→nada, to's→todos…). Curated-overrides rule applies: fix targets,
never delete rows. **IMPACT:** at least 3 visible cards (felis, to's, + tamos via F1)
plus a trail of junk lemmas ("tir", "nir", "to'ir") that later stages lemma-map
against. × **EFFORT: M** (audit script + rebuild).

---

## F3 — 187 apostrophe forms survive unmerged in the inventory; the trailing-apostrophe restorer and the "double elision" rule both miss their documented cases

**WHAT:** After step 3a, 187 apostrophe-bearing forms remain as their own inventory
entries (probe_inventory.py). Only 1 is visible (`to's`, see F2) — the rest are
hidden by the no-translation/single-occurrence filters — but they pollute master
(each got an id, a sense-menu lookup, classification budget) and their counts/
examples never reach the real word's card.

**EVIDENCE:**
- Unaccented d-elisions FAIL: `meti'o, meti'a, prendi'o, perdi'o, amaneci'o, vesti'o,
  lambi'a` — D_ELISION_RULES (step_3a_merge_elisions.py:276-285) only match accented
  `í'o/í'a`; lyrics usually omit the accent. Verified:
  `d_elision_canonical('parao') → None`.
- `double_elision_canonical` is dead code for its own docstring case: it strips the
  trailing `'` then calls d_elision on a now-apostrophe-less stem (`parao'`→`parao`,
  which `(.+)a'o$` can never match). Verified live: `double_elision_canonical("parao'")
  → None`; only the never-occurring `burla'o'` shape works. Inventory still holds
  `parao'` (3), `yao'` (4).
- Trailing-apos restore misses plurals of ordinary nouns because its known-set is
  `Data/Spanish/vocabulary.json` headwords (lemma-level): `notificacione'`,
  `imperfeccione'`, `virtude'`, `cojine'`, `fechoría'` all stay unmerged (restoring
  +s yields a plural that isn't a headword). step_3a_merge_elisions.py:376-391.
- First-person-plural verbs with s-elision (`rompemo'`, `prendimo'`, `seteamo'`,
  `derrumbamo'`, `estuviésemo'`…) fail the same way (conjugated forms not in the
  headword list) — ~15 of the 187.

**ROOT CAUSE:** step_3a_merge_elisions.py:276-285 (accent-only patterns), :360-374
(double-elision ordering bug), :419-427 (`load_known_vocab` uses headwords, not a
full-form list — `conjugation_reverse.json` and `spanish_forms.json` already exist
and would cover these).

**PROPOSED FIX:** add unaccented `i'o/i'a(+s)` rules; fix double-elision to apply
d-elision-with-optional-apostrophe on the stripped stem; use spanish_forms.json
(821k forms) as the restore known-set instead of vocabulary.json. **IMPACT:** ~170
junk master entries and lost example/count mass (mostly count 1-4 each; the visible
harm is indirect — wasted classification calls and inventory noise on every rebuild).
× **EFFORT: S** each, M together.

---

## F4 — Bare (apostrophe-less) elided spellings leak through: visible `pa` NOUN card and `pal` card

**WHAT:** multi_word_elisions.json and elision_mapping.json key on apostrophe
spellings, but Genius transcribers often write the elision with no apostrophe.

**EVIDENCE:**
- Card `c7efca` word **pa**, lemma pa, senses `NOUN "for"/"to"/"by"` — VISIBLE, n=35.
  Example: *"no es **pa** mirarlo es pa' comerse"* (same line contains both spellings;
  the `pa'` went to para, the bare `pa` stayed). A preposition taught as a NOUN.
- Card `a924e2` word **pal**, `PREP "for the (pa'l = para el)"` — VISIBLE, n=2:
  the map has `pa'l` and `pal'` but not bare `pal`, so it survived and later needed
  a hand-curated gloss (glued two-word token as a card).
- Same class, hidden: `na` n≈? (F2, junk lemma "nir"), `e'tos` (= estos, count 1),
  `toa`/`toas` (curated-patched "all (toa' = todas)").
- VERIFY item from the brief: Artists/CLAUDE.md:154 says multi_word_elisions.json is
  "**Not yet wired into step 2a**" — this is STALE. step_2a_count_words.py:1041 loads
  it and applies it (v2+ per STEP_VERSION_NOTES; live evidence is v3). Verified live:
  `pa'l → para + el` with surface preserved (probe_tokenizer.py output), and `pa'l`
  is absent from the inventory. The doc should be corrected; the remaining damage is
  the bare-spelling gap above, not missing wiring.

**ROOT CAUSE:** coverage gap in Artists/curations/multi_word_elisions.json ("pal")
and elision_mapping.json ("pa", "na" handled wrongly per F2).

**PROPOSED FIX:** add `pal → para el` to multi_word_elisions; add elided_only
entries `pa→para`, `na→nada` (safe: bare "pa"/"na" are never anything else in this
corpus — 35/35 sampled pa lines are para). Fix Artists/CLAUDE.md:154. **IMPACT:**
2 visible artifact cards (one glossed as the wrong POS), plus doc correctness.
× **EFFORT: S**.

---

## F5 — Ad-lib and fragment debris still reaches visible flashcard examples

**WHAT:** strip_adlibs removes parentheticals for COUNTING but examples keep the raw
line (by design), and the ≥5-token quality gate has a fallback that hands pure ad-lib
lines to words that have no better line.

**EVIDENCE (live examples on the 3,491 visible cards; probe_examples.py):**
- 129 of 15,020 example lines (0.9%) are ≥50% ad-lib/debris tokens.
- **37 visible cards' FIRST example** is ≥50% ad-lib, e.g. `bla` (card glossed
  `NOUN "b"`, lemma "b"!): *"Bla, bla, bla, bla, bla, bla"*; `squirteé`: *"Y squirteé
  y squirteé y squirteé"*; `mamacita`: *"Mamacita (Rra, rra)"*; `conozco`: *"Esa
  actitud la conozco ya (Yeah-yeah-yeah)"*.
- 66 visible cards' first example has ≤3 word tokens (`ajá`: example line is just
  *"Ajá"*, English side *"Me, Yaviah, ah"* — a misaligned translation to boot; that
  card is also mislemmatized ajá→ajar `VERB "to wither"`, n=12 — same
  slang-lemmatization class as known bug #7).
- Fragments: 26 first-examples end mid-clause on a connector (*"La disco está llena,
  pero"*, *"Ahora vivo mejor… porque"*) — lyric lines genuinely end there; minor.
- Glued prose: 7 visible cards share one 3-sentence Genius speech paragraph as first
  example (*"Nunca esperen por artistas, ni por héroes ficticios. Ustedes son…"*,
  song id in examples_raw ~ "El Apagón" speech section) — the line-splitter treats a
  prose paragraph as one line.
- Inventory-side debris that survived tokenization: single letters `r`(43) `g`(35)
  `j`(32) `t`(27) `p`(26)… 25 total (from "T.B.T."→`t,b,t`, "P.R.", spelled-out
  brands); `ey` 844, `yeh` 465, `eh` 349, `yeah` 251, `brr` 27, `rra` 6 — all get
  master ids and sense lookups even though flags hide them from the deck.

**ROOT CAUSE:** step_2a_count_words.py:599-606 (fallback assigns the best line even
when it fails `is_good_context_line`); :384-391 (repetition check only fires at ≥6
tokens/≤2 uniques, so "Bla, bla, bla, bla, bla, bla" passes as 6/1 — wait, it IS
6/1, but the fallback path bypasses the check entirely for words whose only lines
are bad); single-letter tokens have no min-length gate in WORD_RE.

**PROPOSED FIX:** (a) drop the fallback for words whose only surviving lines are
<3 tokens or ≥50% ad-lib — better no example than a "Bla, bla, bla" example (but per
Josh's preserve-examples preference, make it a filter at 8a-assemble time, not a
re-pick); (b) min-length-2 gate on tokens (keep whitelisted `y,a,e,o,u`); (c) split
prose paragraphs on sentence enders before line iteration. **IMPACT:** ~100 visible
cards with a junk first example (the card face Josh actually reads); ~40 junk master
entries. × **EFFORT: S-M**.

---

## F6 — MWE detection: curated layer is sound; PMI layer is chorus-echo noise with debris; one systematic miss class

**WHAT/EVIDENCE (data/word_counts/mwe_detected.json, current v3 run: 79 curated /
115 PMI / 459 patterns):**
- Curated top-10 all real (`voy a` 347, `para que` 172, `es que` 156…). Elision
  canonicalization works (`pa' que` finds the para-que bucket).
- PMI top-15: mostly whole repeated chorus lines, not lexical MWEs: *"vamos a
  hacerlo otra vez"*, *"sin ti me va mejor"*, *"dile que tú eres mía"*; plus
  **"esto es p r"** (single-letter debris from "P.R." — F5 feeds this) and
  **"hear this music"** (English leak — lingua's per-line filter passed it).
  Maybe 10-15 of 115 are teachable units (`real hasta la muerte` 13×8songs,
  `que me da la gana`, `un hijo e puta` — note the `'e`=de beheading visible even
  here). Fine as long as step_8b treats untranslated PMI entries as low-priority.
- Systematic miss: **"de una"** (BB staple, "right away") can never be detected —
  `_is_all_function_words` (step_2a:764, FUNCTION_WORDS contains both `de` and
  `una`) excludes it; it's also not in curated_mwes. Same for other all-function
  idioms (`por si acaso` — por/si both function words… "acaso" is not, but the
  4-gram count/PMI path found nothing; `a fuego`, `al garete`, `de cora` simply
  aren't curated and miss PMI thresholds).
- Patterns bucket (459 entries) reaches the live index as `mwe_memberships` chips
  with `"translation": ""` (e.g. `que` card carries `"que yo [PRON]": ""`,
  `"todo [PRON] que": ""`) — empty-string chips in the UI if rendered; step_8b
  comment claims consumers ignore this bucket but the live index says otherwise.

**ROOT CAUSE:** step_2a_count_words.py:746-748 (permissive PMI floor, acknowledged
in comment), :764 (`_is_all_function_words` blanket), :936-1004 (patterns emitted
untranslated, then assembled into the index).
**PROPOSED FIX:** curate `de una`, `a fuego`, `al garete`, `de cora` into
curated_mwes.json (one-line each — cheapest quality win of this whole section);
whitelist-exempt curated keys from the function-word filter; have step_8b drop
untranslated pattern chips at assemble time. **IMPACT:** missed high-value idioms on
common-word cards; empty chips on the `que`/`todo` cards Josh sees daily.
× **EFFORT: S**.

---

## F7 — Non-English foreign lines leak (lingua is Spanish-vs-English only)

**WHAT:** step_2a builds lingua with exactly {SPANISH, ENGLISH} (step_2a:1032), so
French/Italian/Portuguese guest verses are never filtered.
**EVIDENCE:** *"Juan, quand est-ce **qu'tu** vas venir chez moi ?"* (Sexo Sin
Cariño) → inventory entries `qu'tu`, `quand`, `chez`, `moi` (count 1 each, hidden)
and — VISIBLE — card `377450` word **une** lemma **unir** `VERB "to unite"` n=2,
whose occurrences are the French article. **ROOT CAUSE:** step_2a_count_words.py:1032.
**PROPOSED FIX:** add FRENCH/PORTUGUESE/ITALIAN to the detector and skip any
non-Spanish top-language line above threshold. **IMPACT:** 1 visible wrong card +
a handful of hidden junk entries; grows with collab-heavy artists. × **EFFORT: S**.

---

## F8 — CROSS-STAGE FLAG (for the assemble/id-keying agent): 1,226 of 11,198 index rows (11%) are orphaned — words like `las`, `dime`, `otra`, `calle` have NO card in the live deck

**WHAT:** 1,226 live-index ids don't exist in vocabulary_master.json;
joinWithMaster (js/vocab.js:88-89 `if (!m) continue`) silently drops them.
**EVIDENCE:** resolved 309 orphan ids by hashing md5(word|lemma) over candidate
pairings: `a8424d = las|la` n=**862**, `a49c83 = dime|dime` 300, `24b8dd = otra|otro`
299, `calle|callar` 150, `ustedes|usted` 107, `darte|dar` 92, `cojones|cojón` 50,
`soltera|soltero` 37, `nalgas|nalga` 19… **307 of the 309 resolved have no other
live card for the same word** (master has e.g. las|las `2c4522` but the index
doesn't reference it). Total orphaned corpus mass ≥9,202 occurrences. Cause
pattern: master was re-keyed when lemma assignments changed (la→las, callar→calle,
clitic re-routing for dime/darte/hacerlo) without rebuilding the artist index.
Not a stage-2/3 bug — flagged here because the corpus-count evidence made it
visible. × **IMPACT: large** (whole common words missing from the deck)
**EFFORT:** for the assemble-stage agent to size.

---

## Ranked summary for the orchestrator

1. **F1** beheaded elisions — wrong-word cards (tamos/tamo/taba="fluff"/"jacks") and
   a 96%-wrong "e" card. S-M effort, needs rebuild.
2. **F8** (cross-stage) 11% orphaned index rows; `las`/`dime`/`otra`/`calle` missing
   entirely. Route to assemble agent.
3. **F2** junk auto-generated mapping targets (felis, tamos, "tir"/"nir" lemmas). M.
4. **F5** ad-lib/fragment first examples on ~100 visible cards + `bla`/`ajá` junk
   cards. S-M.
5. **F6** MWE: curate `de una` et al. (S, high value); empty pattern chips.
6. **F4** bare `pa`/`pal` leak + stale CLAUDE.md claim (verified wired). S.
7. **F3** 187 unmerged apostrophe forms; two dead-code merge rules. S-M, low urgency.
8. **F7** French leak (`une`→"to unite" card). S.

Commands for Josh (not run — >30s or need rebuild): full step-2a→3a→5a re-run to
regenerate counts after F1/F2 mapping fixes; elision_mapping audit script vs
spanish_forms.json.
