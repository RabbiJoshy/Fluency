#!/usr/bin/env python3
"""apply_artist_surface_migration — re-key artist progress onto surface IDs.

Mirrors backend/apply_surface_migration.py, which did the same for speech. Card
rows move to the surface ID their old word|lemma card merged into; where several
old cards collapsed onto one surface, the strongest record wins and the counts
are summed. Each old card also becomes a lemma item, so the pre-migration
word|lemma history stays live rather than existing only in a backup.

Merge rule, same as speech: highest srsStage, then most correct answers, then
most recent sighting. Resetting to the weakest would re-teach a word the learner
already knows.

Cards an earlier migration had already retired are followed through
superseded_by to whichever card is live now — the mapping only lists the cards
that were active when it was generated.

Writes into backend/local/Progress.json so push_sheets.py does the upload.

Usage:
    python3 backend/apply_artist_surface_migration.py --dry-run
    python3 backend/apply_artist_surface_migration.py
"""

import argparse
import json
import os
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
LOCAL_DIR = os.path.join(SCRIPT_DIR, 'local')
PROGRESS = os.path.join(LOCAL_DIR, 'Progress.json')
MAPPING = os.path.join(REPO, 'Artists/spanish/evidence/artist_surface_id_migration.json')
REGISTRY = os.path.join(REPO, 'Artists/spanish/evidence/registries/cards.json')
MASTER = os.path.join(REPO, 'Artists/spanish/vocabulary_master.json')

PREFIX = 'es1'
KNOWLEDGE_SCHEMA_VERSION = 1


def normalize_knowledge_text(value):
    text = unicodedata.normalize('NFKC', str(value or '')).strip().lower()
    return ' '.join(text.split())


def hash_knowledge_signature(value):
    """FNV-1a 32-bit, mirroring hashKnowledgeSignature in js/knowledge.js."""
    h = 0x811C9DC5
    for ch in str(value or ''):
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, '08x')


def lemma_item_id(full_id, headword):
    signature = 'lemma|%s' % normalize_knowledge_text(headword)
    return '%s~k%d:lemma:%s' % (full_id, KNOWLEDGE_SCHEMA_VERSION,
                                hash_knowledge_signature(signature))


def strength(row):
    return (int(row.get('srsStage') or 0),
            int(row.get('correct') or 0),
            str(row.get('lastSeen') or ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--progress', default=PROGRESS)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    mapping = dict(json.load(open(MAPPING, encoding='utf-8'))['mapping'])
    records = json.load(open(REGISTRY, encoding='utf-8'))['records']
    master = json.load(open(MASTER, encoding='utf-8'))

    def destination(card_id, limit=10):
        seen = set()
        while limit > 0 and card_id not in seen:
            seen.add(card_id)
            if card_id in mapping:
                return mapping[card_id]
            record = records.get(card_id) or {}
            if (record.get('status') or 'active') == 'active':
                return card_id
            successor = record.get('superseded_by')
            if not successor:
                return None
            card_id = successor
            limit -= 1
        return None

    payload = json.load(open(args.progress, encoding='utf-8'))
    rows = payload['rows'] if isinstance(payload, dict) and 'rows' in payload else payload

    artist_words = [r for r in rows
                    if r.get('mode') == 'artist' and r.get('itemType') == 'word']
    grouped = defaultdict(list)
    unmatched = []
    for row in artist_words:
        item_id = str(row.get('itemId') or '')
        if not item_id.startswith(PREFIX):
            unmatched.append(item_id)
            continue
        new_id = destination(item_id[len(PREFIX):])
        if new_id is None:
            unmatched.append(item_id)
            continue
        grouped[new_id].append(row)

    retired = {r['itemId'] for members in grouped.values() for r in members}
    kept = [r for r in rows if r.get('itemId') not in retired]

    card_rows, lemma_rows, merges = [], [], []
    for new_id, members in grouped.items():
        members.sort(key=strength, reverse=True)
        best = members[0]
        new_full = PREFIX + new_id
        entry = master.get(new_id) or {}
        card_rows.append({
            **{k: v for k, v in best.items() if k != 'itemId'},
            'itemId': new_full,
            'itemType': 'word',
            'correct': sum(int(r.get('correct') or 0) for r in members),
            'wrong': sum(int(r.get('wrong') or 0) for r in members),
            'srsStage': max(int(r.get('srsStage') or 0) for r in members),
            'lastSeen': max(str(r.get('lastSeen') or '') for r in members),
        })
        if len(members) > 1:
            merges.append((entry.get('word'), [
                ((records.get(str(r.get('itemId') or '')[len(PREFIX):]) or {})
                 .get('aliases') or [{}])[0].get('lemma')
                for r in members]))
        for row in members:
            # The progress row's `label` is the surface word, not the lemma, so
            # using it gives every old card on one surface the same lemma-item
            # ID and collapses exactly the distinction these rows exist to keep
            # (ellos/ello, vino/venir). The registry's alias for the OLD card is
            # where the lemma actually lives.
            old_card = str(row.get('itemId') or '')[len(PREFIX):]
            aliases = (records.get(old_card) or {}).get('aliases') or []
            headword = (aliases[0].get('lemma') if aliases else None) \
                or entry.get('lemma') or entry.get('word') or ''
            lemma_rows.append({
                'user': row.get('user'),
                'itemId': lemma_item_id(new_full, headword),
                'itemType': 'lemma',
                'mode': 'artist',
                'source': row.get('source', ''),
                'parentWordId': new_full,
                'label': headword,
                'language': row.get('language', 'spanish'),
                'correct': int(row.get('correct') or 0),
                'wrong': int(row.get('wrong') or 0),
                'srsStage': int(row.get('srsStage') or 0),
                'lastSeen': row.get('lastSeen', ''),
                'lastCorrect': row.get('lastCorrect', ''),
                'lastWrong': row.get('lastWrong', ''),
                'schemaVersion': row.get('schemaVersion', 4),
            })

    # Drop lemma rows that would collide: two old cards sharing a headword on the
    # same surface are one lemma item, not two.
    seen, deduped = set(), []
    for row in lemma_rows:
        if row['itemId'] in seen:
            continue
        seen.add(row['itemId'])
        deduped.append(row)
    collapsed = len(lemma_rows) - len(deduped)
    lemma_rows = deduped

    merged_rows = kept + card_rows + lemma_rows
    print('artist word rows: %d (matched %d, unmatched %d)'
          % (len(artist_words), len(retired), len(unmatched)))
    print('  card rows out:   %d' % len(card_rows))
    print('  lemma items out: %d (%d collapsed as duplicates)'
          % (len(lemma_rows), collapsed))
    print('  surfaces where >1 progressed card merges: %d' % len(merges))
    for word, labels in merges[:6]:
        print('     %-14s from %s' % (word, labels))
    print('  local rows: %d -> %d' % (len(rows), len(merged_rows)))
    print('  by itemType: %s' % dict(Counter(r.get('itemType') for r in merged_rows)))

    if args.dry_run:
        print('\n--dry-run: nothing written')
        return

    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')
    shutil.copy2(args.progress,
                 os.path.join(LOCAL_DIR, 'Progress.pre_artist_migration.%s.json' % stamp))
    if isinstance(payload, dict) and 'rows' in payload:
        payload['rows'] = merged_rows
        out = payload
    else:
        out = merged_rows
    with open(args.progress, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('\nwrote %s' % args.progress)
    print('Next: python3 backend/push_sheets.py --sheet Progress   (dry run)')


if __name__ == '__main__':
    main()
