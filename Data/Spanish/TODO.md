# Spanish Normal-Mode Pipeline — TODO

## Done
- [x] Archive old Data/Spanish files to archive/
- [x] Build `Scripts/build_examples.py` — corpus-matching pipeline
- [x] Run with Tatoeba: 91% coverage, 62K examples, runs in seconds

## In Progress
- [ ] Integrate OpenSubtitles as fallback layer (file downloading)

## Next Up
- [ ] Parse OpenSubtitles es-en data (Moses format: parallel .es/.en files)
- [ ] Add OpenSubtitles as second corpus source in `build_examples.py`
  - Tatoeba primary (cleaner), OpenSubtitles fills gaps
  - Deduplicate across corpora
  - May need quality filtering (fragments, OCR artifacts, single-word lines)
- [ ] Re-run and measure: how many of the 1,002 uncovered words get filled?

## Future — Coverage Improvements
- [ ] Lemmatization pass (spaCy `es_core_news_lg`) — match conjugated forms to lemmas
  - e.g. `disculpen` matches via `disculpar`, `maten` via `matar`
  - Estimated +4% coverage on top of accent normalization
- [ ] Quality filtering — drop sentences with too many unknown tokens, OCR noise, etc.

## Future — Sense-Specific Examples
- [ ] Distribute examples across meanings instead of duplicating to all
  - Options: spaCy POS matching, cheap Gemini pass for sense disambiguation, or heuristic (keyword overlap with translation)
- [ ] Compute per-sense frequency from corpus (how often each meaning appears)
  - Once sense→sentence mapping exists, frequency = count per sense / total

## Future — Multi-Language
- [ ] Generalize `build_examples.py` to accept language as argument
- [ ] Download Tatoeba pairs for Italian, Swedish, etc.
- [ ] Generate per-language `spanish_ranks.json` equivalent (frequency ranks)
- [ ] Build vocabulary.json for each language

## Notes
- Easiness scoring uses median frequency rank of sentence tokens (same as artist mode `8_rerank.py`)
- `spanish_ranks.json` and `SpanishRawWiki.csv` stay at top level (front-end needs them)
- No LLM calls needed for example matching — local processing only
- OpenSubtitles profanity/slang will fill the gap Tatoeba's polite corpus can't
