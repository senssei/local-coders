"""Guard against drift between the repo sources and the distributable standalone package copies."""

import filecmp
import glob
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


def module_names(directory: str) -> set[str]:
    return {os.path.basename(p) for p in glob.glob(os.path.join(directory, "*.py"))}


class PackagingSyncTests(unittest.TestCase):
    def test_package_copies_match_sources(self):
        for src, dst in MIRRORED_FILES:
            with self.subTest(file=src):
                self.assertTrue(
                    filecmp.cmp(os.path.join(ROOT, src), os.path.join(PKG, dst), shallow=False),
                    f"{dst} has drifted from {src}; re-copy it into packages/antigravity-local-coder/",
                )

    def test_package_ships_the_same_local_coder_modules(self):
        src, dst = os.path.join(ROOT, "local_coder"), os.path.join(PKG, "local_coder")
        self.assertEqual(module_names(src), module_names(dst), "local_coder module set differs in the package")
        for name in sorted(module_names(src)):
            with self.subTest(module=name):
                self.assertTrue(
                    filecmp.cmp(os.path.join(src, name), os.path.join(dst, name), shallow=False),
                    f"local_coder/{name} has drifted; re-copy local_coder/*.py into packages/antigravity-local-coder/local_coder/",
                )


if __name__ == "__main__":
    unittest.main()
