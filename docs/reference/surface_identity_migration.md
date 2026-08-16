# Surface-form card identity — what changed, and how to undo it

Done 2026-08-14/15. Read this first if progress looks wrong, cards are missing,
or the two modes stop agreeing.

## What changed in one line

A card's ID used to be `md5(word|lemma)[:6]`. It is now
`md5("surface/v2:" + surface)[:8]`, in **both** speech and artist mode.

## Why

Lemma is a classifier decision, so identity was a decision. Re-running sense
assignment destroyed **1,185 card IDs** and recorded 22 migrations — learner
progress silently orphaned by a routine operation. Only 52 *surfaces* vanished in
the same run, so keying on the surface cut the blast radius ~23x. Surfaces come
from the corpus; nothing downstream can revise them.

Two claims in `docs/design/spanish_speech_layer_restructure.md` did **not**
survive re-derivation and should not be relied on:

- "1,126 fabricated lemmas" — 89% of those were headwords SpanishDict itself
  lists for that surface (`nada→nadar`, `así→asir`). Only 4 were fabrications.
- "15% of corpus mass split proportionally" — drops to 3.1% once lemmas come
  from `word_inventory.known_lemmas` rather than the assignment layer.

The case rests on the re-run blast radius above, not on those.

## Where the backups are

| what | where | in git? |
|---|---|---|
| pre-migration speech deck | snapshot `2026-08-12_pre_slice` | no — `Data/Spanish/Intermediates` is gitignored |
| pre-migration artist decks + master | commit `041c4384` | **yes** |
| Sheets before speech migration | `backend/local/backup_pre_surface_migration_2026-08-14T0906Z/` | no — `backend/local/*.json` is gitignored |
| Sheets before artist migration | `backend/local/backup_pre_artist_migration_2026-08-15T1035Z/` | no |
| pre-rekey artist master | `Artists/spanish/vocabulary_master.pre_surface_rekey.*.json` | no |
| old `word\|lemma` progress rows | **still on the Sheet**, never deleted | n/a |
| old card IDs and their aliases | `Artists/spanish/evidence/registries/cards.json`, `status: merged` + `superseded_by` | yes |

The pushes ran **without `--replace`**, so nothing was deleted from Sheets. The
pre-migration rows are still there, inert because no card matches them. That is
the fastest rollback: revert the deck and the old rows light up again.

## Rolling back

```bash
git revert --no-commit 2ff659c6..HEAD && git commit   # or reset to 041c4384 for artist too
```

Then rebuild the decks. Progress needs nothing: the old rows were never removed.
`Data/Spanish/id_migration.json` maps old ID -> new, and the app applies it once,
gated on `id_migration_v3` in localStorage — clear that key to re-run it.

## The four things that went wrong, and their symptoms

**Deck changed but the app didn't.** Deck JSON is cache-first and *not* `?v=`
tagged, so `CACHE_NAME` in `service-worker.js` is the only thing that invalidates
it. Any rebuilt deck needs that bump. Symptom: correct data on disk, stale in the
browser. Fix: bump `CACHE_NAME`, unregister the service worker, reload.

**Speech showed zero progress after the artist migration.** `step_8a` seeded
`make_surface_id`'s collision set with the reserved artist master IDs. Once
artist minted from the surface too, every shared surface looked like a collision
and speech slid one hex character off its own ID (`d6ffed1a` -> `6ffed1a9`).
Surface IDs now have their own collision space. Symptom: IDs that are the right
hash shifted by one character.

**Every lemma row silently dropped on push.** `bulkSave`'s first line is
`if (!row.user) return;` — a drop before it looks at the type, reported as
"0 updated, 0 inserted" rather than an error. Any row built from scratch must
carry `user`.

**Apps Script timed out on large pushes.** It re-read the whole sheet twice per
row and appended one row at a time. `bulkSave` now builds one index per call and
writes appends in a single `setValues`. **This lives in
`backend/GoogleAppsScript.js` and must be deployed manually** — the repo copy
does nothing until you paste and deploy it.

## Verifying it is still healthy

```bash
python3 -c "
import json
idx=json.load(open('Data/Spanish/vocabulary.index.json'))
rows=json.load(open('backend/local/Progress.json'))['rows']
sp={r['itemId'] for r in rows if r.get('mode')=='normal' and r.get('itemType')=='word'}
d={e['word'].lower():e['id'] for e in idx}
print('deck cards with a progress row:', sum(1 for i in d.values() if 'es0'+i in sp))
print('id lengths:', {len(i) for i in d.values()})   # must be {8}
"
```

Two invariants worth checking after any deck rebuild:

- **every card ID is 8 hex.** A 6-hex ID means something minted the old way —
  check the clitic path in `step_8b`, which had its own minting site.
- **speech and artist agree on shared surfaces.** They must, because both mint
  from the surface. Disagreement means a collision set is being seeded with the
  other mode's IDs again.

## What identity means now

- **surface** — the card. Observed, never revised.
- **headword / lemma** — a label on each sense, from SpanishDict. Revisable
  without moving a card.
- **POS** — also a label on each sense, also from SpanishDict, not inferred.
- **knowledge** — recorded per `(POS, headword)` pill, keyed on lemma. Chosen
  because that granularity survives this classifier's errors: its mistakes are
  near-misses inside one part of speech and one headword.

Card IDs are namespaced (`surface/v2:`) so a future scheme cannot collide with
this one, which is what makes the migration re-runnable rather than destructive.
