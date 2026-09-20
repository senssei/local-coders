"""Unit tests for the unified local_coder multi-engine suite."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import local_coder_mcp_server
from local_coder.client import UnifiedLocalCoderClient
from local_coder.healing import heal_code_iterative, validate_python_code
from local_coder.prompts import extract_code_block
from local_coder.router import EngineRouter
from local_coder.telemetry import calculate_savings
from local_coder.types import EngineInfo, EngineType


class TestUnifiedRouter(unittest.TestCase):
    """Tests for EngineRouter and multi-engine auto-discovery."""

    def setUp(self):
        self.router = EngineRouter()

    def test_hardware_detection_returns_string(self):
        hw = self.router.hardware
        self.assertIsInstance(hw, str)
        self.assertTrue(len(hw) > 0)

    @patch("local_coder.router.requests.get")
    def test_discover_prism_online(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "phi-4-mini"}, {"id": "qwen2.5-coder-7b"}]}
        mock_get.return_value = mock_resp

        info = self.router.discover_prism()
        self.assertTrue(info.is_online)
        self.assertIn("phi-4-mini", info.installed_models)
        self.assertEqual(info.engine_type, EngineType.PRISM)

    @patch("local_coder.router.requests.get")
    def test_discover_ollama_online(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.1:8b"}]}
        mock_get.return_value = mock_resp

        info = self.router.discover_ollama()
        self.assertTrue(info.is_online)
        self.assertIn("qwen2.5-coder:7b", info.installed_models)
        self.assertEqual(info.engine_type, EngineType.OLLAMA)

    def test_resolve_engine_explicit_prism(self):
        with patch.object(
            self.router,
            "discover_prism",
            return_value=EngineInfo(
                name="Prism",
                engine_type=EngineType.PRISM,
                base_url="http://127.0.0.1:5272/v1",
                is_online=True,
            ),
        ):
            target = self.router.resolve_target_engine(EngineType.PRISM)
            self.assertEqual(target.engine_type, EngineType.PRISM)

    def test_resolve_engine_auto_prioritizes_online(self):
        mock_prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", False)
        mock_ollama = EngineInfo("Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True)
        mock_foundry = EngineInfo("Foundry", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1", False)

        with patch.object(self.router, "list_all_engines", return_value=[mock_prism, mock_ollama, mock_foundry]):
            target = self.router.resolve_target_engine(EngineType.AUTO)
            self.assertEqual(target.engine_type, EngineType.OLLAMA)


class TestUnifiedClient(unittest.TestCase):
    """Tests for UnifiedLocalCoderClient, code generation, and AST self-healing."""

    def setUp(self):
        self.client = UnifiedLocalCoderClient()

    def test_extract_code_block_markdown(self):
        sample = "Here is the code:\n```python\ndef add(a, b):\n    return a + b\n```\nEnjoy!"
        extracted = extract_code_block(sample, "python")
        self.assertEqual(extracted, "def add(a, b):\n    return a + b")

    def test_ast_validation_valid(self):
        code = "def valid():\n    return 42\n"
        is_valid, err = validate_python_code(code)
        self.assertTrue(is_valid)
        self.assertIsNone(err)

    def test_ast_validation_invalid(self):
        code = "def broken(:\n    return 42\n"
        is_valid, err = validate_python_code(code)
        self.assertFalse(is_valid)
        self.assertIn("SyntaxError", err or "")

    def test_self_healing_loop_recovers(self):
        attempts = 0

        def mock_healer(bad_code: str, err: str) -> str:
            nonlocal attempts
            attempts += 1
            return "def healed():\n    return 'fixed'\n"

        broken_code = "def broken(:"
        final, ok = heal_code_iterative(broken_code, mock_healer, max_retries=2, verbose=False)
        self.assertTrue(ok)
        self.assertIn("def healed()", final)
        self.assertEqual(attempts, 1)

    def test_calculate_savings(self):
        tokens, usd = calculate_savings(1000, 2000)
        self.assertEqual(tokens, 3000)
        expected_usd = (1000 / 1e6 * 3.0) + (2000 / 1e6 * 15.0)
        self.assertAlmostEqual(usd, expected_usd)

    @patch("local_coder.client.requests.post")
    def test_complete_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "```python\ndef add(a, b): return a + b\n```"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }
        mock_post.return_value = mock_resp

        with patch.object(
            self.client.router,
            "resolve_target_engine",
            return_value=EngineInfo(
                "Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", True, installed_models=["phi-4-mini"]
            ),
        ):
            code, res = self.client.generate_code("add function", self_heal=False)
            self.assertEqual(code, "def add(a, b): return a + b")
            self.assertEqual(res.prompt_tokens, 50)
            self.assertEqual(res.completion_tokens, 20)


class TestUnifiedMCPServer(unittest.TestCase):
    """Tests for local_coder_mcp_server.py handlers."""

    def test_handle_initialize(self):
        resp = local_coder_mcp_server.handle_initialize(10)
        self.assertEqual(resp["id"], 10)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "local-coder-unified-mcp")

    def test_handle_list_tools(self):
        tools = local_coder_mcp_server.handle_list_tools()
        names = [t["name"] for t in tools]
        self.assertIn("local_code", names)
        self.assertIn("local_test", names)
        self.assertIn("local_code_review", names)
        self.assertIn("local_refactor", names)
        self.assertIn("local_status", names)
        self.assertIn("list_local_models", names)

    def test_handle_call_tool_status(self):
        resp = local_coder_mcp_server.handle_call_tool(1, "local_status", {})
        self.assertEqual(resp["id"], 1)
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Local Coder Multi-Engine Status", text)


if __name__ == "__main__":
    unittest.main()
