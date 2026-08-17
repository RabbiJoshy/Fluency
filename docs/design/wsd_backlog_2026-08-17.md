# WSD backlog — loose notes, 2026-08-17

Not a queue. GitHub Issues is the live backlog (COLLABORATION.md rule 3), but
`gh` is not installed on this machine and there is no `GITHUB_TOKEN`, so these
could not be filed. Written here rather than in `TODO.md`, which is a frozen
historical snapshot. **Move these to Issues when GitHub access exists.**

All would be `owner: claude`. Held at `horizon: soon` — Josh wants upstream
sorted first, and nothing here is authorised to start.

---

## 0. BLOCKER, found while auditing the first playlist run

**Turn off the hubness offset in step_6d / step_6e.** `size: S`

`una` was classified as a verb in the test playlist. Root cause: the hubness
offset inverts a correct answer.

| sense | raw cosine | hub | adjusted | rank |
|---|---|---|---|---|
| `un`/DET "a" — correct | **0.7443** (1st) | **0.8201** (highest) | −0.0758 | 6th |
| `unir`/VERB "to bind" | 0.7397 (2nd) | 0.7908 | −0.0511 | **1st** |

The DET leaves carry the highest hub values because `"una" (DET): a — singular`
is a semantically empty gloss that genuinely sits near everything. Hubness
correction penalises exactly that, so it penalises the correct answer hardest.
**For a high-frequency function word, "near everything" is the truth, not an
artifact.** The correction cannot distinguish the two cases.

Measured on 16,016 target-present gold items:

| | accuracy | yield@99% |
|---|---|---|
| hub on (shipping) | 80.06% | 22.7% |
| hub off | **80.34%** | **23.2%** |

Net negative, and the gold *understates* the harm: `una`'s menu is 13 verb
leaves against 3 DET leaves, so leaf-count-weighted gold scores "call `una` a
verb" as correct much of the time.

Why it survived: validated at +1.3pp on the 150-sentence panel, which is one
sentence per word by design, so function words are ~1 item each. Two known
biases masked each other.

Related: **step_6e ships every assignment regardless of band** (7 of the 8 `una`
claims were correctly marked `low`). That policy is inherited from step_6d and
suits speech mode, where candidates are unlimited and discarding is free. On a
fixed lyric corpus it is actively harmful. Consider a per-word top-N gate.

---

## 1. Cluster near-duplicate sense leaves `size: M`

**55.2% of same-tuple leaves are mergeable at cosine ≥ 0.93.** Real examples:
`que` "who" ← ["which", "that", "who", "that"]; `no` "no" ← ["not", "non-"].
This is Josh's money/cash case.

Free: the 95,003 gloss vectors are already cached, so clustering is a local
matmul with no API. Explains why 28.6% of measured tuple "errors" put an
*identical gloss* on the card — those are duplicate leaves, not errors.

Not really a WSD change; an inventory cleanup that makes every downstream method
look better and stops cards showing three near-identical rows.

## 2. Test SpanishDict `used with` as a calibrator feature `size: M`

**All 96,279 senses carry a context note, and `gloss()` already appends it
verbatim into the embedded sense vector** — so it has been feeding WSD all
along, as undifferentiated prose. 5,855 are explicit `used with X` (`es` → "used
with *de*", `lo` → "used with *que*", `para` → "used with *con*").

| | |
|---|---|
| gold items whose menu carries a companion note | 19.0% |
| ...where the note discriminates between tuples | 17.0% |

Mostly function words, which is where the gloss method is weakest.

**Invert Codex's sequencing.** It proposed exposing the metadata on the card
first and integrating later. Test it as a calibrator feature first: no UI, one
day, and it answers whether the structured form beats the prose already
embedded. If it moves yield, the UI work is justified; if not, it is saved.

Skip the staged same-sentence < clause < dependency ladder initially. Start with
the literal companion test. Precedent: the clitic gate, where a regex captured
100% of the yield headroom and a trained model would have added nothing.

## 3. Keep construction-harvested sentences out of frequency estimation `size: S`

Codex's warning, and the same failure hit twice independently today (leaf-count
weighting; Sinkhorn pool composition). If sentences are harvested *because* they
contain a construction and sense frequencies are then estimated from them, the
prior is circular. Make it structural, not a comment.

## 4. Wire the Gemini cascade into step_6e as an escalation stage `size: M`

Measured: rescues 81.3% of what embeddings get wrong, damages 5% of what they
get right, flat 83–100% across confidence deciles. $0.28/10k, ~5.6¢ per deck.
The 29% of playlist assignments in the `low` band are its target population.

## 5. Recalibrate on lyric data `size: M`

Every number in the stack is trained and measured on dictionary examples. The
cascade can generate lyric labels cheaply to recalibrate against.

## 6. Menu should offer previously invented senses `size: M`

Josh's (B). Needs a look at how `reales` ended up carrying both "money" and
"cash" — likely the same duplicate-leaf problem as item 1.

## 7. Generate `used with` tags when inventing senses `size: M`

Josh's (C). Especially artist mode, where one word rarely captures the meaning
(`rompe la losa`). Depends on items 1 and 2 reporting first.

---

## Deliberately NOT filed

- **Trained clitic classifier** — measured dead. A perfect oracle is worth
  +4.3pp on the production slice and the `se`-only regex already captures 100%
  of the *yield* headroom (regex and oracle both 24.5%).
- **Dependency/constituency ladder for `used with`** — premature until the
  literal companion test reports a number.
