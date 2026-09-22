"""--language: code generation in languages other than Python (prompts, no AST healing, CLIs and MCP)."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import local_coder_mcp_server
from local_coder import cli, compat_foundry, compat_ollama
from local_coder.client import UnifiedLocalCoderClient
from local_coder.models import CompletionResult, EngineInfo, EngineType
from local_coder.prompts import (
    build_code_prompt,
    build_review_prompt,
    is_python,
    language_for_path,
    normalize_language,
    system_coder,
)


def reply(text: str):
    return MagicMock(
        status_code=200,
        json=lambda: {"message": {"content": text}, "done_reason": "stop", "prompt_eval_count": 5, "eval_count": 9},
    )


class TestPrompts(unittest.TestCase):
    def test_python_prompt_is_unchanged(self):
        system, user = (m["content"] for m in build_code_prompt("do it"))
        self.assertIn("```python", system)
        self.assertIn("type annotations", system)
        self.assertIn("Write the complete implementation in Python.", user)
        self.assertEqual(build_code_prompt("do it"), build_code_prompt("do it", None, "PY"))

    def test_other_language_prompt_does_not_ask_for_python(self):
        system, user = (m["content"] for m in build_code_prompt("deploy script", None, "Bash"))
        for text in (system, user):
            self.assertNotIn("Python", text)
            self.assertNotIn("python", text)
        self.assertIn("```bash", system)
        self.assertIn("implementation in bash", user)
        self.assertIn("single ```bash", user)

    def test_context_files_are_still_included(self):
        _, user = (m["content"] for m in build_code_prompt("t", {"a.sh": "echo 1"}, "bash"))
        self.assertIn("--- a.sh ---\necho 1", user)

    def test_language_names_are_normalised_and_validated(self):
        self.assertEqual(normalize_language(None), "python")
        self.assertEqual(normalize_language(""), "python")  # an empty value (e.g. from an MCP client) means the default
        self.assertEqual([normalize_language(x) for x in ("PY", "python3", " Python ")], ["python"] * 3)
        self.assertEqual(normalize_language("C++"), "c++")
        self.assertEqual(normalize_language("c#"), "c#")
        self.assertTrue(is_python("py"))
        self.assertFalse(is_python("bash"))
        for bad in ("   ", "bash; rm -rf /", "x" * 25, "two words", "a\nb", "``` inject"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_language(bad)
        self.assertEqual(system_coder("python"), system_coder(None))

    def test_test_prompt_fences_with_the_chosen_language(self):
        """``build_test_prompt`` honours ``language``: bash → `` ```bash `` fence and bash closing fence."""
        from local_coder.prompts import build_test_prompt

        user = build_test_prompt("echo hi", "deploy.sh", "pytest", language="bash")[1]["content"]
        self.assertIn("```bash\necho hi", user)
        self.assertIn("```bash ... ```", user)  # the closing fence matches the chosen language
        self.assertNotIn("```python", user)  # no Python fence anywhere

    def test_test_prompt_system_message_matches_language(self):
        """``build_test_prompt`` uses ``system_coder(lang)``, not hardcoded Python ``SYSTEM_CODER``."""
        from local_coder.prompts import build_test_prompt

        messages = build_test_prompt("echo hi", "deploy.sh", language="bash")
        system = messages[0]["content"]
        self.assertIn("bash", system)
        self.assertNotIn("```python", system)

    def test_refactor_prompt_system_message_matches_language(self):
        """``build_refactor_prompt`` uses ``system_coder(lang)``, not hardcoded Python ``SYSTEM_CODER``."""
        from local_coder.prompts import build_refactor_prompt

        messages = build_refactor_prompt("echo hi", "deploy.sh", language="bash")
        system = messages[0]["content"]
        self.assertIn("bash", system)
        self.assertNotIn("```python", system)

    def test_test_prompt_defaults_to_python(self):
        """No language → `` ```python `` fence (today's behaviour preserved)."""
        from local_coder.prompts import build_test_prompt

        user = build_test_prompt("def f(): pass", "m.py", "pytest")[1]["content"]
        self.assertIn("```python\ndef f(): pass", user)

    def test_test_prompt_framework_custom_and_omitted(self):
        """Custom framework is mentioned; omitted framework for non-Python does not force pytest."""
        from local_coder.prompts import build_test_prompt

        user_custom = build_test_prompt("echo hi", "deploy.sh", framework="bats", language="bash")[1]["content"]
        self.assertIn("using `bats`", user_custom)

        user_omitted = build_test_prompt("echo hi", "deploy.sh", language="bash")[1]["content"]
        self.assertNotIn("pytest", user_omitted)
        self.assertIn("- Write a comprehensive test suite for the code above.\n", user_omitted)

    def test_refactor_prompt_fences_with_the_chosen_language(self):
        """``build_refactor_prompt`` honours ``language``: bash → `` ```bash `` fence, no Python directives."""
        from local_coder.prompts import build_refactor_prompt

        user = build_refactor_prompt(
            "echo hi",
            "deploy.sh",
            type_hints=True,
            docstrings=False,
            language="bash",
        )[1]["content"]
        self.assertIn("```bash\necho hi", user)
        self.assertNotIn("PEP 484", user)
        self.assertNotIn("PEP 257", user)

    def test_refactor_prompt_defaults_to_python(self):
        """No language → `` ```python `` fence, Python-only directives."""
        from local_coder.prompts import build_refactor_prompt

        user = build_refactor_prompt("def f(): pass", "m.py")[1]["content"]
        self.assertIn("```python\ndef f(): pass", user)
        self.assertIn("PEP 484", user)
        self.assertIn("PEP 257", user)


class TestClientLanguage(unittest.TestCase):
    def setUp(self):
        self.client = UnifiedLocalCoderClient()
        info = EngineInfo(
            "Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True, installed_models=["qwen2.5-coder:7b"]
        )
        patcher = patch.object(self.client.router, "resolve_target_engine", return_value=info)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bash_is_extracted_without_its_tag_and_never_healed(self):
        answer = "Here you go:\n```bash\n#!/bin/bash\nif then fi (\n```"  # not valid anything, and must not matter
        with patch("local_coder.client.requests.post", return_value=reply(answer)) as post:
            code, res = self.client.generate_code("deploy", language="bash")
        self.assertEqual(code, "#!/bin/bash\nif then fi (")
        self.assertEqual(post.call_count, 1)  # no repair round-trips
        prompt = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("implementation in bash", prompt)

    def test_python_is_still_healed(self):
        replies = [reply("```python\ndef broken(:\n```"), reply("```python\ndef ok():\n    return 1\n```")]
        with patch("local_coder.client.requests.post", side_effect=replies) as post:
            code, _ = self.client.generate_code("t")
        self.assertIn("def ok", code)
        self.assertEqual(post.call_count, 2)

    def test_language_alias_and_invalid_names(self):
        with patch("local_coder.client.requests.post", return_value=reply("```python\nx = 1\n```")):
            code, _ = self.client.generate_code("t", language="PY")
        self.assertEqual(code, "x = 1")
        with self.assertRaises(ValueError):
            self.client.generate_code("t", language="bash; rm")


class TestReviewLanguage(unittest.TestCase):
    def test_language_is_guessed_from_the_name_or_extension(self):
        cases = {
            "src/app.py": "python", "a/b/deploy.SH": "bash", "x.ts": "typescript", "Dockerfile": "dockerfile",
            "path/to/Makefile": "makefile", "config.yml": "yaml", "main.go": "go", "C:\\proj\\Main.java": "java",
            "noextension": None, "archive.tar.gz": None, ".hidden": None, "": None, None: None,
        }  # fmt: skip
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(language_for_path(path), expected)

    def test_review_prompt_fences_the_code_with_the_right_language(self):
        def fence(path, language=None):
            user = build_review_prompt("CODE", path, None, language)[1]["content"]
            return user.split("\n")[1]

        self.assertEqual(fence("module.py"), "```python")  # unchanged for Python
        self.assertEqual(fence("deploy.sh"), "```bash")
        self.assertEqual(fence("unknown.xyz"), "```")  # not assumed to be Python any more
        self.assertEqual(fence("deploy.sh", "PY"), "```python")  # an explicit language wins
        with self.assertRaises(ValueError):
            build_review_prompt("CODE", "a.py", None, "bash; rm")

    def test_client_passes_the_language_into_the_prompt(self):
        client = UnifiedLocalCoderClient()
        info = EngineInfo(
            "Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True, installed_models=["llama3.1:8b"]
        )
        with (
            patch.object(client.router, "resolve_target_engine", return_value=info),
            patch("local_coder.client.requests.post", return_value=reply("looks fine")) as post,
        ):
            client.review_code("echo hi", "deploy.sh")
            client.review_code("echo hi", "deploy.sh", language="zsh")
        prompts = [c.kwargs["json"]["messages"][1]["content"] for c in post.call_args_list]
        self.assertIn("```bash\necho hi", prompts[0])
        self.assertIn("```zsh\necho hi", prompts[1])


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return out.getvalue(), err.getvalue(), code


class TestCliLanguage(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.generate_code.return_value = ("echo hi", CompletionResult("x", "m", "E"))

    def test_unified_cli_passes_language(self):
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "code", "--task", "t", "--language", "bash"]),
        ):
            out, _, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 0)
        self.assertEqual(self.client.generate_code.call_args.kwargs["language"], "bash")
        self.assertEqual(out.strip(), "echo hi")

    def test_unified_cli_default_is_python_and_bad_names_are_a_usage_error(self):
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "code", "--task", "t"]),
        ):
            run(lambda _argv: cli.main(), None)
        self.assertEqual(self.client.generate_code.call_args.kwargs["language"], "python")
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "code", "--task", "t", "--language", "bash; rm"]),
        ):
            _, err, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 2)
        self.assertIn("Invalid language", err)

    def test_review_language_reaches_the_client_from_every_cli(self):
        self.client.review_code.return_value = CompletionResult("ok", "m", "E")
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("echo hi\n")
        self.addCleanup(os.remove, f.name)
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "review", "--file", f.name, "--language", "bash"]),
        ):
            run(lambda _argv: cli.main(), None)
        self.assertEqual(self.client.review_code.call_args.kwargs["language"], "bash")
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "review", "--file", f.name]),
        ):
            run(lambda _argv: cli.main(), None)
        self.assertIsNone(self.client.review_code.call_args.kwargs["language"])  # inferred later from the extension
        for module in (compat_ollama, compat_foundry):
            with (
                self.subTest(module=module.__name__),
                patch("local_coder.compat_cli.UnifiedLocalCoderClient", return_value=self.client),
            ):
                _, _, rc = run(module.cli_main, ["review", "--file", f.name, "--language", "yaml"])
            self.assertEqual(rc, 0)
            self.assertEqual(self.client.review_code.call_args.kwargs["language"], "yaml")

    def test_legacy_clis_pass_language(self):
        for module in (compat_ollama, compat_foundry):
            with (
                self.subTest(module=module.__name__),
                patch("local_coder.compat_cli.UnifiedLocalCoderClient", return_value=self.client),
            ):
                _, _, rc = run(module.cli_main, ["code", "--task", "t", "--language", "yaml"])
            self.assertEqual(rc, 0)
            self.assertEqual(self.client.generate_code.call_args.kwargs["language"], "yaml")

    def test_unified_cli_passes_language_to_test_and_refactor(self):
        self.client.generate_tests.return_value = ("ok", CompletionResult("x", "m", "E"))
        self.client.refactor_code.return_value = ("ok", CompletionResult("x", "m", "E"))
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("echo hi\n")
        self.addCleanup(os.remove, f.name)
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "test", "--file", f.name, "--language", "bash"]),
        ):
            out, _, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 0)
        self.assertEqual(self.client.generate_tests.call_args.kwargs.get("language"), "bash")
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "refactor", "--file", f.name, "--language", "yaml"]),
        ):
            out, _, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 0)
        self.assertEqual(self.client.refactor_code.call_args.kwargs.get("language"), "yaml")
        # defaults to python when --language is omitted
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "test", "--file", f.name]),
        ):
            run(lambda _argv: cli.main(), None)
        self.assertEqual(self.client.generate_tests.call_args.kwargs.get("language"), "python")

    def test_cli_test_allows_custom_framework_and_non_python_omitted(self):
        self.client.generate_tests.return_value = ("ok", CompletionResult("x", "m", "E"))
        with tempfile.NamedTemporaryFile("w", suffix=".go", delete=False) as f:
            f.write("package main\n")
        self.addCleanup(os.remove, f.name)
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(
                sys, "argv", ["ask_coder.py", "test", "--file", f.name, "--language", "go", "--framework", "testing"]
            ),
        ):
            _, _, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 0)
        self.assertEqual(self.client.generate_tests.call_args.kwargs.get("framework"), "testing")
        self.assertEqual(self.client.generate_tests.call_args.kwargs.get("language"), "go")

    def test_legacy_clis_pass_language_to_test_and_refactor(self):
        self.client.generate_tests.return_value = ("ok", CompletionResult("x", "m", "E"))
        self.client.refactor_code.return_value = ("ok", CompletionResult("x", "m", "E"))
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("echo hi\n")
        self.addCleanup(os.remove, f.name)
        for module in (compat_ollama, compat_foundry):
            with (
                self.subTest(module=module.__name__),
                patch("local_coder.compat_cli.UnifiedLocalCoderClient", return_value=self.client),
            ):
                _, _, rc = run(module.cli_main, ["test", "--file", f.name, "--language", "bash"])
            self.assertEqual(rc, 0)
            self.assertEqual(self.client.generate_tests.call_args.kwargs.get("language"), "bash")
            with (
                self.subTest(module=module.__name__),
                patch("local_coder.compat_cli.UnifiedLocalCoderClient", return_value=self.client),
            ):
                _, _, rc = run(module.cli_main, ["refactor", "--file", f.name, "--language", "yaml"])
            self.assertEqual(rc, 0)
            self.assertEqual(self.client.refactor_code.call_args.kwargs.get("language"), "yaml")

    def test_invalid_language_is_a_usage_error_for_test_and_refactor(self):
        self.client.generate_tests.return_value = ("ok", CompletionResult("x", "m", "E"))
        self.client.refactor_code.return_value = ("ok", CompletionResult("x", "m", "E"))
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("echo hi\n")
        self.addCleanup(os.remove, f.name)
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "test", "--file", f.name, "--language", "bash; rm"]),
        ):
            _, err, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 2)
        self.assertIn("Invalid language", err)
        with (
            patch("local_coder.cli.UnifiedLocalCoderClient", return_value=self.client),
            patch.object(sys, "argv", ["ask_coder.py", "refactor", "--file", f.name, "--language", "bash; rm"]),
        ):
            _, err, rc = run(lambda _argv: cli.main(), None)
        self.assertEqual(rc, 2)
        self.assertIn("Invalid language", err)


class TestMcpLanguage(unittest.TestCase):
    def test_schema_advertises_language_for_every_generation_tool(self):
        tools = {t["name"]: t for t in local_coder_mcp_server.handle_list_tools()}
        for tool in ("local_code", "local_test", "local_refactor", "local_code_review"):
            with self.subTest(tool=tool):
                self.assertIn(
                    "language",
                    tools[tool]["inputSchema"]["properties"],
                    f"{tool} must advertise a 'language' parameter",
                )

    def test_review_tool_advertises_and_forwards_language(self):
        tools = {t["name"]: t for t in local_coder_mcp_server.handle_list_tools()}
        self.assertIn("language", tools["local_code_review"]["inputSchema"]["properties"])
        res = CompletionResult("fine", "m", "E")
        with patch.object(local_coder_mcp_server.client, "review_code", return_value=res) as review:
            local_coder_mcp_server.handle_call_tool(
                1, "local_code_review", {"code": "x", "file_path": "a.sh", "language": "bash"}
            )
            self.assertEqual(review.call_args.kwargs["language"], "bash")
            local_coder_mcp_server.handle_call_tool(
                2, "local_code_review", {"code": "x", "file_path": "a.sh", "language": ""}
            )
            self.assertIsNone(review.call_args.kwargs["language"])  # empty means: guess from the path

    def test_language_is_forwarded_and_invalid_ones_become_an_error(self):
        res = CompletionResult("x", "m", "E")
        with patch.object(local_coder_mcp_server.client, "generate_code", return_value=("echo hi", res)) as gen:
            resp = local_coder_mcp_server.handle_call_tool(1, "local_code", {"task": "t", "language": "bash"})
        self.assertEqual(gen.call_args.kwargs["language"], "bash")
        self.assertIn("echo hi", resp["result"]["content"][0]["text"])
        resp = local_coder_mcp_server.handle_call_tool(2, "local_code", {"task": "t", "language": "bash; rm"})
        self.assertEqual(resp["error"]["code"], -32603)
        self.assertIn("Invalid language", resp["error"]["message"])
        with patch.object(local_coder_mcp_server.client, "generate_code", return_value=("x = 1", res)) as gen:
            local_coder_mcp_server.handle_call_tool(3, "local_code", {"task": "t"})
        self.assertEqual(gen.call_args.kwargs["language"], "python")

    def test_test_tool_advertises_and_forwards_language(self):
        res = CompletionResult("x", "m", "E")
        with patch.object(local_coder_mcp_server.client, "generate_tests", return_value=("ok", res)) as gen:
            resp = local_coder_mcp_server.handle_call_tool(
                1, "local_test", {"code": "x", "file_path": "a.sh", "language": "bash"}
            )
        self.assertEqual(gen.call_args.kwargs.get("language"), "bash")
        self.assertIn("ok", resp["result"]["content"][0]["text"])
        with patch.object(local_coder_mcp_server.client, "generate_tests", return_value=("ok", res)) as gen:
            local_coder_mcp_server.handle_call_tool(2, "local_test", {"code": "x", "file_path": "a.sh"})
        self.assertEqual(gen.call_args.kwargs.get("language"), "python")  # default
        resp = local_coder_mcp_server.handle_call_tool(
            3, "local_test", {"code": "x", "file_path": "a.sh", "language": "bash; rm"}
        )
        self.assertEqual(resp["error"]["code"], -32603)
        self.assertIn("Invalid language", resp["error"]["message"])

    def test_refactor_tool_advertises_and_forwards_language(self):
        res = CompletionResult("x", "m", "E")
        with patch.object(local_coder_mcp_server.client, "refactor_code", return_value=("ok", res)) as ref:
            resp = local_coder_mcp_server.handle_call_tool(
                1, "local_refactor", {"code": "x", "file_path": "a.sh", "language": "yaml"}
            )
        self.assertEqual(ref.call_args.kwargs.get("language"), "yaml")
        self.assertIn("ok", resp["result"]["content"][0]["text"])
        with patch.object(local_coder_mcp_server.client, "refactor_code", return_value=("ok", res)) as ref:
            local_coder_mcp_server.handle_call_tool(2, "local_refactor", {"code": "x", "file_path": "a.sh"})
        self.assertEqual(ref.call_args.kwargs.get("language"), "python")  # default
        resp = local_coder_mcp_server.handle_call_tool(
            3, "local_refactor", {"code": "x", "file_path": "a.sh", "language": "bash; rm"}
        )
        self.assertEqual(resp["error"]["code"], -32603)
        self.assertIn("Invalid language", resp["error"]["message"])


if __name__ == "__main__":
    unittest.main()
