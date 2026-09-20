"""Model resolution and fallbacks, request sizing, Foundry loading, telemetry totals, auto-extend and discovery cache."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from local_coder.client import ModelNotInstalledError, UnifiedLocalCoderClient
from local_coder.router import MODEL_FALLBACKS, MODEL_PROFILES, EngineRouter
from local_coder.telemetry import calculate_savings, format_result_banner
from local_coder.types import CompletionResult, EngineInfo, EngineType


def info(kind: EngineType, models: list[str], name: str | None = None) -> EngineInfo:
    urls = {
        EngineType.OLLAMA: "http://localhost:11434/v1",
        EngineType.PRISM: "http://127.0.0.1:5272/v1",
        EngineType.FOUNDRY: "http://127.0.0.1:41301/v1",
    }
    return EngineInfo(name or kind.value.title(), kind, urls[kind], True, installed_models=models)


def ollama_reply(content="x", reason="stop", prompt=10, completion=20):
    return MagicMock(
        status_code=200,
        json=lambda: {
            "message": {"content": content},
            "done_reason": reason,
            "prompt_eval_count": prompt,
            "eval_count": completion,
            "eval_duration": 1_000_000_000,
        },
    )


class TestModelResolution(unittest.TestCase):
    def setUp(self):
        self.client = UnifiedLocalCoderClient()

    def resolve(self, engine_info, profile=None, model=None):
        with patch.object(self.client.router, "resolve_target_engine", return_value=engine_info):
            return self.client.resolve_engine_and_model(profile=profile, model=model)[1]

    def test_names_match_across_engines(self):
        ollama = info(EngineType.OLLAMA, ["qwen2.5-coder:7b", "llama3.1:8b"])
        self.assertEqual(self.resolve(ollama, model="qwen2.5-coder-7b"), "qwen2.5-coder:7b")
        prism = info(EngineType.PRISM, ["qwen2.5-coder-7b-instruct-generic-cpu-4:v4", "ollama:qwen2.5-coder:7b"])
        self.assertEqual(self.resolve(prism, model="qwen2.5-coder:7b"), "ollama:qwen2.5-coder:7b")

    def test_unknown_explicit_model_is_passed_through(self):
        ollama = info(EngineType.OLLAMA, ["llama3.1:8b"])
        self.assertEqual(self.resolve(ollama, model="mystery:1b"), "mystery:1b")

    def test_profile_uses_a_fallback_and_says_so(self):
        ollama = info(EngineType.OLLAMA, ["qwen2.5-coder:14b", "llama3.1:8b"])
        with patch("local_coder.client.sys.stderr") as err:
            chosen = self.resolve(ollama, profile="coding")
        self.assertEqual(chosen, "qwen2.5-coder:14b")
        self.assertIn("not installed", "".join(c.args[0] for c in err.write.call_args_list))

    def test_preferred_model_is_used_silently_when_installed(self):
        ollama = info(EngineType.OLLAMA, ["qwen2.5-coder:7b", "qwen2.5-coder:14b"])
        with patch("local_coder.client.sys.stderr") as err:
            self.assertEqual(self.resolve(ollama, profile="coding"), "qwen2.5-coder:7b")
        err.write.assert_not_called()

    def test_no_usable_model_gives_a_clear_error_before_any_request(self):
        ollama = info(EngineType.OLLAMA, ["mistral:7b"])
        with self.assertRaises(ModelNotInstalledError) as ctx:
            self.resolve(ollama, profile="coding")
        message = str(ctx.exception)
        self.assertIn("qwen2.5-coder:7b", message)
        self.assertIn("mistral:7b", message)
        self.assertIn("ollama pull", message)

    def test_engine_that_lists_nothing_gets_the_preferred_model(self):
        self.assertEqual(self.resolve(info(EngineType.OLLAMA, []), profile="coding"), "qwen2.5-coder:7b")

    def test_every_profile_has_fallbacks_only_for_known_engines(self):
        for profile, per_engine in MODEL_FALLBACKS.items():
            self.assertIn(profile, MODEL_PROFILES)
            self.assertLessEqual(set(per_engine), {"prism", "ollama", "foundry"})

    @patch("local_coder.client.requests.post")
    def test_model_not_found_from_the_engine_is_explained(self, post):
        post.return_value = MagicMock(status_code=404, text='{"error":"model \'nope:1b\' not found"}')
        ollama = info(EngineType.OLLAMA, ["llama3.1:8b"])
        with patch.object(self.client.router, "resolve_target_engine", return_value=ollama):
            with self.assertRaises(ModelNotInstalledError) as ctx:
                self.client.complete([{"role": "user", "content": "x"}], model="nope:1b")
        self.assertIn("llama3.1:8b", str(ctx.exception))
        self.assertIn("ollama pull", str(ctx.exception))


class TestRequestSizing(unittest.TestCase):
    def test_ollama_context_grows_to_fit_prompt_and_answer(self):
        client = UnifiedLocalCoderClient()
        ollama = info(EngineType.OLLAMA, ["qwen2.5-coder:7b"])
        _, small = client._build_request(ollama, "m", [{"role": "user", "content": "hi"}], 0.1, 100)
        self.assertEqual(small["options"]["num_ctx"], client.num_ctx)
        big_prompt = [{"role": "user", "content": "x" * 30000}]
        _, big = client._build_request(ollama, "m", big_prompt, 0.1, 4096)
        self.assertGreater(big["options"]["num_ctx"], client.num_ctx)
        self.assertGreaterEqual(big["options"]["num_ctx"], 10000 + 4096)
        _, capped = client._build_request(ollama, "m", [{"role": "user", "content": "x" * 400000}], 0.1, 4096)
        self.assertEqual(capped["options"]["num_ctx"], 32768)


class TestFoundryLoading(unittest.TestCase):
    def setUp(self):
        self.client = UnifiedLocalCoderClient()
        self.not_loaded = MagicMock(
            status_code=400, text="Failed to handle OpenAI completion: Model 'x' is not loaded."
        )
        self.ok = MagicMock(status_code=200, json=lambda: {"choices": [{"message": {"content": "ok"}}]})

    def complete(self, engine_info, replies):
        with (
            patch.object(self.client.router, "resolve_target_engine", return_value=engine_info),
            patch("local_coder.client.requests.post", side_effect=replies),
        ):
            return self.client.complete([{"role": "user", "content": "x"}], model="phi-3.5-mini")

    def test_foundry_model_is_loaded_with_the_cli_then_retried(self):
        foundry = info(EngineType.FOUNDRY, ["phi-3.5-mini"])
        with (
            patch("local_coder.client.shutil.which", return_value="/usr/bin/foundry"),
            patch("local_coder.client.subprocess.run", return_value=MagicMock(returncode=0)) as run,
        ):
            res = self.complete(foundry, [self.not_loaded, self.ok])
        self.assertEqual(res.content, "ok")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/foundry", "model", "load", "phi-3.5-mini"])

    def test_prism_never_shells_out_and_reports_its_own_answer(self):
        prism = info(EngineType.PRISM, ["phi-4-mini"])
        with patch("local_coder.client.subprocess.run") as run, self.assertRaises(RuntimeError) as ctx:
            self.complete(prism, [self.not_loaded])
        run.assert_not_called()
        self.assertIn("HTTP 400", str(ctx.exception))

    def test_load_failures_are_reported_not_swallowed(self):
        foundry = info(EngineType.FOUNDRY, ["phi-3.5-mini"])
        with (
            patch("local_coder.client.shutil.which", return_value="/usr/bin/foundry"),
            patch(
                "local_coder.client.subprocess.run",
                return_value=MagicMock(returncode=1, stderr="no such model", stdout=""),
            ),
            self.assertRaises(RuntimeError) as ctx,
        ):
            self.complete(foundry, [self.not_loaded])
        self.assertIn("no such model", str(ctx.exception))

    def test_missing_cli_is_reported(self):
        foundry = info(EngineType.FOUNDRY, ["phi-3.5-mini"])
        with patch("local_coder.client.shutil.which", return_value=None), self.assertRaises(RuntimeError) as ctx:
            self.complete(foundry, [self.not_loaded])
        self.assertIn("not on PATH", str(ctx.exception))


class TestTotalsAndAutoExtend(unittest.TestCase):
    def setUp(self):
        self.client = UnifiedLocalCoderClient()
        self.ollama = info(EngineType.OLLAMA, ["qwen2.5-coder:7b"])
        patcher = patch.object(self.client.router, "resolve_target_engine", return_value=self.ollama)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_healing_tokens_are_counted_in_the_result(self):
        replies = [
            ollama_reply("```python\ndef broken(:\n```", prompt=10, completion=20),
            ollama_reply("```python\ndef ok():\n    return 1\n```", prompt=30, completion=40),
        ]
        with patch("local_coder.client.requests.post", side_effect=replies):
            code, res = self.client.generate_code("t")
        self.assertIn("def ok", code)
        self.assertEqual((res.prompt_tokens, res.completion_tokens, res.total_tokens), (40, 60, 100))
        self.assertEqual(res.saved_tokens, 100)
        self.assertAlmostEqual(res.saved_usd, calculate_savings(40, 60)[1])

    def test_truncated_output_is_retried_once_with_a_larger_default_limit(self):
        replies = [
            ollama_reply("def f(", reason="length", prompt=5, completion=4096),
            ollama_reply("def f():\n    return 1", prompt=5, completion=30),
        ]
        with patch("local_coder.client.requests.post", side_effect=replies) as post:
            code, res = self.client.generate_code("t", self_heal=False)
        self.assertEqual(code, "def f():\n    return 1")
        limits = [c.kwargs["json"]["options"]["num_predict"] for c in post.call_args_list]
        self.assertEqual(limits, [4096, 8192])
        self.assertFalse(res.truncated)
        self.assertEqual(res.completion_tokens, 4126)
        self.assertEqual(res.max_tokens, 8192)

    def test_an_explicit_limit_is_never_extended(self):
        with patch("local_coder.client.requests.post", return_value=ollama_reply("def f(", reason="length")) as post:
            _, res = self.client.generate_code("t", self_heal=False, max_tokens=50)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(res.truncated)
        self.assertIn("(50)", format_result_banner(res))

    def test_extension_stops_after_one_retry_and_still_flags_truncation(self):
        with patch("local_coder.client.requests.post", return_value=ollama_reply("def f(", reason="length")) as post:
            _, res = self.client.generate_code("t", self_heal=False)
        self.assertEqual(post.call_count, 2)
        self.assertTrue(res.truncated)
        self.assertIn("(8192)", format_result_banner(res))

    def test_healing_is_skipped_for_output_that_was_cut_off(self):
        with patch("local_coder.client.requests.post", return_value=ollama_reply("def f(", reason="length")) as post:
            code, res = self.client.generate_code("t", max_tokens=50)
        self.assertEqual(post.call_count, 1)  # no repair round-trips
        self.assertEqual(code, "def f(")
        self.assertTrue(res.truncated)

    def test_review_extends_too(self):
        replies = [ollama_reply("partial", reason="length"), ollama_reply("complete review")]
        with patch("local_coder.client.requests.post", side_effect=replies):
            res = self.client.review_code("x = 1", "a.py")
        self.assertEqual(res.content, "complete review")


class TestTelemetryPrices(unittest.TestCase):
    def test_reference_prices_are_overridable(self):
        self.assertEqual(calculate_savings(1_000_000, 1_000_000), (2_000_000, 18.0))
        with patch.dict(os.environ, {"LOCAL_CODER_PRICE_PROMPT": "1", "LOCAL_CODER_PRICE_COMPLETION": "2"}):
            self.assertEqual(calculate_savings(1_000_000, 1_000_000), (2_000_000, 3.0))
        with patch.dict(os.environ, {"LOCAL_CODER_PRICE_PROMPT": "not-a-number"}):
            self.assertEqual(calculate_savings(1_000_000, 0)[1], 3.0)

    def test_banner_reports_the_limit_the_result_was_produced_under(self):
        res = CompletionResult("x", "m", "E", finish_reason="length", max_tokens=8192)
        self.assertIn("(8192)", format_result_banner(res, 4096))


class TestDiscoveryCache(unittest.TestCase):
    def make_router(self, ttl: float):
        with patch.dict(os.environ, {"LOCAL_CODER_DISCOVERY_TTL": str(ttl)}):
            router = EngineRouter()
        calls = {"n": 0}

        def discover(kind):
            def fn():
                calls["n"] += 1
                return info(kind, ["m"])

            return fn

        router.discover_prism = discover(EngineType.PRISM)
        router.discover_ollama = discover(EngineType.OLLAMA)
        router.discover_foundry = discover(EngineType.FOUNDRY)
        return router, calls

    def test_scan_is_cached_within_the_ttl(self):
        router, calls = self.make_router(60)
        router.list_all_engines()
        router.list_all_engines()
        self.assertEqual(calls["n"], 3)

    def test_ttl_zero_disables_the_cache(self):
        router, calls = self.make_router(0)
        router.list_all_engines()
        router.list_all_engines()
        self.assertEqual(calls["n"], 6)

    def test_expiry_failure_and_explicit_invalidation_refresh_the_scan(self):
        router, calls = self.make_router(60)
        router.list_all_engines()
        with patch("local_coder.router.time.monotonic", return_value=router._discovered[0] + 61):
            router.list_all_engines()
        self.assertEqual(calls["n"], 6)
        router.mark_failed(EngineType.PRISM)
        router.list_all_engines()
        self.assertEqual(calls["n"], 9)
        router.invalidate_discovery()
        router.list_all_engines()
        self.assertEqual(calls["n"], 12)

    def test_status_always_shows_live_data(self):
        from local_coder.status import format_status

        router, calls = self.make_router(60)
        router.list_all_engines()
        format_status(router)
        self.assertEqual(calls["n"], 6)

    def test_a_complete_call_scans_once_not_per_step(self):
        client = UnifiedLocalCoderClient()
        with patch.dict(os.environ, {"LOCAL_CODER_DISCOVERY_TTL": "60"}):
            client.router.discovery_ttl = 60
        calls = {"n": 0}

        def discover(kind):
            def fn():
                calls["n"] += 1
                return info(kind, ["qwen2.5-coder:7b", "phi-4-mini"])

            return fn

        client.router.discover_prism = discover(EngineType.PRISM)
        client.router.discover_ollama = discover(EngineType.OLLAMA)
        client.router.discover_foundry = discover(EngineType.FOUNDRY)
        reply = MagicMock(
            status_code=200, json=lambda: {"choices": [{"message": {"content": "```python\nx = 1\n```"}}]}
        )
        with (
            patch("local_coder.client.requests.post", return_value=reply),
            patch("local_coder.router.platform.system", return_value="Linux"),
        ):
            client.generate_code("t")
            client.generate_code("t")
        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
