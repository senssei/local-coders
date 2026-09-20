#!/usr/bin/env bash
# Deprecated wrapper kept for existing docs and habits: the cross-harness installer is install.py.
# Extra arguments pass through (e.g. --harness claude-code, --dry-run, --uninstall).
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.py" --components local-coder "$@"
