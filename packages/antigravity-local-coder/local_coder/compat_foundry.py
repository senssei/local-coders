"""Legacy ``foundry-coder`` contract (``ask_foundry.py`` and ``foundry_mcp_server.py``) on top of ``local_coder``.

Foundry Local and Prism share the OpenAI-compatible protocol, so both scripts route to Prism when it is running
(CUDA on WSL2) and fall back to Foundry Local, starting its daemon on demand.
"""

import json
import os
from typing import Any

import requests

from .client import UnifiedLocalCoderClient
from .compat_cli import Flavor, run
from .mcp import StdioMCPServer
from .models import CompletionResult, EngineType
from .router import FOUNDRY_DAEMON_JSON

ENGINES = (EngineType.PRISM, EngineType.FOUNDRY)
DEFAULT_FALLBACK_MODEL = "phi-3.5-mini"

CODER_SYSTEM = (
    "You are an expert software engineer. Provide concise, clean, bug-free code solutions. "
    "Wrap code blocks in markdown ```language tags."
)
REVIEWER_SYSTEM = "You are a senior code reviewer. Be precise, actionable, and concise."

_client: UnifiedLocalCoderClient | None = None


def get_client() -> UnifiedLocalCoderClient:
    global _client
    if _client is None:
        _client = UnifiedLocalCoderClient()
    return _client


def discover_foundry_url(auto_start: bool = False, client: UnifiedLocalCoderClient | None = None) -> str:
    """Base URL of the engine these tools talk to: Prism if it is up, else Foundry Local.

    With nothing online, an explicit ``FOUNDRY_BASE_URL``/``PRISM_BASE_URL`` wins, then Foundry's own discovery.
    """
    router = (client or get_client()).router
    router.autostart_foundry = auto_start
    try:
        return router.resolve_target_engine(ENGINES).base_url
    except ConnectionError:
        return (
            os.environ.get("FOUNDRY_BASE_URL", "").rstrip("/")
            or os.environ.get("PRISM_BASE_URL", "").rstrip("/")
            or router.discover_foundry().base_url
        )
    finally:
        router.autostart_foundry = False


def _daemon_info() -> dict[str, Any] | None:
    if not os.path.exists(FOUNDRY_DAEMON_JSON):
        return None
    with open(FOUNDRY_DAEMON_JSON, encoding="utf-8") as f:
        return json.load(f)


def print_status(client: UnifiedLocalCoderClient) -> None:
    """``ask_foundry.py status``."""
    base_url = discover_foundry_url(client=client)
    print("=========================================================")
    print(" ⚡ Microsoft Foundry Local Diagnostic & Status")
    print("=========================================================")
    print(f"Discovered Base URL: {base_url}")
    try:
        d = _daemon_info()
        if d is None:
            print(f"Daemon Config:       Not found at {FOUNDRY_DAEMON_JSON}")
        else:
            print(f"Daemon State:        Running (PID {d.get('pid')})")
            print(f"Daemon Version:      {d.get('daemon_version')}")
            print(f"ORT Version:         {d.get('ort_version')}")
            print(f"Web URLs:            {d.get('web_urls')}")
    except Exception as e:
        print(f"Daemon Config Error: {e}")

    try:
        r = requests.get(f"{base_url}/models", timeout=3)
        if r.status_code == 200:
            models = r.json().get("data", [])
            print("HTTP Server Status:  ONLINE (200 OK)")
            print(f"Installed Models ({len(models)}):")
            for m in models:
                print(f"  - {m.get('id')}")
        else:
            print(f"HTTP Server Status:  HTTP {r.status_code}")
    except Exception as e:
        print(f"HTTP Server Status:  OFFLINE ({e})")
        print("Tip: Run 'foundry server start' to launch the daemon.")
    print("=========================================================")


FLAVOR = Flavor(
    prog="ask_foundry.py",
    description="Microsoft Foundry Local CLI automation helper with AST self-healing validation.",
    engine=ENGINES,
    review_profile="coding",
    output_style="foundry",
    autostart_foundry=True,
    status=print_status,
)


def cli_main(argv: list[str] | None = None) -> None:
    """Entry point for ``ask_foundry.py``."""
    run(FLAVOR, argv)


def stats_line(res: CompletionResult) -> str:
    return (
        f"[MS Foundry Stats: {res.model} @ {res.tokens_per_sec:.1f} tok/s in {res.duration_s:.2f}s | "
        f"Generated {res.completion_tokens} tokens, Prefill {res.prompt_tokens} tokens | "
        f"⚡ Saved {res.saved_tokens:,} cloud tokens (~${res.saved_usd:.4f})]"
    )


def call_foundry(prompt: str, model: str | None = None, system: str | None = None) -> str:
    """Complete on Prism/Foundry and return raw model text plus a stats footer; failures come back as text."""
    client = get_client()
    client.router.autostart_foundry = True
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    try:
        res = client.complete(messages, engine=ENGINES, model=model or None, profile="coding", temperature=0.1)
    except ConnectionError as e:
        return (
            f"Error: Could not connect to Microsoft Foundry Local ({e}).\n"
            f"Please ensure Foundry server is running ('foundry server start')."
        )
    except RuntimeError as e:
        return f"Foundry API error: {e}"
    except Exception as e:
        return f"Error calling Microsoft Foundry Local model '{model or DEFAULT_FALLBACK_MODEL}': {e}"
    finally:
        client.router.autostart_foundry = False
    return f"{res.content}\n\n{stats_line(res)}"


def list_tools() -> list[dict[str, Any]]:
    try:
        info = get_client().router.resolve_target_engine(ENGINES)
        default_model = info.installed_models[0] if info.installed_models else DEFAULT_FALLBACK_MODEL
    except ConnectionError:
        default_model = DEFAULT_FALLBACK_MODEL

    return [
        {
            "name": "ask_foundry_coder",
            "description": (
                f"Generate code, implement algorithms, solve bugs, or author unit tests using "
                f"Microsoft Foundry Local (ONNX Runtime GenAI). "
                f"Default model: {default_model}. Zero cloud token cost."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Specific coding task or question"},
                    "context_code": {"type": "string", "description": "Relevant code snippets or context"},
                    "model": {"type": "string", "description": f"Model alias or ID (default: {default_model})"},
                },
                "required": ["task"],
            },
        },
        {
            "name": "foundry_code_review",
            "description": (
                "Audit code for potential bugs, race conditions, memory leaks, and security "
                "vulnerabilities using Microsoft Foundry Local."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code snippet or diff to review"},
                    "focus": {
                        "type": "string",
                        "description": "Specific focus area (e.g. security, performance, edge cases)",
                        "default": "security and edge cases",
                    },
                    "model": {"type": "string", "description": "Model alias or ID"},
                },
                "required": ["code"],
            },
        },
        {
            "name": "list_foundry_models",
            "description": "List models available in the local Foundry Local (or Prism) server.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_foundry_status",
            "description": "Check Foundry Local daemon status, endpoint and connectivity.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def call_tool(name: str, args: dict[str, Any]) -> str:
    if name == "ask_foundry_coder":
        task = args.get("task", "")
        context = args.get("context_code", "")
        prompt = f"Context Code:\n```\n{context}\n```\n\nTask: {task}" if context else task
        return call_foundry(prompt, args.get("model"), CODER_SYSTEM)

    if name == "foundry_code_review":
        prompt = (
            f"Review the following code with focus on: {args.get('focus', 'security and edge cases')}.\n"
            f"Identify potential bugs, edge cases, and performance issues. Provide concrete fixes.\n\n"
            f"```\n{args.get('code', '')}\n```"
        )
        return call_foundry(prompt, args.get("model"), REVIEWER_SYSTEM)

    base_url = discover_foundry_url()

    if name == "list_foundry_models":
        try:
            r = requests.get(f"{base_url}/models", timeout=5)
            if r.status_code != 200:
                return f"Foundry returned HTTP {r.status_code}: {r.text}"
            models = r.json().get("data", [])
            if not models:
                return "No models installed in Microsoft Foundry Local."
            lines = [f"Available models in Microsoft Foundry Local ({base_url}):"]
            for m in models:
                m_id = m.get("id", "Unknown")
                parent = m.get("parent")
                alias = f" (alias: '{parent}')" if parent and parent != m_id else ""
                lines.append(f"- {m_id}{alias}")
            return "\n".join(lines)
        except requests.exceptions.ConnectionError:
            return f"Foundry daemon is not reachable at {base_url}. Start it with 'foundry server start'."
        except Exception as e:
            return f"Error querying Foundry models: {e}"

    if name == "get_foundry_status":
        info = [f"Foundry Base URL: {base_url}"]
        try:
            d = _daemon_info()
            if d is None:
                info.append("daemon.json not found at ~/.foundry/daemon.json")
            else:
                info += [
                    f"Daemon PID: {d.get('pid')}",
                    f"Daemon Version: {d.get('daemon_version')}",
                    f"ORT Version: {d.get('ort_version')}",
                    f"Web URLs: {d.get('web_urls')}",
                ]
        except Exception as e:
            info.append(f"Could not read daemon.json: {e}")
        try:
            r = requests.get(f"{base_url}/models", timeout=3)
            info.append(f"HTTP Ping: {'Active (200 OK)' if r.status_code == 200 else f'HTTP {r.status_code}'}")
        except Exception as e:
            info.append(f"HTTP Ping: Failed ({e})")
        return "\n".join(info)

    return f"Unknown tool: {name}"


server = StdioMCPServer("foundry-local-mcp", "1.0.0", list_tools, call_tool)


def mcp_main() -> None:
    """Entry point for ``foundry_mcp_server.py``."""
    server.serve()
