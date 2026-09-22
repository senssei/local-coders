"""Unit tests for Prism local integration, endpoint discovery, and installer sanity."""

import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class TestPrismIntegration(unittest.TestCase):
    """Test suite for Prism-Local connector and endpoint resolution."""

    def test_install_py_accepts_prism_component(self):
        """The deprecated ``install_prism.sh`` wrapper is gone; ``install.py --components prism`` is the canonical path.

        Replaces ``test_install_prism_script_exists_and_executable`` after the shim removal. Runs the local
        installer in ``--dry-run`` mode only — no harness is touched, no network, no ``$HOME`` (the test asserts
        only the exit code and that the requested component appears in the output).
        """
        shim_path = os.path.join(REPO_ROOT, "install_prism.sh")
        self.assertFalse(
            os.path.exists(shim_path),
            f"{shim_path} is deprecated and must be removed; use 'python3 install.py --components prism' instead",
        )
        result = subprocess.run(
            [sys.executable, "install.py", "--dry-run", "--components", "prism"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"install.py --components prism --dry-run failed (rc={result.returncode}):"
            f"\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        combined = (result.stdout + result.stderr).lower()
        self.assertIn("prism", combined, f"expected 'prism' in install.py output; got:\n{combined}")


if __name__ == "__main__":
    unittest.main()
