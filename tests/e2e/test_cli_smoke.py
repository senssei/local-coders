"""End-to-end smoke tests for ``ask_coder.py`` against a real Ollama server.

Opt-in only. The whole class is skipped unless ``LOCAL_CODER_E2E=1`` is set in the environment. With the
flag set, it also skips when Ollama is not reachable at ``http://127.0.0.1:11434/api/tags`` within one
second, so the suite stays safe on machines without a local engine.

The tests run ``python3 ask_coder.py`` from the repo root as a subprocess — the same way an operator
would invoke it. ``tests/conftest.py`` isolates routing files, the discovery cache and the perf state
file, so the suite never touches the real ``~/.local/state/local-coders/``.

This suite is **out of scope** for ``scripts/sdlc_check.py`` (the gate stays hermetic and fast). Run it
directly:

    LOCAL_CODER_E2E=1 .venv/bin/python -m pytest tests/e2e/

It does not replace the hermetic ``tests/test_prism_engine.py`` (Phase 2) — it only exercises the CLI
plumbing with a live engine, and only checks the ``status`` and ``code`` subcommands.
"""

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
ASK_CODER = REPO_ROOT / "ask_coder.py"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_REACH_TIMEOUT_S = 1.0
CLI_TIMEOUT_S = 180  # model load + first token on a cold Ollama can take 30–60 s

# Local import: load extract_code_block from the package that lives next to ask_coder.py. The e2e test
# is not part of the hermetic gate, so it is fine to depend on local_coder/.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from local_coder.prompts import extract_code_block  # noqa: E402


def _ollama_reachable() -> bool:
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=OLLAMA_REACH_TIMEOUT_S)
    except Exception:
        return False
    return r.status_code == 200


@unittest.skipUnless(
    os.environ.get("LOCAL_CODER_E2E") == "1",
    "set LOCAL_CODER_E2E=1 to run end-to-end smoke tests against Ollama",
)
class TestCliSmoke(unittest.TestCase):
    """Smoke tests for ask_coder.py against a running Ollama."""

    @classmethod
    def setUpClass(cls) -> None:
        if not _ollama_reachable():
            raise unittest.SkipTest(f"Ollama is not reachable at {OLLAMA_TAGS_URL}")

    def _run_cli(self, *args: str, timeout: int = CLI_TIMEOUT_S) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ASK_CODER), *args],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=timeout,
            # LOCAL_CODER_ENGINE pins the engine so the test never reaches for Prism or Foundry.
            env={**os.environ, "LOCAL_CODER_ENGINE": "ollama"},
        )

    def test_status_reports_engine(self) -> None:
        """``ask_coder.py status --explain`` exits 0 and mentions ``ollama``."""
        result = self._run_cli("status", "--explain", timeout=15)
        self.assertEqual(
            result.returncode,
            0,
            f"status --explain failed (rc={result.returncode}):\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        combined = (result.stdout + result.stderr).lower()
        self.assertIn(
            "ollama",
            combined,
            f"expected 'ollama' in status output; got:\n{result.stdout}",
        )

    def test_code_produces_parseable_python(self) -> None:
        """``ask_coder.py code --task ... --language python`` exits 0 with a ```python block that ast-parses."""
        result = self._run_cli(
            "code",
            "--task",
            "Write a Python function that takes a list of integers and returns the sum of the even ones.",
            "--language",
            "python",
        )
        self.assertEqual(
            result.returncode,
            0,
            f"code --task failed (rc={result.returncode}):\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertTrue(result.stdout.strip(), "code --task returned empty stdout")

        code = extract_code_block(result.stdout, language="python")
        self.assertTrue(code, f"no code block extracted from output:\n{result.stdout}")

        # The real assertion: the extracted code parses as Python. Anything weaker (length, substring)
        # would let through a non-code answer that happens to mention Python.
        try:
            ast.parse(code)
        except SyntaxError as e:
            self.fail(f"extracted code does not parse as Python ({e}); first 400 chars:\n{code[:400]}")


if __name__ == "__main__":
    unittest.main()
