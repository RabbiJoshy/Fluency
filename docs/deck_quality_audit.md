# Deck Quality Audit — Spanish Artist Decks

**Audited:** 2026-06-13 · **Scope:** Bad Bunny + Young Miko + Rosalía visible decks
**Re-verify any time:** `.venv/bin/python3 pipeline/bench_deck_quality.py` (read-only, fast)

This file is the durable record of a deck-quality pass. The goal (Josh's words):
make the deck *"exceptionally good at translating Spanish words correctly in
context, never show English code-switches as Spanish vocab, and use
lemmatization that respects what the lyric actually says."* The flagged-words
Google Sheet is the gold-standard quality signal.

---

## Verified current numbers (2026-06-13)

`pipeline/bench_deck_quality.py` replicates the front-end default filters
(`js/vocab.js` `buildFilteredVocab`) to count VISIBLE cards and scan them.

| Metric | Count |
|---|---|
| Visible cards (unique) | **5136** (BadBunny 4409, YoungMiko 1666, Rosalía 1327; artists overlap) |
| Blank-translation rows on visible cards | 26 cards |
| Verbose Gemini definitions | 185 cards (overcount — see below) |
| Cognate leaks (gloss == word, score < 0.85) | 61 cards |
| Menu-bloat (one gloss ≥ 4×) | 25 cards |
| Examples (visible cards) | 28040 total · 383 (1.4%) empty-English · 97 (0.3%) untranslated |
| Cards w/ ALL examples empty-English | 13 |

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

## Durability of the master patches

Applied via the idempotent tool **`pipeline/tool_8c_patch_master_curated.py`**
(the 6 edits are hardcoded there). `tool_8c_merge_to_master` rebuilds master
from layers and drops these edits, so **re-run the patch tool after any master
rebuild**, until the fixes are folded into the pipeline proper:

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

- **Verbose definitions (185 flagged, true defect set smaller).** Many flagged
  are loanwords that should be *hidden* not *fixed* (`lean`, `haters`, `combo`,
  `polaroid`, `champaña`, `cherry`, `reggaetón`, `shot`) and several VERB
  "phrasals" are actually fine (`joder` "to be a pain in the ass", `enamorar`
  "to make … fall in love", `atreverse` "to dare"). True repairable NOUN/ADJ
  sentence-defs: `mambo`, `chalet`, `toto`, `mai`, `ángel`, `oasis`, etc. Fix
  via `step_6c` + the existing `_is_definitional` repair. **Don't throw away
  Gemini classifications — surgical gloss repair only.**
- **Cognate leaks (61).** gloss == word, score < 0.85: `hotel`, `radio`,
  `idea`, `tequila`, `mafia`, `suite`, `alcohol`, `natural`, `original`…
  Re-score cognates (`step_7c_flag_cognates`). NB: `me` is a pronoun
  homograph, not a cognate — translation defect, separate.
- **Polysemy splits (count change → rerun):** `bi` (boo vs. bisexual),
  `media` junk entries, `volver`/`vuelve` senses that belong to `volverse`.
- **`todos`** showing "of them all" as primary — re-rank senses.
- **Menu bloat (25)** — one gloss repeated ≥ 4× (`caer` "to fall" ×6). Low
  priority; dedup at build.
- **Example tail (1.4% empty-English, 13 fully-empty cards** — `álbum`,
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
