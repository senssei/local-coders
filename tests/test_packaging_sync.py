"""Guard against drift between the repo sources and the distributable standalone package copies."""

import filecmp
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "packages", "antigravity-local-coder")

# Code that must stay byte-identical. (Skill docs are excluded: the package renames ollama-coder -> local-coder.)
# (source in repo, copy shipped in the standalone package)
MIRRORED_FILES = [
    ("ollama_mcp_server.py", "ollama_mcp_server.py"),
    (".agents/skills/ollama-coder/scripts/ask_local.py", "skills/local-coder/scripts/ask_local.py"),
]


class PackagingSyncTests(unittest.TestCase):
    def test_package_copies_match_sources(self):
        for src, dst in MIRRORED_FILES:
            with self.subTest(file=src):
                self.assertTrue(
                    filecmp.cmp(os.path.join(ROOT, src), os.path.join(PKG, dst), shallow=False),
                    f"{dst} has drifted from {src}; re-copy it into packages/antigravity-local-coder/",
                )


if __name__ == "__main__":
    unittest.main()
