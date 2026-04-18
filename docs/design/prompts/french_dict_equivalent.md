---
title: SpanishDict-equivalent source for French
status: prompt
language: french
created: 2026-04-18
updated: 2026-04-18
---

# SpanishDict equivalent for French

## Context

Spanish artist mode pulls senses from **SpanishDict** (scraped, per-word HTML
cache in `pipeline/util_5c_spanishdict.py`). Every sense comes with:

- `pos`
- `translation`
- `context` (e.g. "used to introduce a subordinate clause", "used in comparisons")
- `regions` (Mexico, Spain, …)
- `examples` (Spanish ↔ English pairs)

The `context` field is what makes multi-sense cards actually learnable — it's
the disambiguator between e.g. `uno (numeral)` and `uno (impersonal use)`. The
front-end already renders it inline as `· context` at
[flashcards.js:1438](js/flashcards.js:1438).

French artist mode (first-pass, landed 2026-04) uses the **English Wiktionary
French extract** via `kaikki-french.jsonl.gz`. After the 2026-04-18 enrichment
(see `pipeline/step_5c_build_senses.py`, `STEP_VERSION = 2`), the Wiktionary
path also populates `context`, `register`, `example`, and `topic` per sense.
On the top 100 French words, 191 senses now carry Wiktionary examples and 98
carry register tags. That closes most of the gap — but not all of it:

- Coverage of colloquial / slang / regional French is thin compared to
  SpanishDict's coverage of equivalent Spanish.
- Some common conjugated forms are missing entirely from the enwiktionary
  extract (e.g. `a` as 3rd-person singular of `avoir` — the letter/preposition
  entries exist, but no verb entry).
- The `context` we synthesise is whatever Wiktionary editors happened to write
  in the leading parenthetical; it isn't a curated sub-sense label the way
  SpanishDict's is. Quality varies.

The question this doc is asking: **what's the right next step if we want
French sense data that feels as good as SpanishDict?**

## Options surveyed (April 2026)

| Source | Quality vs SpanishDict | Free? | Notes |
|---|---|---|---|
| **Kaikki French-Wiktionnaire (fr-extract)** — dump from fr.wiktionary.org, separate from the enwiktionary French slice we use today | Similar structure; broader colloquial / Québec / argot coverage because fr.wiktionary editors document French-internal usage in more depth | Free | Same JSON shape. Supplement-only layer, bolt-on to the enrichment that just landed. Mirrors the Spanish `eswiktionary` dialect supplement (see `project_eswiktionary.md` memory + `bench_gapfill` code). |
| **[Le Robert](https://dictionnaire.lerobert.com/)** (scrape) | ★★★★★ — closest feel to SpanishDict. Sense groupings with register/domain tags, curated examples, French-learner-oriented | No official API — scrapeable | The real SpanishDict-for-French. Same architecture as `util_5c_spanishdict.py`: per-word HTML cache → structured senses with context/register. Substantial build. |
| **[Larousse bilingual](https://www.larousse.com/en/dictionaries/french-english)** | ★★★★ — solid bilingual entries, fewer context labels than Robert | Free web, no API | Same scrape pattern, easier to scrape but less rich than Robert. |
| **[Oxford Dictionaries API](https://developer.oxforddictionaries.com/)** | ★★★★★ structured + context + examples + register | £50/mo as of Jan 2025 relaunch | Cleanest option if paying. Probably overkill for a hobby pipeline. |
| **[Lexicala](https://api.lexicala.com/)** | ★★★★ 50+ languages, claims sense disambiguation + register + domain | Enterprise pricing, no public tier | Sales-cycle barrier. |
| **[Collins Dictionary API](https://www.collinsdictionary.com/collins-api)** | ★★★★ | Contact for pricing | Same situation as Lexicala. |
| **[WordReference](https://api.wordreference.com/)** | ★★★★★ content but API effectively closed | No new signups | Dead end for a new build. |
| **[Glosbe](https://glosbe.com/)** | ★★ — translations + examples; no sense structure, no context tags | Free JSON API | Spot-checked on `c'est` — flat "it's / it is / by all accounts" list, no disambiguation. Not a SpanishDict replacement. |
| **[Linguee](https://www.linguee.com/) / DeepL API** | Translation-only API; the dictionary side isn't programmatically exposed | DeepL free tier = 500k chars/mo | Not a dictionary API. |
| **[Free Dictionary API](https://freedictionaryapi.com/)** | Same data as enwiktionary | Free | No improvement over what we have. |

## Recommendation (as of April 2026)

Phased, cheapest-wins-first:

1. **Ship the 2026-04-18 enrichment and live with it.** We haven't seen real
   user friction yet on French. The enriched Wiktionary menu is substantially
   better than the first-pass version — apos-phrase tier, verb forms resolved
   via form-of redirects, context / register / example fields populated.

2. **If coverage gaps surface** (argot / colloquial / conjugation gaps): pull
   down the **Kaikki French-Wiktionnaire** dump and plug it in as a supplement
   layer alongside the existing enwiktionary slice. Same pattern as
   `kaikki-eswiktionary-raw.jsonl.gz` for Spanish (see `bench_gapfill` / the
   `project_eswiktionary.md` memory). Roughly a day of work. Free.

3. **If we want true SpanishDict parity** (long-term, once French becomes a
   primary language): scrape **Le Robert**. New module
   `pipeline/util_5c_lerobert.py` mirroring `util_5c_spanishdict.py` — per-word
   HTML cache in `Data/French/Senses/lerobert/`, a `lerobert` value for
   `--sense-source`, wired into `step_5c_build_senses.py`. 1–2 weeks. Le Robert
   has the best sense disambiguation of the free French dictionaries, with
   register/domain tags a French learner actually wants.

## Decision

Not made yet. The enrichment landed 2026-04-18. Re-evaluate once there's
signal from actual French flashcard use.

## Sources

- [Raw data downloads extracted from Wiktionary — kaikki.org](https://kaikki.org/dictionary/rawdata.html)
- [Oxford Dictionaries API — plans](https://account.oxforddictionaries.com/pricing)
- [WordReference API status](https://api.wordreference.com/)
- [Lexicala API](https://api.lexicala.com/)
- [Glosbe dictionary](https://glosbe.com/)
- [Linguee](https://www.linguee.com/)
- [Le Robert (online dictionary)](https://dictionnaire.lerobert.com/)
- [Larousse bilingual](https://www.larousse.com/en/dictionaries/french-english)
- [Collins Dictionary API](https://www.collinsdictionary.com/collins-api)
- [Free Dictionary API](https://freedictionaryapi.com/)
