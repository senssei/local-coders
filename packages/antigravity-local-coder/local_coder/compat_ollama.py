"""Legacy ``ollama-coder`` contract (``ask_local.py`` and ``ollama_mcp_server.py``) on top of ``local_coder``."""

import os
from typing import Any

import requests

from .client import UnifiedLocalCoderClient
from .compat_cli import Flavor, run
from .mcp import StdioMCPServer
from .models import CompletionResult, EngineType
from .router import normalize_ollama_host

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5-coder:7b")

CODER_SYSTEM = (
    "You are an expert software engineer. Provide concise, clean, bug-free code solutions. "
    "Wrap code blocks in markdown ```language tags."
)
REVIEWER_SYSTEM = "You are a senior code reviewer. Be precise, actionable, and concise."

FLAVOR = Flavor(
    prog="ask_local.py",
    description="Local Coder CLI - Offload coding, testing, and review to local Ollama models with zero token cost.",
    engine=EngineType.OLLAMA,
    review_profile="reasoning",
    output_style="ollama",
)

_client: UnifiedLocalCoderClient | None = None


def get_client() -> UnifiedLocalCoderClient:
    global _client
    if _client is None:
        _client = UnifiedLocalCoderClient()
    return _client


def cli_main(argv: list[str] | None = None) -> None:
    """Entry point for ``ask_local.py``."""
    run(FLAVOR, argv)


def stats_line(res: CompletionResult) -> str:
    return (
        f"[Local LLM Stats: {res.model} @ {res.tokens_per_sec:.1f} tok/s, {res.completion_tokens} tokens generated | "
        f"⚡ Saved {res.saved_tokens:,} cloud tokens (~${res.saved_usd:.4f})]"
    )


def call_ollama(messages: list[dict[str, str]], model: str) -> str:
    """Complete on Ollama and return raw model text plus a stats footer; failures come back as text."""
    try:
        res = get_client().complete(messages, engine=EngineType.OLLAMA, model=model, temperature=0.1)
    except Exception as e:
        return f"Error calling local Ollama model {model}: {e}"
    return f"{res.content}\n\n{stats_line(res)}"


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "ask_local_coder",
            "description": (
                f"Generate code, algorithms, bug fixes, or unit tests using local LLM model "
                f"({DEFAULT_MODEL} with local GPU / Apple Silicon Metal acceleration). Zero cloud token cost."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Specific coding task or question"},
                    "context_code": {
                        "type": "string",
                        "description": "Relevant code snippets or context files to consider",
                    },
                    "model": {
                        "type": "string",
                        "description": f"Model to use (default: {DEFAULT_MODEL})",
                        "default": DEFAULT_MODEL,
                    },
                },
                "required": ["task"],
            },
        },
        {
            "name": "local_code_review",
            "description": "Perform fast static code review and find potential bugs using local model.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code snippet or diff to review"},
                    "focus": {
                        "type": "string",
                        "description": "Specific focus area (e.g. security, performance, edge cases)",
                        "default": "general bugs and edge cases",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "list_local_models",
            "description": "List available local models in Ollama and their sizes/status.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def call_tool(name: str, args: dict[str, Any]) -> str:
    if name == "ask_local_coder":
        task = args.get("task", "")
        context = args.get("context_code", "")
        prompt = f"Context Code:\n```\n{context}\n```\n\nTask: {task}" if context else task
        messages = [{"role": "system", "content": CODER_SYSTEM}, {"role": "user", "content": prompt}]
        return call_ollama(messages, args.get("model", DEFAULT_MODEL))

    if name == "local_code_review":
        code = args.get("code", "")
        focus = args.get("focus", "bugs and edge cases")
        prompt = (
            f"Review the following code with focus on: {focus}.\n"
            f"Identify potential bugs, edge cases, and performance issues. Provide concrete fixes.\n\n"
            f"```\n{code}\n```"
        )
        messages = [{"role": "system", "content": REVIEWER_SYSTEM}, {"role": "user", "content": prompt}]
        return call_ollama(messages, DEFAULT_MODEL)

    if name == "list_local_models":
        host, _ = normalize_ollama_host(os.environ.get("OLLAMA_HOST"))
        try:
            r = requests.get(f"{host}/api/tags", timeout=5)
            if r.status_code == 200:
                lines = ["Available local models on Ollama:"]
                for m in r.json().get("models", []):
                    lines.append(f"- {m.get('name')} ({m.get('size', 0) / (1024**3):.1f} GB)")
                return "\n".join(lines)
        except Exception as e:
            return f"Error listing models: {e}"
        return "No models found."

    return f"Unknown tool: {name}"


server = StdioMCPServer("ollama-local-mcp", "1.0.0", list_tools, call_tool)


def mcp_main() -> None:
    """Entry point for ``ollama_mcp_server.py``."""
    server.serve()
