## The problem with most vocabulary apps

They teach by theme — *colours*, *at the airport*, *in the kitchen* — and drill you on lists of words you have no reason to care about yet. You learn *la cuchara* (spoon) and forget it before you ever hear it in the wild.

This app takes the opposite approach: every word you study comes from material you already care about. Spotify lyrics, film subtitles, frequency-ranked sentences from real corpora. The word *why* is paired with the sentence *you* are going to meet it in.

### Normal mode

![Normal mode — a flashcard flipping and cycling through senses](demo://normal)

Learn Spanish from the ground up, ordered by how common each word actually is across millions of sentences scraped from OpenSubtitles, Tatoeba and Wiktionary. Every flashcard is paired with real example sentences at your current level — so you don't get a rare word hidden inside an even rarer sentence.

### Artist mode

![Artist mode — a lyric card with the translated line](demo://artist)

Pick an artist — Bad Bunny, say — and the app builds you a deck of every Spanish word they use across their entire discography, ranked by how often they use it. Each flashcard shows the actual song lyric the word came from, with the line translated underneath.

Because language follows a power law, knowing the top-ranked words covers most of what you hear: learn a few hundred words and you're already recognising the majority of the catalog.

## What's under the hood

- **Lyrics pipeline** — Python scripts pull lyrics from Genius, strip section tags and ad-libs, and normalise each Spanish word to its dictionary form using Wiktionary and a full Spanish conjugation table.
- **Sense disambiguation** — Spanish *como* can mean *I eat*, *like*, or *how*. The pipeline uses Gemini and sentence-transformer embeddings to pick the correct sense for each example, so a card shows you the meaning the song actually used.
- **Cognate detection** — transparent cognates like *información → information* are flagged as free vocabulary and can be excluded, so your study time goes to words that actually need memorising.
- **Frontend** — vanilla JS, no framework, no build step. Data loads as static JSON and a service worker caches it for offline use as a PWA.

<!--
## Why it's a portfolio piece

The interesting engineering isn't the flashcard UI — it's everything behind it. Turning raw song lyrics into a ranked, lemmatised, sense-disambiguated vocabulary deck is a compact end-to-end data problem: scraping, cleaning, normalisation, corpus work, LLM-assisted classification, and delivery as static JSON. The app in front is there to prove the data is actually useful.
-->

