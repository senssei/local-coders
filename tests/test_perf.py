"""Performance state for status lines: recording, aggregation, formatting, the stand-alone script, client and MCP."""

import json
import multiprocessing
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import local_coder_mcp_server
from local_coder import perf
from local_coder.client import UnifiedLocalCoderClient
from local_coder.models import EngineInfo, EngineType

NOON = datetime(2026, 9, 20, 12, 0, 0).timestamp()


def call(**kw):
    defaults = {
        "engine": "Ollama",
        "model": "qwen2.5-coder:7b",
        "task": "code",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "duration_s": 1.0,
        "tokens_per_sec": 84.2,
        "saved_usd": 0.01,
    }
    perf.record_call(**{**defaults, **kw})


def _worker(args):
    state_dir, n = args
    os.environ.update({"LOCAL_CODER_PERF": "1", "LOCAL_CODER_STATE_DIR": state_dir})
    for _ in range(n):
        call(now=NOON)


class PerfCase(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        patcher = patch.dict(os.environ, {"LOCAL_CODER_PERF": "1", "LOCAL_CODER_STATE_DIR": str(self.dir)})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestRecording(PerfCase):
    def test_last_call_and_daily_totals(self):
        call(now=NOON, saved_usd=0.01)
        call(
            now=NOON + 5,
            engine="Prism",
            model="Phi-4-mini-instruct-generic-cpu-5:v5",
            tokens_per_sec=108.0,
            saved_usd=0.02,
        )
        data = perf.load()
        self.assertEqual(data["last"]["engine"], "Prism")
        day = data["days"]["2026-09-20"]
        self.assertEqual((day["calls"], day["prompt_tokens"], day["completion_tokens"]), (2, 200, 100))
        self.assertAlmostEqual(day["saved_usd"], 0.03)
        self.assertEqual(day["engines"], {"Ollama": 1, "Prism": 1})

    def test_days_roll_over_and_old_ones_are_pruned(self):
        for offset in range(20):
            call(now=NOON + offset * 86400)
        days = perf.load()["days"]
        self.assertEqual(len(days), perf.KEEP_DAYS)
        self.assertNotIn("2026-09-20", days)  # the oldest went first

    def test_no_prompt_or_output_text_is_stored(self):
        call(now=NOON)
        text = (self.dir / "perf.json").read_text()
        self.assertEqual(
            set(perf.load()["last"]),
            {
                "ts",
                "engine",
                "model",
                "task",
                "tok_s",
                "prompt_tokens",
                "completion_tokens",
                "duration_s",
                "truncated",
                "saved_usd",
            },
        )
        self.assertNotIn("content", text)

    def test_disabled_by_environment(self):
        with patch.dict(os.environ, {"LOCAL_CODER_PERF": "0"}):
            call(now=NOON)
        self.assertFalse((self.dir / "perf.json").exists())

    def test_corrupt_or_foreign_files_do_not_break_reading_or_writing(self):
        (self.dir / "perf.json").write_text("{ not json")
        self.assertEqual(perf.load()["days"], {})
        self.assertEqual(perf.format_line(perf.load()), "")
        call(now=NOON)  # overwrites the garbage
        self.assertEqual(perf.load()["days"]["2026-09-20"]["calls"], 1)
        (self.dir / "perf.json").write_text("[1, 2]")
        self.assertEqual(perf.load()["days"], {})

    def test_an_unwritable_state_directory_never_raises(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        with patch.dict(os.environ, {"LOCAL_CODER_STATE_DIR": str(blocker / "sub")}):
            call(now=NOON)  # must simply do nothing

    def test_concurrent_writers_do_not_lose_updates(self):
        with multiprocessing.get_context("spawn").Pool(4) as pool:
            pool.map(_worker, [(str(self.dir), 15)] * 4)
        self.assertEqual(perf.load()["days"]["2026-09-20"]["calls"], 60)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_state_directory_resolution(self):
        with patch.dict(os.environ, {"LOCAL_CODER_STATE_DIR": "", "XDG_STATE_HOME": str(self.dir / "xdg")}):
            self.assertEqual(perf.state_path(), self.dir / "xdg" / "local-coders" / "perf.json")


class TestFormatting(PerfCase):
    def line(self, now, **kw):
        return perf.format_line(perf.load(), now=now, **kw)

    def test_fresh_call_and_totals(self):
        call(now=NOON, saved_usd=0.0054)
        self.assertEqual(self.line(NOON + 30), "⚡ Ollama qwen2.5-coder:7b 84 tok/s · today 1 call, saved ~$0.005")
        call(now=NOON + 1, saved_usd=0.02)
        self.assertIn("today 2 calls, saved ~$0.03", self.line(NOON + 30))

    def test_a_stale_call_stays_with_its_age_so_the_row_does_not_look_frozen(self):
        call(now=NOON)
        self.assertEqual(self.line(NOON + 30), "⚡ Ollama qwen2.5-coder:7b 84 tok/s · today 1 call, saved ~$0.01")
        self.assertEqual(
            self.line(NOON + 3 * 60 + 5, max_age=60),
            "⚡ Ollama qwen2.5-coder:7b 84 tok/s (3m ago) · today 1 call, saved ~$0.01",
        )
        self.assertIn("(1h ago)", self.line(NOON + 3600 + 30))
        self.assertIn("(just now)", self.line(NOON + 10, max_age=5))
        self.assertIn("(2h ago)", self.line(NOON + 2 * 3600 + 60))

    def test_a_call_from_an_earlier_day_is_not_shown_only_todays_totals_would_be(self):
        call(now=NOON)
        self.assertEqual(self.line(NOON + 86400 + 3600), "")  # yesterday's call, nothing today: empty
        call(now=NOON + 86400 + 60)
        self.assertNotIn("ago", self.line(NOON + 86400 + 90))  # today's call is fresh

    def test_nothing_recorded_today_means_an_empty_line(self):
        call(now=NOON)
        self.assertEqual(self.line(NOON + 2 * 86400), "")
        self.assertEqual(perf.format_line(perf._empty()), "")

    def test_truncation_and_engine_down_are_flagged(self):
        call(now=NOON, truncated=True)
        self.assertIn("84 tok/s ⚠ truncated", self.line(NOON + 1))
        perf.record_failure("Ollama", "connection refused", now=NOON + 10)
        self.assertTrue(self.line(NOON + 20).startswith("⚡ Ollama unreachable"))
        call(now=NOON + 30)  # answering again clears it
        self.assertNotIn("unreachable", self.line(NOON + 31))

    def test_model_names_are_shortened(self):
        self.assertEqual(perf.short_model("Phi-4-mini-instruct-generic-cpu-5:v5"), "Phi-4-mini")
        self.assertEqual(perf.short_model("qwen2.5-coder-7b-instruct-generic-cpu-4:v4"), "qwen2.5-coder-7b")
        self.assertEqual(perf.short_model("qwen3-0.6b-generic-cpu-4:v4"), "qwen3-0.6b")
        self.assertEqual(perf.short_model("qwen2.5-coder:7b"), "qwen2.5-coder:7b")

    def test_color_wraps_the_line_only_when_asked(self):
        call(now=NOON)
        self.assertNotIn("\x1b", self.line(NOON + 1))
        self.assertTrue(self.line(NOON + 1, color=True).startswith("\x1b[2m"))


class TestStandaloneScript(PerfCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "local_coder" / "perf.py"), *args],
            capture_output=True,
            text=True,
            cwd="/",
            env={**os.environ},
        )

    def test_line_and_json_modes(self):
        call(now=time.time())
        line = self.run_script("--line")
        self.assertEqual(line.returncode, 0, line.stderr)
        self.assertIn("⚡ Ollama qwen2.5-coder:7b 84 tok/s", line.stdout)
        data = json.loads(self.run_script("--json").stdout)
        self.assertTrue(data["summary"]["fresh"])
        self.assertEqual(data["state"]["last"]["engine"], "Ollama")

    def test_empty_state_prints_nothing_and_succeeds(self):
        result = self.run_script("--line")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_it_runs_without_the_package_or_requests(self):
        code = (
            "import runpy, sys\n"
            f"sys.path = [p for p in sys.path if p not in ('', {str(REPO_ROOT)!r})]\n"
            "sys.argv = ['perf.py', '--json']\n"
            f"try:\n    runpy.run_path({str(REPO_ROOT / 'local_coder' / 'perf.py')!r}, run_name='__main__')\n"
            "except SystemExit:\n    pass\n"
            "print('requests' in sys.modules, 'local_coder' in sys.modules)"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/", env={**os.environ})
        self.assertEqual(out.stdout.strip().splitlines()[-1], "False False", out.stderr)

    def test_cli_subcommand_answers_without_a_client(self):
        call(now=time.time())
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "ask_coder.py"), "perf", "--line"],
            capture_output=True,
            text=True,
            cwd="/",
            env={**os.environ},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("⚡ Ollama", proc.stdout)


class TestClientAndMcp(PerfCase):
    def setUp(self):
        super().setUp()
        self.client = UnifiedLocalCoderClient()
        info = EngineInfo(
            "Ollama", EngineType.OLLAMA, "http://localhost:11434/v1", True, installed_models=["qwen2.5-coder:7b"]
        )
        patcher = patch.object(self.client.router, "resolve_target_engine", return_value=info)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_completion_is_recorded(self):
        reply = MagicMock(
            status_code=200,
            json=lambda: {
                "message": {"content": "x"},
                "done_reason": "length",
                "prompt_eval_count": 7,
                "eval_count": 9,
                "eval_duration": 1_000_000_000,
            },
        )
        with patch("local_coder.client.requests.post", return_value=reply):
            self.client.complete([{"role": "user", "content": "hi"}], task="review", max_tokens=5)
        last = perf.load()["last"]
        self.assertEqual(
            (last["engine"], last["model"], last["task"], last["truncated"]),
            ("Ollama", "qwen2.5-coder:7b", "review", True),
        )
        self.assertEqual((last["prompt_tokens"], last["completion_tokens"], last["tok_s"]), (7, 9, 9.0))

    def test_a_connection_failure_is_recorded(self):
        import requests

        with (
            patch("local_coder.client.requests.post", side_effect=requests.exceptions.ConnectionError("down")),
            self.assertRaises(ConnectionError),
        ):
            self.client.complete([{"role": "user", "content": "hi"}], engine=EngineType.OLLAMA)
        self.assertEqual(perf.load()["failure"]["engine"], "Ollama")

    def test_mcp_tool_reports_the_same_data(self):
        self.assertIn(
            "no local calls recorded today",
            local_coder_mcp_server.handle_call_tool(1, "local_perf", {})["result"]["content"][0]["text"],
        )
        call(now=time.time())
        text = local_coder_mcp_server.handle_call_tool(2, "local_perf", {})["result"]["content"][0]["text"]
        self.assertIn("⚡ Ollama qwen2.5-coder:7b 84 tok/s", text)
        self.assertIn('"fresh": true', text)
        self.assertIn("local_perf", [t["name"] for t in local_coder_mcp_server.handle_list_tools()])


if __name__ == "__main__":
    unittest.main()
