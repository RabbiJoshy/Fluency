# hard_200 — a WSD panel that can actually resolve a change

200 hand-labelled OpenSubtitles occurrences, built 2026-08-23 because the older
144-item panel could not tell a 7pp win from noise. It scored the AUX tagset-bridge
fix at **−1 item** and called it noise; this panel scores the same fix at **+14**.

## Why it is different

**It is stratified on hard words, not sampled at random.** A random sample of deck
assignments is mostly *kilómetros*, *matemáticas*, *estadio* — words with one sense
where nothing is ever wrong, so the labels buy no information. Every item here is
drawn from one of three classes where errors actually live:

| `cls` | n | what it selects |
|---|---|---|
| `AUX` | 70 | menu headword is `haber, ser, estar, deber, poder, saber, querer, ir, tener, hacer, dar, ver` |
| `REFL` | 65 | menu contains both `X` and `Xse` (also catches noun/verb homographs: `vino`, `parte`, `cargo`) |
| `POLY` | 64 | menu has >= 12 leaves |

Sentences are drawn from `layers/subtitles/sentence_bank.jsonl` and **excluded if
they already appear in the deck**, so building prototypes from deck assignments and
scoring on this panel is leakage-free.

## How the labels work, and why not sense ids

`acceptable` is a list of `[pos, gloss, headword]` triples — **distinct meanings, not
sense ids and not menu positions.**

Three reasons:

1. **It is the metric that matches the product.** The card prints the gloss. Scoring
   sense ids counts `dijo` *to say* → *to say* as a regression, which is nonsense: on
   the old panel four of thirteen "breaks" were an identical gloss string under a
   different id.
2. **It survives a menu rebuild.** Positions shift and ids churn; `("VERB", "to have",
   "tener")` does not.
3. **Josh's actual criterion.** Several leaves are often acceptable; what matters is
   never showing an *un*acceptable one. Mean here is 1.73 acceptable meanings per
   item, against 2.28 sense ids per item on the 144 panel — tighter, because
   near-duplicate leaves collapse into one meaning.

`no_answer: true` means the menu does not contain the right reading at all — the
sense-inventory gap, which is a separate problem and should be measured around, not
through. Exactly 1 of 200 here (`esta` in a subtitle that dropped the accent on
`está`; the menu has no verb).

Labels are Claude's hand-grading, one pass, 2026-08-23. They are not adjudicated by a
second reader, so treat a 1–2 item difference as noise.

## Scoring

    .venv/bin/python3 pipeline/wsd_harness/panels/hard_200_2026-08-23/score.py

Reported 2026-08-23 (baseline is the menu prior — the *commonest* sense — NOT the
shipped v5 stack, which also carries Gemini gloss cosines and is not measured here):

| stratum | n | commonest sense | + POS filter | leaf prototypes | protos + POS |
|---|---|---|---|---|---|
| AUX  | 70  | 80.0% | 85.7% | 88.6% | 88.6% |
| REFL | 65  | 64.6% | **78.5%** | 61.5% | 69.2% |
| POLY | 64  | 56.2% | 57.8% | **68.8%** | 67.2% |
| ALL  | 199 | 67.3% | 74.4% | 73.4% | **75.4%** |

The two mechanisms are complementary and hit different classes: the POS filter is
worth +13.9pp on reflexive/homograph words and nothing on polysemous ones; leaf
prototypes are worth +12.6pp on polysemous words and *hurt* reflexives by 3pp.

## Against real v5

The table above baselines on the menu prior. Scored against the actual shipped stack
(Gemini gloss cosine + prior + POS filter, all three, `--min-gap` not applied):

| stratum | n | v5 | prototypes + POS |
|---|---|---|---|
| AUX  | 70  | 77.1% | **88.6%** |
| REFL | 65  | **81.5%** | 69.2% |
| POLY | 64  | **76.6%** | 67.2% |
| ALL  | 199 | **78.4%** | 75.4% |

**v5 wins overall, 19 fixes / 25 breaks.** Two things follow, and both matter more
than the headline:

1. **The gloss embeddings are worth far more than the 144-item panel implied.**
   There they ablated to ~4 items (~2pp), which is where "the embeddings are worth
   about 2 points" in `wsd_algorithm.md` comes from. Here they are worth **+11.1pp**
   over the prior (67.3% -> 78.4%). The old panel is too easy to see their value; do
   not quote the 2pp figure as a general claim.

2. **Prototypes land ~3pp *below* their own teacher, which is what distillation does.**
   These prototypes were pooled from v5's own assignments, so they can approximate v5
   and cannot out-inform it. The path is only worth pursuing with a *better* teacher
   than the system being replaced.

The AUX column is the exception and is partly an artifact: v5's AUX errors are heavily
`VERB:<EMPTY>` and `PHRASE:he's` picks, which the shipped `select_display_leaf` repair
fixes and this harness does not run. Some of that 11.5pp would close in production.

`leaf prototypes` = each sense represented by the mean BETO token vector of the deck
occurrences assigned to it (>= 2 occurrences; 3,390 of 96,279 leaves qualify), rather
than by its gloss text. Silver labels, from the current stack's own output.
