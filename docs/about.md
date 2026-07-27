## The problem with most vocabulary apps

Fluency turns speech and song lyrics into flashcards, ordered by how often words are actually used and showing the right meaning for each sentence.

They teach by theme (colours, at the airport, in the kitchen) and drill you on lists of words you have no reason to care about yet. You learn *la cuchara* (spoon) and forget it before you ever hear or use it in the wild.

This app takes the opposite approach: every word you study comes from material you already care about — song lyrics, film subtitles and real sentences. It also prioritises small but essential words that topic-based lessons can overlook: *aunque* appears often in real Spanish and can mean *although*, *even though* or *even if*, depending on the sentence.

### Speech

![Speech: a flashcard flipping and cycling through senses](demo://normal)

Learn from subtitle dialogue, ordered by how common each word is across millions of subtitle lines. Every flashcard is paired with real examples from OpenSubtitles and Tatoeba at your current level, so you don't get a rare word hidden inside an even rarer sentence.

### Lyrics

![Lyrics: a lyric card with the translated line](demo://artist)

Pick an artist (Bad Bunny, say) and the app builds a frequency-ranked vocabulary from their catalogue. Each flashcard shows an actual song lyric containing the word, with the line translated underneath. Tap the lyric and it plays in your own Spotify at that exact moment, so you hear the word in context on the original track.

For words with several meanings, the card gives an indicative split: *fuego* is shown as *fire* about 70% of the time, *light* 20%, and *passion* 10%.

A relatively small number of words make up most lyrics. Learn the most frequent few hundred and you can already recognise much of the catalogue.

## What's under the hood

- **Lyrics pipeline**: Python scripts pull lyrics from Genius, strip section tags and ad-libs, and link different forms of a Spanish word using dictionary data and a full conjugation table.
- **Choosing the right meaning**: Spanish *como* can mean *I eat*, *like*, or *how*. The pipeline compares each line with dictionary meanings and uses Gemini to decide which one fits.
- **Familiar words**: easy connections like *información* / *information* are flagged and can be excluded, so your study time goes to words that actually need memorising.
- **Frontend**: vanilla JS, no framework, no build step. Data loads as static JSON and a service worker caches it for offline use as a PWA.

<!--
## Why it's a portfolio piece

The interesting engineering isn't the flashcard UI, it's everything behind it. Turning raw song lyrics into a ranked, lemmatised, sense-disambiguated vocabulary deck is a compact end-to-end data problem: scraping, cleaning, normalisation, corpus work, LLM-assisted classification, and delivery as static JSON. The app in front is there to prove the data is actually useful.
-->
