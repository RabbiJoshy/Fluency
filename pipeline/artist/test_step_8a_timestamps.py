import unittest

from pipeline.artist.step_8a_fetch_lrc_timestamps import (
    match_examples_to_lrc,
    parse_lrc,
)


class LyricTimestampTests(unittest.TestCase):
    def test_empty_lrc_row_is_a_real_end_boundary(self):
        lrc = (
            "[00:10.00]Primera línea\n"
            "[00:13.50]\n"
            "[00:18.00]Segunda línea\n"
        )

        lines = parse_lrc(lrc, duration_ms=24000)

        self.assertEqual(lines[0], (10000, 13500, "Primera línea", "primera línea"))
        self.assertEqual(lines[1], (18000, 24000, "Segunda línea", "segunda línea"))

    def test_matched_example_carries_start_and_end(self):
        lines = parse_lrc(
            "[00:01.00]Hola corazón\n[00:04.25]Siguiente línea\n",
            duration_ms=8000,
        )

        matched = match_examples_to_lrc(["¡Hola, corazón!"], lines)

        self.assertEqual(matched["¡Hola, corazón!"]["ms"], 1000)
        self.assertEqual(matched["¡Hola, corazón!"]["end_ms"], 4250)
        self.assertEqual(matched["¡Hola, corazón!"]["confidence"], "exact")


if __name__ == "__main__":
    unittest.main()
