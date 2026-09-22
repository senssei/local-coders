"""Hermetic fake of a Prism HTTP server.

Spins up a real ``http.server.HTTPServer`` on a free loopback port and lets the test script the
response for each endpoint (``/v1/models`` and ``/v1/chat/completions``). The fake mirrors the shape
of the newest Prism checked out at ``../03-foundy-local/prism/`` — ``_handle_list_models`` and
``_handle_chat_completions`` from ``prism.server``. Imports are pinned against the live reference so a
Prism API change fails the suite loudly instead of silently passing on a stale contract.

Only the tests in ``tests/test_prism_engine.py`` import from here; the gate stays hermetic and the
fake is never reached at runtime in production.
"""

import json
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRISM_REPO_CANDIDATE = os.path.normpath(os.path.join(REPO_ROOT, "..", "03-foundy-local"))


def has_live_prism_reference() -> bool:
    """``True`` iff the live Prism module is importable from ``../03-foundy-local``.

    Used by the test suite to fail loudly when the API pin (the shape of ``/v1/models`` and
    ``/v1/chat/completions``) cannot be checked against the actual implementation. A missing pin is
    treated as a configuration error, not an excuse to skip silently.
    """
    if os.path.isdir(PRISM_REPO_CANDIDATE) and PRISM_REPO_CANDIDATE not in sys.path:
        sys.path.insert(0, PRISM_REPO_CANDIDATE)
    try:
        import prism  # noqa: F401
    except Exception:
        return False
    return True


class PrismFake:
    """In-process Prism HTTP server bound to a free loopback port.

    Each test starts the server in ``setUpClass``, scripts the responses it cares about, then runs
    the production code against ``self.base_url``. ``reset()`` clears scripted responses so the next
    test in the same class starts clean.

    Routes supported (the only ones ``local_coder/`` actually hits):

    * ``GET  /v1/models``           — returns the last ``script_models(...)`` payload, or a
      ``script_status_code(...)`` override, or an empty list when nothing is scripted.
    * ``POST /v1/chat/completions`` — returns the next ``script_chat_completion(...)`` /
      ``script_chat_completion_status(...)`` entry from a FIFO queue (so a single test can script
      both halves of a retry-on-truncation scenario).
    * ``GET  /health`` / ``/v1/health`` / ``/v1/status`` — return ``{"status": "ok"}`` so ``curl``
      style probes do not error.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self._requested_port = port
        self._chat_queue: queue.Queue = queue.Queue()
        self._models_payload: dict | None = None
        self._models_status: int | None = None
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle --------------------------------------------------

    @classmethod
    def from_reference(cls) -> "PrismFake":
        """Build a fake after confirming the live Prism module is importable."""
        if not has_live_prism_reference():
            raise RuntimeError(
                "newest Prism is not importable from ../03-foundy-local (or PYTHONPATH); the API pin cannot be checked."
            )
        return cls()

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("PrismFake is not started")
        return f"http://{self.host}:{self._server.server_address[1]}/v1"

    def start(self) -> None:
        self._server = _FakePrismServer((self.host, self._requested_port), _FakeHandler, self)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    def reset(self) -> None:
        """Drop every scripted response. Called from ``setUp`` so tests do not leak state."""
        with self._chat_queue.mutex:
            self._chat_queue.queue.clear()
        self._models_payload = None
        self._models_status = None

    # ---- response scripting ----------------------------------------

    def script_models(self, models: list[dict]) -> None:
        """Queue a 200 response with ``{"object": "list", "data": models}`` for ``GET /v1/models``."""
        self._models_payload = {"object": "list", "data": models}
        self._models_status = 200

    def script_status_code(self, code: int) -> None:
        """Queue a non-200 response for ``GET /v1/models`` (the body is a generic error envelope)."""
        self._models_status = code
        self._models_payload = None

    def script_chat_completion(self, payload: dict) -> None:
        """Queue a 200 chat-completion response for the next ``POST /v1/chat/completions``."""
        self._chat_queue.put((200, payload))

    def script_chat_completion_status(self, code: int, body: dict | None = None) -> None:
        """Queue an error response (e.g. 404 model_not_found, 503 server_busy) for the next chat request."""
        if body is None:
            body = {"error": {"message": f"fake error {code}", "type": "server_error", "code": "fake_error"}}
        self._chat_queue.put((code, body))


class _FakePrismServer(HTTPServer):
    allow_reuse_address = True

    def __init__(self, addr, handler_cls, fake: PrismFake) -> None:
        super().__init__(addr, handler_cls)
        # Bind the fake to the handler class so do_GET/do_POST can reach its scriptable state.
        handler_cls.fake = fake


class _FakeHandler(BaseHTTPRequestHandler):
    # Populated by _FakePrismServer.__init__.
    fake: PrismFake

    # Silence the access log; the test stderr stays clean.
    def log_message(self, format, *args):  # noqa: A002 - signature dictated by stdlib
        return

    # ---- routing ----------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - signature dictated by stdlib
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/v1/models":
            self._send_models()
            return
        if path in ("/health", "/v1/health", "/v1/status"):
            self._send_json(200, {"status": "ok", "active_model": None, "active_device": None})
            return
        self._send_json(
            404,
            {"error": {"message": f"Unknown route {path}", "type": "not_found_error", "code": "not_found"}},
        )

    def do_POST(self) -> None:  # noqa: N802 - signature dictated by stdlib
        # Drain the request body so the connection can close cleanly. We do not assert on it here;
        # the production code already covers payload shape, and Prism's body shape is exercised by
        # the live server in integration tests (out of scope for the hermetic suite).
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/v1/chat/completions":
            self._send_chat_completion()
            return
        if path == "/v1/embeddings":
            # Prism itself refuses ONNX embeddings with a 400; mirror that behaviour so the production
            # client sees a clean RuntimeError instead of a 404 it cannot parse.
            self._send_json(
                400,
                {
                    "error": {
                        "message": "ONNX models do not produce embeddings",
                        "type": "invalid_request_error",
                        "code": "embeddings_not_supported",
                    }
                },
            )
            return
        self._send_json(
            404,
            {"error": {"message": f"Unknown route {path}", "type": "not_found_error", "code": "not_found"}},
        )

    # ---- response builders -----------------------------------------

    def _send_models(self) -> None:
        if self.fake._models_status is None:
            # Default: empty list with 200 (Prism returns the same shape when no models are loaded).
            self._send_json(200, {"object": "list", "data": []})
            return
        if self.fake._models_status != 200:
            self._send_json(
                self.fake._models_status,
                {
                    "error": {
                        "message": f"fake {self.fake._models_status}",
                        "type": "server_error",
                        "code": "fake_error",
                    }
                },
            )
            return
        self._send_json(200, self.fake._models_payload or {"object": "list", "data": []})

    def _send_chat_completion(self) -> None:
        try:
            status, payload = self.fake._chat_queue.get_nowait()
        except queue.Empty:
            self._send_json(
                500,
                {
                    "error": {
                        "message": "PrismFake: no scripted /v1/chat/completions response (test bug)",
                        "type": "server_error",
                        "code": "fake_misconfigured",
                    }
                },
            )
            return
        self._send_json(status, payload)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
