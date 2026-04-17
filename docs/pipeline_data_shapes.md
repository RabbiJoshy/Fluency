# Pipeline Data Shapes

Reference for the **shape** of every JSON layer the pipeline writes, plus the front-end-facing files. Use this when a front-end bug looks like a missing field — check here to see whether the field ever existed in that file at all.

Companion to [pipeline_schemas.md](pipeline_schemas.md) (which describes _what each step does_). This doc focuses on _what each output looks like_.

## Legend

- `{ ... }` = object, `[ ... ]` = array, `"..."` = string, `N` = number.
- `<key>` = dynamic key (word, id, etc.).
- `?` after a field = optional / may be absent.
- `|` inside a key = compound key (`word|lemma`, surface|lemma).
- Snippets are trimmed examples, not full records.

## Mode-branch summary

Most files have the **same shape** in normal mode (`Data/Spanish/layers/`) and artist mode (`Artists/<Name>/data/layers/`). Differences called out below:

| File | Differs by mode? |
|------|------------------|
| `word_inventory.json` | same shape |
| `examples_raw.json` | same shape |
| `example_pos.json` | same shape |
| `example_translations.json` | artist-only |
| `word_routing.json` | **yes** — normal has only clitic buckets, artist has full routing |
| `sense_menu/<source>.json` | same shape |
| `sense_assignments/<source>.json` | same shape |
| `sense_assignments_lemma/<source>.json` | same shape |
| `unassigned_routing/<source>.json` | artist-only |
| `clitic_forms.json` | same shape |
| `ranking.json` | artist-only |
| `lyrics_timestamps.json` | artist-only |
| `cognates.json`, `conjugations.json`, `conjugation_reverse.json`, `mwe_phrases.json` | normal-only (shared via `Data/Spanish/`) |

## Sense-source branch

From step 5c onward, sense data **branches by source** (SpanishDict vs Wiktionary) and lives in per-source subdirs. The branches run in parallel through 5c → 6a → 7a, then **reconverge at step 8 (assemble)** when the front-end vocabulary is built.

```
                     step 5c
                        │
              ┌─────────┴─────────┐
     sense_menu/             sense_menu/
     spanishdict.json        wiktionary.json
              │                   │
              ▼                   ▼
                     step 6a
                        │
              ┌─────────┴─────────┐
  sense_assignments/        sense_assignments/
  spanishdict.json          wiktionary.json
              │                   │
              ▼                   ▼
                     step 7a (lemma consolidation)
                        │
              ┌─────────┴─────────┐
 sense_assignments_lemma/  sense_assignments_lemma/
 spanishdict.json          wiktionary.json
              │                   │
              └─────────┬─────────┘
                        ▼
                     step 8a (assemble)
                        │
                        ▼
               vocabulary.json (+ index + examples)
```

---

# Phase 1-2: Acquire + Extract

## `vocab_evidence.json` *(artist-only, pre-layer)*
Location: `Artists/<Name>/data/word_counts/vocab_evidence.json`

```jsonc
[
  {
    "word": "amor",
    "corpus_count": 342,
    "examples": [
      { "id": "0", "line": "Mi amor eterno", "title": "Song Name" }
    ]
  }
]
```

## `mwe_detected.json` *(artist-only)*
```jsonc
{
  "mwes":       [{ "expression": "a veces", "translation": "sometimes", "count": 12 }],
  "candidates": [],
  "stats":      { ... }
}
```

---

# Phase 3: Normalize

## `vocab_evidence_merged.json` *(artist-only)*
Location: `Artists/<Name>/data/elision_merge/`. Same shape as `vocab_evidence.json` but adds `surface` to each example, recording the original (possibly elided) form:

```jsonc
[
  {
    "word": "veces",
    "corpus_count": 40,
    "examples": [
      { "id": "0", "line": "A vece' pienso", "title": "Song", "surface": "vece'" }
    ]
  }
]
```

---

# Phase 4: Route

## `word_routing.json` — **schema differs by mode**

### Artist mode: `Artists/<Name>/data/known_vocab/word_routing.json`
```jsonc
{
  "exclude": {
    "english":       ["accord", "air", ...],
    "proper_nouns":  ["puerto", ...],
    "interjections": ["eh", ...],
    "low_frequency": ["...": 1]
  },
  "biencoder": {
    "normal_vocab": [...],
    "conjugation": [...],
    "elision":     [...],
    "derivation":  [...],
    "shared":      [...]
  },
  "gemini":        ["perreo", "bellaca", "mera", ...],
  "clitic_merge":  { "tócame": "tocar", "dándote": "dar", ... },
  "clitic_keep":   ["acabarse", "irse", ...],
  "stats":         { "input_words": N, "min_freq": N, ... }
}
```

### Normal mode: `Data/Spanish/layers/word_routing.json`
Only clitic data; the rest is implicit (all in-inventory words go to bi-encoder).
```jsonc
{
  "clitic_merge":   { "abrirla": "abrir", ... },
  "clitic_orphans": ["acercarme", ...],
  "clitic_keep":    ["acabarse", ...],
  "stats":          { ... }
}
```

---

# Phase 5: Build Menus

## `word_inventory.json`
```jsonc
[ { "word": "amor", "corpus_count": 342 }, ... ]
```

## `examples_raw.json`
Keyed by **bare word** (the surface-stripped lookup form).

```jsonc
{
  "amor": [
    { "id": "t123", "spanish": "Mi amor eterno", "title": "Song", "surface": "amor" }
  ]
}
```

## `sense_menu/<source>.json` — branch point

Shared outer shape: `{ <bare_word>: [ { senses: { <sense_id>: { ... } } } ] }`.
Inner sense records differ by source:

### SpanishDict variant
```jsonc
{
  "banco": [
    {
      "senses": {
        "64a": {
          "pos":         "NOUN",
          "translation": "bench",
          "source":      "spanishdict",
          "headword":    "banco",
          "context":     "seat",
          "examples":    [{ "original": "Los bancos...", "translated": "The benches..." }]
        }
      }
    }
  ]
}
```

### Wiktionary variant
Adds `lemma` and a `morphology` block; drops `context`.
```jsonc
{
  "amarte": [
    {
      "lemma": "amar",
      "senses": {
        "a1b": {
          "pos":         "VERB",
          "translation": "to love",
          "source":      "wiktionary",
          "morphology": {
            "surface":     "amarte",
            "lemma":       "amar",
            "morph_tags":  ["infinitive"],
            "form_of":     "amar",
            "is_form_of":  true
          }
        }
      }
    }
  ]
}
```

## `conjugations.json` *(normal-mode only — shared verb tables)*
```jsonc
{
  "abandonar": {
    "translation":     "to abandon, leave behind",
    "gerund":          "abandonando",
    "past_participle": "abandonado",
    "tenses": {
      "Presente":  ["abandono","abandonas","abandona", ...],
      "Pretérito": [...],
      ...
    }
  }
}
```

## `conjugation_reverse.json` *(normal-mode only)*
```jsonc
{
  "habría abandonado": [
    { "lemma": "abandonar", "mood": "condicional", "tense": "perfecto", "person": "1s" }
  ]
}
```

## `mwe_phrases.json` *(normal-mode only)*
Keyed by **anchor word** → list of MWEs containing it.
```jsonc
{
  "que": [
    { "expression": "por que",  "translation": "why",    "source": "spanishdict" },
    { "expression": "tener que","translation": "to have to","source": "spanishdict" }
  ]
}
```

## `homograph_overrides.json` *(normal-mode only)*
```jsonc
{
  "_comment": "Manual overrides ...",
  "como":    { "como": 0.85, "comer": 0.15 }
}
```

---

# Phase 6: Build Assignments

## `example_pos.json`
Bare-word-keyed. Per example index, a POS string. `_example_ids` tracks which examples were tagged (for incremental re-tagging). `_meta` is step-version info.

```jsonc
{
  "amor": { "0": "NOUN", "1": "NOUN", "2": "NOUN" },
  "_example_ids": { "amor": ["t123", "t456"] },
  "_meta":        { "step": "tool_6a_tag_example_pos", "version": 2, ... }
}
```

## `example_translations.json` *(artist-only)*
Raw-line keyed.
```jsonc
{
  "Mi amor eterno": { "english": "My eternal love", "source": "gemini" }
}
```
`source` ∈ `genius | gemini | google`.

## `sense_assignments/<source>.json`
Unified method-keyed format. Bare-word → method → list of `{sense, examples}` records.
`examples` is a list of **indices into** `examples_raw.json[<word>]`.

```jsonc
{
  "amor": {
    "spanishdict-keyword":  [{ "sense": "64a", "examples": [0, 1, 5, 7] }],
    "spanishdict-biencoder":[{ "sense": "807", "examples": [2, 3] }]
  }
}
```

Methods (see `pipeline/method_priority.py`): `gap-fill` (50), `flash-lite-wiktionary` (50), `gemini` (40), `biencoder` (30), `keyword*` (10), `wiktionary-auto` (0). Methods co-exist additively per word.

---

# Phase 7: Consolidate

## `sense_assignments_lemma/<source>.json`
Same shape as `sense_assignments/` but keyed by **`word|lemma`** compound keys. This is where lemma consolidation actually takes effect.
```jsonc
{
  "amor|amor":     { "spanishdict-keyword": [{ "sense": "64a", "examples": [...] }] },
  "amamos|amar":   { "spanishdict-biencoder": [{ "sense": "a1b", "examples": [...] }] }
}
```

## `unassigned_routing/<source>.json` *(artist-only)*
Records raw example indices that had no POS-compatible sense during lemma split — used to render SENSE_CYCLE remainder buckets.
```jsonc
{
  "que|que": [1, 3, 6, 7]
}
```

## `ranking.json` *(artist-only)*
Ordered word list + per-word, per-sense easiness scores.
```jsonc
{
  "order":    ["que", "y", "no", "me", ...],
  "easiness": {
    "que": { "m": [ [score, score, ...] ] }
  }
}
```

## `cognates.json` *(normal-mode only)*
```jsonc
{
  "es|ser":  { "score": 0.0, "cognet": true },
  "amor|amor": { "score": 1.0, "cognet": true }
}
```

---

# Phase 8: Assemble

## `clitic_forms.json`
MWE-style layer keyed by 6-char hex ID. Tier-1/2 clitics (`word|base_verb` merged into base).

```jsonc
{
  "4163aa": {
    "base_verb":    "abrir",
    "lemma":        "abrir",
    "corpus_count": 7,
    "translation":  "to open",
    "assignments":  {
      "spanishdict-keyword": [{ "sense": "bf0", "examples": [0, 1, 2, ...] }]
    },
    "examples": [
      {
        "target":       "Esta tapa está tan apretada que no puedo abrirla.",
        "english":      "This lid is so tight I can't open it.",
        "source":       "tatoeba",
        "easiness":     59,
        "timestamp_ms": 12345  // artist-only
      }
    ],
    "id":      "4163aa",
    "base_id": "a3f1b2"
  }
}
```

## `lyrics_timestamps.json` *(artist-only)*
```jsonc
{
  "_meta": { ... },
  "timestamps": {
    "Song Name": {
      "La' palabra'": { "ms": 68910, "confidence": 0.95 }
    }
  }
}
```

---

# Front-end-facing files

These are what `js/vocab.js` actually reads. Understanding their shape is key for front-end debugging.

## Normal mode: `Data/Spanish/vocabulary.json`
Full deck in one file (older format, still in use).
```jsonc
[
  {
    "word": "que",
    "lemma": "que",
    "id":    "ed688d",
    "corpus_count": 32894,
    "most_frequent_lemma_instance": true,
    "meanings": [
      {
        "pos":         "CCONJ",
        "translation": "that, which",
        "frequency":   "1.00",
        "detail":      "that",
        "examples": [
          { "target": "...", "english": "...", "source": "tatoeba", "easiness": 4 }
        ]
      }
    ]
  }
]
```

## Normal mode: `vocabulary.index.json`
Slim version (no examples). Adds `mwe_memberships`.
```jsonc
[
  {
    "word": "que", "lemma": "que", "id": "ed688d",
    "corpus_count": 32894, "most_frequent_lemma_instance": true,
    "meanings": [
      { "pos": "CCONJ", "translation": "that, which", "frequency": "1.00", "detail": "that" }
    ],
    "mwe_memberships": [
      { "expression": "por que", "translation": "why", "source": "spanishdict" }
    ]
  }
]
```
**Note:** `meanings[*]` here has `{pos, translation, frequency, detail}` — **no `examples`**. Examples live in `vocabulary.examples.json`, indexed by id → meaning position.

## Normal mode: `vocabulary.examples.json`
Id-keyed; `m` is `[ [examples_for_meaning_0], [examples_for_meaning_1], ... ]`.
```jsonc
{
  "ed688d": {
    "m": [
      [
        { "target": "Tienes que...", "english": "You have to...", "source": "tatoeba", "easiness": 4 }
      ]
    ]
  }
}
```

## Artist mode: `Artists/<Name>/<Name>vocabulary.index.json`
Slim deck. **No `word`/`lemma`/`meanings` — those live in master.** Only artist-local data.
```jsonc
[
  {
    "id":           "ed688d",
    "corpus_count": 5376,
    "most_frequent_lemma_instance": true,
    "sense_frequencies": [0.33, 0.17, 0.5],
    "sense_methods":     ["spanishdict-keyword", "spanishdict-keyword", "spanishdict-keyword"],
    "unassigned":        true,                // ? present only if some examples are unassigned
    "sense_cycles":      [                    // ? SENSE_CYCLE remainder buckets
      { "pos": "SENSE_CYCLE", "cycle_pos": "ANY", "translation": "that", "allSenses": [...] }
    ]
  }
]
```

## Artist mode: `Artists/<Name>/<Name>vocabulary.examples.json`
Same `{ id: { m: [[...]] } }` outer shape as normal mode, but example records have **lyrics-specific fields**.
```jsonc
{
  "ed688d": {
    "m": [
      [
        {
          "song":               "3006211",
          "song_name":          "47 (Remix)",
          "spanish":            "Soy aguardiente...",
          "english":            "I'm aguardiente...",
          "translation_source": "gemini",
          "assignment_method":  "spanishdict-keyword",
          "timestamp_ms":       58170,
          "easiness":           41
        }
      ]
    ]
  }
}
```
**Front-end gotcha:** normal-mode example records use `target`/`english`, artist-mode use `spanish`/`english`. Same `english` key in both; the Spanish side differs.

## `Artists/vocabulary_master.json`
Shared across all artists. Id-keyed.
```jsonc
{
  "ed688d": {
    "word":   "que",
    "lemma":  "que",
    "senses": [
      { "pos": "CCONJ", "translation": "that" },
      { "pos": "CCONJ", "translation": "than" },
      { "pos": "CCONJ", "translation": "to" }
    ],
    "is_english":             false,
    "is_interjection":        false,
    "is_propernoun":          false,
    "is_transparent_cognate": false,
    "display_form":           null
  }
}
```

### Merge responsibility at load time
`js/vocab.js` joins:
- **artist index** (`id` + stats + sense_frequencies + sense_cycles)
- **master** (word, lemma, senses definitions, flags)
- **artist examples** (`m[meaning_idx]` list of lyric records)

If a flashcard is missing a field in the front-end, trace it back: is it in the master record? In the artist index? In the examples file? The three-way join is where field absence typically surfaces.
