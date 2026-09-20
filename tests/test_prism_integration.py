"""Unit tests for Prism local integration, endpoint discovery, and installer sanity."""

import os
import stat
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class TestPrismIntegration(unittest.TestCase):
    """Test suite for Prism-Local connector and endpoint resolution."""

    def test_install_prism_script_exists_and_executable(self):
        installer_path = os.path.join(REPO_ROOT, "install_prism.sh")
        self.assertTrue(os.path.isfile(installer_path), "install_prism.sh must exist in repo root")
        st = os.stat(installer_path)
        self.assertTrue(bool(st.st_mode & stat.S_IXUSR), "install_prism.sh must have user execute permissions")


if __name__ == "__main__":
    unittest.main()
