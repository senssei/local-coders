#!/usr/bin/env python3
"""Unified Local Coder CLI: Multi-Engine Agent Assistant.

Dispatches coding, testing, review, and refactoring to Prism, Ollama, or Microsoft Foundry Local.
"""

import os
import sys

# Ensure package directory is importable even when invoked via symlinks
REAL_DIR = os.path.dirname(os.path.realpath(__file__))
if REAL_DIR not in sys.path:
    sys.path.insert(0, REAL_DIR)

from local_coder.cli import main

if __name__ == "__main__":
    main()
