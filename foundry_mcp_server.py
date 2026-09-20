#!/usr/bin/env python3
"""Stdio MCP server for Foundry Local / Prism (tools: ask_foundry_coder, foundry_code_review, ...).

Thin entry point: the implementation lives in the local_coder package."""

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

from local_coder.compat_foundry import mcp_main  # noqa: E402

if __name__ == "__main__":
    mcp_main()
