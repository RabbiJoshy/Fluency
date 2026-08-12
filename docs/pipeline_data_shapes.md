# Pipeline Data Shapes

Reference for the **shape** of every JSON layer the pipeline writes, plus the front-end-facing files. Use this when a front-end bug looks like a missing field — check here to see whether the field ever existed in that file at all.

Companion to [pipeline_schemas.md](pipeline_schemas.md) (which describes _what each step does_). This doc focuses on _what each output looks like_.

## Legend

- `{ ... }` = object, `[ ... ]` = array, `"..."` = string, `N` = number.
- `<key>` = dynamic key (word, id, etc.).
- `?` after a field = optional / may be absent.
- `|` inside a key = compound key (`word|lemma`, surface|lemma).
- Snippets are trimmed examples, not full records.

## Evidence Store v1 — canonical Artist corpus base

Artist step 2 now dual-writes a language-neutral, occurrence-first evidence
store under `Artists/{lang}/{Name}/data/evidence/`. The historical word-keyed
JSON files remain compatibility materializations while downstream steps migrate.
The store is one logical ledger but physically sharded, so no giant mutable JSON
file must be rewritten.

```text
data/evidence/
  ledger/runs/<run_id>/{segments.jsonl,occurrences.jsonl,manifest.json}
  overlays/<layer>/<run_id>.jsonl
  snapshots/<legacy-layer>/runs/<run_id>/{artifact.json,manifest.json}
  profiles/current.json
  migrations/legacy_example_ids.json
```

- A `segment_id` identifies one persisted source line independent of its lyric
  line number. Repeated identical chorus lines remain distinct segments.
- An `occurrence_id` identifies one frozen raw token use inside a segment.
  Revised elision/tokenization logic emits new analysis-unit claims; it does not
  rewrite raw occurrences.
- Overlay claims carry method/run provenance, semantic input fingerprints,
  confidence, and assert/abstain/retract operations. Competing methods coexist;
  a build profile chooses the active view.
- `overlays/vocal_artifact/<run_id>.jsonl` carries occurrence-level descriptive
  labels such as `adlib`, `echo`, and `stutter`. Classification is deliberately
  separate from `profiles/current.json.policies.vocal_artifact.excluded_labels`:
  selecting another method or turning the policy off never destroys evidence.
- `overlays/usage_tag/<run_id>.jsonl` carries descriptive contextual labels
  independently of sense assignment. The fixed v1 taxonomy is `slang`,
  `regional`, `figurative`, `vulgar`, `idiom`, `loanword`, `proper_noun`,
  `interjection`, and `onomatopoeia`. Historical Gemini `type` values are kept
  with prompt/run provenance; `other` remains raw evidence instead of becoming
  an unlimited catch-all tag. `construction`, `pos`, and `pos_verdict` remain
  structured source assertions rather than new tag names.
- `Artists/curations/usage_tag_overrides.json` supports both global and exact
  occurrence corrections. A global correction is appropriate only when the
  judgment is invariant across every use of the matched form. Occurrence
  corrections target a persisted `occurrence_id`, apply after global
  corrections, and are materialized separately under
  `overlays/usage_tag_override/`; model evidence is never relabelled as human
  curation.
- `step_2e_materialize_corpus` first proves a no-exclusion view equals the
  immutable step-2 baseline, then writes `vocab_evidence.json` from the active
  profile. All later legacy layers and the compact app deck therefore inherit
  exact occurrence-level exclusions without loading the ledger in the browser.
- Compatibility producers not yet converted to granular claims (currently
  elision, routing/noise, POS, menus, and assignment JSON) archive every
  content-distinct output as a content-addressed snapshot before advancing the
  profile pointer. A force rerun therefore does not erase the prior result.
- `profiles/current.json.method_priorities` may rank any adapter method ID, so a
  local/non-Gemini classifier does not require hard-coding its name in assembly.
- Removing a source line writes a tombstone in the next snapshot. Re-adding it
  restores the same identity when it can be reconciled; history is not deleted.
- Language is part of base identity. A sense inventory may be SpanishDict,
  Wiktionary, another provider, or `null`.
- `Artists/{lang}/evidence/registries/cards.json` owns card identity separately
  from mutable surface/lemma properties. Exact aliases, occurrence overlap, and
  explicit merge migrations preserve learner progress; ambiguous splits are not
  guessed.
- `Artists/{lang}/evidence/registries/senses.json` likewise owns per-card sense
  identity; provider IDs and gloss/POS/context revisions become aliases/labels.
  Occurrence overlap can reconcile a changed provider, while ambiguous splits
  require an explicit progress migration.

The same segment/occurrence envelope can accept Speech or parallel-corpus input
(`aligned_texts` on a segment), but Speech has not been rebuilt onto this store.

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
| `unassigned_routing_evidence/<source>.json` | artist-only stable-ID companion |
| `clitic_forms.json` | same shape |
| `ranking.json` | artist-only |
| `lyrics_timestamps.json` | artist-only |
| `cognates.json`, `conjugations.json`, `conjugation_reverse.json`, `mwe_phrases.json` | normal-only (shared via `Data/Spanish/`) |
| `derivational_relations.json` | shared Spanish layer, consumed by both modes |

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
      {
        "id": "0",
        "line": "Mi amor eterno",
        "title": "Song Name",
        "segment_id": "seg_...",
        "occurrence_ids": ["occ_..."]
      }
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
    {
      "id": "t123",
      "segment_id": "seg_...",
      "occurrence_ids": ["occ_..."],
      "spanish": "Mi amor eterno",
      "title": "Song",
      "surface": "amor"
    }
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
  "_meta":        { "step": "tool_6a_tag_example_pos", "version": 4, ... }
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
Unified method-keyed format. Bare-word → method → assignment records. The
integer `examples` list remains for compatibility; `example_ids` is positionally
aligned and stable `occurrence_refs` is authoritative when present.

```jsonc
{
  "amor": {
    "spanishdict-keyword":  [{
      "sense": "64a",
      "examples": [0, 1],
      "example_ids": ["seg_a", "seg_b"],
      "occurrence_refs": [
        {"occurrence_id": "occ_a", "example_id": "seg_a", "example_index": 0}
      ]
    }],
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

## `unassigned_routing_evidence/<source>.json` *(artist-only)*
Stable companion materialized back to indices by the current builder.

```jsonc
{
  "que|que": [
    {"example_index": 1, "example_id": "seg_a", "occurrence_ids": ["occ_a"]}
  ]
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

## `derivational_relations.json` *(shared Spanish layer)*

Distinct derived lexemes are linked, not collapsed. The builder copies the
record to the card/index as `derivation_relation`.

```jsonc
{
  "_meta": { ... },
  "relations": {
    "besito": {
      "base_lemma": "beso",
      "relation": "diminutive",
      "source": "curated"
    }
  }
}
```

Automatic records require both a recognized suffix pattern and compatible
English gloss evidence. Curated overrides can include or exclude exact lemmas.
The relation does not share IDs, progress, frequency, or senses with the base.

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
    "extra_category": "unresolved",       // ? explicit routing abstention; Artist Extra
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
          "surface":            "aguardiente'", // ? exact non-canonical occurrence spelling
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

`extra_category` is a routing result, not a frequency label. `core` means the
pipeline has positive Spanish lexical/morphological evidence and belongs in
Artist Main. `loanword`, `english`, `proper_noun`, `cognate`, `noise`, and
`unresolved` belong in Artist Extra. `unresolved` specifically means routing
abstained (typically a low-frequency form with no positive lexical evidence);
it must not be silently promoted to `core`.
**Front-end gotcha:** normal-mode example records use `target`/`english`, artist-mode use `spanish`/`english`. Same `english` key in both; the Spanish side differs. Artist `surface` is emitted only when the exact lyric occurrence differs from the restored canonical word used by POS/WSD; highlighting must prefer it and must not infer the restoration from the sentence.

## Shared artist sense registers

Artists opt into a configurable lexical register in `artist.json`:

```json
{ "sense_registers": ["reggaeton"] }
```

`pipeline/artist/tool_5d_build_shared_sense_registers.py` derives
`Artists/<language>/sense_registers/<register>.json` from model-proposed lexical
senses supported by member artists. The register clusters near-duplicate
same-POS glosses, retains the original artist/method/prompt/occurrence
provenance, and injects only locally occurring words into the target artist's
SpanishDict menu. SpanishDict remains the base menu.

Membership policy is separate from the artist tag and lives in
`Artists/<language>/sense_registers/policy.json`. A member can be a
`contributor` or a consumer only. For the reggaeton register, Bad Bunny,
J Balvin, Young Miko, and Rels B contribute; Rosalía and Spanish Test Playlist
consume without seeding. Contributions with two distinct stable occurrences
or two supporting contributors are `established` and may enter another
artist's menu. A singleton remains `provisional`: it is withheld from new
contexts, but may support `shared-register-auto` when the complete lyric line
matches exactly and only one registered sense matches. Evidence IDs are
deduplicated before counting, so repeated runs and playlist copies cannot
manufacture support.

An exact cross-artist Genius song-line match may be assigned deterministically
as `shared-register-auto`. A different lyric context merely receives the
registered candidates and still needs POS filtering or WSD. This distinction
prevents repeated proposal variants without treating a word's meaning as
artist-invariant.

Register growth is deliberately non-transitive. New artists enter as consumers
and become contributors only after review; one artist supplies at most one
supporting-artist vote. Artists may belong to multiple registers, but evidence
thresholds are computed independently and cannot be pooled across overlapping
genres. Locale, era, and subgenre can rank candidates, never assign them. A
reviewed contradiction moves a sense to disputed status and suspends automatic
reuse while retaining its source provenance and identity aliases. The policy
file records the full conflict, lifecycle, and extension contract so expanding
beyond the initial artists does not silently relax WSD precision.

## `Artists/vocabulary_master.json`
Shared across all artists. Id-keyed.
```jsonc
{
  "ed688d": {
    "word":   "que",
    "lemma":  "que",
    "senses": [
      { "pos": "CCONJ", "translation": "that", "sense_id": "64a" },
      { "pos": "CCONJ", "translation": "than", "sense_id": "807" },
      { "pos": "CCONJ", "translation": "to", "sense_id": "bf0" }
    ],
    "is_english":             false,
    "is_interjection":        false,
    "is_propernoun":          false,
    "is_transparent_cognate": false,
    "display_form":           null
  }
}
```

`sense_id` is the durable identity for per-sense learner progress. Standard
meanings and artist-master senses retain source-menu IDs through assembly.
Equivalent senses that collapse into one display row keep one canonical ID and
place the others in `sense_id_aliases`. Legacy artist-master senses with no
source-menu row receive reproducible `generated:artist-master:*` IDs; if an
authoritative source ID later appears it becomes canonical and the generated ID
is retained as an alias. `js/knowledge.js` also recognises the old content
signature of POS + translation + context and migrates it on the learner's next
answer. Future rebuilds must preserve both canonical IDs and aliases; an
intentional ID change requires a matching `ItemProgress` migration. This is a
load-bearing front-end/data contract, not display metadata.

### Merge responsibility at load time
`js/vocab.js` joins:
- **artist index** (`id` + stats + sense_frequencies + sense_cycles)
- **master** (word, lemma, senses definitions, flags)
- **artist examples** (`m[meaning_idx]` list of lyric records)

If a flashcard is missing a field in the front-end, trace it back: is it in the master record? In the artist index? In the examples file? The three-way join is where field absence typically surfaces.
