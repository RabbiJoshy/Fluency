# Fluency — the session brief

## The one goal

**Work out when embeddings+BETO does not know that it is wrong, and make it escalate then.**

That is the hard problem and the only goal. A second, related gap: when escalation
does fire it is a closed-set `{"id": ...}` pick, so it *cannot* invent a sense even
when no menu entry fits. Design intent is that escalation is sometimes invention.
Both halves are in scope.

## Definition of done

An explicit change, described to Josh, tested, and shown to improve **named
examples** he can look at. Nothing counts until that last clause. Not commits, not
refactors, not bug fixes, not coverage numbers.

## Cadence — Josh must see this happening

The last session ran for hours in one block and produced a wall of text at the end.
Josh could not see progress, could not steer, and could not stop a mistake early. He
had to drag the actual accuracy number out over five messages. Do not repeat that.

**Report after every discrete unit of work.** One measurement, one build, one
experiment — then report. Never chain two of them silently. If a report would say
"still working", say that rather than staying quiet.

**Every report is short and has these four things:**

1. What was done (one line)
2. **The number** — `n correct / n graded`, or the count that moved
3. A concrete example — an actual rendered card, not a summary of cards
4. What is next, or the decision needed

Ten lines is plenty. If it is longer than a screen, it is a status dump, not a report.

**Decisions go back to Josh one at a time, close to the work.** Do not batch four
decisions into one question at the start and then vanish for an hour — that is what
happened and it produced consent to a plan he could not yet evaluate.

**When offering options, do not mark them all "recommended".** Last time every option
carried a recommendation, Josh picked all three, and that was steering dressed as a
choice. Give the options with the evidence, state at most ONE lean, and say plainly
what you do not know.

**Stop and ask before doing anything the brief does not name.** Not "flag it in the
final summary" — stop, ask, wait. This includes: changing the corpus, changing a
flag, spending money, deleting anything, or fixing a bug you tripped over.

**Verify before reporting success.** A background job's exit code is not proof; read
the log. A rebuild that "completed" was reported as working when it had failed
instantly on a bad flag.

## First action — measure, then STOP

Do this before writing any fix. There are four checkpoints. **Report and wait at
each one** — do not run two in a row.

1. Build the deck **with the real confidence gate**. Do NOT pass `--escalate all`;
   that bypasses the trigger and makes the entire question unobservable. It is how
   the previous session wasted itself.
   → **CHECKPOINT 1** — report: how many escalated vs decided locally, and the band
   distribution. That single number tells Josh whether the trigger is even firing.
2. Also capture a **local-only** pass (`step_6e` with no `--escalate`) over the same
   occurrences. Two decisions per occurrence, same inputs.
   → **CHECKPOINT 2** — report: on how many of the 1,843 do local and escalated
   *disagree*? Show three real disagreements as rendered cards. Ask Josh whether to
   grade the disagreement set first or a random sample first.
3. Grade by hand. There are **1,843 WSD decisions** — small enough to review
   properly. Do not raise `max_examples`; the sample size is deliberate.
   → **CHECKPOINT 3** — report the running number every ~50 cards graded, not once
   at the end. `n correct / n graded` plus any new error class as it appears.
4. Return one table. Every error gets a mode and a named cause:

   | mode | meaning | when |
   |------|---------|------|
   | **2**  | a better sense existed in the menu and it picked wrong without escalating | **PASS 1 — the whole of it** |
   | **1b** | menu had no fitting sense, and it failed to escalate | **PASS 2 — not before** |
   | 3      | it escalated and Gemini picked wrong | low priority |
   | 1a     | word has no menu at all | out of scope, ignore |

   **Pass 1 is mode 2 only: picking the wrong leaf when a better one was sitting in
   the menu.** Classify mode-1b errors as you meet them and count them, but do not
   work on them. They are pass 2, and pass 2 does not start until pass 1 has shipped
   a measured improvement Josh has seen in his deck.

5. Then answer, with evidence: **does any available signal separate the errors from
   the correct picks?** Self-reported model certainty has failed three times — do not
   try it a fourth. Untried candidates: disagreement between the two independent
   methods (embeddings vs BETO), the shape of the whole score distribution rather
   than a top-two gap, menu size / polysemy, a forced-choice probe.
   Report it as separability at a fixed escalation budget (what share of errors is
   caught if you escalate the worst N%), not as an anecdote.

   → **CHECKPOINT 4** — the table, plus the separability result.

Only after Josh has seen that table do you propose a change. Propose ONE. Say what
you expect it to move and on which named cards, get his yes, then build it.

## Out of scope — do not touch

Elisions. Proper nouns. Credits. Translations. Plumbing. Refactors. Test repairs.
MWEs. Duplicate senses. Register reuse.

**If you find a bug, add it to a list and keep going. Do not fix it.** A session was
lost to exactly this: each fix was individually justified and collectively fatal.

Bugs are **paused, not cancelled**. The list gets worked through once — and only
once — all of these are true:

1. Pass 1 has produced a change,
2. it measurably improved mode-2 accuracy on named cards,
3. it has been rebuilt into the deck under a **new named run** (below), and
4. Josh has looked at it in the app and said so.

Until all four hold, the list only grows.

## Every pass ships under a new named run

Josh has to be able to tell, card by card, which run produced what. A change that
cannot be identified on the back of a card did not happen.

Any change to the classifier bumps the version — do not reuse `v1`:

| what | now | next |
|------|-----|------|
| `PROMPT_ID` (`step_6e`) | `sd-beto-cal-v1` | `sd-beto-cal-v2` |
| `PROMPT_ID_ESC` | `sd-beto-cal-esc-v1` | `sd-beto-cal-esc-v2` |
| `METHOD` | `spanishdict-beto-cal-v1` | `spanishdict-beto-cal-v2` |

Then register the new ids in `config/prompt_registry.json` (family, tier, notes), or
the card panel falls back to "provenance not recorded".

`prompt_id` and `run_ts` are already carried on every meaning and example, and
`run_ts` already stores minutes (`2026-08-18T23:31Z`). **But the card only prints the
date.** `fmtTs` in `js/flashcards.js` (~line 6184) formats
`{year, month, day}` and drops the time — so two runs on the same day are
indistinguishable to Josh, which is exactly the thing he needs to see.

Fix it to render **date + HH:MM**. Note `js/` is Codex's surface per `CLAUDE.md`, so
this is a deliberate cross-boundary edit: make it, keep it to that function, and say
so in the commit.

## Rules

- State which part of the goal a piece of work serves *before* starting it. If you
  cannot say it in one sentence, you are drifting — stop and ask.
- One variable per pass.
- The rendered card is the only truth — `pipeline/tool_8j_render_cards.py`, never the
  deck JSON. `js/` repairs a lot at render time.
- You are the judge. Do not build an automated grader; it cost £10 and produced a
  4.7pp regression that did not exist.
- Report accuracy as *number correct / number graded*. Never report activity.
- Long runs go in the background, not handed back as commands to paste.
- Price any model spend before spending it.

## Reference

Test playlist: 17 songs, 980 lines, 6,897 occurrences, 2,020 kept as examples,
532 unique sentences, **1,843 WSD decisions**. It is a throwaway deck whose only
purpose is being reviewable in the app.

Stack: embeddings + BETO decide with a confidence band; low confidence escalates to
`gemini-3.5-flash-lite`. Cost of escalating everything is ~$0.08, so cost is not the
constraint — knowing *when* is.

Rebuild: `run_artist_pipeline.py --artist "Artists/spanish/SpanishTestPlaylist"
--from-step 2 --to-step 5b`, then `step_6e_assign_senses_calibrated`, then
`step_7a_map_senses_to_lemmas`, then `step_8b_assemble_artist_vocabulary
--prompt-policy testplaylist-beto-cal-pinned`.

Known dead ends — do not redo: self-reported certainty (3×, incl. a local 8B).
Trained clitic classifier. `used with` as a ranking feature. Menu position.
Tuple-sum aggregation. Hubness offset. 8B generative WSD. Jina/Cohere rerankers.
Spanish examples as sense vectors. Pairwise yes/no prompting. WordNet as inventory.
English line in the escalation prompt (+1.6pp, noise). spaCy DET gate. Coarsening
the inventory (ceiling +3pp). Automated LLM grading.

Known-unfixable by any classifier, so do not chase: SpanishDict inventory defects —
`fumar` has one "to smoke" leaf permanently tagged *tobacco*; `dejar` has no
`dejar de` = "to stop"; `platón` has no *Plato*. In a 78-card graded sample, 8 of 10
errors were of this kind.

## Handoff rule

If you write a handoff at the end of a session, it may contain measurements and open
questions **only**. Never a task list. A brief written by an agent that just went
down a rabbit hole hands the next agent the rabbit hole, with the authority of a
checked-in file. That is what happened three sessions running.
