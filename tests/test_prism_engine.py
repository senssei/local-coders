"""Hermetic end-to-end tests for the Prism code paths in ``local_coder/``.

The test class spins up a real ``http.server.HTTPServer`` on a free loopback port, points the engine
discovery at it via ``PRISM_BASE_URL``, and runs the production code paths against it. No real Prism,
no network, no GPU, no ``$HOME`` (``tests/conftest.py`` already isolates routing files, the discovery
cache and the perf state file).

Coverage:

* ``EngineRouter.discover_prism`` — online (200 with models + aliases), offline (5xx), connection refused.
* ``UnifiedLocalCoderClient.complete`` — chat completion happy path, 404 ``ModelNotInstalledError``,
  400/503 ``RuntimeError``, retry-on-truncation (``_complete_extendable`` doubles the limit once).

The fake (``tests.fakes.prism_fake``) mirrors the API of the newest Prism checked out at
``../03-foundy-local/prism/``. If the live Prism module cannot be imported (path layout change, moved
checkout) ``setUpClass`` raises a plain ``RuntimeError`` so the gate fails loudly instead of silently
skipping.

The ``from tests.fakes.prism_fake import …`` line lives inside ``setUpClass`` so the test class
**collects** even when the fake does not exist yet — that is the form ``sdlc_check.py --red`` requires
(it exits 1 on collection errors and only exits 0 when the test fails for the right runtime reason).
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from local_coder.client import ModelNotInstalledError, UnifiedLocalCoderClient  # noqa: E402
from local_coder.router import EngineRouter  # noqa: E402


class TestPrismEngine(unittest.TestCase):
    """End-to-end Prism coverage against a fake HTTP server bound to localhost."""

    @classmethod
    def setUpClass(cls) -> None:
        # Imported here so the class collects even when the fake is not implemented yet;
        # an ImportError at this point becomes a setUpClass error, which pytest surfaces as
        # an error (red) on every test in the class.
        from tests.fakes.prism_fake import PrismFake, has_live_prism_reference

        if not has_live_prism_reference():
            raise RuntimeError(
                "newest Prism is not importable from ../03-foundy-local (or PYTHONPATH): "
                "the API pin cannot be checked, so the hermetic suite is unsafe to run."
            )
        cls.fake = PrismFake.from_reference()
        cls.fake.start()
        cls._base_url = cls.fake.base_url
        os.environ["PRISM_BASE_URL"] = cls._base_url

    @classmethod
    def tearDownClass(cls) -> None:
        # `fake` may not exist if setUpClass raised mid-way.
        fake = getattr(cls, "fake", None)
        if fake is not None:
            fake.stop()

    def setUp(self) -> None:
        EngineRouter().invalidate_discovery()
        # ``test_discover_prism_offline_when_unreachable`` calls ``self.fake.stop()``/``start()``
        # to simulate the server going away; that cycle picks a fresh port, so the env var
        # has to be re-pinned to whatever the fake is bound to *now*.
        os.environ["PRISM_BASE_URL"] = self.fake.base_url
        self.fake.reset()

    # -------------------------------------------------------------------- discover_prism

    def test_discover_prism_online_lists_models_and_aliases(self) -> None:
        """A 200 /v1/models reply populates ``installed_models`` and the ``id → id`` alias map.

        Prism itself does not emit ``parent`` (Foundry does), so the alias map is the identity
        mapping on the model ids — this test pins the Prism shape against accidental changes.
        """
        self.fake.script_models(
            [
                {
                    "id": "phi-4-mini",
                    "object": "model",
                    "created": 1,
                    "owned_by": "prism",
                    "size_mb": 8000,
                    "device": "cuda",
                },
                {
                    "id": "qwen3-0.6b",
                    "object": "model",
                    "created": 1,
                    "owned_by": "prism",
                    "size_mb": 500,
                    "device": "cuda",
                },
            ]
        )
        router = EngineRouter()
        info = router.discover_prism()
        self.assertTrue(info.is_online, "discover_prism must report online when /v1/models returns 200")
        self.assertEqual(info.installed_models, ["phi-4-mini", "qwen3-0.6b"])
        # Alias map is keyed by lowercased id; each value is the id itself until Prism starts
        # emitting `parent` (Foundry-only field, present here only to keep the parser honest).
        self.assertEqual(info.model_aliases.get("phi-4-mini"), "phi-4-mini")
        self.assertEqual(info.model_aliases.get("qwen3-0.6b"), "qwen3-0.6b")

    def test_discover_prism_offline_when_5xx(self) -> None:
        """A 5xx /v1/models reply makes discover_prism report offline with no models parsed."""
        self.fake.script_status_code(500)
        info = EngineRouter().discover_prism()
        self.assertFalse(info.is_online)
        self.assertEqual(info.installed_models, [])

    def test_discover_prism_offline_when_unreachable(self) -> None:
        """When the server is down entirely, discover_prism still returns an EngineInfo (offline)."""
        # First hit it while up so we exercise the online path, then stop the server.
        EngineRouter().discover_prism()
        self.fake.stop()
        try:
            offline = EngineRouter().discover_prism()
            self.assertFalse(offline.is_online)
            self.assertEqual(offline.installed_models, [])
        finally:
            self.fake.start()

    # -------------------------------------------------------------------- complete()

    def test_complete_non_stream_extracts_content(self) -> None:
        """A normal /v1/chat/completions reply becomes a CompletionResult with content and tokens."""
        self.fake.script_models([{"id": "phi-4-mini", "object": "model"}])
        self.fake.script_chat_completion(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "phi-4-mini",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hello world"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            }
        )
        client = UnifiedLocalCoderClient(default_engine="prism")
        with patch.object(client, "_model_for_profile", return_value="phi-4-mini"):
            res = client.complete([{"role": "user", "content": "say hi"}], engine="prism", profile="coding")
        self.assertEqual(res.content, "hello world")
        self.assertEqual(res.model, "phi-4-mini")
        self.assertEqual(res.engine, "Prism")
        self.assertEqual(res.finish_reason, "stop")
        self.assertFalse(res.truncated, "finish_reason=stop must not be marked truncated")

    def test_complete_404_raises_model_not_installed(self) -> None:
        """A 404 with 'not found' in the body becomes ``ModelNotInstalledError`` (not a bare RuntimeError)."""
        self.fake.script_chat_completion_status(
            404,
            body={
                "error": {
                    "message": "Model 'phi-4-mini' not found",
                    "type": "not_found_error",
                    "code": "model_not_found",
                }
            },
        )
        client = UnifiedLocalCoderClient(default_engine="prism")
        with patch.object(client, "_model_for_profile", return_value="phi-4-mini"):
            with self.assertRaises(ModelNotInstalledError):
                client.complete([{"role": "user", "content": "x"}], engine="prism", profile="coding")

    def test_complete_503_raises_runtime_error_with_engine_message(self) -> None:
        """A 503 with Prism's error envelope becomes a RuntimeError carrying the engine's message."""
        self.fake.script_chat_completion_status(
            503,
            body={"error": {"message": "Server busy: queue full", "type": "server_error", "code": "server_busy"}},
        )
        client = UnifiedLocalCoderClient(default_engine="prism")
        with patch.object(client, "_model_for_profile", return_value="phi-4-mini"):
            with self.assertRaises(RuntimeError) as ctx:
                client.complete([{"role": "user", "content": "x"}], engine="prism", profile="coding")
        # The message body from the fake ends up in the exception text (it is a server_error, not a 404).
        self.assertIn("Server busy", str(ctx.exception))

    # -------------------------------------------------------------------- truncation retry

    def test_complete_extendable_retries_when_truncated(self) -> None:
        """When the first reply carries ``finish_reason=length`` and the caller did not set max_tokens,
        ``_complete_extendable`` retries once with a doubled limit and returns the longer answer."""
        self.fake.script_chat_completion(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "phi-4-mini",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "short"}, "finish_reason": "length"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            }
        )
        self.fake.script_chat_completion(
            {
                "id": "chatcmpl-2",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "phi-4-mini",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "long answer"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        )
        client = UnifiedLocalCoderClient(default_engine="prism")
        with patch.object(client, "_model_for_profile", return_value="phi-4-mini"):
            res, budget = client._complete_extendable(
                [{"role": "user", "content": "x"}],
                max_tokens=None,
                engine="prism",
                profile="coding",
            )
        self.assertEqual(res.content, "long answer")
        self.assertFalse(res.truncated)
        self.assertGreater(budget, 4096, "retry budget must be larger than the default 4096")


if __name__ == "__main__":
    unittest.main()
