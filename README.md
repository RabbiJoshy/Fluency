# Fluency

A vocabulary flashcard app built around the idea that the best way to learn a language is through content you already love. Instead of generic word lists, every word comes with a real example sentence pulled from the source it was discovered in.

## The Idea

Most vocabulary tools give you the same 1000 words in the same order, with invented example sentences. Fluency takes a different approach:

- **Frequency-first**: words are ranked by how often they actually appear in real usage, not by what a textbook committee decided was "important"
- **Real examples**: every flashcard shows an example sentence from the actual corpus the word was drawn from — so you see it used the way real speakers use it
- **CEFR-aware**: vocabulary is organised by proficiency level so you can focus on words at the right difficulty for you
- **Flags for learner shortcuts**: transparent cognates (words that look almost identical in both languages) are flagged so you know which words you can effectively skip

## Bad Bunny Mode

The standout feature is a Spanish vocabulary deck built entirely from Bad Bunny's discography. The pipeline downloads his lyrics, counts every word by frequency, filters out English loanwords and ad-libs, handles Caribbean Spanish features like s-elision (`ere'` → `eres`), and produces a ranked vocabulary list where every entry has a real lyric as its example sentence.

The result is a deck of genuinely useful Spanish vocabulary — weighted toward the informal, urban Spanish that Bad Bunny actually uses — with examples that feel meaningful rather than contrived. If you already listen to his music, the context is immediately familiar.

The same pipeline architecture can be applied to any artist or corpus.

## How It Works

The app is a progressive web app (PWA) — it runs entirely in the browser with no backend, installs to your home screen, and works offline after the first load.

**Study flow:**
1. Pick a language and CEFR level
2. Choose a set size (25, 50, or 100 cards)
3. Flip cards by tapping or pressing Space — swipe/arrow keys to mark correct or incorrect
4. Review incorrect cards at the end of each session

**On each card:**
- Front: the word as it appears in real text, with its frequency rank
- Back: all meanings with part-of-speech and usage frequency, plus an example sentence with translation and links to SpanishDict, Reverso, and conjugation tools

## The Data Pipeline

For the Bad Bunny deck, vocabulary goes through a multi-stage NLP pipeline:

1. Lyrics are downloaded via the Genius API
2. Words are tokenised, frequency-counted (in PPM), and scored for line quality
3. Caribbean Spanish elisions are merged back to canonical forms (`ere'` + `eres` → `eres`)
4. spaCy (`es_core_news_lg`) assigns lemmas and POS tags; `wordfreq` identifies English loanwords by comparing EN/ES corpus frequency ratios
5. Translations are applied from a cache, with live Google Translate filling any gaps
6. Duplicate entries with hallucinated lemmas are deduplicated
7. Transparent cognates are auto-detected using suffix rules and string similarity
8. Entries are re-ranked using a tiebreaker: general Spanish frequency, cross-song coverage, and cognate status (cognates sort last — they're "free" knowledge)

## Tech Stack

- Vanilla JavaScript, CSS Grid/Flexbox — no frameworks
- PWA with Service Worker for offline support
- Python NLP pipeline: spaCy, wordfreq, Lingua, deep-translator
- Deployed as a static site (GitHub Pages compatible)

## Install as an App

**iOS**: Safari → Share → Add to Home Screen
**Android**: Chrome → Menu → Add to Home Screen
