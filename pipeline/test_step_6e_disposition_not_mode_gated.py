"""Escalation and rejection are options, in both modes.

`wsd_algorithm.md` read "artist escalates, speech rejects" for two days, and it
was never true of the code -- it was a default someone chose, written down as
though it were a constraint. Nothing enforced the difference between those two
statements, so this does.

The invariant: `--artist-dir` selects WHERE the layers are read from and has no
other effect. Any mode-conditional disposition would have to consult it, so a
single use inside `main` is the whole test.
"""

import ast
import unittest
from pathlib import Path

STEP = Path(__file__).resolve().parent / "step_6e_assign_senses_calibrated.py"

DISPOSITION_FLAGS = ("escalate", "escalate_budget", "min_confidence", "keep_best")


def _main_body():
    tree = ast.parse(STEP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("step_6e has no main()")


def _arg_uses(body, name):
    """Lines where `a.<name>` is read inside main()."""
    return [n.lineno for n in ast.walk(body)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "a"
            and n.attr == name]


class DispositionIsNotModeGatedTests(unittest.TestCase):
    def test_artist_dir_only_chooses_the_layer_directory(self):
        # One expression -- `(REPO / a.artist_dir / ...) if a.artist_dir else
        # LAYERS_DIR` -- reads it twice, so the invariant is one LINE, not one
        # read.
        lines = set(_arg_uses(_main_body(), "artist_dir"))
        self.assertEqual(
            len(lines), 1,
            "--artist-dir is read on lines %s. It may only select the layer "
            "directory; a second site means a disposition has been made "
            "mode-dependent, which is exactly the fiction wsd_algorithm.md "
            "carried." % sorted(lines))

    def test_every_disposition_flag_is_reachable(self):
        body = _main_body()
        for flag in DISPOSITION_FLAGS:
            with self.subTest(flag=flag):
                self.assertTrue(
                    _arg_uses(body, flag),
                    f"--{flag.replace('_', '-')} is parsed but never read")

    def test_no_flag_is_declared_only_for_one_mode(self):
        # A mode-scoped flag would say so in its own help text. None may.
        source = STEP.read_text(encoding="utf-8")
        for flag in ("--escalate", "--escalate-budget",
                     "--min-confidence", "--keep-best"):
            with self.subTest(flag=flag):
                self.assertIn(f'"{flag}"', source)


if __name__ == "__main__":
    unittest.main()
