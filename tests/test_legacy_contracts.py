"""Contract tests for the ollama-coder and foundry-coder entry points, now thin shims over ``local_coder``.

Flags, tool names, output shape and engine choice are the external contract; the internals live in local_coder.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from local_coder import compat_foundry, compat_ollama
from local_coder.types import CompletionResult, EngineInfo, EngineType

OLLAMA_SCRIPT = os.path.join(REPO_ROOT, ".agents", "skills", "ollama-coder", "scripts", "ask_local.py")
FOUNDRY_SCRIPT = os.path.join(REPO_ROOT, ".agents", "skills", "foundry-coder", "scripts", "ask_foundry.py")


def result(content: str = "raw text", **kw) -> CompletionResult:
    defaults = {
        "model": "m",
        "engine": "E",
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "duration_s": 1.5,
        "tokens_per_sec": 13.3,
        "saved_tokens": 30,
        "saved_usd": 0.0003,
    }
    return CompletionResult(content=content, **{**defaults, **kw})


def run_cli(module, argv, client):
    """Run a legacy CLI with a mocked client; returns (stdout, stderr, exit_code)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with (
        patch("local_coder.compat_cli.UnifiedLocalCoderClient", return_value=client),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        try:
            module.cli_main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return out.getvalue(), err.getvalue(), code


class TestOllamaCli(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.generate_code.return_value = ("def f(): pass", result())
        self.client.generate_tests.return_value = ("def test_f(): pass", result())
        self.client.review_code.return_value = result("review text")
        self.client.refactor_code.return_value = ("x = 1", result())

    def test_code_prints_code_and_telemetry_goes_to_stderr(self):
        out, err, rc = run_cli(compat_ollama, ["code", "--task", "do it"], self.client)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "def f(): pass")
        self.assertIn("cloud tokens", err)
        kwargs = self.client.generate_code.call_args.kwargs
        self.assertEqual(kwargs["engine"], EngineType.OLLAMA)
        self.assertEqual(kwargs["profile"], "coding")
        self.assertEqual(kwargs["temperature"], 0.1)
        self.assertTrue(kwargs["self_heal"])

    def test_no_heal_and_legacy_auto_heal_flag(self):
        run_cli(compat_ollama, ["code", "--task", "t", "--no-heal"], self.client)
        self.assertFalse(self.client.generate_code.call_args.kwargs["self_heal"])
        run_cli(compat_ollama, ["code", "--task", "t", "--auto-heal"], self.client)
        self.assertTrue(self.client.generate_code.call_args.kwargs["self_heal"])

    def test_legacy_invocation_without_subcommand_means_code(self):
        _, _, rc = run_cli(compat_ollama, ["--task", "do it", "--model", "qwen2.5-coder:3b"], self.client)
        self.assertEqual(rc, 0)
        self.assertEqual(self.client.generate_code.call_args.kwargs["task"], "do it")
        self.assertEqual(self.client.generate_code.call_args.kwargs["model"], "qwen2.5-coder:3b")

    def test_output_file_gets_trailing_newline_and_stdout_stays_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "out.py")
            out, err, _ = run_cli(compat_ollama, ["code", "--task", "t", "-o", path], self.client)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "def f(): pass\n")
        self.assertEqual(out, "")
        self.assertIn("Saved", err)

    def test_missing_source_file_exits_1(self):
        _, err, rc = run_cli(compat_ollama, ["test", "--file", "/nonexistent/x.py"], self.client)
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_review_defaults_to_reasoning_profile_and_default_focus(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("x = 1\n")
        try:
            out, _, rc = run_cli(compat_ollama, ["review", "--file", f.name], self.client)
        finally:
            os.remove(f.name)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "review text")
        kwargs = self.client.review_code.call_args.kwargs
        self.assertEqual(kwargs["profile"], "reasoning")
        self.assertIn("race conditions", kwargs["focus"])

    def test_refactor_flags_default_off_and_task_becomes_instructions(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("x = 1\n")
        try:
            run_cli(compat_ollama, ["refactor", "--file", f.name, "--task", "split it"], self.client)
            kwargs = self.client.refactor_code.call_args.kwargs
            self.assertFalse(kwargs["type_hints"])
            self.assertFalse(kwargs["docstrings"])
            self.assertEqual(kwargs["instructions"], "split it")
            run_cli(compat_ollama, ["refactor", "--file", f.name, "--type-hints", "--docstrings"], self.client)
            kwargs = self.client.refactor_code.call_args.kwargs
            self.assertTrue(kwargs["type_hints"] and kwargs["docstrings"])
        finally:
            os.remove(f.name)

    def test_engine_error_is_a_clean_message(self):
        self.client.generate_code.side_effect = ConnectionError("Ollama engine requested but offline")
        _, err, rc = run_cli(compat_ollama, ["code", "--task", "t"], self.client)
        self.assertEqual(rc, 1)
        self.assertIn("Error: Ollama engine requested but offline", err)

    def test_no_subcommand_prints_help_and_exits_1(self):
        out, _, rc = run_cli(compat_ollama, [], self.client)
        self.assertEqual(rc, 1)
        self.assertIn("usage", out.lower())


class TestFoundryCli(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.generate_code.return_value = ("def f(): pass", result())

    def test_targets_prism_then_foundry_and_enables_autostart(self):
        out, err, rc = run_cli(compat_foundry, ["code", "--task", "t"], self.client)
        self.assertEqual(rc, 0)
        self.assertEqual(self.client.generate_code.call_args.kwargs["engine"], (EngineType.PRISM, EngineType.FOUNDRY))
        self.assertTrue(self.client.router.autostart_foundry)

    def test_code_and_telemetry_both_on_stdout(self):
        out, err, _ = run_cli(compat_foundry, ["code", "--task", "t"], self.client)
        self.assertIn("def f(): pass", out)
        self.assertIn("cloud tokens", out)
        self.assertEqual(err, "")

    def test_output_file_without_extra_newline_and_saved_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.py")
            out, _, _ = run_cli(compat_foundry, ["code", "--task", "t", "--output", path], self.client)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "def f(): pass")
        self.assertIn("Output saved to", out)

    def test_short_flags_and_max_tokens(self):
        run_cli(
            compat_foundry,
            ["code", "--task", "t", "-m", "phi-3.5-mini", "-t", "0.3", "--max-tokens", "999"],
            self.client,
        )
        kwargs = self.client.generate_code.call_args.kwargs
        self.assertEqual((kwargs["model"], kwargs["temperature"], kwargs["max_tokens"]), ("phi-3.5-mini", 0.3, 999))

    def test_status_subcommand_exists(self):
        with (
            patch("local_coder.compat_foundry.discover_foundry_url", return_value="http://x/v1"),
            patch("local_coder.compat_foundry.requests.get", side_effect=Exception("down")),
        ):
            out, _, rc = run_cli(compat_foundry, ["status"], self.client)
        self.assertEqual(rc, 0)
        self.assertIn("Discovered Base URL: http://x/v1", out)
        self.assertIn("OFFLINE", out)


class TestOllamaMcp(unittest.TestCase):
    def test_tool_names_and_server_identity(self):
        self.assertEqual(
            [t["name"] for t in compat_ollama.list_tools()],
            ["ask_local_coder", "local_code_review", "list_local_models"],
        )
        resp = compat_ollama.server.initialize(1)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "ollama-local-mcp")

    def test_ask_local_coder_returns_raw_text_with_stats_and_uses_context(self):
        client = MagicMock()
        client.complete.return_value = result("```python\nx = 1\n```", model="qwen", tokens_per_sec=50.0)
        with patch("local_coder.compat_ollama.get_client", return_value=client):
            text = compat_ollama.call_tool("ask_local_coder", {"task": "T", "context_code": "CTX", "model": "qwen"})
        self.assertTrue(text.startswith("```python\nx = 1\n```"))
        self.assertIn("[Local LLM Stats: qwen @ 50.0 tok/s", text)
        messages = client.complete.call_args.args[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Context Code:\n```\nCTX\n```", messages[1]["content"])
        self.assertEqual(client.complete.call_args.kwargs["engine"], EngineType.OLLAMA)

    def test_failures_come_back_as_text(self):
        client = MagicMock()
        client.complete.side_effect = ConnectionError("offline")
        with patch("local_coder.compat_ollama.get_client", return_value=client):
            text = compat_ollama.call_tool("local_code_review", {"code": "x"})
        self.assertIn("Error calling local Ollama model", text)
        self.assertIn("offline", text)

    def test_unknown_tool_is_text_and_list_models_shows_sizes(self):
        self.assertEqual(compat_ollama.call_tool("nope", {}), "Unknown tool: nope")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"models": [{"name": "a:1", "size": 2 * 1024**3}]}
        with patch("local_coder.compat_ollama.requests.get", return_value=resp):
            text = compat_ollama.call_tool("list_local_models", {})
        self.assertIn("- a:1 (2.0 GB)", text)

    def test_notifications_are_not_answered(self):
        self.assertIsNone(
            compat_ollama.server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )


class TestFoundryMcp(unittest.TestCase):
    def test_tool_names_and_server_identity(self):
        with patch("local_coder.compat_foundry.get_client") as gc:
            gc.return_value.router.resolve_target_engine.side_effect = ConnectionError("down")
            names = [t["name"] for t in compat_foundry.list_tools()]
        self.assertEqual(
            names, ["ask_foundry_coder", "foundry_code_review", "list_foundry_models", "get_foundry_status"]
        )
        self.assertEqual(compat_foundry.server.initialize(1)["result"]["serverInfo"]["name"], "foundry-local-mcp")

    def test_ask_foundry_coder_uses_prism_then_foundry_and_autostart(self):
        client = MagicMock()
        client.complete.return_value = result("answer", model="phi")
        with patch("local_coder.compat_foundry.get_client", return_value=client):
            text = compat_foundry.call_tool("ask_foundry_coder", {"task": "T"})
        self.assertIn("answer", text)
        self.assertIn("[MS Foundry Stats: phi @", text)
        self.assertEqual(client.complete.call_args.kwargs["engine"], (EngineType.PRISM, EngineType.FOUNDRY))
        self.assertFalse(client.router.autostart_foundry)  # switched back off after the call

    def test_connection_and_api_errors_come_back_as_text(self):
        client = MagicMock()
        client.complete.side_effect = ConnectionError("none online")
        with patch("local_coder.compat_foundry.get_client", return_value=client):
            self.assertIn("Could not connect to Microsoft Foundry Local", compat_foundry.call_foundry("p"))
        client.complete.side_effect = RuntimeError("HTTP 500 boom")
        with patch("local_coder.compat_foundry.get_client", return_value=client):
            self.assertIn("Foundry API error", compat_foundry.call_foundry("p"))

    def test_list_models_shows_alias(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": [{"id": "Phi-3.5-mini-instruct-generic-cpu:2", "parent": "phi-3.5-mini"}]}
        with (
            patch("local_coder.compat_foundry.discover_foundry_url", return_value="http://h/v1"),
            patch("local_coder.compat_foundry.requests.get", return_value=resp),
        ):
            text = compat_foundry.call_tool("list_foundry_models", {})
        self.assertIn("(alias: 'phi-3.5-mini')", text)

    def test_status_reports_daemon_json_and_ping(self):
        resp = MagicMock(status_code=200)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"pid": 42, "web_urls": ["http://127.0.0.1:1"]}, f)
        try:
            with (
                patch("local_coder.compat_foundry.FOUNDRY_DAEMON_JSON", f.name),
                patch("local_coder.compat_foundry.discover_foundry_url", return_value="http://h/v1"),
                patch("local_coder.compat_foundry.requests.get", return_value=resp),
            ):
                text = compat_foundry.call_tool("get_foundry_status", {})
        finally:
            os.remove(f.name)
        self.assertIn("Daemon PID: 42", text)
        self.assertIn("HTTP Ping: Active (200 OK)", text)

    def test_unknown_tool_is_text(self):
        with patch("local_coder.compat_foundry.discover_foundry_url", return_value="http://h/v1"):
            self.assertEqual(compat_foundry.call_tool("nope", {}), "Unknown tool: nope")


class TestFoundryEndpointDiscovery(unittest.TestCase):
    """foundry-coder targets Prism when it is running, else Foundry Local (formerly probed 5272 first)."""

    def _client(self, prism_online: bool, foundry_online: bool, foundry_url="http://127.0.0.1:45678/v1"):
        from local_coder.router import EngineRouter

        router = EngineRouter()
        prism = EngineInfo("Prism", EngineType.PRISM, "http://127.0.0.1:5272/v1", prism_online)
        foundry = EngineInfo("Foundry", EngineType.FOUNDRY, foundry_url, foundry_online)
        router.discover_prism = lambda: prism
        router.discover_foundry = lambda: foundry
        client = MagicMock()
        client.router = router
        return client

    def test_prism_preferred_when_online(self):
        client = self._client(True, True)
        self.assertEqual(compat_foundry.discover_foundry_url(client=client), "http://127.0.0.1:5272/v1")

    def test_foundry_used_when_prism_offline(self):
        client = self._client(False, True)
        self.assertEqual(compat_foundry.discover_foundry_url(client=client), "http://127.0.0.1:45678/v1")

    def test_env_override_wins_when_nothing_is_online(self):
        client = self._client(False, False)
        with patch.dict(os.environ, {"FOUNDRY_BASE_URL": "http://10.0.0.5:9999/v1/"}):
            self.assertEqual(compat_foundry.discover_foundry_url(client=client), "http://10.0.0.5:9999/v1")

    def test_default_fallback_is_ipv4_5272(self):
        client = self._client(False, False, foundry_url="http://127.0.0.1:5272/v1")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(compat_foundry.discover_foundry_url(client=client), "http://127.0.0.1:5272/v1")

    def test_autostart_flag_is_restored(self):
        client = self._client(False, False)
        compat_foundry.discover_foundry_url(auto_start=True, client=client)
        self.assertFalse(client.router.autostart_foundry)


class TestShimScripts(unittest.TestCase):
    """The scripts must find local_coder on their own and speak their historical protocol."""

    def run_script(self, script, args=(), stdin=""):
        return subprocess.run(
            [sys.executable, script, *args], input=stdin, capture_output=True, text=True, timeout=30, cwd="/"
        )

    def test_cli_shims_show_help(self):
        for script in (OLLAMA_SCRIPT, FOUNDRY_SCRIPT):
            with self.subTest(script=os.path.basename(script)):
                proc = self.run_script(script, ["--help"])
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("code", proc.stdout)

    def test_mcp_shims_initialize_and_ignore_notifications(self):
        stdin = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            + "\n"
        )
        for script, name in (
            (os.path.join(REPO_ROOT, "ollama_mcp_server.py"), "ollama-local-mcp"),
            (os.path.join(REPO_ROOT, "foundry_mcp_server.py"), "foundry-local-mcp"),
        ):
            with self.subTest(server=name):
                proc = self.run_script(script, stdin=stdin)
                lines = [json.loads(line) for line in proc.stdout.splitlines()]
                self.assertEqual([m["id"] for m in lines], [1, 2])
                self.assertEqual(lines[0]["result"]["serverInfo"]["name"], name)

    def test_shim_reports_missing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            lonely = os.path.join(tmp, "ollama_mcp_server.py")
            with open(os.path.join(REPO_ROOT, "ollama_mcp_server.py"), encoding="utf-8") as f:
                content = f.read()
            with open(lonely, "w", encoding="utf-8") as f:
                f.write(content)
            proc = self.run_script(lonely)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("local_coder package not found", proc.stderr)


if __name__ == "__main__":
    unittest.main()
