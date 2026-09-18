"""Unit tests for Microsoft Foundry Local MCP Server and Foundry-Coder CLI Skill."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure repo root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import foundry_mcp_server
from core.client import FoundryClient
import importlib.util

# Dynamically import ask_foundry
ask_foundry_path = os.path.join(REPO_ROOT, ".agents", "skills", "foundry-coder", "scripts", "ask_foundry.py")
spec = importlib.util.spec_from_file_location("ask_foundry", ask_foundry_path)
ask_foundry = importlib.util.module_from_spec(spec)
sys.modules["ask_foundry"] = ask_foundry
spec.loader.exec_module(ask_foundry)


class TestFoundryMCPServer(unittest.TestCase):
    """Test suite for foundry_mcp_server.py."""

    def test_discover_foundry_url_env_override(self):
        with patch.dict(os.environ, {"FOUNDRY_BASE_URL": "http://10.0.0.5:9999/v1"}):
            url = foundry_mcp_server.discover_foundry_url()
            self.assertEqual(url, "http://10.0.0.5:9999/v1")

    def test_discover_foundry_url_daemon_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"web_urls": ["http://127.0.0.1:45678"]}, f)
            tmp_json = f.name

        try:
            with patch.dict(os.environ, {}, clear=True):
                if "FOUNDRY_BASE_URL" in os.environ:
                    del os.environ["FOUNDRY_BASE_URL"]
                with patch("foundry_mcp_server.DAEMON_JSON_PATH", tmp_json):
                    url = foundry_mcp_server.discover_foundry_url()
                    self.assertEqual(url, "http://127.0.0.1:45678/v1")
        finally:
            if os.path.exists(tmp_json):
                os.remove(tmp_json)

    def test_handle_list_tools(self):
        tools = foundry_mcp_server.handle_list_tools()
        names = [t["name"] for t in tools]
        self.assertIn("ask_foundry_coder", names)
        self.assertIn("foundry_code_review", names)
        self.assertIn("list_foundry_models", names)
        self.assertIn("get_foundry_status", names)

    @patch("foundry_mcp_server.requests.post")
    def test_call_foundry_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "def hello(): return 'world'"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8},
        }
        mock_post.return_value = mock_resp

        res = foundry_mcp_server.call_foundry(prompt="Write hello")
        self.assertIn("def hello(): return 'world'", res)
        self.assertIn("MS Foundry Stats", res)
        self.assertIn("Saved", res)

    @patch("foundry_mcp_server.requests.get")
    def test_handle_tool_call_list_models(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"id": "Phi-3.5-mini-instruct-generic-cpu:2"}, {"id": "qwen3-0.6b"}]
        }
        mock_get.return_value = mock_resp

        out = foundry_mcp_server.handle_tool_call("list_foundry_models", {})
        self.assertIn("Phi-3.5-mini-instruct-generic-cpu:2", out)
        self.assertIn("qwen3-0.6b", out)

    def test_handle_tool_call_get_status(self):
        out = foundry_mcp_server.handle_tool_call("get_foundry_status", {})
        self.assertIn("Foundry Base URL:", out)


class TestAskFoundrySkill(unittest.TestCase):
    """Test suite for ask_foundry.py."""

    def test_extract_clean_code(self):
        raw = "Here is the code:\n```python\ndef add(a, b):\n    return a + b\n```\nHope it helps!"
        cleaned = ask_foundry.extract_clean_code(raw)
        self.assertEqual(cleaned, "def add(a, b):\n    return a + b")

    def test_validate_python_code_valid(self):
        code = "def valid():\n    return 42\n"
        is_valid, msg = ask_foundry.validate_python_code(code)
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")

    def test_validate_python_code_invalid(self):
        code = "def invalid(\n    return 42"
        is_valid, msg = ask_foundry.validate_python_code(code)
        self.assertFalse(is_valid)
        self.assertIn("SyntaxError", msg)

    def test_format_telemetry_summary(self):
        telem = {
            "runtime": "MS Foundry Local",
            "model": "Phi-3.5-mini-instruct-generic-cpu:2",
            "tok_s": 75.5,
            "total_sec": 1.25,
            "eval_count": 80,
            "prompt_eval_count": 25,
            "tokens_saved": 105,
            "cost_saved_usd": 0.00128,
        }
        summary = ask_foundry.format_telemetry_summary(telem)
        self.assertIn("MS Foundry Local: Phi-3.5-mini-instruct-generic-cpu:2", summary)
        self.assertIn("75.5 tok/s", summary)
        self.assertIn("Saved: 105 tokens", summary)

    @patch("ask_foundry.query_foundry")
    def test_self_healing_loop_success(self, mock_query):
        # First attempt returns code with syntax error, second attempt heals it
        mock_query.side_effect = [
            ("```python\ndef broken(\n```", {
                "eval_count": 10, "prompt_eval_count": 5, "tokens_saved": 15, "cost_saved_usd": 0.0001
            }),
            ("```python\ndef fixed():\n    return True\n```", {
                "eval_count": 12, "prompt_eval_count": 10, "tokens_saved": 22, "cost_saved_usd": 0.0002
            }),
        ]

        code, telem = ask_foundry.execute_with_self_healing(
            prompt="Make a function",
            model="Phi-3.5-mini-instruct-generic-cpu:2",
            base_url="http://localhost:5272/v1",
            auto_heal=True,
            max_retries=2,
        )
        self.assertEqual(code, "def fixed():\n    return True")
        self.assertEqual(mock_query.call_count, 2)
        self.assertEqual(telem["eval_count"], 22)


if __name__ == "__main__":
    unittest.main()
