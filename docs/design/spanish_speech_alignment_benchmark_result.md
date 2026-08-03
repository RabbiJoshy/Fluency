# Spanish Speech alignment + semantic-gate benchmark

## Decision

Proceed to a larger **candidate-validation** benchmark, but do not run this
across the full corpus or use it to estimate prominence yet.

The best architecture for corpus or television examples is simpler than the
proposed two-stage requirement:

1. literal bilingual cues cheaply retrieve candidates;
2. a conservative closed-set semantic gate validates the exact SpanishDict leaf
   and its context;
3. pretrained word alignment is optional diagnostic or consensus evidence, not
   a mandatory gate.

This result applies to sense-tied example retrieval. It does **not** make the
cue-selected subset an unbiased sense-frequency sample.

## Fixed benchmark

The panel was frozen and manually labelled before either prediction stage:

- 60 SHA-256-selected candidates from polysemous Spanish surfaces;
- sense-stratified through the full audit's bounded per-leaf samples;
- 40 valid exact-leaf attachments and 20 invalid attachments;
- every candidate includes the Spanish sentence, aligned English sentence,
  proposed stable SpanishDict ID, full menu, translation, context, and canonical
  dictionary example.

The raw string method therefore begins at 66.7% precision on this panel.

## Results

| Method | Accepted | Precision | Recall of valid candidates | Panel coverage |
|---|---:|---:|---:|---:|
| Raw string cue | 60 | 66.7% | 100.0% | 100.0% |
| SimAlign strict intersection | 40 | 82.5% | 82.5% | 66.7% |
| SimAlign IterMax | 44 | 81.8% | 90.0% | 73.3% |
| Semantic same-leaf, medium/high | 23 | **100.0%** | 57.5% | 38.3% |
| Semantic same-leaf, high only | 20 | **100.0%** | 50.0% | 33.3% |
| Strict alignment + semantic medium/high | 19 | **100.0%** | 47.5% | 31.7% |

SimAlign used `bert-base-multilingual-cased` revision
`3f076fdb1ab68d5b2880cb87a0886f315b8146f8`, layer 8, on CPU. All 60 rows
completed in six seconds after model loading. The semantic gate used
`gemini-3.5-flash-lite`, temperature 0, in ten batches of six.

Primary method references:

- [SimAlign](https://arxiv.org/abs/2004.08728)
- [AWESOME-Align](https://aclanthology.org/2021.eacl-main.181/)

## What each stage catches

Word alignment correctly rejects many wrong-token cues, but it cannot resolve an
English word's meaning or choose among close SpanishDict leaves. It therefore
misses the 95% precision gate by a wide margin.

The semantic gate rejected every manually invalid candidate in this panel. It
also rejected many valid examples by choosing a translation-equivalent but
different SpanishDict leaf. That is acceptable for a high-precision example
bank: when stable leaf identity is not distinguishable, abstention is safer than
silently merging dictionary senses.

Examples retained by the semantic gate include:

- `casero` → `landlord`: `Y mi casero.` / `And landlord.`
- `banco`-style concrete cases represented in the prior audit;
- `dominio` → `knowledge`: `¿era de dominio público ...?` / `was it common knowledge ...?`
- `vano` → `in vain`: `He usado el nombre del Señor en vano.`
- `cargas` → `to bear`: `Cargas con tanta responsabilidad como yo.`

It correctly rejected demonstrated contaminations such as `hacer`/`think`,
`daba`/`press`, `mano`/`way`, `maría`/`grass`, and `carga`/`blame`.

## Product consequence

Keep the four Speech outputs separate:

- **Sense inventory:** SpanishDict stable leaves.
- **Canonical examples:** exact SpanishDict examples, requiring no WSD.
- **Prominence:** dictionary order or a separately validated random-occurrence
  estimator; never the cue-retrieved subset.
- **Television/corpus examples:** retrieval followed by conservative semantic
  exact-leaf validation, with alignment available as audit evidence.

Before using the semantic gate at scale, expand to a second manually reviewed
panel of at least 200 rows, stratified by POS, surface frequency, cue length,
translation-equivalent leaves, proper names, and subtitle alignment quality. The
release gate remains at least 95% exact-leaf precision.
