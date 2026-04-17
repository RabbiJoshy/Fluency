#!/usr/bin/env python3
"""Artist-mode step 7a — thin wrapper calling the shared unified implementation.

The shared `pipeline/step_7a_map_senses_to_lemmas.py` handles both normal mode
and artist mode. This wrapper forwards --artist-dir to it so the orchestrator
can keep calling the artist script directly.
"""

import os
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
SHARED_SCRIPT = os.path.join(_PROJECT_ROOT, "pipeline", "step_7a_map_senses_to_lemmas.py")
PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


if __name__ == "__main__":
    sys.exit(subprocess.call([PYTHON, SHARED_SCRIPT] + sys.argv[1:]))
