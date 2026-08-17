#!/usr/bin/env python3
"""Parity guard for tool_8j_render_cards.

tool_8j is a SECOND implementation of rules that live in js/vocab.js and
js/flashcards.js -- files this side of the repo does not own. A second
implementation that silently falls behind the first is worse than no tool at
all: it would answer "what does the learner see?" confidently and wrongly,
which is the exact failure the tool was built to end.

So these tests pin the predicates tool_8j mirrors. A failure here does NOT mean
the front end is broken. It means the front end moved and tool_8j is now lying
-- go read the cited line and update the port.

Same contract the repo already uses elsewhere: FEATURE_VERSION refuses to load
a calibrator trained on a different feature vector, and check_asset_versions.py
fails on any ?v= disagreement, rather than guessing.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VOCAB = (REPO / "js/vocab.js").read_text(encoding="utf-8")
CARDS = (REPO / "js/flashcards.js").read_text(encoding="utf-8")

from tool_8j_render_cards import ARTIST_EXTRA_CATEGORIES  # noqa: E402


class RenderParity(unittest.TestCase):

    def test_extra_categories_match(self):
        """The Main/Extra split must use the front end's exact category set."""
        m = re.search(r"const ARTIST_EXTRA_CATEGORIES = new Set\(\s*(\[[^\]]*\])",
                      VOCAB, re.S)
        self.assertIsNotNone(m, "ARTIST_EXTRA_CATEGORIES not found in js/vocab.js")
        js = set(re.findall(r"'([a-z_]+)'", m.group(1)))
        self.assertEqual(
            js, ARTIST_EXTRA_CATEGORIES,
            "js/vocab.js changed which categories are Extra; tool_8j's "
            "Main/Extra split is now wrong. Update ARTIST_EXTRA_CATEGORIES.")

    def test_empty_gloss_strip_still_exists(self):
        """Meanings with no translation are removed before a card renders.

        This is why an all-empty card shows nothing, and the whole reason leaf
        selection was worth building.
        """
        self.assertRegex(
            VOCAB, r"item\.meanings\s*=\s*\(item\.meanings \|\| \[\]\)\s*\.filter\("
                   r"m\s*=>\s*m\.translation && m\.translation\.trim\(\)\)",
            "js/vocab.js no longer strips empty-gloss meanings; tool_8j's "
            "'teaches nothing' count is now wrong.")

    def test_raw_artist_card_rule_still_corpus_count_le_1(self):
        """A meaningless card survives only in Extra, or at corpus_count <= 1."""
        m = re.search(r"const allowsRawArtistCard = activeArtist && \(([^;]*)\);",
                      VOCAB, re.S)
        self.assertIsNotNone(m, "allowsRawArtistCard not found in js/vocab.js")
        body = " ".join(m.group(1).split())
        self.assertIn("artistVocabularyScope === 'extra'", body)
        self.assertIn("Number(item.corpus_count) <= 1", body,
                      "the raw-card threshold moved; tool_8j keeps cards the app "
                      "now drops (or vice versa).")

    def test_duplicate_meaning_grouping_is_on(self):
        """Rows sharing (pos, headword, gloss) collapse into one.

        With this off, `para` would render five rows instead of three and
        tool_8j's row counts would overstate the card, which is precisely the
        phantom finding this tool exists to prevent.
        """
        self.assertRegex(
            CARDS, r"const GROUP_DUPLICATE_MEANINGS = true;",
            "GROUP_DUPLICATE_MEANINGS is no longer unconditionally true; "
            "tool_8j must stop grouping meaning rows.")

    def test_grouping_key_is_pos_headword_translation(self):
        """The group key tool_8j mirrors, character for character."""
        self.assertRegex(
            CARDS, r"const groupPrefix = `\$\{m\.pos\}\\u0000\$\{m\.headword \|\| ''\}\\u0000`",
            "the duplicate-grouping key changed in js/flashcards.js; tool_8j "
            "groups meanings differently from the card now.")

    def test_english_filter_is_unconditional(self):
        """is_english has no toggle -- tool_8j hides it regardless of --exclude."""
        self.assertRegex(
            CARDS if "item.is_english" in CARDS else VOCAB, r"item\.is_english",
            "the unconditional English filter moved.")


if __name__ == "__main__":
    unittest.main()
