# Bad Bunny Vocabulary Pipeline

Generates a structured Spanish vocabulary JSON from Bad Bunny song lyrics.
Handles Caribbean Spanish features (s-elision, d-elision, code-switching)
and produces lemmatised, translated, deduplicated entries for a language
learning app.

## Pipeline

| Step | Script | Input | Output | Description |
|------|--------|-------|--------|-------------|
| 1 | `1_download_lyrics.py` | Genius API | `bad_bunny_genius/batch_*.json` | Download song lyrics from Genius |
| 2 | `2_count_words.py` | `bad_bunny_genius/batch_*.json` | `intermediates/2_vocab_evidence.json` | Tokenise lyrics, count word frequencies (PPM), extract example lines |
| 3 | `3_merge_elisions.py` | `intermediates/2_vocab_evidence.json` | `intermediates/3_vocab_evidence_merged.json` | Merge elided forms into canonical words (ere' + eres -> eres with display_form) |
| 4 | `4_add_spacy_info.py` | `intermediates/3_vocab_evidence_merged.json` | `intermediates/4_spacy_output.json` | Lemmatise with spaCy `es_core_news_lg`, assign POS tags |
| 5 | `5_add_translations.py` | `intermediates/4_spacy_output.json` | `BadBunnyvocabulary.json` | Build final vocab structure, apply cached translations (CACHE_ONLY mode) |
| 6 | `6_fill_translation_gaps.py` | `BadBunnyvocabulary.json` | `BadBunnyvocabulary.json` | Fill missing translations via Google Translate API (restartable) |
| 7 | `7_dedup_same_word.py` | `BadBunnyvocabulary.json` | `BadBunnyvocabulary.json` | Merge same-word entries with different (often hallucinated) lemmas |
| 8 | `8_flag_cognates.py` | `BadBunnyvocabulary.json` | `BadBunnyvocabulary.json` | Flag transparent Spanish-English cognates |

## Running the pipeline

All scripts are run from the project root (`Fluency/`):

```bash
cd /Users/joshuathomas/PycharmProjects/Fluency

# Step 1: Download lyrics (only needed once)
.venv/bin/python3 "Bad Bunny/1_download_lyrics.py"

# Step 2: Tokenise and count words
.venv/bin/python3 "Bad Bunny/2_count_words.py" \
    --batch_glob "Bad Bunny/bad_bunny_genius/batch_*.json" \
    --out "Bad Bunny/intermediates/2_vocab_evidence.json"

# Step 3: Merge elision pairs
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/3_merge_elisions.py"

# Step 4: spaCy lemmatisation
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/4_add_spacy_info.py"

# Step 5: Build vocab with cached translations (instant)
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/5_add_translations.py"

# Step 6: Fill translation gaps via API (~30 min first run)
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/6_fill_translation_gaps.py"

# Step 7: Deduplicate same-word entries
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/7_dedup_same_word.py"

# Step 8: Flag cognates
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/8_flag_cognates.py"
```

## Key concepts

- **S-elision**: Caribbean Spanish drops final -s and marks it with an
  apostrophe (`eres` -> `ere'`). Step 3 merges these back, keeping the
  elided spelling in `display_form`.
- **CACHE_ONLY mode**: Step 5 reuses translations from `intermediates/old_vocabulary_cache.json`
  without making API calls. Step 6 fills the remaining gaps with live
  Google Translate calls and saves progress every 100 translations.
- **Hallucinated lemmas**: spaCy sometimes invents fake infinitives for
  slang words (e.g. `loca` -> `locar`). Step 7 detects and removes these
  by scoring lemma candidates and keeping the most plausible one.

## Folder structure

```
Bad Bunny/
  1_download_lyrics.py      # Step 1
  2_count_words.py           # Step 2
  3_merge_elisions.py        # Step 3
  4_add_spacy_info.py        # Step 4
  5_add_translations.py      # Step 5
  6_fill_translation_gaps.py # Step 6
  7_dedup_same_word.py       # Step 7
  8_flag_cognates.py         # Step 8
  BadBunnyvocabulary.json    # Final output
  BadBunnyPPM.csv            # Word frequency CSV
  bad_bunny_albums_dictionary.json  # Album metadata
  bad_bunny_genius/          # Raw lyrics (Genius API output)
  Images/                    # Album cover art
  intermediates/             # Pipeline intermediate files
    2_vocab_evidence.json        # Step 2 output
    3_elision_mapping.json       # Elision merge mapping
    3_vocab_evidence_merged.json # Step 3 output
    4_spacy_output.json          # Step 4 output
    old_vocabulary_cache.json    # Previous vocab (translation cache source)
```

## Output format

Each entry in `BadBunnyvocabulary.json`:

```json
{
  "rank": 57,
  "word": "eres",
  "lemma": "ser",
  "display_form": "ere'",
  "meanings": [
    {
      "pos": "AUX",
      "translation": "are",
      "frequency": "1.00",
      "examples": [
        {
          "song": "5305010",
          "song_name": "A Tu Merced",
          "spanish": "Tu ere' una pitcher, pero yo estoy puesto pa' la nueva entrada",
          "english": "You are a pitcher, but I am ready for the new inning"
        }
      ]
    }
  ],
  "most_frequent_lemma_instance": true,
  "is_english": false,
  "is_interjection": false,
  "is_propernoun": false,
  "is_transparent_cognate": false,
  "occurrences_ppm": 1234.56
}
```
