# Deck Quality Audit — Spanish Artist Decks

**Audited:** 2026-06-13 · **Updated:** 2026-06-16 · **Scope:** Bad Bunny + Young Miko + Rosalía visible decks
**Re-verify any time:** `.venv/bin/python3 pipeline/bench_deck_quality.py` (read-only, fast)

This file is the durable record of a deck-quality pass. The goal (Josh's words):
make the deck *"exceptionally good at translating Spanish words correctly in
context, never show English code-switches as Spanish vocab, and use
lemmatization that respects what the lyric actually says."* The flagged-words
Google Sheet is the gold-standard quality signal.

---

## Verified current numbers (2026-06-16)

`pipeline/bench_deck_quality.py` replicates the front-end default filters
(`js/vocab.js` `buildFilteredVocab`) to count VISIBLE cards and scan them.

| Metric | Count (2026-06-16) | Was (2026-06-13) |
|---|---|---|
| Visible cards (unique) | **4704** (BadBunny 4037, YoungMiko 1535, Rosalía 1191) | 5136 |
| Blank-translation rows on visible cards | 25 | 26 |
| Verbose Gemini definitions | 183 (overcount — see below) | 185 |
| Cognate leaks (gloss == word) | 6 | 61 |
| Menu-bloat (one gloss ≥ 4×) | 25 | 25 |
| Examples (visible cards) | 25693 total · 354 (1.4%) empty-English · 88 (0.3%) untranslated | 28040 / 383 / 97 |
| Cards w/ ALL examples empty-English | 12 | 13 |

> **Why "Visible" dropped 5136 → 4704.** Most of that (≈399) is a **bench
> correction, not a deck change**: the old `visible()` read `cognate_score`
> only, but `merge_to_master` strips `cognate_score` from the index, so the
> bench was counting all 696 `is_transparent_cognate` master cards as visible
> — even though the live front-end already hides them (`vocab.js:166` derives
> `cognate_score` from `is_transparent_cognate`). The bench now mirrors that
> fallback. The remaining 33 is the real deck change from FIX 3 below. The
> cognate-leak drop (61 → 6) is FIX 3 plus making the detector
> accent-insensitive (now catches `área`/`melón`-type leaks). The 6 survivors
> are all short words (`me, ex, gas, eo, dúo, era`) deliberately left for
> individual judgment — see FIX 3.

---

## Two no-rerun mechanisms (used this pass)

Both avoid the pipeline, which matters while Josh's CPU is busy on the heavy
"Dutch Pijp loan" job. Changes appear after a hard-refresh.

1. **Front-end JS edits** — `js/vocab.js` filters at runtime.
2. **Direct `vocabulary_master.json` patches** — front-end fetches master at
   runtime, so in-place edits show immediately.

**HARD CONSTRAINT — positional sense arrays.** Index files reference senses
*by position* (`sense_frequencies[]`, `sense_methods[]`). Any master edit that
changes a card's sense **count** (add/remove a sense) desyncs the index and is
UNSAFE without a rerun. Only **in-place string edits** (translation, pos,
lemma, context, flags) are safe no-rerun. Splitting polysemy, deleting senses,
etc. → rerun.

**REBUILD CAVEAT.** `tool_8c_merge_to_master` rebuilds master from layers and
drops unknown fields, so any direct master patch is LOST on the next rebuild
unless also recorded in a durable curation file. See "Durability" below.

---

## FIX 1 (done, no rerun): front-end empty-meaning guard

`js/vocab.js` ~line 246 used to strip only `pos === 'X' && !translation`.
Changed to drop **any** meaning with no translation:

```js
item.meanings = item.meanings.filter(m => m.translation && m.translation.trim());
if (item.meanings.length === 0) continue;
```

**Validated delta** (bench): old guard 5144 visible → new guard 5136. The 8
newly-hidden cards are **all entirely blank** (no real gloss at all): `bate`,
`gana`, `fenomenal`, `sendo`, `amanezco`, `culona`, `rodeos`, `let's`. Zero
good cards lost. Within the surviving 5136, 26 stray blank rows stop rendering.

Requires bumping every `?v=` cache-busting tag in `main.js` and `index.html`
in lockstep (per `js/CLAUDE.md`).

*Underlying data still carries the blanks* — a future rerun + SpanishDict
scrape fix removes them from the data. The 8 all-blank words above are real
Spanish words (except `let's`) that need a gloss backfilled on the next rerun.

---

## FIX 2 (done, no rerun): in-place master patches

Safe in-place edits (no sense-count change). Hex keys are the master dict keys.

| Word | Key | Before | After | Why |
|---|---|---|---|---|
| `millo` | c7a231 | NOUN "corn" (ctx botany) | NOUN "millionaire" (ctx slang) | Lyric *"Nací pa' ser millo"* = born to be rich. PR slang clip of *millón*. |
| `niveles` | 7917b4 | lemma **nivelar**, VERB "to level" | lemma **nivel**, NOUN "level" | Lyric *"es cuestión de niveles"* = a question of levels. Plural of noun *nivel*, not the verb. |
| `diablo` | b7f4e2 | sense[1] NOUN "" (ctx "used to express anger or surprise") | sense[1] NOUN "damn!; the hell" | Fills the blank interjection sense (the flagged "damn!" usage). 2 senses → in-place fill keeps count. |
| `diablos` | 8b83ae | NOUN "devil" | NOUN "the hell; devils" (ctx exclamation) | Lyric *"¿Cómo diablos…?"* = how the hell. |
| `bi` | d15eaf | NOUN "Term of endearment for a romantic partner, similar to 'boo' or 'baby'." | NOUN "boo; baby (term of endearment)" | Shorten verbose gloss in place (single real sense; the POS=X empty sense is stripped by the guard). |
| `shot` | 0f1ec2 | (no flag) | `is_english_loanword: true` | English code-switch. Flag hides it (default-on filter). Its verbose gloss then never renders. |

**Deferred for `bate` (b31775):** blank VERB sense, open question baseball-bat
vs. blunt/joint (lyric *"tengo un bate… fumamo' hasta 10"* suggests a joint).
The empty-meaning guard hides the blank card meanwhile. Real fix = add a NOUN
sense → count change → needs rerun. Awaiting Josh's call on bat-vs-joint.

---

## FIX 3 (done, no rerun): transparent-cognate stamp + 2 gloss fixes

**Mechanism recap.** Post-merge the front-end's only cognate signal is the
master flag `is_transparent_cognate` (`merge_to_master` strips the index's
`cognate_score`; `vocab.js:166` falls back to `is_transparent_cognate ? 1 : 0`
and hides ≥ 0.85 under the default-on cognate filter). The shared
`cognates.json` layer is **too noisy to stamp wholesale** (`estar`, `como`,
`beso`, `creo`, `primero` all score 1.0). So the fix is a hand-reviewed stamp.

**What was stamped (33 words).** Single-sense cards whose only gloss == the
Spanish word itself (accent-insensitive), len ≥ 4, not a `cognates.json`
false-friend, not already flagged:

> alcohol, area, bachata, bases, chicha, control, crack, dimensión, formal,
> gala, idea, iris, legal, local, manual, marihuana, melón, normal, novena,
> perfume, personal, popular, radio, samurai, sangría, santería, sativa,
> sensual, sushi, súper, unión, vodka, élite

The **single-sense guard** is what makes a card-hide safe — it never throws
away a useful second meaning. It also auto-excluded the feared false
positives: `china` (2 senses → PR "woman" survives), and `media`/`armada`/
`date` aren't gloss==word leaks at all.

**2 carve-outs fixed in place, NOT hidden** (failed glosses, not transparent
cognates): `compositor` "compositor" → **"composer"** (English "compositor"
is an archaic printing term); `tití` "titi" → **"auntie"** ("Tití me
preguntó"; "titi" isn't English).

Applied via `tool_8c_patch_master_curated.py` (`COGNATE_STAMPS` list + 2
`OVERRIDES`). Idempotent; survives rebuilds when re-run (it's in
`run_spanish_rerun.sh` phase 4). Bench confirms: cognate_leak 61 → 6.

**Left for individual judgment (6, not stamped):** `me` (pronoun
mistranslation, not a cognate), `era` (homograph — also "was", imperfect of
*ser*), `eo` (ad-lib noise → better as `is_noise`), and short transparent
cognates `ex`/`gas`/`dúo` (len < 4, blanket guard skipped them).

**Separate job — 12 multi-sense primary leaks** (do NOT card-hide; demote/fix
the primary sense): `charro, china, combi, complot, general, no, paca, polo,
super, triple, union, use`.

## FIX 4 (done, no rerun, 2026-07-05): two example-side detectors + 103-card sweep

Two new bench detectors exploit data the deck already has:

1. **`code_switch_verbatim`** — the word appears unchanged in the Genius
   ENGLISH translation of every one of its lyric lines. A native translator
   already decided it doesn't translate → English code-switch. Caught 37
   loanwords the Wiktionary-derived layer missed (`so` ×10 — was glossed
   "under"! — `go, too, yes, game, hot, time, body, tune, royal, cash, tag,
   ski, full, boys, shots, lowkey, boujee, …`).
2. **`propernoun_caps`** — the word is capitalized mid-sentence in every
   lyric line. Caught 36 proper nouns with dictionary-artifact glosses:
   `rob`="syrup" (Rob Van Dam), `lee`="read" (Bruce Lee), `carmen`="poem"
   (Virgen del Carmen), `vegas`="meadow", `montana`="mountain",
   `chacón`="Philippine lizard", `cavaliers`="caballero", `jhay`="chick",
   `caicos`="guys" (lemma=chicos!), `luían`="to polish" (DJ Luian),
   `lary`="perezoso" (lemma=lazy!, Lary Over), …

Both are permanent bench categories now (steady-state 0; reviewed keepers
like `bomba`, `plena`, `manín`, `rola` live in `DETECTOR_KNOWN_OK`).

The sweep also fixed a distinct root-cause class: **reverse-direction
SpanishDict glosses** — the scrape hit the ENGLISH headword page when a
Spanish surface collides with an English word, producing *Spanish* "glosses"
(`tán`→"bronceado" via English "tan", `usa`→"EE. UU.", `capos`→"ceja",
`complot`→"conspiración", `trili`→"trino", `boujee`→"fresa"). Flagship fix:
**`tán` = apheresis of `están`** (9 corpus lines) — sense 0 rewritten to
"are (short for 'están')" / lemma `estar`, senses 1–8 blanked in place
(translation="" + pos=X; the front-end drops empty-translation meanings
AFTER the positional join, so blanking is index-safe — the new no-rerun
"sense removal" pattern).

All via `tool_8c_patch_master_curated.py` (now with `PROPERNOUN_STAMPS` and
`NOISE_STAMPS` lists): 165 field changes, 103 cards, 0 sense-count changes
(verified against a pre-patch snapshot). Bench after: visible 4309→4219,
verbose_def 175→119, cognate_leak 0, code_switch_verbatim 0,
propernoun_caps 0. Also gloss-fixed PR slang: `media`="half" (was "media"),
`manín`="bro" (was "peanut"), `mera`="hey!" (was "boss"), `cuki`="cutie"
(was "guinea pig", lemma=cuy), `toa`, `jeepeta`, `zeta`, `mai`, `dos`, etc.

Known loose end: `toa`'s example list contains a leaked Genius *annotation*
("Alude al caso del niño Rolando Salas Jusino…") rendered as a lyric line —
example-side, not master-side; scan for more when next touching examples.

---

## Durability of the master patches

Applied via the idempotent tool **`pipeline/tool_8c_patch_master_curated.py`**
(8 `OVERRIDES` field edits + 33 `COGNATE_STAMPS` are hardcoded there).
`tool_8c_merge_to_master` rebuilds master from layers and drops these edits,
so **re-run the patch tool after any master rebuild**, until the fixes are
folded into the pipeline proper:

```
.venv/bin/python3 pipeline/tool_8c_patch_master_curated.py
```

**Why not `curated_translations.json`?** That system is currently **dormant**.
`step_8b` loads it with `modes=("shared", "artist")`, but all 216 entries in
`shared/archive/curated_translations.json` are tagged `mode: "archive"` (215)
or `"wiktionary"` (1) — **zero** pass the filter. There is also no
`shared/curated_translations.json` (loader falls through to `archive/`). So
adding entries there would either be dormant too, or reactivate only my entries
while 216 others stay off — inconsistent and surprising. The patch tool is the
clean durability vehicle instead. (Reactivating the curated system is a
separate, larger decision for Josh.)

Folding these into the pipeline proper (so the patch tool can be retired):
- `diablo` interjection + `bi`/`shot` verbose glosses → `step_6c` gap-fill /
  `_is_definitional` repair.
- `shot` loanword flag → Wiktionary-etymology loanword path.
- `niveles` **lemma** (nivelar→nivel) → needs a durable lemma override
  (`homograph_overrides` or a lemma curation); the pipeline re-derives lemma.

---

## Deferred — needs a pipeline rerun (CPU currently busy)

Root causes: (1) SpanishDict menu/scrape quality (blank rows, cognate leaks,
menu bloat, wrong lemma); (2) Gemini Flash-Lite gap-fill (verbose defs,
polysemy collapse, wrong slang).

- **Verbose definitions (183 flagged, true defect set smaller).** Many flagged
  are loanwords that should be *hidden* not *fixed* (`lean`, `haters`, `combo`,
  `polaroid`, `champaña`, `cherry`, `reggaetón`, `shot`) and several VERB
  "phrasals" are actually fine (`joder` "to be a pain in the ass", `enamorar`
  "to make … fall in love", `atreverse` "to dare"). True repairable NOUN/ADJ
  sentence-defs: `mambo`, `chalet`, `toto`, `mai`, `ángel`, `oasis`, etc. Fix
  via `step_6c` + the existing `_is_definitional` repair. **Don't throw away
  Gemini classifications — surgical gloss repair only.**
- **Cognate leaks — DONE (no rerun), see FIX 3 above.** 33 single-sense
  gloss==word cards stamped `is_transparent_cognate`; 2 carve-outs gloss-fixed.
  Residual: 6 short words for individual judgment (`me, era, eo, ex, gas,
  dúo`) and 12 multi-sense primary leaks for sense-demotion (`china, super,
  union, general, …`).
- **Polysemy splits (count change → rerun):** `bi` (boo vs. bisexual),
  `media` junk entries, `volver`/`vuelve` senses that belong to `volverse`.
- **`todos`** showing "of them all" as primary — re-rank senses.
- **Menu bloat (25)** — one gloss repeated ≥ 4× (`caer` "to fall" ×6). Low
  priority; dedup at build.
- **Example tail (1.4% empty-English, 12 fully-empty cards** — `álbum`,
  `muchacha`, `curas`, `capítulo`…). Low priority. Prefer surgical translation
  backfill over re-picking examples.

---

## Constraints carried forward (from Josh)

- Never run long pipeline commands (>30s) inline — print them for his terminal.
- No browser previews / Claude-in-Chrome (service-worker caching unreliable).
- git: `git pull --rebase` before any push; never `--force`; never auto-amend;
  never skip hooks. Multiple Claude sessions share this repo.
- Add new layer files alongside existing — never overwrite (he compares methods).
- Never delete curated overrides — they're regression tests.
- `--from-step` runs ALL subsequent steps — always add `--skip` for expensive ones.
- `backend/secrets.json` holds the secret Apps Script URL — sensitive, do not commit.
