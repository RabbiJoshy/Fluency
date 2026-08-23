"""A token tagged AUX must not annihilate its own menu.

SpanishDict has no AUX category and files every auxiliary and modal as VERB,
while UD tags them AUX. Without a bridge entry, `sense_compatible_bridged`
rejects VERB *and* NOUN for an AUX token -- so every leaf fails, the caller's
empty-keep-set fallback fires, and the POS filter silently does nothing on
`haber`, `ser`, `estar`, `deber` and `saber`: the commonest verbs in speech.

That failure is invisible. The filter does not error, it just stops filtering,
and the only symptom is that `haya` in "que haya existido" keeps four `beech`
noun senses and picks one. So the test pins the two halves separately:

  1. VERB survives an AUX tag at all (the bridge entry exists), and
  2. a realistic AUX menu keeps a strict, non-empty subset -- which is what
     distinguishes a working filter from one that has fallen back.
"""

import unittest

from util_6a_pos_menu_filter import sense_compatible_bridged

# `haya`: the menu SpanishDict actually returns, trimmed to distinct POS.
HAYA_MENU = ["NOUN", "NOUN", "NOUN", "NOUN", "VERB", "VERB", "VERB", "VERB"]


class AuxBridge(unittest.TestCase):
    def test_verb_is_compatible_with_an_aux_tag(self):
        self.assertTrue(
            sense_compatible_bridged("VERB", "AUX"),
            "AUX is missing from _TAGSET_BRIDGE, so every VERB sense of every "
            "auxiliary is rejected and the filter falls back to no-op",
        )

    def test_aux_menu_is_narrowed_and_not_emptied(self):
        kept = [p for p in HAYA_MENU if sense_compatible_bridged(p, "AUX")]
        self.assertTrue(kept, "AUX tag deletes the whole menu; filter is a no-op")
        self.assertLess(len(kept), len(HAYA_MENU), "AUX tag prunes nothing")
        self.assertNotIn("NOUN", kept, "`haya` must not keep its `beech` senses")

    def test_orthogonal_categories_still_pass(self):
        # PHRASE/CONTRACTION are POS-less in SpanishDict and must never be cut.
        for pos in ("PHRASE", "CONTRACTION"):
            self.assertTrue(sense_compatible_bridged(pos, "AUX"))


if __name__ == "__main__":
    unittest.main()
