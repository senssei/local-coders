"""Unit tests for the unified local_coder multi-engine suite."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import local_coder_mcp_server
from local_coder.client import UnifiedLocalCoderClient, _requires_tests
from local_coder.healing import heal_code_iterative, validate_python_code
from local_coder.models import CompletionResult, EngineInfo, EngineType
from local_coder.prompts import extract_code_block
from local_coder.router import EngineRouter, normalize_ollama_host
from local_coder.status import format_status
from local_coder.telemetry import calculate_savings, format_result_banner


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

    def test_status_marks_shared_endpoint_as_alias(self):
        router = EngineRouter()
        prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", True, installed_models=["m"])
        ollama = EngineInfo("Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", False)
        foundry = EngineInfo("Foundry", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1", True, installed_models=["m"])
        with (
            patch("local_coder.router.platform.system", return_value="Linux"),
            patch.object(router, "list_all_engines", return_value=[prism, ollama, foundry]),
        ):
            text = format_status(router)
        self.assertIn("same server as Prism", text)
        self.assertEqual(text.count("Models ("), 1)

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

    def test_resolve_ordered_engine_preference(self):
        prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", False)
        foundry = EngineInfo("Foundry", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1", True)
        with (
            patch.object(self.router, "discover_prism", return_value=prism),
            patch.object(self.router, "discover_foundry", return_value=foundry),
        ):
            target = self.router.resolve_target_engine((EngineType.PRISM, EngineType.FOUNDRY))
        self.assertEqual(target.engine_type, EngineType.FOUNDRY)

    def test_resolve_ordered_preference_all_offline(self):
        down = EngineInfo("X", EngineType.PRISM, "http://127.0.0.1:5272/v1", False)
        with (
            patch.object(self.router, "discover_prism", return_value=down),
            patch.object(self.router, "discover_foundry", return_value=down),
            self.assertRaises(ConnectionError),
        ):
            self.router.resolve_target_engine((EngineType.PRISM, EngineType.FOUNDRY))

    def test_foundry_autostart_only_when_enabled(self):
        offline = EngineInfo("F", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1", False)
        online = EngineInfo("F", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1", True)
        with (
            patch.object(self.router, "discover_foundry", side_effect=[offline, online]),
            patch.object(self.router, "start_foundry_daemon", return_value=True) as start,
        ):
            with self.assertRaises(ConnectionError):
                self.router.discover_foundry.side_effect = [offline]
                self.router.resolve_target_engine(EngineType.FOUNDRY)
            start.assert_not_called()
            self.router.autostart_foundry = True
            self.router.discover_foundry.side_effect = [offline, online]
            self.assertTrue(self.router.resolve_target_engine(EngineType.FOUNDRY).is_online)
            start.assert_called_once()

    def test_normalize_ollama_host_variants(self):
        cases = {
            None: ("http://localhost:11434", "http://localhost:11434/v1"),
            "127.0.0.1:11434": ("http://127.0.0.1:11434", "http://127.0.0.1:11434/v1"),
            "0.0.0.0": ("http://127.0.0.1:11434", "http://127.0.0.1:11434/v1"),
            ":8080": ("http://localhost:8080", "http://localhost:8080/v1"),
            "http://box:9999/v1/": ("http://box:9999", "http://box:9999/v1"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_ollama_host(raw), expected)

    @patch.dict(os.environ, {"OLLAMA_HOST": "127.0.0.1:11434"})
    @patch("local_coder.router.requests.get")
    def test_discover_ollama_bare_host_env(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"models": []})
        info = self.router.discover_ollama()
        self.assertTrue(info.is_online)
        self.assertEqual(info.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(mock_get.call_args.args[0], "http://127.0.0.1:11434/api/tags")

    def test_rank_online_dedupes_shared_endpoint(self):
        prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", True)
        foundry = EngineInfo("Foundry", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1/", True)
        ollama = EngineInfo("Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True)
        with patch("local_coder.router.platform.system", return_value="Linux"):
            ranked = self.router.rank_online([foundry, ollama, prism])
        self.assertEqual([e.engine_type for e in ranked], [EngineType.OLLAMA, EngineType.PRISM])

    def test_failover_candidates_skip_failed_endpoint(self):
        prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", True)
        foundry = EngineInfo("Foundry", EngineType.FOUNDRY, "http://127.0.0.1:5272/v1", True)
        ollama = EngineInfo("Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True)
        with (
            patch("local_coder.router.platform.system", return_value="Linux"),
            patch.object(self.router, "list_all_engines", return_value=[prism, ollama, foundry]),
        ):
            candidates = self.router.failover_candidates(prism)
        self.assertEqual([e.engine_type for e in candidates], [EngineType.OLLAMA])


class TestUnifiedClient(unittest.TestCase):
    """Tests for UnifiedLocalCoderClient, code generation, and AST self-healing."""

    def setUp(self):
        self.client = UnifiedLocalCoderClient()

    def test_extract_code_block_markdown(self):
        sample = "Here is the code:\n```python\ndef add(a, b):\n    return a + b\n```\nEnjoy!"
        extracted = extract_code_block(sample, "python")
        self.assertEqual(extracted, "def add(a, b):\n    return a + b")

    def test_extract_code_block_edge_cases(self):
        cases = {
            "first python block only": ("```python\nimport os\n```\nusage:\n```python\nprint(1)\n```", "import os"),
            "python tag is case-insensitive": ("```Python\nx = 1\n```", "x = 1"),
            "other language: info string is not code": ("```bash\n#!/bin/bash\necho hi\n```", "#!/bin/bash\necho hi"),
            "dockerfile": ("```dockerfile\nFROM python:3.12\n```", "FROM python:3.12"),
            "bare fence": ("```\nplain\n```", "plain"),
            "python preferred over an earlier other block": ("```bash\nls\n```\n```python\nx = 1\n```", "x = 1"),
            "unclosed fence keeps the code, drops the fence line": (
                "```python\ndef f(:\n    pass",
                "def f(:\n    pass",
            ),
            "unclosed fence of another language": ("Here:\n```yaml\na: 1\nb: 2", "a: 1\nb: 2"),
            "no fence": ("just words", "just words"),
            "windows line endings": ("```python\r\nx = 1\r\n```", "x = 1"),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(extract_code_block(text, "python"), expected)

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

    def test_healing_rejects_candidate_that_discards_the_code(self):
        broken = "def keep_me():\n    return 1\n" * 20 + "def oops(:\n"

        def shrinking_healer(bad: str, err: str) -> str:
            return "x = 1\n"

        final, ok = heal_code_iterative(broken, shrinking_healer, max_retries=2, verbose=False)
        self.assertFalse(ok)
        self.assertEqual(final, broken)

    def test_healing_extra_check_rejects_valid_but_empty_result(self):
        source = "def helper():\n    return 1\n"
        healed = "import pytest\n\ndef test_helper():\n    assert True\n"
        calls = []

        def healer(bad: str, err: str) -> str:
            calls.append(err)
            return healed

        final, ok = heal_code_iterative(source, healer, verbose=False, extra_check=_requires_tests)
        self.assertTrue(ok)
        self.assertEqual(final, healed)
        self.assertIn("no test functions", calls[0])

    def test_requires_tests_detects_tests(self):
        self.assertIsNone(_requires_tests("def test_a():\n    pass\n"))
        self.assertIsNone(_requires_tests("class TestA:\n    pass\n"))
        self.assertIsNone(_requires_tests("async def test_a():\n    pass\n"))
        self.assertIsNotNone(_requires_tests("def helper():\n    pass\n"))

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

    def test_default_engine_from_env(self):
        with patch.dict(os.environ, {"LOCAL_CODER_ENGINE": "ollama"}):
            self.assertEqual(UnifiedLocalCoderClient().default_engine, EngineType.OLLAMA)
        self.assertEqual(UnifiedLocalCoderClient("prism").default_engine, EngineType.PRISM)
        with patch.dict(os.environ, {"LOCAL_CODER_ENGINE": "bogus"}), self.assertRaises(ValueError):
            UnifiedLocalCoderClient()

    @patch("local_coder.client.requests.post")
    def test_ollama_uses_native_chat_with_num_ctx_and_flags_truncation(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "message": {"content": "def f("},
                "done_reason": "length",
                "prompt_eval_count": 11,
                "eval_count": 123,
                "eval_duration": 2_000_000_000,
            },
        )
        info = EngineInfo(
            "Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True, installed_models=["qwen2.5-coder:7b"]
        )
        with patch.object(self.client.router, "resolve_target_engine", return_value=info):
            res = self.client.complete([{"role": "user", "content": "x"}], max_tokens=123)
        self.assertEqual(mock_post.call_args.args[0], "http://localhost:11434/api/chat")
        options = mock_post.call_args.kwargs["json"]["options"]
        self.assertEqual(options["num_predict"], 123)
        self.assertEqual(options["num_ctx"], self.client.num_ctx)
        self.assertTrue(res.truncated)
        self.assertEqual((res.prompt_tokens, res.completion_tokens), (11, 123))
        self.assertEqual(res.tokens_per_sec, 61.5)  # engine-reported decode speed, not wall time
        self.assertIn("truncated", format_result_banner(res, 123))
        self.assertNotIn("truncated", format_result_banner(CompletionResult("", "m", "e"), 123))

    @patch("local_coder.client.requests.post")
    def test_prism_uses_openai_endpoint_and_reported_decode_speed(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "hi"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 9},
                "telemetry": {"decode_tok_per_sec": 108.2},
            },
        )
        info = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", True, installed_models=["phi-4-mini"])
        with patch.object(self.client.router, "resolve_target_engine", return_value=info):
            res = self.client.complete([{"role": "user", "content": "x"}], max_tokens=50)
        self.assertEqual(mock_post.call_args.args[0], "http://127.0.0.1:5272/v1/chat/completions")
        self.assertEqual(mock_post.call_args.kwargs["json"]["max_tokens"], 50)
        self.assertTrue(res.truncated)
        self.assertEqual(res.tokens_per_sec, 108.2)

    def test_model_alias_resolution(self):
        info = EngineInfo(
            "Foundry",
            EngineType.FOUNDRY,
            "http://127.0.0.1:5272/v1",
            True,
            installed_models=["Phi-3.5-mini-instruct-generic-cpu:2"],
            model_aliases={"phi-3.5-mini-instruct-generic-cpu:2": "phi-3.5-mini", "phi-3.5-mini": "phi-3.5-mini"},
        )
        match = UnifiedLocalCoderClient.match_installed_model
        self.assertEqual(match(info, "Phi-3.5-mini-instruct-generic-cpu:2"), "phi-3.5-mini")
        self.assertEqual(match(info, "phi-3.5-mini-instruct-generic-cpu:2"), "phi-3.5-mini")
        self.assertEqual(match(info, "PHI-3.5-MINI"), "phi-3.5-mini")
        self.assertIsNone(match(info, "nonexistent-model"))

    @patch("local_coder.client.requests.post")
    def test_auto_failover_goes_to_different_endpoint(self, mock_post):
        import requests

        ok = MagicMock(status_code=200, json=lambda: {"message": {"content": "ok"}})
        mock_post.side_effect = [requests.exceptions.ConnectionError("down"), ok]
        prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", True)
        ollama = EngineInfo("Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True)
        with (
            patch.object(self.client.router, "resolve_target_engine", side_effect=[prism, ollama]),
            patch.object(self.client.router, "failover_candidates", return_value=[ollama]),
        ):
            res = self.client.complete([{"role": "user", "content": "x"}])
        self.assertEqual(res.engine, "Ollama")
        self.assertEqual(mock_post.call_args_list[1].args[0], "http://localhost:11434/api/chat")


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
        offline = [
            EngineInfo(n, t, "http://127.0.0.1:1/v1", False)
            for n, t in (("Prism", EngineType.PRISM), ("Ollama", EngineType.OLLAMA), ("Foundry", EngineType.FOUNDRY))
        ]
        with patch.object(local_coder_mcp_server.client.router, "list_all_engines", return_value=offline):
            resp = local_coder_mcp_server.handle_call_tool(1, "local_status", {})
        self.assertEqual(resp["id"], 1)
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Local Coder Multi-Engine Status", text)

    def test_notifications_get_no_response(self):
        self.assertIsNone(
            local_coder_mcp_server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_ping_and_unknown_method(self):
        self.assertEqual(local_coder_mcp_server.handle_request({"id": 3, "method": "ping"})["result"], {})
        resp = local_coder_mcp_server.handle_request({"id": 4, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_local_code_forwards_max_tokens_and_reports_truncation(self):
        res = CompletionResult("x", "m", "Ollama", finish_reason="length")
        with patch.object(local_coder_mcp_server.client, "generate_code", return_value=("code", res)) as gen:
            resp = local_coder_mcp_server.handle_call_tool(5, "local_code", {"task": "t", "max_tokens": 77})
        self.assertEqual(gen.call_args.kwargs["max_tokens"], 77)
        self.assertIsNone(gen.call_args.kwargs["engine"])
        self.assertIn("truncated", resp["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
