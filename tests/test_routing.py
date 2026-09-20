"""Routing exceptions: rule parsing, matching, precedence, router/client integration, cooldown and --explain."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from local_coder.client import UnifiedLocalCoderClient
from local_coder.models import EngineInfo, EngineType
from local_coder.router import EngineRouter
from local_coder.routing import RouteContext, RoutingConfigError, RoutingPolicy, parse_rules
from local_coder.status import format_status

PRISM, OLLAMA, FOUNDRY = EngineType.PRISM, EngineType.OLLAMA, EngineType.FOUNDRY
LINUX_ORDER = [PRISM, OLLAMA, FOUNDRY]


def rules(*raw: dict):
    return parse_rules({"rules": list(raw)}, "test.json")


def engines(prism=True, ollama=True, foundry=False) -> list[EngineInfo]:
    return [
        EngineInfo("Prism", PRISM, "http://127.0.0.1:5272/v1", prism, installed_models=["phi-4-mini"]),
        EngineInfo("Ollama", OLLAMA, "http://localhost:11434/v1", ollama, installed_models=["qwen2.5-coder:7b"]),
        EngineInfo("Foundry", FOUNDRY, "http://127.0.0.1:41301/v1", foundry, installed_models=["phi-3.5-mini"]),
    ]


def router_with(*raw: dict, online=(True, True, False)) -> EngineRouter:
    router = EngineRouter(policy=RoutingPolicy(rules=rules(*raw)))
    router.list_all_engines = lambda: engines(*online)
    # explicit-engine resolution and failover call the individual discover_* methods; keep them off the network too
    router.discover_prism = lambda: engines(*online)[0]
    router.discover_ollama = lambda: engines(*online)[1]
    router.discover_foundry = lambda: engines(*online)[2]
    return router


class TestValidation(unittest.TestCase):
    def assertRejected(self, doc, fragment):
        with self.assertRaises(RoutingConfigError) as ctx:
            parse_rules(doc, "routing.json")
        self.assertIn(fragment, str(ctx.exception))
        self.assertIn("routing.json", str(ctx.exception))

    def test_errors_name_the_file_and_rule(self):
        self.assertRejected({"rules": [{"prefer": ["ollamma"]}]}, "unknown prefer ['ollamma']")
        self.assertRejected({"rules": [{"prefer": ["ollama"], "wen": {}}]}, "rule #1: unknown keys ['wen']")
        self.assertRejected({"rules": [{"when": {"taks": "test"}, "prefer": ["ollama"]}]}, "'when' must be an object")
        self.assertRejected({"rules": [{"when": {"task": "deploy"}, "prefer": ["ollama"]}]}, "unknown task")
        self.assertRejected({"rules": [{"when": {"task": "test"}}]}, "needs at least one of")
        self.assertRejected({"rules": [{"prefer": []}]}, "non-empty list")
        self.assertRejected({"rules": [{"prefer": ["prism"], "avoid": ["prism"]}]}, "both avoided and preferred")
        self.assertRejected({"rules": "x"}, "'rules' must be a list")
        self.assertRejected({"rulez": []}, "unknown keys")
        self.assertRejected([], "single 'rules' list")

    def test_second_rule_error_is_located(self):
        self.assertRejected({"rules": [{"prefer": ["ollama"]}, {"avoid": ["nope"]}]}, "rule #2")

    def test_engine_names_are_case_insensitive_and_strings_are_lists(self):
        (rule,) = rules({"when": {"task": "TEST"}, "prefer": "Ollama"})
        self.assertEqual(rule.prefer, (OLLAMA,))
        self.assertTrue(rule.matches(RouteContext(task="test")))


class TestMatchingAndSemantics(unittest.TestCase):
    def test_conditions_are_anded_and_missing_ones_are_wildcards(self):
        (rule,) = rules({"when": {"task": ["test", "review"], "profile": "coding"}, "prefer": ["ollama"]})
        self.assertTrue(rule.matches(RouteContext(task="test", profile="coding")))
        self.assertTrue(rule.matches(RouteContext(task="review")))  # profile defaults to coding
        self.assertFalse(rule.matches(RouteContext(task="code")))
        self.assertFalse(rule.matches(RouteContext(task="test", profile="fast")))
        (always,) = rules({"prefer": ["ollama"]})
        self.assertTrue(always.matches(RouteContext()))

    def test_model_condition_only_matches_an_explicit_model(self):
        (rule,) = rules({"when": {"model": "*Coder*"}, "avoid": ["prism"]})
        self.assertTrue(rule.matches(RouteContext(model="qwen2.5-coder-7b")))
        self.assertFalse(rule.matches(RouteContext(model="phi-4-mini")))
        self.assertFalse(rule.matches(RouteContext(model=None)))  # profile-derived models never match

    def test_platform_condition(self):
        (rule,) = rules({"when": {"platform": "definitely-not-this-os"}, "prefer": ["ollama"]})
        self.assertFalse(rule.matches(RouteContext()))
        (rule,) = rules({"when": {"platform": sys.platform[:3]}, "prefer": ["ollama"]})
        self.assertTrue(rule.matches(RouteContext()))

    def test_prefer_reorders_softly(self):
        (rule,) = rules({"prefer": ["foundry", "ollama"]})
        self.assertEqual(rule.apply(LINUX_ORDER), [FOUNDRY, OLLAMA, PRISM])

    def test_avoid_removes_and_only_restricts(self):
        (avoid,) = rules({"avoid": ["prism"]})
        self.assertEqual(avoid.apply(LINUX_ORDER), [OLLAMA, FOUNDRY])
        (only,) = rules({"only": ["ollama"]})
        self.assertEqual(only.apply(LINUX_ORDER), [OLLAMA])
        (both,) = rules({"prefer": ["foundry"], "only": ["foundry", "prism"], "avoid": ["ollama"]})
        self.assertEqual(both.apply(LINUX_ORDER), [FOUNDRY, PRISM])

    def test_first_matching_rule_wins(self):
        policy = RoutingPolicy(rules=rules({"when": {"task": "test"}, "prefer": ["ollama"]}, {"avoid": ["ollama"]}))
        self.assertEqual(policy.decide(LINUX_ORDER, RouteContext(task="test")).order[0], OLLAMA)
        self.assertEqual(policy.decide(LINUX_ORDER, RouteContext(task="code")).order, [PRISM, FOUNDRY])
        self.assertIsNone(RoutingPolicy().decide(LINUX_ORDER, RouteContext(task="code")).rule)
        self.assertIsNone(policy.decide(LINUX_ORDER, None).rule)


class TestLoadingAndPrecedence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.project = self.root / "proj"
        (self.project / "sub" / "deeper").mkdir(parents=True)
        (self.project / ".local-coder").mkdir()
        (self.home / ".config" / "local-coders").mkdir(parents=True)

    def write(self, path: Path, *raw: dict) -> Path:
        path.write_text(json.dumps({"rules": list(raw)}))
        return path

    def load(self, cwd=None, env=None) -> RoutingPolicy:
        return RoutingPolicy.load(cwd=cwd or self.project, env=env if env is not None else {}, home=self.home)

    def test_builtins_apply_without_files(self):
        policy = self.load()
        self.assertEqual({r.source for r in policy.rules}, {"built-in"})
        self.assertEqual(policy.files, [])
        self.assertEqual([r.index for r in policy.rules], [1])  # the only built-in exception
        self.assertIsNone(policy.decide(LINUX_ORDER, RouteContext(task="test")).rule)  # Ollama-first needs no rule
        self.assertNotIn(PRISM, policy.decide(LINUX_ORDER, RouteContext(model="qwen2.5-coder-7b")).order)
        self.assertIn(PRISM, policy.decide(LINUX_ORDER, RouteContext(model="phi-4-mini")).order)

    def test_default_order_is_ollama_first_on_every_platform(self):
        for system, expected in (("Linux", [OLLAMA, PRISM, FOUNDRY]), ("Darwin", [OLLAMA, FOUNDRY, PRISM])):
            with self.subTest(system=system), patch("local_coder.router.platform.system", return_value=system):
                self.assertEqual(EngineRouter.priority(), expected)

    def test_project_beats_user_beats_builtin(self):
        self.write(
            self.home / ".config" / "local-coders" / "routing.json", {"when": {"task": "test"}, "prefer": ["foundry"]}
        )
        project_file = self.write(
            self.project / ".local-coder" / "routing.json", {"when": {"task": "test"}, "prefer": ["prism"]}
        )
        policy = self.load()
        decision = policy.decide(LINUX_ORDER, RouteContext(task="test"))
        self.assertEqual(decision.order[0], PRISM)
        self.assertEqual(decision.rule.source, str(project_file))
        (self.project / ".local-coder" / "routing.json").unlink()
        self.assertEqual(self.load().decide(LINUX_ORDER, RouteContext(task="test")).order[0], FOUNDRY)

    def test_project_file_is_found_from_a_subdirectory(self):
        path = self.write(self.project / ".local-coder" / "routing.json", {"prefer": ["foundry"]})
        self.assertEqual(self.load(cwd=self.project / "sub" / "deeper").files, [path])

    def test_env_file_replaces_project_and_user_files(self):
        self.write(self.project / ".local-coder" / "routing.json", {"prefer": ["prism"]})
        explicit = self.write(self.root / "custom.json", {"prefer": ["foundry"]})
        policy = self.load(env={"LOCAL_CODER_ROUTING": str(explicit)})
        self.assertEqual(policy.files, [explicit])
        self.assertEqual(policy.decide(LINUX_ORDER, RouteContext(task="code")).order[0], FOUNDRY)

    def test_env_none_skips_files_and_missing_env_file_is_an_error(self):
        self.write(self.project / ".local-coder" / "routing.json", {"prefer": ["prism"]})
        self.assertEqual(self.load(env={"LOCAL_CODER_ROUTING": "none"}).files, [])
        with self.assertRaises(RoutingConfigError):
            self.load(env={"LOCAL_CODER_ROUTING": str(self.root / "missing.json")})

    def test_broken_files_fail_at_load_time(self):
        (self.project / ".local-coder" / "routing.json").write_text("{ nope")
        with self.assertRaises(RoutingConfigError) as ctx:
            self.load()
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_invalid_file_stops_client_construction(self):
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"rules": [{"prefer": ["nowhere"]}]}))
        with patch.dict(os.environ, {"LOCAL_CODER_ROUTING": str(bad)}), self.assertRaises(ValueError):
            UnifiedLocalCoderClient()


class TestRouterIntegration(unittest.TestCase):
    def test_rule_changes_the_auto_choice(self):
        router = router_with({"when": {"task": "test"}, "prefer": ["prism"]})
        with patch("local_coder.router.platform.system", return_value="Linux"):
            self.assertEqual(
                router.resolve_target_engine(EngineType.AUTO, RouteContext(task="test")).engine_type, PRISM
            )
            self.assertEqual(
                router.resolve_target_engine(EngineType.AUTO, RouteContext(task="code")).engine_type, OLLAMA
            )
        self.assertEqual(router.last_decision.rule, None)

    def test_explicit_engine_bypasses_rules(self):
        router = router_with({"avoid": ["prism"]})
        router.discover_prism = lambda: engines()[0]
        self.assertEqual(router.resolve_target_engine(EngineType.PRISM, RouteContext(task="test")).engine_type, PRISM)
        self.assertIsNone(router.last_decision)

    def test_avoid_is_hard_even_when_it_is_the_only_engine_online(self):
        router = router_with({"avoid": ["prism"], "why": "too slow"}, online=(True, False, False))
        with self.assertRaises(ConnectionError) as ctx:
            router.resolve_target_engine(EngineType.AUTO, RouteContext(task="code"))
        self.assertIn("No allowed engine is online", str(ctx.exception))
        self.assertIn("too slow", str(ctx.exception))

    def test_prefer_falls_back_when_the_preferred_engine_is_offline(self):
        router = router_with({"prefer": ["ollama"]}, online=(True, False, False))
        with patch("local_coder.router.platform.system", return_value="Linux"):
            self.assertEqual(
                router.resolve_target_engine(EngineType.AUTO, RouteContext(task="code")).engine_type, PRISM
            )

    def test_failover_never_lands_on_an_avoided_engine(self):
        router = router_with({"avoid": ["ollama"]}, online=(True, True, True))
        failed = engines()[0]
        with patch("local_coder.router.platform.system", return_value="Linux"):
            candidates = router.failover_candidates(failed, RouteContext(task="code"))
        self.assertEqual([e.engine_type for e in candidates], [FOUNDRY])

    def test_nothing_online_still_returns_the_informative_first_engine(self):
        router = router_with({"prefer": ["ollama"]}, online=(False, False, False))
        self.assertEqual(router.resolve_target_engine(EngineType.AUTO, RouteContext(task="code")).engine_type, PRISM)


class TestCooldown(unittest.TestCase):
    def test_failed_engine_is_skipped_until_the_cooldown_expires(self):
        router = router_with()
        router.cooldown_sec = 30
        with patch("local_coder.router.platform.system", return_value="Linux"):
            self.assertEqual(router.rank_online(engines())[0].engine_type, OLLAMA)
            router.mark_failed(OLLAMA)
            self.assertEqual(router.rank_online(engines())[0].engine_type, PRISM)
            with patch("local_coder.router.time.monotonic", return_value=router._failed_at[OLLAMA] + 31):
                self.assertEqual(router.rank_online(engines())[0].engine_type, OLLAMA)
            router.mark_ok(OLLAMA)
            self.assertEqual(router.rank_online(engines())[0].engine_type, OLLAMA)

    def test_everything_cooling_down_is_still_tried(self):
        router = router_with(online=(True, False, False))
        router.mark_failed(PRISM)
        self.assertEqual([e.engine_type for e in router.rank_online(engines(True, False, False))], [PRISM])


class TestClient(unittest.TestCase):
    def make_client(self, *raw: dict) -> UnifiedLocalCoderClient:
        client = UnifiedLocalCoderClient()
        client.router = router_with(*raw)
        return client

    def test_task_and_explicit_model_reach_the_router(self):
        client = self.make_client()
        seen = []
        original = client.router.resolve_target_engine

        def spy(requested, route=None):
            seen.append(route)
            return original(requested, route)

        client.router.resolve_target_engine = spy
        with patch("local_coder.client.requests.post") as post:
            post.return_value = MagicMock(status_code=200, json=lambda: {"choices": [{"message": {"content": "x"}}]})
            client.generate_tests("def f(): pass", "f.py", self_heal=False)
            client.generate_code("t", model="qwen2.5-coder-7b", self_heal=False)
        self.assertEqual((seen[0].task, seen[0].model), ("test", None))
        self.assertEqual((seen[1].task, seen[1].model), ("code", "qwen2.5-coder-7b"))

    def test_route_reason_is_announced_once_per_rule(self):
        client = self.make_client({"when": {"task": "test"}, "prefer": ["ollama"], "why": "measured"})
        err = io.StringIO()
        with patch("local_coder.router.platform.system", return_value="Linux"), redirect_stderr(err):
            client.resolve_engine_and_model(task="test")
            client.resolve_engine_and_model(task="test")
            client.resolve_engine_and_model(task="code")  # no rule matched: silent
        self.assertEqual(err.getvalue().count("[route]"), 1)
        self.assertIn("Ollama: rule #1 (test.json): measured", err.getvalue())

    def test_explicit_engine_is_never_announced(self):
        client = self.make_client({"avoid": ["ollama"]})
        client.router.discover_ollama = lambda: engines()[1]
        err = io.StringIO()
        with redirect_stderr(err):
            client.resolve_engine_and_model(engine=EngineType.OLLAMA, task="code")
        self.assertEqual(err.getvalue(), "")

    def test_failed_request_puts_the_engine_in_cooldown_and_fails_over_within_rules(self):
        import requests

        client = self.make_client()
        ok = MagicMock(status_code=200, json=lambda: {"choices": [{"message": {"content": "ok"}}]})
        with (
            patch("local_coder.router.platform.system", return_value="Linux"),
            patch("local_coder.client.requests.post", side_effect=[requests.exceptions.ConnectionError("down"), ok]),
        ):
            res = client.complete([{"role": "user", "content": "x"}], task="code")
        self.assertEqual(res.engine, "Prism")  # Ollama is first and failed; Prism is the next allowed engine
        self.assertTrue(client.router._cooling_down(OLLAMA))


class TestExplain(unittest.TestCase):
    def test_status_explain_lists_rules_and_where_each_task_goes(self):
        router = router_with(
            {"when": {"task": "review"}, "only": ["foundry"], "why": "reviews on foundry"}, online=(True, True, True)
        )
        with patch("local_coder.router.platform.system", return_value="Linux"):
            text = format_status(router, explain=True)
        self.assertIn("Routing rules (first match wins", text)
        self.assertIn("#1 [test.json]", text)
        self.assertRegex(text, r"review\s+-> Foundry")
        self.assertRegex(text, r"code\s+-> Ollama")
        self.assertNotIn("Routing rules", format_status(router))

    def test_explain_reports_when_no_allowed_engine_is_online(self):
        router = router_with({"only": ["foundry"]}, online=(True, True, False))
        text = format_status(router, explain=True)
        self.assertIn("no allowed engine online", text)


if __name__ == "__main__":
    unittest.main()
