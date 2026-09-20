"""Unit tests for Prism local integration, endpoint discovery, and installer sanity."""

import os
import stat
import sys
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import foundry_mcp_server


class TestPrismIntegration(unittest.TestCase):
    """Test suite for Prism-Local connector and endpoint resolution."""

    def test_prism_base_url_env_override(self):
        with patch.dict(os.environ, {"PRISM_BASE_URL": "http://127.0.0.1:5272/v1"}):
            url = foundry_mcp_server.discover_foundry_url(auto_start=False)
            self.assertEqual(url, "http://127.0.0.1:5272/v1")

    @patch("foundry_mcp_server.requests.get")
    def test_probe_5272_active_preferred(self, mock_get):
        # When 127.0.0.1:5272/v1/models responds with 200, use it immediately
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        with patch.dict(os.environ, {}, clear=True):
            if "FOUNDRY_BASE_URL" in os.environ:
                del os.environ["FOUNDRY_BASE_URL"]
            if "PRISM_BASE_URL" in os.environ:
                del os.environ["PRISM_BASE_URL"]

            url = foundry_mcp_server.discover_foundry_url(auto_start=False)
            self.assertEqual(url, "http://127.0.0.1:5272/v1")

    def test_install_prism_script_exists_and_executable(self):
        installer_path = os.path.join(REPO_ROOT, "install_prism.sh")
        self.assertTrue(os.path.isfile(installer_path), "install_prism.sh must exist in repo root")
        st = os.stat(installer_path)
        self.assertTrue(bool(st.st_mode & stat.S_IXUSR), "install_prism.sh must have user execute permissions")

    def test_default_fallback_is_ipv4(self):
        with patch.dict(os.environ, {}, clear=True):
            if "FOUNDRY_BASE_URL" in os.environ:
                del os.environ["FOUNDRY_BASE_URL"]
            if "PRISM_BASE_URL" in os.environ:
                del os.environ["PRISM_BASE_URL"]
            with patch("foundry_mcp_server.os.path.exists", return_value=False):
                with patch("foundry_mcp_server.requests.get", side_effect=Exception("Offline")):
                    url = foundry_mcp_server.discover_foundry_url(auto_start=False)
                    self.assertEqual(url, "http://127.0.0.1:5272/v1")


if __name__ == "__main__":
    unittest.main()
