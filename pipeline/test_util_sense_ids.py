import unittest

from pipeline.util_sense_ids import (
    carry_sense_identity,
    make_generated_sense_id,
    merge_sense_identity,
)


class SenseIdentityTests(unittest.TestCase):
    def test_first_id_becomes_canonical(self):
        sense = {}
        carry_sense_identity(sense, "abc")
        self.assertEqual(sense, {"sense_id": "abc"})

    def test_persisted_canonical_is_never_replaced(self):
        sense = {"sense_id": "old"}
        carry_sense_identity(sense, "new")
        self.assertEqual(sense["sense_id"], "old")
        self.assertEqual(sense["sense_id_aliases"], ["new"])

    def test_merge_deduplicates_aliases(self):
        target = {"sense_id": "a", "sense_id_aliases": ["b"]}
        incoming = {"sense_id": "b", "sense_id_aliases": ["c", "a"]}
        merge_sense_identity(target, incoming)
        self.assertEqual(target["sense_id"], "a")
        self.assertEqual(target["sense_id_aliases"], ["b", "c"])

    def test_blank_ids_are_not_emitted(self):
        sense = {}
        carry_sense_identity(sense, "", [None, "  "])
        self.assertEqual(sense, {})

    def test_source_id_supersedes_generated_id_without_breaking_alias(self):
        sense = {"sense_id": "generated:artist-master:abc"}
        carry_sense_identity(sense, "source-123")
        self.assertEqual(sense["sense_id"], "source-123")
        self.assertEqual(sense["sense_id_aliases"], ["generated:artist-master:abc"])

    def test_generated_id_is_reproducible_and_namespaced(self):
        first = make_generated_sense_id("artist-master", "Propio", " ADJ ", " own ")
        second = make_generated_sense_id("artist-master", "propio", "ADJ", "own")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("generated:artist-master:"))


if __name__ == "__main__":
    unittest.main()
