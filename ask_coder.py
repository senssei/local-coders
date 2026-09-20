#!/usr/bin/env python3
"""Unified Local Coder CLI: Multi-Engine Agent Assistant.

Dispatches coding, testing, review, and refactoring to Prism, Ollama, or Microsoft Foundry Local.
"""

import os
import sys


def _add_local_coder_to_path() -> None:
    """Find the ``local_coder`` package next to this script or in a parent directory (repo or installed skill)."""
    here = os.path.dirname(os.path.realpath(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(here, "local_coder")):
            sys.path.insert(0, here)
            return
        here = os.path.dirname(here)
    sys.exit("local_coder package not found next to this script; re-run the installer.")


_add_local_coder_to_path()

from local_coder.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
