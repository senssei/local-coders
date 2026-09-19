"""Unit tests for the ollama-coder ask_local utility script."""

import os
import sys
import unittest
from unittest.mock import patch

# Add skill script directory to sys.path
SKILL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".agents", "skills", "ollama-coder", "scripts")
)
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from ask_local import (
    DEFAULT_PROFILES,
    extract_clean_code,
    resolve_model,
    self_healing_query,
    validate_python_code,
)


class TestAskLocalHelpers(unittest.TestCase):
    """Test helper functions in ask_local.py."""

    def test_extract_clean_code_with_python_tag(self):
        raw = "Here is the code:\n```python\ndef add(a, b):\n    return a + b\n```\nEnjoy!"
        cleaned = extract_clean_code(raw)
        self.assertEqual(cleaned, "def add(a, b):\n    return a + b")

    def test_extract_clean_code_with_generic_tag(self):
        raw = "```\nx = 42\n```"
        cleaned = extract_clean_code(raw)
        self.assertEqual(cleaned, "x = 42")

    def test_extract_clean_code_raw_code(self):
        raw = "def greet():\n    return 'hello'"
        cleaned = extract_clean_code(raw)
        self.assertEqual(cleaned, raw)

    def test_validate_python_code_valid(self):
        code = "def valid_func(x: int) -> int:\n    return x * 2\n"
        is_valid, err = validate_python_code(code)
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

    def test_validate_python_code_syntax_error(self):
        code = "def broken_func(x\n    return x"
        is_valid, err = validate_python_code(code)
        self.assertFalse(is_valid)
        self.assertIn("SyntaxError", err)

    def test_validate_python_code_indentation_error(self):
        code = "def func():\nx = 1"
        is_valid, err = validate_python_code(code)
        self.assertFalse(is_valid)
        self.assertIn("SyntaxError", err)

    def test_validate_python_code_empty(self):
        is_valid, err = validate_python_code("")
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

    def test_resolve_model_profiles(self):
        self.assertEqual(resolve_model("fast", None), DEFAULT_PROFILES["fast"])
        self.assertEqual(resolve_model("coding", None), DEFAULT_PROFILES["coding"])
        self.assertEqual(resolve_model("reasoning", None), DEFAULT_PROFILES["reasoning"])

    def test_resolve_model_explicit_override(self):
        custom = "my-custom-model:latest"
        self.assertEqual(resolve_model("fast", model=custom), custom)
        self.assertEqual(resolve_model(None, model=custom), custom)

    def test_resolve_model_default(self):
        self.assertEqual(resolve_model(None, None), DEFAULT_PROFILES["coding"])


class TestSelfHealingQuery(unittest.TestCase):
    """Test self-healing loop in query dispatch."""

    @patch("ask_local.query_ollama")
    def test_self_healing_passes_immediately(self, mock_query):
        mock_query.return_value = (
            "```python\ndef hello():\n    return 'world'\n```",
            {"model": "qwen2.5-coder:7b", "eval_count": 20, "eval_duration": 500_000_000, "tok_s": 40.0},
        )
        code, telem = self_healing_query("Write hello", "qwen2.5-coder:7b")
        self.assertEqual(code, "def hello():\n    return 'world'")
        self.assertEqual(mock_query.call_count, 1)

    @patch("ask_local.query_ollama")
    def test_self_healing_recovers_from_syntax_error(self, mock_query):
        broken_output = "```python\ndef hello(\n    return 'world'\n```"
        fixed_output = "```python\ndef hello():\n    return 'world'\n```"

        telem = {"model": "qwen2.5-coder:7b", "eval_count": 20, "eval_duration": 500_000_000, "tok_s": 40.0}
        mock_query.side_effect = [
            (broken_output, telem),
            (fixed_output, telem),
        ]

        code, telem_res = self_healing_query("Write hello", "qwen2.5-coder:7b", auto_heal=True, max_retries=2)
        self.assertEqual(code, "def hello():\n    return 'world'")
        self.assertEqual(mock_query.call_count, 2)

    @patch("ask_local.query_ollama")
    def test_no_heal_returns_raw_code(self, mock_query):
        broken_output = "```python\ndef hello(\n    return 'world'\n```"
        telem = {"model": "qwen2.5-coder:7b", "eval_count": 20, "eval_duration": 500_000_000, "tok_s": 40.0}
        mock_query.return_value = (broken_output, telem)

        code, _ = self_healing_query("Write hello", "qwen2.5-coder:7b", auto_heal=False)
        self.assertEqual(code, "def hello(\n    return 'world'")
        self.assertEqual(mock_query.call_count, 1)

    def test_format_telemetry_summary(self):
        from ask_local import format_telemetry_summary

        telem = {
            "model": "qwen2.5-coder:7b",
            "tok_s": 42.5,
            "eval_count": 100,
            "prompt_eval_count": 50,
            "tokens_saved": 150,
            "cost_saved_usd": 0.00165,
            "total_sec": 2.35,
        }
        summary = format_telemetry_summary(telem)
        self.assertIn("qwen2.5-coder:7b", summary)
        self.assertIn("42.5 tok/s", summary)
        self.assertIn("100 tokens", summary)
        self.assertIn("150 cloud tokens", summary)
        self.assertIn("$0.0016", summary)


if __name__ == "__main__":
    unittest.main()
