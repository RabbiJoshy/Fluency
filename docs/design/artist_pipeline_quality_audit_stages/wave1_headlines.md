# Wave-1 headlines (for wave-2 agents — full detail in stage{1,2,3,6}_*_findings.md)

Baseline numbers: 537 songs scraped → 302 kept; live deck = 11,198 index rows / 26,588
example instances / 3,951 default-view cards (3,491 visible under Josh's settings).

- ORPHANED INDEX ROWS: 1,226 of 11,198 live index ids join to NO master entry →
  js joinWithMaster silently drops them. las(862), dime(300), otra(299), calle(150),
  cojones(50) have no card at all. Cause: tool_8c master patches re-key lemmas; index
  never rebuilt. (stage2 F8, stage3 #9, stage6 bonus)
- NEVER-CLASSIFIED CARDS: 326 of 3,951 default-view cards (8.3%) have no classifier
  assignment — 297 gap-fill-only + 29 blank X-cards. Mechanism: step_8b X-fallback
  (step_8b:1137-1161) + no unclassified gate in joinWithMaster. Worst: baby(613),
  dos(133), flow(121). (stage3 #3)
- GHOST EXCLUDE BUCKETS: step_8b flag-hides only 3 of 5 exclude buckets
  (step_8b:528-537). exclude.cognate + exclude.low_frequency leak: 71/79 curated
  cognates visible with Gemini-invented glosses; 839 low-freq words became blank
  X-cards. (stage3 #1,#4)
- COGNATE_SCORE TIMEBOMB: 0 live entries carry cognate_score; fresh rebuild stamps
  ≥0.85 on 695 currently-visible cards (está/estoy/estás…, mucho, hombre) and default
  excludeCognates hides them. (stage3 #2)
- LEMMA = SD HEADWORD AT SCRAPE TIME: step_7a never lemmatizes; no plausibility guard;
  derivation_map + homograph_overrides computed but never consulted in artist mode.
  (stage6 F0)
- HOMOGRAPH SURVIVOR CARDS: live index carries only the minor-verb analysis with the
  full surface count: para|parar "to stop" n=1505, como|comer n=754, todo|todos n=613,
  fue/fui→ser. Current step_8b already splits counts proportionally (fix exists);
  live index predates it. (stage6 F2)
- TOKENIZER BEHEADS LEADING APOSTROPHES: 'tamos/'taba/'e lose elision marker →
  live cards tamos/tamo="fluff/chaff", taba="jacks", e="and"(n=234, ~92% actually 'e=de).
  (stage2 F1)
- STEP_6C ENGLISH_LOANWORDS SKIP overrides routing for 138 classifier-routed words
  (gasolina, gol, ron, dembow, bichote) — never classified. (stage3 #5)
- EXAMPLE HYGIENE: 348 live examples blank English; 318 carry invisible Unicode
  (U+2005 etc.); 37 visible cards' first example is ≥50% ad-lib; 32.7% of example
  instances are non-BB voices (attribution data exists in batches, unused);
  5 songs leak Genius editorial prose as lyrics (9 fake cards). (stage1 F1/F3/F4/F5,
  stage2 F5)
- Genius community translation alignment is TRUSTWORTHY (30/30 random audit correct);
  live example translation sources: gemini 61.6% / genius 37.1% / blank 1.3%. (stage1 F7)
