# Stage 1 — Lyric + Translation Acquisition Quality (Bad Bunny)

Audit date: 2026-07-19 (session continued from 2026-07-16). All probes in this scratchpad:
`probe1_batches.py`, `probe2_lyric_quality.py`, `probe3_live_leaks.py`, `probe4_feature_contamination.py`.

Corpus baseline (probe1/2): 537 unique songs in `Artists/spanish/Bad Bunny/data/input/batches/batch_*.json`
(no per-song lyric files exist — the brief's `data/input/lyrics/` path is not this artist's layout).
Exclusions in `data/input/duplicate_songs.json`: 154 duplicates + 19 placeholders + 53 non-Spanish +
14 non-songs = 235 unique skip IDs → **302 kept songs enter step 2a**. Live deck: 11,198 word entries,
**26,588 example instances** (`BadBunnyvocabulary.examples.json`).

Overall verdict: acquisition is in better shape than expected — the step_2a cleaner catches nearly all
Genius boilerplate (0 contributor headers, 0 section tags, 0 HTML entities, 0 Cyrillic homoglyphs
survive in the 302 kept songs), and Genius translation alignment is high quality. The real problems are
five specific leaks/gaps below.

---

## F1. Genius editorial descriptions leak into lyrics → 9 fake vocabulary cards + ~31 polluted live examples  [CONFIRMED]

**WHAT:** Multi-paragraph Genius song descriptions survive `clean_genius_lyrics` for 5 songs and were
counted as lyrics, minting vocabulary cards for words that never appear in any Bad Bunny lyric.

**EVIDENCE:**
- Leaking songs (probe2 + description-region cross-check): RLNDT (4179002), Amantes de una Noche
  (3380054, English prose), El Challet (Remix) (3167974), Me Llueven 2 (3007462), Polaroid (Remix) (3825550).
- Example leak line in the LIVE deck: *"Alude al caso del niño Rolando Salas Jusino, que desapareció el
  7 de julio de 1999 en Toa Alta, Puerto Rico; como una metáfora de cómo se siente: perdido."* — this is
  Genius annotation prose about RLNDT, not a lyric. It is the example sentence on 10+ live cards.
- **Cards that exist ONLY because of leaked prose** (corpus_count / leak-examples verified in probe of
  index + master): `alude` (fd574e, cc=1), `rlndt` (8731f1, cc=1), `rolandito` (5b90c9, cc=1),
  `rolando` (6f96f0, cc=1), `jusino` (79fb28, cc=1), `salas` (048c9b, cc=1, lemma "sala"!),
  `rumoreó` (549d85, cc=1), `metáfora` (ce2dee, cc=1), plus `toa` (844643, 1 of 2 examples is leak).
  Note `alude|alude` and `rumoreó|rumoreó` are also lemma-fuzz instances (unlemmatized).
- **Real cards with polluted examples**: niño (f9ec95), julio (cd4420), desapareció (de6da5),
  remix (162de5, 2 of 7 examples), primer (26c4e8), oficial (938891), acerca→acercar (f011df),
  versión (f2fd60), alta→alto (ca9c46), llueven→llover (c4c148), este (196e6a).
- Total in live deck: **31 leak example instances** across ~20 word IDs (probe3; the 5 additional
  "Juntes así de grandes…" hits are a genuine spoken intro in Escápate Conmigo (Remix), not a leak).
- The leaked English paragraph from Amantes de una Noche also entered
  `data/layers/example_translations.json` ("first collaboration" grep hit) — i.e. junk got a Gemini
  translation call spent on it.

**ROOT CAUSE:** `pipeline/artist/step_2a_count_words.py:173` — the Read More strip regex
`r'(?:…|\.\.\.|…)?\s*Read More[\xa0\s]*\n'` requires a newline right after "Read More", but these
Genius pages append `[Letra de "X"]` on the same line (raw: `…es… Read More\xa0[Letra de "RLNDT"]\n`),
so the regex never matches. The fallback editorial heuristic (lines 177-196) only inspects the FIRST
paragraph before `\n\n` and only recognizes Spanish meta-phrases + quote chars — RLNDT's first chunk is
the 17-char "RLNDT = Rolandito" and Amantes' is quote-free English, so both fail. Every description
paragraph except the final "… Read More" line (dropped by `BOILERPLATE_LINE_RE`, line 99) then leaks.

**PROPOSED FIX (S):** In `clean_genius_lyrics`, (1) drop the `\n` requirement — cut everything through
`Read More` (+ optional trailing `[Letra de "…"]`) wherever it appears in the first ~1500 chars;
(2) when a `[Letra de "…"]` or first `[Sección]` tag exists, treat it as the authoritative lyrics start.
Then rebuild vocab_evidence and prune the 9 junk master entries via `tool_8c_patch_master_curated.py`.

**IMPACT:** 9 junk cards + ~22 polluted example instances on real cards, all live today. Highly visible
when hit (prose "example sentences" with dates and full names). × **EFFORT: S**

---

## F2. Placeholder heuristic drops one REAL song entirely  [CONFIRMED]

**WHAT:** "No Prometo Nada" (5242339) has ~900 chars of genuine leaked-track lyrics (Intro/Pre-Coro/Coro
all transcribed) but `clean_genius_lyrics` returns "" for it, so the song contributes zero lines.

**EVIDENCE:** Raw contains the transcribed song PLUS the line "¡La letra completa estará disponible
pronto!" under an `[Adelanto]` tag. 16 kept songs clean to empty; the other 15 are genuine placeholder
pages (leak snippets, titles suffixed `*`: "Tú Me Gustas\*", "Alta Moda\*", …) — only this one has real
content ("Yeh, sabes que no soy fácil, menos de convencer / Que no confío en nadie…").

**ROOT CAUSE:** `pipeline/artist/step_2a_count_words.py:155-159` — placeholder detection is a substring
test over the WHOLE raw text (`"letra completa" in raw.lower()`), so one placeholder line anywhere nukes
the song.

**PROPOSED FIX (S):** Treat as placeholder only if the marker appears AND cleaned content is < ~8 lines,
or drop just the marker line via `BOILERPLATE_LINE_RE`.

**IMPACT:** 1 of 302 songs (~35 usable lines) silently missing; also means effective corpus is 286
content-bearing songs, not 302. × **EFFORT: S**

---

## F3. 348 live example instances (1.3%) have EMPTY English translations  [CONFIRMED]

**WHAT:** Every live example whose `translation_source` is blank also has an empty `english` — the card
shows an untranslated Spanish lyric line.

**EVIDENCE (probe3 + blank-sample probe):** 348/26,588 instances, all with `english: ""`/null. They
cluster in a handful of songs — Prayer, La Parabi, Loco Pero Millonario (Remix), Favorito De Los Capos
(Remix), Ahora Soy Peor — i.e. songs whose lines never made it into
`data/layers/example_translations.json` (18,987 lines: gemini 12,765 / genius 6,222 / google 0).
Samples: "Mi herma, yo tengo el poder pa' manejarte con to' tu' manejo' (Wuh)" [Prayer],
"Escuchando todos los clásicos de Jowell y Randy" [La Parabi].

**ROOT CAUSE:** These example lines are absent from the example_translations layer (likely
examples re-picked/added after the big Gemini translation run); step_8b assembles anyway and stamps
`trans_info.get("source", "")` (`pipeline/artist/step_8b_assemble_artist_vocabulary.py:936,1006,1110`)
with no missing-translation gap-fill or warning.

**PROPOSED FIX (S):** One Gemini batch over the ~300 unique missing lines appended to
example_translations.json (source "gemini"), then re-run step_8b. Also make step_8b print a count of
translation-less examples so this regression is visible. Command for Josh (not run, >30s): the
translation gap-fill path in step_6c / legacy translate flow.

**IMPACT:** 348 user-visible untranslated examples, concentrated so a session hitting Prayer/La Parabi
sees many. × **EFFORT: S**

---

## F4. One third of live examples are not Bad Bunny's voice  [CONFIRMED — scope decision, not a bug]

**WHAT:** No pipeline stage filters or tags lines by performer, so guest verses on kept songs are counted
and surfaced as "Bad Bunny vocabulary".

**EVIDENCE (probe4, section-tag attribution using scan_duplicates' own parser):**
- 6,219 / 19,682 content lines (31.6%) in the 302 kept songs belong to non-BB sections.
- 63 songs have MORE non-BB lines than BB lines: 47 (Remix) BB=38/other=137, Maldades (Remix) 55/125,
  El Combo Me Llama 2 36/120, Me Mata 25/108, Pa' Que Le De (Remix) 19/97, Te Boté (Remix) 48/92…
- Top foreign voices in the corpus: Arcángel 460 lines, J Balvin 398, Anuel AA 323, Almighty 266,
  Farruko 239, Bryant Myers 233, De La Ghetto 196, Ñengo Flow 189, Daddy Yankee 173, Residente 150.
- Live deck: **8,612 of 26,370 attributable example instances (32.7%)** come from non-BB sections, e.g.
  ed688d "BAILE INoLVIDABLE" line by Jacobo Morales; "Loca (Remix)" line by Khea/Cazzu (rioplatense
  dialect); LA NOCHE DE ANOCHE line by Rosalía.
- English guest verses are largely absorbed by the lingua line filter downstream, so the damage is
  dialect/register mixing (Argentine voseo from Cazzu/Khea, Colombian J Balvin), not English cards.

**ROOT CAUSE:** `clean_genius_lyrics` strips `[Verso: Artist]` tags without reading them
(`step_2a_count_words.py:211-212`); the attribution parser exists only in the reporting tool
(`Artists/tools/scan_duplicates.py:106-171`). The batches were even re-scraped specifically to preserve
these tags (`step_1a_download_lyrics.py:295-344, rescrape_with_headers`) — the data is there, unused.

**PROPOSED FIX (M):** Carry performer metadata per line from section tags into vocab_evidence/
examples_raw (a boolean `is_target_voice` per example), then have step_8b PREFER BB-voice lines when a
word has alternatives — a surgical example-selection bias, not a corpus filter (consistent with Josh's
keep-unique-content exclusion philosophy and preserve-examples feedback). Optionally down-weight
other-voice lines in ranking.

**IMPACT:** pervasive (1/3 of examples); mostly invisible per-card but shapes the whole deck's claim of
being "Bad Bunny's Spanish". × **EFFORT: M**

---

## F5. Genius invisible anti-scrape spaces persist into the live deck  [CONFIRMED — minor]

**WHAT:** Genius injects U+2005/U+205F/U+200A as space substitutes; `normalize_text` doesn't map them, so
they flow through examples into the deck.

**EVIDENCE:** In cleaned kept lyrics: U+2005 ×213 (52 songs), U+205F ×105 (21 songs), U+200A ×11
(2 songs). **318 live example instances** contain one (probe: "Sé que te incito a pecar…"
[Una Vez]). Tokenization is unaffected (WORD_RE treats them as separators), but any downstream
exact-string matching of these lines against text from other sources (LRC timestamp lines, curated
overrides keyed by line text) silently misses, and Gemini/Genius line-lookups depend on identical bytes.
Also 4 live instances still carry Genius' `[?]` unknown-transcription marker.

**ROOT CAUSE:** `pipeline/artist/step_2a_count_words.py:133-140` `normalize_text` handles smart quotes,
dashes and 7 Cyrillic homoglyphs only.

**PROPOSED FIX (S):** Add ` -   　 → " "` (and strip `​﻿`, `[?]`) to
`normalize_text`; harmless to re-run.

**IMPACT:** 318 instances cosmetic + latent matching hazard. × **EFFORT: S**

---

## F6. Song-selection bookkeeping: stale stats, exclusion chains, 16 zero-content "kept" songs  [CONFIRMED — hygiene]

**WHAT:** duplicate_songs.json is internally inconsistent in small ways; exclusion decisions themselves
spot-check as sound.

**EVIDENCE:**
- `stats.unique_songs: 317` but actual kept = **302** (537 − 235 union of skip IDs; buckets overlap:
  dup∩placeholders=4, dup∩non_spanish=1).
- 13 duplicate entries' `keep` targets are THEMSELVES excluded (e.g. 3587995 Gucci Gang (Mega Remix),
  5501114, 7253324 → placeholders) — those songs' content is fully dropped with no surviving "keep".
  Mostly benign (chains into placeholders) but nothing validates it.
- 16 of the 302 kept songs clean to empty (15 placeholder pages + F2's false positive) — the
  placeholders list (19 IDs) is incomplete; content heuristics catch the rest by accident.
- Spot-checked exclusions are justified: Soy Peor (Remix)/(Mambo Remix) → Soy Peor; Tú No Metes Cabra
  (Remix) → original; Pa' Que Le De: original excluded in favor of the remix (remix supersets it).
  26 kept remix-titled songs are all cases where the BB version IS the remix (Te Boté, No Me Conoce,
  Soltera, LOYAL…) — correct keeps, but they are the main driver of F4.
- Detection limits of `Artists/tools/scan_duplicates.py`: exact normalized-line matching with min-run 4
  and 30% shared threshold — cannot catch re-recordings with changed wording, live versions with
  per-line ad-lib differences beyond parentheses, or copied hooks <4 lines. No missed duplicate
  surfaced in my sampling; full re-scan is cheap but O(n²) — command for Josh:
  `.venv/bin/python3 Artists/tools/scan_duplicates.py --artist "spanish/Bad Bunny"`.

**PROPOSED FIX (S):** validation pass in scan_duplicates or a tiny lint: recompute stats, flag excluded
keep-targets, auto-add empty-cleaning songs to placeholders.

**IMPACT:** No live-deck damage found; prevents silent drift for artist #4. × **EFFORT: S**

---

## F7. Translation acquisition quality is GOOD; coverage, not alignment, is the limit  [CONFIRMED — positive control]

**WHAT:** Genius community-translation alignment (step_1b `build_aligned_translations`) shows no
detectable misalignment; the conservative strategy discards rather than shifts.

**EVIDENCE:**
- Coverage: 190 translations scraped; **178 of 302 kept songs (58.9%)** have one. Kept-song alignment:
  80 exact, 88 close (section-matched), 10 skipped (>10% line-count diff). **6,876 aligned pairs** in
  kept songs; 6,300 unique lines in the flat index.
- Misalignment audit: random 30 pairs (seed 7) across exact+close songs → **30/30 correctly aligned**,
  including risky "close"-bucket songs (Bichiyal, DtMF, TELEFONO NUEVO, YO VISTO ASÍ). Observed rate 0%
  (upper 95% bound ≈ 10% at n=30; nothing suggests systematic off-by-one — the section strategy only
  zips sections with EXACTLY equal line counts, and drops mismatched sections; step_1b:557-572).
- ES==EN identical pairs: 341/6,876 (5.0%) — legitimately untranslatable lines (ad-libs "Eh-eh",
  producer tags "Mambo Kingz", English lines). EN side containing Spanish: 11 pairs, all song-title
  references ("She listens to me from 'Diles' and 'Pa' Que Le Dé'"). Not corruption.
- Design quirk worth knowing: the flat `index` is first-wins ACROSS songs for identical Spanish lines
  (step_1b:552-556) — a repeated line ("Yeah, yeah") gets one song's English everywhere. No harmful
  instance found (repeated lines are ad-libs).
- Alignment-side cleaning `_clean_lyrics_keep_blanks` (step_1b:442-456) drops only line[0], so the F1
  description paragraphs also pollute the Spanish side of alignment for those 5 songs — same fix covers it.

**Source provenance (question 4):** live deck's 26,588 examples: **gemini 16,380 (61.6%) / genius 9,860
(37.1%) / blank 348 (1.3%) / google 0**. The layer example_translations.json: gemini 12,765 / genius
6,222 / google 0. The "google" source exists only via `tool_1b_translate_sentences_google.py` →
`sentence_translations.json` (merges genius lines, marks the rest "google") for --no-gemini artists
(Young Miko, Rosalía per its docstring) — never used for BB. BB's gemini translations were written by
the legacy step 6 (`legacy_llm_analyze.py:1351` writes example_translations.json) and step_6c. Known
bug #8 (translation judge scores ignored by the builder) is the downstream stage's problem — but note
step_8b DOES load translation_scores.json (line 430) and reads per-line entries (line 871); what it does
with them is for the stage auditing the builder.

**IMPACT:** none negative; genius lines feed WSD safely. The lever here is coverage (41% of kept songs
have no community translation → Gemini bears the load). × EFFORT: n/a

---

## Side notes
- **Hardcoded Genius API token** committed in source: `pipeline/artist/step_1a_download_lyrics.py:21` and
  `step_1b_scrape_translations.py:17` (same token). Hygiene: move to `.env` (loader already exists in
  `util_1a_artist_config.load_dotenv_from_project_root`).
- Producer-credit outro lines ("Hyde El Químico", "Alex Killer", "Los Legendarios") survive cleaning in
  many songs; they are short so `is_good_context_line` keeps them out of examples — they surface only
  as proper-noun tokens for step_4a routing to absorb. Low priority.
- All 537 batch records carry `artist: "Bad Bunny"` (step_1a `song_meta_to_record` uses primary_artist),
  so batch metadata cannot distinguish BB-primary from feature-only songs — attribution must come from
  section tags (F4).

## Ranked summary
1. **F1** editorial-description leak → 9 fake cards + 31 bad examples (S fix, high visibility)
2. **F3** 348 untranslated live examples (S fix, directly user-visible)
3. **F4** 32.7% of examples are non-BB voices (M, strategic)
4. **F2** one real song dropped by placeholder heuristic (S)
5. **F5** invisible Unicode in 318 live examples (S, cosmetic/latent)
6. **F6** exclusion bookkeeping drift (S, hygiene)
7. **F7** translation alignment: clean bill of health
