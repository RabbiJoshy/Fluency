# Normal-mode Spanish full rebuild

Why this exists: the OpenSubtitles corpus was replaced on **2026-07-31**, but the
sense assignments date from **2026-05-02**. Every layer built before the swap
references example IDs that no longer exist, so `step_8a` (deck assembly) can no
longer attach examples it actually has. A partial rebuild cannot fix this —
the assignment layer has to be regenerated against the new corpus.

Symptom if you skip it: ~1,300 cards assemble with **zero** examples despite
having 20 good ones sitting in `examples_raw.json`, because the sense→example
links are stale.

## Before you start

Everything the app ships is tracked in git, so the whole rebuild is revertible:

```bash
git checkout -- Data/Spanish/
```

Take a branch anyway — several stages are expensive to redo.

```bash
git switch -c rebuild-2026-08
```

## Stage 0 — inventory (skip unless the word list is changing)

`word_inventory.json` defines which 10k words exist. Leave it alone unless you
mean to change deck membership; regenerating it invalidates everything below.

## Stage 1 — SpanishDict cache, re-scraped

This is what kills the `fotito → fotuto` class. The plausibility guard
(`is_plausible_headword`) is already live and correctly rejects fuzzy headwords —
but it only runs at scrape time, so entries cached before the guard keep their
bad headwords forever. Reconstructing from master would *preserve* them; only a
re-scrape re-runs the guard.

```bash
.venv/bin/python3 pipeline/tool_5c_build_spanishdict_cache.py --force
```

Network-bound and throttled — the slowest stage. Consider scoping to the
affected surfaces first rather than forcing all 10k.

**Checkpoint:** no menu should carry an implausible headword.

```bash
.venv/bin/python3 pipeline/test_util_5c_guard.py     # 22 cases, expect 0 failures
```

## Stage 2 — sense menus

```bash
.venv/bin/python3 pipeline/step_5c_build_senses.py --language spanish
```

**Checkpoint:** `fotito` should be gone or repointed, never `fotuto`.

```bash
.venv/bin/python3 -c "
import json
d=json.load(open('Data/Spanish/layers/sense_menu/spanishdict.json'))
m=d.get('menus',d)
print('fotito ->', m.get('fotito','ABSENT'))"
```

## Stage 3 — examples

Already rebuilt against the July corpus (9,997 words / 174,793 examples). Only
re-run if the corpus changes again — it streams all 61M lines and takes ~5 min.

```bash
.venv/bin/python3 pipeline/step_5a_build_examples.py --language spanish
```

Do **not** pass `--no-opensubtitles`; it changes selection.

## Stage 4 — sense assignment (the actual fix, and the new prompt)

This is the stage that reconciles assignments with the new corpus. Use it to
introduce the new prompt.

```bash
.venv/bin/python3 pipeline/step_6a_assign_senses.py --language spanish \
    --classifier gemini --gap-fill
```

Costs real API budget. Run one small slice first and inspect before committing
to all 10k.

**Checkpoint — the one that matters.** Assignment IDs must resolve against the
current examples layer. Before the rebuild this sat at 39.77%; it should now be
near-total.

```bash
.venv/bin/python3 -c "
import json,glob
raw=json.load(open('Data/Spanish/layers/examples_raw.json'))
have={e['id'] for v in raw.values() for e in v if e.get('id')}
try: have|=set(json.load(open('Data/Spanish/layers/example_store.json')))
except OSError: pass
need=set()
for p in glob.glob('Data/Spanish/layers/sense_assignments/*.json'):
    if p.endswith('.meta.json'): continue
    for w,ms in json.load(open(p)).items():
        rows=[r for g in (ms.values() if isinstance(ms,dict) else [ms]) for r in g]
        for r in rows:
            if isinstance(r,dict): need.update(r.get('example_ids') or [])
print('resolvable: %.2f%%'%(100*len(need&have)/len(need)))"
```

**Below ~95%, stop and investigate — do not assemble.**

## Stage 5 — lemma mapping (required)

The builders read `sense_assignments_lemma/`, not `sense_assignments/`.
Skipping this silently assembles a stale deck.

```bash
.venv/bin/python3 pipeline/step_7a_map_senses_to_lemmas.py --language spanish
```

## Stage 6 — routing + assembly

```bash
.venv/bin/python3 pipeline/step_4a_route_clitics.py
.venv/bin/python3 pipeline/step_8a_assemble_vocabulary.py --language spanish
```

`step_4a_route_clitics` picks up the infinitive+enclitic detection, so
`alejarme` folds onto `alejar` (or is kept and stamped when the bare infinitive
isn't in the corpus).

**Checkpoint:** compare the assembled deck against the committed one — cards
that lost every example, and total example count.

```bash
.venv/bin/python3 -c "
import json,subprocess
def head(p): return json.loads(subprocess.run(['git','show','HEAD:'+p],capture_output=True).stdout)
P='Data/Spanish/vocabulary.examples.json'
old,new=head(P),json.load(open(P))
def n(e): return sum(len(g) for b in ('m','w','c') for g in (e.get(b) or []))
lost=[h for h,e in old.items() if n(e) and not n(new.get(h,{}))]
print('examples: %d -> %d'%(sum(n(e) for e in old.values()),sum(n(e) for e in new.values())))
print('cards that lost ALL examples:',len(lost))"
```

Expect example count **up** (richer corpus) and cards-losing-everything near
zero. If that count is in the hundreds, stage 4 didn't take — revert and
re-check its checkpoint.

## Stage 7 — ship

Bump the front-end cache tags so the new deck is actually fetched:

```bash
find js index.html service-worker.js -type f -exec sed -i '' -E 's/\?v=[0-9]{8}[a-z]/?v=NEWTAG/g' {} +
```

Then update both `ASSET_VERSION` constants and `CACHE_NAME`, and verify:

```bash
python3 tools/check_asset_versions.py
```

Add a `config/dev_changelog.json` entry.

## Known issues to fold in while you're here

- **Homographs.** `veces → vezar`, `combate → combatir`, `nombres → nombrar` —
  the lemmatizer prefers a verb reading on ambiguous noun surfaces. This is a
  handful of words, not a systemic problem (a strict scan found 6 genuinely
  wrong noun→verb lemmas in 11,729 cards, 4 of which are just accent
  normalisation). Fix via `Data/Spanish/layers/homograph_overrides.json`.
- **`step_5a` backfill has no line cap.** It streams all 61M lines regardless of
  how few words need backfilling. Fine for a full rebuild, painful otherwise; a
  resumable cache keyed by the target set would fix it.
- **`update_example_store` crashes on a malformed store.** Two concurrent
  `step_5a` runs produce a torn read and an unhandled `JSONDecodeError`. It
  should back the file up and start fresh instead of dying.
- **`example_store.json` is gitignored**, so its accumulated history is lost on
  every clone. That history is what bridges assignment/example drift — worth
  reconsidering whether it should be tracked or snapshotted.
