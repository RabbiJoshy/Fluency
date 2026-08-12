# Local Artist evidence artifacts

The browser does not load `Artists/*/*/data/evidence/`. It loads the committed
compact index, examples, and shared master files. Consequently, losing the
local evidence directories would not break the deployed app or erase learner
progress.

The evidence directories are nevertheless important pipeline assets. They
contain immutable occurrence ledgers, overlay claims, run manifests, and
snapshots selected by each artist's active profile. The current Spanish artist
directories total roughly 3 GB, and three J Balvin normalization shards exceed
GitHub's ordinary 100 MB per-file limit. Generated `*_preview` and
`*_ledger_candidate` decks are disposable; ledgers and selected claims are not.

## Risk classification

- **Runtime risk:** none. Compact app files are committed and checksummed.
- **Rebuild risk:** moderate. A clean clone cannot replay the exact active
  evidence profile without the local artifact tree.
- **Data-loss risk:** moderate while the artifact tree has only one physical
  copy. Most raw lyrics can be rescanned and occurrence IDs are deterministic,
  but exact run history, retired claims, and audit provenance would be lost.

## Storage rule

Keep generated previews local and disposable. Back up the evidence tree as
content-addressed compressed archives in object storage or another two-copy
artifact store. Commit only a small manifest containing archive name, byte
size, SHA-256, artist, active profile hash, and restore instructions. Do not
put the raw 3 GB tree in ordinary Git, and do not make an active profile point
to an artifact that exists on only one machine without recording that fact in
the handoff.

The repository `.gitignore` excludes new Artist/Data evidence trees and
generated preview decks so a broad `git add` cannot accidentally upload them.
Files that were already tracked remain tracked by Git. The next storage step is
operational rather than an app change: create the external archives, verify
their hashes, restore one into a temporary clone, and commit the small archive
manifest described above.
