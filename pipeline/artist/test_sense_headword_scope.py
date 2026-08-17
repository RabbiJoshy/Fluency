#!/usr/bin/env python3
"""A sense_id identifies a sense WITHIN A WORD, never across the language.

96,279 SpanishDict senses share only 8,416 distinct ids, so 81.6% of sense rows
sit on an id some other word also claims. step_8b once built its headword map
keyed by sense_id alone; the last word processed won each id and its headword
was stamped onto unrelated cards. Because buildCardFormModel prefers the
assigned sense's headword over item.lemma, the corruption surfaced as the most
visible field on the card: `cama` displayed lemma `haberes`, `pero` displayed
`loco`, `sexo` displayed `esos`.

This test pins the invariant, not the fix, so any future map keyed the same
wrong way fails here rather than in the app.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STEP_8B = REPO / "pipeline/artist/step_8b_assemble_artist_vocabulary.py"


class SenseHeadwordScope(unittest.TestCase):

    def test_headword_map_is_keyed_by_word_and_sense_id(self):
        src = STEP_8B.read_text(encoding="utf-8")
        self.assertIn("_hw_by_word_sense.setdefault((_w, _sid)", src,
                      "the headword map must be keyed by (word, sense_id); "
                      "keying by sense_id alone collides across 81.6% of senses")
        self.assertIn("(_mw, _sid) in _hw_by_word_sense", src,
                      "the lookup must also carry the master entry's word")
        self.assertNotIn("_hw_by_sense_id[_sid] =", src,
                         "the global sense_id-keyed headword map is back")

    def test_sense_ids_really_do_collide(self):
        """Guard the premise. If ids ever became globally unique this test
        should be the thing that tells us, rather than the invariant quietly
        becoming pointless."""
        menu_path = REPO / "Data/Spanish/layers/sense_menu/spanishdict.json"
        if not menu_path.exists():
            self.skipTest("canonical sense menu not present")
        menu = json.loads(menu_path.read_text(encoding="utf-8"))
        owners = {}
        collisions = 0
        for word, entries in menu.items():
            for entry in entries or []:
                for sid, sense in (entry.get("senses") or {}).items():
                    hw = sense.get("headword")
                    if not hw:
                        continue
                    prev = owners.setdefault(sid, hw)
                    if prev != hw:
                        collisions += 1
        self.assertGreater(
            collisions, 1000,
            "sense_ids no longer collide across words — if that is genuinely "
            "true the keying invariant above can be relaxed, but verify it.")


if __name__ == "__main__":
    unittest.main()
